from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide"
STATUS = (
    "PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED"
)


def test_phase7d_acceptance_record_is_specific_and_honest():
    text = (GUIDE / "Phase_7D_Acceptance_Record.md").read_text(encoding="utf-8")
    for required in (
        "5996ef1f1a959f0c3c28f93d1fb1360f4c40111b",
        "project_owner",
        "2026-08-11",
        "36da267aed5bf12e40e5e923100ecbaf4811a896a523a6f476f80d4612b78b4a",
        "9",
        "Partial",
        "1120×720",
        "2026-08-12",
        "100%",
        "125%",
        "150%",
        STATUS,
    ):
        assert required in text
    assert "personal AUSL producer review" in text
    assert "project-owner reported" in text


def test_tracker_preserves_phase7d_acceptance_after_phase7e_progress():
    text = (GUIDE / "AUSL_Broadcast_Stats_Improvement_Tracker.md").read_text(encoding="utf-8")
    assert "[x] `COLLEGE-002`" in text
    assert "[x] `COLLEGE-006`" in text
    assert "[x] `COLLEGE-007`" in text
    assert "[ ] `COLLEGE-008`" in text
    assert STATUS in text
    assert "FULLY ACCEPTED — PHASE 7D" in text


def test_readme_and_guide_record_scaling_and_authorize_phase7e():
    for path in (
        ROOT / "README.txt",
        GUIDE / "AUSL_Broadcast_Stats_Implementation_Guide.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "2026-08-12" in text
        assert "project owner" in text.casefold()
        assert "Phase 7E" in text
        assert "100%" in text and "125%" in text and "150%" in text
        assert STATUS in text
