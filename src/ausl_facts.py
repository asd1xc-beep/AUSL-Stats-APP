"""Canonical, deterministic Phase 6B broadcast facts.

This module is deliberately GUI-free and network-free.  It converts one
installed database snapshot plus one exact official game into immutable facts.
Tkinter may render or copy those values, but it does not own fact identity,
trust, or air-ready policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from ausl_data import normalize_roster_status
from ausl_college_approval import ApprovedCollegeArtifact, validate_approved_payload
from ausl_college_batch_approval import (
    ApprovedAggregateArtifact,
    validate_aggregate_approval,
)
from ausl_college_connection_approval import (
    ApprovedConnectionArtifact,
    validate_connection_approval,
)
from ausl_splits import apply_split_sample_policy, innings_to_outs as split_innings_to_outs


class FactCategory(str, Enum):
    AVAILABILITY = "availability"
    CONFIRMED_STARTER = "confirmed_starter"
    PROJECTED_STARTER = "projected_starter"
    MILESTONE_REACHED = "milestone_reached"
    MILESTONE_WATCH = "milestone_watch"
    RECENT_TREND = "recent_trend"
    SEASON_CONTEXT = "season_context"
    MATCHUP_HISTORY = "matchup_history"
    CAREER_SUMMARY = "career_summary"
    TEAM_CONTEXT = "team_context"
    BACKGROUND = "background"
    MANUAL_NOTE = "manual_note"
    COLLEGE_CONNECTION = "college_connection"


class FactSubjectType(str, Enum):
    PLAYER = "player"
    TEAM = "team"
    GAME = "game"
    GLOBAL = "global"


class VerificationState(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFY = "VERIFY"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CharacterCountProfile:
    name: str
    limit: int
    guidance: str

    def __post_init__(self):
        if not self.name.strip() or self.limit <= 0:
            raise ValueError("Character-count profiles require a name and positive limit")


CHARACTER_COUNT_PROFILES: Mapping[str, CharacterCountProfile] = {
    "one_line": CharacterCountProfile(
        "one_line",
        60,
        "One-line graphics-copy guidance; not graphics-system validation.",
    ),
    "extended": CharacterCountProfile(
        "extended",
        120,
        "Extended/two-line copy guidance; not graphics-system validation.",
    ),
}


@dataclass(frozen=True)
class CharacterCountPreview:
    text: str
    profile_name: str
    character_count: int
    limit: int
    state: str
    label: str
    guidance: str


@dataclass(frozen=True)
class SourceProvenance:
    source_name: str
    source_reference: str
    source_date: str | None = None
    source_page: str | None = None
    source_game_id: str | None = None
    snapshot_timestamp: str | None = None
    parser_version: str | None = None
    approval_record_id: str | None = None
    source_record_id: str | None = None

    def is_complete(self) -> bool:
        return bool(
            _text(self.source_name)
            and _text(self.source_reference)
            and _text(self.snapshot_timestamp)
        )


@dataclass(frozen=True)
class BroadcastFact:
    category: FactCategory
    subject_type: FactSubjectType
    subject_id: str
    season: int
    selected_game_id: str | None
    source_record_identity: str
    concept_key: str
    headline: str
    air_copy: str
    supporting_context: str
    subject_display_name: str
    team_code: str | None
    team_display_name: str | None
    opponent_context: str | None
    provenance: tuple[SourceProvenance, ...]
    verification_state: VerificationState
    source_health: str
    producer_confirmation_required: bool
    warning_reason: str
    readiness_blocking: bool
    evidence: tuple[tuple[str, str], ...] = ()
    template_profile: str = "one_line"
    fact_id: str = field(init=False)
    evidence_hash: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "category", FactCategory(self.category))
        object.__setattr__(self, "subject_type", FactSubjectType(self.subject_type))
        object.__setattr__(
            self, "verification_state", VerificationState(self.verification_state)
        )
        object.__setattr__(self, "subject_id", _identifier(self.subject_id))
        object.__setattr__(
            self,
            "selected_game_id",
            _identifier(self.selected_game_id) or None,
        )
        object.__setattr__(self, "team_code", _text(self.team_code).upper() or None)
        object.__setattr__(self, "source_health", _text(self.source_health).lower())
        object.__setattr__(
            self,
            "provenance",
            tuple(self.provenance),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted((str(key), str(value)) for key, value in self.evidence)),
        )
        required = (
            self.subject_id,
            self.source_record_identity,
            self.concept_key,
            self.headline,
            self.air_copy,
        )
        if not all(_text(item) for item in required):
            raise ValueError("Broadcast facts require exact identity and visible content")
        if not isinstance(self.season, int) or self.season < 2000:
            raise ValueError("Broadcast fact season must be an exact calendar year")
        if self.template_profile not in CHARACTER_COUNT_PROFILES:
            raise ValueError(f"Unknown character-count profile: {self.template_profile}")

        identity = {
            "category": self.category.value,
            "subject_type": self.subject_type.value,
            "subject_id": self.subject_id,
            "team_code": self.team_code,
            "selected_game_id": self.selected_game_id,
            "season": self.season,
            "concept_key": self.concept_key,
            "source_record_identity": self.source_record_identity,
        }
        object.__setattr__(self, "fact_id", f"fact_{_hash(identity)[:24]}")
        version = {
            **identity,
            "headline": self.headline,
            "air_copy": self.air_copy,
            "supporting_context": self.supporting_context,
            "subject_display_name": self.subject_display_name,
            "team_display_name": self.team_display_name,
            "opponent_context": self.opponent_context,
            "provenance": [asdict(item) for item in self.provenance],
            "verification_state": self.verification_state.value,
            "source_health": self.source_health,
            "producer_confirmation_required": self.producer_confirmation_required,
            "warning_reason": self.warning_reason,
            "evidence": self.evidence,
        }
        object.__setattr__(self, "evidence_hash", _hash(version))

    @property
    def air_ready(self) -> bool:
        return bool(
            self.verification_state is VerificationState.VERIFIED
            and self.source_health == "green"
            and self.provenance
            and all(item.is_complete() for item in self.provenance)
            and not self.producer_confirmation_required
            and not _text(self.warning_reason)
        )

    @property
    def character_count(self) -> int:
        return len(self.air_copy)

    @property
    def character_preview(self) -> CharacterCountPreview:
        return character_count_preview(self.air_copy, self.template_profile)


@dataclass(frozen=True)
class FactCollection:
    game_id: str
    snapshot_timestamp: str
    database_version: str
    facts: tuple[BroadcastFact, ...]
    available: bool
    empty_reason: str

    @property
    def blocking_verification_count(self) -> int | None:
        if not self.available:
            return None
        return sum(
            item.readiness_blocking and not item.air_ready for item in self.facts
        )


@dataclass(frozen=True)
class FactCopyEvent:
    fact_id: str
    evidence_hash: str
    copied_text: str
    provenance: tuple[SourceProvenance, ...]
    snapshot_timestamp: str
    copied_at: datetime
    template_profile: str


class FactCopyBlocked(ValueError):
    """Raised when ordinary air-line copy is attempted for unsafe evidence."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _identifier(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        number = float(text)
    except (TypeError, ValueError, OverflowError):
        return text
    if math.isfinite(number) and number.is_integer():
        return str(int(number))
    return text


def _field(value: Any, key: str, default=None):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bool_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"true", "1", "yes"}


