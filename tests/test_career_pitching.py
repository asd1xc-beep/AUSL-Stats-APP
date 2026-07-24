"""Offline correctness tests for baseball innings and career pitching."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import ausl_data


@pytest.mark.parametrize(
    ("value", "expected_outs"),
    [
        (0, 0),
        ("0.1", 1),
        (0.2, 2),
        ("1.2", 5),
        (31.2, 95),
        # Excel can expose the binary representation instead of a tidy 9.2.
        (9.199999999999999, 29),
    ],
)
def test_innings_to_outs_uses_baseball_notation(value, expected_outs):
    assert ausl_data.innings_to_outs(value) == expected_outs


@pytest.mark.parametrize(
    "value",
    [None, pd.NA, math.nan, "", "not innings", -0.1, 1.3, 31.25, True],
)
def test_innings_to_outs_rejects_unavailable_or_malformed_values(value):
    assert ausl_data.innings_to_outs(value) is None


def _pitching_row(**overrides):
    row = {
        "season": 2025,
        "player_id": 77,
        "player_name": "Test Pitcher",
        "inningsPitched": "1.2",
        "appearances": 1,
        "gamesStarted": 1,
        "hitsAllowed": 2,
        "earnedRuns": 1,
        "baseOnBalls": 1,
        "strikeOuts": 3,
    }
    row.update(overrides)
    return row


def test_career_pitching_aggregates_outs_before_era_and_whip():
    season_2025 = pd.DataFrame([_pitching_row()])
    season_2026 = pd.DataFrame(
        [
            _pitching_row(
                season=2026,
                inningsPitched="0.1",
                hitsAllowed=1,
                earnedRuns=0,
                baseOnBalls=0,
                strikeOuts=1,
            )
        ]
    )

    result = ausl_data.career_pitching([season_2025, season_2026])
    row = result.iloc[0]

    assert row["seasons"] == 2
    assert float(row["inningsPitched"]) == pytest.approx(2.0)
    assert row["earnedRunAverage"] == pytest.approx(3.5)
    assert row["whip"] == pytest.approx(2.0)
    assert bool(row["innings_available"]) is True
    assert int(row["innings_invalid_count"]) == 0
    source_values = str(row["innings_source_values"])
    assert "1.2" in source_values
    assert "0.1" in source_values


@pytest.mark.parametrize("bad_innings", [None, pd.NA, math.nan, "bad", 1.3])
def test_invalid_contributing_innings_make_career_rates_unavailable(bad_innings):
    valid = pd.DataFrame([_pitching_row()])
    invalid = pd.DataFrame(
        [
            _pitching_row(
                season=2026,
                inningsPitched=bad_innings,
                hitsAllowed=4,
                earnedRuns=2,
                baseOnBalls=2,
            )
        ]
    )

    row = ausl_data.career_pitching([valid, invalid]).iloc[0]

    assert pd.isna(row["inningsPitched"])
    assert pd.isna(row["earnedRunAverage"])
    assert pd.isna(row["whip"])
    assert bool(row["innings_available"]) is False
    assert int(row["innings_invalid_count"]) == 1
    assert "1.2" in str(row["innings_source_values"])


def test_missing_innings_column_is_unavailable_and_auditable_not_a_crash():
    frame = pd.DataFrame(
        [
            {
                key: value
                for key, value in _pitching_row().items()
                if key != "inningsPitched"
            }
        ]
    )

    row = ausl_data.career_pitching([frame]).iloc[0]

    assert pd.isna(row["inningsPitched"])
    assert pd.isna(row["earnedRunAverage"])
    assert pd.isna(row["whip"])
    assert bool(row["innings_available"]) is False
    assert int(row["innings_invalid_count"]) == 1
    assert "innings_source_values" in row.index


@pytest.mark.parametrize(
    ("missing_input", "unavailable_rate", "availability_field", "invalid_count_field"),
    [
        ("earnedRuns", "earnedRunAverage", "era_inputs_available", "era_input_invalid_count"),
        ("hitsAllowed", "whip", "whip_inputs_available", "whip_input_invalid_count"),
        ("baseOnBalls", "whip", "whip_inputs_available", "whip_input_invalid_count"),
    ],
)
def test_missing_career_rate_input_never_becomes_a_partial_zero_sum(
    missing_input,
    unavailable_rate,
    availability_field,
    invalid_count_field,
):
    valid = pd.DataFrame([_pitching_row(inningsPitched="1.0")])
    incomplete_values = {
        "season": 2026,
        "inningsPitched": "1.0",
        "hitsAllowed": 2,
        "earnedRuns": 1,
        "baseOnBalls": 1,
    }
    incomplete_values[missing_input] = None
    incomplete = pd.DataFrame(
        [_pitching_row(**incomplete_values)]
    )

    row = ausl_data.career_pitching([valid, incomplete]).iloc[0]

    assert bool(row["innings_available"]) is True
    assert pd.isna(row[unavailable_rate])
    assert bool(row[availability_field]) is False
    assert int(row[invalid_count_field]) == 1


def test_career_batting_requires_complete_inputs_instead_of_partial_sums():
    rows = [
        {
            "season": 2025,
            "player_id": 88,
            "player_name": "Incomplete Hitter",
            "atBat": 1,
            "hits": 1,
            "totalBases": 1,
            "baseonBalls": 0,
            "hitByPitch": 0,
            "sacrificeFly": 0,
        },
        {
            "season": 2026,
            "player_id": 88,
            "player_name": "Incomplete Hitter",
            "atBat": 1,
            "hits": None,
            "totalBases": None,
            "baseonBalls": 0,
            "hitByPitch": 0,
            "sacrificeFly": 0,
        },
    ]

    row = ausl_data.career_batting([pd.DataFrame(rows)]).iloc[0]

    assert pd.isna(row["hits"])
    assert pd.isna(row["battingAverage"])
    assert pd.isna(row["sluggingPercentage"])
    assert pd.isna(row["opsPercentage"])


def test_career_fielding_requires_complete_inputs_instead_of_partial_sums():
    rows = [
        {
            "season": 2025,
            "player_id": 89,
            "player_name": "Incomplete Fielder",
            "putOuts": 1,
            "assists": 1,
            "errors": 0,
            "totalChances": 2,
        },
        {
            "season": 2026,
            "player_id": 89,
            "player_name": "Incomplete Fielder",
            "putOuts": None,
            "assists": 1,
            "errors": None,
            "totalChances": 1,
        },
    ]

    row = ausl_data.career_fielding([pd.DataFrame(rows)]).iloc[0]

    assert pd.isna(row["putOuts"])
    assert pd.isna(row["errors"])
    assert pd.isna(row["fieldingPercent"])
