from __future__ import annotations

import json

import pandas as pd

import ausl_data


def test_phase4_conservative_game_note_categories(load_fixture):
    fixture = load_fixture("official_game_notes_phase4.json")

    actual = {
        case["note"]: ausl_data._game_note_category(case["note"])
        for case in fixture["classification_cases"]
    }

    assert actual == {
        case["note"]: case["category"] for case in fixture["classification_cases"]
    }


def test_split_game_note_item_keeps_exact_subject_identity_and_team():
    page = (
        "#12 - ADA ACTIVE P 5-7 Raleigh, N.C. "
        " • Needs two hits to reach 50 AUSL career hits."
    )
    lookup = [
        {
            "name": "Ada Active",
            "player_id": "101",
            "team_code": "CHI",
            "key": "ADAACTIVE",
            "first_initial": "A",
            "last_key": "ACTIVE",
        }
    ]

    notes = ausl_data._split_game_note_items(page, lookup)

    assert notes == [
        {
            "note_text": "Ada Active: Needs two hits to reach 50 AUSL career hits.",
            "player_name": "Ada Active",
            "player_id": "101",
            "team_code": "CHI",
        }
    ]


def test_official_note_rows_include_complete_provenance_and_fail_closed_state():
    game = pd.Series(
        {
            "game_id": 9001,
            "game_date": "2026-07-20",
            "away_team_code": "CHI",
            "home_team_code": "CAR",
        }
    )
    parsed_note = {
        "note_text": "Ada Active: Needs two hits to reach 50 AUSL career hits.",
        "player_name": "Ada Active",
        "player_id": "101",
        "team_code": "CHI",
    }

    row = ausl_data._official_game_note_row(
        game,
        parsed_note,
        source_url="https://theausl.com/notes/9001.pdf",
        source_page=3,
        imported_at="2026-07-20T22:00:00+00:00",
    )

    assert row["subject_player_id"] == "101"
    assert row["subject_player_name"] == "Ada Active"
    assert row["subject_team_code"] == "CHI"
    assert row["opposing_team_code"] == "CAR"
    assert row["effective_date"] == "2026-07-20"
    assert row["source_date"] == "2026-07-20"
    assert row["source_game_id"] == 9001
    assert row["source_pdf"] == "9001.pdf"
    assert row["source_page"] == 3
    assert row["parser_version"]
    assert len(row["normalized_hash"]) == 64
    assert row["verification_state"] == "VERIFY"
    assert row["needs_review"] is True


def test_duplicate_official_notes_prefer_newest_verified_and_keep_source_history(load_fixture):
    rows = load_fixture("official_game_notes_phase4.json")["duplicate_rows"]

    result = ausl_data._deduplicate_official_game_notes(pd.DataFrame(rows))

    assert len(result) == 1
    kept = result.iloc[0]
    assert kept["game_id"] == 9001
    assert kept["verification_state"] == "VERIFIED"
    assert len(kept["normalized_hash"]) == 64
    history = json.loads(kept["source_history"])
    assert [item["source_pdf"] for item in history] == ["older.pdf", "newer.pdf"]
    assert [item["source_page"] for item in history] == [3, 5]


def test_same_text_for_different_subjects_is_not_deduplicated():
    rows = pd.DataFrame(
        [
            {
                "note_text": "Needs two hits to reach 50 AUSL career hits.",
                "subject_player_id": player_id,
                "subject_team_code": team_code,
                "source_pdf": f"{player_id}.pdf",
                "source_page": 1,
                "source_date": "2026-07-20",
                "verification_state": "VERIFIED",
            }
            for player_id, team_code in (("101", "CHI"), ("202", "CAR"))
        ]
    )

    result = ausl_data._deduplicate_official_game_notes(rows)

    assert len(result) == 2
