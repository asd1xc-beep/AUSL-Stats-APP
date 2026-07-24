"""Small offline characterization coverage for unchanged application behavior."""

from __future__ import annotations

import pandas as pd
import pytest

import ausl_data
from ausl_stats_app import AUSLStatsApp


def _app_without_tk(**attributes):
    app = AUSLStatsApp.__new__(AUSLStatsApp)
    for name, value in attributes.items():
        setattr(app, name, value)
    return app


def test_existing_lineup_parser_resolves_team_players_and_sorts_order():
    roster = pd.DataFrame(
        [
            {
                "player_id": 101,
                "player_name": "Casey Ace",
                "team": "Chicago Bandits",
                "team_code": "CHI",
                "jersey_number": 13,
                "position": "CF",
                "roster_status": "Active",
            },
            {
                "player_id": 102,
                "player_name": "Riley Roe",
                "team": "Chicago Bandits",
                "team_code": "CHI",
                "jersey_number": 8,
                "position": "SS",
                "roster_status": "Reserve Pool",
            },
        ]
    )
    app = _app_without_tk(db={"roster": roster})

    entries = app.parse_lineup_text(
        "2. #8 Riley Roe - SS\n1. #13 Casey Ace - CF",
        "Chicago Bandits",
    )

    assert [entry["batting_order"] for entry in entries] == [1, 2]
    assert [entry["player_id"] for entry in entries] == ["101", "102"]
    assert entries[0]["position"] == "CF"
    assert entries[1]["roster_status"] == "Reserve Pool"


def test_invalid_lineup_fixture_characterizes_current_unvalidated_cases(
    load_fixture,
    fixture_database,
):
    examples = load_fixture("lineup_examples.json")["invalid"]
    app = _app_without_tk(db={"roster": fixture_database["roster"]})
    parsed = {
        example["case"]: app.parse_lineup_text(
            example["text"], "Chicago Bandits"
        )
        for example in examples
    }

    assert [
        entry["batting_order"]
        for entry in parsed["duplicate batting order"]
    ] == [1, 1]
    assert parsed["ambiguous typed player"][0]["player_id"] == "101"
    assert parsed["DP without FLEX"][0]["position"] == "DP"
    assert all(
        entry["position"].upper() != "FLEX"
        for entry in parsed["DP without FLEX"]
    )


def test_media_guide_cleaner_removes_repeated_page_noise():
    raw = (
        "12 | 2026 AUSL MEDIA GUIDE @THEAUSLOFFICIAL THEAUSL.COM "
        "Rachel Garcia won the title."
    )

    cleaned = ausl_data._clean_media_guide_text(raw)

    assert cleaned.endswith("Rachel Garcia won the title.")
    assert "2026 AUSL MEDIA GUIDE" not in cleaned
    assert "THEAUSL.COM" not in cleaned


@pytest.mark.parametrize(
    ("note", "expected_category"),
    [
        ("Taylor is the probable starter tonight.", "probable_starter"),
        ("She needs two hits for the career milestone.", "milestone_watch"),
        ("Official injury availability update.", "availability"),
        ("The clubs meet in a rematch.", "matchup_history"),
        ("The team has won four straight games.", "recent_trend"),
    ],
)
def test_existing_game_note_classification(note, expected_category):
    assert ausl_data._game_note_category(note) == expected_category


def test_atomic_excel_writer_replaces_complete_workbook_and_cleans_temp_files(tmp_path):
    target = tmp_path / "database.xlsx"
    pd.DataFrame({"old": [1]}).to_excel(target, index=False)

    ausl_data._write_excel_atomic(
        target,
        {
            "roster_2026": pd.DataFrame(
                {"player_id": [123], "player_name": ["Casey Example"]}
            ),
            "a_sheet_name_longer_than_thirty_one_characters": pd.DataFrame(
                {"game_id": [9001]}
            ),
        },
    )

    assert pd.read_excel(target, sheet_name="roster_2026").to_dict("records") == [
        {"player_id": 123, "player_name": "Casey Example"}
    ]
    with pd.ExcelFile(target) as workbook:
        assert workbook.sheet_names == [
            "roster_2026",
            "a_sheet_name_longer_than_thirty",
        ]
    assert list(tmp_path.glob("*.xlsx")) == [target]


