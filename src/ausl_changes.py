"""Deterministic, private-safe Phase 6E snapshot comparison models.

The module is GUI-free and network-free.  It stores only compact material
broadcast state, compares two validated installed snapshots, and returns
immutable events.  It never mutates facts, lineups, or rundown state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

import pandas as pd


DIGEST_SCHEMA_VERSION = 1
COMPARISON_SCHEMA_VERSION = 1
MAX_DIGEST_RECORDS = 10_000
MAX_CHANGE_EVENTS = 300
_MILESTONE_CATEGORIES = {"milestone_watch", "milestone_reached"}


class ChangeSeverity(str, Enum):
    BLOCKING = "blocking"
    ATTENTION = "attention"
    INFO = "info"


class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    UPDATED = "updated"
    VERIFICATION_UPGRADED = "verification_upgraded"
    VERIFICATION_DOWNGRADED = "verification_downgraded"
    INVALIDATED = "invalidated"
    RESTORED = "restored"
    SOURCE_HEALTH_CHANGED = "source_health_changed"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _identifier(value: Any, label: str) -> str:
    result = _text(value)
    if not result:
        raise ValueError(f"{label} is required")
    if len(result) > 4_096:
        raise ValueError(f"{label} exceeds safe limits")
    return result


def _season(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("season must be an integer")
    if value < 2000 or value > 2200:
        raise ValueError("season is outside safe limits")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: Any, label: str, *, required: bool = False) -> str:
    text = _text(value)
    if not text:
        if required:
            raise ValueError(f"{label} is required")
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _strict_mapping(
    value: Any,
    label: str,
    allowed: set[str],
    *,
    required: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label} contains unexpected fields: {sorted(unknown)}")
    missing = (required or set()) - set(value)
    if missing:
        raise ValueError(f"{label} is missing fields: {sorted(missing)}")
    return value


@dataclass(frozen=True)
class SnapshotMetadata:
    season: int
    source_id: str
    imported_at: str
    parser_version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "season", _season(self.season))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(
            self, "imported_at", _timestamp(self.imported_at, "imported_at", required=True)
        )
        object.__setattr__(self, "parser_version", _text(self.parser_version))


@dataclass(frozen=True)
class RosterDigest:
    player_id: str
    season: int
    team_code: str
    roster_status: str
    player_name: str
    jersey_number: str = ""
    position: str = ""

    def __post_init__(self):
        object.__setattr__(self, "player_id", _identifier(self.player_id, "player_id"))
        object.__setattr__(self, "season", _season(self.season))
        object.__setattr__(self, "team_code", _text(self.team_code).upper())
        object.__setattr__(self, "roster_status", _text(self.roster_status).lower())
        object.__setattr__(
            self, "player_name", _identifier(self.player_name, "player_name")
        )
        object.__setattr__(self, "jersey_number", _text(self.jersey_number))
        object.__setattr__(self, "position", _text(self.position))
        if not self.team_code or not self.roster_status:
            raise ValueError("Roster digest requires team and roster status")

    @property
    def key(self) -> tuple[int, str]:
        return self.season, self.player_id


@dataclass(frozen=True)
class TeamDigest:
    team_code: str
    season: int
    wins: int
    losses: int
    rank: int | None = None
    games_back: str = ""
    streak: str = ""
    source_id: str = ""

    def __post_init__(self):
        object.__setattr__(self, "team_code", _identifier(self.team_code, "team_code").upper())
        object.__setattr__(self, "season", _season(self.season))
        for name in ("wins", "losses"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.rank is not None and (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("rank must be a positive integer")
        object.__setattr__(self, "games_back", _text(self.games_back))
        object.__setattr__(self, "streak", _text(self.streak))
        object.__setattr__(self, "source_id", _text(self.source_id))

    @property
    def key(self) -> tuple[int, str]:
        return self.season, self.team_code


@dataclass(frozen=True)
class ScheduleDigest:
    game_id: str
    season: int
    away_team_code: str
    home_team_code: str
    scheduled_start: str
    venue: str
    status: str
    away_score: int | None = None
    home_score: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "game_id", _identifier(self.game_id, "game_id"))
        object.__setattr__(self, "season", _season(self.season))
        object.__setattr__(
            self, "away_team_code", _identifier(self.away_team_code, "away_team_code").upper()
        )
        object.__setattr__(
            self, "home_team_code", _identifier(self.home_team_code, "home_team_code").upper()
        )
        if self.away_team_code == self.home_team_code:
            raise ValueError("Schedule teams must be different")
        object.__setattr__(
            self,
            "scheduled_start",
            _timestamp(self.scheduled_start, "scheduled_start", required=True),
        )
        object.__setattr__(self, "venue", _text(self.venue))
        object.__setattr__(self, "status", _identifier(self.status, "status").lower())
        for name in ("away_score", "home_score"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")

    @property
    def key(self) -> tuple[int, str]:
        return self.season, self.game_id


@dataclass(frozen=True)
class LineupDigest:
    game_id: str
    season: int
    team_code: str
    source_state: str
    player_ids: tuple[str, ...]
    revision: str = ""

    def __post_init__(self):
        object.__setattr__(self, "game_id", _identifier(self.game_id, "game_id"))
        object.__setattr__(self, "season", _season(self.season))
        object.__setattr__(self, "team_code", _identifier(self.team_code, "team_code").upper())
        object.__setattr__(self, "source_state", _identifier(self.source_state, "source_state").lower())
        players = tuple(sorted({_identifier(item, "lineup player_id") for item in self.player_ids}))
        object.__setattr__(self, "player_ids", players)
        object.__setattr__(self, "revision", _text(self.revision))

    @property
    def key(self) -> tuple[int, str, str]:
        return self.season, self.game_id, self.team_code


@dataclass(frozen=True)
class FactDigest:
    fact_id: str
    evidence_hash: str
    category: str
    subject_type: str
    subject_id: str
    player_id: str | None
    team_code: str | None
    game_id: str | None
    season: int
    concept_key: str
    headline: str
    air_copy: str
    verification_state: str
    air_ready: bool
    source_name: str
    source_reference: str
    source_date: str = ""
    source_page: str = ""
    snapshot_timestamp: str = ""

    def __post_init__(self):
        for name in (
            "fact_id",
            "evidence_hash",
            "category",
            "subject_type",
            "subject_id",
            "concept_key",
            "headline",
            "verification_state",
            "source_name",
            "source_reference",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "season", _season(self.season))
        object.__setattr__(
            self, "player_id", _text(self.player_id) or None
        )
        object.__setattr__(
            self, "team_code", _text(self.team_code).upper() or None
        )
        object.__setattr__(self, "game_id", _text(self.game_id) or None)
        object.__setattr__(self, "category", self.category.lower())
        object.__setattr__(self, "subject_type", self.subject_type.lower())
        object.__setattr__(self, "verification_state", self.verification_state.upper())
        object.__setattr__(self, "air_copy", _text(self.air_copy))
        object.__setattr__(self, "source_date", _text(self.source_date))
        object.__setattr__(self, "source_page", _text(self.source_page))
        if not isinstance(self.air_ready, bool):
            raise ValueError("air_ready must be Boolean")
        if self.snapshot_timestamp:
            object.__setattr__(
                self,
                "snapshot_timestamp",
                _timestamp(self.snapshot_timestamp, "snapshot_timestamp"),
            )

    @property
    def key(self) -> str:
        return self.fact_id

    @property
    def milestone_key(self) -> tuple[Any, ...] | None:
        if self.category not in _MILESTONE_CATEGORIES:
            return None
        return (
            self.subject_type,
            self.subject_id,
            self.player_id,
            self.team_code,
            self.game_id,
            self.season,
            self.concept_key,
        )


@dataclass(frozen=True)
class SourceHealthDigest:
    source_name: str
    state: str
    warning: str = ""
    content_id: str = ""

    def __post_init__(self):
        object.__setattr__(
            self, "source_name", _identifier(self.source_name, "source_name")
        )
        state = _identifier(self.state, "source health state").lower()
        if state not in {"green", "yellow", "red", "unknown"}:
            raise ValueError("Unknown source health state")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "warning", _text(self.warning))
        object.__setattr__(self, "content_id", _text(self.content_id))

    @property
    def key(self) -> str:
        return self.source_name.casefold()


@dataclass(frozen=True)
class BroadcastSnapshotDigest:
    schema_version: int
    snapshot_id: str
    metadata: SnapshotMetadata
    roster: tuple[RosterDigest, ...] = ()
    teams: tuple[TeamDigest, ...] = ()
    schedule: tuple[ScheduleDigest, ...] = ()
    lineups: tuple[LineupDigest, ...] = ()
    facts: tuple[FactDigest, ...] = ()
    source_health: tuple[SourceHealthDigest, ...] = ()

    def __post_init__(self):
        if self.schema_version != DIGEST_SCHEMA_VERSION:
            raise ValueError("Unsupported digest schema version")
        if not isinstance(self.metadata, SnapshotMetadata):
            raise ValueError("Digest metadata is invalid")
        for name, expected in (
            ("roster", RosterDigest),
            ("teams", TeamDigest),
            ("schedule", ScheduleDigest),
            ("lineups", LineupDigest),
            ("facts", FactDigest),
            ("source_health", SourceHealthDigest),
        ):
            items = tuple(getattr(self, name))
            if len(items) > MAX_DIGEST_RECORDS:
                raise ValueError(f"{name} exceeds safe limits")
            if any(not isinstance(item, expected) for item in items):
                raise ValueError(f"{name} contains invalid records")
        expected_id = _canonical_hash(self._material_payload())
        if self.snapshot_id != expected_id:
            raise ValueError("Digest snapshot_id does not match material content")

    @classmethod
    def create(
        cls,
        *,
        metadata: SnapshotMetadata,
        roster: Iterable[RosterDigest] = (),
        teams: Iterable[TeamDigest] = (),
        schedule: Iterable[ScheduleDigest] = (),
        lineups: Iterable[LineupDigest] = (),
        facts: Iterable[FactDigest] = (),
        source_health: Iterable[SourceHealthDigest] = (),
    ) -> "BroadcastSnapshotDigest":
        redacted_facts = []
        for item in facts:
            if item.category == "manual_note":
                item = replace(
                    item,
                    headline="Producer-approved manual note",
                    air_copy="",
                )
            redacted_facts.append(item)
        values = {
            "roster": _unique_sorted(roster, lambda item: item.key, "roster"),
            "teams": _unique_sorted(teams, lambda item: item.key, "teams"),
            "schedule": _unique_sorted(schedule, lambda item: item.key, "schedule"),
            "lineups": _unique_sorted(lineups, lambda item: item.key, "lineups"),
            "facts": _unique_sorted(redacted_facts, lambda item: item.key, "facts"),
            "source_health": _unique_sorted(
                source_health, lambda item: item.key, "source_health"
            ),
        }
        provisional = object.__new__(cls)
        object.__setattr__(provisional, "schema_version", DIGEST_SCHEMA_VERSION)
        object.__setattr__(provisional, "snapshot_id", "")
        object.__setattr__(provisional, "metadata", metadata)
        for name, records in values.items():
            object.__setattr__(provisional, name, records)
        snapshot_id = _canonical_hash(provisional._material_payload())
        return cls(
            schema_version=DIGEST_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            metadata=metadata,
            **values,
        )

    def _material_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "season": self.metadata.season,
            "source_id": self.metadata.source_id,
            "roster": [asdict(item) for item in self.roster],
            "teams": [asdict(item) for item in self.teams],
            "schedule": [asdict(item) for item in self.schedule],
            "lineups": [asdict(item) for item in self.lineups],
            "facts": [asdict(item) for item in self.facts],
            "source_health": [asdict(item) for item in self.source_health],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "metadata": asdict(self.metadata),
            "roster": [asdict(item) for item in self.roster],
            "teams": [asdict(item) for item in self.teams],
            "schedule": [asdict(item) for item in self.schedule],
            "lineups": [asdict(item) for item in self.lineups],
            "facts": [asdict(item) for item in self.facts],
            "source_health": [asdict(item) for item in self.source_health],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BroadcastSnapshotDigest":
        allowed = {
            "schema_version",
            "snapshot_id",
            "metadata",
            "roster",
            "teams",
            "schedule",
            "lineups",
            "facts",
            "source_health",
        }
        data = _strict_mapping(
            value,
            "digest",
            allowed,
            required={"schema_version", "snapshot_id", "metadata"},
        )
        if data["schema_version"] != DIGEST_SCHEMA_VERSION:
            raise ValueError("Unsupported digest schema version")
        metadata_data = _strict_mapping(
            data["metadata"],
            "metadata",
            {"season", "source_id", "imported_at", "parser_version"},
            required={"season", "source_id", "imported_at"},
        )
        metadata = SnapshotMetadata(**metadata_data)
        record_types = {
            "roster": RosterDigest,
            "teams": TeamDigest,
            "schedule": ScheduleDigest,
            "lineups": LineupDigest,
            "facts": FactDigest,
            "source_health": SourceHealthDigest,
        }
        parsed: dict[str, tuple[Any, ...]] = {}
        for name, record_type in record_types.items():
            raw = data.get(name, [])
            if not isinstance(raw, list) or len(raw) > MAX_DIGEST_RECORDS:
                raise ValueError(f"{name} must be a bounded list")
            parsed[name] = tuple(record_type(**item) for item in raw)
        return cls(
            schema_version=DIGEST_SCHEMA_VERSION,
            snapshot_id=_identifier(data["snapshot_id"], "snapshot_id"),
            metadata=metadata,
            **parsed,
        )


def _unique_sorted(items: Iterable[Any], key, label: str) -> tuple[Any, ...]:
    records = tuple(items)
    if len(records) > MAX_DIGEST_RECORDS:
        raise ValueError(f"{label} exceeds safe limits")
    by_key: dict[Any, Any] = {}
    for item in records:
        identity = key(item)
        if identity in by_key:
            raise ValueError(f"Duplicate {label} identity: {identity}")
        by_key[identity] = item
    return tuple(by_key[item] for item in sorted(by_key, key=lambda value: str(value)))


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _scalar_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or not number.is_integer():
        return None
    return int(number)


def fact_digest_from_broadcast_fact(fact: Any) -> FactDigest:
    """Reduce one canonical BroadcastFact without retaining private context."""

    provenance = tuple(getattr(fact, "provenance", ()) or ())
    primary = provenance[0] if provenance else None
    category = getattr(getattr(fact, "category", ""), "value", getattr(fact, "category", ""))
    subject_type = getattr(
        getattr(fact, "subject_type", ""), "value", getattr(fact, "subject_type", "")
    )
    verification = getattr(
        getattr(fact, "verification_state", ""),
        "value",
        getattr(fact, "verification_state", ""),
    )
    return FactDigest(
        fact_id=getattr(fact, "fact_id", ""),
        evidence_hash=getattr(fact, "evidence_hash", ""),
        category=category,
        subject_type=subject_type,
        subject_id=getattr(fact, "subject_id", ""),
        player_id=(
            getattr(fact, "subject_id", None)
            if str(subject_type) == "player"
            else None
        ),
        team_code=getattr(fact, "team_code", None),
        game_id=getattr(fact, "selected_game_id", None),
        season=getattr(fact, "season", None),
        concept_key=getattr(fact, "concept_key", ""),
        headline=getattr(fact, "headline", ""),
        air_copy=getattr(fact, "air_copy", ""),
        verification_state=verification,
        air_ready=bool(getattr(fact, "air_ready", False)),
        source_name=getattr(primary, "source_name", "") if primary else "Unavailable",
        source_reference=(
            getattr(primary, "source_reference", "") if primary else "Unavailable"
        ),
        source_date=getattr(primary, "source_date", "") if primary else "",
        source_page=getattr(primary, "source_page", "") if primary else "",
        snapshot_timestamp=(
            getattr(primary, "snapshot_timestamp", "") if primary else ""
        ),
    )


def build_snapshot_digest(
    database: Mapping[str, Any],
    *,
    facts: Iterable[Any] = (),
    locked_lineups: Mapping[str, Any] | None = None,
) -> BroadcastSnapshotDigest:
    """Build a compact digest from one already-validated local database.

    The adapter intentionally ignores routine stat-table rows. Material stat
    transitions enter through canonical BroadcastFacts, preventing an ordinary
    box-score refresh from flooding the producer with noise.
    """

    if not isinstance(database, Mapping):
        raise ValueError("A validated database mapping is required")
    manifest = database.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("Database manifest is required")
    raw_updated = manifest.get("updated_at")
    imported_at = _timestamp(raw_updated, "manifest.updated_at", required=True)
    seasons = manifest.get("seasons", {})
    if not isinstance(seasons, Mapping) or not seasons:
        raise ValueError("Manifest seasons are required")
    calendar_seasons: dict[int, int] = {}
    for calendar, source_season in seasons.items():
        year = _scalar_int(calendar)
        source_id = _scalar_int(source_season)
        if year is not None and source_id is not None:
            calendar_seasons[year] = source_id
    if not calendar_seasons:
        raise ValueError("Manifest seasons are invalid")
    inverse_seasons = {value: key for key, value in calendar_seasons.items()}
    season = max(calendar_seasons)

    health_items: list[SourceHealthDigest] = []
    raw_health = manifest.get("source_health", {})
    if isinstance(raw_health, Mapping):
        for key, value in raw_health.items():
            if not isinstance(value, Mapping):
                continue
            raw_state = _scalar_text(value.get("status")).lower()
            if raw_state == "disabled":
                continue
            state = raw_state if raw_state in {"green", "yellow", "red", "unknown"} else "unknown"
            warning = ""
            if state != "green":
                warning = _scalar_text(
                    value.get("error_summary") or value.get("status_detail")
                )
            health_items.append(
                SourceHealthDigest(
                    source_name=_scalar_text(value.get("source_name")) or str(key),
                    state=state,
                    warning=warning,
                    content_id=_scalar_text(value.get("content_hash_or_etag")),
                )
            )
    source_identity = {
        "source": _scalar_text(manifest.get("source")),
        "seasons": sorted(calendar_seasons.items()),
        "sources": [
            (item.source_name, item.content_id, item.state)
            for item in sorted(health_items, key=lambda value: value.key)
        ],
    }
    parser_versions = sorted(
        {
            _scalar_text(value.get("parser_version"))
            for value in raw_health.values()
            if isinstance(value, Mapping) and _scalar_text(value.get("parser_version"))
        }
    ) if isinstance(raw_health, Mapping) else []
    metadata = SnapshotMetadata(
        season=season,
        source_id=_canonical_hash(source_identity),
        imported_at=imported_at,
        parser_version=",".join(parser_versions),
    )

    roster_items: list[RosterDigest] = []
    roster = database.get("roster")
    if isinstance(roster, pd.DataFrame) and not roster.empty:
        required = {"player_id", "player_name", "team_code", "roster_status"}
        if not required.issubset(roster.columns):
            raise ValueError("Roster is missing material identity fields")
        for _, row in roster.iterrows():
            row_season = _scalar_int(row.get("season")) or season
            roster_items.append(
                RosterDigest(
                    player_id=_scalar_text(row.get("player_id")),
                    season=row_season,
                    team_code=(
                        _scalar_text(row.get("team_code")) or "UNASSIGNED"
                    ),
                    roster_status=_scalar_text(row.get("roster_status")),
                    player_name=_scalar_text(row.get("player_name")),
                    jersey_number=_scalar_text(row.get("jersey_number")),
                    position=_scalar_text(row.get("position")),
                )
            )

    team_items: list[TeamDigest] = []
    standings = database.get("standings")
    if isinstance(standings, pd.DataFrame) and not standings.empty:
        required = {"seasonId", "team_code", "wins", "losses", "standingsTypeLk"}
        if not required.issubset(standings.columns):
            raise ValueError("Standings are missing material identity fields")
        official = standings[
            standings["standingsTypeLk"].astype(str).str.strip().eq("SEASON")
        ]
        for _, row in official.iterrows():
            row_season = inverse_seasons.get(_scalar_int(row.get("seasonId")))
            wins = _scalar_int(row.get("wins"))
            losses = _scalar_int(row.get("losses"))
            if row_season is None or wins is None or losses is None:
                continue
            team_items.append(
                TeamDigest(
                    team_code=_scalar_text(row.get("team_code")),
                    season=row_season,
                    wins=wins,
                    losses=losses,
                    rank=_scalar_int(row.get("rank")),
                    games_back=_scalar_text(row.get("gamesBehind")),
                    streak=_scalar_text(row.get("winStreak")),
                    source_id=_scalar_text(row.get("source_url")),
                )
            )

    schedule_items: list[ScheduleDigest] = []
    schedule = database.get("schedule_results")
    if isinstance(schedule, pd.DataFrame) and not schedule.empty:
        required = {
            "game_id", "season", "away_team_code", "home_team_code",
            "game_date", "venue", "status",
        }
        if not required.issubset(schedule.columns):
            raise ValueError("Schedule is missing material identity fields")
        game_ids = schedule["game_id"].map(_scalar_text)
        counts = game_ids[game_ids.ne("")].value_counts()
        for index, row in schedule.iterrows():
            game_id = game_ids.loc[index]
            if not game_id or counts.get(game_id, 0) != 1:
                continue
            row_season = _scalar_int(row.get("season"))
            if row_season in inverse_seasons:
                row_season = inverse_seasons[row_season]
            if row_season not in calendar_seasons:
                continue
            try:
                scheduled = pd.to_datetime(row.get("game_date"), errors="raise")
                if scheduled.tzinfo is None:
                    continue
                scheduled_start = scheduled.to_pydatetime().astimezone(
                    timezone.utc
                ).isoformat()
            except (TypeError, ValueError, OverflowError):
                continue
            schedule_items.append(
                ScheduleDigest(
                    game_id=game_id,
                    season=row_season,
                    away_team_code=_scalar_text(row.get("away_team_code")),
                    home_team_code=_scalar_text(row.get("home_team_code")),
                    scheduled_start=scheduled_start,
                    venue=_scalar_text(row.get("venue")),
                    status=_scalar_text(row.get("status")) or "unavailable",
                    away_score=_scalar_int(row.get("away_score")),
                    home_score=_scalar_int(row.get("home_score")),
                )
            )

    lineup_items: list[LineupDigest] = []
    games = (locked_lineups or {}).get("games", {})
    if isinstance(games, Mapping):
        for game_id, lock in games.items():
            if not isinstance(lock, Mapping):
                continue
            matching = next(
                (item for item in schedule_items if item.game_id == str(game_id)),
                None,
            )
            if matching is None:
                continue
            raw_lineups = lock.get("lineups", {})
            if not isinstance(raw_lineups, Mapping):
                continue
            for side_or_code, team_lineup in raw_lineups.items():
                if isinstance(team_lineup, Mapping):
                    team_code = _scalar_text(team_lineup.get("team_code"))
                    if not team_code:
                        team_code = (
                            matching.away_team_code
                            if str(side_or_code).lower() == "away"
                            else matching.home_team_code
                            if str(side_or_code).lower() == "home"
                            else str(side_or_code)
                        )
                    player_values = team_lineup.get("lineup", ())
                elif isinstance(team_lineup, (list, tuple)):
                    team_code = str(side_or_code)
                    player_values = team_lineup
                else:
                    continue
                if not isinstance(player_values, (list, tuple, Mapping)):
                    continue
                if isinstance(player_values, Mapping):
                    player_values = player_values.values()
                player_ids = []
                for player in player_values:
                    if isinstance(player, Mapping):
                        player_id = _scalar_text(
                            player.get("player_id") or player.get("id")
                        )
                    else:
                        player_id = _scalar_text(player)
                    if player_id:
                        player_ids.append(player_id)
                lineup_items.append(
                    LineupDigest(
                        game_id=matching.game_id,
                        season=matching.season,
                        team_code=team_code,
                        source_state=_scalar_text(lock.get("source")) or "unknown",
                        player_ids=tuple(player_ids),
                        revision=_scalar_text(
                            lock.get("revision") or lock.get("updated_at")
                        ),
                    )
                )

    fact_items = tuple(
        item if isinstance(item, FactDigest) else fact_digest_from_broadcast_fact(item)
        for item in facts
    )
    return BroadcastSnapshotDigest.create(
        metadata=metadata,
        roster=roster_items,
        teams=team_items,
        schedule=schedule_items,
        lineups=lineup_items,
        facts=fact_items,
        source_health=health_items,
    )


@dataclass(frozen=True)
class ChangeComparisonContext:
    selected_game_id: str | None = None
    pinned_fact_versions: tuple[tuple[str, str], ...] = ()
    used_fact_versions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "selected_game_id", _text(self.selected_game_id) or None)
        for name in ("pinned_fact_versions", "used_fact_versions"):
            values = tuple(
                sorted(
                    {
                        (
                            _identifier(fact_id, f"{name} fact_id"),
                            _identifier(version, f"{name} evidence_hash"),
                        )
                        for fact_id, version in getattr(self, name)
                    }
                )
            )
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class ChangeEvent:
    event_id: str
    category: str
    severity: ChangeSeverity
    scope: str
    change_type: ChangeType
    headline: str
    before_summary: str
    after_summary: str
    detected_at: str
    before_snapshot_id: str
    after_snapshot_id: str
    player_id: str | None = None
    team_code: str | None = None
    game_id: str | None = None
    season: int | None = None
    fact_id: str | None = None
    before_fact_id: str | None = None
    before_evidence_hash: str | None = None
    after_evidence_hash: str | None = None
    selected_game_impact: bool = False
    pinned_impact: bool = False
    used_impact: bool = False
    readiness_impact: bool = False
    can_replace_pinned: bool = False
    suggested_action: str = ""
    source_summary: str = ""

    def __post_init__(self):
        object.__setattr__(self, "severity", ChangeSeverity(self.severity))
        object.__setattr__(self, "change_type", ChangeType(self.change_type))
        object.__setattr__(self, "detected_at", _timestamp(self.detected_at, "detected_at", required=True))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        payload["change_type"] = self.change_type.value
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "ChangeEvent":
        fields = set(cls.__dataclass_fields__)
        data = _strict_mapping(value, "change event", fields, required={
            "event_id", "category", "severity", "scope", "change_type",
            "headline", "before_summary", "after_summary", "detected_at",
            "before_snapshot_id", "after_snapshot_id",
        })
        return cls(**data)


@dataclass(frozen=True)
class ChangeComparison:
    schema_version: int
    before_snapshot_id: str
    after_snapshot_id: str
    before_imported_at: str
    after_imported_at: str
    detected_at: str
    events: tuple[ChangeEvent, ...]

    def __post_init__(self):
        if self.schema_version != COMPARISON_SCHEMA_VERSION:
            raise ValueError("Unsupported comparison schema version")
        object.__setattr__(self, "detected_at", _timestamp(self.detected_at, "detected_at", required=True))
        if len(self.events) > MAX_CHANGE_EVENTS:
            raise ValueError("Change event count exceeds safe limits")

    @property
    def blocking_count(self) -> int:
        return sum(item.severity is ChangeSeverity.BLOCKING for item in self.events)

    @property
    def attention_count(self) -> int:
        return sum(item.severity is ChangeSeverity.ATTENTION for item in self.events)

    @property
    def info_count(self) -> int:
        return sum(item.severity is ChangeSeverity.INFO for item in self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "before_snapshot_id": self.before_snapshot_id,
            "after_snapshot_id": self.after_snapshot_id,
            "before_imported_at": self.before_imported_at,
            "after_imported_at": self.after_imported_at,
            "detected_at": self.detected_at,
            "events": [item.to_dict() for item in self.events],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ChangeComparison":
        fields = {
            "schema_version", "before_snapshot_id", "after_snapshot_id",
            "before_imported_at", "after_imported_at", "detected_at", "events",
        }
        data = _strict_mapping(value, "comparison", fields, required=fields)
        raw_events = data["events"]
        if not isinstance(raw_events, list) or len(raw_events) > MAX_CHANGE_EVENTS:
            raise ValueError("events must be a bounded list")
        return cls(
            schema_version=data["schema_version"],
            before_snapshot_id=data["before_snapshot_id"],
            after_snapshot_id=data["after_snapshot_id"],
            before_imported_at=data["before_imported_at"],
            after_imported_at=data["after_imported_at"],
            detected_at=data["detected_at"],
            events=tuple(ChangeEvent.from_dict(item) for item in raw_events),
        )


def _event(
    *,
    before: BroadcastSnapshotDigest,
    after: BroadcastSnapshotDigest,
    detected_at: str,
    category: str,
    scope: str,
    change_type: ChangeType,
    headline: str,
    before_summary: str,
    after_summary: str,
    severity: ChangeSeverity,
    identity: Mapping[str, Any],
    **kwargs: Any,
) -> ChangeEvent:
    stable = {
        "before_snapshot_id": before.snapshot_id,
        "after_snapshot_id": after.snapshot_id,
        "category": category,
        "scope": scope,
        "change_type": change_type.value,
        "identity": dict(identity),
    }
    return ChangeEvent(
        event_id=f"change_{_canonical_hash(stable)[:24]}",
        category=category,
        severity=severity,
        scope=scope,
        change_type=change_type,
        headline=headline,
        before_summary=before_summary,
        after_summary=after_summary,
        detected_at=detected_at,
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        **kwargs,
    )


def _health_rank(state: str) -> int:
    return {"green": 3, "yellow": 2, "unknown": 1, "red": 0}.get(state, 0)


def _fact_summary(fact: FactDigest | None) -> str:
    if fact is None:
        return "Not present"
    if fact.category == "manual_note":
        return f"Producer-approved manual note · {fact.verification_state}"
    return f"{fact.air_copy or fact.headline} · {fact.verification_state}"


def _roster_summary(item: RosterDigest | None) -> str:
    if item is None:
        return "Not on installed roster"
    details = [item.roster_status, item.team_code]
    if item.jersey_number:
        details.append(f"#{item.jersey_number}")
    if item.position:
        details.append(item.position)
    return f"{item.player_name}: {' · '.join(details)}"


def _team_summary(item: TeamDigest | None) -> str:
    if item is None:
        return "Unavailable"
    details = [f"{item.team_code} {item.wins}-{item.losses}"]
    if item.rank is not None:
        details.append(f"rank {item.rank}")
    if item.games_back:
        details.append(f"{item.games_back} GB")
    if item.streak:
        details.append(item.streak)
    return " · ".join(details)


def _schedule_summary(item: ScheduleDigest | None) -> str:
    if item is None:
        return "Not present"
    details = [
        f"{item.away_team_code} at {item.home_team_code}",
        item.scheduled_start,
        item.status,
        item.venue or "venue unavailable",
    ]
    if item.away_score is not None and item.home_score is not None:
        details.append(
            f"{item.away_team_code} {item.away_score}, "
            f"{item.home_team_code} {item.home_score}"
        )
    return " · ".join(details)


def _fact_event(
    before_digest: BroadcastSnapshotDigest,
    after_digest: BroadcastSnapshotDigest,
    old: FactDigest | None,
    new: FactDigest | None,
    *,
    context: ChangeComparisonContext,
    detected_at: str,
    milestone_transition: bool = False,
) -> ChangeEvent:
    fact_id = new.fact_id if new else old.fact_id
    pinned_versions = dict(context.pinned_fact_versions)
    used_versions = dict(context.used_fact_versions)
    pinned = fact_id in pinned_versions or (old is not None and old.fact_id in pinned_versions)
    used = fact_id in used_versions or (old is not None and old.fact_id in used_versions)
    selected_game = bool(
        context.selected_game_id
        and context.selected_game_id
        in {item.game_id for item in (old, new) if item is not None}
    )
    if old is None:
        change_type = ChangeType.ADDED
    elif new is None:
        change_type = ChangeType.REMOVED
    elif old.air_ready and not new.air_ready:
        change_type = ChangeType.VERIFICATION_DOWNGRADED
    elif not old.air_ready and new.air_ready:
        change_type = ChangeType.VERIFICATION_UPGRADED
    else:
        change_type = ChangeType.UPDATED

    readiness = bool(
        (old and old.air_ready and (new is None or not new.air_ready))
        or (new and new.verification_state in {"VERIFY", "STALE", "UNAVAILABLE"})
    )
    if pinned and (new is None or not new.air_ready):
        severity = ChangeSeverity.BLOCKING
    elif readiness and selected_game:
        severity = ChangeSeverity.BLOCKING
    elif pinned or used or selected_game or change_type is ChangeType.VERIFICATION_DOWNGRADED:
        severity = ChangeSeverity.ATTENTION
    else:
        severity = ChangeSeverity.INFO
    if pinned:
        action = "Review pinned fact"
    elif used:
        action = "Review used-on-air history"
    else:
        action = "Review current fact"
    category = "milestone" if milestone_transition else "fact"
    subject = new or old
    source = new or old
    return _event(
        before=before_digest,
        after=after_digest,
        detected_at=detected_at,
        category=category,
        scope="fact",
        change_type=change_type,
        headline=(
            "Milestone status changed"
            if milestone_transition
            else f"{subject.headline} changed"
        ),
        before_summary=_fact_summary(old),
        after_summary=_fact_summary(new),
        severity=severity,
        identity={
            "before_fact_id": old.fact_id if old else None,
            "after_fact_id": new.fact_id if new else None,
            "concept_key": subject.concept_key,
        },
        player_id=subject.player_id,
        team_code=subject.team_code,
        game_id=subject.game_id,
        season=subject.season,
        fact_id=new.fact_id if new else old.fact_id,
        before_fact_id=old.fact_id if old else None,
        before_evidence_hash=old.evidence_hash if old else None,
        after_evidence_hash=new.evidence_hash if new else None,
        selected_game_impact=selected_game,
        pinned_impact=pinned,
        used_impact=used,
        readiness_impact=readiness,
        can_replace_pinned=bool(pinned and new and new.air_ready),
        suggested_action=action,
        source_summary=(
            f"{source.source_name} · {source.source_reference}"
            if source
            else ""
        ),
    )


def compare_snapshot_digests(
    before: BroadcastSnapshotDigest,
    after: BroadcastSnapshotDigest,
    *,
    context: ChangeComparisonContext | None = None,
    detected_at: datetime | str | None = None,
) -> ChangeComparison:
    """Compare two validated digests without mutating either snapshot."""

    if not isinstance(before, BroadcastSnapshotDigest) or not isinstance(
        after, BroadcastSnapshotDigest
    ):
        raise ValueError("Validated before and after digests are required")
    context = context or ChangeComparisonContext()
    if isinstance(detected_at, datetime):
        timestamp = detected_at.astimezone(timezone.utc).isoformat()
    else:
        timestamp = _timestamp(
            detected_at or datetime.now(timezone.utc).isoformat(),
            "detected_at",
            required=True,
        )
    events: list[ChangeEvent] = []

    before_roster = {item.key: item for item in before.roster}
    after_roster = {item.key: item for item in after.roster}
    for key in sorted(set(before_roster) | set(after_roster)):
        old, new = before_roster.get(key), after_roster.get(key)
        if old == new:
            continue
        subject = new or old
        if old and new:
            old_summary = _roster_summary(old)
            new_summary = _roster_summary(new)
            change_type = ChangeType.UPDATED
            headline = f"{subject.player_name} roster status changed"
        elif new:
            old_summary = _roster_summary(None)
            new_summary = _roster_summary(new)
            change_type = ChangeType.ADDED
            headline = f"{subject.player_name} added to roster"
        else:
            old_summary = _roster_summary(old)
            new_summary = "No longer on installed roster"
            change_type = ChangeType.REMOVED
            headline = f"{subject.player_name} removed from roster"
        events.append(
            _event(
                before=before,
                after=after,
                detected_at=timestamp,
                category="roster",
                scope="player",
                change_type=change_type,
                headline=headline,
                before_summary=old_summary,
                after_summary=new_summary,
                severity=ChangeSeverity.ATTENTION,
                identity={"season": subject.season, "player_id": subject.player_id},
                player_id=subject.player_id,
                team_code=subject.team_code,
                season=subject.season,
                suggested_action="Review player",
            )
        )

    before_teams = {item.key: item for item in before.teams}
    after_teams = {item.key: item for item in after.teams}
    for key in sorted(set(before_teams) | set(after_teams)):
        old, new = before_teams.get(key), after_teams.get(key)
        if old == new:
            continue
        subject = new or old
        events.append(
            _event(
                before=before,
                after=after,
                detected_at=timestamp,
                category="team",
                scope="team",
                change_type=ChangeType.UPDATED if old and new else (
                    ChangeType.ADDED if new else ChangeType.REMOVED
                ),
                headline=f"{subject.team_code} official record changed",
                before_summary=(
                    _team_summary(old)
                ),
                after_summary=(
                    _team_summary(new)
                ),
                severity=ChangeSeverity.INFO,
                identity={"season": subject.season, "team_code": subject.team_code},
                team_code=subject.team_code,
                season=subject.season,
                suggested_action="Review team snapshot",
            )
        )

    before_games = {item.key: item for item in before.schedule}
    after_games = {item.key: item for item in after.schedule}
    for key in sorted(set(before_games) | set(after_games)):
        old, new = before_games.get(key), after_games.get(key)
        if old == new:
            continue
        subject = new or old
        selected = context.selected_game_id == subject.game_id
        events.append(
            _event(
                before=before,
                after=after,
                detected_at=timestamp,
                category="schedule",
                scope="game",
                change_type=ChangeType.UPDATED if old and new else (
                    ChangeType.ADDED if new else ChangeType.REMOVED
                ),
                headline=f"Game {subject.game_id} schedule changed",
                before_summary=(
                    _schedule_summary(old)
                ),
                after_summary=(
                    _schedule_summary(new) if new else "Removed"
                ),
                severity=(
                    ChangeSeverity.ATTENTION if selected else ChangeSeverity.INFO
                ),
                identity={"season": subject.season, "game_id": subject.game_id},
                team_code=subject.home_team_code,
                game_id=subject.game_id,
                season=subject.season,
                selected_game_impact=selected,
                readiness_impact=selected,
                suggested_action="Review game",
            )
        )

    before_lineups = {item.key: item for item in before.lineups}
    after_lineups = {item.key: item for item in after.lineups}
    for key in sorted(set(before_lineups) | set(after_lineups)):
        old, new = before_lineups.get(key), after_lineups.get(key)
        if old == new:
            continue
        subject = new or old
        selected = context.selected_game_id == subject.game_id
        lost_confirmation = bool(
            old
            and old.source_state in {"confirmed", "official"}
            and (
                new is None
                or new.source_state not in {"confirmed", "official"}
            )
        )
        severity = (
            ChangeSeverity.BLOCKING
            if selected and lost_confirmation
            else ChangeSeverity.ATTENTION
            if selected
            else ChangeSeverity.INFO
        )
        events.append(
            _event(
                before=before,
                after=after,
                detected_at=timestamp,
                category="lineup",
                scope="lineup",
                change_type=(
                    ChangeType.INVALIDATED
                    if lost_confirmation
                    else ChangeType.UPDATED
                    if old and new
                    else ChangeType.ADDED
                    if new
                    else ChangeType.REMOVED
                ),
                headline=f"Game {subject.game_id} {subject.team_code} lineup changed",
                before_summary=(
                    f"{old.source_state.title()} · {len(old.player_ids)} players"
                    if old
                    else "No locked lineup"
                ),
                after_summary=(
                    f"{new.source_state.title()} · {len(new.player_ids)} players"
                    if new
                    else "No locked lineup"
                ),
                severity=severity,
                identity={
                    "season": subject.season,
                    "game_id": subject.game_id,
                    "team_code": subject.team_code,
                },
                team_code=subject.team_code,
                game_id=subject.game_id,
                season=subject.season,
                selected_game_impact=selected,
                readiness_impact=selected,
                suggested_action="Review lineup",
            )
        )

    before_health = {item.key: item for item in before.source_health}
    after_health = {item.key: item for item in after.source_health}
    for key in sorted(set(before_health) | set(after_health)):
        old, new = before_health.get(key), after_health.get(key)
        if old == new:
            continue
        old_state = old.state if old else "unknown"
        new_state = new.state if new else "unknown"
        recovered = _health_rank(new_state) > _health_rank(old_state)
        severity = (
            ChangeSeverity.BLOCKING
            if new_state in {"red", "unknown"}
            else ChangeSeverity.ATTENTION
            if new_state == "yellow"
            else ChangeSeverity.INFO
        )
        subject = new or old
        events.append(
            _event(
                before=before,
                after=after,
                detected_at=timestamp,
                category="source_health",
                scope="source",
                change_type=(
                    ChangeType.RESTORED
                    if recovered and new_state == "green"
                    else ChangeType.SOURCE_HEALTH_CHANGED
                ),
                headline=f"{subject.source_name} health changed",
                before_summary=old_state.upper(),
                after_summary=new_state.upper(),
                severity=severity,
                identity={"source_name": subject.source_name.casefold()},
                readiness_impact=severity is not ChangeSeverity.INFO,
                suggested_action="Review source health",
                source_summary=subject.source_name,
            )
        )

    before_facts = {item.fact_id: item for item in before.facts}
    after_facts = {item.fact_id: item for item in after.facts}
    matched_before: set[str] = set()
    matched_after: set[str] = set()
    for fact_id in sorted(set(before_facts) & set(after_facts)):
        old, new = before_facts[fact_id], after_facts[fact_id]
        matched_before.add(fact_id)
        matched_after.add(fact_id)
        if old.evidence_hash != new.evidence_hash or old != new:
            events.append(
                _fact_event(
                    before,
                    after,
                    old,
                    new,
                    context=context,
                    detected_at=timestamp,
                )
            )

    old_milestones: dict[tuple[Any, ...], FactDigest] = {}
    new_milestones: dict[tuple[Any, ...], FactDigest] = {}
    for item in before.facts:
        if item.fact_id not in matched_before and item.milestone_key is not None:
            old_milestones[item.milestone_key] = item
    for item in after.facts:
        if item.fact_id not in matched_after and item.milestone_key is not None:
            new_milestones[item.milestone_key] = item
    for key in sorted(set(old_milestones) & set(new_milestones), key=str):
        old, new = old_milestones[key], new_milestones[key]
        if old.category == new.category:
            continue
        matched_before.add(old.fact_id)
        matched_after.add(new.fact_id)
        events.append(
            _fact_event(
                before,
                after,
                old,
                new,
                context=context,
                detected_at=timestamp,
                milestone_transition=True,
            )
        )

    for fact_id in sorted(set(before_facts) - matched_before):
        events.append(
            _fact_event(
                before,
                after,
                before_facts[fact_id],
                None,
                context=context,
                detected_at=timestamp,
            )
        )
    for fact_id in sorted(set(after_facts) - matched_after):
        events.append(
            _fact_event(
                before,
                after,
                None,
                after_facts[fact_id],
                context=context,
                detected_at=timestamp,
            )
        )

    severity_order = {
        ChangeSeverity.BLOCKING: 0,
        ChangeSeverity.ATTENTION: 1,
        ChangeSeverity.INFO: 2,
    }
    events.sort(
        key=lambda item: (
            severity_order[item.severity],
            not item.selected_game_impact,
            not item.pinned_impact,
            not item.used_impact,
            item.category,
            item.team_code or "",
            item.player_id or "",
            item.game_id or "",
            item.event_id,
        )
    )
    if len(events) > MAX_CHANGE_EVENTS:
        raise ValueError("Change event count exceeds safe limits")
    return ChangeComparison(
        schema_version=COMPARISON_SCHEMA_VERSION,
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        before_imported_at=before.metadata.imported_at,
        after_imported_at=after.metadata.imported_at,
        detected_at=timestamp,
        events=tuple(events),
    )
