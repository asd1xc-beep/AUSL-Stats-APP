from __future__ import annotations

import pandas as pd

import ausl_stats_app


def _app_for_game(load_fixture):
    schedule = pd.DataFrame(load_fixture("selected_games.json")["official_games"])
    selected = ausl_stats_app.official_selected_games(schedule)[0]
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = selected
    app.db = {
        "official_game_notes": pd.DataFrame(
            load_fixture("official_game_note_selection.json")["rows"]
        )
    }
    return app


def test_official_note_selection_requires_exact_game_id_and_balances_verified_teams(load_fixture):
    app = _app_for_game(load_fixture)

    notes = app._select_official_game_notes(
        "Chicago Bandits", "Carolina Blaze", limit=3
    )

    assert [note.category for note in notes] == [
        "availability",
        "probable_starter",
        "season_context",
    ]
    assert {note.subject_team_code for note in notes} == {"CHI", "CAR"}
    assert all(note.game_id == "9001" for note in notes)
    assert not any("Wrong repeat-opponent" in note.text for note in notes)


def test_official_note_selection_deduplicates_repeated_pdfs_before_display(load_fixture):
    app = _app_for_game(load_fixture)

    lines = app._official_game_note_lines("Chicago Bandits", "Carolina Blaze")

    assert sum(".325 average" in line for line in lines) == 1


def test_official_note_lines_show_verification_freshness_and_exact_source(load_fixture):
    app = _app_for_game(load_fixture)

    air_ready_lines = app._official_game_note_lines(
        "Chicago Bandits", "Carolina Blaze", limit=5
    )
    review_lines = app._official_game_note_review_lines(
        "Chicago Bandits", "Carolina Blaze", limit=5
    )
    output = "\n".join(air_ready_lines + review_lines)

    assert "[VERIFIED]" in output
    assert "[VERIFY]" in output
    assert "Source: 2026-07-20 | game-9001.pdf | Game 9001 | page 2" in output
    assert "Cara Blaze played college softball" in output
    assert "page unavailable" in output
    assert not any("Cara Blaze played college softball" in line for line in air_ready_lines)


def test_missing_exact_selected_game_fails_closed(load_fixture):
    app = _app_for_game(load_fixture)
    app.selected_game = None

    assert app._select_official_game_notes("Chicago Bandits", "Carolina Blaze") == []
    assert app._official_game_note_lines("Chicago Bandits", "Carolina Blaze") == []


def test_explicit_stale_note_is_labeled_and_kept_out_of_air_ready_copy(load_fixture):
    app = _app_for_game(load_fixture)
    stale = load_fixture("official_game_note_selection.json")["stale_row"]
    app.db["official_game_notes"] = pd.DataFrame([stale])

    notes = app._select_official_game_notes("Chicago Bandits", "Carolina Blaze")
    air_ready = app._official_game_note_lines("Chicago Bandits", "Carolina Blaze")
    review = app._official_game_note_review_lines(
        "Chicago Bandits", "Carolina Blaze"
    )

    assert len(notes) == 1
    assert notes[0].verification_state == "STALE"
    assert notes[0].air_ready is False
    assert not any("older verified update" in line for line in air_ready)
    assert len(review) == 1
    assert "[STALE]" in review[0]
    assert "2026-07-18 | game-9001.pdf | Game 9001 | page 2" in review[0]
