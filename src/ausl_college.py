"""Phase 7B college résumé foundation.

This module is deliberately independent of Tk, application startup, refresh,
and distribution code.  It accepts reviewed evidence; it never collects or
promotes data.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_NAME = "ausl-college-resume"
SCHEMA_VERSION = 1
CORE_RESUME_V1 = "CORE_RESUME_V1"
MAX_PAYLOAD_BYTES = 5_000_000
MAX_COLLECTION_ITEMS = 10_000
MAX_STRING_LENGTH = 20_000
MAX_NESTING_DEPTH = 24


class UnsupportedSchemaVersion(ValueError):
    pass


class SourceType(str, Enum):
    OFFICIAL_AUSL_PROFILE = "official_ausl_player_profile"
    NCAA_STATISTICS = "ncaa_statistics"
    OFFICIAL_SCHOOL = "official_school_athletics"
    MANUAL_VERIFIED = "explicit_manually_verified"


class IdentityReviewState(str, Enum):
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    NEEDS_REVIEW = "needs_review"


class ValueState(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED_CONFLICT = "unresolved_conflict"


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"
    INCOMPATIBLE = "incompatible"


class CompletenessState(str, Enum):
    VERIFIED = "Verified"
    PARTIAL = "Partial"
    NEEDS_REVIEW = "Needs Review"


class PlayerRole(str, Enum):
    HITTER = "hitter"
    PITCHER = "pitcher"
    TWO_WAY = "two_way"


class SeasonKind(str, Enum):
    STANDARD = "standard"
    REDSHIRT = "redshirt"
    SHORTENED = "shortened"
    EXTRA_ELIGIBILITY = "extra_eligibility"
    UNKNOWN = "unknown"


class StatRecordType(str, Enum):
    SEASON_BATTING = "season_batting"
    SEASON_PITCHING = "season_pitching"
    SOURCE_CAREER_BATTING = "source_career_batting"
    SOURCE_CAREER_PITCHING = "source_career_pitching"
    DERIVED_CAREER_BATTING = "derived_career_batting"
    DERIVED_CAREER_PITCHING = "derived_career_pitching"


class AchievementType(str, Enum):
    HONOR = "honor"
    RECORD = "record"
    CONFERENCE_AWARD = "conference_award"
    NATIONAL_AWARD = "national_award"
    WCWS_APPEARANCE = "wcws_appearance"
    WCWS_RESULT = "wcws_result"
    CHAMPIONSHIP = "championship"
    POSTSEASON = "postseason"


def _required(value: Any, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > MAX_STRING_LENGTH:
        raise ValueError(f"{label} exceeds the safe string limit")
    return text


def _optional(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required(value, label)


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def _tuple_limit(values: Iterable[Any], label: str) -> tuple[Any, ...]:
    result = tuple(values)
    if len(result) > MAX_COLLECTION_ITEMS:
        raise ValueError(f"{label} exceeds the safe collection limit")
    return result


@dataclass(frozen=True)
class SourceProvenance:
    source_id: str
    source_type: SourceType
    organization: str
    title: str
    locator: str
    retrieved_at: datetime
    version: str
    verification_state: str
    url: str | None = None
    local_document_id: str | None = None
    effective_date: str | None = None
    content_hash: str | None = None
    reviewer: str | None = None
    approved_at: datetime | None = None
    review_note: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        for name in ("organization", "title", "locator", "version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        for name in ("url", "local_document_id", "effective_date", "content_hash", "reviewer", "review_note"):
            object.__setattr__(self, name, _optional(getattr(self, name), name))
        state = _required(self.verification_state, "verification_state").casefold()
        if state not in {"verified", "unavailable", "needs_review"}:
            raise ValueError("unsupported provenance verification_state")
        object.__setattr__(self, "verification_state", state)
        if self.approved_at is not None:
            object.__setattr__(self, "approved_at", _utc(self.approved_at, "approved_at"))
        if self.source_type is SourceType.MANUAL_VERIFIED and state == "verified":
            if not all((self.reviewer, self.approved_at, self.review_note, self.url or self.local_document_id)):
                raise ValueError("verified manual source requires reviewer, approval time, reason, and evidence reference")


@dataclass(frozen=True)
class IdentityMapping:
    mapping_id: str
    ausl_player_id: str
    source_id: str
    source_athlete_id: str | None
    aliases: tuple[str, ...]
    review_state: IdentityReviewState
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    evidence_reference: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "mapping_id", _required(self.mapping_id, "mapping_id"))
        object.__setattr__(self, "ausl_player_id", _required(self.ausl_player_id, "AUSL player_id"))
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "source_athlete_id", _optional(self.source_athlete_id, "source_athlete_id"))
        object.__setattr__(self, "aliases", tuple(_required(v, "alias") for v in _tuple_limit(self.aliases, "aliases")))
        object.__setattr__(self, "review_state", IdentityReviewState(self.review_state))
        if self.reviewed_at is not None:
            object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at, "reviewed_at"))
        if self.review_state is IdentityReviewState.VERIFIED and not all((self.source_athlete_id, self.reviewer, self.reviewed_at, self.evidence_reference)):
            raise ValueError("verified identity requires source athlete ID, reviewer, time, and evidence")


@dataclass(frozen=True)
class Program:
    program_id: str
    display_name: str
    source_ids: tuple[str, ...]
    source_identifiers: tuple[tuple[str, str], ...] = ()
    historical_names: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "program_id", _required(self.program_id, "program_id"))
        object.__setattr__(self, "display_name", _required(self.display_name, "program display_name"))
        sources = tuple(_required(v, "program source_id") for v in _tuple_limit(self.source_ids, "program sources"))
        if not sources:
            raise ValueError("program requires field-level provenance")
        object.__setattr__(self, "source_ids", sources)
        object.__setattr__(self, "source_identifiers", tuple(( _required(a, "source_id"), _required(b, "school identifier")) for a, b in self.source_identifiers))
        object.__setattr__(self, "historical_names", tuple(_required(v, "historical name") for v in self.historical_names))


@dataclass(frozen=True)
class ProgramStint:
    stint_id: str
    program_id: str
    transfer_order: int
    start_season: int | None
    end_season: int | None
    provenance_ids: tuple[str, ...]
    season_kinds: tuple[tuple[int, SeasonKind], ...] = ()
    uncertainty_note: str | None = None

    def __post_init__(self):
        for name in ("stint_id", "program_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if isinstance(self.transfer_order, bool) or self.transfer_order < 1:
            raise ValueError("transfer_order must be a positive integer")
        for name in ("start_season", "end_season"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1800):
                raise ValueError(f"{name} must be an exact season or unavailable")
        object.__setattr__(self, "season_kinds", tuple((int(year), SeasonKind(kind)) for year, kind in self.season_kinds))
        object.__setattr__(self, "provenance_ids", tuple(_required(v, "stint provenance") for v in self.provenance_ids))
        object.__setattr__(self, "uncertainty_note", _optional(self.uncertainty_note, "uncertainty_note"))
        if self.start_season is None and not self.uncertainty_note:
            raise ValueError("unknown stint dates require an uncertainty note")


def _number(value: Any) -> int | Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a statistical value")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("statistical values must be finite")
        raise ValueError("binary floating-point values are not persisted; use Decimal")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("statistical values must be finite")
        return value
    raise ValueError("statistical value must be an exact integer or Decimal")


@dataclass(frozen=True)
class CandidateValue:
    candidate_id: str
    field_path: str
    value: int | Decimal | None
    value_state: ValueState
    source_id: str
    player_id: str
    program_id: str | None
    season: int | None
    record_type: str
    metric_definition: str
    unit: str

    def __post_init__(self):
        for name in ("candidate_id", "field_path", "source_id", "player_id", "record_type", "metric_definition", "unit"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "program_id", _optional(self.program_id, "program_id"))
        object.__setattr__(self, "value_state", ValueState(self.value_state))
        if "ausl" in self.metric_definition.casefold() or "ausl" in self.field_path.casefold():
            raise ValueError("college metrics must remain in college scope")
        value = _number(self.value)
        if self.value_state is ValueState.PRESENT and value is None:
            raise ValueError("present candidate requires a value")
        if self.value_state is not ValueState.PRESENT and value is not None:
            raise ValueError("missing/unavailable candidates cannot contain a value")
        if self.unit == "count" and value is not None and not isinstance(value, int):
            raise ValueError("count metrics require exact integers")
        object.__setattr__(self, "value", value)

    @property
    def dimensions(self) -> tuple[Any, ...]:
        return (self.field_path, self.player_id, self.program_id, self.season, self.record_type, self.metric_definition, self.unit)


@dataclass(frozen=True)
class ManualResolution:
    selected_candidate_id: str
    reviewer: str
    resolved_at: datetime
    reason: str
    evidence_source_id: str

    def __post_init__(self):
        for name in ("selected_candidate_id", "reviewer", "reason", "evidence_source_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "resolved_at", _utc(self.resolved_at, "resolved_at"))


@dataclass(frozen=True)
class ResolutionResult:
    state: ResolutionState
    candidates: tuple[CandidateValue, ...]
    selected_candidate_id: str | None
    selected_value: int | Decimal | None
    rejected_candidate_ids: tuple[str, ...]
    reason: str
    manual_resolution: ManualResolution | None = None


_SOURCE_PRIORITY = {kind: index for index, kind in enumerate(SourceType)}


def resolve_candidates(candidates: Sequence[CandidateValue], sources: Mapping[str, SourceProvenance], *, manual_resolution: ManualResolution | None = None) -> ResolutionResult:
    values = tuple(candidates)
    if not values:
        return ResolutionResult(ResolutionState.UNAVAILABLE, (), None, None, (), "No candidate values are available.")
    if len({item.candidate_id for item in values}) != len(values):
        raise ValueError("duplicate candidate_id")
    if any(item.source_id not in sources or sources[item.source_id].verification_state != "verified" for item in values):
        return ResolutionResult(ResolutionState.UNAVAILABLE, values, None, None, (), "Candidate provenance is missing or unverified.")
    if len({item.dimensions for item in values}) != 1:
        return ResolutionResult(ResolutionState.INCOMPATIBLE, values, None, None, (), "Candidate dimensions differ and cannot be compared.")
    present = tuple(item for item in values if item.value_state is ValueState.PRESENT)
    if not present:
        return ResolutionResult(ResolutionState.UNAVAILABLE, values, None, None, (), "No present candidate value is available.")
    if manual_resolution is not None:
        selected = next((item for item in present if item.candidate_id == manual_resolution.selected_candidate_id), None)
        evidence = sources.get(manual_resolution.evidence_source_id)
        if selected is None or evidence is None or evidence.verification_state != "verified":
            raise ValueError("manual resolution selection and evidence must be verified")
        return ResolutionResult(ResolutionState.RESOLVED, values, selected.candidate_id, selected.value, tuple(item.candidate_id for item in values if item is not selected), manual_resolution.reason, manual_resolution)
    if len({item.value for item in present}) != 1:
        return ResolutionResult(ResolutionState.CONFLICTING, values, None, None, (), "Verified compatible candidates conflict; review is required.")
    selected = min(present, key=lambda item: (_SOURCE_PRIORITY[sources[item.source_id].source_type], item.candidate_id))
    return ResolutionResult(ResolutionState.RESOLVED, values, selected.candidate_id, selected.value, tuple(item.candidate_id for item in values if item is not selected), "Equivalent candidates resolved by deterministic source preference.")


@dataclass(frozen=True)
class StatRecord:
    record_id: str
    record_type: StatRecordType
    role: PlayerRole
    player_id: str
    program_id: str | None
    season: int | None
    candidates: tuple[CandidateValue, ...]

    def __post_init__(self):
        for name in ("record_id", "player_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "record_type", StatRecordType(self.record_type))
        object.__setattr__(self, "role", PlayerRole(self.role))
        object.__setattr__(self, "program_id", _optional(self.program_id, "program_id"))
        values = _tuple_limit(self.candidates, "stat candidates")
        if not values:
            raise ValueError("stat record requires candidate evidence")
        if any(item.player_id != self.player_id for item in values):
            raise ValueError("stat candidate player identity mismatch")
        object.__setattr__(self, "candidates", values)


@dataclass(frozen=True)
class Achievement:
    achievement_id: str
    achievement_type: AchievementType
    scope: str
    player_id: str
    program_id: str | None
    season_or_date: str | None
    normalized_label: str
    source_wording: str | None
    provenance_ids: tuple[str, ...]

    def __post_init__(self):
        for name in ("achievement_id", "scope", "player_id", "normalized_label"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "achievement_type", AchievementType(self.achievement_type))
        if self.scope not in {"individual", "team"}:
            raise ValueError("achievement scope must be individual or team")
        if not self.provenance_ids:
            raise ValueError("achievement requires provenance")


@dataclass(frozen=True)
class CollegeResume:
    resume_id: str
    player_id: str
    canonical_display_name: str
    display_name_source_id: str
    identity_mappings: tuple[IdentityMapping, ...]
    programs: tuple[Program, ...]
    stints: tuple[ProgramStint, ...]
    stat_records: tuple[StatRecord, ...]
    achievements: tuple[Achievement, ...]
    section_statuses: tuple[tuple[str, str], ...]

    def __post_init__(self):
        for name in ("resume_id", "player_id", "canonical_display_name", "display_name_source_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        for name in ("identity_mappings", "programs", "stints", "stat_records", "achievements"):
            object.__setattr__(self, name, _tuple_limit(getattr(self, name), name))
        if any(item.ausl_player_id != self.player_id for item in self.identity_mappings):
            raise ValueError("identity mapping does not match résumé player_id")
        statuses = tuple((str(key), str(value)) for key, value in self.section_statuses)
        allowed = {"verified", "unavailable", "not_applicable", "needs_review"}
        if any(value not in allowed for _, value in statuses):
            raise ValueError("unsupported section status")
        object.__setattr__(self, "section_statuses", statuses)


@dataclass(frozen=True)
class CollegeEnvelope:
    generated_at: datetime
    completeness_profile: str
    resumes: tuple[CollegeResume, ...]
    sources: tuple[SourceProvenance, ...]
    validation_metadata: tuple[tuple[str, str], ...] = ()
    schema_name: str = field(default=SCHEMA_NAME, init=False)
    schema_version: int = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self):
        object.__setattr__(self, "generated_at", _utc(self.generated_at, "generated_at"))
        if self.completeness_profile != CORE_RESUME_V1:
            raise ValueError("unsupported completeness profile")
        object.__setattr__(self, "resumes", _tuple_limit(self.resumes, "resumes"))
        object.__setattr__(self, "sources", _tuple_limit(self.sources, "sources"))
        object.__setattr__(self, "validation_metadata", tuple((str(k), str(v)) for k, v in self.validation_metadata))


@dataclass(frozen=True)
class CompletenessAssessment:
    state: CompletenessState
    blocking_reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]


def _resume_source_refs(resume: CollegeResume) -> set[str]:
    refs = {resume.display_name_source_id}
    refs.update(item.source_id for item in resume.identity_mappings)
    refs.update(source for item in resume.programs for source in item.source_ids)
    refs.update(item.source_id for record in resume.stat_records for item in record.candidates)
    refs.update(source for item in resume.achievements for source in item.provenance_ids)
    refs.update(source for item in resume.stints for source in item.provenance_ids)
    return refs


def assess_completeness(resume: CollegeResume, envelope: CollegeEnvelope) -> CompletenessAssessment:
    source_ids = {item.source_id for item in envelope.sources if item.verification_state == "verified"}
    blocking: list[str] = []
    if not resume.identity_mappings or not any(item.review_state is IdentityReviewState.VERIFIED for item in resume.identity_mappings):
        blocking.append("ambiguous_identity")
    if resume.display_name_source_id not in source_ids:
        blocking.append("display_name_missing_provenance")
    if _resume_source_refs(resume) - source_ids:
        blocking.append("missing_or_unverified_provenance")
    for record in resume.stat_records:
        grouped: dict[tuple[Any, ...], list[CandidateValue]] = {}
        for item in record.candidates:
            grouped.setdefault(item.dimensions, []).append(item)
        if any(resolve_candidates(items, {s.source_id: s for s in envelope.sources}).state is ResolutionState.CONFLICTING for items in grouped.values()):
            blocking.append("unresolved_material_conflict")
    statuses = dict(resume.section_statuses)
    if statuses.get("identity") == "needs_review" or any(value == "needs_review" for value in statuses.values()):
        blocking.append("section_needs_review")
    missing = tuple(f"sections.{name}" for name in ("identity", "programs", "statistics", "achievements") if statuses.get(name) in {None, "unavailable"})
    if blocking:
        return CompletenessAssessment(CompletenessState.NEEDS_REVIEW, tuple(sorted(set(blocking))), missing)
    if missing:
        return CompletenessAssessment(CompletenessState.PARTIAL, (), missing)
    return CompletenessAssessment(CompletenessState.VERIFIED, (), ())


def derive_career_record(
    seasons: Sequence[StatRecord],
    *,
    record_id: str,
    expected_seasons: Sequence[int] | None = None,
    verified_source_ids: Sequence[str] | None = None,
) -> StatRecord | None:
    records = tuple(seasons)
    verified = set(verified_source_ids or ())
    if (
        not records
        or expected_seasons is None
        or verified_source_ids is None
        or {item.season for item in records} != set(expected_seasons)
        or any(item.record_type not in {StatRecordType.SEASON_BATTING, StatRecordType.SEASON_PITCHING} for item in records)
    ):
        return None
    if len({(item.player_id, item.role, item.record_type) for item in records}) != 1:
        return None
    grouped: dict[tuple[str, str, str], list[CandidateValue]] = {}
    for record in records:
        for item in record.candidates:
            if item.value_state is not ValueState.PRESENT or item.source_id not in verified:
                return None
            grouped.setdefault((item.field_path, item.metric_definition, item.unit), []).append(item)
    derived: list[CandidateValue] = []
    for index, ((path, metric, unit), values) in enumerate(sorted(grouped.items())):
        per_season: dict[int | None, set[int | Decimal | None]] = {}
        for item in values:
            per_season.setdefault(item.season, set()).add(item.value)
        if any(len(candidates) != 1 for candidates in per_season.values()):
            return None
        normalized = [next(iter(per_season[season])) for season in sorted(per_season)]
        if unit == "rate" and len(normalized) != 1:
            return None
        total = normalized[0] if unit == "rate" else sum(int(item) for item in normalized)
        derived.append(CandidateValue(f"{record_id}:{index}", path, total, ValueState.PRESENT, values[0].source_id, records[0].player_id, None, None, "derived_career_" + ("batting" if records[0].record_type is StatRecordType.SEASON_BATTING else "pitching"), metric, unit))
    kind = StatRecordType.DERIVED_CAREER_BATTING if records[0].record_type is StatRecordType.SEASON_BATTING else StatRecordType.DERIVED_CAREER_PITCHING
    return StatRecord(record_id, kind, records[0].role, records[0].player_id, None, None, tuple(derived))


def innings_to_outs(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("innings must use baseball notation")
    text = str(value).strip()
    if text.startswith("-"):
        raise ValueError("innings cannot be negative")
    if text.lower() in {"nan", "inf", "infinity"}:
        raise ValueError("innings must be finite")
    if "." in text:
        whole, fraction = text.split(".", 1)
        if not whole.isdigit() or fraction not in {"0", "1", "2"}:
            raise ValueError("innings fraction must be .0, .1, or .2")
    else:
        whole, fraction = text, "0"
        if not whole.isdigit():
            raise ValueError("innings are malformed")
    return int(whole) * 3 + int(fraction)


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    player_count: int
    source_count: int
    record_counts_by_type: tuple[tuple[str, int], ...]
    duplicate_stable_ids: tuple[str, ...]
    unresolved_identities: tuple[str, ...]
    missing_provenance: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    invalid_timestamps: tuple[str, ...]
    malformed_numeric_values: tuple[str, ...]
    unsupported_metric_definitions: tuple[str, ...]
    completeness_totals: tuple[tuple[str, int], ...]
    safe_for_pilot_review: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_envelope(envelope: CollegeEnvelope) -> ValidationReport:
    resume_ids = [item.resume_id for item in envelope.resumes]
    source_ids = [item.source_id for item in envelope.sources]
    duplicate_values: set[str] = {
        key for key, count in Counter(resume_ids).items() if count > 1
    }
    duplicate_values.update(
        key for key, count in Counter(source_ids).items() if count > 1
    )
    for resume in envelope.resumes:
        groups = (
            [item.mapping_id for item in resume.identity_mappings],
            [item.program_id for item in resume.programs],
            [item.stint_id for item in resume.stints],
            [item.record_id for item in resume.stat_records],
            [item.candidate_id for record in resume.stat_records for item in record.candidates],
            [item.achievement_id for item in resume.achievements],
        )
        for identifiers in groups:
            duplicate_values.update(
                key for key, count in Counter(identifiers).items() if count > 1
            )
    duplicates = tuple(sorted(duplicate_values))
    source_set = set(source_ids)
    missing: set[str] = set()
    unresolved: list[str] = []
    conflicts: list[str] = []
    unsupported: set[str] = set()
    counts: Counter[str] = Counter()
    complete: Counter[str] = Counter()
    safe: list[str] = []
    for resume in envelope.resumes:
        refs = _resume_source_refs(resume)
        missing.update(f"{resume.resume_id}:{source}" for source in refs - source_set)
        athlete_ids: dict[str, set[str]] = {}
        for mapping in resume.identity_mappings:
            if mapping.source_athlete_id:
                athlete_ids.setdefault(mapping.source_id, set()).add(
                    mapping.source_athlete_id
                )
        conflicting_athletes = any(len(values) > 1 for values in athlete_ids.values())
        if conflicting_athletes:
            unresolved.append(resume.resume_id)
        elif not any(item.review_state is IdentityReviewState.VERIFIED for item in resume.identity_mappings):
            unresolved.append(resume.resume_id)
        counts.update(item.record_type.value for item in resume.stat_records)
        supported_metrics = {
            "games", "at_bats", "plate_appearances", "runs", "hits",
            "doubles", "triples", "home_runs", "rbi", "walks",
            "strikeouts", "stolen_bases", "batting_average",
            "on_base_percentage", "slugging_percentage", "innings_outs",
            "earned_runs", "wins", "losses", "saves", "era", "whip",
            "pitching_strikeouts",
        }
        for record in resume.stat_records:
            for item in record.candidates:
                if item.metric_definition not in supported_metrics:
                    unsupported.add(
                        f"{resume.resume_id}:{item.metric_definition}"
                    )
        assessment = assess_completeness(resume, envelope)
        complete[assessment.state.value] += 1
        if "unresolved_material_conflict" in assessment.blocking_reasons:
            conflicts.append(resume.resume_id)
        if (
            assessment.state is not CompletenessState.NEEDS_REVIEW
            and not (refs - source_set)
            and not any(
                item.metric_definition not in supported_metrics
                for record in resume.stat_records
                for item in record.candidates
            )
        ):
            safe.append(resume.resume_id)
    conflicting_identity_ids = []
    for resume in envelope.resumes:
        by_source: dict[str, set[str]] = {}
        for mapping in resume.identity_mappings:
            if mapping.source_athlete_id:
                by_source.setdefault(mapping.source_id, set()).add(
                    mapping.source_athlete_id
                )
        if any(len(values) > 1 for values in by_source.values()):
            conflicting_identity_ids.append(resume.resume_id)
    errors = [*(f"duplicate stable ID: {item}" for item in duplicates), *(f"missing provenance: {item}" for item in sorted(missing)), *(f"unresolved identity: {item}" for item in unresolved), *(f"conflicting source athlete IDs: {item}" for item in conflicting_identity_ids), *(f"unresolved conflict: {item}" for item in conflicts), *(f"unsupported metric definition: {item}" for item in sorted(unsupported))]
    return ValidationReport(tuple(errors), (), len(envelope.resumes), len(envelope.sources), tuple(sorted(counts.items())), duplicates, tuple(sorted(set(unresolved))), tuple(sorted(missing)), tuple(sorted(conflicts)), (), (), tuple(sorted(unsupported)), tuple(sorted(complete.items())), tuple(sorted(safe)))


def _wire(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "__dataclass_fields__"):
        return {item.name: _wire(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    return value


def _envelope_dict(envelope: CollegeEnvelope) -> dict[str, Any]:
    data = _wire(envelope)
    data["sources"] = sorted(data["sources"], key=lambda item: item["source_id"])
    data["resumes"] = sorted(data["resumes"], key=lambda item: item["resume_id"])
    return data


def serialize_envelope(envelope: CollegeEnvelope) -> bytes:
    return (json.dumps(_envelope_dict(envelope), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict(data: Mapping[str, Any], cls: type, *, omit: set[str] | None = None) -> None:
    expected = {item.name for item in fields(cls)} - (omit or set())
    unknown = set(data) - expected
    missing = expected - set(data)
    if unknown:
        raise ValueError(f"unknown fields for {cls.__name__}: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing fields for {cls.__name__}: {sorted(missing)}")


def _dt(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is an invalid timestamp") from exc
    return _utc(parsed, label)


def _depth(value: Any, level: int = 0) -> None:
    if level > MAX_NESTING_DEPTH:
        raise ValueError("JSON nesting depth exceeds the safe limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if len(str(key)) > MAX_STRING_LENGTH:
                raise ValueError("JSON key exceeds the safe string limit")
            _depth(item, level + 1)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ValueError("JSON collection exceeds the safe limit")
        for item in value:
            _depth(item, level + 1)
    elif isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        raise ValueError("JSON value exceeds the safe string limit")


def _construct(cls: type, data: Mapping[str, Any], **changes: Any):
    _strict(data, cls)
    values = dict(data)
    values.update(changes)
    return cls(**values)


def load_envelope(payload: bytes) -> CollegeEnvelope:
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("college payload exceeds the safe payload limit")
    try:
        data = json.loads(payload.decode("utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"nonfinite JSON value: {token}")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("college payload is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("college payload root must be an object")
    _depth(data)
    required_top = {"schema_name", "schema_version", "generated_at", "completeness_profile", "resumes", "sources", "validation_metadata"}
    if set(data) != required_top:
        raise ValueError("college payload fields are missing or unknown")
    if data["schema_name"] != SCHEMA_NAME:
        raise ValueError("unsupported or missing college schema name")
    if data["schema_version"] != SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(f"unsupported college schema version: {data['schema_version']}")
    sources = []
    for raw in data["sources"]:
        values = dict(raw)
        values["retrieved_at"] = _dt(values["retrieved_at"], "retrieved_at")
        values["approved_at"] = _dt(values["approved_at"], "approved_at") if values["approved_at"] else None
        sources.append(_construct(SourceProvenance, raw, **values))
    resumes = []
    for raw in data["resumes"]:
        identities = []
        for item in raw["identity_mappings"]:
            values = dict(item)
            values["reviewed_at"] = _dt(values["reviewed_at"], "reviewed_at") if values["reviewed_at"] else None
            values["aliases"] = tuple(values["aliases"])
            identities.append(_construct(IdentityMapping, item, **values))
        programs = [_construct(Program, item, source_ids=tuple(item["source_ids"]), source_identifiers=tuple(tuple(v) for v in item["source_identifiers"]), historical_names=tuple(item["historical_names"])) for item in raw["programs"]]
        stints = [_construct(ProgramStint, item, provenance_ids=tuple(item["provenance_ids"]), season_kinds=tuple((v[0], v[1]) for v in item["season_kinds"])) for item in raw["stints"]]
        records = []
        for item in raw["stat_records"]:
            candidates = []
            for candidate in item["candidates"]:
                values = dict(candidate)
                if values["value"] is not None and values["unit"] != "count":
                    try:
                        values["value"] = Decimal(values["value"])
                    except InvalidOperation as exc:
                        raise ValueError("malformed exact decimal value") from exc
                candidates.append(_construct(CandidateValue, candidate, **values))
            records.append(_construct(StatRecord, item, candidates=tuple(candidates)))
        achievements = [_construct(Achievement, item, provenance_ids=tuple(item["provenance_ids"])) for item in raw["achievements"]]
        resumes.append(_construct(CollegeResume, raw, identity_mappings=tuple(identities), programs=tuple(programs), stints=tuple(stints), stat_records=tuple(records), achievements=tuple(achievements), section_statuses=tuple(tuple(v) for v in raw["section_statuses"])))
    return CollegeEnvelope(_dt(data["generated_at"], "generated_at"), data["completeness_profile"], tuple(sorted(resumes, key=lambda item: item.resume_id)), tuple(sorted(sources, key=lambda item: item.source_id)), tuple(tuple(v) for v in data["validation_metadata"]))
