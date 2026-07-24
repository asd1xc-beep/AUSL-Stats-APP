from __future__ import annotations

import pandas as pd
import pytest

import ausl_stats_app


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeTree:
    def __init__(self):
        self.rows = []

    def get_children(self, _parent=""):
        return list(range(len(self.rows)))

    def delete(self, *items):
        if items:
            self.rows = []

    def insert(self, _parent, _where, **kwargs):
        self.rows.append(kwargs)
        return len(self.rows) - 1


def make_team_app(database):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = database
    app.data_freshness_text = "Data updated: fixture"
    app.team_totals_team_var = FakeVar("Chicago Bandits")
    app.team_totals_season_var = FakeVar("2026")
    app.team_totals_summary_var = FakeVar()
    app.team_stat_trees = {
        "batting": FakeTree(),
        "pitching": FakeTree(),
        "fielding": FakeTree(),
    }
    app.team_totals_copy_text = ""
    return app


def snapshot_api():
    assert hasattr(ausl_stats_app, "TeamSnapshot"), (
        "Phase 1 requires ausl_stats_app.TeamSnapshot"
    )
    assert hasattr(ausl_stats_app, "official_team_snapshot"), (
        "Phase 1 requires ausl_stats_app.official_team_snapshot"
    )
    return ausl_stats_app.TeamSnapshot, ausl_stats_app.official_team_snapshot


def test_snapshot_uses_one_exact_official_regular_season_row(fixture_database):
    snapshot_type, build = snapshot_api()

    snapshot = build("CHI", 2026, fixture_database)

    assert isinstance(snapshot, snapshot_type)
    assert snapshot.available is True
    assert snapshot.team_code == "CHI"
    assert snapshot.season == 2026
    assert snapshot.wins == 11
    assert snapshot.losses == 7
    assert snapshot.runs_for == 82
    assert snapshot.runs_against == 68
    assert snapshot.run_differential == 14
    assert snapshot.streak == "W2"
    assert snapshot.games_back == 1.5
    assert snapshot.source_name == "Official AUSL Standings"
    assert snapshot.source_url == "https://theausl.com/standings/"
    assert snapshot.source_timestamp == "2026-07-18T23:40:00+00:00"
    assert snapshot.record_text == "11-7"


def test_snapshot_keeps_an_official_blank_field_unavailable(fixture_database):
    _snapshot_type, build = snapshot_api()

    snapshot = build("CAR", 2026, fixture_database)

    assert snapshot.available is True
    assert snapshot.games_back is None
    assert snapshot.record_text == "9-9"


def test_snapshot_rejects_ambiguous_duplicate_official_rows(fixture_database):
    _snapshot_type, build = snapshot_api()

    snapshot = build("UTA", 2026, fixture_database)

    assert snapshot.available is False
    assert snapshot.wins is None
    assert snapshot.losses is None
    assert snapshot.record_text == "Record unavailable"


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"wins": -1}, "invalid official record"),
        ({"wins": True}, "invalid official record"),
        ({"gamesBehind": -0.5}, "games behind"),
        ({"rank": 0}, "rank"),
        ({"winPercentage": 1.2}, "win percentage"),
        ({"source_name": None}, "provenance"),
        ({"imported_at": None, "lastChangeTimestamp": None}, "freshness"),
        ({"imported_at": "not-a-timestamp"}, "freshness"),
        ({"runsScored": 20, "runsAllowed": 10, "runDifferential": 3}, "differential"),
    ],
)
def test_snapshot_rejects_malformed_or_unverifiable_official_rows(
    overrides,
    reason_fragment,
):
    row = {
        "team_code": "CHI",
        "seasonId": 369,
        "standingsTypeLk": "SEASON",
        "wins": 4,
        "losses": 2,
        "runsScored": 20,
        "runsAllowed": 10,
        "runDifferential": 10,
        "source_name": "Official AUSL Standings",
        "source_url": "https://theausl.com/standings/",
        "imported_at": "2026-07-19T00:00:00+00:00",
    }
    row.update(overrides)

    snapshot = snapshot_api()[1]("CHI", 2026, {"standings": pd.DataFrame([row])})

    assert snapshot.available is False
    assert snapshot.record_text == "Record unavailable"
    assert reason_fragment in snapshot.unavailable_reason


def test_snapshot_never_falls_back_to_pitcher_decisions():
    _snapshot_type, build = snapshot_api()
    database = {
        "standings": pd.DataFrame(),
        "pitching_2026": pd.DataFrame(
            [{"team_code": "CHI", "wins": 4}, {"team_code": "CHI", "wins": 5}]
        ),
    }

    snapshot = build("CHI", 2026, database)

    assert snapshot.available is False
    assert snapshot.wins is None
    assert snapshot.losses is None
    assert snapshot.record_text == "Record unavailable"