def test_atomic_excel_writer_preserves_prior_file_when_generation_fails(
    tmp_path, monkeypatch
):
    target = tmp_path / "database.xlsx"
    original = b"recoverable prior database"
    target.write_bytes(original)

    def fail_to_create_writer(*_args, **_kwargs):
        raise RuntimeError("injected writer failure")

    monkeypatch.setattr(ausl_data.pd, "ExcelWriter", fail_to_create_writer)

    with pytest.raises(RuntimeError, match="injected writer failure"):
        ausl_data._write_excel_atomic(
            target, {"standings": pd.DataFrame({"wins": [1]})}
        )

    assert target.read_bytes() == original
    assert list(tmp_path.glob("*.xlsx")) == [target]


def test_representative_live_box_formats_without_network_or_tk():
    app = _app_without_tk(
        live_box={
            "competitors": [
                {"eventTeamId": 1, "name": "Chicago Bandits", "abbreviation": "CHI"},
                {"eventTeamId": 2, "name": "Carolina Blaze", "abbreviation": "CAR"},
            ],
            "lineScores": [
                {
                    "eventTeamId": 1,
                    "abbreviation": "CHI",
                    "runs": 4,
                    "hits": 7,
                    "errors": 0,
                    "innings": [{"runs": 1}, {"runs": 3}],
                },
                {
                    "eventTeamId": 2,
                    "abbreviation": "CAR",
                    "runs": 2,
                    "hits": 5,
                    "errors": 1,
                    "innings": [{"runs": 0}, {"runs": 2}],
                },
            ],
            "batting": {
                "chi": {
                    "players": [
                        {
                            "playerName": "Casey Example",
                            "eventTeamId": 1,
                            "ab": 3,
                            "h": 2,
                            "r": 1,
                            "rbi": 2,
                        }
                    ]
                }
            },
            "pitching": {
                "car": {
                    "players": [
                        {
                            "playerName": "Riley Pitcher",
                            "eventTeamId": 2,
                            "ip": "3.2",
                            "h": 4,
                            "er": 1,
                            "bb": 1,
                            "so": 5,
                        }
                    ]
                }
            },
        }
    )

    text = app.format_live_comparison()

    assert "CHICAGO BANDITS VS CAROLINA BLAZE" in text
    assert "CHI          R 4   H 7   E 0   | 1 3" in text
    assert "CAR          R 2   H 5   E 1   | 0 2" in text
    assert "Batting player lines available: 1" in text
    assert "Pitching player lines available: 1" in text


def test_live_action_note_characterization():
    assert AUSLStatsApp.live_action_note(
        "batting", {"h": 2, "hr": 1, "rbi": 3, "r": 1}
    ) == "Has homered; has a 2-hit game; has driven in 3 runs."


@pytest.mark.parametrize(
    "row",
    [
        {"ip": None, "er": 0, "so": 5},
        {"ip": "3.0", "er": None, "so": 5},
        {"ip": "bad", "er": 0, "so": 5},
    ],
)
def test_live_action_note_does_not_turn_missing_pitching_data_into_zero(row):
    rendered = AUSLStatsApp.live_action_note("pitching", row)

    assert rendered == "Action note unavailable — official live stats are incomplete; verify before air."
    assert "scoreless" not in rendered.lower()
    assert "0 earned" not in rendered.lower()


@pytest.mark.parametrize(
    ("category", "row"),
    [
        ("batting", {"h": 1.9, "hr": 0, "rbi": 1, "r": 0}),
        ("batting", {"h": -1, "hr": 0, "rbi": 1, "r": 0}),
        ("pitching", {"ip": "3.0", "er": 0, "so": 4.2}),
        ("pitching", {"ip": "3.0", "er": -1, "so": 4}),
    ],
)
def test_live_action_note_rejects_fractional_or_negative_count_stats(category, row):
    rendered = AUSLStatsApp.live_action_note(category, row)

    assert rendered == (
        "Action note unavailable — official live stats are incomplete; verify before air."
    )


def test_compact_stats_fixture_includes_batting_and_pitching_nulls(fixture_database):
    assert fixture_database["batting_2026"].isna().any().any()
    assert fixture_database["pitching_2026"].isna().any().any()
