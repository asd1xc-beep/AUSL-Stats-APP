from __future__ import annotations

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


COPY_KINDS = (
    "player_id",
    "season_stat",
    "career_stat",
    "announcer_note",
    "lower",
    "full",
    "note",
    "jersey",
)


def status_normalizer():
    assert hasattr(ausl_data, "normalize_roster_status"), (
        "Phase 1 requires ausl_data.normalize_roster_status"
    )
    return ausl_data.normalize_roster_status


@pytest.mark.parametrize("raw", [None, "", "   ", float("nan"), "—", "nan"])
def test_missing_roster_status_is_unknown_not_active(raw):
    assert status_normalizer()(raw) == "Status unknown"


@pytest.mark.parametrize("raw", ["Active", "Inactive", "Reserve Athlete Pool"])
def test_official_nonblank_roster_status_is_preserved(raw):
    assert status_normalizer()(raw) == raw


def make_app(fixture_database):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = fixture_database
    app.selected_player_id = None
    app.current_broadcast_note = "Fixture narrative; verify before air."
    app.data_freshness_text = "Data updated: July 18, 2026 at 11:45 PM UTC - VERIFY"
    return app


@pytest.mark.parametrize("kind", COPY_KINDS)
def test_every_roster_player_can_generate_every_copy_type_without_nan(
    fixture_database,
    kind,
):
    app = make_app(fixture_database)

    for player_id in fixture_database["roster"]["player_id"]:
        app.selected_player_id = int(player_id)
        rendered = app.gfx_text(kind)
        assert rendered
        assert "nan" not in rendered.lower()


@pytest.mark.parametrize("player_id", [102, 103, 104])
@pytest.mark.parametrize("kind", COPY_KINDS)
def test_nonactive_or_unknown_copy_is_unmistakably_labeled(
    fixture_database,
    player_id,
    kind,
):
    app = make_app(fixture_database)
    app.selected_player_id = player_id

    rendered = app.gfx_text(kind).upper()

    assert "VERIFY" in rendered
    if player_id == 102:
        assert "INACTIVE" in rendered
    elif player_id == 103:
        assert "RESERVE" in rendered or "RAP" in rendered
    else:
        assert "STATUS UNKNOWN" in rendered


def test_missing_team_has_a_safe_label_in_player_id_copy(fixture_database):
    app = make_app(fixture_database)
    app.selected_player_id = 106

    rendered = app.gfx_text("jersey").upper()

    assert "TEAM UNKNOWN" in rendered
    assert "NAN" not in rendered


def test_projected_lineup_contains_active_players_only(fixture_database):
    app = make_app(fixture_database)

    projected = app._projected_lineup("Chicago Bandits", 2026)
    ids = {int(item["player"]["player_id"]) for item in projected}

    assert ids
    assert ids <= {101, 105}


def test_projected_pitchers_contain_active_players_only(fixture_database):
    app = make_app(fixture_database)

    projected = app._projected_pitchers("Chicago Bandits", 2026)
    ids = {int(item[3]["player_id"]) for item in projected}

    assert ids == {105}


def test_players_to_watch_contain_active_players_only(fixture_database):
    app = make_app(fixture_database)

    watched = app._players_to_watch("Chicago Bandits", 2026)
    ids = {int(item[0]["player_id"]) for item in watched}

    assert ids
    assert ids <= {101, 105}


def test_milestone_watch_excludes_nonactive_players(fixture_database):
    app = make_app(fixture_database)

    lines = app._milestone_watch("Chicago Bandits", 2026)
    rendered = "\n".join(lines).upper()

    assert "RAE RESERVE" not in rendered
    assert "IVY INACTIVE" not in rendered
    assert "UMA UNKNOWN" not in rendered


def test_availability_impact_is_separate_and_freshness_labeled(fixture_database):
    app = make_app(fixture_database)

    lines = app._availability_impact("Chicago Bandits")
    rendered = "\n".join(lines).upper()

    assert "ADA ACTIVE" not in rendered
    assert "IVY INACTIVE" in rendered
    assert "INACTIVE" in rendered
    assert "RAE RESERVE" in rendered
    assert "RESERVE" in rendered
    assert "UMA UNKNOWN" in rendered
    assert "STATUS UNKNOWN" in rendered
    assert "DATA UPDATED" in rendered


