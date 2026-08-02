from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ausl_college import (
    CORE_RESUME_V1,
    CandidateValue,
    CollegeEnvelope,
    CollegeResume,
    IdentityMapping,
    IdentityReviewState,
    Program,
    ProgramStint,
    SourceProvenance,
    SourceType,
    StatRecord,
    StatRecordType,
    UnsupportedSchemaVersion,
    ValueState,
    load_envelope,
    serialize_envelope,
    validate_envelope,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def envelope():
    source = SourceProvenance(
        source_id="src-1",
        source_type=SourceType.NCAA_STATISTICS,
        organization="Synthetic NCAA Fixture",
        title="Synthetic stats",
        url="https://example.invalid/stats",
        locator="row 7",
        effective_date="2025",
        retrieved_at=NOW,
        version="fixture-v1",
        content_hash="sha256:" + "b" * 64,
        verification_state="verified",
        reviewer="Fixture Reviewer",
        approved_at=NOW,
        review_note="Synthetic fixture.",
    )
    identity = IdentityMapping(
        mapping_id="identity-301",
        ausl_player_id="ausl-301",
        source_id="src-1",
        source_athlete_id="ncaa-301",
        aliases=("R. Fiction",),
        review_state=IdentityReviewState.VERIFIED,
        reviewer="Fixture Reviewer",
        reviewed_at=NOW,
        evidence_reference="Synthetic crosswalk",
    )
    program = Program(
        program_id="sample-university",
        display_name="Sample University",
        source_ids=("src-1",),
    )
    stint = ProgramStint(
        stint_id="stint-301",
        program_id=program.program_id,
        transfer_order=1,
        start_season=2024,
        end_season=2025,
        provenance_ids=("src-1",),
    )
    candidate = CandidateValue(
        candidate_id="avg-301",
        field_path="stats.batting_average",
        value=Decimal("0.333"),
        value_state=ValueState.PRESENT,
        source_id="src-1",
        player_id="ausl-301",
        program_id=program.program_id,
        season=2025,
        record_type="season_batting",
        metric_definition="batting_average",
        unit="rate",
    )
    stat = StatRecord(
        record_id="batting-301-2025",
        record_type=StatRecordType.SEASON_BATTING,
        role="hitter",
        player_id="ausl-301",
        program_id=program.program_id,
        season=2025,
        candidates=(candidate,),
    )
    resume = CollegeResume(
        resume_id="resume-301",
        player_id="ausl-301",
        canonical_display_name="Riley Fiction",
        display_name_source_id="src-1",
        identity_mappings=(identity,),
        programs=(program,),
        stints=(stint,),
        stat_records=(stat,),
        achievements=(),
        section_statuses=(("identity", "verified"), ("programs", "verified"), ("statistics", "verified"), ("achievements", "not_applicable")),
    )
    return CollegeEnvelope(
        generated_at=NOW,
        completeness_profile=CORE_RESUME_V1,
        resumes=(resume,),
        sources=(source,),
        validation_metadata=(("fixture", "synthetic"),),
    )


def test_deterministic_round_trip_bytes_and_decimal_preservation():
    first = serialize_envelope(envelope())
    second = serialize_envelope(envelope())
    loaded = load_envelope(first)
    assert first == second == serialize_envelope(loaded)
    assert b'"0.333"' in first
    assert loaded == envelope()


def test_ordering_is_deterministic_across_input_order():
    original = envelope()
    extra = replace(original.sources[0], source_id="src-0")
    a = replace(original, sources=(original.sources[0], extra))
    b = replace(original, sources=(extra, original.sources[0]))
    assert serialize_envelope(a) == serialize_envelope(b)


def test_future_unversioned_malformed_and_unknown_fields_fail_closed():
    valid = json.loads(serialize_envelope(envelope()))
    future = {**valid, "schema_version": 99}
    with pytest.raises(UnsupportedSchemaVersion):
        load_envelope(json.dumps(future).encode())
    for invalid in ({"resumes": []}, {**valid, "unexpected": True}, []):
        with pytest.raises(ValueError):
            load_envelope(json.dumps(invalid).encode())


def test_invalid_timestamp_nonfinite_and_hostile_payloads_are_bounded():
    valid = json.loads(serialize_envelope(envelope()))
    valid["generated_at"] = "2026-08-01T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        load_envelope(json.dumps(valid).encode())
    with pytest.raises(ValueError, match="payload"):
        load_envelope(b"{" + b" " * (5_000_001))
    deeply_nested = b'{"schema_name":"ausl-college-resume","schema_version":1,"generated_at":"2026-08-01T12:00:00+00:00","completeness_profile":"CORE_RESUME_V1","sources":[],"resumes":[],"validation_metadata":' + b"[" * 30 + b"]" * 30 + b"}"
    with pytest.raises(ValueError, match="depth"):
        load_envelope(deeply_nested)


def test_validation_reports_duplicate_ids_counts_and_safe_records():
    original = envelope()
    duplicate = replace(original, resumes=(original.resumes[0], original.resumes[0]))
    report = validate_envelope(duplicate)
    assert not report.valid
    assert report.player_count == 2
    assert report.duplicate_stable_ids == ("resume-301",)
    assert report.completeness_totals


def test_validation_reports_conflicting_source_athlete_ids():
    original = envelope()
    mapping = original.resumes[0].identity_mappings[0]
    conflict = replace(
        mapping,
        mapping_id="identity-301-conflict",
        source_athlete_id="ncaa-other-301",
    )
    resume = replace(
        original.resumes[0], identity_mappings=(mapping, conflict)
    )
    report = validate_envelope(replace(original, resumes=(resume,)))
    assert not report.valid
    assert report.unresolved_identities == ("resume-301",)
    assert any("conflicting source athlete IDs" in error for error in report.errors)


def test_validation_reports_unsupported_metric_definition():
    original = envelope()
    record = original.resumes[0].stat_records[0]
    unsupported = replace(
        record.candidates[0],
        metric_definition="mystery_efficiency",
        field_path="stats.mystery_efficiency",
    )
    record = replace(record, candidates=(unsupported,))
    resume = replace(original.resumes[0], stat_records=(record,))
    report = validate_envelope(replace(original, resumes=(resume,)))
    assert not report.valid
    assert report.unsupported_metric_definitions == (
        "resume-301:mystery_efficiency",
    )
