"""Offline tests for canonical identifiers and roster availability state."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import ausl_data


@pytest.mark.parametrize(
    ("alias", "expected_code"),
    [
        ("Bandits", "CHI"),
        ("Chicago Bandits", "CHI"),
        (" chi ", "CHI"),
        ("Blaze", "CAR"),
        ("Carolina Blaze", "CAR"),
        ("CAR", "CAR"),
        ("Cascade", "PDX"),
        ("Portland Cascade", "PDX"),
        ("pdx", "PDX"),
        ("Spark", "OKC"),
        ("Oklahoma City Spark", "OKC"),
        ("OKC", "OKC"),
        ("Talons", "UTA"),
        ("Utah Talons", "UTA"),
        ("UTA", "UTA"),
        ("Volts", "TEX"),
        ("Texas Volts", "TEX"),
        ("tex", "TEX"),
    ],
)
def test_normalize_team_code_accepts_only_exact_known_aliases(alias, expected_code):
    assert ausl_data.normalize_team_code(alias) == expected_code


@pytest.mark.parametrize(
    "unknown",
    [None, "", "   ", "Oklahoma City", "Portland Pioneers", "Mystery Club"],
)
def test_normalize_team_code_never_guesses_from_unknown_names(unknown):
    assert ausl_data.normalize_team_code(unknown) is None


@pytest.mark.parametrize("missing", [None, "", "   ", pd.NA, math.nan])
def test_normalize_roster_status_marks_missing_values_unknown(missing):
    assert ausl_data.normalize_roster_status(missing) == "Status unknown"


@pytest.mark.parametrize(
    "official_status", ["Active", "Reserve Pool", "Injured - Temporary"]
)
def test_normalize_roster_status_preserves_official_nonblank_text(official_status):
    assert ausl_data.normalize_roster_status(official_status) == official_status


def _roster_payload(*, team_name="Bandits", status_marker="absent"):
    ausl_info = {
        "uniformNumberDisplay": "12",
        "primaryPosition": {"positionLk": "IF", "description": "Infield"},
    }
    if status_marker != "absent":
        ausl_info["currentRosterStatus"] = status_marker
    return {
        "players": [
            {
                "playerId": 123,
                "firstName": "Casey",
                "lastName": "Example",
                "franchise": {"teamName": team_name},
                "sportInfoBySport": {"ausl": ausl_info},
            }
        ]
    }


def test_roster_frame_does_not_treat_absent_status_as_active():
    row = ausl_data.roster_frame(_roster_payload(), 2026).iloc[0]

    assert row["roster_status"] == "Status unknown"
    assert row["team_code"] == "CHI"


def test_roster_frame_does_not_fabricate_unknown_team_code():
    row = ausl_data.roster_frame(
        _roster_payload(
            team_name="Portland Pioneers",
            status_marker={"description": "Active"},
        ),
        2026,
    ).iloc[0]

    assert pd.isna(row["team_code"]) or row["team_code"] in (None, "")
    assert row["roster_status"] == "Active"


def test_schedule_parser_never_guesses_home_and_away_from_competitor_order(
    monkeypatch,
):
    game = {
        "seasonId": 2026,
        "gameId": 9001,
        "homeTeamId": 10,
        "awayTeamId": 20,
        "competitors": [
            {"competitorId": 30, "name": "Chicago Bandits"},
            {"competitorId": 40, "name": "Carolina Blaze"},
        ],
    }
    monkeypatch.setattr(ausl_data, "_get_text", lambda _path: "fixture")
    monkeypatch.setattr(
        ausl_data,
        "_json_array_after",
        lambda _text, _marker: [game],
    )

    row = ausl_data.fetch_schedule_frame().iloc[0]

    assert row["game_id"] == 9001
    assert row["home_team"] == ""
    assert row["away_team"] == ""
    assert row["home_team_code"] == ""
    assert row["away_team_code"] == ""
