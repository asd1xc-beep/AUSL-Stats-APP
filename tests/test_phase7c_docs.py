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
    assert "932 passed in 19.26 s" in acceptance
    assert "d8c111e7762bf96e81ccd6844230123e31cfbab780f92d40d5aa695ccfdb3442" in acceptance
    assert "c4c315ceebc976d791060bcf8ce1b8760176fd768cb1be410b694bd25f056891" in acceptance


def test_tracker_records_owner_acceptance_without_starting_phase7e():
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "[x] `COLLEGE-003`" in tracker
    assert "[x] `COLLEGE-006`" in tracker
    assert "PROJECT-OWNER REVIEWED 2026-08-11" in tracker
    assert "[x] `COLLEGE-002`" in tracker
    assert "[ ] `COLLEGE-007`" in tracker
    assert "[ ] `COLLEGE-008`" in tracker


def test_implementation_guide_points_to_phase7c_review_and_acceptance_records():
    guide = (GUIDE / "AUSL_Broadcast_Stats_Implementation_Guide.md").read_text(encoding="utf-8")
    assert "Phase_7C_Pilot_Cohort.md" in guide
    assert "Phase_7C_Review_Packet.md" in guide
    assert "Phase_7C_Acceptance_Record.md" in guide
    assert "Phase 7D implementation is complete" in guide
    assert "Phase 7E has not started" in guide
