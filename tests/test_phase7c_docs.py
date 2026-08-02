from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide"
STATUS = "PHASE 7C TECHNICAL PILOT COMPLETE — PRODUCER REVIEW PENDING — PHASE 7D NOT STARTED"


def test_phase7c_required_documents_exist_and_preserve_phase_boundary():
    cohort = (GUIDE / "Phase_7C_Pilot_Cohort.md").read_text(encoding="utf-8")
    review = (GUIDE / "Phase_7C_Review_Packet.md").read_text(encoding="utf-8")
    acceptance = (GUIDE / "Phase_7C_Acceptance_Record.md").read_text(encoding="utf-8")
    assert "exactly ten" in cohort.casefold()
    assert "AUSL ID" in cohort
    assert "developer review" in cohort.casefold()
    assert "air-ready" not in review.casefold()
    assert "PRODUCER REVIEW PENDING" in review
    assert STATUS in acceptance
    assert "Schema version: `1`" in acceptance


def test_tracker_marks_only_the_technical_core_complete_and_review_pending():
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "[x] `COLLEGE-003`" in tracker
    assert "[ ] `COLLEGE-006`" in tracker
    assert "PRODUCER REVIEW PENDING" in tracker
    assert "[ ] `COLLEGE-002`" in tracker
    assert "[ ] `COLLEGE-007`" in tracker
    assert "[ ] `COLLEGE-008`" in tracker


def test_implementation_guide_points_to_phase7c_review_and_acceptance_records():
    guide = (GUIDE / "AUSL_Broadcast_Stats_Implementation_Guide.md").read_text(encoding="utf-8")
    assert "Phase_7C_Pilot_Cohort.md" in guide
    assert "Phase_7C_Review_Packet.md" in guide
    assert "Phase_7C_Acceptance_Record.md" in guide
    assert "Phase 7D remains not started" in guide
