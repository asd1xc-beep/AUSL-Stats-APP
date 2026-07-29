from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import ausl_stats_app
from test_phase6a_command_center import FakeVar, make_app, selected_game


class FakeResults:
    def __init__(self):
        self.rows = []
        self.selected = ()
        self.activated = None

    def delete(self, *_args):
        self.rows = []
        self.selected = ()

    def insert(self, _where, value):
        self.rows.append(value)

    def curselection(self):
        return self.selected

    def selection_clear(self, *_args):
        self.selected = ()

    def selection_set(self, index):
        self.selected = (int(index),)

    def activate(self, index):
        self.activated = int(index)

    def see(self, _index):
        return None


class FakeCanvas:
    def __init__(self):
        self.scrolls = []

    def yview_scroll(self, amount, unit):
        self.scrolls.append((amount, unit))


class FakeClipboardRoot:
    def __init__(self):
        self.text = ""

    def clipboard_clear(self):
        self.text = ""

    def clipboard_append(self, value):
        self.text = value


def _app(fixture_database):
    app = make_app()
    app.db = dict(fixture_database)
    app.selected_game = selected_game()
    app.scope_var = FakeVar(True)
    app.search_var = FakeVar("")
    app.search_scope_var = FakeVar("")
    app.search_feedback_var = FakeVar("")
    app.results = FakeResults()
    app.search_rows = []
    app._search_view = None
    app._search_team = None
    app._player_search_index = None
    app._player_search_response = None
    app._highlighted_player_id = None
    app.selected_player_id = None
    app.comparison_left_player_id = None
    app.comparison_right_player_id = None
    app._current_comparison = None
    app._last_comparison_copy_record = None
    app._comparison_restore_warning = ""
    app._render_comparison = lambda: None
    app._select_notebook_text = lambda *_args: True
    app._schedule_session_autosave = lambda *_args: None
    app.comparison_left_var = FakeVar("")
    app.comparison_right_var = FakeVar("")
    app.comparison_status_var = FakeVar("")
    return app


def test_lookup_highlight_is_distinct_from_explicit_selection(fixture_database):
    app = _app(fixture_database)
    rendered = []
    app.render_player = lambda row: rendered.append(row["player_id"])
    app.search_var.set("Ada Active")

    app.search()
    app.results.selection_set(0)
    app._on_result_highlight()

    assert app._highlighted_player_id == "101"
    assert app.selected_player_id is None
    assert rendered == []

    app._activate_highlighted_result()
    assert app.selected_player_id == 101
    assert rendered == [101]


def test_search_displays_filter_chips_scope_count_and_match_reason(fixture_database):
    app = _app(fixture_database)
    app.search_var.set("team:CHI pos:P #30")

    app.search()

    assert len(app.search_rows) == 1
    assert "Pia Pitcher" in app.results.rows[0]
    assert "Matches all selected filters" in app.results.rows[0]
    assert "TEAM: CHI" in app.search_feedback_var.get()
    assert "POS: P" in app.search_feedback_var.get()
    assert "NUMBER: 30" in app.search_feedback_var.get()
    assert "Explicit team filter: CHI" in app.search_feedback_var.get()


def test_typo_result_is_labeled_and_not_auto_selected(fixture_database):
    app = _app(fixture_database)
    app.search_var.set("Adda Active")

    app.search()

    assert app.selected_player_id is None
    assert "POSSIBLE TYPO" in app.results.rows[0]
    assert "explicit selection" in app.search_feedback_var.get()


def test_database_replacement_rebuilds_index_and_comparison(fixture_database):
    app = _app(fixture_database)
    first = app._rebuild_player_search_index().index_identity
    app.comparison_left_player_id = "101"
    app.comparison_right_player_id = "103"
    assert app._rebuild_comparison()
    before = app._current_comparison.database_identity

    app.db = dict(fixture_database)
    app.db["manifest"] = dict(
        fixture_database["manifest"], snapshot_id="replacement-snapshot"
    )
    second = app._rebuild_player_search_index().index_identity
    assert app._rebuild_comparison()

    assert first != second
    assert before != app._current_comparison.database_identity
    assert app._last_comparison_copy_record is None


def test_assign_swap_clear_and_copy_comparison(fixture_database):
    app = _app(fixture_database)
    app.root = FakeClipboardRoot()
    app._highlighted_player_id = "101"
    assert app.assign_comparison_player("left")
    app._highlighted_player_id = "103"
    assert app.assign_comparison_player("right")

    assert app._current_comparison.left.player_id == "101"
    assert app._current_comparison.right.player_id == "103"
    assert app.copy_comparison_with_sources()
    assert "Ada Active" in app.root.text
    assert "Rae Reserve" in app.root.text
    assert app._last_comparison_copy_record.left_player_id == "101"

    app.swap_comparison_players()
    assert app._current_comparison.left.player_id == "103"
    app.clear_comparison_side("right")
    assert app._current_comparison is None


def test_missing_restored_comparison_identity_stays_visible_without_guess(
    fixture_database,
):
    app = _app(fixture_database)
    app.comparison_left_player_id = "999"
    app.comparison_right_player_id = "103"

    assert not app._rebuild_comparison()
    assert app.comparison_left_player_id == "999"
    assert "No replacement player was guessed" in app._comparison_restore_warning


def test_comparison_mousewheel_supports_windows_and_x11_directions(
    fixture_database,
):
    app = _app(fixture_database)
    app.comparison_canvas = FakeCanvas()

    assert app._on_comparison_mousewheel(
        SimpleNamespace(delta=120, num=None)
    ) == "break"
    assert app._on_comparison_mousewheel(
        SimpleNamespace(delta=-240, num=None)
    ) == "break"
    assert app._on_comparison_mousewheel(
        SimpleNamespace(delta=0, num=4)
    ) == "break"
    assert app._on_comparison_mousewheel(
        SimpleNamespace(delta=0, num=5)
    ) == "break"
    assert app.comparison_canvas.scrolls == [
        (-1, "units"),
        (2, "units"),
        (-3, "units"),
        (3, "units"),
    ]


def test_multiline_text_shortcuts_are_not_hijacked(fixture_database):
    app = _app(fixture_database)
    widget = object.__new__(ausl_stats_app.tk.Text)
    event = SimpleNamespace(widget=widget)

    assert app._focus_player_search(event) is None
    assert app._comparison_left_shortcut(event) is None
    assert app._comparison_right_shortcut(event) is None


def test_arrow_navigation_highlights_without_rendering(fixture_database):
    app = _app(fixture_database)
    rendered = []
    app.render_player = lambda row: rendered.append(row["player_id"])
    app.search_var.set("")
    app._search_view = "all"
    app.search()

    assert app._move_search_highlight(SimpleNamespace(keysym="Down")) == "break"
    assert app.results.curselection() == (0,)
    assert app.selected_player_id is None
    assert rendered == []