def test_legacy_copy_aliases_match_their_explicit_semantics(fixture_database):
    app = make_app(fixture_database)
    app.selected_player_id = 101

    assert app.gfx_text("jersey") == app.gfx_text("player_id")
    assert app.gfx_text("lower") == app.gfx_text("season_stat")
    assert app.gfx_text("full") == app.gfx_text("career_stat")
    assert app.gfx_text("note") == app.gfx_text("announcer_note")


def test_dp_position_uses_batting_not_pitching_copy_semantics(fixture_database):
    fixture_database["roster"] = pd.DataFrame(
        [
            {
                "player_id": 999,
                "player_name": "Dee Player",
                "team": "Chicago Bandits",
                "team_code": "CHI",
                "jersey_number": 8,
                "position": "DP",
                "roster_status": "Active",
            }
        ]
    )
    fixture_database["batting_2026"] = pd.DataFrame(
        [
            {
                "player_id": 999,
                "gamesPlayed": 2,
                "plateAppearances": 5,
                "hits": 2,
                "homeRuns": 0,
                "runsBattedIn": 1,
                "battingAverage": 0.400,
                "onBasePercentage": 0.400,
                "sluggingPercentage": 0.400,
                "opsPercentage": 0.800,
            }
        ]
    )
    fixture_database["pitching_2026"] = pd.DataFrame(
        [{"player_id": 999, "appearances": 1, "earnedRunAverage": 9.99}]
    )
    app = make_app(fixture_database)
    app.selected_player_id = 999

    rendered = app.gfx_text("season_stat")

    assert "AVG" in rendered
    assert "9.99 ERA" not in rendered


def test_teamless_reserve_is_listed_only_as_unassigned_availability_impact(
    fixture_database,
):
    reserve = fixture_database["roster"].iloc[0].copy()
    reserve["player_id"] = 777
    reserve["player_name"] = "Riley Reserve"
    reserve["team"] = None
    reserve["team_code"] = None
    reserve["roster_status"] = "Reserve Pool"
    fixture_database["roster"] = pd.concat(
        [fixture_database["roster"], reserve.to_frame().T], ignore_index=True
    )
    app = make_app(fixture_database)

    team_lines = "\n".join(app._availability_impact("Chicago Bandits")).upper()
    unassigned_lines = "\n".join(app._unassigned_availability_impact()).upper()

    assert "RILEY RESERVE" not in team_lines
    assert "RILEY RESERVE" in unassigned_lines
    assert "TEAM UNKNOWN" in unassigned_lines
    assert "RESERVE POOL" in unassigned_lines
    assert "DATA UPDATED" in unassigned_lines


def test_teamless_reserve_ui_identity_never_renders_nan():
    row = pd.Series(
        {
            "player_id": 777,
            "player_name": "Riley Reserve",
            "team": float("nan"),
            "team_code": float("nan"),
            "jersey_number": float("nan"),
            "position": "IF",
            "roster_status": "Reserve Pool",
        }
    )

    list_text = ausl_stats_app.AUSLStatsApp.roster_list_text(row)
    title_text = ausl_stats_app.AUSLStatsApp.player_title_text(row)

    assert "nan" not in list_text.lower()
    assert "nan" not in title_text.lower()
    assert "TEAM UNKNOWN" in list_text
    assert "TEAM UNKNOWN" in title_text
    assert "NUMBER UNAVAILABLE" in title_text
    assert "Reserve Pool" in list_text


def test_player_meta_uses_status_unknown_instead_of_a_missing_marker():
    row = pd.Series(
        {
            "roster_status": None,
            "bats_throws": "R/R",
            "college": "Fixture U",
            "hometown": "Example, USA",
            "height": "5-8",
        }
    )

    rendered = ausl_stats_app.AUSLStatsApp.player_meta_text(row)

    assert "Status: Status unknown" in rendered
    assert "Status: —" not in rendered
