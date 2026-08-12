from __future__ import annotations

import hashlib
from pathlib import Path

from ausl_college import load_envelope, validate_envelope
from ausl_college_scale import (
    CoverageState,
    load_coverage_manifest,
)
from tools.build_phase7e_roster_review import build_review_bundle


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "college_review" / "phase7e"
EXPECTED_WORKBOOK_HASHES = {
    "ausl_rosters.xlsx": "fa7e390b645bccea2497eca95eebb914e9cff6e5da214e1604f9b3235eb07840",
    "ausl_season_stats.xlsx": "f4aa966c94802944ceba3bfbeeddc54e135b1d13518867945e7e7419f54d8caa",
    "ausl_career_stats.xlsx": "c2cfb23f4247baf3baefd40f2dd9cfe34a5ca7c532da9f77238a0bc4a2dc3773",
    "ausl_team_context.xlsx": "45e60f70ee341a4fe805ad463a1ff6db52fa456004aeec4097788e6b2b5189eb",
}


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_checked_in_roster_review_bundle_accounts_for_all_players_safely():
    manifest = load_coverage_manifest(
        (REVIEW / "roster_coverage_manifest.json").read_bytes()
    )

    assert manifest.season == 2026
    assert len(manifest.entries) == 118
    assert len({entry.player_id for entry in manifest.entries}) == 118
    assert sum(
        entry.coverage_state is CoverageState.APPROVED_RESUME_AVAILABLE
        for entry in manifest.entries
    ) == 9
    assert sum(
        entry.coverage_state is CoverageState.REVIEWED_PARTIAL_RESUME
        for entry in manifest.entries
    ) == 1
    assert sum(
        entry.coverage_state is CoverageState.DEVELOPER_REVIEW_PENDING
        for entry in manifest.entries
    ) == 108


def test_every_pending_id_occurs_in_exactly_one_review_batch():
    manifest = load_coverage_manifest(
        (REVIEW / "roster_coverage_manifest.json").read_bytes()
    )
    pending = {
        entry.player_id
        for entry in manifest.entries
        if entry.coverage_state is CoverageState.DEVELOPER_REVIEW_PENDING
    }
    seen = []
    batch_dirs = sorted((REVIEW / "batches").iterdir())
    assert len(batch_dirs) == 11
    for batch_dir in batch_dirs:
        envelope = load_envelope(
            (batch_dir / "developer_review_envelope.json").read_bytes()
        )
        report = validate_envelope(envelope)
        assert not tuple(
            error
            for error in report.errors
            if not error.startswith("unresolved identity:")
        )
        assert ("mode", "developer_review") in envelope.validation_metadata
        assert ("producer_approval", "absent") in envelope.validation_metadata
        assert all(source.reviewer is None for source in envelope.sources)
        assert all(source.approved_at is None for source in envelope.sources)
        seen.extend(resume.player_id for resume in envelope.resumes)
    assert len(seen) == len(set(seen)) == 108
    assert set(seen) == pending


def test_two_independent_real_roster_review_builds_are_byte_identical(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    arguments = {
        "roster_path": ROOT / "data" / "exports" / "ausl_rosters.xlsx",
        "approved_dir": ROOT / "data" / "college_approved",
        "update_manifest_path": ROOT / "data" / "exports" / "update_manifest.json",
    }
    assert build_review_bundle(output_dir=first, **arguments) == (118, 11)
    assert build_review_bundle(output_dir=second, **arguments) == (118, 11)

    assert _tree_hashes(first) == _tree_hashes(second) == _tree_hashes(REVIEW)


def test_phase7e_roster_work_did_not_change_professional_workbooks():
    for name, expected in EXPECTED_WORKBOOK_HASHES.items():
        payload = (ROOT / "data" / "exports" / name).read_bytes()
        assert payload.startswith(b"PK\x03\x04")
        assert hashlib.sha256(payload).hexdigest() == expected

