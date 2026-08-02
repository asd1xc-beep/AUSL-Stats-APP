from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from test_phase7b_college_serialization import envelope

from ausl_college import (
    CompletenessState,
    IdentityReviewState,
    assess_completeness,
    derive_career_record,
)


def test_fully_evidenced_core_resume_is_verified():
    data = envelope()
    result = assess_completeness(data.resumes[0], data)
    assert result.state is CompletenessState.VERIFIED
    assert result.blocking_reasons == ()
    assert result.missing_fields == ()


def test_safe_incomplete_resume_is_partial_with_machine_readable_missing_list():
    data = envelope()
    resume = replace(
        data.resumes[0],
        section_statuses=(("identity", "verified"), ("programs", "verified"), ("statistics", "verified"), ("achievements", "unavailable")),
    )
    result = assess_completeness(resume, replace(data, resumes=(resume,)))
    assert result.state is CompletenessState.PARTIAL
    assert result.missing_fields == ("sections.achievements",)


def test_ambiguous_identity_and_blocking_conflict_need_review():
    data = envelope()
    mapping = replace(data.resumes[0].identity_mappings[0], review_state=IdentityReviewState.AMBIGUOUS, reviewer=None, reviewed_at=None, evidence_reference=None)
    resume = replace(data.resumes[0], identity_mappings=(mapping,))
    result = assess_completeness(resume, replace(data, resumes=(resume,)))
    assert result.state is CompletenessState.NEEDS_REVIEW
    assert "ambiguous_identity" in result.blocking_reasons


def test_missing_field_level_provenance_prevents_verified_completeness():
    data = envelope()
    resume = replace(data.resumes[0], display_name_source_id="missing-source")
    result = assess_completeness(resume, replace(data, resumes=(resume,)))
    assert result.state is CompletenessState.NEEDS_REVIEW
    assert "missing_or_unverified_provenance" in result.blocking_reasons


def test_source_reported_and_derived_career_totals_remain_distinct():
    data = envelope()
    season = data.resumes[0].stat_records[0]
    derived = derive_career_record(
        (season,),
        record_id="derived-career-301",
        expected_seasons=(2025,),
        verified_source_ids=("src-1",),
    )
    assert derived is not None
    assert derived.record_type.value == "derived_career_batting"
    assert season.record_type.value == "season_batting"


def test_unsafe_partial_aggregation_is_unavailable():
    data = envelope()
    season = data.resumes[0].stat_records[0]
    unavailable = replace(season.candidates[0], value=None, value_state="missing")
    incomplete = replace(season, candidates=(unavailable,))
    assert derive_career_record(
        (incomplete,),
        record_id="unsafe",
        expected_seasons=(2025,),
        verified_source_ids=("src-1",),
    ) is None


def test_derived_career_requires_complete_declared_scope_and_verified_sources():
    data = envelope()
    season = data.resumes[0].stat_records[0]
    assert derive_career_record((season,), record_id="missing-scope") is None
    assert derive_career_record(
        (season,),
        record_id="wrong-scope",
        expected_seasons=(2024, 2025),
        verified_source_ids=("src-1",),
    ) is None
    assert derive_career_record(
        (season,),
        record_id="unverified",
        expected_seasons=(2025,),
        verified_source_ids=(),
    ) is None


def test_conflicting_component_candidates_block_derived_career():
    data = envelope()
    season = data.resumes[0].stat_records[0]
    conflict = replace(
        season.candidates[0], candidate_id="conflict", value=Decimal("0.334")
    )
    conflicted = replace(season, candidates=(*season.candidates, conflict))
    assert derive_career_record(
        (conflicted,),
        record_id="conflicted",
        expected_seasons=(2025,),
        verified_source_ids=("src-1",),
    ) is None
