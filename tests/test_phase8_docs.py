"""Documentation guards for the Phase 8 responsiveness and data-path pass."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide"
TRACKER = GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md"
RECORD = GUIDE / "Phase_8_Perf_Acceptance_Record.md"


def test_tracker_carries_section_p_with_the_review_evidence():
    tracker = TRACKER.read_text(encoding="utf-8")

    assert "### P. UI responsiveness and data-path separation" in tracker
    assert "1,063 passed in 84.12 s" in tracker
    assert "886" in tracker and "971" in tracker
    assert "Rejected during this review" in tracker
    assert "wraplength" in tracker


def test_tracker_marks_only_the_delivered_perf_items_complete():
    tracker = TRACKER.read_text(encoding="utf-8")

    assert "[x] `PERF-001`" in tracker
    assert "[x] `PERF-003`" in tracker
    assert "[x] `PERF-004`" in tracker
    # PERF-002 touches pinned, used, and copy state and was excluded from
    # this pass; PERF-005 was not started.
    assert "[ ] `PERF-002`" in tracker
    assert "[ ] `PERF-005`" in tracker


def test_tracker_current_milestone_is_no_longer_phase_7():
    tracker = TRACKER.read_text(encoding="utf-8")
    milestone = tracker.split("## Approved next roadmap")[0]

    assert "### Milestone 8 — UI responsiveness and data-path separation" in milestone
    assert "PHASE 8 IN PROGRESS" in milestone
    assert "Phase_8_Perf_Acceptance_Record.md" in milestone


def test_tracker_records_the_shipped_debounce_interval():
    """The 120 ms the section proposed is not what shipped."""

    tracker = TRACKER.read_text(encoding="utf-8")

    assert "250 ms" in tracker
    assert "159.8 ms/step" in tracker
    assert "44.7%" in tracker


def test_acceptance_record_states_the_start_point_and_per_unit_commits():
    record = RECORD.read_text(encoding="utf-8")

    assert "d55ee43" in record
    assert "agent/phase8-perf-responsiveness" in record
    assert "3.12.10" in record and "3.14.6" in record
    for commit in ("231c924", "ce06f85", "1d79cbc", "d76da5a"):
        assert commit in record, f"missing per-unit commit {commit}"


def test_acceptance_record_states_the_test_counts_and_final_result():
    record = RECORD.read_text(encoding="utf-8")

    assert "1063 passed" in record
    assert "1071 passed" in record
    assert "1086 passed" in record
    assert "1093 passed, 1 skipped" in record


def test_acceptance_record_is_honest_about_the_measurement_spread():
    record = RECORD.read_text(encoding="utf-8")

    assert "218–330 ms/step" in record
    assert "did not reproduce" in record
    assert "288.8" in record and "159.8" in record and "156.2" in record
    assert "run-to-run spread" in record.casefold()


def test_acceptance_record_carries_the_unchanged_lfs_hashes():
    record = RECORD.read_text(encoding="utf-8")

    for digest in (
        "fa7e390b645bccea2497eca95eebb914e9cff6e5da214e1604f9b3235eb07840",
        "f4aa966c94802944ceba3bfbeeddc54e135b1d13518867945e7e7419f54d8caa",
        "c2cfb23f4247baf3baefd40f2dd9cfe34a5ca7c532da9f77238a0bc4a2dc3773",
        "45e60f70ee341a4fe805ad463a1ff6db52fa456004aeec4097788e6b2b5189eb",
    ):
        assert digest in record, f"missing tracked LFS hash {digest[:12]}"
    assert "git diff --stat -- data/exports" in record


def test_acceptance_record_states_the_remaining_limitations():
    record = RECORD.read_text(encoding="utf-8")
    limitations = record.split("## Remaining limitations")[-1]

    assert "`PERF-002` is untouched" in limitations
    assert "`PERF-005` is untouched" in limitations
    assert "truck" in limitations
    assert "has not been promoted" in limitations
    assert "No producer or truck-hardware verification" in limitations


def test_acceptance_record_documents_the_college_decision():
    """PERF-003 had to decide explicitly where college artifacts live."""

    record = RECORD.read_text(encoding="utf-8")

    assert "College artifacts stay canonical-only" in record
    assert "ausl_college_store" in record
    assert "Approval semantics are unchanged" in record
