from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeText:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, text):
        self.value = text


def selected_game(game_id: str):
    return ausl_stats_app.SelectedGame(
        game_id=game_id,
        season=2026,
        date_time=datetime(2026, 7, 20, 19, 0, tzinfo=ZoneInfo("America/New_York")),
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        away_team_code="CHI",
        home_team_code="CAR",
        time_zone="EDT",
        venue="Fixture Stadium",
        status="Scheduled",
        source_updated_at="2026-07-19T12:00:00+00:00",
        source_name="Official AUSL Schedule",
    )


def exact_lock(game_id: str, marker: str):
    return {
        "game_id": game_id,
        "date_time": "2026-07-20T19:00:00-04:00",
        "away_team": "Chicago Bandits",
        "home_team": "Carolina Blaze",
        "venue": "Fixture Stadium",
        "locked_at": "2026-07-19T15:00:00+00:00",
        "source": "manual",
        "revision": 1,
        "lineups": {
            "away": {"starting_pitcher": marker, "lineup": []},
            "home": {"starting_pitcher": f"{marker} home", "lineup": []},
        },
    }


def test_repeat_matchup_locks_are_isolated_by_authoritative_game_id():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.locked_lineups = {
        "schema_version": 2,
        "games": {
            "9001": exact_lock("9001", "Game One Starter"),
            "9002": exact_lock("9002", "Game Two Starter"),
        },
        "legacy_unassigned": [],
    }

    app.selected_game = selected_game("9001")
    assert app.lineup_key() == "9001"
    assert app.current_locked_lineups()["away"]["starting_pitcher"] == "Game One Starter"

    app.selected_game = selected_game("9002")
    assert app.lineup_key() == "9002"
    assert app.current_locked_lineups()["away"]["starting_pitcher"] == "Game Two Starter"


def test_legacy_matchup_lock_is_backed_up_and_left_unassigned(load_fixture, tmp_path):
    path = tmp_path / "locked_lineups.json"
    legacy = load_fixture("legacy_lineup_locks.json")
    original = json.dumps(legacy, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)

    migrated, backup_path = ausl_data.migrate_locked_lineups_file(path)

    assert backup_path is not None
    assert Path(backup_path).read_bytes() == original
    assert migrated["schema_version"] == 2
    assert migrated["games"] == {}
    assert len(migrated["legacy_unassigned"]) == 1
    retained = migrated["legacy_unassigned"][0]
    assert retained["status"] == "legacy_unassigned"
    assert retained["legacy_key"] == "CHI_at_CAR"
    assert retained["payload"] == legacy["CHI_at_CAR"]
    assert json.loads(path.read_text(encoding="utf-8")) == migrated


def test_current_exact_game_store_is_not_rewritten_or_backed_up(tmp_path):
    path = tmp_path / "locked_lineups.json"
    current = {
        "schema_version": 2,
        "games": {"9001": exact_lock("9001", "Current Starter")},
        "legacy_unassigned": [],
    }
    original = json.dumps(current, indent=4).encode("utf-8")
    path.write_bytes(original)

    loaded, backup_path = ausl_data.migrate_locked_lineups_file(path)

    assert backup_path is None
    assert loaded == current
    assert path.read_bytes() == original


def test_atomic_lineup_write_preserves_original_when_replace_fails(monkeypatch, tmp_path):
    path = tmp_path / "locked_lineups.json"
    path.write_bytes(b'{"original":true}\n')

    def fail_replace(*_args, **_kwargs):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(ausl_data.os, "replace", fail_replace)

    with pytest.raises(OSError, match="fixture replace failure"):
        ausl_data.write_locked_lineups_atomic(
            path,
            {"schema_version": 2, "games": {}, "legacy_unassigned": []},
        )

    assert path.read_bytes() == b'{"original":true}\n'
    assert not list(tmp_path.glob("*.tmp"))


def test_unreadable_lineup_store_is_never_replaced_or_migrated(tmp_path):
    path = tmp_path / "locked_lineups.json"
    original = b'{"CHI_at_CAR": invalid-json}\n'
    path.write_bytes(original)

    with pytest.raises(ValueError, match="left unchanged"):
        ausl_data.migrate_locked_lineups_file(path)

    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.backup-*"))


def test_app_refuses_to_save_after_a_lineup_store_load_error():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app._lineup_store_error = "Lineup locks unavailable; original left unchanged."

    with pytest.raises(RuntimeError, match="original left unchanged"):
        app.save_locked_lineups()


