from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase7d_app_loads_only_approved_college_boundary_not_importer():
    app = (ROOT / "src/ausl_stats_app.py").read_text(encoding="utf-8")
    assert "ausl_college_store" in app
    assert "ausl_college_view" in app
    assert "ausl_college_import" not in app
    assert "college_pilot" not in app
    for relative in ("src/ausl_data.py", "src/ausl_enrichment.py"):
        assert "ausl_college" not in (ROOT / relative).read_text(encoding="utf-8")


def test_only_approved_college_artifacts_enter_explicit_distribution_contract():
    builder = (ROOT / "tools/build_distribution_profile.py").read_text(encoding="utf-8").casefold()
    verifier = (ROOT / "tools/verify_distribution.py").read_text(encoding="utf-8").casefold()
    portable = (ROOT / "tools/create_portable_zip.py").read_text(encoding="utf-8").casefold()
    assert "college_approved_envelope_name" in builder
    assert "validate_approved_payload" in builder
    assert "college_approved_envelope_name" in verifier
    assert "review_staging.json" in verifier
    assert "college" not in portable
    pilot_root = ROOT / "data" / "college_pilot"
    assert all(
        ROOT / "data" / "exports" not in path.parents
        for path in pilot_root.rglob("*")
    )


def test_phase7d_college_ui_remains_separate_from_professional_facts():
    app = (ROOT / "src/ausl_stats_app.py").read_text(encoding="utf-8")
    facts = (ROOT / "src/ausl_facts.py").read_text(encoding="utf-8")
    assert "College Résumé" in app
    assert "ausl_college" not in facts
