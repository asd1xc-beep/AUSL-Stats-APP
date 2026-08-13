from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path

import pytest

from tools.build_distribution_profile import stage_distribution_profile
from tools.create_portable_zip import create_portable_zip
from tools.verify_distribution import scan_distribution


ROOT = Path(__file__).resolve().parents[1]
STARTING_SHA = "930217d55cb562a6c18cfa9642c7f0c6858d1d97"
CORE_NAMES = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
    "update_manifest.json",
    "refresh_attempt.json",
)


def _starting_bytes(relative: str) -> bytes:
    payload = subprocess.run(
        ["git", "show", f"{STARTING_SHA}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if payload.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        oid = next(
            line.removeprefix("oid sha256:")
            for line in payload.decode("ascii").splitlines()
            if line.startswith("oid sha256:")
        )
        git_dir = Path(
            subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        if not git_dir.is_absolute():
            git_dir = ROOT / git_dir
        payload = (git_dir / "lfs" / "objects" / oid[:2] / oid[2:4] / oid).read_bytes()
    return payload


def _phase7e_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for name in CORE_NAMES:
        (source / name).write_bytes(_starting_bytes(f"data/exports/{name}"))
    for name in (
        "college_resume_envelope.json",
        "college_aggregate_approval_manifest.json",
    ):
        shutil.copyfile(ROOT / "data" / "college_approved_phase7e" / name, source / name)
    for name in (
        "college_connection_candidates.json",
        "college_connection_approval_manifest.json",
    ):
        shutil.copyfile(ROOT / "data" / "college_connections_approved" / name, source / name)
    return source


@pytest.mark.parametrize(
    "entry",
    (
        "data/college_review/phase7e/roster_coverage_manifest.json",
        "developer_review_envelope.json",
        "phase7e_batch_manifest.json",
        "phase7e_connection_review_packet.md",
    ),
)
def test_review_only_phase7e_artifacts_are_rejected_from_packages(tmp_path, entry):
    path = tmp_path / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("review only\n", encoding="utf-8")

    violations = scan_distribution(tmp_path, profile="approved-enrichment")

    assert len(violations) == 1
    assert "review" in violations[0].reason.casefold()


def test_core_and_current_approved_profile_ignore_phase7e_review_tree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in CORE_NAMES:
        shutil.copyfile(ROOT / "data" / "exports" / name, source / name)
    for name in ("college_resume_envelope.json", "college_approval_manifest.json"):
        shutil.copyfile(ROOT / "data" / "college_approved" / name, source / name)
    review = source / "data" / "college_review" / "phase7e"
    review.mkdir(parents=True)
    (review / "roster_coverage_manifest.json").write_text("{}\n", encoding="utf-8")

    core = tmp_path / "core"
    approved = tmp_path / "approved"
    stage_distribution_profile(source, core, profile="core")
    stage_distribution_profile(source, approved, profile="approved-enrichment")

    assert not list(core.rglob("*phase7e*"))
    assert not list(approved.rglob("*phase7e*"))
    assert scan_distribution(core, profile="core") == []
    assert scan_distribution(approved, profile="approved-enrichment") == []


def test_startup_refresh_and_fact_code_do_not_import_review_batch_builder():
    for relative in (
        "src/ausl_stats_app.py",
        "src/ausl_data.py",
        "src/ausl_facts.py",
        "src/ausl_college_store.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "ausl_college_scale" not in text
        assert "college_review" not in text


def test_approved_profile_packages_full_roster_and_exact_approved_connections(tmp_path):
    source = _phase7e_source(tmp_path)
    approved = tmp_path / "approved"

    stage_distribution_profile(source, approved, profile="approved-enrichment")

    college_names = {path.name for path in approved.glob("*college*")}
    assert college_names == {
        "college_aggregate_approval_manifest.json",
        "college_connection_approval_manifest.json",
        "college_connection_candidates.json",
        "college_resume_envelope.json",
    }
    manifest = json.loads(
        (approved / "approved_enrichment_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["college_player_count"] == 118
    assert manifest["college_connection_count"] == 8
    assert scan_distribution(approved, profile="approved-enrichment") == []


@pytest.mark.parametrize(
    "filename,replacement",
    (
        ("college_connection_candidates.json", (b"national championship", b"conference championship")),
        ("college_connection_approval_manifest.json", (b"project_owner", b"other_reviewer")),
        ("college_resume_envelope.json", (b"Tiare Jennings", b"Changed Player")),
    ),
)
def test_phase7e_college_tampering_fails_distribution_verification(
    tmp_path, filename, replacement
):
    approved = tmp_path / "approved"
    stage_distribution_profile(
        _phase7e_source(tmp_path), approved, profile="approved-enrichment"
    )
    path = approved / filename
    before, after = replacement
    assert before in path.read_bytes()
    path.write_bytes(path.read_bytes().replace(before, after, 1))

    violations = scan_distribution(approved, profile="approved-enrichment")

    assert any("college" in item.reason.casefold() for item in violations)


def test_phase7e_approved_profile_is_deterministic_and_core_stays_college_free(tmp_path):
    source = _phase7e_source(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    core = tmp_path / "core"
    stage_distribution_profile(source, first, profile="approved-enrichment")
    stage_distribution_profile(source, second, profile="approved-enrichment")
    stage_distribution_profile(source, core, profile="core")
    first_zip = tmp_path / "first.zip"
    second_zip = tmp_path / "second.zip"
    create_portable_zip(first, first_zip)
    create_portable_zip(second, second_zip)

    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert not list(core.glob("*college*"))
    assert scan_distribution(core, profile="core") == []