def test_legacy_unassigned_warning_survives_selected_game_reset(tmp_path):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app._lineup_store_error = ""
    app._lineup_store_backup = tmp_path / "locked_lineups.json.backup-fixture"
    app.locked_lineups = {
        "schema_version": 2,
        "games": {},
        "legacy_unassigned": [{"status": "legacy_unassigned"}],
    }
    app.lineup_widgets = {}
    app.lineup_lock_status = FakeVar()

    app._reset_lineup_editor_for_game(selected_game("9002"))

    rendered = app.lineup_lock_status.get()
    assert "Game 9002" in rendered
    assert "NOT ATTACHED" in rendered
    assert "backup-fixture" in rendered


def test_stale_editor_context_cannot_save_under_new_selected_game():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame()}
    app.selected_game = selected_game("9002")
    app._lineup_editor_game_id = "9001"
    app.locked_lineups = {
        "schema_version": 2,
        "games": {},
        "legacy_unassigned": [],
    }
    app.lineup_lock_status = FakeVar()
    app.lineup_widgets = {
        side: {
            "starter": FakeVar("Stale Starter"),
            "text": FakeText("1. Stale Player - P"),
            "status": FakeVar(),
        }
        for side in ("away", "home")
    }
    saved = []
    app.save_locked_lineups = lambda *_args: saved.append(True)
    app.render_producer_prep = lambda: None

    app.lock_lineups_from_editor()

    assert saved == []
    assert app.locked_lineups["games"] == {}
    assert "Game 9001" in app.lineup_lock_status.get()
    assert "Game 9002" in app.lineup_lock_status.get()


def test_saved_lock_contains_exact_game_metadata_revision_and_nested_lineups():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame()}
    app.selected_game = selected_game("9002")
    app._lineup_editor_game_id = "9002"
    app._lineup_editor_source = "manual"
    app.locked_lineups = {
        "schema_version": 2,
        "games": {"9002": exact_lock("9002", "Prior Starter")},
        "legacy_unassigned": [],
    }
    app.lineup_lock_status = FakeVar()
    app.lineup_widgets = {
        side: {
            "starter": FakeVar(f"{side.title()} Starter"),
            "text": FakeText(f"1. {side.title()} Batter - P"),
            "status": FakeVar(),
        }
        for side in ("away", "home")
    }
    saved = []
    app.save_locked_lineups = lambda *_args: saved.append(True)
    app.render_producer_prep = lambda: None
    app._validate_lineup_editor_side = lambda side, _team: (
        ausl_stats_app.LineupValidationResult(
            normalized_lineup=[
                {
                    "batting_order": order,
                    "player_id": f"{side}-{order}",
                    "player_name": f"{side.title()} Batter {order}",
                    "jersey_number": str(order),
                    "position": "OF",
                    "roster_status": "Active",
                    "raw_line": "",
                    "line_number": order,
                }
                for order in range(1, 10)
            ],
            starting_pitcher={
                "player_id": f"{side}-starter",
                "player_name": f"{side.title()} Starter",
            },
        )
    )

    app.lock_lineups_from_editor()

    assert saved == [True]
    locked = app.locked_lineups["games"]["9002"]
    assert locked["game_id"] == "9002"
    assert locked["date_time"] == "2026-07-20T19:00:00-04:00"
    assert locked["away_team"] == "Chicago Bandits"
    assert locked["home_team"] == "Carolina Blaze"
    assert locked["venue"] == "Fixture Stadium"
    assert locked["source"] == "manual"
    assert locked["revision"] == 2
    assert set(locked["lineups"]) == {"away", "home"}
    assert locked["lineups"]["away"]["starting_pitcher"] == "Away Starter"


