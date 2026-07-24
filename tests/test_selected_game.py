from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import ausl_stats_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakePicker:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class FakeText:
    def __init__(self, value="stale editor text"):
        self.value = value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, text):
        self.value = text


def selected_game_frame(load_fixture):
    fixture = load_fixture("selected_games.json")
    return pd.DataFrame(fixture["official_games"] + fixture["invalid_rows"])


def test_official_selected_games_require_unique_authoritative_identity(load_fixture):
    games = ausl_stats_app.official_selected_games(selected_game_frame(load_fixture))

    assert [game.game_id for game in games] == ["9001", "9002", "9005"]
    first = games[0]
    assert first.season == 2026
    assert first.date_time.isoformat() == "2026-07-20T19:00:00-04:00"
    assert first.away_team == "Chicago Bandits"
    assert first.home_team == "Carolina Blaze"
    assert first.venue == "Fixture Stadium"
    assert first.status == "Scheduled"
    assert first.source_updated_at == "2026-07-19T12:00:00+00:00"
    assert "GAME 9001" in first.choice_label

    unavailable = games[-1]
    assert unavailable.venue == "Venue unavailable"
    assert unavailable.status == "Status unavailable"


def test_default_selected_game_prefers_nearest_upcoming_official_id(load_fixture):
    games = ausl_stats_app.official_selected_games(selected_game_frame(load_fixture))

    selected = ausl_stats_app.choose_default_selected_game(
        games, today=date(2026, 7, 19)
    )

    assert selected.game_id == "9001"


def test_schedule_picker_uses_official_games_not_team_pair_guessing(load_fixture):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"schedule_results": selected_game_frame(load_fixture)}
    app.game_picker = FakePicker()
    app.game_choice_var = FakeVar()
    app.selected_game = None
    selected = []
    app.on_game_changed = selected.append

    app.refresh_game_choices(today=date(2026, 7, 19))

    assert app.game_picker.options["state"] == "readonly"
    values = app.game_picker.options["values"]
    assert len(values) == 3
    assert values[0] != values[1]
    assert "GAME 9001" in values[0]
    assert "GAME 9002" in values[1]
    assert selected[0].game_id == "9001"


def test_repeat_opponent_game_change_resets_stale_state_by_game_id(load_fixture):
    games = ausl_stats_app.official_selected_games(selected_game_frame(load_fixture))
    first, second = games[:2]
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "roster": pd.DataFrame(
            [{"player_id": 77, "team_code": "UTA", "player_name": "Old Player"}]
        )
    }
    app.selected_game = first
    app.selected_player_id = 77
    app.away_var = FakeVar(first.away_team)
    app.home_var = FakeVar(first.home_team)
    app.game_choice_var = FakeVar(first.choice_label)
    app.game_context_var = FakeVar()
    app.note_game_var = FakeVar(first.game_id)
    app.game_id_var = FakeVar(first.game_id)
    app.scope_var = FakeVar(True)
    app.live_game = {"gameId": int(first.game_id)}
    app.live_box = {"competitors": []}
    app._search_view = "team"
    app._search_team = "Chicago Bandits"

    events = []
    app.search = lambda: events.append("search")
    app._clear_selected_player = lambda: (
        setattr(app, "selected_player_id", None),
        events.append("player-cleared"),
    )
    app._reset_lineup_editor_for_game = lambda game: events.append(
        f"lineup-{game.game_id}"
    )
    app._reset_live_for_game = lambda game: events.append(f"live-{game.game_id}")
    app.render_producer_prep = lambda: events.append("prep")
    app.render_manual_notes = lambda: events.append("notes")

    app.on_game_changed(second)

    assert app.selected_game == second
    assert app.away_var.get() == "Chicago Bandits"
    assert app.home_var.get() == "Carolina Blaze"
    assert app.selected_player_id is None
    assert app.note_game_var.get() == "9002"
    assert app.game_id_var.get() == "9002"
    assert app._search_view is None
    assert app._search_team is None
    assert "OFFICIAL AUSL SCHEDULE" in app.game_context_var.get().upper()
    assert "GAME ID 9002" in app.game_context_var.get().upper()
    assert "lineup-9002" in events
    assert "live-9002" in events
    assert {"search", "player-cleared", "prep", "notes"}.issubset(events)


def test_lineup_editor_reset_cannot_carry_text_across_repeat_games(load_fixture):
    game = ausl_stats_app.official_selected_games(selected_game_frame(load_fixture))[1]
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.lineup_widgets = {
        side: {
            "starter": FakeVar("Stale Pitcher"),
            "text": FakeText(),
            "status": FakeVar("Locked for another game"),
        }
        for side in ("away", "home")
    }
    app.lineup_lock_status = FakeVar()

    app._reset_lineup_editor_for_game(game)

    for widget in app.lineup_widgets.values():
        assert widget["starter"].get() == ""
        assert widget["text"].value == ""
        assert "Game 9002" in widget["status"].get()
    assert "cleared" in app.lineup_lock_status.get().lower()


def test_selected_game_line_uses_exact_id_instead_of_guessing_repeat_matchup(
    load_fixture,
):
    game = ausl_stats_app.official_selected_games(selected_game_frame(load_fixture))[1]
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = game
    app.db = {"schedule_results": selected_game_frame(load_fixture)}

    rendered = app._selected_game_line(game.away_team, game.home_team)

    assert "Game ID 9002" in rendered
    assert "Fixture Stadium" in rendered
    assert "Official AUSL Schedule" in rendered
    assert "2026-07-19T12:00:00+00:00" in rendered
    assert "9001" not in rendered


def test_custom_game_line_never_guesses_an_official_game_from_team_names(load_fixture):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = None
    app.db = {"schedule_results": selected_game_frame(load_fixture)}

    rendered = app._selected_game_line("Chicago Bandits", "Carolina Blaze")

    assert "CUSTOM / UNVERIFIED" in rendered
    assert "official game ID" in rendered
    assert "9001" not in rendered
    assert "9002" not in rendered


def test_checked_in_schedule_has_one_selected_model_per_authoritative_game_id():
    schedule = pd.read_excel(
        PROJECT_ROOT / "data" / "exports" / "ausl_team_context.xlsx",
        sheet_name="schedule_results",
    )

    games = ausl_stats_app.official_selected_games(schedule)
    expected_ids = {
        ausl_stats_app._manual_note_identifier(value)
        for value in schedule["game_id"]
    }

    assert len(games) == len(schedule)
    assert {game.game_id for game in games} == expected_ids
