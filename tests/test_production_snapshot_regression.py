from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


EXPECTED_2026_RECORDS = {
    "CHI": (16, 9),
    "UTA": (16, 9),
    "PDX": (14, 11),
    "OKC": (13, 12),
    "CAR": (9, 16),
    "TEX": (7, 18),
}
EXPECTED_SNAPSHOT_UPDATED_AT = "2026-07-23T18:08:06.854069+00:00"
COPY_KINDS = (
    "player_id",
    "season_stat",
    "career_stat",
    "announcer_note",
    "jersey",
    "lower",
    "full",
    "note",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PITCHING_AUDIT_COLUMNS = {
    "innings_available",
    "innings_invalid_count",
    "innings_source_values",
    "era_inputs_available",
    "era_input_invalid_count",
    "whip_inputs_available",
    "whip_input_invalid_count",
}


@pytest.fixture
def production_snapshot(monkeypatch):
    """Load only the checked-in July 23 snapshot; never touch local notes or the web."""

    monkeypatch.setattr(ausl_data, "load_manual_notes", lambda: pd.DataFrame())
    database = ausl_data.load_database()
    assert database["manifest"]["updated_at"] == EXPECTED_SNAPSHOT_UPDATED_AT
    return database


def make_app(database):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = database
    app.selected_player_id = None
    app.current_broadcast_note = "Local snapshot narrative; verify before air."
    app.data_freshness_text = ausl_stats_app.AUSLStatsApp.format_data_freshness(
        database["manifest"]
    )
    return app


def test_local_official_snapshot_has_expected_six_team_records(production_snapshot):
    for team_code, (wins, losses) in EXPECTED_2026_RECORDS.items():
        snapshot = ausl_stats_app.official_team_snapshot(
            team_code, 2026, production_snapshot
        )
        assert snapshot.available
        assert (snapshot.wins, snapshot.losses) == (wins, losses)
        assert snapshot.record_text == f"{wins}-{losses}"
        assert snapshot.source_url == "https://theausl.com/standings/"
        assert snapshot.source_timestamp


@pytest.mark.parametrize("kind", COPY_KINDS)
def test_every_local_roster_player_copy_sweep_is_safe(production_snapshot, kind):
    app = make_app(production_snapshot)

    for _, player in production_snapshot["roster"].iterrows():
        app.selected_player_id = int(player["player_id"])
        text = app.gfx_text(kind)
        assert text, f"empty {kind} output for player_id={player['player_id']}"
        assert "nan" not in text.lower(), (
            f"unsafe {kind} output for player_id={player['player_id']}: {text!r}"
        )
        status = app.roster_status(player)
        if status.lower() != "active":
            assert "verify" in text.lower()
            assert status.lower() in text.lower()


def test_local_automatic_recommendations_are_active_only(production_snapshot):
    app = make_app(production_snapshot)
    roster = production_snapshot["roster"].set_index("player_id")

    for team in ausl_stats_app.TEAM_TO_CODE:
        lineup = app._projected_lineup(team, 2026)
        pitchers = app._projected_pitchers(team, 2026)
        watched = app._players_to_watch(team, 2026)
        ids = {
            *(int(item["player"]["player_id"]) for item in lineup),
            *(int(item[3]["player_id"]) for item in pitchers),
            *(int(item[0]["player_id"]) for item in watched),
        }
        for player_id in ids:
            assert app.is_active_roster(roster.loc[player_id]), (
                f"nonactive player_id={player_id} recommended for {team}"
            )


def test_local_snapshot_manifest_is_freshly_dated_but_still_requires_verification(
    production_snapshot,
):
    app = make_app(production_snapshot)

    assert "July 23, 2026" in app.data_freshness_text
    assert "VERIFY" in app.data_freshness_text


def test_local_snapshot_preserves_official_reserve_pool_status(production_snapshot):
    roster = production_snapshot["roster"]

    jala_wright = roster.loc[roster["player_id"] == 1308]
    assert len(jala_wright) == 1
    assert jala_wright.iloc[0]["player_name"] == "Jala Wright"
    assert jala_wright.iloc[0]["roster_status"] == "Reserve Pool"
    assert pd.isna(jala_wright.iloc[0]["team_code"])
    assert roster.loc[roster["player_id"] == 1097].empty


def test_local_snapshot_schedule_has_unique_authoritative_game_ids(production_snapshot):
    schedule = production_snapshot["schedule_results"]

    assert len(schedule) == 76
    assert schedule["game_id"].notna().all()
    assert schedule["game_id"].is_unique
    assert schedule["status"].value_counts().to_dict() == {
        "Completed": 75,
        "Postponed": 1,
    }


def test_checked_in_career_pitching_snapshot_is_auditable_and_fail_closed(
    production_snapshot,
):
    pitching = production_snapshot["career_pitching"]

    assert PITCHING_AUDIT_COLUMNS.issubset(pitching.columns)
    assert (pitching["innings_invalid_count"] >= 0).all()
    assert (pitching["era_input_invalid_count"] >= 0).all()
    assert (pitching["whip_input_invalid_count"] >= 0).all()

    unavailable_innings = ~pitching["innings_available"].astype(bool)
    unavailable_era = ~pitching["era_inputs_available"].astype(bool)
    unavailable_whip = ~pitching["whip_inputs_available"].astype(bool)
    assert pitching.loc[unavailable_innings, "inningsPitched"].isna().all()
    assert pitching.loc[unavailable_innings | unavailable_era, "earnedRunAverage"].isna().all()
    assert pitching.loc[unavailable_innings | unavailable_whip, "whip"].isna().all()

    manifest = json.loads(
        (PROJECT_ROOT / "data" / "exports" / "update_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["updated_at"] == EXPECTED_SNAPSHOT_UPDATED_AT