def test_dp_flex_survives_saved_editor_reload_and_revalidation(load_fixture):
    fixture = load_fixture("lineup_validation.json")
    roster = pd.DataFrame(fixture["roster"])
    first = ausl_stats_app.validate_lineup_text(
        fixture["valid_lineup"],
        roster=roster,
        team="Chicago Bandits",
        starter="Chi Pitch",
    )
    stored_flex = {
        **first.flex,
        "source": "manual",
        "source_timestamp": "2026-07-20T16:00:00+00:00",
        "warnings": [],
    }
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": roster}
    app.selected_game = selected_game("9002")
    app.away_var = FakeVar("Chicago Bandits")
    app.home_var = FakeVar("Carolina Blaze")
    app._lineup_store_error = ""
    app.locked_lineups = {
        "schema_version": 2,
        "games": {
            "9002": {
                **exact_lock("9002", "Chi Pitch"),
                "locked_at": "2026-07-20T16:00:00+00:00",
                "lineups": {
                    "away": {
                        "starting_pitcher": "Chi Pitch",
                        "lineup": first.normalized_lineup,
                        "flex": stored_flex,
                    },
                    "home": {"starting_pitcher": "", "lineup": [], "flex": None},
                },
            }
        },
        "legacy_unassigned": [],
    }
    app.lineup_widgets = {
        side: {
            "starter": FakeVar(),
            "text": FakeText(),
            "status": FakeVar(),
        }
        for side in ("away", "home")
    }
    app.lineup_lock_status = FakeVar()
    app._projected_pitchers = lambda *_args: []
    app.projected_lineup_entries = lambda _team: []

    app.load_projected_lineups_into_editor()
    reloaded_text = app.lineup_widgets["away"]["text"].value
    second = ausl_stats_app.validate_lineup_text(
        reloaded_text,
        roster=roster,
        team="Chicago Bandits",
        starter=app.lineup_widgets["away"]["starter"].get(),
    )

    assert reloaded_text.count("Chi Flex") == 1
    assert "FLEX." in reloaded_text
    assert second.errors == []
    for key in ("player_id", "player_name", "jersey_number", "position", "roster_status"):
        assert second.flex[key] == stored_flex[key]

    home_result = ausl_stats_app.LineupValidationResult(
        normalized_lineup=[
            {
                "batting_order": order,
                "player_id": f"CAR-{order}",
                "player_name": f"Car Player {order}",
                "jersey_number": str(order),
                "position": "OF",
                "roster_status": "Active",
            }
            for order in range(1, 10)
        ],
        starting_pitcher={
            "player_id": "CAR-P",
            "player_name": "Car Pitch",
            "position": "P",
        },
    )
    app._validate_lineup_editor_side = lambda side, _team: (
        second if side == "away" else home_result
    )
    saved_candidates = []
    app.save_locked_lineups = lambda candidate: saved_candidates.append(candidate)
    app.render_producer_prep = lambda: None

    app.lock_lineups_from_editor()

    assert len(saved_candidates) == 1
    resaved_flex = app.locked_lineups["games"]["9002"]["lineups"]["away"]["flex"]
    for key in (
        "player_id",
        "player_name",
        "jersey_number",
        "position",
        "roster_status",
        "source",
        "source_timestamp",
        "warnings",
    ):
        assert resaved_flex[key] == stored_flex[key]


def test_lineup_save_failure_keeps_previous_memory_and_reports_error(monkeypatch):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame()}
    app.selected_game = selected_game("9002")
    app._lineup_editor_game_id = "9002"
    app._lineup_editor_source = "manual"
    app._lineup_editor_loaded_at = datetime.fromisoformat(
        "2026-07-20T16:00:00+00:00"
    )
    app._lineup_store_error = ""
    previous = exact_lock("9002", "Prior Starter")
    app.locked_lineups = {
        "schema_version": 2,
        "games": {"9002": previous},
        "legacy_unassigned": [],
    }
    app.lineup_lock_status = FakeVar()
    app.lineup_widgets = {
        side: {
            "starter": FakeVar("Fixture Starter"),
            "text": FakeText(),
            "status": FakeVar(),
        }
        for side in ("away", "home")
    }
    valid = ausl_stats_app.LineupValidationResult(
        normalized_lineup=[
            {
                "batting_order": order,
                "player_id": f"P-{order}",
                "player_name": f"Player {order}",
                "jersey_number": str(order),
                "position": "OF",
                "roster_status": "Active",
            }
            for order in range(1, 10)
        ],
        starting_pitcher={
            "player_id": "P-SP",
            "player_name": "Fixture Starter",
            "position": "P",
        },
    )
    app._validate_lineup_editor_side = lambda *_args: valid
    app.render_producer_prep = lambda: None
    app.save_locked_lineups = lambda *_args: (_ for _ in ()).throw(
        OSError("fixture disk full")
    )

    app.lock_lineups_from_editor()

    assert app.locked_lineups["games"]["9002"] is previous
    assert "not saved" in app.lineup_lock_status.get().lower()
    assert "fixture disk full" in app.lineup_lock_status.get()


def test_lineup_delete_failure_keeps_previous_memory_and_reports_error():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = selected_game("9002")
    app._lineup_store_error = ""
    previous = exact_lock("9002", "Prior Starter")
    app.locked_lineups = {
        "schema_version": 2,
        "games": {"9002": previous},
        "legacy_unassigned": [],
    }
    app.lineup_lock_status = FakeVar()
    app.lineup_widgets = {
        side: {"status": FakeVar()} for side in ("away", "home")
    }
    app.render_producer_prep = lambda: None
    app.save_locked_lineups = lambda *_args: (_ for _ in ()).throw(
        PermissionError("fixture read only")
    )

    app.clear_locked_lineups()

    assert app.locked_lineups["games"]["9002"] is previous
    assert "not cleared" in app.lineup_lock_status.get().lower()
    assert "fixture read only" in app.lineup_lock_status.get()
