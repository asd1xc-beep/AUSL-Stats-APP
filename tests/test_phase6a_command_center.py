from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import ausl_stats_app


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.state = "normal"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)


class FakeRoot:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []
        self.destroyed = False

    def after(self, delay, callback):
        timer = f"timer-{len(self.scheduled) + 1}"
        self.scheduled.append((timer, delay, callback))
        return timer

    def after_cancel(self, timer):
        self.cancelled.append(timer)

    def destroy(self):
        self.destroyed = True


class FakeToken:
    def __init__(self):
        self.cancelled = 0

    def cancel(self):
        self.cancelled += 1


def selected_game(game_id="9001", status="Scheduled"):
    return ausl_stats_app.SelectedGame(
        game_id=game_id,
        season=2026,
        date_time=datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc),
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        away_team_code="CHI",
        home_team_code="CAR",
        time_zone="UTC",
        venue="Fixture Stadium",
        status=status,
        source_updated_at="2026-07-20T17:45:00+00:00",
        source_name="Official AUSL Schedule",
    )


def make_app():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.root = FakeRoot()
    app.db = {
        "roster": pd.DataFrame(
            [
                {"player_id": 1, "team_code": "CHI", "team": "Chicago Bandits"},
                {"player_id": 2, "team_code": "CAR", "team": "Carolina Blaze"},
            ]
        ),
        "official_game_notes": pd.DataFrame(),
        "manifest": {
            "updated_at": "2026-07-20T17:45:00+00:00",
            "source_health": {
                "official_rosters": {"status": "green"},
                "official_stats": {"status": "green"},
            },
        },
        "refresh_attempt": {"state": "succeeded"},
        "enrichment_enabled": False,
    }
    app.selected_game = selected_game()
    app.locked_lineups = {
        "schema_version": 2,
        "games": {},
        "legacy_unassigned": [],
    }
    app.live_game = None
    app.live_box = None
    app.live_health = ausl_stats_app.LiveFeedHealth(
        "RED", "DISCONNECTED", None, "", None, "NOT LOADED"
    )
    app._packet_metadata = {}
    app._offline_mode = False
    app.offline_mode_var = FakeVar(False)
    app.auto_var = FakeVar(False)
    app.status_var = FakeVar("")
    app.live_status = FakeVar("")
    app.data_health_var = FakeVar("")
    app.update_button = FakeButton()
    app.cancel_update_button = FakeButton()
    app.live_refresh_button = FakeButton()
    app.cancel_live_button = FakeButton()
    app._initial_load_in_flight = False
    app._data_update_in_flight = False
    app._data_update_cancel_token = None
    app._live_refresh_in_flight = False
    app._live_refresh_cancel_token = None
    app._active_live_request = None
    app._live_timer_id = None
    app._live_request_generation = 0
    return app


def test_missing_optional_verification_data_is_unavailable_not_zero():
    app = make_app()

    assert app._scoped_verification_count() is None


def test_scoped_verification_count_uses_exact_game_and_team_context():
    app = make_app()
    app.db["enrichment_enabled"] = True
    app.db["official_game_notes"] = pd.DataFrame(
        [
            {
                "game_id": "9001",
                "subject_team_code": "CHI",
                "verification_state": "needs_review",
            },
            {
                "game_id": "9001",
                "subject_team_code": "CAR",
                "verification_state": "VERIFIED",
            },
            {
                "game_id": "9002",
                "subject_team_code": "CHI",
                "verification_state": "needs_review",
            },
            {
                "game_id": "9001",
                "subject_team_code": "OKC",
                "verification_state": "needs_review",
            },
        ]
    )

    assert app._scoped_verification_count() == 1


def test_recording_packet_refreshes_only_exact_game_dashboard_state():
    app = make_app()
    refreshed = []
    app.refresh_game_day_dashboard = lambda: refreshed.append(True)
    path = "20260720T175500000000Z_game_9001_r3_producer_packet.txt"

    app._record_packet_generated(
        path,
        generated_at=datetime(2026, 7, 20, 17, 55, tzinfo=timezone.utc),
        game_id="9001",
        lineup_revision=3,
        lineup_source="manual",
    )

    assert app._packet_metadata["game_id"] == "9001"
    assert app._packet_metadata["lineup_revision"] == 3
    assert refreshed == [True]


def test_database_replacement_invalidates_verification_cache_and_refreshes_dashboard():
    app = make_app()
    events = []
    app._verification_count_cache = {("old",): 9}
    app.data_freshness_var = FakeVar()
    app._apply_data_health_display = lambda *_args: None
    app._refresh_manual_note_players = lambda: None
    app.refresh_game_choices = lambda: None
    app._sync_selected_player_after_load = lambda *_args: None
    app.show_all = lambda: None
    app.render_team_totals = lambda: None
    app.render_producer_prep = lambda: None
    app.render_manual_notes = lambda: None
    app.refresh_game_day_dashboard = lambda: events.append("dashboard")
    replacement = dict(app.db)
    replacement["roster"] = app.db["roster"].copy()

    app._finish_load(replacement)

    assert app._verification_count_cache == {}
    assert events == ["dashboard"]


def test_late_abandoned_data_callback_cannot_refresh_dashboard():
    app = make_app()
    events = []
    current = FakeToken()
    stale = FakeToken()
    app._data_update_cancel_token = current
    app.refresh_game_day_dashboard = lambda: events.append("dashboard")

    app._finish_data_update_success({"roster": []}, stale)
    app._finish_data_update_error(RuntimeError("late"), stale)
    app._finish_data_update_cancelled(stale)

    assert events == []
    assert app._data_update_cancel_token is current


def test_game_change_refreshes_dashboard_after_old_context_is_cleared():
    app = make_app()
    old = app.selected_game
    new = selected_game("9002")
    events = []
    app.away_var = FakeVar(old.away_team)
    app.home_var = FakeVar(old.home_team)
    app.game_choice_var = FakeVar()
    app.game_context_var = FakeVar()
    app.note_game_var = FakeVar(old.game_id)
    app.game_id_var = FakeVar(old.game_id)
    app.selected_player_id = None
    app._search_view = None
    app.search = lambda: None
    app.render_producer_prep = lambda: None
    app.render_manual_notes = lambda: None
    app._reset_lineup_editor_for_game = lambda game: events.append(
        ("lineup", game.game_id)
    )
    app._reset_live_for_game = lambda game: events.append(("live", game.game_id))
    app.refresh_game_day_dashboard = lambda: events.append(
        ("dashboard", app.selected_game.game_id)
    )

    app.on_game_changed(new)

    assert app.selected_game.game_id == "9002"
    assert events[-1] == ("dashboard", "9002")
    assert ("lineup", "9002") in events
    assert ("live", "9002") in events


def test_lineup_delete_refreshes_dashboard():
    app = make_app()
    app.locked_lineups["games"]["9001"] = {
        "game_id": "9001",
        "lineups": {},
    }
    app._lineup_store_error = ""
    app.lineup_widgets = {
        "away": {"status": FakeVar()},
        "home": {"status": FakeVar()},
    }
    app.lineup_lock_status = FakeVar()
    app.save_locked_lineups = lambda *_args: None
    app.render_producer_prep = lambda: None
    events = []
    app.refresh_game_day_dashboard = lambda: events.append("dashboard")

    app.clear_locked_lineups()

    assert events == ["dashboard"]
