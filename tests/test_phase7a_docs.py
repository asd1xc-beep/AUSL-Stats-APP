from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "Implementation guide"
GUIDE = DOCS / "AUSL_Broadcast_Stats_Implementation_Guide.md"
TRACKER = DOCS / "AUSL_Broadcast_Stats_Improvement_Tracker.md"
PHASE6 = DOCS / "Phase_6_Full_Acceptance_Record.md"
PHASE7A = DOCS / "Phase_7A_Acceptance_Record.md"


def test_phase6_full_acceptance_records_only_owner_reported_details():
    text = PHASE6.read_text(encoding="utf-8")

    assert "08fd7f09f24a53f3270516c51e6667e9daa35538" in text
    assert "PR #11" in text
    assert "769 passed" in text
    assert "100%, 125%, and 150%" in text
    assert "Project-owner reported" in text
    assert "Truck-hardware smoke" in text
    assert "Producer rehearsal" in text
    assert "No hardware model" in text
    assert "PHASE 6 ACCEPTED" in text


def test_tracker_marks_only_phase7a_scope_complete_and_phase7b_unstarted():
    text = TRACKER.read_text(encoding="utf-8")

    for item in (
        "SPLIT-001",
        "SPLIT-002",
        "SPLIT-003",
        "ENRICH-001",
        "ENRICH-002",
        "ENRICH-003",
        "ENRICH-004",
    ):
        assert f"- [x] `{item}`" in text
    assert "PHASE 7A COMPLETE — PHASE 7B NOT STARTED" in text
    assert "Phase 7B" in text and "NOT STARTED" in text
    assert "- [ ] `COLLEGE-001`" in text


def test_phase7a_acceptance_record_captures_trust_and_verification():
    text = PHASE7A.read_text(encoding="utf-8")

    for expected in (
        "08fd7f09f24a53f3270516c51e6667e9daa35538",
        "agent/phase7a-producer-enrichment",
        "c23ab52",
        "8a34785",
        "85b0db9",
        "CORE_ONLY",
        "PRODUCER_APPROVED",
        "DEVELOPER_REVIEW",
        "12 plate appearances",
        "9 outs",
        "approved-enrichment",
        "847 passed",
        "Windows-10-10.0.19045-SP0",
        "network calls: 0",
        "Phase 7B has not started",
    ):
        assert expected in text


def test_readme_and_guide_explain_producer_refresh_and_distribution_profile():
    readme = (ROOT / "README.txt").read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")

    for text in (readme, guide):
        assert "Full Enrichment Refresh" in text
        assert "PRODUCER_APPROVED" in text
        assert "DEVELOPER_REVIEW" in text
        assert "approved-enrichment" in text
        assert "Phase 7B has not started" in text
