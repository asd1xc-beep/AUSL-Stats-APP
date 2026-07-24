from __future__ import annotations

import pandas as pd

import ausl_stats_app


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeResults:
    def __init__(self):
        self.rows = []

    def delete(self, *_args):
        self.rows = []

    def insert(self, _where, value):
        self.rows.append(value)


def search_app(roster_rows, game_codes=("CAR",)):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame(roster_rows)}
    app.scope_var = FakeVar(True)
    app.search_var = FakeVar("")
    app.search_scope_var = FakeVar("")
    app.results = FakeResults()
    app.search_rows = []
    app._search_view = None
    app._search_team = None
    app.game_codes = lambda: set(game_codes)
    return app


def ids(frame):
    return set(frame["player_id"].astype(str))


def test_number_search_accepts_plain_and_hash_forms(roster_rows):
    roster = pd.DataFrame(roster_rows)

    plain = ausl_stats_app.filter_roster_search(roster, "22")
    hashed = ausl_stats_app.filter_roster_search(roster, "#22")

    assert ids(plain) == {"103"}
    assert ids(hashed) == {"103"}


def test_search_includes_inactive_reserve_and_unknown_status(roster_rows):
    roster = pd.DataFrame(roster_rows)

    inactive = ausl_stats_app.filter_roster_search(roster, "inactive")
    reserve = ausl_stats_app.filter_roster_search(roster, "reserve")
    unknown = ausl_stats_app.filter_roster_search(roster, "status unknown")

    assert ids(inactive) == {"102"}
    assert ids(reserve) == {"103"}
    assert ids(unknown) == {"104"}


def test_all_players_view_ignores_game_filter_without_changing_preference(roster_rows):
    app = search_app(roster_rows, game_codes=("CAR",))

    app.show_all()

    assert app.scope_var.get() is True
    assert len(app.search_rows) == len(roster_rows)
    assert app.search_scope_var.get() == "Showing: all players"


def test_team_view_does_not_mutate_game_scope_preference(roster_rows):
    app = search_app(roster_rows, game_codes=("CAR",))

    app.show_team("Chicago Bandits")

    assert app.scope_var.get() is True
    assert {row["team"] for row in app.search_rows} == {"Chicago Bandits"}
    assert app.search_scope_var.get() == "Showing: Chicago Bandits roster"


def test_scope_checkbox_clears_temporary_team_view_and_label(roster_rows):
    app = search_app(roster_rows, game_codes=("CAR",))
    app.show_team("Chicago Bandits")

    app._on_search_scope_changed()

    assert app._search_view is None
    assert app.search_rows == []
    assert app.search_scope_var.get() == "Showing: selected game teams"
