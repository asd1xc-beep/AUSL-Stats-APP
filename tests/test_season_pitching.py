from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "season_pitching_whip_cases.json").read_text(
        encoding="utf-8"
    )
)


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": index + 1,
                "player_name": case["label"],
                "inningsPitched": case["inningsPitched"],
                "hitsAllowed": case["hitsAllowed"],
                "baseOnBalls": case["baseOnBalls"],
                "whip": case["source_whip"],
            }
            for index, case in enumerate(CASES)
        ]
    )


def test_season_pitching_normalization_keeps_source_and_derives_whip_from_outs():
    normalized = ausl_data.normalize_pitching_frame(_source_frame())

    assert {"source_whip", "innings_outs", "whip_inputs_available"}.issubset(
        normalized.columns
    )
    for case, (_, row) in zip(CASES, normalized.iterrows()):
        assert row["source_whip"] == pytest.approx(case["source_whip"])
        if case["expected_outs"] is None:
            assert pd.isna(row["innings_outs"])
            assert pd.isna(row["whip"])
            assert bool(row["whip_inputs_available"]) is False
        else:
            assert int(row["innings_outs"]) == case["expected_outs"]
            assert row["whip"] == pytest.approx(case["expected_whip"])
            assert bool(row["whip_inputs_available"]) is True


@pytest.mark.parametrize("case", CASES, ids=[case["label"] for case in CASES])
def test_exact_season_stat_clipboard_uses_canonical_whip(case):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_player_id = 77
    app.data_freshness_text = "Data updated: fixture - VERIFY"
    app.db = {
        "roster": pd.DataFrame(
            [
                {
                    "player_id": 77,
                    "player_name": "Test Pitcher",
                    "team": "Chicago Bandits",
                    "position": "P",
                    "jersey_number": 7,
                    "roster_status": "Active",
                }
            ]
        ),
        "pitching_2026": pd.DataFrame(
            [
                {
                    "player_id": 77,
                    "appearances": 1,
                    "gamesStarted": 1,
                    "wins": 1,
                    "losses": 0,
                    "inningsPitched": case["inningsPitched"],
                    "earnedRunAverage": 0.88,
                    "strikeOuts": 5,
                    "hitsAllowed": case["hitsAllowed"],
                    "baseOnBalls": case["baseOnBalls"],
                    "whip": case["source_whip"],
                    "saves": 0,
                }
            ]
        ),
    }

    expected = (
        "TEST PITCHER — 2026 AUSL SEASON\n"
        f"1 APP / 1 GS | 1-0 | {case['inningsPitched'] if case['expected_outs'] is not None else '—'} IP | "
        f"0.88 ERA | 5 SO | {case['baseOnBalls']} BB | {case['expected_display']} WHIP | 0 SV\n"
        "STATUS: Active\n"
        "SOURCE: Official AUSL roster and imported stat snapshot\n"
        "Data updated: fixture - VERIFY"
    )
    assert app.gfx_text("season_stat") == expected


def test_checked_in_season_pitching_workbook_is_canonical_and_auditable():
    workbook = PROJECT_ROOT / "data" / "exports" / "ausl_season_stats.xlsx"
    for year in ausl_data.SEASONS:
        frame = pd.read_excel(workbook, sheet_name=f"pitching_{year}")
        assert {"source_whip", "innings_outs", "whip_inputs_available"}.issubset(
            frame.columns
        )
        for _, row in frame.iterrows():
            expected = ausl_data.canonical_pitching_whip(row)
            if expected is None:
                assert pd.isna(row["whip"])
            else:
                assert row["whip"] == pytest.approx(expected)


def test_all_checked_in_season_pitcher_copy_routes_use_formula_correct_whip():
    database = ausl_data.load_database()
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = database
    app.data_freshness_text = "Data updated: checked-in snapshot - VERIFY"

    pitcher_roster = database["roster"][
        database["roster"]["position"].fillna("").str.upper().isin(ausl_stats_app.PITCHER_POSITIONS)
    ]
    roster_ids = set(pd.to_numeric(pitcher_roster["player_id"], errors="coerce").dropna())
    for _, row in database["pitching_2026"].iterrows():
        player_id = int(row["player_id"])
        if player_id not in roster_ids:
            continue
        app.selected_player_id = player_id
        rendered = app.gfx_text("season_stat")
        expected = ausl_data.canonical_pitching_whip(row)
        expected_text = "— WHIP" if expected is None else f"{expected:.2f} WHIP"
        assert expected_text in rendered, f"player_id={player_id}: {rendered!r}"