def _bool_false(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    return _text(value).casefold() in {"false", "0", "no"}


def _number(value: Any, *, integer: bool = False) -> float | int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if integer:
        if not number.is_integer():
            return None
        return int(number)
    return number


def character_count_preview(
    text: str, profile: str | CharacterCountProfile | Mapping[str, Any]
) -> CharacterCountPreview:
    exact = str(text)
    if isinstance(profile, str):
        selected = CHARACTER_COUNT_PROFILES[profile]
    elif isinstance(profile, CharacterCountProfile):
        selected = profile
    elif isinstance(profile, Mapping):
        selected = CharacterCountProfile(
            _text(profile.get("name")) or "custom",
            int(profile.get("limit")),
            _text(profile.get("guidance"))
            or "Character-count guidance; not graphics-system validation.",
        )
    else:
        raise TypeError("Character-count profile must be a name, profile, or mapping")
    count = len(exact)
    near_margin = max(3, math.ceil(selected.limit * 0.1))
    if count > selected.limit:
        state = "likely_wrap"
        status = "likely wraps"
    elif count >= selected.limit - near_margin:
        state = "near_limit"
        status = "near limit"
    else:
        state = "fits"
        status = "fits"
    return CharacterCountPreview(
        text=exact,
        profile_name=selected.name,
        character_count=count,
        limit=selected.limit,
        state=state,
        label=f"{count}/{selected.limit} — {status}",
        guidance=selected.guidance,
    )


def build_copy_event(
    fact: BroadcastFact,
    *,
    copied_at: datetime | None = None,
    template_profile: str | None = None,
) -> FactCopyEvent:
    if not fact.air_ready:
        reason = _text(fact.warning_reason) or fact.verification_state.value
        raise FactCopyBlocked(f"Fact is not air-ready: {reason}")
    timestamp = copied_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Copy timestamp must be timezone-aware")
    snapshots = [
        _text(item.snapshot_timestamp)
        for item in fact.provenance
        if _text(item.snapshot_timestamp)
    ]
    selected_profile = template_profile or fact.template_profile
    if selected_profile not in CHARACTER_COUNT_PROFILES:
        raise ValueError(f"Unknown character-count profile: {selected_profile}")
    return FactCopyEvent(
        fact_id=fact.fact_id,
        evidence_hash=fact.evidence_hash,
        copied_text=fact.air_copy,
        provenance=fact.provenance,
        snapshot_timestamp=snapshots[0] if snapshots else "",
        copied_at=timestamp,
        template_profile=selected_profile,
    )


def copy_with_source_text(fact: BroadcastFact) -> str:
    status = fact.verification_state.value
    lead = fact.air_copy if fact.air_ready else f"[{status}] {fact.air_copy}"
    primary = fact.provenance[0] if fact.provenance else None
    source_parts = []
    if primary is not None:
        source_parts.append(primary.source_name or "Source unavailable")
        if primary.source_game_id:
            source_parts.append(f"Game {primary.source_game_id}")
        if primary.source_page:
            source_parts.append(f"page {primary.source_page}")
    lines = [
        lead,
        f"Source: {', '.join(source_parts) if source_parts else 'Unavailable'}",
        f"Source date: {primary.source_date if primary and primary.source_date else 'Unavailable'}",
        (
            "Data snapshot: "
            f"{primary.snapshot_timestamp if primary and primary.snapshot_timestamp else 'Unavailable'}"
        ),
        f"Status: {status}",
        f"Fact ID: {fact.fact_id}",
        f"Evidence: {fact.evidence_hash}",
    ]
    for index, source in enumerate(fact.provenance[1:], 2):
        source_bits = [source.source_name or "Source unavailable"]
        if source.source_game_id:
            source_bits.append(f"Game {source.source_game_id}")
        if source.source_page:
            source_bits.append(f"page {source.source_page}")
        lines.extend(
            [
                f"Source {index}: {', '.join(source_bits)}",
                f"Source {index} date: {source.source_date or 'Unavailable'}",
                (
                    f"Source {index} snapshot: "
                    f"{source.snapshot_timestamp or 'Unavailable'}"
                ),
            ]
        )
    if fact.warning_reason:
        lines.append(f"Warning: {fact.warning_reason}")
    return "\n".join(lines)


_CATEGORY_PRIORITY = {
    FactCategory.AVAILABILITY: 0,
    FactCategory.CONFIRMED_STARTER: 1,
    FactCategory.PROJECTED_STARTER: 1,
    FactCategory.MILESTONE_REACHED: 2,
    FactCategory.MILESTONE_WATCH: 3,
    FactCategory.RECENT_TREND: 4,
    FactCategory.SEASON_CONTEXT: 5,
    FactCategory.MATCHUP_HISTORY: 6,
    FactCategory.TEAM_CONTEXT: 6,
    FactCategory.CAREER_SUMMARY: 7,
    FactCategory.MANUAL_NOTE: 8,
    FactCategory.BACKGROUND: 8,
    FactCategory.COLLEGE_CONNECTION: 8,
}


def _authority_score(fact: BroadcastFact) -> tuple[int, int, int]:
    names = " ".join(item.source_name.casefold() for item in fact.provenance)
    authority = 3 if "official ausl game notes" in names else 2 if "official" in names else 1
    state = {
        VerificationState.VERIFIED: 3,
        VerificationState.STALE: 2,
        VerificationState.VERIFY: 1,
        VerificationState.UNAVAILABLE: 0,
    }[fact.verification_state]
    return (1 if fact.air_ready else 0, state, authority)


def _normalized_copy(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def deduplicate_facts(facts: Iterable[BroadcastFact]) -> list[BroadcastFact]:
    groups: dict[tuple[Any, ...], list[BroadcastFact]] = {}
    for fact in facts:
        key = (
            fact.category,
            fact.subject_type,
            fact.subject_id,
            fact.team_code,
            fact.selected_game_id,
            fact.season,
            _normalized_copy(fact.air_copy),
        )
        groups.setdefault(key, []).append(fact)
    result = []
    for group in groups.values():
        strongest = max(group, key=_authority_score)
        provenance = []
        for item in [strongest, *sorted(group, key=lambda fact: fact.fact_id)]:
            for source in item.provenance:
                if source not in provenance:
                    provenance.append(source)
        result.append(replace(strongest, provenance=tuple(provenance)))
    return result


def order_facts(
    facts: Iterable[BroadcastFact], *, team_codes: Sequence[str] = ()
) -> list[BroadcastFact]:
    normalized_teams = tuple(_text(item).upper() for item in team_codes if _text(item))
    by_priority: dict[int, list[BroadcastFact]] = {}
    for fact in facts:
        by_priority.setdefault(_CATEGORY_PRIORITY.get(fact.category, 99), []).append(fact)
    ordered = []
    for priority in sorted(by_priority):
        group = by_priority[priority]
        group.sort(
            key=lambda item: (
                -_authority_score(item)[0],
                -_authority_score(item)[1],
                item.category.value,
                item.subject_display_name.casefold(),
                item.fact_id,
            )
        )
        team_groups = {
            team: [item for item in group if item.team_code == team]
            for team in normalized_teams
        }
        remainder = [item for item in group if item.team_code not in normalized_teams]
        while any(team_groups.values()):
            for team in normalized_teams:
                if team_groups[team]:
                    ordered.append(team_groups[team].pop(0))
        ordered.extend(remainder)
    return ordered


def _source_health(database: Mapping[str, Any], source: str) -> str:
    manifest = database.get("manifest")
    entries = manifest.get("source_health") if isinstance(manifest, Mapping) else {}
    entry = entries.get(source) if isinstance(entries, Mapping) else None
    if (
        entry is None
        and source == "media_guide"
        and isinstance(entries, Mapping)
    ):
        # Read legacy Phase 6 fixtures/manifests, but all new snapshots use
        # the canonical ``media_guide`` key emitted by ausl_data.
        entry = entries.get("official_media_guide")
    status = _text(entry.get("status") if isinstance(entry, Mapping) else "").lower()
    if status not in {"green", "yellow", "red"}:
        return "unknown"
    return status


_CORE_SOURCES = {
    "official_rosters",
    "official_stats",
    "official_schedule",
    "official_standings",
}


def _source_trust(
    database: Mapping[str, Any], source: str
) -> tuple[VerificationState, str, str]:
    health = _source_health(database, source)
    if health == "green":
        state = VerificationState.VERIFIED
        warning = ""
    elif health == "yellow":
        state = VerificationState.STALE
        warning = f"{source.replace('_', ' ').title()} is aging; verify before air."
    else:
        state = VerificationState.UNAVAILABLE
        warning = f"{source.replace('_', ' ').title()} health is {health}; not air-ready."
    attempt = database.get("refresh_attempt")
    if isinstance(attempt, Mapping) and _text(attempt.get("state")).casefold() == "failed":
        affected = _text(attempt.get("affected_source"))
        affected_matches = affected == source or (
            affected == "official_core_sources" and source in _CORE_SOURCES
        ) or (
            affected == "optional_enrichment_sources"
            and source in {"official_game_notes", "media_guide", "split_stats"}
        )
        if affected_matches and state is VerificationState.VERIFIED:
            state = VerificationState.VERIFY
            detail = _text(attempt.get("error_summary")) or "error detail unavailable"
            warning = (
                "Stored snapshot remains installed; latest refresh failed "
                f"for {affected}: {detail}."
            )
    return state, health, warning


def _source_reference(database: Mapping[str, Any], source: str, fallback: str) -> str:
    manifest = database.get("manifest")
    entries = manifest.get("source_health") if isinstance(manifest, Mapping) else {}
    entry = entries.get(source) if isinstance(entries, Mapping) else None
    if isinstance(entry, Mapping):
        return _text(entry.get("source_url") or entry.get("source_reference")) or fallback
    return fallback


def _fact(
    *,
    category: FactCategory,
    subject_type: FactSubjectType,
    subject_id: str,
    season: int,
    game_id: str,
    source_record_identity: str,
    concept_key: str,
    headline: str,
    air_copy: str,
    supporting_context: str,
    subject_display_name: str,
    team_code: str | None,
    team_display_name: str | None,
    opponent_context: str,
    provenance: Sequence[SourceProvenance],
    verification_state: VerificationState,
    source_health: str,
    warning_reason: str = "",
    producer_confirmation_required: bool = False,
    readiness_blocking: bool = False,
    evidence: Iterable[tuple[str, Any]] = (),
) -> BroadcastFact:
    return BroadcastFact(
        category=category,
        subject_type=subject_type,
        subject_id=subject_id,
        season=season,
        selected_game_id=game_id,
        source_record_identity=source_record_identity,
        concept_key=concept_key,
        headline=headline,
        air_copy=air_copy,
        supporting_context=supporting_context,
        subject_display_name=subject_display_name,
        team_code=team_code,
        team_display_name=team_display_name,
        opponent_context=opponent_context,
        provenance=tuple(provenance),
        verification_state=verification_state,
        source_health=source_health,
        producer_confirmation_required=producer_confirmation_required,
        warning_reason=warning_reason,
        readiness_blocking=readiness_blocking,
        evidence=tuple((str(key), str(value)) for key, value in evidence),
    )


def _selected_team_names(selected_game: Any) -> dict[str, str]:
    return {
        _text(_field(selected_game, "away_team_code")).upper(): _text(
            _field(selected_game, "away_team")
        ),
        _text(_field(selected_game, "home_team_code")).upper(): _text(
            _field(selected_game, "home_team")
        ),
    }


def _roster_rows(database: Mapping[str, Any], team_codes: set[str]) -> pd.DataFrame:
    roster = database.get("roster")
    required = {"player_id", "player_name", "team_code", "roster_status"}
    if not isinstance(roster, pd.DataFrame) or not required.issubset(roster.columns):
        return pd.DataFrame()
    rows = roster.copy()
    rows["_player_id"] = rows["player_id"].map(_identifier)
    rows["_team_code"] = rows["team_code"].map(lambda item: _text(item).upper())
    rows = rows[
        rows["_player_id"].ne("")
        & rows["player_name"].map(_text).ne("")
        & rows["_team_code"].isin(team_codes)
    ]
    return rows.sort_values(["_team_code", "_player_id"], kind="stable")


def _single_player_stat(frame: Any, player_id: str) -> pd.Series | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "player_id" not in frame:
        return None
    rows = frame[frame["player_id"].map(_identifier).eq(player_id)]
    return rows.iloc[0] if len(rows) == 1 else None


def _roster_status(value: Any) -> str:
    return normalize_roster_status(value)


def _official_stats_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    snapshot: str,
) -> list[BroadcastFact]:
    season = int(_field(selected_game, "season"))
    game_id = _identifier(_field(selected_game, "game_id"))
    team_names = _selected_team_names(selected_game)
    opponent = {
        _text(_field(selected_game, "away_team_code")).upper(): _text(
            _field(selected_game, "home_team_code")
        ).upper(),
        _text(_field(selected_game, "home_team_code")).upper(): _text(
            _field(selected_game, "away_team_code")
        ).upper(),
    }
    stats_state, stats_health, stats_warning = _source_trust(
        database, "official_stats"
    )
    roster_state, roster_health, roster_warning = _source_trust(
        database, "official_rosters"
    )
    facts = []
    for _, player in roster.iterrows():
        player_id = player["_player_id"]
        name = _text(player.get("player_name"))
        code = player["_team_code"]
        team_name = team_names.get(code) or _text(player.get("team")) or code
        status = _roster_status(player.get("roster_status"))
        game_context = f"vs {opponent.get(code, 'opponent unavailable')}, Game {game_id}"
        if status != "Active":
            warning = (
                f"{name} is listed {status}; confirm current availability before air."
            )
            if roster_warning:
                warning = f"{warning} {roster_warning}"
            facts.append(
                _fact(
                    category=FactCategory.AVAILABILITY,
                    subject_type=FactSubjectType.PLAYER,
                    subject_id=player_id,
                    season=season,
                    game_id=game_id,
                    source_record_identity=f"roster:{player_id}:{season}:status",
                    concept_key="roster-availability",
                    headline=f"{name.upper()} — {status.upper()}",
                    air_copy=f"{name} is listed {status} on the installed AUSL roster.",
                    supporting_context="Roster status is not a same-day participation guarantee.",
                    subject_display_name=name,
                    team_code=code,
                    team_display_name=team_name,
                    opponent_context=game_context,
                    provenance=(
                        SourceProvenance(
                            "Official AUSL Rosters",
                            _source_reference(
                                database,
                                "official_rosters",
                                "local:ausl_rosters.xlsx",
                            ),
                            source_date=snapshot,
                            snapshot_timestamp=snapshot,
                            source_record_id=f"player:{player_id}:roster-status",
                        ),
                    ),
                    verification_state=VerificationState.VERIFY,
                    source_health=roster_health,
                    warning_reason=warning,
                    producer_confirmation_required=True,
                    readiness_blocking=True,
                    evidence=(("roster_status", status),),
                )
            )
            continue

        position = _text(player.get("position")).upper()
        is_pitcher = position in {"P", "RHP", "LHP"}
        season_frame = database.get(
            f"{'pitching' if is_pitcher else 'batting'}_{season}"
        )
        season_row = _single_player_stat(season_frame, player_id)
        if season_row is not None:
            if is_pitcher:
                appearances = _number(season_row.get("appearances"), integer=True)
                strikeouts = _number(season_row.get("strikeOuts"), integer=True)
                era = _number(season_row.get("earnedRunAverage"))
                if (
                    appearances is not None
                    and appearances > 0
                    and strikeouts is not None
                    and era is not None
                ):
                    air_copy = (
                        f"{name} has {strikeouts} strikeouts and a {era:.2f} ERA "
                        f"in the {season} AUSL season."
                    )
                    evidence = (
                        ("appearances", appearances),
                        ("strikeouts", strikeouts),
                        ("era", f"{era:.6f}"),
                    )
                else:
                    air_copy = ""
                    evidence = ()
            else:
                appearances = _number(
                    season_row.get("plateAppearances"), integer=True
                )
                hits = _number(season_row.get("hits"), integer=True)
                home_runs = _number(season_row.get("homeRuns"), integer=True)
                rbi = _number(season_row.get("runsBattedIn"), integer=True)
                if (
                    appearances is not None
                    and appearances > 0
                    and hits is not None
                    and home_runs is not None
                    and rbi is not None
                ):
                    air_copy = (
                        f"{name} has {hits} hits, {home_runs} HR and {rbi} RBI "
                        f"in the {season} AUSL season."
                    )
                    evidence = (
                        ("plate_appearances", appearances),
                        ("hits", hits),
                        ("home_runs", home_runs),
                        ("rbi", rbi),
                    )
                else:
                    air_copy = ""
                    evidence = ()
            if air_copy:
                facts.append(
                    _fact(
                        category=FactCategory.RECENT_TREND,
                        subject_type=FactSubjectType.PLAYER,
                        subject_id=player_id,
                        season=season,
                        game_id=game_id,
                        source_record_identity=f"stats:{player_id}:{season}:summary",
                        concept_key=f"{season}-season-stat-summary",
                        headline=f"{name.upper()} — {season} FORM",
                        air_copy=air_copy,
                        supporting_context=(
                            f"Official {season} AUSL regular-season "
                            f"{'pitching' if is_pitcher else 'batting'} totals."
                        ),
                        subject_display_name=name,
                        team_code=code,
                        team_display_name=team_name,
                        opponent_context=game_context,
                        provenance=(
                            SourceProvenance(
                                "Official AUSL Stats",
                                _source_reference(
                                    database,
                                    "official_stats",
                                    "local:ausl_season_stats.xlsx",
                                ),
                                source_date=snapshot,
                                snapshot_timestamp=snapshot,
                                source_record_id=f"player:{player_id}:season:{season}",
                            ),
                        ),
                        verification_state=stats_state,
                        source_health=stats_health,
                        warning_reason=stats_warning,
                        evidence=evidence,
                    )
                )

        career_row = _single_player_stat(
            database.get("career_pitching" if is_pitcher else "career_batting"),
            player_id,
        )
        if career_row is None:
            continue
        milestones = (
            (
                ("strikeOuts", 25, 7, "strikeouts"),
                ("wins", 5, 2, "wins"),
                ("appearances", 25, 5, "appearances"),
            )
            if is_pitcher
            else (
                ("hits", 25, 7, "hits"),
                ("homeRuns", 5, 2, "home runs"),
                ("runsBattedIn", 25, 7, "RBI"),
                ("stolenBases", 10, 2, "stolen bases"),
                ("gamesPlayed", 25, 5, "games"),
            )
        )
        candidates = []
        for priority, (key, interval, max_gap, label) in enumerate(milestones):
            current = _number(career_row.get(key), integer=True)
            if current is None or current <= 0:
                continue
            target = ((current // interval) + 1) * interval
            gap = target - current
            if gap <= max_gap:
                candidates.append((gap / interval, priority, key, current, target, gap, label))
        if candidates:
            _, _, key, current, target, gap, label = min(candidates)
            singular_label = {
                "strikeouts": "strikeout",
                "wins": "win",
                "appearances": "appearance",
                "hits": "hit",
                "home runs": "home run",
                "RBI": "RBI",
                "stolen bases": "stolen base",
                "games": "game",
            }[label]
            gap_label = singular_label if gap == 1 else label
            facts.append(
                _fact(
                    category=FactCategory.MILESTONE_WATCH,
                    subject_type=FactSubjectType.PLAYER,
                    subject_id=player_id,
                    season=season,
                    game_id=game_id,
                    source_record_identity=f"stats:{player_id}:career:{key}:{target}",
                    concept_key=f"career-milestone:{key}:{target}",
                    headline=f"{name.upper()} — MILESTONE WATCH",
                    air_copy=(
                        f"{name} needs {gap} more {gap_label} to reach "
                        f"{target} career AUSL {label}."
                    ),
                    supporting_context=(
                        "AUSL career totals only; does not include college or other leagues."
                    ),
                    subject_display_name=name,
                    team_code=code,
                    team_display_name=team_name,
                    opponent_context=game_context,
                    provenance=(
                        SourceProvenance(
                            "Official AUSL Stats",
                            _source_reference(
                                database,
                                "official_stats",
                                "local:ausl_career_stats.xlsx",
                            ),
                            source_date=snapshot,
                            snapshot_timestamp=snapshot,
                            source_record_id=f"player:{player_id}:career:{key}",
                        ),
                    ),
                    verification_state=stats_state,
                    source_health=stats_health,
                    warning_reason=stats_warning,
                    evidence=(
                        ("metric", key),
                        ("current", current),
                        ("target", target),
                        ("gap", gap),
                    ),
                )
            )
    return facts


def _split_stat_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    snapshot: str,
) -> list[BroadcastFact]:
    """Adapt detailed official splits through the shared sample-size policy."""

    if database.get("enrichment_enabled") is not True:
        return []
    season = int(_field(selected_game, "season"))
    game_id = _identifier(_field(selected_game, "game_id"))
    team_names = _selected_team_names(selected_game)
    team_codes = set(team_names)
    health_state, health, health_warning = _source_trust(
        database, "split_stats"
    )
    enrichment_mode = _text(database.get("enrichment_mode")).casefold()
    roster_counts = roster["_player_id"].value_counts()
    roster_by_id = {
        _identifier(row.get("_player_id")): row
        for row in roster.to_dict("records")
        if roster_counts.get(_identifier(row.get("_player_id")), 0) == 1
        and _text(row.get("_team_code")).upper() in team_codes
    }
    facts: list[BroadcastFact] = []
    for key, category, is_pitcher in (
        ("batting_splits", "batting", False),
        ("pitching_splits", "pitching", True),
    ):
        source_frame = database.get(key, pd.DataFrame())
        if not isinstance(source_frame, pd.DataFrame) or source_frame.empty:
            continue
        if (
            "player_id" not in source_frame.columns
            or "season" not in source_frame.columns
        ):
            continue
        player_ids = source_frame["player_id"].map(_identifier)
        seasons = pd.to_numeric(source_frame["season"], errors="coerce")
        relevant = source_frame.loc[
            player_ids.isin(roster_by_id) & seasons.eq(season)
        ].copy()
        if relevant.empty:
            continue
        policy_columns = {
            "split_sample_state",
            "split_sample_label",
            "split_air_ready",
            "producer_approved",
            "producer_air_ready",
            "producer_trust_state",
        }
        canonical_producer_rows = bool(
            enrichment_mode == "producer_approved"
            and policy_columns.issubset(relevant.columns)
            and relevant["producer_approved"].map(_bool_true).all()
        )
        frame = (
            relevant
            if canonical_producer_rows
            else apply_split_sample_policy(relevant, category=category)
        )
        if frame.empty:
            continue
        for row in frame.to_dict("records"):
            player_id = _identifier(row.get("player_id"))
            player = roster_by_id.get(player_id)
            if player is None:
                continue
            team_code = player["_team_code"]
            row_season = _number(row.get("season"), integer=True)
            if row_season != season:
                continue
            split_key = _text(row.get("split_key"))
            split_label = _text(row.get("split_label"))
            source_name = _text(row.get("source_name"))
            source_url = _text(row.get("source_url"))
            imported_at = _text(row.get("imported_at"))
            if not all((split_key, split_label, source_name, source_url, imported_at)):
                continue
            name = _text(player.get("player_name"))
            eligible = _bool_true(row.get("split_air_ready"))
            if is_pitcher:
                outs = split_innings_to_outs(row.get("inningsPitched"))
                strikeouts = _number(row.get("strikeOuts"), integer=True)
                era = _number(row.get("earnedRunAverage"))
                if outs is None or strikeouts is None or era is None:
                    continue
                innings = f"{outs // 3}.{outs % 3}"
                air_copy = (
                    f"{name} has a {era:.2f} ERA with {strikeouts} strikeouts "
                    f"in {innings} innings over the {split_label.lower()} split."
                )
                sample_evidence = ("sample_outs", outs)
            else:
                plate_appearances = _number(
                    row.get("plateAppearances"), integer=True
                )
                hits = _number(row.get("hits"), integer=True)
                average = _number(row.get("battingAverage"))
                if (
                    plate_appearances is None
                    or hits is None
                    or average is None
                ):
                    continue
                air_copy = (
                    f"{name} is batting {average:.3f} with {hits} hits in "
                    f"{plate_appearances} plate appearances over the "
                    f"{split_label.lower()} split."
                )
                sample_evidence = ("sample_plate_appearances", plate_appearances)
            producer_row_approved = bool(
                enrichment_mode == "producer_approved"
                and _bool_true(row.get("producer_approved"))
                and _bool_true(row.get("producer_air_ready"))
            )
            if (
                eligible
                and producer_row_approved
                and health_state is VerificationState.VERIFIED
            ):
                state = VerificationState.VERIFIED
                warning = ""
            elif health_state is VerificationState.STALE:
                state = VerificationState.STALE
                warning = health_warning
            elif health_state is VerificationState.UNAVAILABLE:
                state = VerificationState.UNAVAILABLE
                warning = health_warning
            else:
                state = VerificationState.VERIFY
                if not eligible:
                    warning = (
                        "SMALL SAMPLE: below the configured producer split "
                        "threshold; not air-ready."
                    )
                elif enrichment_mode == "developer_review":
                    warning = (
                        "Split row is available for developer review only; "
                        "producer approval is required."
                    )
                elif not producer_row_approved:
                    warning = (
                        "Split row did not pass the producer-approved load boundary."
                    )
                else:
                    warning = (
                        health_warning or "Split source approval is incomplete."
                    )
            record_identity = (
                f"split:{season}:{player_id}:{category}:{split_key}"
            )
            facts.append(
                _fact(
                    category=FactCategory.RECENT_TREND,
                    subject_type=FactSubjectType.PLAYER,
                    subject_id=player_id,
                    season=season,
                    game_id=game_id,
                    source_record_identity=record_identity,
                    concept_key=f"official-split:{category}:{split_key}",
                    headline=f"{name.upper()} — {split_label.upper()}",
                    air_copy=air_copy,
                    supporting_context=(
                        f"Official detailed split. "
                        f"{'Meets' if eligible else 'Below'} the configured sample threshold."
                    ),
                    subject_display_name=name,
                    team_code=team_code,
                    team_display_name=team_names.get(team_code) or team_code,
                    opponent_context=f"Game {game_id}",
                    provenance=(
                        SourceProvenance(
                            source_name,
                            source_url,
                            source_date=imported_at,
                            snapshot_timestamp=snapshot,
                            parser_version="phase7a-split-policy-v1",
                            source_record_id=record_identity,
                        ),
                    ),
                    verification_state=state,
                    source_health=health,
                    warning_reason=warning,
                    producer_confirmation_required=state
                    is not VerificationState.VERIFIED,
                    evidence=(
                        ("split_key", split_key),
                        ("split_label", split_label),
                        sample_evidence,
                        ("sample_eligible", eligible),
                    ),
                )
            )
    return facts


def _category(raw: Any) -> FactCategory:
    mapping = {
        "availability": FactCategory.AVAILABILITY,
        "injury": FactCategory.AVAILABILITY,
        "transaction": FactCategory.AVAILABILITY,
        "probable_starter": FactCategory.PROJECTED_STARTER,
        "confirmed_starter": FactCategory.CONFIRMED_STARTER,
        "milestone_reached": FactCategory.MILESTONE_REACHED,
        "milestone_watch": FactCategory.MILESTONE_WATCH,
        "recent_trend": FactCategory.RECENT_TREND,
        "season_context": FactCategory.SEASON_CONTEXT,
        "matchup_history": FactCategory.MATCHUP_HISTORY,
        "career_summary": FactCategory.CAREER_SUMMARY,
        "team_context": FactCategory.TEAM_CONTEXT,
        "background": FactCategory.BACKGROUND,
    }
    return mapping.get(_text(raw).casefold(), FactCategory.BACKGROUND)


_UNSAFE_NOTE_MARKERS = (
    "date opponent score/time",
    "statistics player c 1b 2b",
    "statistics team runs, game",
    "player c 1b 2b 3b ss lf cf rf",
)


def _official_note_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    snapshot: str,
) -> list[BroadcastFact]:
    if database.get("enrichment_enabled") is not True:
        return []
    frame = database.get("official_game_notes")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    game_id = _identifier(_field(selected_game, "game_id"))
    season = int(_field(selected_game, "season"))
    team_names = _selected_team_names(selected_game)
    team_codes = set(team_names)
    source_state, source_health, source_warning = _source_trust(
        database, "official_game_notes"
    )
    facts = []
    for _, row in frame.sort_index(kind="stable").iterrows():
        source_game_id = _identifier(
            row.get("source_game_id") or row.get("game_id")
        )
        if source_game_id != game_id:
            continue
        text = _text(row.get("note_text"))
        if not text or any(marker in text.casefold() for marker in _UNSAFE_NOTE_MARKERS):
            continue
        team_code = _text(row.get("subject_team_code")).upper()
        if team_code not in team_codes:
            continue
        player_id = _identifier(row.get("subject_player_id"))
        player_name = _text(row.get("subject_player_name"))
        if player_id:
            matches = roster[roster["_player_id"].eq(player_id)]
            if len(matches) != 1 or matches.iloc[0]["_team_code"] != team_code:
                continue
            player_name = player_name or _text(matches.iloc[0].get("player_name"))
        subject_type = FactSubjectType.PLAYER if player_id else FactSubjectType.TEAM
        subject_id = player_id or team_code
        subject_name = player_name or team_names.get(team_code) or team_code
        source_date = _text(row.get("source_date"))
        source_url = _text(row.get("source_url"))
        source_pdf = _text(row.get("source_pdf")) or (
            source_url.rsplit("/", 1)[-1].split("?", 1)[0] if source_url else ""
        )
        source_page = _identifier(row.get("source_page"))
        parser_version = _text(row.get("parser_version"))
        category = _category(row.get("note_category"))
        complete = bool(
            source_date
            and source_pdf
            and source_page
            and source_game_id == game_id
            and team_code in team_codes
        )
        raw_state = _text(row.get("verification_state")).upper()
        approved = _bool_false(row.get("needs_review"))
        enrichment_mode = _text(database.get("enrichment_mode")).casefold()
        if enrichment_mode == "producer_approved":
            approved = (
                approved
                and row.get("producer_approved") is True
                and row.get("producer_air_ready") is True
            )
        elif enrichment_mode == "developer_review":
            approved = False
        if (
            raw_state == "VERIFIED"
            and approved
            and complete
            and source_state is VerificationState.VERIFIED
        ):
            state = VerificationState.VERIFIED
            warning = ""
        elif raw_state == "STALE" or source_state is VerificationState.STALE:
            state = VerificationState.STALE
            warning = source_warning or "Official note is marked stale."
        elif source_state is VerificationState.UNAVAILABLE:
            state = VerificationState.UNAVAILABLE
            warning = source_warning
        else:
            state = VerificationState.VERIFY
            warning = "Official note requires exact-game source and review approval."
        if category is FactCategory.PROJECTED_STARTER:
            state = VerificationState.VERIFY
            warning = "Projected/probable starter is not an official confirmed starter."
        record_identity = (
            f"official-note:{game_id}:{source_pdf}:{source_page}:"
            f"{subject_id}:{category.value}"
        )
        opposing = (
            _text(_field(selected_game, "home_team_code")).upper()
            if team_code == _text(_field(selected_game, "away_team_code")).upper()
            else _text(_field(selected_game, "away_team_code")).upper()
        )
        facts.append(
            _fact(
                category=category,
                subject_type=subject_type,
                subject_id=subject_id,
                season=season,
                game_id=game_id,
                source_record_identity=record_identity,
                concept_key=f"official-note:{category.value}:{source_pdf}:{source_page}",
                headline=f"{subject_name.upper()} — {category.value.replace('_', ' ').upper()}",
                air_copy=text,
                supporting_context="Exact-game official-note item.",
                subject_display_name=subject_name,
                team_code=team_code,
                team_display_name=team_names.get(team_code) or team_code,
                opponent_context=f"vs {opposing}, Game {game_id}",
                provenance=(
                    SourceProvenance(
                        "Official AUSL Game Notes",
                        source_url or f"local:{source_pdf}",
                        source_date=source_date or None,
                        source_page=source_page or None,
                        source_game_id=game_id,
                        snapshot_timestamp=snapshot,
                        parser_version=parser_version or None,
                        source_record_id=record_identity,
                    ),
                ),
                verification_state=state,
                source_health=source_health,
                warning_reason=warning,
                producer_confirmation_required=not state
                is VerificationState.VERIFIED,
                readiness_blocking=category
                in {FactCategory.AVAILABILITY, FactCategory.CONFIRMED_STARTER},
                evidence=(
                    ("normalized_hash", _text(row.get("normalized_hash"))),
                    ("verification_state", raw_state),
                    ("needs_review", _text(row.get("needs_review"))),
                    ("confidence_score", _text(row.get("confidence_score"))),
                ),
            )
        )
    return facts


def _resolve_lineup_pitcher(
    value: Any, roster: pd.DataFrame, team_code: str
) -> pd.Series | None:
    if isinstance(value, Mapping):
        identity = _identifier(value.get("player_id"))
        name = _text(value.get("player_name"))
    else:
        identity = _identifier(value)
        name = _text(value)
    matches = roster[roster["_team_code"].eq(team_code)]
    if identity:
        by_id = matches[matches["_player_id"].eq(identity)]
        if len(by_id) == 1:
            return by_id.iloc[0]
    if name:
        by_name = matches[
            matches["player_name"].map(_text).str.casefold().eq(name.casefold())
        ]
        if len(by_name) == 1:
            return by_name.iloc[0]
    return None


def _lineup_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    lineup_lock: Mapping[str, Any] | None,
    snapshot: str,
) -> list[BroadcastFact]:
    if not isinstance(lineup_lock, Mapping):
        return []
    game_id = _identifier(_field(selected_game, "game_id"))
    if _identifier(lineup_lock.get("game_id")) != game_id:
        return []
    lineups = lineup_lock.get("lineups")
    if not isinstance(lineups, Mapping):
        return []
    season = int(_field(selected_game, "season"))
    source = _text(lineup_lock.get("source")).casefold()
    official = source == "official"
    approval = lineup_lock.get("official_provenance")
    approval_complete = bool(
        official
        and isinstance(approval, Mapping)
        and approval.get("verified") is True
        and all(
            _text(approval.get(key))
            for key in ("source_name", "source_id", "verified_at", "verified_by")
        )
    )
    roster_state, roster_health, roster_warning = _source_trust(
        database, "official_rosters"
    )
    team_info = (
        (
            "away",
            _text(_field(selected_game, "away_team_code")).upper(),
            _text(_field(selected_game, "away_team")),
            _text(_field(selected_game, "home_team_code")).upper(),
        ),
        (
            "home",
            _text(_field(selected_game, "home_team_code")).upper(),
            _text(_field(selected_game, "home_team")),
            _text(_field(selected_game, "away_team_code")).upper(),
        ),
    )
    facts = []
    for side, team_code, team_name, opponent in team_info:
        team = lineups.get(side)
        if not isinstance(team, Mapping):
            continue
        player = _resolve_lineup_pitcher(team.get("starting_pitcher"), roster, team_code)
        if player is None:
            continue
        player_id = player["_player_id"]
        player_name = _text(player.get("player_name"))
        if approval_complete:
            category = FactCategory.CONFIRMED_STARTER
            state = roster_state
            warning = roster_warning
            source_name = _text(approval.get("source_name"))
            source_reference = _text(approval.get("source_id"))
            approval_id = source_reference
            source_date = _text(approval.get("verified_at"))
        else:
            category = FactCategory.PROJECTED_STARTER
            state = VerificationState.VERIFY
            if official:
                warning = (
                    "Official starter claim lacks complete approval provenance."
                )
            else:
                warning = (
                    roster_warning
                    or "Saved projected/manual/imported starter is not official."
                )
            source_name = f"{source.title() or 'Saved'} lineup"
            source_reference = (
                f"local:locked_lineups.json#game={game_id}&side={side}"
            )
            approval_id = None
            source_date = _text(lineup_lock.get("locked_at"))
        label = "is the confirmed starter" if category is FactCategory.CONFIRMED_STARTER else "is the projected starter"
        facts.append(
            _fact(
                category=category,
                subject_type=FactSubjectType.PLAYER,
                subject_id=player_id,
                season=season,
                game_id=game_id,
                source_record_identity=f"lineup:{game_id}:{side}:starting-pitcher",
                concept_key=f"{side}-starting-pitcher",
                headline=f"{player_name.upper()} — {'CONFIRMED' if category is FactCategory.CONFIRMED_STARTER else 'PROJECTED'} STARTER",
                air_copy=f"{player_name} {label} for {team_name} in Game {game_id}.",
                supporting_context="Starter identity comes from the exact selected-game lineup.",
                subject_display_name=player_name,
                team_code=team_code,
                team_display_name=team_name,
                opponent_context=f"vs {opponent}, Game {game_id}",
                provenance=(
                    SourceProvenance(
                        source_name,
                        source_reference,
                        source_date=source_date or None,
                        source_game_id=game_id,
                        snapshot_timestamp=snapshot,
                        approval_record_id=approval_id,
                        source_record_id=f"lineup:{game_id}:{side}:starting-pitcher",
                    ),
                ),
                verification_state=state,
                source_health=roster_health,
                warning_reason=warning,
                producer_confirmation_required=state
                is not VerificationState.VERIFIED,
                readiness_blocking=True,
                evidence=(
                    ("lineup_source", source),
                    ("player_id", player_id),
                    ("revision", _text(lineup_lock.get("revision"))),
                    ("approval_complete", str(approval_complete)),
                ),
            )
        )
    return facts


