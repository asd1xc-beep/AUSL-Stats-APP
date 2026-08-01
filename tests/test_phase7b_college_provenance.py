from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ausl_college import (
    CandidateValue,
    ManualResolution,
    ResolutionState,
    SourceProvenance,
    SourceType,
    ValueState,
    resolve_candidates,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def source(source_id, source_type):
    return SourceProvenance(
        source_id=source_id,
        source_type=source_type,
        organization="Synthetic Source",
        title="Synthetic evidence",
        url="https://example.invalid/evidence",
        locator="record 1",
        effective_date="2025",
        retrieved_at=NOW,
        version="fixture-v1",
        verification_state="verified",
        reviewer="Fixture Reviewer",
        approved_at=NOW,
        review_note="Synthetic only.",
    )


def candidate(candidate_id, value, source_id="school", **overrides):
    values = dict(
        candidate_id=candidate_id,
        field_path="stats.hits",
        value=value,
        value_state=ValueState.PRESENT,
        source_id=source_id,
        player_id="ausl-201",
        program_id="invented-tech",
        season=2025,
        record_type="season_batting",
        metric_definition="hits",
        unit="count",
    )
    values.update(overrides)
    return CandidateValue(**values)


def catalog():
    return {
        "ncaa": source("ncaa", SourceType.NCAA_STATISTICS),
        "school": source("school", SourceType.OFFICIAL_SCHOOL),
        "manual": source("manual", SourceType.MANUAL_VERIFIED),
    }


def test_equivalent_compatible_candidates_resolve_deterministically():
    result = resolve_candidates(
        (candidate("school-value", 44), candidate("ncaa-value", 44, "ncaa")),
        catalog(),
    )
    assert result.state is ResolutionState.RESOLVED
    assert result.selected_candidate_id == "ncaa-value"
    assert set(result.rejected_candidate_ids) == {"school-value"}


def test_conflicting_values_are_preserved_and_not_overwritten_by_priority():
    values = (candidate("school-value", 44), candidate("ncaa-value", 45, "ncaa"))
    result = resolve_candidates(values, catalog())
    assert result.state is ResolutionState.CONFLICTING
    assert result.selected_candidate_id is None
    assert result.candidates == values


def test_incompatible_definitions_remain_separate_not_direct_conflicts():
    result = resolve_candidates(
        (
            candidate("hits", 44),
            candidate("games", 52, metric_definition="games", field_path="stats.games"),
        ),
        catalog(),
    )
    assert result.state is ResolutionState.INCOMPATIBLE
    assert "dimensions" in result.reason


def test_manual_resolution_requires_full_review_evidence():
    values = (candidate("a", 44), candidate("b", 45, "ncaa"))
    with pytest.raises(ValueError, match="reviewer"):
        ManualResolution(
            selected_candidate_id="a",
            reviewer="",
            resolved_at=NOW,
            reason="Checked scorebook",
            evidence_source_id="manual",
        )
    resolution = ManualResolution(
        selected_candidate_id="a",
        reviewer="Fixture Reviewer",
        resolved_at=NOW,
        reason="Synthetic scorebook resolves the discrepancy.",
        evidence_source_id="manual",
    )
    result = resolve_candidates(values, catalog(), manual_resolution=resolution)
    assert result.state is ResolutionState.RESOLVED
    assert result.selected_candidate_id == "a"
    assert result.candidates == values
    assert result.manual_resolution == resolution


def test_missing_provenance_fails_closed():
    result = resolve_candidates((candidate("orphan", 44, "missing"),), catalog())
    assert result.state is ResolutionState.UNAVAILABLE
    assert result.selected_candidate_id is None


def test_manual_source_type_is_not_self_approving():
    with pytest.raises(ValueError, match="manual source"):
        SourceProvenance(
            source_id="manual-bad",
            source_type=SourceType.MANUAL_VERIFIED,
            organization="Producer",
            title="Manual entry",
            local_document_id="review-1",
            locator="field note",
            retrieved_at=NOW,
            version="manual-v1",
            verification_state="verified",
        )
