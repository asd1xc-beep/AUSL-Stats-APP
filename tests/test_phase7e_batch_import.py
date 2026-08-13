from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from ausl_college import CompletenessState, assess_completeness, validate_envelope
from ausl_college_scale import (
    build_batch_manifests,
    build_developer_review_batch,
    build_roster_coverage,
    promote_batch_bundle,
    render_batch_review_packet,
    serialize_batch_manifest,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _roster():
    return pd.DataFrame(
        [
            (2026, "10", "Alpha Player", "CHI", "Active", "IF", "Alpha University"),
            (2026, "11", "Beta Pitcher", None, "Reserve Pool", "RHP", "Beta State"),
        ],
        columns=(
            "season",
            "player_id",
            "player_name",
            "team_code",
            "roster_status",
            "position",
            "college",
        ),
    )


def _bundle():
    roster = _roster()
    coverage = build_roster_coverage(
        roster,
        season=2026,
        generated_at=NOW,
        batch_size=10,
    )
    batch = build_batch_manifests(coverage)[0]
    envelope = build_developer_review_batch(
        batch,
        roster,
        generated_at=NOW,
        roster_snapshot_hash="a" * 64,
        source_url="https://theausl.com",
    )
    return roster, batch, envelope


def test_batch_import_uses_exact_ids_and_phase7b_envelope():
    _, batch, envelope = _bundle()

    assert {resume.player_id for resume in envelope.resumes} == set(batch.player_ids)
    assert validate_envelope(envelope).valid
    for resume in envelope.resumes:
        assessment = assess_completeness(resume, envelope)
        assert assessment.state is CompletenessState.NEEDS_REVIEW
        assert "identity_review_pending" in assessment.blocking_reasons
        assert resume.identity_mappings[0].ausl_player_id == resume.player_id
        assert resume.identity_mappings[0].reviewer is None
        assert resume.identity_mappings[0].reviewed_at is None


def test_batch_import_preserves_school_only_as_reviewed_source_value():
    _, _, envelope = _bundle()
    alpha = next(item for item in envelope.resumes if item.player_id == "10")

    assert [program.display_name for program in alpha.programs] == ["Alpha University"]
    assert alpha.stints[0].start_season is None
    assert alpha.stints[0].end_season is None
    assert "does not provide attendance seasons" in alpha.stints[0].uncertainty_note
    assert alpha.stat_records == ()
    assert alpha.achievements == ()


def test_batch_import_does_not_infer_role_or_producer_approval():
    _, _, envelope = _bundle()
    payload = envelope.validation_metadata

    assert ("mode", "developer_review") in payload
    assert all(source.reviewer is None for source in envelope.sources)
    assert all(source.approved_at is None for source in envelope.sources)
    assert all(not resume.stat_records for resume in envelope.resumes)


def test_unknown_player_or_name_disagreement_fails_instead_of_name_matching():
    roster, batch, _ = _bundle()
    wrong = roster.copy()
    wrong.loc[wrong["player_id"].astype(str).eq("10"), "player_name"] = "Different Person"

    with pytest.raises(ValueError, match="canonical name disagreement"):
        build_developer_review_batch(
            batch,
            wrong,
            generated_at=NOW,
            roster_snapshot_hash="a" * 64,
            source_url="https://theausl.com",
        )

    unknown = roster.loc[roster["player_id"].astype(str).ne("11")]
    with pytest.raises(ValueError, match="does not resolve to exactly one"):
        build_developer_review_batch(
            batch,
            unknown,
            generated_at=NOW,
            roster_snapshot_hash="a" * 64,
            source_url="https://theausl.com",
        )


def test_review_packet_is_deterministic_and_never_calls_candidates_air_ready():
    _, batch, envelope = _bundle()
    first = render_batch_review_packet(batch, envelope)
    second = render_batch_review_packet(batch, envelope)

    assert first == second
    assert "BATCH REVIEW PENDING" in first
    assert "Alpha Player — AUSL ID 10" in first
    assert "Beta Pitcher — AUSL ID 11" in first
    assert "air-ready" not in first.casefold()
    assert "https://theausl.com" in first


def test_batch_promotion_is_idempotent_and_failure_retains_last_known_good(tmp_path):
    _, batch, envelope = _bundle()
    manifest_bytes = serialize_batch_manifest(batch)
    envelope_bytes = __import__("ausl_college").serialize_envelope(envelope)
    report_bytes = render_batch_review_packet(batch, envelope).encode("utf-8")
    destination = tmp_path / batch.batch_id

    first = promote_batch_bundle(
        destination,
        manifest_bytes=manifest_bytes,
        envelope_bytes=envelope_bytes,
        report_bytes=report_bytes,
    )
    before = {path.name: path.read_bytes() for path in destination.iterdir()}
    second = promote_batch_bundle(
        destination,
        manifest_bytes=manifest_bytes,
        envelope_bytes=envelope_bytes,
        report_bytes=report_bytes,
    )

    assert first == second
    assert before == {path.name: path.read_bytes() for path in destination.iterdir()}
    def fail_replace(source, target):
        raise OSError("forced promotion failure")

    with pytest.raises(OSError, match="forced promotion failure"):
        promote_batch_bundle(
            destination,
            manifest_bytes=manifest_bytes.replace(b"batch-01", b"batch-99"),
            envelope_bytes=envelope_bytes,
            report_bytes=report_bytes,
            replace_func=fail_replace,
        )
    assert before == {path.name: path.read_bytes() for path in destination.iterdir()}
