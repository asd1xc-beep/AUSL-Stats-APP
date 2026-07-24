from __future__ import annotations

import pandas as pd

import ausl_stats_app


def _note(category, text, *, state="VERIFIED", team="CHI", player="Ada Active"):
    return ausl_stats_app.OfficialGameNote(
        game_id="9001",
        category=category,
        text=text,
        subject_player_id="101" if player else "",
        subject_player_name=player,
        subject_team_code=team,
        opposing_team_code="CAR" if team == "CHI" else "CHI",
        verification_state=state,
        source_date="2026-07-20",
        source_pdf="game-9001.pdf",
        source_page="3",
        source_url="https://theausl.com/notes/game-9001.pdf",
        source_history="",
        confidence_score=0.99,
    )


def _prep_app():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame()}
    app.data_freshness_text = "Data updated: fixture"
    app._selected_game_line = lambda *_args: "Selected game: Game ID 9001"
    app._lineup_broadcast_status = lambda: "PROJECTED / NOT OFFICIAL"
    app._why_game_matters = lambda *_args: "Official records make this a one-game standings swing."
    app._team_context_line = lambda team, _year: f"{team}: official fixture standing."
    app._recent_matchup_line = lambda *_args: "Recent matchup: CHI 4 at CAR 3."
    app._select_official_game_notes = lambda *_args, **_kwargs: [
        _note("availability", "Ada Active is inactive tonight with an illness."),
        _note(
            "probable_starter",
            "Cara Blaze was announced as tonight's starting pitcher.",
            team="CAR",
            player="Cara Blaze",
        ),
        _note("season_context", "Ada Active has a .325 average this AUSL season."),
        _note(
            "background",
            "Cara Blaze played college softball at State U.",
            state="VERIFY",
            team="CAR",
            player="Cara Blaze",
        ),
    ]
    app._team_metrics = lambda team, _year: {
        "runs": 40 if team == "Chicago Bandits" else 38,
        "home_runs": 8,
        "rbi": 35,
        "ops": 0.750,
        "era": 3.10,
        "whip": 1.20,
        "strikeouts": 55,
        "offense_available": True,
        "pitching_available": True,
    }
    app._players_to_watch = lambda team, _year: [
        (
            {"player_name": f"{team} Player", "position": "OF"},
            ".300 AVG",
            "Current AUSL season",
        )
    ]
    app.availability_warning = lambda _player: ""
    app._milestone_watch = lambda team, _year: [f"- {team}: milestone fixture."]
    app._availability_impact = lambda team: [
        "Data updated: fixture",
        f"- {team}: no unavailable fixture players.",
    ]
    app._unassigned_availability_impact = lambda: [
        "Data updated: fixture",
        "- No unassigned fixture players.",
    ]
    app._graphic_suggestions = lambda *_args: ["1. Fixture graphic"]
    return app


def test_producer_prep_is_a_sectioned_model_with_expected_sections(load_fixture):
    app = _prep_app()

    prep = app._producer_prep_model(
        "Chicago Bandits", "Carolina Blaze", 2026
    )
    lines = prep.render_lines()

    assert isinstance(prep, ausl_stats_app.ProducerPrep)
    assert all(
        isinstance(storyline, ausl_stats_app.ProducerStoryline)
        for storyline in prep.top_storylines
    )
    for section in load_fixture("producer_prep_phase4.json")["screen_sections"]:
        assert lines.count(section) == 1


def test_top_storylines_are_objects_and_not_repeated_official_note_bullets():
    app = _prep_app()

    prep = app._producer_prep_model(
        "Chicago Bandits", "Carolina Blaze", 2026
    )
    storyline_lines = [item.render() for item in prep.top_storylines]

    assert storyline_lines
    assert not set(storyline_lines) & set(prep.official_notes)
    assert len(storyline_lines) == len(set(storyline_lines))
    assert any("Ada Active is inactive tonight" in line for line in storyline_lines)
    assert not any("Ada Active is inactive tonight" in line for line in prep.official_notes)


def test_screen_and_packet_intro_render_from_the_same_prep_model(load_fixture):
    app = _prep_app()
    prep = app._producer_prep_model(
        "Chicago Bandits", "Carolina Blaze", 2026
    )

    screen = app._producer_prep_lines("Chicago Bandits", "Carolina Blaze", 2026)
    packet = app._producer_packet_prep_lines(prep)

    expected = load_fixture("producer_prep_phase4.json")
    for section in expected["screen_sections"]:
        assert screen.count(section) == 1
    for section in expected["packet_sections"]:
        assert packet.count(section) == 1
    assert prep.section_items("TOP STORYLINES") == tuple(
        packet[
            packet.index("TOP STORYLINES") + 1 : packet.index("OFFICIAL GAME NOTES") - 1
        ]
    )
