from __future__ import annotations

import json
import shutil
from pathlib import Path

from tools.build_distribution_profile import stage_distribution_profile
from tools.create_portable_zip import create_portable_zip
from tools.verify_distribution import scan_distribution


ROOT = Path(__file__).resolve().parents[1]
CORE_NAMES = (
    "ausl_rosters.xlsx", "ausl_season_stats.xlsx", "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx", "update_manifest.json", "refresh_attempt.json",
)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for name in CORE_NAMES:
        shutil.copyfile(ROOT / "data" / "exports" / name, source / name)
    for name in ("college_resume_envelope.json", "college_approval_manifest.json"):
        shutil.copyfile(ROOT / "data" / "college_approved" / name, source / name)
    return source


def test_core_excludes_college_and_approved_profile_includes_only_approved_outputs(tmp_path):
    source = _source(tmp_path)
    core = tmp_path / "core"
    approved = tmp_path / "approved"
    stage_distribution_profile(source, core, profile="core")
    stage_distribution_profile(source, approved, profile="approved-enrichment")
    assert not list(core.glob("*college*"))
    assert {path.name for path in approved.glob("*college*")} == {
        "college_resume_envelope.json", "college_approval_manifest.json"
    }
    assert scan_distribution(approved, profile="approved-enrichment") == []
    assert not any(path.name in {"pilot_envelope.json", "review_staging.json"} for path in approved.iterdir())


def test_modified_approved_college_payload_fails_verification(tmp_path):
    source = _source(tmp_path)
    approved = tmp_path / "approved"
    stage_distribution_profile(source, approved, profile="approved-enrichment")
    path = approved / "college_resume_envelope.json"
    path.write_bytes(path.read_bytes() + b" ")
    violations = scan_distribution(approved, profile="approved-enrichment")
    assert any("college" in item.reason and "hash" in item.reason for item in violations)


def test_independent_approved_distribution_zips_are_identical(tmp_path):
    source = _source(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    stage_distribution_profile(source, first, profile="approved-enrichment")
    stage_distribution_profile(source, second, profile="approved-enrichment")
    first_zip, second_zip = tmp_path / "first.zip", tmp_path / "second.zip"
    create_portable_zip(first, first_zip)
    create_portable_zip(second, second_zip)
    assert first_zip.read_bytes() == second_zip.read_bytes()


def test_distribution_manifest_records_college_transaction(tmp_path):
    source = _source(tmp_path)
    approved = tmp_path / "approved"
    stage_distribution_profile(source, approved, profile="approved-enrichment")
    manifest = json.loads((approved / "approved_enrichment_manifest.json").read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest["files"]}
    assert {"college_resume_envelope.json", "college_approval_manifest.json"} <= names
