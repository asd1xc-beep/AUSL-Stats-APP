from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "Implementation guide"


def test_college_spec_records_required_trust_contract():
    text = (DOCS / "College_Data_Specification_v1.md").read_text(encoding="utf-8")
    for expected in (
        "CORE_RESUME_V1",
        "stable AUSL `player_id`",
        "field-level provenance",
        "canonical outs",
        "source-reported",
        "derived career",
        "Missing is never zero",
        "Verified",
        "Partial",
        "Needs Review",
        "Phase 7C importer contract",
        "College totals and AUSL totals",
    ):
        assert expected in text


def test_phase7b_acceptance_and_status_are_bounded():
    acceptance = (DOCS / "Phase_7B_Acceptance_Record.md").read_text(encoding="utf-8")
    tracker = (DOCS / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    guide = (DOCS / "AUSL_Broadcast_Stats_Implementation_Guide.md").read_text(encoding="utf-8")
    for item in ("COLLEGE-001", "COLLEGE-004", "COLLEGE-005"):
        assert f"- [x] `{item}`" in tracker
    for item in ("COLLEGE-003", "COLLEGE-006"):
        assert f"- [ ] `{item}`" in tracker
    statement = "PHASE 7B COMPLETE — PHASE 7C TEN-PLAYER PILOT NOT STARTED"
    assert statement in acceptance
    assert statement in tracker
    assert "Phase 7C" in guide and "ten-player pilot" in guide
    assert "production college data" in acceptance
    assert "College Résumé UI" in acceptance

