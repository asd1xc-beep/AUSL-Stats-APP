from __future__ import annotations

from pathlib import Path

from ausl_college_approval import load_checked_in_approval
from ausl_college_view import build_college_resume_view, format_innings_outs
from ausl_enrichment import EnrichmentMode


ROOT = Path(__file__).resolve().parents[1]


def _artifact():
    return load_checked_in_approval(ROOT / "data" / "college_approved")


def test_all_ten_players_render_with_explicit_college_scope():
    artifact = _artifact()
    for resume in artifact.envelope.resumes:
        view = build_college_resume_view(
            artifact,
            player_id=resume.player_id,
            mode=EnrichmentMode.PRODUCER_APPROVED,
        )
        assert view.available
        assert view.player_id == resume.player_id
        for field in view.stat_fields:
            assert "COLLEGE" in field.scope_label
            assert "Career Stats" not in field.copy_text


def test_hitter_pitcher_two_way_and_transfer_views_stay_separate():
    artifact = _artifact()
    hitter = build_college_resume_view(artifact, player_id="1075", mode=EnrichmentMode.PRODUCER_APPROVED)
    pitcher = build_college_resume_view(artifact, player_id="1285", mode=EnrichmentMode.PRODUCER_APPROVED)
    two_way = build_college_resume_view(artifact, player_id="950", mode=EnrichmentMode.PRODUCER_APPROVED)
    transfer = build_college_resume_view(artifact, player_id="1102", mode=EnrichmentMode.PRODUCER_APPROVED)

    assert hitter.batting_fields and not hitter.pitching_fields
    assert pitcher.pitching_fields and not pitcher.batting_fields
    assert two_way.batting_fields and two_way.pitching_fields
    assert transfer.school_timeline == ("Louisville", "Florida")


def test_career_and_season_labels_include_program_and_never_mix_ausl():
    artifact = _artifact()
    career = build_college_resume_view(artifact, player_id="950", mode=EnrichmentMode.PRODUCER_APPROVED)
    season = build_college_resume_view(artifact, player_id="278", mode=EnrichmentMode.PRODUCER_APPROVED)
    assert all("COLLEGE CAREER" in item.scope_label for item in career.stat_fields)
    assert all("2021 COLLEGE SEASON" in item.scope_label for item in season.stat_fields)
    assert all("AUSL CAREER" not in item.copy_text for item in (*career.stat_fields, *season.stat_fields))


def test_partial_resume_and_nonpilot_player_are_honest():
    artifact = _artifact()
    partial = build_college_resume_view(artifact, player_id="1322", mode=EnrichmentMode.PRODUCER_APPROVED)
    missing = build_college_resume_view(artifact, player_id="999999", mode=EnrichmentMode.PRODUCER_APPROVED)
    assert partial.completeness == "Partial"
    assert "achievements" in " ".join(partial.missing_fields).casefold()
    assert not missing.available
    assert "no college history has been inferred" in missing.message


def test_copy_text_is_field_specific_and_contains_source_and_review_date():
    artifact = _artifact()
    view = build_college_resume_view(artifact, player_id="950", mode=EnrichmentMode.PRODUCER_APPROVED)
    field = view.stat_fields[0]
    assert field.copy_eligible
    assert "VALERIE CAGLE" in field.copy_text
    assert "COLLEGE CAREER" in field.copy_text
    assert "CLEMSON" in field.copy_text
    assert "Source:" in field.copy_with_source
    assert "reviewed 2026-08-11" in field.copy_with_source


def test_developer_review_fields_are_not_copyable():
    artifact = _artifact()
    view = build_college_resume_view(artifact, player_id="950", mode=EnrichmentMode.DEVELOPER_REVIEW)
    assert view.available
    assert all(not field.copy_eligible for field in view.stat_fields)
    assert all("developer review" in field.block_reason.casefold() for field in view.stat_fields)


def test_canonical_outs_and_missing_formatting():
    assert format_innings_outs(409) == "136.1 IP"
    assert format_innings_outs(0) == "0.0 IP"
    assert format_innings_outs(None) == "Unavailable"

