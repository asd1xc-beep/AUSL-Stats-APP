from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide" / "AUSL_Broadcast_Stats_Implementation_Guide.md"
TRACKER = ROOT / "Implementation guide" / "AUSL_Broadcast_Stats_Improvement_Tracker.md"


def test_tracker_records_owner_reported_phase6_scaling_acceptance():
    text = TRACKER.read_text(encoding="utf-8")

    assert "- [x] `SEARCH-004`" in text
    assert "- [x] `SEARCH-005`" in text
    assert "- [x] `UI-003`" in text
    assert "- [x] `UX-011`" in text
    assert "- [x] `UI-001`" in text
    assert "- [x] `UI-002`" in text
    assert "Phase 6F completed on 2026-07-29" in text
    assert "project-owner reported" in text
    assert "100%, 125%, and 150%" in text
    assert "Phase 7A" in text and "Phase 7E" in text


def test_guide_next_work_order_stops_before_phase7e_scaling_gate():
    text = GUIDE.read_text(encoding="utf-8")
    phase6f = text.index("#### 6F. Faster search and player comparison")
    phase7 = text.index("### Phase 7", phase6f)
    phase6f_section = text[phase6f:phase7]
    next_work = text[text.index("## 13. Current next work order") :]

    assert "Implementation status (2026-07-29): complete" in phase6f_section
    assert "Complete Phase 6F" not in next_work
    assert "Phase 7D" in next_work
    assert "scaling" in next_work.casefold()
    assert "Phase 7E" in next_work
    assert "blocked" in next_work.casefold()
