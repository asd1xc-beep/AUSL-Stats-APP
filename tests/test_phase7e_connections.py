from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ausl_college import (
    Achievement,
    AchievementType,
    CollegeEnvelope,
    CollegeResume,
    IdentityMapping,
    IdentityReviewState,
    Program,
    ProgramStint,
    SourceProvenance,
    SourceType,
)
from ausl_college_batch_approval import load_aggregate_approval
from ausl_college_connections import (
    CollegeConnectionCandidate,
    ConnectionApprovalState,
    ConnectionReviewState,
    ConnectionType,
    build_college_connections,
    load_connection_artifact,
    serialize_connection_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
AGGREGATE = ROOT / "data" / "college_approved_phase7e"
NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _source(source_id: str, *, verified=True, version="v1"):
    return SourceProvenance(
        source_id=source_id,
        source_type=SourceType.OFFICIAL_SCHOOL,
        organization="Official School",
        title=f"Source {source_id}",
        locator="record 1",
        retrieved_at=NOW,
        version=version,
        verification_state="verified" if verified else "needs_review",
        url=f"https://example.edu/{source_id}",
    )


def _resume(
    player_id: str,
    name: str,
    programs: tuple[tuple[str, str, int | None, int | None], ...],
    *,
    achievements=(),
):
    source_id = f"source-{player_id}"
    program_models = tuple(
        Program(program_id, display, (source_id,))
        for program_id, display, _start, _end in programs
    )
    stints = tuple(
        ProgramStint(
            f"stint-{player_id}-{index}",
            program_id,
            index,
            start,
            end,
            (source_id,),
            uncertainty_note=(
                "Exact attendance seasons unavailable."
                if start is None or end is None
                else None
            ),
        )
        for index, (program_id, _display, start, end) in enumerate(programs, 1)
    )
    return CollegeResume(
        resume_id=f"resume-{player_id}",
        player_id=player_id,
        canonical_display_name=name,
        display_name_source_id=source_id,
        identity_mappings=(
            IdentityMapping(
                f"identity-{player_id}",
                player_id,
                source_id,
                f"athlete-{player_id}",
                (),
                IdentityReviewState.VERIFIED,
                reviewer="project_owner",
                reviewed_at=NOW,
                evidence_reference=f"review-{player_id}",
            ),
        ),
        programs=program_models,
        stints=stints,
        stat_records=(),
        achievements=tuple(achievements),
        section_statuses=(
            ("identity", "verified"),
            ("programs", "verified"),
            ("statistics", "unavailable"),
            ("achievements", "verified" if achievements else "unavailable"),
        ),
    )


def _envelope(*resumes, sources=None):
    if sources is None:
        sources = tuple(_source(f"source-{resume.player_id}") for resume in resumes)
    return CollegeEnvelope(NOW, "CORE_RESUME_V1", tuple(resumes), tuple(sources))


def test_transfer_wording_is_deterministic_and_retains_all_evidence():
    resume = _resume(
        "10",
        "Exact Player",
        (("alpha", "Alpha", 2021, 2022), ("beta", "Beta", 2023, 2024)),
    )
    result = build_college_connections(_envelope(resume))
    candidate = next(
        item for item in result.candidates if item.connection_type is ConnectionType.TRANSFER
    )

    assert candidate.wording == (
        "COLLEGE CONNECTION — Exact Player played at Alpha before moving to Beta."
    )
    assert candidate.subject_player_ids == ("10",)
    assert candidate.program_ids == ("alpha", "beta")
    assert candidate.season_scope == ("2021-2022", "2023-2024")
    assert candidate.evidence_source_ids == ("source-10",)
    assert set(candidate.evidence_record_ids) == {
        "program:alpha",
        "program:beta",
        "stint:stint-10-1",
        "stint:stint-10-2",
    }
    assert not candidate.air_ready


def test_stable_identity_is_separate_from_evidence_version():
    resume = _resume(
        "10",
        "Exact Player",
        (("alpha", "Alpha", 2021, 2022), ("beta", "Beta", 2023, 2024)),
    )
    candidate = build_college_connections(_envelope(resume)).candidates[0]
    changed = replace(
        candidate,
        wording="COLLEGE CONNECTION — Exact Player attended Alpha before Beta.",
    )

    assert changed.connection_id == candidate.connection_id
    assert changed.evidence_version_hash != candidate.evidence_version_hash


def test_nonoverlapping_same_program_is_precise_but_overlap_does_not_prove_teammates():
    earlier = _resume("10", "Earlier Player", (("alpha", "Alpha", 2018, 2020),))
    later = _resume("11", "Later Player", (("alpha", "Alpha", 2022, 2024),))
    overlap = _resume("12", "Overlap Player", (("alpha", "Alpha", 2020, 2023),))
    result = build_college_connections(_envelope(earlier, later, overlap))

    shared = [
        item
        for item in result.candidates
        if item.connection_type is ConnectionType.SHARED_PROGRAM
        and item.subject_player_ids == ("10", "11")
    ]
    assert len(shared) == 1
    assert "two seasons apart" in shared[0].wording
    assert not any(
        item.connection_type is ConnectionType.FORMER_COLLEGE_TEAMMATES
        for item in result.candidates
    )
    assert any(
        item.reason == "stint_overlap_does_not_prove_teammates"
        for item in result.suppressions
    )


def test_missing_season_or_unverified_source_suppresses_connection():
    exact = _resume("10", "Exact", (("alpha", "Alpha", 2020, 2021),))
    unknown = _resume("11", "Unknown", (("alpha", "Alpha", None, None),))
    sources = (_source("source-10"), _source("source-11", verified=False))
    result = build_college_connections(_envelope(exact, unknown, sources=sources))

    assert result.candidates == ()
    reasons = {item.reason for item in result.suppressions}
    assert "season_scope_unavailable" in reasons or "source_not_verified" in reasons


def test_championship_teammates_require_exact_program_and_year_evidence():
    a = _resume("10", "Alpha", (("school", "School", 2024, 2024),))
    b = _resume("11", "Beta", (("school", "School", 2024, 2024),))
    a = replace(
        a,
        achievements=(
            Achievement("ach-a", AchievementType.CHAMPIONSHIP, "team", "10", "school", "2024", "2024 NCAA champion", None, ("source-10",)),
        ),
        section_statuses=tuple((key, "verified") for key, _value in a.section_statuses),
    )
    b = replace(
        b,
        achievements=(
            Achievement("ach-b", AchievementType.CHAMPIONSHIP, "team", "11", "school", "2024", "2024 NCAA champion", None, ("source-11",)),
        ),
        section_statuses=tuple((key, "verified") for key, _value in b.section_statuses),
    )
    candidate = next(
        item
        for item in build_college_connections(_envelope(a, b)).candidates
        if item.connection_type is ConnectionType.CHAMPIONSHIP_TEAMMATES
    )

    assert candidate.wording == (
        "COLLEGE CONNECTION — Alpha and Beta were School teammates on the 2024 national championship team."
    )
    assert set(candidate.evidence_source_ids) == {"source-10", "source-11"}
    assert set(candidate.evidence_record_ids) == {"achievement:ach-a", "achievement:ach-b"}


def test_shared_award_normalization_requires_exact_reviewable_label():
    a = _resume("10", "Alpha", (("a", "A", 2023, 2023),))
    b = _resume("11", "Beta", (("b", "B", 2024, 2024),))
    a = replace(
        a,
        achievements=(
            Achievement("award-a", AchievementType.NATIONAL_AWARD, "individual", "10", "a", "2023", "2023 Player of the Year", None, ("source-10",)),
        ),
        section_statuses=tuple((key, "verified") for key, _value in a.section_statuses),
    )
    b = replace(
        b,
        achievements=(
            Achievement("award-b", AchievementType.NATIONAL_AWARD, "individual", "11", "b", "2024", "2024 Player of the Year", None, ("source-11",)),
        ),
        section_statuses=tuple((key, "verified") for key, _value in b.section_statuses),
    )
    result = build_college_connections(_envelope(a, b))
    shared = next(
        item for item in result.candidates if item.connection_type is ConnectionType.SHARED_AWARD
    )

    assert shared.wording == (
        "COLLEGE CONNECTION — Alpha (2023) and Beta (2024) both earned Player of the Year."
    )


def test_serialization_is_deterministic_and_rejects_approval_shortcuts():
    artifact = load_aggregate_approval(AGGREGATE)
    result = build_college_connections(artifact.envelope)
    first = serialize_connection_artifact(result, generated_at=NOW)
    second = serialize_connection_artifact(result, generated_at=NOW)

    assert first == second
    loaded = load_connection_artifact(first)
    assert loaded == result
    assert all(
        candidate.review_state is ConnectionReviewState.ELIGIBLE_FOR_REVIEW
        and candidate.approval_state is ConnectionApprovalState.UNREVIEWED
        and not candidate.air_ready
        for candidate in loaded.candidates
    )
    assert b"producer_approved" not in first


def test_connection_model_rejects_independently_editable_air_ready_state():
    fields = CollegeConnectionCandidate.__dataclass_fields__
    assert "air_ready" not in fields

