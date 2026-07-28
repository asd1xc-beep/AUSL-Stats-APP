"""Private, versioned producer-session persistence for Phase 6D.

The module is GUI-free and network-free. It accepts only primitive JSON data,
reconstructs canonical Phase 6B/6C models through their validation paths, and
uses same-directory atomic replacement so a failed save cannot damage the
last-known-good producer session.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ausl_facts import (
    BroadcastFact,
    FactCategory,
    FactSubjectType,
    SourceProvenance,
    VerificationState,
)
from ausl_rundown import (
    RUNDOWN_SCHEMA_VERSION,
    GameRundownState,
    PinnedFactEntry,
    ReconciliationState,
    RundownMutationError,
    UsedFactRecord,
    validate_break_target,
)


SESSION_SCHEMA_VERSION = 1
SESSION_FILENAME = "producer_session.json"
SESSION_BACKUP_FILENAME = "producer_session.backup.json"
SESSION_TEMP_PREFIX = ".producer-session-"
SESSION_TEMP_SUFFIX = ".tmp"
MAX_SESSION_BYTES = 5 * 1024 * 1024
MAX_RUNDOWN_STATES = 64
MAX_ENTRIES_PER_GAME = 250
MAX_USED_PER_GAME = 500
MAX_PROVENANCE_ITEMS = 32
MAX_STRING_LENGTH = 16_384
_GAME_ID_RE = re.compile(r"\d+")
_TEAM_CODE_RE = re.compile(r"[A-Z0-9]{2,12}")


class SessionValidationError(ValueError):
    """Raised when untrusted persisted state does not satisfy the v1 schema."""


class SessionLifecycle(str, Enum):
    ACTIVE = "active"
    CLOSED_CLEANLY = "closed_cleanly"


class SessionLoadStatus(str, Enum):
    EMPTY = "empty"
    RESUME = "resume"
    RECOVERED = "recovered"
    BACKUP_RECOVERED = "backup_recovered"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GameIdentity:
    game_id: str
    season: int
    away_team_code: str
    home_team_code: str

    def __post_init__(self):
        object.__setattr__(self, "game_id", _game_id(self.game_id))
        if isinstance(self.season, bool) or not isinstance(self.season, int):
            raise SessionValidationError("Selected-game season must be an integer")
        if self.season < 2000 or self.season > 2200:
            raise SessionValidationError("Selected-game season is outside safe limits")
        object.__setattr__(
            self, "away_team_code", _team_code(self.away_team_code, "away")
        )
        object.__setattr__(
            self, "home_team_code", _team_code(self.home_team_code, "home")
        )
        if self.away_team_code == self.home_team_code:
            raise SessionValidationError("Selected-game teams must be different")


@dataclass(frozen=True)
class SessionUIState:
    main_tab: str = "Game Day"
    game_day_view: str = "Readiness"
    fact_status_filter: str = "Air Ready"
    fact_team_filter: str = "Both teams"
    fact_category_filter: str = "All categories"
    fact_template_profile: str = "60 — one line"
    show_used: bool = False
    selected_player_id: str | None = None
    fact_scroll_fraction: float = 0.0
    rundown_scroll_fraction: float = 0.0
    prior_offline_mode: bool = False

    def __post_init__(self):
        for name in (
            "main_tab",
            "game_day_view",
            "fact_status_filter",
            "fact_team_filter",
            "fact_category_filter",
            "fact_template_profile",
        ):
            object.__setattr__(self, name, _string(getattr(self, name), name))
        if not isinstance(self.show_used, bool):
            raise SessionValidationError("show_used must be Boolean")
        if not isinstance(self.prior_offline_mode, bool):
            raise SessionValidationError("prior_offline_mode must be Boolean")
        if self.selected_player_id is not None:
            player = _string(self.selected_player_id, "selected_player_id")
            object.__setattr__(self, "selected_player_id", player or None)
        for name in ("fact_scroll_fraction", "rundown_scroll_fraction"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SessionValidationError(f"{name} scroll value must be numeric")
            normalized = float(value)
            if normalized < 0.0 or normalized > 1.0:
                raise SessionValidationError(f"{name} scroll value must be 0 through 1")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True)
class SessionSnapshot:
    schema_version: int
    session_id: str
    created_at: datetime
    updated_at: datetime
    lifecycle: SessionLifecycle
    selected_game: GameIdentity | None = None
    rundown_states: tuple[GameRundownState, ...] = ()
    ui_state: SessionUIState = field(default_factory=SessionUIState)

    def __post_init__(self):
        if self.schema_version != SESSION_SCHEMA_VERSION:
            raise SessionValidationError(
                f"Unsupported session schema_version {self.schema_version}"
            )
        object.__setattr__(self, "session_id", _string(self.session_id, "session_id"))
        if not self.session_id:
            raise SessionValidationError("session_id is required")
        created = _aware_utc(self.created_at, "created_at")
        updated = _aware_utc(self.updated_at, "updated_at")
        if updated < created:
            raise SessionValidationError("updated_at cannot be before created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        try:
            lifecycle = SessionLifecycle(self.lifecycle)
        except (TypeError, ValueError) as exc:
            raise SessionValidationError("Unknown session lifecycle") from exc
        object.__setattr__(self, "lifecycle", lifecycle)
        if self.selected_game is not None and not isinstance(
            self.selected_game, GameIdentity
        ):
            raise SessionValidationError("selected_game must be an exact identity")
        states = tuple(self.rundown_states)
        if len(states) > MAX_RUNDOWN_STATES:
            raise SessionValidationError("Rundown state count exceeds safe limit")
        seen: set[str] = set()
        for state in states:
            if not isinstance(state, GameRundownState):
                raise SessionValidationError("rundown_states contains an invalid state")
            if state.game_id in seen:
                raise SessionValidationError(
                    f"Duplicate rundown state for Game {state.game_id}"
                )
            seen.add(state.game_id)
        object.__setattr__(
            self, "rundown_states", tuple(sorted(states, key=lambda item: int(item.game_id)))
        )
        if not isinstance(self.ui_state, SessionUIState):
            raise SessionValidationError("ui_state is invalid")

    @classmethod
    def new(
        cls,
        *,
        now: datetime | None = None,
        session_id: str | None = None,
    ) -> "SessionSnapshot":
        timestamp = _aware_utc(now or datetime.now(timezone.utc), "now")
        return cls(
            schema_version=SESSION_SCHEMA_VERSION,
            session_id=session_id or f"session-{uuid.uuid4().hex}",
            created_at=timestamp,
            updated_at=timestamp,
            lifecycle=SessionLifecycle.ACTIVE,
        )


@dataclass(frozen=True)
class SessionSaveResult:
    saved: bool
    path: Path
    generation: int
    error: str = ""
    superseded: bool = False


@dataclass(frozen=True)
class SessionLoadResult:
    status: SessionLoadStatus
    snapshot: SessionSnapshot | None
    message: str
    source_path: Path | None = None
    quarantine_path: Path | None = None


def session_state_dir(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | str | None = None,
) -> Path:
    """Return an injectable per-user state directory outside the repository."""

    values = os.environ if environ is None else environ
    platform_value = sys.platform if platform_name is None else platform_name
    home_path = Path.home() if home is None else Path(home)
    if platform_value.startswith("win"):
        base = Path(values.get("LOCALAPPDATA") or home_path / "AppData" / "Local")
    else:
        base = Path(values.get("XDG_STATE_HOME") or home_path / ".local" / "state")
    return base / "AUSL Broadcast Stats"


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SessionValidationError(f"{label} must be text")
    if len(value) > MAX_STRING_LENGTH:
        raise SessionValidationError(f"{label} exceeds safe string limit")
    if not allow_empty and not value.strip():
        raise SessionValidationError(f"{label} is required")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label, allow_empty=True) or None


def _game_id(value: Any) -> str:
    result = _string(value, "game_id")
    if not _GAME_ID_RE.fullmatch(result):
        raise SessionValidationError("game_id must be an exact official numeric ID")
    return result


def _team_code(value: Any, label: str) -> str:
    result = _string(value, f"{label}_team_code").upper()
    if not _TEAM_CODE_RE.fullmatch(result):
        raise SessionValidationError(f"{label}_team_code is invalid")
    return result


def _aware_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SessionValidationError(f"{label} timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionValidationError(f"{label} timestamp is invalid") from exc
    return _aware_utc(parsed, label)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SessionValidationError(f"{label} must be an object")
    return value


def _list(value: Any, label: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise SessionValidationError(f"{label} must be a list")
    if len(value) > limit:
        raise SessionValidationError(f"{label} exceeds safe limit")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionValidationError(f"{label} must be an integer")
    if value < minimum:
        raise SessionValidationError(f"{label} is outside safe limits")
    return value


def _fact_from_dict(value: Any, label: str) -> BroadcastFact:
    data = _mapping(value, label)
    provenance = []
    for index, raw in enumerate(
        _list(data.get("provenance", []), f"{label}.provenance", MAX_PROVENANCE_ITEMS)
    ):
        source = _mapping(raw, f"{label}.provenance[{index}]")
        try:
            provenance.append(
                SourceProvenance(
                    source_name=_string(
                        source.get("source_name"), "provenance.source_name"
                    ),
                    source_reference=_string(
                        source.get("source_reference"),
                        "provenance.source_reference",
                    ),
                    source_date=_optional_string(
                        source.get("source_date"), "provenance.source_date"
                    ),
                    source_page=_optional_string(
                        source.get("source_page"), "provenance.source_page"
                    ),
                    source_game_id=_optional_string(
                        source.get("source_game_id"), "provenance.source_game_id"
                    ),
                    snapshot_timestamp=_optional_string(
                        source.get("snapshot_timestamp"),
                        "provenance.snapshot_timestamp",
                    ),
                    parser_version=_optional_string(
                        source.get("parser_version"), "provenance.parser_version"
                    ),
                    approval_record_id=_optional_string(
                        source.get("approval_record_id"),
                        "provenance.approval_record_id",
                    ),
                    source_record_id=_optional_string(
                        source.get("source_record_id"),
                        "provenance.source_record_id",
                    ),
                )
            )
        except TypeError as exc:
            raise SessionValidationError(f"{label} provenance is invalid") from exc
    raw_evidence = _list(data.get("evidence", []), f"{label}.evidence", 128)
    evidence: list[tuple[str, str]] = []
    for index, item in enumerate(raw_evidence):
        if not isinstance(item, list) or len(item) != 2:
            raise SessionValidationError(f"{label}.evidence[{index}] is invalid")
        evidence.append(
            (
                _string(item[0], "evidence key", allow_empty=True),
                _string(item[1], "evidence value", allow_empty=True),
            )
        )
    try:
        return BroadcastFact(
            category=FactCategory(data.get("category")),
            subject_type=FactSubjectType(data.get("subject_type")),
            subject_id=_string(data.get("subject_id"), "fact subject_id"),
            season=_integer(data.get("season"), "fact season", minimum=2000),
            selected_game_id=_optional_string(
                data.get("selected_game_id"), "fact selected_game_id"
            ),
            source_record_identity=_string(
                data.get("source_record_identity"), "fact source_record_identity"
            ),
            concept_key=_string(data.get("concept_key"), "fact concept_key"),
            headline=_string(data.get("headline"), "fact headline"),
            air_copy=_string(data.get("air_copy"), "fact air_copy"),
            supporting_context=_string(
                data.get("supporting_context", ""),
                "fact supporting_context",
                allow_empty=True,
            ),
            subject_display_name=_string(
                data.get("subject_display_name"),
                "fact subject_display_name",
                allow_empty=True,
            ),
            team_code=_optional_string(data.get("team_code"), "fact team_code"),
            team_display_name=_optional_string(
                data.get("team_display_name"), "fact team_display_name"
            ),
            opponent_context=_optional_string(
                data.get("opponent_context"), "fact opponent_context"
            ),
            provenance=tuple(provenance),
            verification_state=VerificationState(data.get("verification_state")),
            source_health=_string(data.get("source_health"), "fact source_health"),
            producer_confirmation_required=_boolean(
                data.get("producer_confirmation_required"),
                "fact producer_confirmation_required",
            ),
            warning_reason=_string(
                data.get("warning_reason", ""),
                "fact warning_reason",
                allow_empty=True,
            ),
            readiness_blocking=_boolean(
                data.get("readiness_blocking"), "fact readiness_blocking"
            ),
            evidence=tuple(evidence),
            template_profile=_string(
                data.get("template_profile", "one_line"), "fact template_profile"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise SessionValidationError(f"{label} is not a valid canonical fact: {exc}") from exc


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SessionValidationError(f"{label} must be Boolean")
    return value


def _entry_from_dict(value: Any, label: str) -> PinnedFactEntry:
    data = _mapping(value, label)
    fact = _fact_from_dict(data.get("fact_snapshot"), f"{label}.fact_snapshot")
    fact_id = _string(data.get("fact_id"), f"{label}.fact_id")
    evidence_hash = _string(data.get("evidence_hash"), f"{label}.evidence_hash")
    if fact_id != fact.fact_id:
        raise SessionValidationError(f"{label} fact identity does not match snapshot")
    if evidence_hash != fact.evidence_hash:
        raise SessionValidationError(f"{label} evidence hash does not match snapshot")
    latest_raw = data.get("latest_fact")
    latest = (
        _fact_from_dict(latest_raw, f"{label}.latest_fact")
        if latest_raw is not None
        else None
    )
    try:
        return PinnedFactEntry(
            entry_id=_string(data.get("entry_id"), f"{label}.entry_id"),
            game_id=_game_id(data.get("game_id")),
            fact_id=fact_id,
            evidence_hash=evidence_hash,
            fact_snapshot=fact,
            position=_integer(data.get("position"), f"{label}.position", minimum=1),
            pinned_at=_parse_timestamp(data.get("pinned_at"), f"{label}.pinned_at"),
            verification_state_at_pin=VerificationState(
                data.get("verification_state_at_pin")
            ),
            reconciliation_state=ReconciliationState(
                data.get("reconciliation_state", ReconciliationState.CURRENT.value)
            ),
            used_on_air_at=(
                _parse_timestamp(data.get("used_on_air_at"), f"{label}.used_on_air_at")
                if data.get("used_on_air_at") is not None
                else None
            ),
            warning_reason=_string(
                data.get("warning_reason", ""),
                f"{label}.warning_reason",
                allow_empty=True,
            ),
            latest_fact=latest,
        )
    except (TypeError, ValueError) as exc:
        raise SessionValidationError(f"{label} is invalid: {exc}") from exc


def _used_from_dict(value: Any, label: str) -> UsedFactRecord:
    data = _mapping(value, label)
    fact = _fact_from_dict(data.get("fact_snapshot"), f"{label}.fact_snapshot")
    fact_id = _string(data.get("fact_id"), f"{label}.fact_id")
    evidence_hash = _string(data.get("evidence_hash"), f"{label}.evidence_hash")
    if fact_id != fact.fact_id:
        raise SessionValidationError(f"{label} fact identity does not match snapshot")
    if evidence_hash != fact.evidence_hash:
        raise SessionValidationError(f"{label} evidence hash does not match snapshot")
    entry_raw = data.get("entry_snapshot")
    original_position = data.get("original_position")
    if original_position is not None:
        original_position = _integer(
            original_position, f"{label}.original_position", minimum=1
        )
    return UsedFactRecord(
        game_id=_game_id(data.get("game_id")),
        fact_id=fact_id,
        evidence_hash=evidence_hash,
        fact_snapshot=fact,
        used_at=_parse_timestamp(data.get("used_at"), f"{label}.used_at"),
        from_queue=_boolean(data.get("from_queue"), f"{label}.from_queue"),
        original_position=original_position,
        entry_snapshot=(
            _entry_from_dict(entry_raw, f"{label}.entry_snapshot")
            if entry_raw is not None
            else None
        ),
    )


def _state_from_dict(value: Any, label: str) -> GameRundownState:
    data = _mapping(value, label)
    if data.get("schema_version") != RUNDOWN_SCHEMA_VERSION:
        raise SessionValidationError(f"{label} has unsupported rundown schema")
    game_id = _game_id(data.get("game_id"))
    entries = tuple(
        _entry_from_dict(item, f"{label}.active_entries[{index}]")
        for index, item in enumerate(
            _list(
                data.get("active_entries"),
                f"{label}.active_entries",
                MAX_ENTRIES_PER_GAME,
            )
        )
    )
    history = tuple(
        _used_from_dict(item, f"{label}.used_history[{index}]")
        for index, item in enumerate(
            _list(
                data.get("used_history"),
                f"{label}.used_history",
                MAX_USED_PER_GAME,
            )
        )
    )
    if any(item.game_id != game_id for item in (*entries, *history)):
        raise SessionValidationError(f"{label} contains wrong-game fact state")
    positions = [item.position for item in entries]
    if positions != list(range(1, len(entries) + 1)):
        raise SessionValidationError(f"{label} queue positions are not dense")
    if len({item.entry_id for item in entries}) != len(entries):
        raise SessionValidationError(f"{label} contains duplicate entry identity")
    target = data.get("break_target_seconds")
    if target is not None:
        try:
            target = validate_break_target(target)
        except RundownMutationError as exc:
            raise SessionValidationError(f"{label} break target is invalid") from exc
    return GameRundownState(
        schema_version=RUNDOWN_SCHEMA_VERSION,
        game_id=game_id,
        active_entries=entries,
        used_history=history,
        break_target_seconds=target,
        revision=_integer(data.get("revision"), f"{label}.revision"),
        created_at=_parse_timestamp(data.get("created_at"), f"{label}.created_at"),
        updated_at=_parse_timestamp(data.get("updated_at"), f"{label}.updated_at"),
        session_only=_boolean(data.get("session_only", True), f"{label}.session_only"),
    )


def _game_from_dict(value: Any) -> GameIdentity | None:
    if value is None:
        return None
    data = _mapping(value, "selected_game")
    return GameIdentity(
        game_id=data.get("game_id"),
        season=data.get("season"),
        away_team_code=data.get("away_team_code"),
        home_team_code=data.get("home_team_code"),
    )


def _ui_from_dict(value: Any) -> SessionUIState:
    if value is None:
        return SessionUIState()
    data = _mapping(value, "ui_state")
    return SessionUIState(
        main_tab=data.get("main_tab", "Game Day"),
        game_day_view=data.get("game_day_view", "Readiness"),
        fact_status_filter=data.get("fact_status_filter", "Air Ready"),
        fact_team_filter=data.get("fact_team_filter", "Both teams"),
        fact_category_filter=data.get("fact_category_filter", "All categories"),
        fact_template_profile=data.get("fact_template_profile", "60 — one line"),
        show_used=data.get("show_used", False),
        selected_player_id=data.get("selected_player_id"),
        fact_scroll_fraction=data.get("fact_scroll_fraction", 0.0),
        rundown_scroll_fraction=data.get("rundown_scroll_fraction", 0.0),
        prior_offline_mode=data.get("prior_offline_mode", False),
    )


def session_from_dict(value: Any) -> SessionSnapshot:
    data = _mapping(value, "session")
    if "schema_version" not in data:
        raise SessionValidationError("session schema_version is required")
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise SessionValidationError("session schema_version must be an integer")
    if version > SESSION_SCHEMA_VERSION:
        raise SessionValidationError(
            f"Session uses newer schema version {version}; this app supports "
            f"version {SESSION_SCHEMA_VERSION}"
        )
    if version < 1:
        raise SessionValidationError(f"Unsupported session schema_version {version}")
    raw_states = data.get("rundown_states", [])
    states = tuple(
        _state_from_dict(item, f"rundown_states[{index}]")
        for index, item in enumerate(
            _list(raw_states, "rundown_states", MAX_RUNDOWN_STATES)
        )
    )
    return SessionSnapshot(
        schema_version=SESSION_SCHEMA_VERSION,
        session_id=data.get("session_id"),
        created_at=_parse_timestamp(data.get("created_at"), "created_at"),
        updated_at=_parse_timestamp(data.get("updated_at"), "updated_at"),
        lifecycle=data.get("lifecycle"),
        selected_game=_game_from_dict(data.get("selected_game")),
        rundown_states=states,
        ui_state=_ui_from_dict(data.get("ui_state")),
    )


def _snapshot_payload(snapshot: SessionSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "session_id": snapshot.session_id,
        "created_at": snapshot.created_at.isoformat(),
        "updated_at": snapshot.updated_at.isoformat(),
        "lifecycle": snapshot.lifecycle.value,
        "selected_game": (
            asdict(snapshot.selected_game) if snapshot.selected_game else None
        ),
        "rundown_states": [state.to_dict() for state in snapshot.rundown_states],
        "ui_state": asdict(snapshot.ui_state),
    }


def session_to_json_bytes(snapshot: SessionSnapshot) -> bytes:
    if not isinstance(snapshot, SessionSnapshot):
        raise SessionValidationError("A validated SessionSnapshot is required")
    rendered = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    data = f"{rendered}\n".encode("utf-8")
    if len(data) > MAX_SESSION_BYTES:
        raise SessionValidationError("Session exceeds safe byte limit")
    return data


def session_from_json_bytes(data: bytes) -> SessionSnapshot:
    if not isinstance(data, bytes):
        raise SessionValidationError("Session content must be bytes")
    if len(data) > MAX_SESSION_BYTES:
        raise SessionValidationError("Session exceeds safe byte limit")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionValidationError("Session JSON is corrupt or invalid UTF-8") from exc
    return session_from_dict(value)


class SessionStore:
    """Serialize all saves and keep one previous validated snapshot as backup."""

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] | None = None,
    ):
        self.directory = (
            session_state_dir() if directory is None else Path(directory)
        )
        self.current_path = self.directory / SESSION_FILENAME
        self.backup_path = self.directory / SESSION_BACKUP_FILENAME
        self._lock = threading.Lock()
        self._latest_generation = -1
        self._replace = replace_func or os.replace

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _flush_file(handle) -> None:
        handle.flush()
        os.fsync(handle.fileno())

    def _atomic_write(self, destination: Path, data: bytes) -> None:
        self._ensure_directory()
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=SESSION_TEMP_PREFIX,
            suffix=SESSION_TEMP_SUFFIX,
            dir=self.directory,
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                self._flush_file(handle)
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            self._replace(temporary, destination)
            try:
                destination.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def save(self, snapshot: SessionSnapshot, *, generation: int) -> SessionSaveResult:
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise SessionValidationError("Save generation must be an integer")
        data = session_to_json_bytes(snapshot)
        with self._lock:
            if generation < self._latest_generation:
                return SessionSaveResult(
                    saved=False,
                    path=self.current_path,
                    generation=generation,
                    error="A newer session generation is already saved.",
                    superseded=True,
                )
            try:
                if self.current_path.exists():
                    current_bytes = self.current_path.read_bytes()
                    try:
                        session_from_json_bytes(current_bytes)
                    except SessionValidationError:
                        pass
                    else:
                        self._atomic_write(self.backup_path, current_bytes)
                self._atomic_write(self.current_path, data)
            except OSError as exc:
                return SessionSaveResult(
                    saved=False,
                    path=self.current_path,
                    generation=generation,
                    error=f"{type(exc).__name__}: {exc}",
                )
            self._latest_generation = generation
            return SessionSaveResult(
                saved=True,
                path=self.current_path,
                generation=generation,
            )

    def _quarantine_copy(self, source: Path, data: bytes) -> Path:
        self._ensure_directory()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.directory / f"producer_session.corrupt-{stamp}.json"
        self._write_exclusive(destination, data)
        return destination

    def _read_valid(
        self, path: Path
    ) -> tuple[SessionSnapshot | None, str, Path | None]:
        try:
            data = path.read_bytes()
        except OSError as exc:
            return None, f"{type(exc).__name__}: {exc}", None
        try:
            return session_from_json_bytes(data), "", None
        except SessionValidationError as exc:
            quarantine = None
            try:
                quarantine = self._quarantine_copy(path, data)
            except OSError:
                pass
            return None, str(exc), quarantine

    def load(self) -> SessionLoadResult:
        with self._lock:
            self.cleanup_owned_temps()
            if not self.current_path.exists():
                return SessionLoadResult(
                    SessionLoadStatus.EMPTY,
                    None,
                    "No saved producer session is available.",
                )
            snapshot, error, quarantine = self._read_valid(self.current_path)
            if snapshot is not None:
                if snapshot.lifecycle is SessionLifecycle.ACTIVE:
                    return SessionLoadResult(
                        SessionLoadStatus.RECOVERED,
                        snapshot,
                        "Recovered a session that did not close cleanly.",
                        self.current_path,
                    )
                return SessionLoadResult(
                    SessionLoadStatus.RESUME,
                    snapshot,
                    "Resumed the last session, which closed cleanly.",
                    self.current_path,
                )
            if self.backup_path.exists():
                backup, backup_error, _backup_quarantine = self._read_valid(
                    self.backup_path
                )
                if backup is not None:
                    return SessionLoadResult(
                        SessionLoadStatus.BACKUP_RECOVERED,
                        backup,
                        (
                            f"Current session was unavailable ({error}); recovered "
                            "the last-known-good backup."
                        ),
                        self.backup_path,
                        quarantine,
                    )
                error = f"{error}; backup unavailable: {backup_error}"
            return SessionLoadResult(
                SessionLoadStatus.UNAVAILABLE,
                None,
                f"Saved session is unavailable: {error}",
                None,
                quarantine,
            )

    def cleanup_owned_temps(self) -> int:
        if not self.directory.exists():
            return 0
        removed = 0
        for path in self.directory.glob(
            f"{SESSION_TEMP_PREFIX}*{SESSION_TEMP_SUFFIX}"
        ):
            if not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def archive_current_for_start_fresh(self) -> Path:
        with self._lock:
            data = self.current_path.read_bytes()
            session_from_json_bytes(data)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            destination = (
                self.directory / f"producer_session.start-fresh-{stamp}.json"
            )
            self._write_exclusive(destination, data)
            return destination
