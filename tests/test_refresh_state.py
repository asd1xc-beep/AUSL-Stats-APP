from __future__ import annotations

import pandas as pd

import ausl_stats_app


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def app_for_sync(roster):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame(roster)}
    app.selected_player_id = 101
    app.current_broadcast_note = "stale clipboard note"
    return app


def test_refresh_rerenders_selected_player_from_new_database_version():
    app = app_for_sync(
        [{"player_id": 101, "player_name": "Ada Updated", "team_code": "CHI"}]
    )
    rendered = []

    def render(row):
        rendered.append(row.to_dict())
        app.current_broadcast_note = f"new note for {row['player_name']}"

    app.render_player = render
    app._clear_selected_player = lambda: (_ for _ in ()).throw(
        AssertionError("valid selected player should not clear")
    )

    app._sync_selected_player_after_load(101)

    assert rendered == [
        {"player_id": 101, "player_name": "Ada Updated", "team_code": "CHI"}
    ]
    assert app.current_broadcast_note == "new note for Ada Updated"


def test_refresh_clears_player_and_clipboard_note_when_identity_disappears():
    app = app_for_sync(
        [{"player_id": 202, "player_name": "Different Player", "team_code": "CAR"}]
    )
    cleared = []

    def clear():
        cleared.append(True)
        app.selected_player_id = None
        app.current_broadcast_note = ""

    app._clear_selected_player = clear
    app.render_player = lambda _row: (_ for _ in ()).throw(
        AssertionError("missing selected player should not render")
    )

    app._sync_selected_player_after_load(101)

    assert cleared == [True]
    assert app.selected_player_id is None
    assert app.current_broadcast_note == ""


def test_refresh_clears_ambiguous_duplicate_player_identity():
    app = app_for_sync(
        [
            {"player_id": 101, "player_name": "Ada One", "team_code": "CHI"},
            {"player_id": 101, "player_name": "Ada Duplicate", "team_code": "CHI"},
        ]
    )
    cleared = []
    app._clear_selected_player = lambda: cleared.append(True)
    app.render_player = lambda _row: None

    app._sync_selected_player_after_load(101)

    assert cleared == [True]


def test_finish_load_synchronizes_player_after_installing_new_database():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "roster": pd.DataFrame(
            [{"player_id": 101, "player_name": "Old Name", "team_code": "CHI"}]
        )
    }
    app.selected_player_id = 101
    app.current_broadcast_note = "old note"
    app.data_freshness_var = FakeVar()
    app.status_var = FakeVar()
    app.format_data_freshness = lambda _manifest: "fresh fixture data"
    app._refresh_manual_note_players = lambda: None
    app.refresh_game_choices = lambda: None
    app.show_all = lambda: None
    app.render_team_totals = lambda: None
    app.render_producer_prep = lambda: None
    app.render_manual_notes = lambda: None
    rendered = []

    def render(row):
        rendered.append(row["player_name"])
        app.current_broadcast_note = "new note"

    app.render_player = render
    app._clear_selected_player = lambda: None
    replacement = {
        "roster": pd.DataFrame(
            [{"player_id": 101, "player_name": "New Name", "team_code": "CHI"}]
        ),
        "manifest": {"updated_at": "2026-07-19T22:00:00+00:00"},
    }

    app._finish_load(replacement)

    assert rendered == ["New Name"]
    assert app.current_broadcast_note == "new note"
