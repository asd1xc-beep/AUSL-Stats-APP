from __future__ import annotations

from datetime import datetime, timezone

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


class FakeButton:
    def __init__(self):
        self.state = "normal"

    def configure(self, state=None, **_kwargs):
        if state is not None:
            self.state = state


def bare_app():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.status_var = FakeVar()
    app.live_status = FakeVar()
    app.update_button = FakeButton()
    app.cancel_update_button = FakeButton()
    app.live_refresh_button = FakeButton()
    app.cancel_live_button = FakeButton()
    app._data_update_in_flight = False
    app._initial_load_in_flight = False
    app._live_refresh_in_flight = False
    app._data_update_cancel_token = None
    app._live_refresh_cancel_token = None
    app._active_live_request = None
    app._live_request_generation = 0
    app._live_timer_id = None
    app.selected_game = None
    app.game_id_var = FakeVar()
    app._log_event = lambda *_args, **_kwargs: None
    return app


# ---------------------------------------------------------------------------
# Quick Refresh (core data update) cancellation
# ---------------------------------------------------------------------------


def test_cancel_data_update_with_nothing_in_flight_is_a_safe_noop():
    app = bare_app()

    app.cancel_data_update()  # must not raise

    assert app._data_update_in_flight is False
    assert app._data_update_cancel_token is None


def test_cancel_data_update_frees_ui_state_immediately_without_waiting():
    app = bare_app()
    token = ausl_data.CancelToken()
    app._data_update_in_flight = True
    app._data_update_cancel_token = token

    app.cancel_data_update()

    assert token.cancelled is True
    assert app._data_update_in_flight is False
    assert app._data_update_cancel_token is None
    assert app.update_button.state == "normal"
    assert app.cancel_update_button.state == "disabled"


def test_cancel_data_update_is_idempotent_across_repeated_calls():
    app = bare_app()
    token = ausl_data.CancelToken()
    app._data_update_in_flight = True
    app._data_update_cancel_token = token

    app.cancel_data_update()
    app.cancel_data_update()
    app.cancel_data_update()

    assert app._data_update_in_flight is False
    assert app._data_update_cancel_token is None


def test_stale_data_update_success_after_cancel_does_not_promote():
    app = bare_app()
    app._data_update_cancel_token = None  # already cancelled/cleared
    promoted = []
    app._finish_load = lambda data: promoted.append(data)
    stale_token = ausl_data.CancelToken()

    app._finish_data_update_success({"roster": pd.DataFrame()}, stale_token)

    assert promoted == []
    assert app._data_update_in_flight is False


def test_stale_data_update_error_after_cancel_does_not_show_dialog(monkeypatch):
    app = bare_app()
    app._data_update_cancel_token = None
    shown = []
    monkeypatch.setattr(ausl_stats_app.messagebox, "showerror", lambda *a: shown.append(a))
    stale_token = ausl_data.CancelToken()

    app._finish_data_update_error(RuntimeError("boom"), stale_token)

    assert shown == []


def test_finish_data_update_success_promotes_when_token_is_current():
    app = bare_app()
    token = ausl_data.CancelToken()
    app._data_update_in_flight = True
    app._data_update_cancel_token = token
    promoted = []
    app._finish_load = lambda data: promoted.append(data)
    app._roster_count = lambda _data: 1
    data = {"roster": pd.DataFrame([{"player_id": 1}])}

    app._finish_data_update_success(data, token)

    assert len(promoted) == 1
    assert promoted[0] is data
    assert app._data_update_in_flight is False
    assert app._data_update_cancel_token is None


def test_finish_data_update_cancelled_updates_status_when_current():
    app = bare_app()
    token = ausl_data.CancelToken()
    app._data_update_in_flight = True
    app._data_update_cancel_token = token

    app._finish_data_update_cancelled(token)

    assert app._data_update_in_flight is False
    assert app._data_update_cancel_token is None
    assert "cancel" in app.status_var.get().lower()