def _manual_note_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    snapshot: str,
) -> list[BroadcastFact]:
    frame = database.get("manual_notes")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    game_id = _identifier(_field(selected_game, "game_id"))
    season = int(_field(selected_game, "season"))
    team_names = _selected_team_names(selected_game)
    team_codes = set(team_names)
    facts = []
    for _, row in frame.sort_index(kind="stable").iterrows():
        note_id = _identifier(row.get("note_id"))
        note_text = _text(row.get("note_text"))
        scope = _text(row.get("scope")).casefold()
        player_id = _identifier(row.get("player_id"))
        team_code = _text(row.get("team_code")).upper()
        row_game_id = _identifier(row.get("game_id"))
        if not note_id or not note_text or scope not in {"player", "team", "game"}:
            continue
        subject_type = FactSubjectType.GAME
        subject_id = game_id
        subject_name = f"Game {game_id}"
        if scope == "player":
            matches = roster[roster["_player_id"].eq(player_id)]
            if len(matches) != 1:
                continue
            player = matches.iloc[0]
            if player["_team_code"] not in team_codes:
                continue
            team_code = player["_team_code"]
            subject_type = FactSubjectType.PLAYER
            subject_id = player_id
            subject_name = _text(player.get("player_name"))
        elif scope == "team":
            if team_code not in team_codes:
                continue
            subject_type = FactSubjectType.TEAM
            subject_id = team_code
            subject_name = team_names.get(team_code) or team_code
        elif row_game_id != game_id:
            continue
        author = _text(row.get("author") or row.get("entered_by"))
        verified_date = _text(row.get("last_verified_date"))
        note_type = _text(row.get("note_type")).casefold()
        category = (
            FactCategory.AVAILABILITY
            if any(item in note_type for item in ("availability", "injury", "transaction"))
            else FactCategory.MANUAL_NOTE
        )
        do_not_use = "do not use" in note_text.casefold() or "do_not_use" in note_type
        safe = _bool_true(row.get("air_safe")) and bool(author and verified_date) and not do_not_use
        if do_not_use:
            state = VerificationState.UNAVAILABLE
            warning = "Producer note is marked do not use."
        elif safe:
            state = VerificationState.VERIFIED
            warning = ""
        else:
            state = VerificationState.VERIFY
            warning = "Manual note requires air-safe approval, reviewer, and verification date."
        updated = _text(row.get("updated_at") or row.get("created_at")) or snapshot
        source_name = _text(row.get("source")) or "Manual producer note"
        facts.append(
            _fact(
                category=category,
                subject_type=subject_type,
                subject_id=subject_id,
                season=season,
                game_id=game_id,
                source_record_identity=f"manual-note:{note_id}",
                concept_key=f"manual-note:{note_id}",
                headline=f"{subject_name.upper()} — PRODUCER NOTE",
                air_copy=note_text,
                supporting_context=f"Manual producer note scoped to {scope}.",
                subject_display_name=subject_name,
                team_code=team_code or None,
                team_display_name=team_names.get(team_code) if team_code else None,
                opponent_context=f"Game {game_id}",
                provenance=(
                    SourceProvenance(
                        source_name,
                        f"local:manual-note:{note_id}",
                        source_date=verified_date or updated,
                        source_game_id=game_id if scope == "game" else None,
                        snapshot_timestamp=updated,
                        approval_record_id=note_id if safe else None,
                        source_record_id=note_id,
                    ),
                ),
                verification_state=state,
                source_health="green",
                warning_reason=warning,
                producer_confirmation_required=not safe,
                readiness_blocking=category is FactCategory.AVAILABILITY,
                evidence=(
                    ("scope", scope),
                    ("author", author),
                    ("verified_date", verified_date),
                    ("air_safe", str(_bool_true(row.get("air_safe")))),
                ),
            )
        )
    return facts


