from __future__ import annotations

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


def required(module, name):
    assert hasattr(module, name), f"Phase 1 requires {module.__name__}.{name}"
    return getattr(module, name)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0),
        ("0.1", 1),
        (0.2, 2),
        ("1.2", 5),
        (31.2, 95),
        (9.199999999999999, 29),
    ],
)
def test_canonical_innings_parser_uses_baseball_notation(raw, expected):
    parser = required(ausl_data, "innings_to_outs")
    assert parser(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "bad", float("nan"), -1, "1.3", 2.9])
def test_canonical_innings_parser_rejects_unknown_or_invalid_values(raw):
    parser = required(ausl_data, "innings_to_outs")
    assert parser(raw) is None


def test_outs_formatter_round_trips_and_preserves_unavailable():
    formatter = required(ausl_data, "outs_to_innings")
    assert formatter(95) == "31.2"
    assert formatter(0) == "0.0"
    assert formatter(None) is None
    assert formatter(-1) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.1", "0.1"), (31.2, "31.2"), ("1.3", "—"), (None, "—")],
)
def test_visible_innings_formatter_uses_the_canonical_parser(raw, expected):
    formatter = required(ausl_stats_app, "_format_innings_value")
    assert formatter(raw) == expected


def test_rate_and_decimal_formatters_have_distinct_leading_zero_rules():
    row = pd.Series({"avg": 0.392, "era": 0.88, "whip": 1.0})
    rate = required(ausl_stats_app, "rate")

    assert rate(row, "avg") == ".392"
    assert ausl_stats_app.decimal(row, "era") == "0.88"
    assert ausl_stats_app.decimal(row, "whip") == "1.00"


@pytest.mark.parametrize("raw", [None, pd.NA, float("nan"), "not-a-number"])
def test_formatters_render_missing_or_malformed_values_as_unavailable(raw):
    row = pd.Series({"rate": raw, "decimal": raw, "whole": raw}, dtype=object)
    rate = required(ausl_stats_app, "rate")

    assert rate(row, "rate") == "—"
    assert ausl_stats_app.decimal(row, "decimal") == "—"
    assert ausl_stats_app.whole(row, "whole") == "—"


@pytest.mark.parametrize("raw", [1.9, -2.4, True, False])
def test_whole_number_formatter_rejects_nonintegral_or_boolean_counts(raw):
    row = pd.Series({"whole": raw}, dtype=object)
    assert ausl_stats_app.whole(row, "whole") == "—"


def test_missing_pitching_fields_do_not_become_factual_zeroes():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    row = pd.Series(
        {
            "appearances": None,
            "gamesStarted": None,
            "wins": None,
            "losses": None,
            "inningsPitched": None,
            "earnedRunAverage": None,
            "strikeOuts": None,
            "baseOnBalls": None,
            "whip": None,
            "saves": None,
        }
    )

    rendered = app.pitching_line(row)
    assert "—" in rendered
    assert "0-0" not in rendered


@pytest.mark.parametrize("is_pitcher", [False, True])
def test_missing_stats_do_not_create_zero_fact_broadcast_notes(is_pitcher):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    missing = pd.Series(
        {
            "hits": None,
            "homeRuns": None,
            "runsBattedIn": None,
            "strikeOuts": None,
            "inningsPitched": None,
            "earnedRunAverage": None,
        },
        dtype=object,
    )

    rendered = app.build_broadcast_note(
        is_pitcher,
        None,
        None,
        None if is_pitcher else missing,
        missing if is_pitcher else None,
    )

    assert "0 hits" not in rendered.lower()
    assert "0 strikeouts" not in rendered.lower()
    assert "available" in rendered.lower()


def test_split_line_never_displays_malformed_innings_as_an_on_air_fact():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "pitching_splits": pd.DataFrame(
            [
                {
                    "player_id": 77,
                    "season": 2026,
                    "split_label": "Fixture split",
                    "inningsPitched": "1.3",
                    "earnedRunAverage": 0.0,
                    "strikeOuts": 4,
                    "whip": 1.0,
                    "needs_review": False,
                }
            ]
        )
    }

    rendered = "\n".join(app._best_split_lines(77, True, 2026))

    assert "1.3 IP" not in rendered
    assert "unavailable until its verification gates pass" in rendered


def test_missing_first_pitch_em_dash_is_tbd():
    assert (
        ausl_stats_app.AUSLStatsApp._format_first_pitch(
            {"game_time": "—", "game_time_zone": "ET"}
        )
        == "First pitch TBD"
    )


def test_missing_time_zone_em_dash_is_not_appended():
    assert (
        ausl_stats_app.AUSLStatsApp._format_first_pitch(
            {"game_time": "07:00:00 PM", "game_time_zone": "—"}
        )
        == "7:00 PM"
    )
