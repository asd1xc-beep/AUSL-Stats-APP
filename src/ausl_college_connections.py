"""Deterministic, review-only college connection candidates for Phase 7E.

The engine consumes only an already validated Phase 7B college envelope.  It
does not collect evidence, infer identity from names, or grant producer
approval.  Connections remain unavailable for producer use until a separate
project-owner review binds an approval to the exact evidence version.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from itertools import combinations
from typing import Any, Iterable, Mapping

from ausl_college import (
    Achievement,
    AchievementType,
    CollegeEnvelope,
    CollegeResume,
    CompletenessState,
    IdentityReviewState,
    Program,
    ProgramStint,
    SourceProvenance,
    assess_completeness,
)


CONNECTION_SCHEMA_NAME = "ausl-college-connection-candidates"
CONNECTION_SCHEMA_VERSION = 1
MAX_CONNECTION_PAYLOAD_BYTES = 5_000_000


class ConnectionType(str, Enum):
    FORMER_COLLEGE_TEAMMATES = "former_college_teammates"
    SHARED_PROGRAM = "shared_program"
    TRANSFER = "transfer"
    SHARED_WCWS = "shared_wcws"
    CHAMPIONSHIP_TEAMMATES = "championship_teammates"
    FORMER_OPPONENTS = "former_opponents"
    CONFERENCE_CONNECTION = "conference_connection"
    SHARED_AWARD = "shared_award"
    COLLEGE_TO_AUSL_ROLE_CHANGE = "college_to_ausl_role_change"


class ConnectionReviewState(str, Enum):
    ELIGIBLE_FOR_REVIEW = "eligible_for_review"
    SUPPRESSED = "suppressed"


class ConnectionApprovalState(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"


def _required(value: Any, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _optional(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required(value, label)


def _strings(
    values: Iterable[Any],
    label: str,
    *,
    nonempty: bool = False,
    allow_duplicates: bool = False,
) -> tuple[str, ...]:
    result = tuple(_required(item, label) for item in values)
    if nonempty and not result:
        raise ValueError(f"{label} is required")
    if not allow_duplicates and len(result) != len(set(result)):
        raise ValueError(f"{label} contains duplicates")
    return result


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _player_sort_key(value: str) -> tuple[Any, ...]:
    return (0, int(value)) if value.isdigit() else (1, value.casefold(), value)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _canonical_program_id(program: Program) -> str:
    """Unify only the explicit Phase 7E reviewed-program namespace.

    This is not name matching.  The reviewed batch builder minted IDs as
    ``review-program-<display-name slug>``.  We accept that documented alias
    only when its suffix exactly agrees with the stored display-name slug.
    """

    prefix = "review-program-"
    if program.program_id.startswith(prefix):
        suffix = program.program_id[len(prefix) :]
        if suffix == _slug(program.display_name):
            return suffix
    return program.program_id


def _source_wire(source: SourceProvenance) -> dict[str, Any]:
    return {
        "approved_at": (
            source.approved_at.astimezone(timezone.utc).isoformat()
            if source.approved_at
            else None
        ),
        "content_hash": source.content_hash,
        "effective_date": source.effective_date,
        "local_document_id": source.local_document_id,
        "locator": source.locator,
        "organization": source.organization,
        "retrieved_at": source.retrieved_at.astimezone(timezone.utc).isoformat(),
        "review_note": source.review_note,
        "reviewer": source.reviewer,
        "source_id": source.source_id,
        "source_type": source.source_type.value,
        "title": source.title,
        "url": source.url,
        "verification_state": source.verification_state,
        "version": source.version,
    }


@dataclass(frozen=True)
class CollegeConnectionCandidate:
    connection_type: ConnectionType
    subject_player_ids: tuple[str, ...]
    subject_display_names: tuple[str, ...]
    program_ids: tuple[str, ...]
    program_display_names: tuple[str, ...]
    season_scope: tuple[str, ...]
    wording: str
    evidence_source_ids: tuple[str, ...]
    evidence_record_ids: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    review_state: ConnectionReviewState
    approval_state: ConnectionApprovalState
    priority_score: int
    completeness_states: tuple[str, ...]
    uncertainty_info: tuple[str, ...] = ()
    game_relevance: str | None = None
    suppression_reason: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "connection_type", ConnectionType(self.connection_type))
        object.__setattr__(
            self,
            "subject_player_ids",
            _strings(self.subject_player_ids, "subject player ID", nonempty=True),
        )
        object.__setattr__(
            self,
            "subject_display_names",
            _strings(self.subject_display_names, "subject display name", nonempty=True),
        )
        if len(self.subject_player_ids) != len(self.subject_display_names):
            raise ValueError("connection subjects and names must align")
        for name in (
            "program_ids",
            "program_display_names",
            "evidence_source_ids",
            "evidence_record_ids",
            "evidence_fingerprints",
            "uncertainty_info",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        for name in ("season_scope", "completeness_states"):
            object.__setattr__(
                self,
                name,
                _strings(getattr(self, name), name, allow_duplicates=True),
            )
        if len(self.program_ids) != len(self.program_display_names):
            raise ValueError("connection program IDs and names must align")
        if not self.evidence_source_ids or not self.evidence_record_ids:
            raise ValueError("connection requires field-level evidence")
        object.__setattr__(self, "wording", _required(self.wording, "connection wording"))
        object.__setattr__(self, "review_state", ConnectionReviewState(self.review_state))
        object.__setattr__(self, "approval_state", ConnectionApprovalState(self.approval_state))
        if isinstance(self.priority_score, bool) or not isinstance(self.priority_score, int):
            raise ValueError("priority_score must be an integer")
        object.__setattr__(self, "game_relevance", _optional(self.game_relevance, "game_relevance"))
        object.__setattr__(self, "suppression_reason", _optional(self.suppression_reason, "suppression_reason"))
        if self.review_state is ConnectionReviewState.SUPPRESSED and not self.suppression_reason:
            raise ValueError("suppressed connection requires a reason")
        if self.approval_state is ConnectionApprovalState.APPROVED:
            raise ValueError("the Phase 7E candidate engine cannot create approval")

    @property
    def connection_id(self) -> str:
        stable = {
            "connection_type": self.connection_type.value,
            "program_ids": list(self.program_ids),
            "subject_player_ids": list(self.subject_player_ids),
        }
        return f"college-connection-{_hash(stable)[:24]}"

    @property
    def evidence_version_hash(self) -> str:
        evidence = {
            "approval_state": self.approval_state.value,
            "completeness_states": list(self.completeness_states),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "evidence_record_ids": list(self.evidence_record_ids),
            "evidence_source_ids": list(self.evidence_source_ids),
            "game_relevance": self.game_relevance,
            "review_state": self.review_state.value,
            "season_scope": list(self.season_scope),
            "suppression_reason": self.suppression_reason,
            "uncertainty_info": list(self.uncertainty_info),
            "wording": self.wording,
        }
        return _hash(evidence)

    @property
    def air_ready(self) -> bool:
        return (
            self.review_state is ConnectionReviewState.ELIGIBLE_FOR_REVIEW
            and self.approval_state is ConnectionApprovalState.APPROVED
            and not self.suppression_reason
            and not self.uncertainty_info
        )


@dataclass(frozen=True)
class ConnectionSuppression:
    connection_type: ConnectionType
    subject_player_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    reason: str
    detail: str
    evidence_source_ids: tuple[str, ...] = ()
    evidence_record_ids: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "connection_type", ConnectionType(self.connection_type))
        for name in (
            "subject_player_ids",
            "program_ids",
            "evidence_source_ids",
            "evidence_record_ids",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "reason", _required(self.reason, "suppression reason"))
        object.__setattr__(self, "detail", _required(self.detail, "suppression detail"))

    @property
    def suppression_id(self) -> str:
        return f"college-suppression-{_hash({'connection_type': self.connection_type.value, 'subject_player_ids': list(self.subject_player_ids), 'program_ids': list(self.program_ids), 'reason': self.reason})[:24]}"


@dataclass(frozen=True)
class CollegeConnectionBuildResult:
    candidates: tuple[CollegeConnectionCandidate, ...]
    suppressions: tuple[ConnectionSuppression, ...]


def _verified_source_ids(envelope: CollegeEnvelope) -> set[str]:
    return {
        source.source_id
        for source in envelope.sources
        if source.verification_state == "verified"
    }


def _source_fingerprints(
    source_ids: Iterable[str], source_by_id: Mapping[str, SourceProvenance]
) -> tuple[str, ...]:
    return tuple(
        _hash(_source_wire(source_by_id[source_id]))
        for source_id in sorted(set(source_ids))
    )


def _resume_eligible(resume: CollegeResume, envelope: CollegeEnvelope) -> bool:
    return (
        any(
            mapping.review_state is IdentityReviewState.VERIFIED
            for mapping in resume.identity_mappings
        )
        and assess_completeness(resume, envelope).state
        is not CompletenessState.NEEDS_REVIEW
    )


def _program_map(resume: CollegeResume) -> dict[str, Program]:
    return {program.program_id: program for program in resume.programs}


def _stint_evidence(stint: ProgramStint, program: Program) -> tuple[tuple[str, ...], tuple[str, ...]]:
    source_ids = tuple(sorted(set((*stint.provenance_ids, *program.source_ids))))
    record_ids = (f"program:{program.program_id}", f"stint:{stint.stint_id}")
    return source_ids, record_ids


def _season_label(stint: ProgramStint) -> str:
    if stint.start_season == stint.end_season:
        return str(stint.start_season)
    return f"{stint.start_season}-{stint.end_season}"


def _candidate(
    *,
    connection_type: ConnectionType,
    subjects: tuple[CollegeResume, ...],
    programs: tuple[Program, ...],
    season_scope: tuple[str, ...],
    wording: str,
    source_ids: Iterable[str],
    record_ids: Iterable[str],
    source_by_id: Mapping[str, SourceProvenance],
    envelope: CollegeEnvelope,
    priority: int,
) -> CollegeConnectionCandidate:
    ordered_source_ids = tuple(sorted(set(source_ids)))
    return CollegeConnectionCandidate(
        connection_type=connection_type,
        subject_player_ids=tuple(resume.player_id for resume in subjects),
        subject_display_names=tuple(resume.canonical_display_name for resume in subjects),
        program_ids=tuple(_canonical_program_id(program) for program in programs),
        program_display_names=tuple(program.display_name for program in programs),
        season_scope=season_scope,
        wording=wording,
        evidence_source_ids=ordered_source_ids,
        evidence_record_ids=tuple(sorted(set(record_ids))),
        evidence_fingerprints=_source_fingerprints(ordered_source_ids, source_by_id),
        review_state=ConnectionReviewState.ELIGIBLE_FOR_REVIEW,
        approval_state=ConnectionApprovalState.UNREVIEWED,
        priority_score=priority,
        completeness_states=tuple(
            assess_completeness(resume, envelope).state.value for resume in subjects
        ),
    )


def _ordered_resumes(resumes: Iterable[CollegeResume]) -> tuple[CollegeResume, ...]:
    return tuple(sorted(resumes, key=lambda item: _player_sort_key(item.player_id)))


def _award_label(achievement: Achievement) -> str:
    return re.sub(r"^\s*\d{4}\s+", "", achievement.normalized_label).strip()


def _exact_year(value: str | None) -> int | None:
    if value and re.fullmatch(r"\d{4}", value.strip()):
        return int(value)
    return None


def build_college_connections(envelope: CollegeEnvelope) -> CollegeConnectionBuildResult:
    source_by_id = {source.source_id: source for source in envelope.sources}
    verified_sources = _verified_source_ids(envelope)
    resumes = _ordered_resumes(envelope.resumes)
    eligible = {
        resume.player_id: _resume_eligible(resume, envelope) for resume in resumes
    }
    candidates: list[CollegeConnectionCandidate] = []
    suppressions: list[ConnectionSuppression] = []

    # Transfer history: exact ordered stints only.
    for resume in resumes:
        stints = tuple(sorted(resume.stints, key=lambda item: item.transfer_order))
        if len(stints) < 2:
            continue
        programs = _program_map(resume)
        evidence_sources: set[str] = set()
        evidence_records: set[str] = set()
        for stint in stints:
            program = programs.get(stint.program_id)
            if program is None:
                continue
            sources, records = _stint_evidence(stint, program)
            evidence_sources.update(sources)
            evidence_records.update(records)
        reason = None
        if any(
            stint.start_season is None
            or stint.end_season is None
            or stint.uncertainty_note
            for stint in stints
        ):
            reason = "season_scope_unavailable"
        elif not evidence_sources or not evidence_sources <= verified_sources:
            reason = "source_not_verified"
        elif not eligible[resume.player_id]:
            reason = "resume_not_eligible"
        elif any(stint.program_id not in programs for stint in stints):
            reason = "program_identity_unavailable"
        if reason:
            suppressions.append(
                ConnectionSuppression(
                    ConnectionType.TRANSFER,
                    (resume.player_id,),
                    tuple(
                        _canonical_program_id(programs[stint.program_id])
                        for stint in stints
                        if stint.program_id in programs
                    ),
                    reason,
                    "Transfer wording requires exact, verified program and season evidence.",
                    tuple(sorted(evidence_sources)),
                    tuple(sorted(evidence_records)),
                )
            )
            continue
        stint_programs = tuple(programs[stint.program_id] for stint in stints)
        if len(stint_programs) == 2:
            wording = (
                f"COLLEGE CONNECTION — {resume.canonical_display_name} played at "
                f"{stint_programs[0].display_name} before moving to "
                f"{stint_programs[1].display_name}."
            )
        else:
            middle = ", then ".join(item.display_name for item in stint_programs[1:-1])
            path = (
                f"{stint_programs[0].display_name}, then {middle}, and finally "
                f"{stint_programs[-1].display_name}"
            )
            wording = f"COLLEGE CONNECTION — {resume.canonical_display_name} played at {path}."
        candidates.append(
            _candidate(
                connection_type=ConnectionType.TRANSFER,
                subjects=(resume,),
                programs=stint_programs,
                season_scope=tuple(_season_label(stint) for stint in stints),
                wording=wording,
                source_ids=evidence_sources,
                record_ids=evidence_records,
                source_by_id=source_by_id,
                envelope=envelope,
                priority=80,
            )
        )

    # Same-program claims require exact intervals.  An overlap is preserved as
    # a suppression because shared attendance alone does not prove teammates.
    program_stints: dict[str, list[tuple[CollegeResume, Program, ProgramStint]]] = {}
    for resume in resumes:
        programs = _program_map(resume)
        for stint in resume.stints:
            program = programs.get(stint.program_id)
            if program:
                program_stints.setdefault(_canonical_program_id(program), []).append(
                    (resume, program, stint)
                )
    for canonical_id, records in sorted(program_stints.items()):
        for left, right in combinations(
            sorted(records, key=lambda item: _player_sort_key(item[0].player_id)), 2
        ):
            first, second = left[0], right[0]
            if first.player_id == second.player_id:
                continue
            source_ids = set((*left[1].source_ids, *left[2].provenance_ids, *right[1].source_ids, *right[2].provenance_ids))
            record_ids = (
                f"program:{left[1].program_id}",
                f"stint:{left[2].stint_id}",
                f"program:{right[1].program_id}",
                f"stint:{right[2].stint_id}",
            )
            if not source_ids <= verified_sources:
                reason = "source_not_verified"
            elif any(
                value is None
                for value in (
                    left[2].start_season,
                    left[2].end_season,
                    right[2].start_season,
                    right[2].end_season,
                )
            ) or left[2].uncertainty_note or right[2].uncertainty_note:
                reason = "season_scope_unavailable"
            elif not eligible[first.player_id] or not eligible[second.player_id]:
                reason = "resume_not_eligible"
            else:
                reason = None
            if reason:
                suppressions.append(
                    ConnectionSuppression(
                        ConnectionType.SHARED_PROGRAM,
                        (first.player_id, second.player_id),
                        (canonical_id,),
                        reason,
                        "Shared-program wording requires exact verified attendance seasons for both players.",
                        tuple(sorted(source_ids)),
                        tuple(sorted(set(record_ids))),
                    )
                )
                continue
            left_start, left_end = left[2].start_season, left[2].end_season
            right_start, right_end = right[2].start_season, right[2].end_season
            assert None not in (left_start, left_end, right_start, right_end)
            if left_start > right_start:
                left, right = right, left
                first, second = left[0], right[0]
                left_start, left_end = left[2].start_season, left[2].end_season
                right_start, right_end = right[2].start_season, right[2].end_season
            assert left_end is not None and right_start is not None
            if right_start <= left_end:
                suppressions.append(
                    ConnectionSuppression(
                        ConnectionType.FORMER_COLLEGE_TEAMMATES,
                        tuple(sorted((first.player_id, second.player_id), key=_player_sort_key)),
                        (canonical_id,),
                        "stint_overlap_does_not_prove_teammates",
                        "Overlapping program seasons require an explicit roster or teammate source.",
                        tuple(sorted(source_ids)),
                        tuple(sorted(set(record_ids))),
                    )
                )
                continue
            gap = right_start - left_end
            gap_words = {
                1: "one season",
                2: "two seasons",
            }.get(gap, f"{gap} seasons")
            subjects = _ordered_resumes((first, second))
            program = left[1]
            candidates.append(
                _candidate(
                    connection_type=ConnectionType.SHARED_PROGRAM,
                    subjects=subjects,
                    programs=(program,),
                    season_scope=(_season_label(left[2]), _season_label(right[2])),
                    wording=(
                        f"COLLEGE CONNECTION — {subjects[0].canonical_display_name} and "
                        f"{subjects[1].canonical_display_name} both played at "
                        f"{program.display_name}, {gap_words} apart."
                    ),
                    source_ids=source_ids,
                    record_ids=record_ids,
                    source_by_id=source_by_id,
                    envelope=envelope,
                    priority=60,
                )
            )

    # Exact same-program, same-year championship evidence can support a
    # teammate claim; shared attendance alone cannot.
    championship_records: dict[tuple[str, int], list[tuple[CollegeResume, Program, Achievement]]] = {}
    for resume in resumes:
        programs = _program_map(resume)
        for achievement in resume.achievements:
            year = _exact_year(achievement.season_or_date)
            program = programs.get(achievement.program_id or "")
            if (
                achievement.achievement_type is AchievementType.CHAMPIONSHIP
                and achievement.scope == "team"
                and year is not None
                and program is not None
            ):
                championship_records.setdefault(
                    (_canonical_program_id(program), year), []
                ).append((resume, program, achievement))
    for (_program_id, year), records in sorted(championship_records.items()):
        for left, right in combinations(
            sorted(records, key=lambda item: _player_sort_key(item[0].player_id)), 2
        ):
            subjects = _ordered_resumes((left[0], right[0]))
            source_ids = set((*left[2].provenance_ids, *right[2].provenance_ids))
            if (
                not all(eligible[item.player_id] for item in subjects)
                or not source_ids
                or not source_ids <= verified_sources
            ):
                continue
            candidates.append(
                _candidate(
                    connection_type=ConnectionType.CHAMPIONSHIP_TEAMMATES,
                    subjects=subjects,
                    programs=(left[1],),
                    season_scope=(str(year),),
                    wording=(
                        f"COLLEGE CONNECTION — {subjects[0].canonical_display_name} and "
                        f"{subjects[1].canonical_display_name} were {left[1].display_name} "
                        f"teammates on the {year} national championship team."
                    ),
                    source_ids=source_ids,
                    record_ids=(
                        f"achievement:{left[2].achievement_id}",
                        f"achievement:{right[2].achievement_id}",
                    ),
                    source_by_id=source_by_id,
                    envelope=envelope,
                    priority=100,
                )
            )

    # Match only exact normalized award labels after removing a leading year.
    awards: dict[str, list[tuple[CollegeResume, Program | None, Achievement, int]]] = {}
    for resume in resumes:
        programs = _program_map(resume)
        for achievement in resume.achievements:
            if achievement.achievement_type not in {
                AchievementType.NATIONAL_AWARD,
                AchievementType.CONFERENCE_AWARD,
            }:
                continue
            year = _exact_year(achievement.season_or_date)
            label = _award_label(achievement)
            if year is None or not label:
                continue
            awards.setdefault(label.casefold(), []).append(
                (resume, programs.get(achievement.program_id or ""), achievement, year)
            )
    for records in awards.values():
        for left, right in combinations(
            sorted(records, key=lambda item: _player_sort_key(item[0].player_id)), 2
        ):
            if left[0].player_id == right[0].player_id:
                continue
            subjects = _ordered_resumes((left[0], right[0]))
            source_ids = set((*left[2].provenance_ids, *right[2].provenance_ids))
            if (
                not all(eligible[item.player_id] for item in subjects)
                or not source_ids
                or not source_ids <= verified_sources
            ):
                continue
            by_id = {left[0].player_id: left[3], right[0].player_id: right[3]}
            label = _award_label(left[2])
            candidate_programs = tuple(
                item for item in (left[1], right[1]) if item is not None
            )
            candidates.append(
                _candidate(
                    connection_type=ConnectionType.SHARED_AWARD,
                    subjects=subjects,
                    programs=candidate_programs,
                    season_scope=tuple(str(by_id[item.player_id]) for item in subjects),
                    wording=(
                        f"COLLEGE CONNECTION — {subjects[0].canonical_display_name} "
                        f"({by_id[subjects[0].player_id]}) and "
                        f"{subjects[1].canonical_display_name} "
                        f"({by_id[subjects[1].player_id]}) both earned {label}."
                    ),
                    source_ids=source_ids,
                    record_ids=(
                        f"achievement:{left[2].achievement_id}",
                        f"achievement:{right[2].achievement_id}",
                    ),
                    source_by_id=source_by_id,
                    envelope=envelope,
                    priority=50,
                )
            )

    unique_candidates = {item.connection_id: item for item in candidates}
    unique_suppressions = {item.suppression_id: item for item in suppressions}
    return CollegeConnectionBuildResult(
        tuple(
            sorted(
                unique_candidates.values(),
                key=lambda item: (-item.priority_score, item.connection_id),
            )
        ),
        tuple(sorted(unique_suppressions.values(), key=lambda item: item.suppression_id)),
    )


def _candidate_wire(candidate: CollegeConnectionCandidate) -> dict[str, Any]:
    return {
        "approval_state": candidate.approval_state.value,
        "completeness_states": list(candidate.completeness_states),
        "connection_id": candidate.connection_id,
        "connection_type": candidate.connection_type.value,
        "evidence_fingerprints": list(candidate.evidence_fingerprints),
        "evidence_record_ids": list(candidate.evidence_record_ids),
        "evidence_source_ids": list(candidate.evidence_source_ids),
        "evidence_version_hash": candidate.evidence_version_hash,
        "game_relevance": candidate.game_relevance,
        "priority_score": candidate.priority_score,
        "program_display_names": list(candidate.program_display_names),
        "program_ids": list(candidate.program_ids),
        "review_state": candidate.review_state.value,
        "season_scope": list(candidate.season_scope),
        "subject_display_names": list(candidate.subject_display_names),
        "subject_player_ids": list(candidate.subject_player_ids),
        "suppression_reason": candidate.suppression_reason,
        "uncertainty_info": list(candidate.uncertainty_info),
        "wording": candidate.wording,
    }


def _suppression_wire(suppression: ConnectionSuppression) -> dict[str, Any]:
    return {
        "connection_type": suppression.connection_type.value,
        "detail": suppression.detail,
        "evidence_record_ids": list(suppression.evidence_record_ids),
        "evidence_source_ids": list(suppression.evidence_source_ids),
        "program_ids": list(suppression.program_ids),
        "reason": suppression.reason,
        "subject_player_ids": list(suppression.subject_player_ids),
        "suppression_id": suppression.suppression_id,
    }


def serialize_connection_artifact(
    result: CollegeConnectionBuildResult, *, generated_at: datetime
) -> bytes:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return _json_bytes(
        {
            "candidates": [_candidate_wire(item) for item in result.candidates],
            "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
            "schema_name": CONNECTION_SCHEMA_NAME,
            "schema_version": CONNECTION_SCHEMA_VERSION,
            "suppressions": [_suppression_wire(item) for item in result.suppressions],
        }
    )


def _strict(raw: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"{label} fields are missing or unknown")


def load_connection_artifact(payload: bytes) -> CollegeConnectionBuildResult:
    if not isinstance(payload, bytes) or len(payload) > MAX_CONNECTION_PAYLOAD_BYTES:
        raise ValueError("connection payload exceeds the safe size limit")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("connection payload is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("connection payload root must be an object")
    _strict(
        raw,
        {"schema_name", "schema_version", "generated_at", "candidates", "suppressions"},
        "connection payload",
    )
    if raw["schema_name"] != CONNECTION_SCHEMA_NAME:
        raise ValueError("connection schema name is unsupported")
    if raw["schema_version"] != CONNECTION_SCHEMA_VERSION:
        raise ValueError("connection schema version is unsupported")
    try:
        generated_at = datetime.fromisoformat(str(raw["generated_at"]))
    except ValueError as exc:
        raise ValueError("connection generated_at is invalid") from exc
    if generated_at.tzinfo is None:
        raise ValueError("connection generated_at must be timezone-aware")
    candidate_fields = {
        "approval_state", "completeness_states", "connection_id", "connection_type",
        "evidence_fingerprints", "evidence_record_ids", "evidence_source_ids",
        "evidence_version_hash", "game_relevance", "priority_score",
        "program_display_names", "program_ids", "review_state", "season_scope",
        "subject_display_names", "subject_player_ids", "suppression_reason",
        "uncertainty_info", "wording",
    }
    candidates = []
    if not isinstance(raw["candidates"], list):
        raise ValueError("connection candidates must be an array")
    for item in raw["candidates"]:
        if not isinstance(item, dict):
            raise ValueError("connection candidate must be an object")
        _strict(item, candidate_fields, "connection candidate")
        candidate = CollegeConnectionCandidate(
            connection_type=item["connection_type"],
            subject_player_ids=tuple(item["subject_player_ids"]),
            subject_display_names=tuple(item["subject_display_names"]),
            program_ids=tuple(item["program_ids"]),
            program_display_names=tuple(item["program_display_names"]),
            season_scope=tuple(item["season_scope"]),
            wording=item["wording"],
            evidence_source_ids=tuple(item["evidence_source_ids"]),
            evidence_record_ids=tuple(item["evidence_record_ids"]),
            evidence_fingerprints=tuple(item["evidence_fingerprints"]),
            review_state=item["review_state"],
            approval_state=item["approval_state"],
            priority_score=item["priority_score"],
            completeness_states=tuple(item["completeness_states"]),
            uncertainty_info=tuple(item["uncertainty_info"]),
            game_relevance=item["game_relevance"],
            suppression_reason=item["suppression_reason"],
        )
        if item["connection_id"] != candidate.connection_id:
            raise ValueError("connection stable ID does not match candidate content")
        if item["evidence_version_hash"] != candidate.evidence_version_hash:
            raise ValueError("connection evidence hash does not match candidate content")
        candidates.append(candidate)
    suppression_fields = {
        "connection_type", "detail", "evidence_record_ids", "evidence_source_ids",
        "program_ids", "reason", "subject_player_ids", "suppression_id",
    }
    suppressions = []
    if not isinstance(raw["suppressions"], list):
        raise ValueError("connection suppressions must be an array")
    for item in raw["suppressions"]:
        if not isinstance(item, dict):
            raise ValueError("connection suppression must be an object")
        _strict(item, suppression_fields, "connection suppression")
        suppression = ConnectionSuppression(
            connection_type=item["connection_type"],
            subject_player_ids=tuple(item["subject_player_ids"]),
            program_ids=tuple(item["program_ids"]),
            reason=item["reason"],
            detail=item["detail"],
            evidence_source_ids=tuple(item["evidence_source_ids"]),
            evidence_record_ids=tuple(item["evidence_record_ids"]),
        )
        if item["suppression_id"] != suppression.suppression_id:
            raise ValueError("connection suppression ID does not match content")
        suppressions.append(suppression)
    result = CollegeConnectionBuildResult(tuple(candidates), tuple(suppressions))
    if len({item.connection_id for item in result.candidates}) != len(result.candidates):
        raise ValueError("connection payload contains duplicate stable IDs")
    if len({item.suppression_id for item in result.suppressions}) != len(result.suppressions):
        raise ValueError("connection payload contains duplicate suppression IDs")
    return result
