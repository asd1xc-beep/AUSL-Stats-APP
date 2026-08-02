from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_college_foundation_is_not_loaded_by_app_or_refresh():
    for relative in ("src/ausl_stats_app.py", "src/ausl_data.py", "src/ausl_enrichment.py"):
        assert "ausl_college" not in (ROOT / relative).read_text(encoding="utf-8")


def test_college_artifacts_are_absent_from_producer_distribution_contracts():
    for relative in (
        "tools/build_distribution_profile.py",
        "tools/create_portable_zip.py",
        "tools/verify_distribution.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8").casefold()
        assert "college" not in text
    assert not list((ROOT / "data").rglob("*college*"))


def test_no_college_ui_or_facts_exist_in_phase7b():
    app = (ROOT / "src/ausl_stats_app.py").read_text(encoding="utf-8")
    facts = (ROOT / "src/ausl_facts.py").read_text(encoding="utf-8")
    assert "College Résumé" not in app
    assert "ausl_college" not in facts