def _media_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    roster: pd.DataFrame,
    snapshot: str,
    validator: Callable[..., str] | None,
) -> list[BroadcastFact]:
    if database.get("enrichment_enabled") is not True:
        return []
    frame = database.get("media_players")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    season = int(_field(selected_game, "season"))
    game_id = _identifier(_field(selected_game, "game_id"))
    team_names = _selected_team_names(selected_game)
    source_state, source_health, source_warning = _source_trust(
        database, "media_guide"
    )
    facts = []
    for _, row in frame.sort_index(kind="stable").iterrows():
        if _text(row.get("match_status")).casefold() == "not_in_guide":
            continue
        player_id = _identifier(row.get("entity_id") or row.get("player_id"))
        matches = roster[roster["_player_id"].eq(player_id)]
        if len(matches) != 1:
            continue
        player = matches.iloc[0]
        team_code = player["_team_code"]
        text = _text(
            row.get("media_guide_bio")
            or row.get("note_text")
            or row.get("bio_text")
        )
        if not text:
            continue
        warning_value = _text(row.get("warnings"))
        approval_state = (
            _text(
                validator(
                    row,
                    expected_entity_type="player",
                    expected_entity_id=player_id,
                )
            ).upper()
            if validator is not None
            else "VERIFY"
        )
        source_name = _text(row.get("source_name"))
        source_url = _text(row.get("source_url"))
        guide_date = _text(row.get("guide_date"))
        printed_page = _text(row.get("expected_printed_pages"))
        parsed_page = _text(row.get("parsed_pdf_pages"))
        approval_id = _text(row.get("approval_record_id"))
        complete = bool(
            source_name
            and source_url
            and guide_date
            and printed_page
            and parsed_page
            and approval_id
            and not warning_value
        )
        enrichment_mode = _text(database.get("enrichment_mode")).casefold()
        if enrichment_mode == "producer_approved":
            complete = (
                complete
                and row.get("producer_approved") is True
                and row.get("producer_air_ready") is True
            )
        elif enrichment_mode == "developer_review":
            approval_state = "VERIFY"
        if (
            approval_state == "VERIFIED"
            and complete
            and source_state is VerificationState.VERIFIED
        ):
            state = VerificationState.VERIFIED
            warning = ""
        elif source_state is VerificationState.STALE:
            state = VerificationState.STALE
            warning = source_warning
        elif source_state is VerificationState.UNAVAILABLE:
            state = VerificationState.UNAVAILABLE
            warning = source_warning
        else:
            state = VerificationState.VERIFY
            warning = warning_value or "Media-guide approval or page identity is incomplete."
        record_identity = f"media-guide:player:{player_id}:{printed_page or parsed_page}"
        facts.append(
            _fact(
                category=FactCategory.BACKGROUND,
                subject_type=FactSubjectType.PLAYER,
                subject_id=player_id,
                season=season,
                game_id=game_id,
                source_record_identity=record_identity,
                concept_key=f"media-guide-biography:{printed_page or parsed_page}",
                headline=f"{_text(player.get('player_name')).upper()} — BACKGROUND",
                air_copy=text,
                supporting_context="Approved media-guide background.",
                subject_display_name=_text(player.get("player_name")),
                team_code=team_code,
                team_display_name=team_names.get(team_code) or team_code,
                opponent_context=f"Game {game_id}",
                provenance=(
                    SourceProvenance(
                        source_name or "AUSL Media Guide",
                        source_url or "local:media-guide",
                        source_date=guide_date or None,
                        source_page=printed_page or parsed_page or None,
                        snapshot_timestamp=snapshot,
                        parser_version=_text(row.get("parser_version")) or None,
                        approval_record_id=approval_id or None,
                        source_record_id=record_identity,
                    ),
                ),
                verification_state=state,
                source_health=source_health,
                warning_reason=warning,
                producer_confirmation_required=state
                is not VerificationState.VERIFIED,
                evidence=(
                    ("approval_record_id", approval_id),
                    ("printed_page", printed_page),
                    ("parsed_page", parsed_page),
                    ("warnings", warning_value),
                ),
            )
        )
    return facts


