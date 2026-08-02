from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from ausl_college import (
    IdentityReviewState,
    PlayerRole,
    StatRecordType,
    assess_completeness,
    load_envelope,
    validate_envelope,
)
from ausl_college_import import (
    REQUIRED_COVERAGE,
    import_college_pilot,
    load_pilot_manifest,
    load_staging,
    validate_pilot_manifest,
)
from tools.build_phase7c_pilot_inputs import build


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data" / "college_pilot"
EXPECTED_IDS = {
    "169", "278", "933", "950", "1075", "1102", "1285", "1322", "1324", "1327"
}
OFFICIAL_HOSTS = {
    "byucougars.com",
    "data.clemsontigers.com",
    "floridagators.com",
    "jmusports.com",
    "soonersports.com",
    "texastech.com",
    "ukathletics.com",
    "uclabruins.com",
    "utsports.com",
}


def _roster() -> pd.DataFrame:
    with pd.ExcelFile(ROOT / "data" / "exports" / "ausl_rosters.xlsx") as workbook:
        return pd.read_excel(workbook, sheet_name="roster_2026")


def _manifest():
    return load_pilot_manifest((PILOT / "pilot_manifest.json").read_bytes())


def _envelope():
    return load_envelope((PILOT / "pilot_envelope.json").read_bytes())


def test_checked_in_pilot_is_exactly_ten_canonical_ausl_ids_with_full_coverage():
    manifest = _manifest()
    report = validate_pilot_manifest(manifest, _roster())
    assert report.valid, report.errors
    assert set(report.accepted_player_ids) == EXPECTED_IDS
    assert len(report.accepted_player_ids) == len(set(report.accepted_player_ids)) == 10
    assert REQUIRED_COVERAGE <= set(report.coverage_categories)


def test_checked_in_normalized_inputs_are_reproducible_from_offline_builder():
    manifest, staging = build()
    assert manifest == json.loads((PILOT / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert staging == json.loads((PILOT / "review_staging.json").read_text(encoding="utf-8"))
    cagle = next(item for item in staging["resumes"] if item["player_id"] == "950")
    innings = next(
        candidate
        for record in cagle["stat_records"]
        for candidate in record["candidates"]
        if candidate["metric_definition"] == "innings_outs"
    )
    assert innings["raw_source_value"] == "756.1"
    assert innings["value"] == 2269


def test_real_pilot_uses_official_sources_and_every_selected_value_is_traceable():
    envelope = _envelope()
    validation = validate_envelope(envelope)
    assert validation.valid, validation.errors
    assert not validation.missing_provenance
    assert not validation.unresolved_conflicts
    assert len(validation.unresolved_identities) == 10
    source_ids = {source.source_id for source in envelope.sources}
    for source in envelope.sources:
        if source.url:
            assert urlparse(source.url).hostname in OFFICIAL_HOSTS
        else:
            assert source.local_document_id == "data/exports/ausl_rosters.xlsx#roster_2026"
        assert source.reviewer is None
        assert source.approved_at is None
    for resume in envelope.resumes:
        assert resume.player_id in EXPECTED_IDS
        assert any(
            mapping.ausl_player_id == resume.player_id
            and mapping.source_id == "ausl-roster-2026"
            and mapping.review_state is IdentityReviewState.NEEDS_REVIEW
            for mapping in resume.identity_mappings
        )
        assert all(program.source_ids and set(program.source_ids) <= source_ids for program in resume.programs)
        assert all(stint.provenance_ids and set(stint.provenance_ids) <= source_ids for stint in resume.stints)
        assert all(
            candidate.source_id in source_ids
            and candidate.player_id == resume.player_id
            for record in resume.stat_records
            for candidate in record.candidates
        )
        assert all(
            achievement.provenance_ids
            and set(achievement.provenance_ids) <= source_ids
            for achievement in resume.achievements
        )
        assessment = assess_completeness(resume, envelope)
        assert assessment.state.value == "Needs Review"
        assert "identity_review_pending" in assessment.blocking_reasons


def test_two_way_pilot_records_keep_batting_and_pitching_separate():
    envelope = _envelope()
    by_id = {resume.player_id: resume for resume in envelope.resumes}
    for player_id in ("169", "278", "950", "1322", "1327"):
        records = by_id[player_id].stat_records
        assert all(record.role is PlayerRole.TWO_WAY for record in records)
        kinds = {record.record_type for record in records}
        assert kinds & {StatRecordType.SEASON_BATTING, StatRecordType.SOURCE_CAREER_BATTING}
        assert kinds & {StatRecordType.SEASON_PITCHING, StatRecordType.SOURCE_CAREER_PITCHING}
    agbayani = by_id["1322"]
    assert dict(agbayani.section_statuses)["achievements"] == "unavailable"
    assert "sections.achievements" in assess_completeness(agbayani, envelope).missing_fields


def test_independent_real_pilot_imports_are_byte_identical(tmp_path):
    first = tmp_path / "first.json"
    first_report = tmp_path / "first.md"
    second = tmp_path / "second.json"
    second_report = tmp_path / "second.md"
    args = (
        ROOT / "data" / "exports" / "ausl_rosters.xlsx",
        PILOT / "pilot_manifest.json",
        PILOT / "review_staging.json",
    )
    one = import_college_pilot(*args, first, first_report)
    two = import_college_pilot(*args, second, second_report)
    assert first.read_bytes() == second.read_bytes() == (PILOT / "pilot_envelope.json").read_bytes()
    assert first_report.read_bytes() == second_report.read_bytes() == (
        ROOT / "Implementation guide" / "Phase_7C_Review_Packet.md"
    ).read_bytes()
    assert one.envelope_sha256 == two.envelope_sha256
    assert one.review_report_sha256 == two.review_report_sha256


def test_staging_and_envelope_contain_no_producer_approval_shortcut():
    staging = load_staging((PILOT / "review_staging.json").read_bytes())
    text = (PILOT / "pilot_envelope.json").read_text(encoding="utf-8").casefold()
    assert len(staging.envelope.resumes) == 10
    assert "producer_approved" not in text
    assert '"reviewer":null' in text