def test_all_record_bearing_routes_use_the_same_official_snapshot(fixture_database):
    fixture_database["fielding_2026"] = pd.DataFrame(
        columns=["team_code", "gamesPlayed", "putOuts", "assists", "errors"]
    )
    app = make_team_app(fixture_database)

    app.render_team_totals()
    packet = app._packet_team_snapshot("Chicago Bandits", 2026)
    metrics = app._team_metrics("Chicago Bandits", 2026)
    context = app._team_context_line("Chicago Bandits", 2026)
    why = app._why_game_matters("Chicago Bandits", "Carolina Blaze", 2026)

    assert "11-7" in app.team_totals_summary_var.get()
    assert "TEAM RECORD\n11-7" in app.team_totals_copy_text
    assert packet[0] == "Record: 11-7"
    assert any("Official AUSL Standings" in line for line in packet)
    assert metrics["wins"] == 11
    assert metrics["losses"] == 7
    assert metrics["record_text"] == "11-7"
    assert "11-7" in context
    assert "11-7" in why
    assert "9-9" in why

    # Pitcher decisions may remain only as an explicitly calculated aggregate.
    assert "Calculated pitcher decisions: 8-2" in app.team_totals_copy_text
    pitching_total = app.team_stat_trees["pitching"].rows[-1]["values"]
    assert pitching_total[0] == "CALCULATED PITCHER TOTALS"
    batting_total = app.team_stat_trees["batting"].rows[-1]["values"]
    assert batting_total[12].startswith(".")
    assert not batting_total[12].startswith("0.")


def test_missing_official_snapshot_never_promotes_pitcher_decisions_to_team_record(
    fixture_database,
):
    fixture_database["standings"] = pd.DataFrame()
    fixture_database["fielding_2026"] = pd.DataFrame(
        columns=["team_code", "gamesPlayed", "putOuts", "assists", "errors"]
    )
    app = make_team_app(fixture_database)

    app.render_team_totals()
    packet = app._packet_team_snapshot("Chicago Bandits", 2026)
    metrics = app._team_metrics("Chicago Bandits", 2026)
    context = app._team_context_line("Chicago Bandits", 2026)

    assert "Record unavailable" in app.team_totals_summary_var.get()
    assert "TEAM RECORD\nRecord unavailable" in app.team_totals_copy_text
    assert packet[0] == "Record unavailable"
    assert metrics["wins"] is None
    assert metrics["losses"] is None
    assert metrics["record_text"] == "Record unavailable"
    assert "Record unavailable" in context
    assert "Calculated pitcher decisions: 8-2" in app.team_totals_copy_text


def test_team_sum_distinguishes_missing_values_from_factual_zeroes():
    app = make_team_app({})

    assert app._frame_sum(pd.DataFrame(), "runs") is None
    assert app._frame_sum(pd.DataFrame({"runs": [None, pd.NA]}), "runs") is None
    assert app._frame_sum(pd.DataFrame({"runs": [0, 0]}), "runs") == 0


def test_missing_fielding_source_is_unavailable_instead_of_zero(fixture_database):
    fixture_database["fielding_2026"] = pd.DataFrame(
        columns=["team_code", "gamesPlayed", "putOuts", "assists", "errors"]
    )
    app = make_team_app(fixture_database)

    app.render_team_totals()
    metrics = app._team_metrics("Chicago Bandits", 2026)

    fielding_total = app.team_stat_trees["fielding"].rows[-1]["values"]
    assert fielding_total[3:] == ("—", "—", "—", "—", "—")
    assert "FIELDING\nTotals unavailable — source data missing." in app.team_totals_copy_text
    assert metrics["errors"] is None
    assert metrics["fielding_pct"] is None


def test_team_pitcher_whip_is_unavailable_when_a_required_input_is_missing(
    fixture_database,
):
    pitching = fixture_database["pitching_2026"].copy()
    pitching.loc[pitching["player_id"].eq(105), "hitsAllowed"] = None
    fixture_database["pitching_2026"] = pitching
    app = make_team_app(fixture_database)

    app.render_team_totals()

    player_row = next(
        row["values"]
        for row in app.team_stat_trees["pitching"].rows
        if row["values"][0] == "Pia Pitcher"
    )
    assert player_row[12] == "—"


@pytest.mark.parametrize(
    ("missing_key", "copy_section", "packet_line", "metric_keys"),
    [
        (
            "batting_2026",
            "BATTING\nTotals unavailable — source data missing.",
            "Offense: unavailable — source data missing.",
            ("runs", "hits", "home_runs", "rbi", "avg", "obp", "slg", "ops"),
        ),
        (
            "pitching_2026",
            "PITCHING\nTotals unavailable — source data missing.",
            "Pitching: unavailable — source data missing.",
            (
                "calculated_pitcher_wins",
                "calculated_pitcher_losses",
                "era",
                "whip",
                "strikeouts",
            ),
        ),
    ],
)
def test_missing_team_stat_source_is_unavailable_across_routes(
    fixture_database,
    missing_key,
    copy_section,
    packet_line,
    metric_keys,
):
    fixture_database[missing_key] = pd.DataFrame()
    app = make_team_app(fixture_database)

    app.render_team_totals()
    packet = app._packet_team_snapshot("Chicago Bandits", 2026)
    metrics = app._team_metrics("Chicago Bandits", 2026)

    assert copy_section in app.team_totals_copy_text
    assert packet_line in packet
    assert all(metrics[key] is None for key in metric_keys)
