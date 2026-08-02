from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data" / "college_pilot"
PRODUCER_CODE = (
    "src/ausl_stats_app.py",
    "src/ausl_data.py",
    "src/ausl_enrichment.py",
)


def test_college_pilot_is_outside_core_and_approved_enrichment_exports():
    assert PILOT.is_dir()
    assert {path.name for path in PILOT.iterdir()} == {
        "pilot_envelope.json",
        "pilot_manifest.json",
        "review_staging.json",
    }
    assert not list((ROOT / "data" / "exports").glob("*college*"))
    for relative in (
        "tools/build_distribution_profile.py",
        "tools/create_portable_zip.py",
        "tools/verify_distribution.py",
    ):
        assert "college_pilot" not in (ROOT / relative).read_text(encoding="utf-8")


def test_startup_offline_mode_and_full_refresh_do_not_load_or_rewrite_pilot():
    for relative in PRODUCER_CODE:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "ausl_college_import" not in text
        assert "college_pilot" not in text


def test_importer_is_not_reachable_from_existing_fact_or_ui_workflows():
    for relative in ("src/ausl_stats_app.py", "src/ausl_facts.py", "src/ausl_data.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "import_college_pilot" not in text
        assert "Phase 7C" not in text


def test_pilot_files_do_not_duplicate_professional_workbooks():
    workbook_hashes = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT / "data" / "exports").glob("*.xlsx")
    }
    assert workbook_hashes
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() not in workbook_hashes
        for path in PILOT.iterdir()
    )
