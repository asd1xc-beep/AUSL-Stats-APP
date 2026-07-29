from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "Implementation guide" / "AUSL_Broadcast_Stats_Implementation_Guide.md"
TRACKER = ROOT / "Implementation guide" / "AUSL_Broadcast_Stats_Improvement_Tracker.md"


def test_tracker_records_phase6f_completion_without_closing_scaling():
    text = TRACKER.read_text(encoding="utf-8")

    assert "- [x] `SEARCH-004`" in text
    assert "- [x] `SEARCH-005`" in text
    assert "- [x] `UI-003`" in text
    assert "- [x] `UX-011`" in text
    assert "- [ ] `UI-002`" in text
    assert "Phase 6F completed on 2026-07-29" in text
    assert "full Phase 6 acceptance review" in text
    assert "Phase 7A" in text and "Phase 7E" in text


def test_guide_next_work_order_no_longer_instructs_phase6f_implementation():
    text = GUIDE.read_text(encoding="utf-8")
    phase6f = text.index("#### 6F. Faster search and player comparison")
    phase7 = text.index("### Phase 7", phase6f)
    phase6f_section = text[phase6f:phase7]
    next_work = text[text.index("## 13. Current next work order") :]

    assert "Implementation status (2026-07-29): complete" in phase6f_section
    assert "Complete Phase 6F" not in next_work
    assert "stabilization pass" in next_work
    assert "scaling sign-off" in next_work
    assert "full Phase 6 acceptance" in next_work
    assert "then begin phase 7a" in next_work.casefold()
