from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide"
PENDING = "PHASE 7E DATA ACCEPTED — FINAL WINDOWS SIGN-OFF PENDING"


def test_phase7d_scaling_gate_is_closed_before_phase7e():
    acceptance = (GUIDE / "Phase_7D_Acceptance_Record.md").read_text(encoding="utf-8")
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED" in acceptance
    assert "2026-08-12" in acceptance
    assert "100%" in acceptance and "125%" in acceptance and "150%" in acceptance
    assert "FULLY ACCEPTED — PHASE 7D" in tracker


def test_coverage_report_preserves_original_preapproval_checkpoint():
    text = (GUIDE / "Phase_7E_Roster_Coverage_Report.md").read_text(encoding="utf-8")
    for required in (
        "FULL-ROSTER COLLEGE IMPORT COMPLETE — BATCH REVIEW PENDING",
        "Exact roster IDs accounted for: 118",
        "Approved résumés available: 9",
        "Reviewed Partial résumés: 1",
        "Developer review pending: 108",
        "Review batches: 11",
        "Producer approval for new batches: absent",
    ):
        assert required in text


def test_review_packet_records_all_batch_and_connection_approvals():
    text = (GUIDE / "Phase_7E_Review_Packet.md").read_text(encoding="utf-8")
    assert PENDING in text
    assert "data/college_review/phase7e/batches" in text
    assert "batch_manifest.json" in text
    assert "developer_review_envelope.json" in text
    assert "review_packet.md" in text
    assert "exact AUSL ID" in text
    assert "Batch 01" in text and "Batch 11" in text
    assert "11 approved" in text
    assert "No mistakes" in text
    assert "connection_review_packet.md" in text
    assert "all eight exact connection wordings" in text
    assert "approved-enrichment" in text
    assert "personal AUSL producer review" in text


def test_interim_acceptance_record_is_honest_about_phase_boundary():
    text = (GUIDE / "Phase_7E_Acceptance_Record.md").read_text(encoding="utf-8")
    assert "930217d55cb562a6c18cfa9642c7f0c6858d1d97" in text
    assert "985 passed" in text
    assert "1013 passed" in text
    assert "57cf838cb618317a4902462aaf1effa6c216fa7143499d04cbd4042168494c72" in text
    assert PENDING in text
    assert "Connection engine: complete" in text
    assert "Connection wording review and approval: complete" in text
    assert "eight review candidates" in text
    assert "Phase 7 complete" not in text
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "[x] `COLLEGE-007`" in tracker
    assert "[ ] `COLLEGE-008`" in tracker


def test_living_docs_show_the_current_connection_review_gate():
    for path in (
        ROOT / "README.txt",
        GUIDE / "AUSL_Broadcast_Stats_Implementation_Guide.md",
        GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert PENDING in text
        assert "118" in text
        assert "109" in text
        assert "11" in text
    tracker = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "7E-A" in tracker
    assert "[x] `COLLEGE-007`" in tracker


def test_connection_specification_documents_fail_closed_relationship_rules():
    text = (GUIDE / "Phase_7E_Connection_Specification.md").read_text(
        encoding="utf-8"
    )
    for required in (
        PENDING,
        "Stable connection identity",
        "Evidence version hash",
        "Overlapping attendance does not prove a teammate relationship",
        "Missing attendance seasons suppress",
        "project-owner approval",
        "COLLEGE-007 is technically complete",
    ):
        assert required in text


def test_full_phase7_record_stops_at_final_windows_gate():
    text = (GUIDE / "Phase_7_Full_Acceptance_Record.md").read_text(
        encoding="utf-8"
    )
    assert PENDING in text
    assert "118" in text and "109 Partial" in text
    assert "all eight exact" in text
    assert "100%" in text and "125%" in text and "150%" in text
    assert "COLLEGE-008` remains deferred" in text
