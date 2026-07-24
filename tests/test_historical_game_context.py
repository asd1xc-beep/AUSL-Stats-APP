from __future__ import annotations

from datetime import datetime

import pandas as pd

import ausl_stats_app


def selected_game(*, game_id="9001", date_time="2026-07-20T19:00:00-04:00", status="Completed"):
    return ausl_stats_app.SelectedGame(
        game_id=game_id,
        season=2026,
        date_time=datetime.fromisoformat(date_time),
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        away_team_code="CHI",
        home_team_code="CAR",
        time_zone="EDT",
        venue="Fixture Stadium",
        status=status,
        source_updated_at="2026-07-22T12:00:00+00:00",
        source_name="Official AUSL Schedule",
    )


def context_app(rows, *, game=None):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = game or selected_game()
    app.db = {"schedule_results": pd.DataFrame(rows)}
    return app


def test_recent_matchup_uses_only_completed_games_strictly_before_selection():
    app = context_app(
        [
            {
                "game_id": "8999",
                "game_date": "2026-07-10T19:00:00-04:00",
                "away_team_code": "CAR",
                "home_team_code": "CHI",
                "away_score": 3,
                "home_score": 5,
                "status": "completed",
            },
            {
                "game_id": "9001",
                "game_date": "2026-07-20T19:00:00-04:00",
                "away_team_code": "CHI",
                "home_team_code": "CAR",
                "away_score": 2,
                "home_score": 1,
                "status": "completed",
            },
            {
                "game_id": "9002",
                "game_date": "2026-07-27T19:00:00-04:00",
                "away_team_code": "CAR",
                "home_team_code": "CHI",
                "away_score": 6,
                "home_score": 7,
                "status": "completed",
            },
        ]
    )

    line = app._recent_matchup_line("Chicago Bandits", "Carolina Blaze")

    assert "CAR 3 at CHI 5" in line
    assert "9001" not in line
    assert "July 27" not in line


def test_recent_matchup_fails_closed_for_equal_time_and_unparseable_rows():
    app = context_app(
        [
            {
                "game_id": "8998",
                "game_date": "not-a-date",
                "away_team_code": "CAR",
                "home_team_code": "CHI",
                "away_score": 3,
                "home_score": 5,
                "status": "completed",
            },
            {
                "game_id": "8999",
                "game_date": "2026-07-20T19:00:00-04:00",
                "away_team_code": "CAR",
                "home_team_code": "CHI",
                "away_score": 3,
                "home_score": 5,
                "status": "completed",
            },
        ]
    )

    line = app._recent_matchup_line("Chicago Bandits", "Carolina Blaze")

    assert "No prior completed head-to-head meeting" in line


def test_historical_game_uses_current_standings_only_with_not_as_of_label(
    fixture_database,
):
    app = context_app(
        fixture_database["schedule_results"].to_dict("records"),
        game=selected_game(date_time="2026-07-11T19:00:00-04:00"),
    )
    app.db.update(fixture_database)

    line = app._why_game_matters("Chicago Bandits", "Carolina Blaze", 2026)

    assert "enters" not in line.lower()
    assert "current standings" in line.lower()
    assert "not an as-of-game snapshot" in line.lower()
