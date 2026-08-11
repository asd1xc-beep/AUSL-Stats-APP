from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFESSIONAL_WORKBOOKS = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
)


def test_professional_fact_packet_comparison_and_change_modules_do_not_import_college():
    for relative in (
        "src/ausl_facts.py",
        "src/ausl_rundown.py",
        "src/ausl_comparison.py",
        "src/ausl_changes.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "ausl_college" not in text
        assert "college_resume" not in text


def test_refresh_code_reloads_but_never_fetches_or_rewrites_college_sources():
    app = (ROOT / "src" / "ausl_stats_app.py").read_text(encoding="utf-8")
    data = (ROOT / "src" / "ausl_data.py").read_text(encoding="utf-8")
    assert "self._college_store.load" in app
    for forbidden in (
        "approve_pilot_files",
        "import_college_pilot",
        "fetch_college",
        "update_college",
    ):
        assert forbidden not in app
        assert forbidden not in data


def test_approved_college_artifacts_are_not_professional_workbooks():
    workbook_hashes = {
        hashlib.sha256((ROOT / "data" / "exports" / name).read_bytes()).hexdigest()
        for name in PROFESSIONAL_WORKBOOKS
    }
    college_hashes = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data" / "college_approved").iterdir()
    }
    assert workbook_hashes.isdisjoint(college_hashes)