def _team_context_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    snapshot: str,
    provider: Callable[[str, int], Any] | None,
) -> list[BroadcastFact]:
    if provider is None:
        return []
    season = int(_field(selected_game, "season"))
    game_id = _identifier(_field(selected_game, "game_id"))
    team_names = _selected_team_names(selected_game)
    state, health, warning = _source_trust(database, "official_standings")
    facts = []
    for code in (
        _text(_field(selected_game, "away_team_code")).upper(),
        _text(_field(selected_game, "home_team_code")).upper(),
    ):
        snapshot_value = provider(code, season)
        if not bool(_field(snapshot_value, "available", False)):
            continue
        wins = _number(_field(snapshot_value, "wins"), integer=True)
        losses = _number(_field(snapshot_value, "losses"), integer=True)
        if wins is None or losses is None:
            continue
        name = team_names.get(code) or code
        source_name = _text(_field(snapshot_value, "source_name"))
        source_timestamp = _text(_field(snapshot_value, "source_timestamp"))
        source_url = _text(_field(snapshot_value, "source_url"))
        facts.append(
            _fact(
                category=FactCategory.TEAM_CONTEXT,
                subject_type=FactSubjectType.TEAM,
                subject_id=code,
                season=season,
                game_id=game_id,
                source_record_identity=f"standings:{season}:{code}",
                concept_key=f"{season}-official-record",
                headline=f"{name.upper()} — OFFICIAL RECORD",
                air_copy=f"{name} enters Game {game_id} with an official {wins}-{losses} record.",
                supporting_context="Official standings record; not calculated pitcher decisions.",
                subject_display_name=name,
                team_code=code,
                team_display_name=name,
                opponent_context=f"Game {game_id}",
                provenance=(
                    SourceProvenance(
                        source_name or "Official AUSL Standings",
                        source_url
                        or _source_reference(
                            database,
                            "official_standings",
                            "local:ausl_team_context.xlsx",
                        ),
                        source_date=source_timestamp or snapshot,
                        snapshot_timestamp=snapshot,
                        source_record_id=f"standings:{season}:{code}",
                    ),
                ),
                verification_state=state,
                source_health=health,
                warning_reason=warning,
                evidence=(("wins", wins), ("losses", losses)),
            )
        )
    return facts


