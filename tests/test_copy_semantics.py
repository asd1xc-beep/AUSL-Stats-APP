from __future__ import annotations

import inspect

import pandas as pd

import ausl_stats_app


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeClipboardRoot:
    def __init__(self):
        self.clipboard = None
        self.clear_calls = 0

    def clipboard_clear(self):
        self.clear_calls += 1
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard = text

    def update(self):
        return None


def make_app(database, player_id=101):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = database
    app.selected_player_id = player_id
    app.current_broadcast_note = "Fixture narrative; verify before air."
    app.data_freshness_text = "Data updated: July 18, 2026 at 11:45 PM UTC - VERIFY"
    app.root = FakeClipboardRoot()
    app.copy_status = FakeVar()
    return app


def test_copy_types_have_distinct_explicit_semantics(fixture_database):
    app = make_app(fixture_database)

    player_id = app.gfx_text("player_id").upper()
    season = app.gfx_text("season_stat").upper()
    career = app.gfx_text("career_stat").upper()
    announcer = app.gfx_text("announcer_note").upper()

    assert "ADA ACTIVE" in player_id
    assert "CHICAGO BANDITS" in player_id
    assert "STATUS: ACTIVE" in player_id
    assert "#7" in player_id
    assert "2026 AUSL SEASON" in season
    assert "AUSL CAREER" not in season
    assert "AUSL CAREER 2025–26" in career
    assert "[VERIFY]" in announcer
    assert "FIXTURE NARRATIVE" in announcer
    assert "DATA UPDATED" in announcer


def test_unknown_copy_kind_is_unavailable_not_a_silent_player_id(fixture_database):
    app = make_app(fixture_database)

    assert app.gfx_text("typo-kind") == ""


def test_nonactive_copy_requires_confirmation_before_clipboard(
    monkeypatch,
    fixture_database,
):
    app = make_app(fixture_database, player_id=102)
    prompts = []
    monkeypatch.setattr(
        ausl_stats_app.messagebox,
        "askyesno",
        lambda title, message: prompts.append((title, message)) or False,
    )

    app.copy_gfx("player_id")

    assert prompts
    assert "INACTIVE" in prompts[0][1].upper()
    assert app.root.clear_calls == 0
    assert app.root.clipboard is None
    assert "not copied" in app.copy_status.get().lower()


def test_confirmed_nonactive_override_keeps_warning_in_clipboard(
    monkeypatch,
    fixture_database,
):
    app = make_app(fixture_database, player_id=103)
    monkeypatch.setattr(ausl_stats_app.messagebox, "askyesno", lambda *_args: True)

    app.copy_gfx("player_id")

    assert "RESERVE" in app.root.clipboard.upper()
    assert "VERIFY" in app.root.clipboard.upper()


def test_unknown_copy_kind_never_mutates_clipboard(fixture_database):
    app = make_app(fixture_database)

    app.copy_gfx("typo-kind")

    assert app.root.clear_calls == 0
    assert app.root.clipboard is None
    assert "unavailable" in app.copy_status.get().lower()


def test_duplicate_player_id_is_ambiguous_and_never_reaches_clipboard(
    fixture_database,
):
    duplicate = fixture_database["roster"].iloc[0].copy()
    duplicate["player_name"] = "Conflicting Identity"
    fixture_database["roster"] = pd.concat(
        [fixture_database["roster"], duplicate.to_frame().T], ignore_index=True
    )
    duplicate_stat = fixture_database["batting_2026"].iloc[0].copy()
    duplicate_stat["hits"] = 999
    fixture_database["batting_2026"] = pd.concat(
        [fixture_database["batting_2026"], duplicate_stat.to_frame().T],
        ignore_index=True,
    )
    app = make_app(fixture_database)

    assert app.gfx_text("player_id") == ""
    assert app.stat_row("batting_2026") is None
    assert app._player_row("batting_2026", 101) is None

    app.copy_gfx("player_id")

    assert app.root.clipboard is None
    assert "ambiguous" in app.copy_status.get().lower()


def test_lookup_buttons_name_the_four_explicit_copy_semantics():
    source = inspect.getsource(ausl_stats_app.AUSLStatsApp._build_lookup)

    assert '("Copy Player ID", "player_id")' in source
    assert '("Copy Season Stat", "season_stat")' in source
    assert '("Copy Career Stat", "career_stat")' in source
    assert '("Copy Announcer Note", "announcer_note")' in source
    assert "Copy Lower Third" not in source
    assert "Copy Fullscreen Stat" not in source
