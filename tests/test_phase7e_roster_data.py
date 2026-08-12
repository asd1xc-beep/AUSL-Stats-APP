from __future__ import annotations

import hashlib
import subprocess
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
STARTING_SHA = "930217d55cb562a6c18cfa9642c7f0c6858d1d97"


def _starting_bytes(relative: str) -> bytes:
    payload = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "show",
            f"{STARTING_SHA}:{relative}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    prefix = b"version https://git-lfs.github.com/spec/v1\n"
    if payload.startswith(prefix):
        oid_line = next(
            line for line in payload.decode("ascii").splitlines() if line.startswith("oid sha256:")
        )
        oid = oid_line.removeprefix("oid sha256:")
        git_dir_text = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={ROOT}",
                "rev-parse",
                "--git-common-dir",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_dir = Path(git_dir_text)
        if not git_dir.is_absolute():
            git_dir = ROOT / git_dir
        payload = (git_dir / "lfs" / "objects" / oid[:2] / oid[2:4] / oid).read_bytes()
    return payload


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "batch_review_decisions.json"
        and path.relative_to(root).parts[0] != "connections"
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
    source = tmp_path / "starting-source"
    source.mkdir()
    roster_path = source / "ausl_rosters.xlsx"
    update_manifest_path = source / "update_manifest.json"
    roster_path.write_bytes(_starting_bytes("data/exports/ausl_rosters.xlsx"))
    update_manifest_path.write_bytes(_starting_bytes("data/exports/update_manifest.json"))
    arguments = {
        "roster_path": roster_path,
        "approved_dir": ROOT / "data" / "college_approved",
        "update_manifest_path": update_manifest_path,
    }
    assert build_review_bundle(output_dir=first, **arguments) == (118, 11)
    assert build_review_bundle(output_dir=second, **arguments) == (118, 11)

    assert _tree_hashes(first) == _tree_hashes(second) == _tree_hashes(REVIEW)


def test_phase7e_roster_work_did_not_change_professional_workbooks():
    for name, expected in EXPECTED_WORKBOOK_HASHES.items():
        payload = _starting_bytes(f"data/exports/{name}")
        assert payload.startswith(b"PK\x03\x04")
        assert hashlib.sha256(payload).hexdigest() == expected
