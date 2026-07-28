"""Session-only, exact-game rundown workflow for Phase 6C.

The business model in this module is GUI-free and network-free.  It stores
canonical ``BroadcastFact`` snapshots rather than rendered Tk text, so pinned
wording, evidence identity, provenance, and trust cannot drift silently.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable

from ausl_facts import BroadcastFact, VerificationState


RUNDOWN_SCHEMA_VERSION = 1
DEFAULT_READING_WPM = 140
DEFAULT_BREAK_TARGET_SECONDS = 30
BREAK_TARGET_PRESETS = (15, 30, 45, 60, 90)
MAX_BREAK_TARGET_SECONDS = 3600
_READ_WORD_RE = re.compile(r"[^\W_]+(?:[.'’/-][^\W_]+)*", re.UNICODE)
_OFFICIAL_GAME_ID_RE = re.compile(r"\d+")


class RundownMutationError(ValueError):
    """Raised when a requested rundown mutation cannot be applied safely."""


class ReconciliationState(str, Enum):
    CURRENT = "CURRENT"
    SOURCE_CHANGED = "SOURCE CHANGED"
    INVALIDATED = "INVALIDATED"
    VERIFICATION_DOWNGRADED = "VERIFICATION DOWNGRADED"


def _aware_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise RundownMutationError("A timezone-aware timestamp is required")
    return result.astimezone(timezone.utc)


def _game_id(value: object) -> str:
    result = str(value or "").strip()
    if not _OFFICIAL_GAME_ID_RE.fullmatch(result):
        raise RundownMutationError("An exact official numeric game ID is required")
    return result


def count_read_words(text: object) -> int:
    """Count spoken-copy tokens consistently, including Unicode names."""

    return len(_READ_WORD_RE.findall(str(text or "")))


def estimate_read_time_seconds(
    text: object,
    *,
    words_per_minute: int = DEFAULT_READING_WPM,
) -> int:
    """Estimate read time from exact air copy without rewriting it."""

    if isinstance(words_per_minute, bool) or not isinstance(words_per_minute, int):
        raise RundownMutationError("Reading rate must be a positive whole number")
    if words_per_minute <= 0:
        raise RundownMutationError("Reading rate must be a positive whole number")
    rendered = str(text or "")
    if not rendered:
        return 0
    words = count_read_words(rendered)
    return max(1, math.ceil(words / words_per_minute * 60))


def validate_break_target(value: object) -> int:
    if isinstance(value, bool):
        raise RundownMutationError("Break target must be a whole number of seconds")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or not re.fullmatch(r"\d+", stripped):
            raise RundownMutationError("Break target must be a whole number of seconds")
        result = int(stripped)
    elif isinstance(value, int):
        result = value
    else:
        raise RundownMutationError("Break target must be a whole number of seconds")
    if result < 1 or result > MAX_BREAK_TARGET_SECONDS:
        raise RundownMutationError(
            f"Break target must be between 1 and {MAX_BREAK_TARGET_SECONDS} seconds"
        )
    return result


def _fact_payload(fact: BroadcastFact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "evidence_hash": fact.evidence_hash,
        "category": fact.category.value,
        "subject_type": fact.subject_type.value,
        "subject_id": fact.subject_id,
        "season": fact.season,
        "selected_game_id": fact.selected_game_id,
        "source_record_identity": fact.source_record_identity,
        "concept_key": fact.concept_key,
        "headline": fact.headline,
        "air_copy": fact.air_copy,
        "supporting_context": fact.supporting_context,
        "subject_display_name": fact.subject_display_name,
        "team_code": fact.team_code,
        "team_display_name": fact.team_display_name,
        "opponent_context": fact.opponent_context,
        "verification_state": fact.verification_state.value,
        "source_health": fact.source_health,
        "producer_confirmation_required": fact.producer_confirmation_required,
        "warning_reason": fact.warning_reason,
        "readiness_blocking": fact.readiness_blocking,
        "provenance": [asdict(source) for source in fact.provenance],
        "evidence": list(fact.evidence),
        "template_profile": fact.template_profile,
    }


@dataclass(frozen=True)
class PinnedFactEntry:
    entry_id: str
    game_id: str
    fact_id: str
    evidence_hash: str
    fact_snapshot: BroadcastFact
    position: int
    pinned_at: datetime
    verification_state_at_pin: VerificationState
    reconciliation_state: ReconciliationState = ReconciliationState.CURRENT
    used_on_air_at: datetime | None = None
    warning_reason: str = ""
    latest_fact: BroadcastFact | None = None

    @property
    def read_time_seconds(self) -> int:
        return estimate_read_time_seconds(self.fact_snapshot.air_copy)

    @property
    def is_air_ready_for_timing(self) -> bool:
        return bool(
            self.used_on_air_at is None
            and self.reconciliation_state is ReconciliationState.CURRENT
            and self.fact_snapshot.air_ready
            and not self.warning_reason
        )

    @property
    def needs_verification(self) -> bool:
        return not self.is_air_ready_for_timing

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "game_id": self.game_id,
            "fact_id": self.fact_id,
            "evidence_hash": self.evidence_hash,
            "fact_snapshot": _fact_payload(self.fact_snapshot),
            "position": self.position,
            "pinned_at": self.pinned_at.isoformat(),
            "verification_state_at_pin": self.verification_state_at_pin.value,
            "reconciliation_state": self.reconciliation_state.value,
            "used_on_air_at": (
                self.used_on_air_at.isoformat() if self.used_on_air_at else None
            ),
            "warning_reason": self.warning_reason,
            "latest_fact": (
                _fact_payload(self.latest_fact) if self.latest_fact else None
            ),
        }


@dataclass(frozen=True)
class UsedFactRecord:
    game_id: str
    fact_id: str
    evidence_hash: str
    fact_snapshot: BroadcastFact
    used_at: datetime
    from_queue: bool
    original_position: int | None = None
    entry_snapshot: PinnedFactEntry | None = None

    @property
    def read_time_seconds(self) -> int:
        return estimate_read_time_seconds(self.fact_snapshot.air_copy)

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "fact_id": self.fact_id,
            "evidence_hash": self.evidence_hash,
            "fact_snapshot": _fact_payload(self.fact_snapshot),
            "used_at": self.used_at.isoformat(),
            "from_queue": self.from_queue,
            "original_position": self.original_position,
            "entry_snapshot": (
                self.entry_snapshot.to_dict() if self.entry_snapshot else None
            ),
        }


@dataclass(frozen=True)
class GameRundownState:
    schema_version: int
    game_id: str
    active_entries: tuple[PinnedFactEntry, ...]
    used_history: tuple[UsedFactRecord, ...]
    break_target_seconds: int | None
    revision: int
    created_at: datetime
    updated_at: datetime
    session_only: bool = True

    @classmethod
    def new(
        cls,
        game_id: object,
        *,
        now: datetime | None = None,
    ) -> "GameRundownState":
        timestamp = _aware_utc(now)
        return cls(
            schema_version=RUNDOWN_SCHEMA_VERSION,
            game_id=_game_id(game_id),
            active_entries=(),
            used_history=(),
            break_target_seconds=DEFAULT_BREAK_TARGET_SECONDS,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def active_air_ready_entries(self) -> tuple[PinnedFactEntry, ...]:
        return tuple(
            entry for entry in self.active_entries if entry.is_air_ready_for_timing
        )

    @property
    def review_entries(self) -> tuple[PinnedFactEntry, ...]:
        return tuple(entry for entry in self.active_entries if entry.needs_verification)

    @property
    def remaining_read_seconds(self) -> int:
        return sum(entry.read_time_seconds for entry in self.active_air_ready_entries)

    @property
    def used_read_seconds(self) -> int:
        return sum(record.read_time_seconds for record in self.used_history)

    @property
    def blocking_issue_fact_ids(self) -> frozenset[str]:
        return frozenset(
            entry.fact_id
            for entry in self.review_entries
            if entry.fact_snapshot.readiness_blocking
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "game_id": self.game_id,
            "active_entries": [entry.to_dict() for entry in self.active_entries],
            "used_history": [record.to_dict() for record in self.used_history],
            "break_target_seconds": self.break_target_seconds,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "session_only": self.session_only,
        }


@dataclass(frozen=True)
class ReadTimeBudget:
    active_seconds: int
    target_seconds: int | None
    difference_seconds: int | None
    status: str
    label: str


def budget_for_state(state: GameRundownState) -> ReadTimeBudget:
    active = state.remaining_read_seconds
    target = state.break_target_seconds
    if target is None:
        return ReadTimeBudget(
            active, None, None, "unset", f"{active} sec active · no target set"
        )
    difference = active - target
    if difference < 0:
        label = f"{active} sec / {target} sec target — {-difference} sec available"
        status = "under"
    elif difference == 0:
        label = f"{active} sec / {target} sec target — exactly on target"
        status = "exact"
    else:
        label = (
            f"{active} sec / {target} sec target — approximately "
            f"{difference} sec over"
        )
        status = "over"
    return ReadTimeBudget(active, target, difference, status, label)


def _dense(entries: Iterable[PinnedFactEntry]) -> tuple[PinnedFactEntry, ...]:
    return tuple(
        replace(entry, position=index)
        for index, entry in enumerate(entries, start=1)
    )


class RundownSession:
    """Isolated in-memory state keyed only by exact official game ID."""

    def __init__(self):
        self._states: dict[str, GameRundownState] = {}

    def get_state(
        self,
        game_id: object,
        *,
        create: bool = True,
        now: datetime | None = None,
    ) -> GameRundownState | None:
        exact_id = _game_id(game_id)
        state = self._states.get(exact_id)
        if state is None and create:
            state = GameRundownState.new(exact_id, now=now)
            self._states[exact_id] = state
        return state

    def ensure_state(
        self, game_id: object, *, now: datetime | None = None
    ) -> GameRundownState:
        state = self.get_state(game_id, create=True, now=now)
        assert state is not None
        return state

    def _mutated(
        self,
        state: GameRundownState,
        *,
        now: datetime | None = None,
        **changes,
    ) -> GameRundownState:
        result = replace(
            state,
            revision=state.revision + 1,
            updated_at=_aware_utc(now),
            **changes,
        )
        self._states[state.game_id] = result
        return result

    @staticmethod
    def _validate_fact_game(game_id: str, fact: BroadcastFact) -> None:
        if not isinstance(fact, BroadcastFact):
            raise RundownMutationError("A canonical Broadcast Fact is required")
        if fact.selected_game_id != game_id:
            raise RundownMutationError(
                "Fact game identity does not match the selected official game"
            )

    def pin_fact(
        self,
        game_id: object,
        fact: BroadcastFact,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        exact_id = _game_id(game_id)
        self._validate_fact_game(exact_id, fact)
        if fact.verification_state is VerificationState.UNAVAILABLE:
            raise RundownMutationError("Unavailable facts cannot be pinned")
        state = self.ensure_state(exact_id, now=now)
        if any(entry.fact_id == fact.fact_id for entry in state.active_entries):
            raise RundownMutationError("This fact is already pinned for this game")
        if any(record.fact_id == fact.fact_id for record in state.used_history):
            raise RundownMutationError(
                "This fact is already marked used for this game; undo use first"
            )
        pinned_at = _aware_utc(now)
        entry_key = "|".join(
            (
                exact_id,
                fact.fact_id,
                fact.evidence_hash,
                pinned_at.isoformat(),
                str(state.revision + 1),
            )
        )
        entry = PinnedFactEntry(
            entry_id=f"pin_{hashlib.sha256(entry_key.encode('utf-8')).hexdigest()[:24]}",
            game_id=exact_id,
            fact_id=fact.fact_id,
            evidence_hash=fact.evidence_hash,
            fact_snapshot=fact,
            position=len(state.active_entries) + 1,
            pinned_at=pinned_at,
            verification_state_at_pin=fact.verification_state,
            warning_reason=fact.warning_reason,
        )
        return self._mutated(
            state,
            now=now,
            active_entries=(*state.active_entries, entry),
        )

    def move_entry(
        self,
        game_id: object,
        entry_id: str,
        direction: int,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        if direction not in (-1, 1):
            raise RundownMutationError("Move direction must be up or down")
        entries = list(state.active_entries)
        index = next(
            (position for position, item in enumerate(entries) if item.entry_id == entry_id),
            None,
        )
        if index is None:
            raise RundownMutationError("Pinned rundown entry is unavailable")
        destination = index + direction
        if destination < 0 or destination >= len(entries):
            return state
        entries[index], entries[destination] = entries[destination], entries[index]
        return self._mutated(
            state,
            now=now,
            active_entries=_dense(entries),
        )

    def remove_entry(
        self,
        game_id: object,
        entry_id: str,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        entries = tuple(
            entry for entry in state.active_entries if entry.entry_id != entry_id
        )
        if len(entries) == len(state.active_entries):
            return state
        return self._mutated(
            state,
            now=now,
            active_entries=_dense(entries),
        )

    def set_break_target(
        self,
        game_id: object,
        target_seconds: object,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        target = validate_break_target(target_seconds)
        if target == state.break_target_seconds:
            return state
        return self._mutated(
            state,
            now=now,
            break_target_seconds=target,
        )

    def is_fact_used(self, game_id: object, fact_id: str) -> bool:
        state = self.get_state(game_id, create=False)
        return bool(
            state
            and any(record.fact_id == fact_id for record in state.used_history)
        )

    def mark_entry_used(
        self,
        game_id: object,
        entry_id: str,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        entry = next(
            (item for item in state.active_entries if item.entry_id == entry_id),
            None,
        )
        if entry is None:
            return state
        if self.is_fact_used(state.game_id, entry.fact_id):
            return state
        used_at = _aware_utc(now)
        used_entry = replace(entry, used_on_air_at=used_at)
        record = UsedFactRecord(
            game_id=state.game_id,
            fact_id=entry.fact_id,
            evidence_hash=entry.evidence_hash,
            fact_snapshot=entry.fact_snapshot,
            used_at=used_at,
            from_queue=True,
            original_position=entry.position,
            entry_snapshot=used_entry,
        )
        remaining = _dense(
            item for item in state.active_entries if item.entry_id != entry_id
        )
        return self._mutated(
            state,
            now=now,
            active_entries=remaining,
            used_history=(*state.used_history, record),
        )

    def mark_fact_used(
        self,
        game_id: object,
        fact: BroadcastFact,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        exact_id = _game_id(game_id)
        self._validate_fact_game(exact_id, fact)
        state = self.ensure_state(exact_id, now=now)
        if self.is_fact_used(exact_id, fact.fact_id):
            return state
        pinned = next(
            (entry for entry in state.active_entries if entry.fact_id == fact.fact_id),
            None,
        )
        if pinned is not None:
            return self.mark_entry_used(exact_id, pinned.entry_id, now=now)
        used_at = _aware_utc(now)
        record = UsedFactRecord(
            game_id=exact_id,
            fact_id=fact.fact_id,
            evidence_hash=fact.evidence_hash,
            fact_snapshot=fact,
            used_at=used_at,
            from_queue=False,
        )
        return self._mutated(
            state,
            now=now,
            used_history=(*state.used_history, record),
        )

    def undo_used(
        self,
        game_id: object,
        fact_id: str,
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        record = next(
            (item for item in reversed(state.used_history) if item.fact_id == fact_id),
            None,
        )
        if record is None:
            return state
        history = tuple(item for item in state.used_history if item is not record)
        entries = list(state.active_entries)
        if record.from_queue and record.entry_snapshot is not None:
            restored = replace(record.entry_snapshot, used_on_air_at=None)
            insertion = max(
                0,
                min((record.original_position or len(entries) + 1) - 1, len(entries)),
            )
            entries.insert(insertion, restored)
        return self._mutated(
            state,
            now=now,
            active_entries=_dense(entries),
            used_history=history,
        )

    def reconcile(
        self,
        game_id: object,
        current_facts: Iterable[BroadcastFact],
        *,
        now: datetime | None = None,
    ) -> GameRundownState:
        state = self.ensure_state(game_id, now=now)
        current_by_id = {
            fact.fact_id: fact
            for fact in current_facts
            if isinstance(fact, BroadcastFact)
            and fact.selected_game_id == state.game_id
        }
        reconciled = []
        for entry in state.active_entries:
            current = current_by_id.get(entry.fact_id)
            if current is None:
                updated = replace(
                    entry,
                    reconciliation_state=ReconciliationState.INVALIDATED,
                    warning_reason=(
                        "Fact is no longer available in the current selected-game "
                        "collection."
                    ),
                    latest_fact=None,
                )
            elif current.evidence_hash == entry.evidence_hash:
                updated = replace(
                    entry,
                    reconciliation_state=ReconciliationState.CURRENT,
                    warning_reason=entry.fact_snapshot.warning_reason,
                    latest_fact=None,
                )
            else:
                downgraded = bool(
                    entry.fact_snapshot.air_ready and not current.air_ready
                )
                updated = replace(
                    entry,
                    reconciliation_state=(
                        ReconciliationState.VERIFICATION_DOWNGRADED
                        if downgraded
                        else ReconciliationState.SOURCE_CHANGED
                    ),
                    warning_reason=(
                        current.warning_reason
                        or (
                            "Verification or source trust was downgraded."
                            if downgraded
                            else "Source evidence or wording changed; review latest."
                        )
                    ),
                    latest_fact=current,
                )
            reconciled.append(updated)
        result = _dense(reconciled)
        if result == state.active_entries:
            return state
        return self._mutated(state, now=now, active_entries=result)

    def replace_with_latest(
        self,
        game_id: object,
        entry_id: str,
        *,
        confirmed: bool,
        now: datetime | None = None,
    ) -> GameRundownState:
        if not confirmed:
            raise RundownMutationError("Explicit confirmation is required")
        state = self.ensure_state(game_id, now=now)
        entries = list(state.active_entries)
        index = next(
            (position for position, item in enumerate(entries) if item.entry_id == entry_id),
            None,
        )
        if index is None:
            raise RundownMutationError("Pinned rundown entry is unavailable")
        entry = entries[index]
        latest = entry.latest_fact
        if latest is None:
            raise RundownMutationError("No newer fact version is available")
        self._validate_fact_game(state.game_id, latest)
        entries[index] = replace(
            entry,
            fact_id=latest.fact_id,
            evidence_hash=latest.evidence_hash,
            fact_snapshot=latest,
            verification_state_at_pin=latest.verification_state,
            reconciliation_state=ReconciliationState.CURRENT,
            warning_reason=latest.warning_reason,
            latest_fact=None,
        )
        return self._mutated(
            state,
            now=now,
            active_entries=_dense(entries),
        )

    def used_version_changed(self, game_id: object, fact: BroadcastFact) -> bool:
        state = self.get_state(game_id, create=False)
        if state is None:
            return False
        record = next(
            (item for item in reversed(state.used_history) if item.fact_id == fact.fact_id),
            None,
        )
        return bool(record and record.evidence_hash != fact.evidence_hash)


@dataclass(frozen=True)
class RundownExportContext:
    game_id: str
    away_team: str
    home_team: str
    scheduled_time: str
    venue: str
    snapshot_timestamp: str


def _source_summary(fact: BroadcastFact) -> str:
    if not fact.provenance:
        return "Source unavailable · snapshot unavailable"
    source = fact.provenance[0]
    bits = [
        source.source_name,
        f"Game {source.source_game_id}" if source.source_game_id else "",
        f"page {source.source_page}" if source.source_page else "",
        source.source_date or "",
        f"snapshot {source.snapshot_timestamp}" if source.snapshot_timestamp else "",
    ]
    return " · ".join(bit for bit in bits if bit)


def _render_entry(entry: PinnedFactEntry, *, order: int | None = None) -> list[str]:
    fact = entry.fact_snapshot
    prefix = f"{order}. " if order is not None else "- "
    lines = [
        (
            f"{prefix}{fact.category.value.replace('_', ' ').upper()} · "
            f"{fact.team_code or 'GLOBAL'} · {fact.subject_display_name}"
        ),
        f"   {fact.air_copy}",
        (
            f"   Estimated read: {entry.read_time_seconds} sec · "
            f"Status: {fact.verification_state.value} · "
            f"Reconciliation: {entry.reconciliation_state.value}"
        ),
        f"   Source: {_source_summary(fact)}",
    ]
    if entry.warning_reason:
        lines.append(f"   WARNING: {entry.warning_reason}")
    return lines


def render_rundown_export(
    state: GameRundownState,
    context: RundownExportContext,
    *,
    exported_at: datetime | None = None,
) -> str:
    exported = _aware_utc(exported_at)
    if _game_id(context.game_id) != state.game_id:
        raise RundownMutationError("Export context does not match rundown game ID")
    budget = budget_for_state(state)
    header = [
        "AUSL BROADCAST RUNDOWN — PRODUCER-PRIVATE SESSION EXPORT",
        f"GAME: {context.away_team} at {context.home_team}",
        f"OFFICIAL GAME ID: {state.game_id}",
        f"SCHEDULED: {context.scheduled_time or 'Unavailable'}",
        f"VENUE: {context.venue or 'Unavailable'}",
        f"EXPORTED UTC: {exported.isoformat()}",
        f"RUNDOWN REVISION: {state.revision}",
        (
            f"BREAK TARGET: {state.break_target_seconds} sec"
            if state.break_target_seconds is not None
            else "BREAK TARGET: Not set"
        ),
        f"Estimated active read time: {state.remaining_read_seconds} sec",
        f"BUDGET: {budget.label}",
        f"DATA SNAPSHOT: {context.snapshot_timestamp or 'Unavailable'}",
        "SESSION STATUS: In memory only; Phase 6D persistence is not implemented.",
        "VERIFY BEFORE AIR: Recheck lineups, availability, milestones, and sources.",
        "",
        "ACTIVE AIR-READY RUNDOWN",
        "-------------------------",
    ]
    body = list(header)
    if state.active_air_ready_entries:
        for order, entry in enumerate(state.active_air_ready_entries, start=1):
            body.extend(_render_entry(entry, order=order))
            body.append("")
    else:
        body.extend(["No active air-ready facts.", ""])
    body.extend(["NEEDS VERIFICATION", "------------------"])
    if state.review_entries:
        for entry in state.review_entries:
            body.extend(_render_entry(entry))
            body.append("")
    else:
        body.extend(["No pinned review items.", ""])
    body.extend(["USED-ON-AIR HISTORY", "-------------------"])
    if state.used_history:
        for record in state.used_history:
            fact = record.fact_snapshot
            body.extend(
                [
                    (
                        f"- {fact.category.value.replace('_', ' ').upper()} · "
                        f"{fact.team_code or 'GLOBAL'} · {fact.subject_display_name}"
                    ),
                    f"   {fact.air_copy}",
                    (
                        f"   Used UTC: {record.used_at.isoformat()} · "
                        f"Estimated read: {record.read_time_seconds} sec · "
                        f"Evidence: {record.evidence_hash}"
                    ),
                    f"   Source: {_source_summary(fact)}",
                    "",
                ]
            )
    else:
        body.append("No facts marked used on air.")
    return "\n".join(body).rstrip() + "\n"


def rundown_export_filename(
    state: GameRundownState,
    *,
    exported_at: datetime | None = None,
) -> str:
    exported = _aware_utc(exported_at)
    stamp = exported.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_game_{_game_id(state.game_id)}_r{state.revision}_rundown.txt"


def write_rundown_export_exclusive(
    output_directory: Path,
    state: GameRundownState,
    context: RundownExportContext,
    *,
    exported_at: datetime | None = None,
) -> Path:
    exported = _aware_utc(exported_at)
    destination = Path(output_directory) / rundown_export_filename(
        state, exported_at=exported
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = render_rundown_export(state, context, exported_at=exported)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return destination
