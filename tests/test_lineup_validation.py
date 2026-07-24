from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

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


def validate(fixture, text, **overrides):
    kwargs = {
        "roster": pd.DataFrame(fixture["roster"]),
        "team": "Chicago Bandits",
        "starter": "Chi Pitch",
        "source": "manual",
        "game_time": datetime(2026, 7, 20, 19, 0, tzinfo=ZoneInfo("America/New_York")),
        "lineup_timestamp": datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("America/New_York")),
    }
    kwargs.update(overrides)
    return ausl_stats_app.validate_lineup_text(text, **kwargs)


def issue_codes(issues):
    return {issue.code for issue in issues}


def test_valid_dp_flex_lineup_has_nine_hitters_and_separate_flex(load_fixture):
    fixture = load_fixture("lineup_validation.json")

    result = validate(fixture, fixture["valid_lineup"])

    assert result.errors == []
    assert result.warnings == []
    assert [entry["batting_order"] for entry in result.normalized_lineup] == list(range(1, 10))
    assert result.flex["player_id"] == "CHI-F"
    assert result.flex["batting_order"] is None
    assert result.starting_pitcher["player_id"] == "CHI-P"


@pytest.mark.parametrize(
    ("case_name", "expected_code"),
    [
        ("duplicate_order", "batting_order"),
        ("duplicate_player", "duplicate_player"),
        ("unresolved", "unresolved_player"),
        ("ambiguous", "ambiguous_player"),
        ("wrong_team", "wrong_team"),
        ("bad_position", "invalid_position"),
        ("malformed_flex", "malformed_dp_flex"),
    ],
)
def test_blocking_lineup_fixtures_fail_closed(load_fixture, case_name, expected_code):
    fixture = load_fixture("lineup_validation.json")

    result = validate(fixture, fixture["cases"][case_name])

    assert expected_code in issue_codes(result.errors)
    assert any(issue.line_number is not None for issue in result.errors)


def test_missing_starter_is_a_blocking_error(load_fixture):
    fixture = load_fixture("lineup_validation.json")

    result = validate(fixture, fixture["valid_lineup"], starter="")

    assert "missing_starter" in issue_codes(result.errors)


@pytest.mark.parametrize("starter", ["Chi One", "Chi Three", "Chi Two", "Chi Missing"])
def test_nonpitcher_or_unknown_position_starter_is_blocked(load_fixture, starter):
    fixture = load_fixture("lineup_validation.json")

    result = validate(fixture, fixture["valid_lineup"], starter=starter)

    assert "starter_position" in issue_codes(result.errors)
    assert result.starting_pitcher["position"] in {"OF", "C", "IF", ""}


@pytest.mark.parametrize("position", ["P", "RHP", "LHP"])
def test_supported_pitcher_positions_pass_and_are_not_overwritten(
    load_fixture, position
):
    fixture = load_fixture("lineup_validation.json")
    roster = pd.DataFrame(fixture["roster"])
    roster.loc[roster["player_id"].eq("CHI-P"), "position"] = position

    result = validate(
        fixture,
        fixture["valid_lineup"],
        roster=roster,
        starter="Chi Pitch",
    )

    assert "starter_position" not in issue_codes(result.errors)
    assert result.starting_pitcher["position"] == position


def test_reviewed_two_way_exception_retains_real_position_and_provenance(load_fixture):
    fixture = load_fixture("lineup_validation.json")
    approval = {
        "player_id": "CHI-1",
        "reviewer": "Fixture Producer",
        "approved_at": "2026-07-20T16:00:00+00:00",
        "source": "official two-way designation",
    }

    result = validate(
        fixture,
        fixture["valid_lineup"],
        starter="Chi One",
        starter_position_exception=approval,
    )

    assert "starter_position" not in issue_codes(result.errors)
    assert "two_way_starter_exception" in issue_codes(result.warnings)
    assert result.starting_pitcher["position"] == "OF"
    assert result.starting_pitcher["position_exception"] == approval


def test_inactive_and_missing_identity_fields_require_confirmation(load_fixture):
    fixture = load_fixture("lineup_validation.json")

    inactive = validate(fixture, fixture["cases"]["inactive_warning"])
    missing = validate(fixture, fixture["cases"]["missing_fields_warning"])

    assert "roster_status" in issue_codes(inactive.warnings)
    assert {"roster_status", "missing_jersey", "missing_position"}.issubset(
        issue_codes(missing.warnings)
    )