def _validated_college_artifact(
    artifact: ApprovedCollegeArtifact | ApprovedAggregateArtifact | None,
) -> ApprovedCollegeArtifact | ApprovedAggregateArtifact | None:
    try:
        if isinstance(artifact, ApprovedAggregateArtifact):
            return validate_aggregate_approval(
                artifact.envelope_payload, artifact.manifest_payload
            )
        if isinstance(artifact, ApprovedCollegeArtifact):
            return validate_approved_payload(
                artifact.envelope_payload, artifact.manifest_payload
            )
    except (OSError, ValueError):
        return None
    return None


def build_college_connection_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    *,
    college_artifact: ApprovedCollegeArtifact | ApprovedAggregateArtifact | None,
    connection_approval: ApprovedConnectionArtifact | None,
    maximum_facts: int = 3,
    maximum_per_player: int = 2,
) -> list[BroadcastFact]:
    """Adapt only validated, approved college connections to BroadcastFact.

    The adapter is local-only.  It revalidates both approval byte sets, checks
    every connection subject against the current exact-ID roster, and applies
    bounded Game Day diversity without changing the underlying connection.
    """

    if maximum_facts < 1 or maximum_per_player < 1:
        return []
    college = _validated_college_artifact(college_artifact)
    if college is None or connection_approval is None:
        return []
    try:
        approved = validate_connection_approval(
            connection_approval.candidate_payload,
            connection_approval.manifest_payload,
        )
    except (OSError, ValueError):
        return []
    game_id = _identifier(_field(selected_game, "game_id"))
    season_value = _number(_field(selected_game, "season"), integer=True)
    if not game_id or season_value is None:
        return []
    season = int(season_value)
    away_code = _text(_field(selected_game, "away_team_code")).upper()
    home_code = _text(_field(selected_game, "home_team_code")).upper()
    team_order = tuple(code for code in (away_code, home_code) if code)
    if len(set(team_order)) != 2:
        return []
    roster = database.get("roster") if isinstance(database, Mapping) else None
    required = {"player_id", "player_name", "team_code", "roster_status"}
    if not isinstance(roster, pd.DataFrame) or not required.issubset(roster.columns):
        return []
    rows_by_player: dict[str, pd.Series] = {}
    duplicate_ids: set[str] = set()
    for _, row in roster.iterrows():
        player_id = _identifier(row.get("player_id"))
        if not player_id:
            continue
        if player_id in rows_by_player:
            duplicate_ids.add(player_id)
        else:
            rows_by_player[player_id] = row
    source_by_id = {source.source_id: source for source in college.envelope.sources}
    snapshot = college.envelope.generated_at.astimezone(timezone.utc).isoformat()
    team_names = _selected_team_names(selected_game)
    approval_record_prefix = (
        f"{approved.manifest.approval_schema_name}:"
        f"{approved.manifest.approved_candidate_sha256}"
    )
    proposed: list[tuple[BroadcastFact, tuple[str, ...], tuple[str, ...], int]] = []
    for candidate in approved.connections.candidates:
        if not candidate.air_ready:
            continue
        if any(
            player_id in duplicate_ids or player_id not in rows_by_player
            for player_id in candidate.subject_player_ids
        ):
            continue
        subject_rows = tuple(
            rows_by_player[player_id] for player_id in candidate.subject_player_ids
        )
        subject_team_codes = tuple(
            _text(row.get("team_code")).upper() for row in subject_rows
        )
        relevant_teams = tuple(
            code for code in team_order if code in subject_team_codes
        )
        if not relevant_teams:
            continue
        used_sources = tuple(
            source_by_id[source_id]
            for source_id in candidate.evidence_source_ids
            if source_id in source_by_id
        )
        if (
            len(used_sources) != len(candidate.evidence_source_ids)
            or any(source.verification_state != "verified" for source in used_sources)
        ):
            continue
        statuses = tuple(normalize_roster_status(row.get("roster_status")) for row in subject_rows)
        inactive = tuple(
            candidate.subject_display_names[index]
            for index, status in enumerate(statuses)
            if status != "Active"
        )
        warning = (
            "Current roster status requires verification for " + ", ".join(inactive) + "."
            if inactive
            else ""
        )
        state = VerificationState.VERIFY if warning else VerificationState.VERIFIED
        provenance = tuple(
            SourceProvenance(
                source_name=f"{source.organization} — {source.title}",
                source_reference=(
                    source.url
                    or source.local_document_id
                    or f"local:college-source:{source.source_id}"
                ),
                source_date=(
                    source.effective_date
                    or source.retrieved_at.astimezone(timezone.utc).date().isoformat()
                ),
                source_page=source.locator or None,
                snapshot_timestamp=snapshot,
                parser_version=source.version,
                approval_record_id=(
                    f"{approval_record_prefix}:{candidate.connection_id}"
                ),
                source_record_id=(
                    f"{candidate.connection_id}:{source.source_id}"
                ),
            )
            for source in used_sources
        )
        primary_team = relevant_teams[0]
        display_names = " / ".join(candidate.subject_display_names)
        program_season = " · ".join(
            value
            for value in (
                " / ".join(candidate.program_display_names),
                " / ".join(candidate.season_scope),
            )
            if value
        )
        fact = _fact(
            category=FactCategory.COLLEGE_CONNECTION,
            subject_type=FactSubjectType.PLAYER,
            subject_id="+".join(candidate.subject_player_ids),
            season=season,
            game_id=game_id,
            source_record_identity=candidate.connection_id,
            concept_key=f"college-connection:{candidate.connection_type.value}",
            headline=f"COLLEGE CONNECTION — {display_names.upper()}",
            air_copy=candidate.wording,
            supporting_context=(
                f"Approved college connection · {program_season}"
                if program_season
                else "Approved college connection."
            ),
            subject_display_name=display_names,
            team_code=primary_team,
            team_display_name=team_names.get(primary_team) or primary_team,
            opponent_context=f"Game {game_id} · {away_code} vs {home_code}",
            provenance=provenance,
            verification_state=state,
            source_health="green",
            warning_reason=warning,
            producer_confirmation_required=bool(warning),
            readiness_blocking=False,
            evidence=(
                ("approved_connection_sha256", approved.manifest.approved_candidate_sha256),
                ("connection_evidence_hash", candidate.evidence_version_hash),
                ("connection_id", candidate.connection_id),
                ("connection_type", candidate.connection_type.value),
                ("program_ids", ",".join(candidate.program_ids)),
                ("season_scope", ",".join(candidate.season_scope)),
                ("source_record_ids", ",".join(candidate.evidence_record_ids)),
                ("subject_player_ids", ",".join(candidate.subject_player_ids)),
                ("subject_team_codes", ",".join(subject_team_codes)),
            ),
        )
        proposed.append(
            (fact, candidate.subject_player_ids, relevant_teams, candidate.priority_score)
        )

    remaining = sorted(
        proposed,
        key=lambda item: (
            -len(item[2]),
            -item[3],
            item[0].source_record_identity,
        ),
    )
    selected: list[BroadcastFact] = []
    player_counts: dict[str, int] = {}
    team_counts = {code: 0 for code in team_order}
    while remaining and len(selected) < maximum_facts:
        eligible = [
            item
            for item in remaining
            if all(
                player_counts.get(player_id, 0) < maximum_per_player
                for player_id in item[1]
            )
        ]
        if not eligible:
            break
        choice = min(
            eligible,
            key=lambda item: (
                -len(item[2]),
                min(team_counts[code] for code in item[2]),
                -item[3],
                item[0].source_record_identity,
            ),
        )
        remaining.remove(choice)
        selected.append(choice[0])
        for player_id in choice[1]:
            player_counts[player_id] = player_counts.get(player_id, 0) + 1
        for code in choice[2]:
            team_counts[code] += 1
    return selected


