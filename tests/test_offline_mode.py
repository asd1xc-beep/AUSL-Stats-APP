from __future__ import annotations

from datetime import datetime, timezone

import ausl_stats_app

from test_phase6a_command_center import (
    FakeButton,
    FakeRoot,
    FakeToken,
    FakeVar,
    make_app,
)


def test_offline_mode_blocks_core_and_live_network_entry_points(monkeypatch):
    app = make_app()
    app._offline_mode = True
    app.offline_mode_var.set(True)
    calls = []
    monkeypatch.setattr(
        ausl_stats_app,
        "update_all_data",
        lambda *_args, **_kwargs: calls.append("core"),
    )
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda *_args, **_kwargs: calls.append("live"),
    )
    app.game_id_var = FakeVar("9001")

    app.update_data()
    app.refresh_live()

    assert calls == []
    assert "LOCAL/OFFLINE MODE" in app.status_var.get()
    assert "LOCAL/OFFLINE MODE" in app.live_status.get()


def test_enabling_offline_cancels_inflight_work_and_owned_timer():
    app = make_app()
    data_token = FakeToken()
    live_token = FakeToken()
    app._data_update_cancel_token = data_token
    app._data_update_in_flight = True
    app._live_refresh_cancel_token = live_token
    app._live_refresh_in_flight = True
    app._active_live_request = ausl_stats_app.LiveRequestToken("9001", 1)
    app._live_timer_id = "timer-existing"
    app.auto_var.set(True)
    events = []
    app.refresh_game_day_dashboard = lambda: events.append("dashboard")

    app.set_local_offline_mode(True)

    assert data_token.cancelled == 1
    assert live_token.cancelled == 1
    assert app._data_update_in_flight is False
    assert app._live_refresh_in_flight is False
    assert app._live_timer_id is None
    assert app.root.cancelled == ["timer-existing"]
    assert app.auto_var.get() is False
    assert events == ["dashboard"]


def test_offline_mode_prevents_live_timer_rescheduling():
    app = make_app()
    app._offline_mode = True
    app.offline_mode_var.set(True)
    app.auto_var.set(True)

    app._schedule_live()
    app._auto_refresh()

    assert app.root.scheduled == []
    assert app._live_timer_id is None


def test_repeated_enable_disable_is_safe_and_disable_does_not_fetch(monkeypatch):
    app = make_app()
    calls = []
    app.refresh_game_day_dashboard = lambda: None
    monkeypatch.setattr(app, "update_data", lambda: calls.append("core"))
    monkeypatch.setattr(app, "refresh_live", lambda: calls.append("live"))

    app.set_local_offline_mode(True)
    app.set_local_offline_mode(True)
    app.set_local_offline_mode(False)
    app.set_local_offline_mode(False)

    assert app._offline_mode is False
    assert calls == []
    assert "No refresh was started" in app.status_var.get()


def test_offline_sync_disables_only_network_controls():
    app = make_app()
    local_button = FakeButton()
    app.local_workflow_button = local_button
    app._offline_mode = True

    app._sync_update_button()
    app._sync_live_refresh_button()

    assert app.update_button.state == "disabled"
    assert app.live_refresh_button.state == "disabled"
    assert local_button.state == "normal"


def test_late_network_callbacks_are_ignored_after_offline_activation():
    app = make_app()
    data_token = FakeToken()
    live_request = ausl_stats_app.LiveRequestToken("9001", 1)
    app._data_update_cancel_token = data_token
    app._data_update_in_flight = True
    app._live_refresh_cancel_token = FakeToken()
    app._live_refresh_in_flight = True
    app._active_live_request = live_request
    app.game_id_var = FakeVar("9001")
    dashboard_updates = []
    app.refresh_game_day_dashboard = lambda: dashboard_updates.append("offline")

    app.set_local_offline_mode(True)

    app.refresh_game_day_dashboard = lambda: (_ for _ in ()).throw(
        AssertionError("late callback changed dashboard")
    )
    app._finish_data_update_success({"roster": []}, data_token)
    app._finish_data_update_error(RuntimeError("late"), data_token)
    app._finish_live_refresh_success(
        {"gameId": 9001, "lastUpdated": datetime.now(timezone.utc).isoformat()},
        {},
        live_request,
    )
    app._finish_live_refresh_error(RuntimeError("late"), live_request)

    assert dashboard_updates == ["offline"]


def test_app_closes_normally_while_offline():
    app = make_app()
    app._offline_mode = True
    app.offline_mode_var.set(True)

    app._on_close()

    assert app.root.destroyed is True
