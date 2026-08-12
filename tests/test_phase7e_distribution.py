from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.build_distribution_profile import stage_distribution_profile
from tools.verify_distribution import scan_distribution


ROOT = Path(__file__).resolve().parents[1]
CORE_NAMES = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
    "update_manifest.json",
    "refresh_attempt.json",
)


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