def build_selected_game_facts(
    database: Mapping[str, Any],
    selected_game: Any,
    *,
    lineup_lock: Mapping[str, Any] | None = None,
    media_approval_validator: Callable[..., str] | None = None,
    team_snapshot_provider: Callable[[str, int], Any] | None = None,
    college_artifact: ApprovedCollegeArtifact | ApprovedAggregateArtifact | None = None,
    connection_approval: ApprovedConnectionArtifact | None = None,
) -> FactCollection:
    """Build one deterministic, exact-game fact collection without I/O."""

    game_id = _identifier(_field(selected_game, "game_id"))
    if not game_id:
        return FactCollection("", "", "", (), False, "No game selected.")
    if not isinstance(database, Mapping):
        return FactCollection(
            game_id, "", "", (), False, "Source data is unavailable."
        )
    manifest = database.get("manifest")
    snapshot = _text(manifest.get("updated_at") if isinstance(manifest, Mapping) else "")
    team_codes = {
        _text(_field(selected_game, "away_team_code")).upper(),
        _text(_field(selected_game, "home_team_code")).upper(),
    }
    if "" in team_codes or len(team_codes) != 2:
        return FactCollection(
            game_id,
            snapshot,
            "",
            (),
            False,
            "Selected-game team identity is unavailable.",
        )
    roster = _roster_rows(database, team_codes)
    if roster.empty:
        return FactCollection(
            game_id,
            snapshot,
            "",
            (),
            False,
            "Source data for selected-game rosters is unavailable.",
        )
    facts = [
        *_official_stats_facts(database, selected_game, roster, snapshot),
        *_split_stat_facts(database, selected_game, roster, snapshot),
        *_lineup_facts(
            database, selected_game, roster, lineup_lock, snapshot
        ),
        *_official_note_facts(database, selected_game, roster, snapshot),
        *_media_facts(
            database,
            selected_game,
            roster,
            snapshot,
            media_approval_validator,
        ),
        *_manual_note_facts(database, selected_game, roster, snapshot),
        *_team_context_facts(
            database, selected_game, snapshot, team_snapshot_provider
        ),
        *build_college_connection_facts(
            database,
            selected_game,
            college_artifact=college_artifact,
            connection_approval=connection_approval,
        ),
    ]
    facts = order_facts(
        deduplicate_facts(facts),
        team_codes=(
            _text(_field(selected_game, "away_team_code")).upper(),
            _text(_field(selected_game, "home_team_code")).upper(),
        ),
    )
    database_version = _hash(
        {
            "snapshot": snapshot,
            "game_id": game_id,
            "facts": [(item.fact_id, item.evidence_hash) for item in facts],
        }
    )
    reason = ""
    if not facts:
        reason = "No safe facts are available for the selected game."
    return FactCollection(
        game_id=game_id,
        snapshot_timestamp=snapshot,
        database_version=database_version,
        facts=tuple(facts),
        available=True,
        empty_reason=reason,
    )
