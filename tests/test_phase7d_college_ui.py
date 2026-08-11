from __future__ import annotations

from pathlib import Path

import ausl_stats_app


ROOT = Path(__file__).resolve().parents[1]


class _Notebook:
    def __init__(self):
        self.selected = None

    def tabs(self):
        return tuple(range(9))

    def tab(self, tab_id, option):
        assert option == "text"
        return (
            "Game Day", "Player Lookup", "College RÃ©sumÃ©", "Team Totals",
            "Producer Prep", "Lineup Lock", "Manual Notes", "Live Game", "Compare Players",
        )[tab_id]

    def select(self, tab_id=None):
        if tab_id is not None:
            self.selected = tab_id
        return self.selected


def test_phase7d_source_builds_exactly_nine_tabs_and_lookup_handoff():
    source = (ROOT / "src" / "ausl_stats_app.py").read_text(encoding="utf-8")
    assert source.count('self.main_tabs.add(') == 9
    assert 'text="College RÃ©sumÃ©"' in source
    assert "View College RÃ©sumÃ©" in source

    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.main_tabs = _Notebook()
    app.selected_player_id = 950
    app._schedule_session_autosave = lambda *_a, **_k: True
    app.render_college_resume = lambda: True
    assert app.view_selected_college_resume()
    assert app.main_tabs.selected == 2
    assert app.selected_player_id == 950


def test_no_selected_player_handoff_fails_safely():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.main_tabs = _Notebook()
    app.selected_player_id = None
    app.college_status_var = type("Var", (), {"set": lambda self, value: setattr(self, "value", value)})()
    assert not app.view_selected_college_resume()
    assert "exact player" in app.college_status_var.value


def test_college_scroll_contract_is_mouse_and_keyboard_accessible():
    assert ausl_stats_app.AUSLStatsApp.COLLEGE_PANEL_SCROLLABLE is True
    source = (ROOT / "src" / "ausl_stats_app.py").read_text(encoding="utf-8")
    assert "_on_college_mousewheel" in source
    assert '"<MouseWheel>"' in source
    assert '"<Prior>"' in source and '"<Next>"' in source