def test_projected_and_old_lineups_require_confirmation(load_fixture):
    fixture = load_fixture("lineup_validation.json")

    result = validate(
        fixture,
        fixture["valid_lineup"],
        source="projected",
        lineup_timestamp=datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert {"projected_source", "stale_lineup"}.issubset(issue_codes(result.warnings))


def validation_app():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {"roster": pd.DataFrame([{"player_name": "Fixture"}])}
    app.selected_game = ausl_stats_app.SelectedGame(
        game_id="9002",
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
    app._lineup_editor_game_id = "9002"
    app._lineup_editor_source = "manual"
    app._lineup_editor_loaded_at = datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("America/New_York"))
    app._lineup_store_error = ""
    app.locked_lineups = {"schema_version": 2, "games": {}, "legacy_unassigned": []}
    app.lineup_lock_status = FakeVar()
    app.lineup_widgets = {
        side: {
            "starter": FakeVar("Fixture Starter"),
            "text": FakeText("1. Fixture - CF"),
            "status": FakeVar(),
        }
        for side in ("away", "home")
    }
    app.render_producer_prep = lambda: None
    return app


def test_lock_button_blocks_structured_errors_inline(monkeypatch):
    app = validation_app()
    saved = []
    app.save_locked_lineups = lambda *_args: saved.append(True)
    blocking = ausl_stats_app.LineupValidationResult(
        errors=[
            ausl_stats_app.LineupIssue(
                "wrong_team", "Fixture Player is assigned to another team.", 3
            )
        ]
    )
    monkeypatch.setattr(ausl_stats_app, "validate_lineup_text", lambda *_a, **_k: blocking)

    app.lock_lineups_from_editor()

    assert saved == []
    assert app.locked_lineups["games"] == {}
    assert "Line 3" in app.lineup_widgets["away"]["status"].get()
    assert "not locked" in app.lineup_lock_status.get().lower()


def test_lock_button_requires_confirmation_for_warnings(monkeypatch):
    app = validation_app()
    saved = []
    app.save_locked_lineups = lambda *_args: saved.append(True)
    warning = ausl_stats_app.LineupValidationResult(
        warnings=[
            ausl_stats_app.LineupIssue(
                "roster_status", "Fixture Player roster status is Inactive.", 4
            )
        ],
        normalized_lineup=[
            {
                "batting_order": order,
                "player_id": f"P-{order}",
                "player_name": f"Player {order}",
                "jersey_number": str(order),
                "position": "OF",
                "roster_status": "Active",
                "raw_line": "",
                "line_number": order,
            }
            for order in range(1, 10)
        ],
        starting_pitcher={"player_id": "P-SP", "player_name": "Fixture Starter"},
    )
    monkeypatch.setattr(ausl_stats_app, "validate_lineup_text", lambda *_a, **_k: warning)
    confirmations = []
    monkeypatch.setattr(
        ausl_stats_app.messagebox,
        "askyesno",
        lambda *_a, **_k: confirmations.append(True) or False,
    )

    app.lock_lineups_from_editor()

    assert confirmations == [True]
    assert saved == []
    assert app.locked_lineups["games"] == {}
    assert "not locked" in app.lineup_lock_status.get().lower()


def test_confirmed_warnings_are_recorded_with_the_saved_lock(monkeypatch):
    app = validation_app()
    app._lineup_editor_source = "projected"
    saved = []
    app.save_locked_lineups = lambda *_args: saved.append(True)
    warning = ausl_stats_app.LineupValidationResult(
        warnings=[
            ausl_stats_app.LineupIssue(
                "projected_source", "This lineup is projected, not official.", None
            )
        ],
        normalized_lineup=[
            {
                "batting_order": order,
                "player_id": f"P-{order}",
                "player_name": f"Player {order}",
                "jersey_number": str(order),
                "position": "OF",
                "roster_status": "Active",
                "raw_line": "",
                "line_number": order,
            }
            for order in range(1, 10)
        ],
        starting_pitcher={"player_id": "P-SP", "player_name": "Fixture Starter"},
    )
    monkeypatch.setattr(ausl_stats_app, "validate_lineup_text", lambda *_a, **_k: warning)
    monkeypatch.setattr(ausl_stats_app.messagebox, "askyesno", lambda *_a, **_k: True)

    app.lock_lineups_from_editor()

    assert saved == [True]
    locked = app.locked_lineups["games"]["9002"]
    assert locked["source"] == "projected"
    assert locked["validation"]["warnings"]
    assert locked["validation"]["warnings_confirmed_at"]
    assert app._lineup_broadcast_status() == "SAVED PROJECTION — NOT OFFICIAL"
