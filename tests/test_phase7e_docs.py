from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide"
PENDING = "FULL-ROSTER COLLEGE IMPORT COMPLETE — BATCH REVIEW PENDING"


def test_phase7d_scaling_gate_is_closed_before_phase7e():
    acceptance = (GUIDE / "Phase_7D_Acceptance_Record.md").read_text(encoding="utf-8")
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED" in acceptance
    assert "2026-08-12" in acceptance
    assert "100%" in acceptance and "125%" in acceptance and "150%" in acceptance
    assert "FULLY ACCEPTED — PHASE 7D" in tracker


def test_coverage_report_states_exact_scope_and_pending_approval():
    text = (GUIDE / "Phase_7E_Roster_Coverage_Report.md").read_text(encoding="utf-8")
    for required in (
        PENDING,
        "Exact roster IDs accounted for: 118",
        "Approved résumés available: 9",
        "Reviewed Partial résumés: 1",
        "Developer review pending: 108",
        "Review batches: 11",
        "Producer approval for new batches: absent",
    ):
        assert required in text


def test_review_packet_identifies_files_checklist_and_human_gate():
    text = (GUIDE / "Phase_7E_Review_Packet.md").read_text(encoding="utf-8")
    assert PENDING in text
    assert "data/college_review/phase7e/batches" in text
    assert "batch_manifest.json" in text
    assert "developer_review_envelope.json" in text
    assert "review_packet.md" in text
    assert "exact AUSL ID" in text
    assert "do not approve" in text.casefold()
    assert "Phase 7E-B" in text and "must not begin" in text
    assert "personal AUSL producer review" in text


def test_interim_acceptance_record_is_honest_about_phase_boundary():
    text = (GUIDE / "Phase_7E_Acceptance_Record.md").read_text(encoding="utf-8")
    assert "930217d55cb562a6c18cfa9642c7f0c6858d1d97" in text
    assert "985 passed" in text
    assert "1013 passed" in text
    assert "57cf838cb618317a4902462aaf1effa6c216fa7143499d04cbd4042168494c72" in text
    assert PENDING in text
    assert "Connection engine: not started" in text
    assert "Phase 7 complete" not in text
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "[ ] `COLLEGE-007`" in tracker
    assert "[ ] `COLLEGE-008`" in tracker


def test_living_docs_show_the_current_batch_review_gate():
    for path in (
        ROOT / "README.txt",
        GUIDE / "AUSL_Broadcast_Stats_Implementation_Guide.md",
        GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert PENDING in text
        assert "118" in text
        assert "108" in text
        assert "11" in text
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "7E-A" in tracker
    assert "[ ] `COLLEGE-007`" in tracker