def test_finish_data_update_cancelled_is_a_noop_when_superseded():
    app = bare_app()
    app._data_update_cancel_token = None
    app._data_update_in_flight = True  # a newer job is now active
    stale_token = ausl_data.CancelToken()

    app._finish_data_update_cancelled(stale_token)

    # Must not stomp on a newer in-flight job's state.
    assert app._data_update_in_flight is True


# ---------------------------------------------------------------------------
# Live refresh cancellation
# ---------------------------------------------------------------------------


def _live_token(app, game_id="9001", generation=1):
    request_token = ausl_stats_app.LiveRequestToken(game_id, generation)
    app._active_live_request = request_token
    app._live_request_generation = generation
    app.selected_game = ausl_stats_app.SelectedGame(
        game_id=game_id,
        season=2026,
        date_time=datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc),
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        away_team_code="CHI",
        home_team_code="CAR",
        time_zone="UTC",
        venue="",
        status="Final",
        source_updated_at="",
        source_name="Official AUSL Schedule",
    )
    app.game_id_var.set(game_id)
    return request_token


def test_cancel_live_refresh_with_nothing_in_flight_is_a_safe_noop():
    app = bare_app()

    app.cancel_live_refresh()  # must not raise

    assert app._live_refresh_in_flight is False


def test_cancel_live_refresh_frees_ui_state_immediately_without_waiting():
    app = bare_app()
    token = ausl_data.CancelToken()
    request_token = _live_token(app)
    app._live_refresh_cancel_token = token
    app._live_refresh_in_flight = True

    app.cancel_live_refresh()

    assert token.cancelled is True
    assert app._live_refresh_in_flight is False
    assert app._active_live_request is None
    assert app.live_refresh_button.state == "normal"
    assert app.cancel_live_button.state == "disabled"
    assert request_token is not None  # sanity: fixture actually set one up


def test_cancel_live_refresh_is_idempotent_across_repeated_calls():
    app = bare_app()
    token = ausl_data.CancelToken()
    _live_token(app)
    app._live_refresh_cancel_token = token
    app._live_refresh_in_flight = True

    app.cancel_live_refresh()
    app.cancel_live_refresh()
    app.cancel_live_refresh()

    assert app._live_refresh_in_flight is False


def test_stale_live_refresh_success_after_cancel_is_discarded():
    app = bare_app()
    request_token = _live_token(app)
    app._live_refresh_in_flight = True
    app.cancel_live_refresh()  # clears _active_live_request -> token now stale
    rendered = []
    app._finish_live = lambda game, box: rendered.append((game, box))

    app._finish_live_refresh_success({"gameId": "9001"}, {}, request_token)

    assert rendered == []


def test_stale_live_refresh_error_after_cancel_is_discarded():
    app = bare_app()
    request_token = _live_token(app)
    app._live_refresh_in_flight = True
    app.cancel_live_refresh()
    app.live_status.set("cancelled")

    app._finish_live_refresh_error(RuntimeError("boom"), request_token)

    # The cancel-time status message must not be clobbered by a late error.
    assert "cancelled" in app.live_status.get().lower()


def test_finish_live_refresh_cancelled_updates_status_when_current():
    app = bare_app()
    request_token = _live_token(app)
    app._live_refresh_in_flight = True
    app._live_refresh_cancel_token = ausl_data.CancelToken()

    app._finish_live_refresh_cancelled(request_token)

    assert app._live_refresh_in_flight is False
    assert app._active_live_request is None
    assert "cancel" in app.live_status.get().lower()


def test_game_change_cancels_in_flight_live_refresh_immediately():
    """A game change already cleared _live_refresh_in_flight immediately
    (pre-existing SAFE-002/LIVE-001 behavior); what REFRESH-006 adds is
    cancelling the abandoned request's own CancelToken too, so it stops
    retrying instead of working through its full retry/backoff budget in
    the background."""

    app = bare_app()
    token = ausl_data.CancelToken()
    _live_token(app)
    app._live_refresh_cancel_token = token
    app._live_refresh_in_flight = True

    app._invalidate_live_context()

    assert token.cancelled is True
    assert app._live_refresh_in_flight is False
    assert app._active_live_request is None
