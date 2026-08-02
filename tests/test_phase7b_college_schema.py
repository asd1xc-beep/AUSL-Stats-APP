from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ausl_college import (
    CandidateValue,
    CollegeResume,
    IdentityMapping,
    IdentityReviewState,
    PlayerRole,
    Program,
    ProgramStint,
    SeasonKind,
    SourceProvenance,
    SourceType,
    StatRecord,
    StatRecordType,
    ValueState,
    innings_to_outs,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def source(source_id="src-school"):
    return SourceProvenance(
        source_id=source_id,
        source_type=SourceType.OFFICIAL_SCHOOL,
        organization="Fictional State Athletics",
        title="2025 record book",
        url="https://example.invalid/record-book",
        locator="page 12, batting table",
        effective_date="2025",
        retrieved_at=NOW,
        version="manual-entry-v1",
        content_hash="sha256:" + "a" * 64,
        verification_state="verified",
        reviewer="Fixture Reviewer",
        approved_at=NOW,
        review_note="Synthetic fixture reviewed for schema tests.",
    )


def candidate(candidate_id, value, *, metric="hits", record_type="season_batting"):
    return CandidateValue(
        candidate_id=candidate_id,
        field_path=f"stats.{metric}",
        value=value,
        value_state=ValueState.PRESENT,
        source_id="src-school",
        player_id="ausl-101",
        program_id="fictional-state",
        season=2025,
        record_type=record_type,
        metric_definition=metric,
        unit="rate" if isinstance(value, (Decimal, float)) else "count",
    )


def identity(state=IdentityReviewState.VERIFIED):
    return IdentityMapping(
        mapping_id="identity-ausl-101",
        ausl_player_id="ausl-101",
        source_id="src-school",
        source_athlete_id="fsu-44",
        aliases=("A. Example",),
        review_state=state,
        reviewer="Fixture Reviewer" if state is IdentityReviewState.VERIFIED else None,
        reviewed_at=NOW if state is IdentityReviewState.VERIFIED else None,
        evidence_reference="Roster ID crosswalk" if state is IdentityReviewState.VERIFIED else None,
    )


def test_identity_requires_stable_ausl_id_and_never_accepts_name_only():
    with pytest.raises(ValueError, match="AUSL player_id"):
        IdentityMapping(
            mapping_id="name-only",
            ausl_player_id="",
            source_id="src-school",
            source_athlete_id="fsu-44",
            aliases=("Alex Example",),
            review_state=IdentityReviewState.VERIFIED,
            reviewer="Reviewer",
            reviewed_at=NOW,
            evidence_reference="A name is not proof",
        )


def test_reviewed_alias_does_not_replace_stable_identity():
    mapping = identity()
    assert mapping.ausl_player_id == "ausl-101"
    assert mapping.aliases == ("A. Example",)


def test_program_stints_support_transfer_and_unusual_seasons_without_guessing():
    first = ProgramStint(
        stint_id="stint-1",
        program_id="fictional-state",
        transfer_order=1,
        start_season=2021,
        end_season=2023,
        season_kinds=((2021, SeasonKind.REDSHIRT), (2022, SeasonKind.SHORTENED)),
        provenance_ids=("src-school",),
    )
    second = ProgramStint(
        stint_id="stint-2",
        program_id="invented-tech",
        transfer_order=2,
        start_season=None,
        end_season=2025,
        season_kinds=((2025, SeasonKind.EXTRA_ELIGIBILITY),),
        uncertainty_note="Transfer start season is not established by the source.",
        provenance_ids=("src-school",),
    )
    assert first.transfer_order < second.transfer_order
    assert second.start_season is None
    assert second.uncertainty_note


def test_two_way_batting_and_pitching_records_remain_independent():
    batting = StatRecord(
        record_id="bat-2025",
        record_type=StatRecordType.SEASON_BATTING,
        role=PlayerRole.HITTER,
        player_id="ausl-101",
        program_id="fictional-state",
        season=2025,
        candidates=(candidate("hits-1", 42),),
    )
    pitching = StatRecord(
        record_id="pitch-2025",
        record_type=StatRecordType.SEASON_PITCHING,
        role=PlayerRole.PITCHER,
        player_id="ausl-101",
        program_id="fictional-state",
        season=2025,
        candidates=(candidate("so-1", 88, metric="strikeouts", record_type="season_pitching"),),
    )
    assert batting.record_type is StatRecordType.SEASON_BATTING
    assert pitching.record_type is StatRecordType.SEASON_PITCHING


@pytest.mark.parametrize(("notation", "outs"), [("7", 21), ("7.1", 22), ("7.2", 23), (0, 0)])
def test_pitching_innings_use_canonical_outs(notation, outs):
    assert innings_to_outs(notation) == outs


@pytest.mark.parametrize("notation", ["7.3", "7.25", -1, float("nan"), float("inf"), True])
def test_malformed_or_nonfinite_innings_fail_closed(notation):
    with pytest.raises(ValueError):
        innings_to_outs(notation)


def test_missing_and_explicit_zero_are_distinct():
    zero = candidate("zero", 0)
    missing = CandidateValue(
        candidate_id="missing",
        field_path="stats.hits",
        value=None,
        value_state=ValueState.MISSING,
        source_id="src-school",
        player_id="ausl-101",
        program_id="fictional-state",
        season=2025,
        record_type="season_batting",
        metric_definition="hits",
        unit="count",
    )
    assert zero.value == 0 and zero.value_state is ValueState.PRESENT
    assert missing.value is None and missing.value_state is ValueState.MISSING


def test_rate_values_are_lossless_decimal_text_and_nonfinite_values_rejected():
    rate = candidate("avg", Decimal("0.375"), metric="batting_average")
    assert rate.value == Decimal("0.375")
    with pytest.raises(ValueError, match="finite"):
        candidate("bad", float("nan"), metric="batting_average")


def test_college_and_ausl_scopes_cannot_be_combined():
    with pytest.raises(ValueError, match="college scope"):
        candidate("bad-scope", 5, metric="ausl_hits")


def test_program_requires_stable_identity_and_provenance():
    program = Program(
        program_id="fictional-state",
        display_name="Fictional State",
        source_ids=("src-school",),
        source_identifiers=(("src-school", "FSU"),),
        historical_names=("Fictional Normal School",),
    )
    assert program.program_id == "fictional-state"
