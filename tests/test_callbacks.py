from __future__ import annotations

from datetime import datetime

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

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class DeferredRoot:
    def __init__(self):
        self.callbacks = []
        self.next_id = 0

    def after(self, _delay_ms, callback):
        self.next_id += 1
        callback_id = f"after-{self.next_id}"
        self.callbacks.append((callback_id, callback))
        return callback_id

    def after_cancel(self, callback_id):
        self.callbacks = [
            item for item in self.callbacks if item[0] != callback_id
        ]

    def run_all(self):
        while self.callbacks:
            _callback_id, callback = self.callbacks.pop(0)
            callback()


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def bare_app(monkeypatch):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.root = DeferredRoot()
    app.status_var = FakeVar()
    app.live_status = FakeVar()
    app.update_button = FakeButton()
    app.live_refresh_button = FakeButton()
    app._initial_load_in_flight = False
    app._data_update_in_flight = False
    app._live_refresh_in_flight = False
    app.logger = None
    monkeypatch.setattr(ausl_stats_app.threading, "Thread", ImmediateThread)
    return app


def select_official_game(app, game_id="9001"):
    app.selected_game = ausl_stats_app.SelectedGame(
        game_id=str(game_id),
        season=2026,
        date_time=datetime.fromisoformat("2026-07-20T19:00:00-04:00"),
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
    app.game_id_var = FakeVar(str(game_id))


def test_initial_load_reports_the_original_error_after_deferred_callback(monkeypatch):
    app = bare_app(monkeypatch)
    seen = []
    app._load_failed = lambda exc: seen.append(str(exc))
    monkeypatch.setattr(
        ausl_stats_app,
        "load_database",
        lambda *, include_enrichment: (_ for _ in ()).throw(
            RuntimeError("initial fixture failure")
        ),
    )

    app._load_initial()
    app.root.run_all()

    assert seen == ["initial fixture failure"]
    assert app._initial_load_in_flight is False
    assert app.update_button.state == "normal"


def test_initial_load_suppresses_a_duplicate_job_until_terminal_callback(monkeypatch):
    app = bare_app(monkeypatch)
    loads = []
    app._finish_load = lambda _data: app.status_var.set("Initial load complete")

    def load_once(*, include_enrichment):
        assert include_enrichment is False
        loads.append("load")
        return {"roster": []}

    monkeypatch.setattr(ausl_stats_app, "load_database", load_once)

    app._load_initial()
    app._load_initial()

    assert loads == ["load"]
    assert app._initial_load_in_flight is True
    assert app.update_button.state == "disabled"

    app.root.run_all()

    assert app._initial_load_in_flight is False
    assert app.update_button.state == "normal"


def test_data_update_reports_the_original_error_after_deferred_callback(monkeypatch):
    app = bare_app(monkeypatch)
    seen = []
    monkeypatch.setattr(
        ausl_stats_app.messagebox,
        "showerror",
        lambda _title, message: seen.append(str(message)),
    )
    monkeypatch.setattr(
        ausl_stats_app,
        "update_all_data",
        lambda _progress, *, include_enrichment: (_ for _ in ()).throw(
            RuntimeError("update fixture failure")
        ),
    )

    app.update_data()
    app.root.run_all()

    assert seen == ["update fixture failure"]
    assert app.status_var.get() == "Data update failed: update fixture failure"
    assert app._data_update_in_flight is False
    assert app.update_button.state == "normal"


def test_data_update_suppresses_duplicate_and_restores_button_on_success(monkeypatch):
    app = bare_app(monkeypatch)
    updates = []
    app._finish_load = lambda _data: app.status_var.set("Ready")

    def update_once(_progress, *, include_enrichment):
        assert include_enrichment is False
        updates.append("update")

    monkeypatch.setattr(ausl_stats_app, "update_all_data", update_once)
    monkeypatch.setattr(
        ausl_stats_app,
        "load_database",
        lambda *, include_enrichment: {"roster": [1, 2]},
    )

    app.update_data()
    app.update_data()

    assert updates == ["update"]
    assert app._data_update_in_flight is True
    assert app.update_button.state == "disabled"

    app.root.run_all()

    assert app._data_update_in_flight is False
    assert app.update_button.state == "normal"
    assert app.status_var.get() == "Update complete — 2 current players loaded"


def test_live_refresh_reports_the_original_error_after_deferred_callback(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app)
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda _game_id: (_ for _ in ()).throw(RuntimeError("live fixture failure")),
    )

    app.refresh_live()
    app.root.run_all()

    assert app.live_status.get() == "Live feed error: live fixture failure"
    assert app._live_refresh_in_flight is False
    assert app.live_refresh_button.state == "normal"


def test_live_refresh_suppresses_duplicate_and_restores_button_on_success(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app)
    fetches = []

    def fetch_once(game_id):
        fetches.append(game_id)
        return {"gameId": int(game_id), "recordStatus": "Scheduled"}, {"competitors": []}

    app._finish_live = lambda game, _box: app.live_status.set(f"Loaded game {game['gameId']}")
    monkeypatch.setattr(ausl_stats_app, "fetch_live_game", fetch_once)

    app.refresh_live()
    app.refresh_live()

    assert fetches == ["9001"]
    assert app._live_refresh_in_flight is True
    assert app.live_refresh_button.state == "disabled"

    app.root.run_all()

    assert app._live_refresh_in_flight is False
    assert app.live_refresh_button.state == "normal"
    assert app.live_status.get() == "Loaded game 9001"


def test_live_refresh_rejects_a_response_for_a_different_official_game(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app)
    finished = []
    app._finish_live = lambda *_args: finished.append(True)
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda _game_id: ({"gameId": 9002, "recordStatus": "Scheduled"}, {}),
    )

    app.refresh_live()
    app.root.run_all()

    assert finished == []
    assert "9002" in app.live_status.get()
    assert "9001" in app.live_status.get()
    assert "did not match" in app.live_status.get().lower()
    assert app._live_refresh_in_flight is False
    assert app.live_refresh_button.state == "normal"


def test_refresh_lifecycle_emits_structured_events_without_payload_contents(monkeypatch):
    app = bare_app(monkeypatch)
    app.logger = object()
    select_official_game(app)
    app._finish_live = lambda _game, _box: app.live_status.set("Loaded fixture")
    events = []
    monkeypatch.setattr(
        ausl_stats_app,
        "log_event",
        lambda _logger, event, **fields: events.append((event, fields)),
    )
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda _game_id: ({"gameId": 9001, "recordStatus": "Scheduled"}, {}),
    )

    app.refresh_live()
    app.root.run_all()

    assert [event for event, _fields in events] == [
        "live_refresh_started",
        "live_refresh_succeeded",
    ]
    assert all("note_text" not in fields for _event, fields in events)


def test_live_refresh_blocks_an_id_detached_from_selected_official_game(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app, "9001")
    app.game_id_var.set("9002")
    fetched = []
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda game_id: fetched.append(game_id),
    )

    app.refresh_live()

    assert fetched == []
    assert app._live_refresh_in_flight is False
    assert "selected official game 9001" in app.live_status.get().lower()


def test_live_refresh_rejects_late_response_after_selected_game_changes(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app, "9001")
    rendered = []
    app._finish_live = lambda *_args: rendered.append("stale live data")
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda _game_id: ({"gameId": 9001, "recordStatus": "Scheduled"}, {}),
    )

    app.refresh_live()
    select_official_game(app, "9002")
    app.root.run_all()

    assert rendered == []
    assert app.live_game is None if hasattr(app, "live_game") else True
    assert "discarded" in app.live_status.get().lower()


def test_live_auto_refresh_owns_and_replaces_one_timer(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app)
    app.auto_var = FakeVar(True)

    app._schedule_live()
    first_timer = app._live_timer_id
    app._schedule_live()

    assert first_timer != app._live_timer_id
    assert [item[0] for item in app.root.callbacks] == [app._live_timer_id]

    app.auto_var.set(False)
    app._schedule_live()

    assert app._live_timer_id is None
    assert app.root.callbacks == []


def test_live_worker_never_calls_tk_after_directly(monkeypatch):
    app = bare_app(monkeypatch)
    select_official_game(app)
    in_worker = False
    original_after = app.root.after

    def guarded_after(delay, callback):
        assert in_worker is False
        return original_after(delay, callback)

    app.root.after = guarded_after

    class GuardedThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            nonlocal in_worker
            in_worker = True
            try:
                self.target()
            finally:
                in_worker = False

    monkeypatch.setattr(ausl_stats_app.threading, "Thread", GuardedThread)
    monkeypatch.setattr(
        ausl_stats_app,
        "fetch_live_game",
        lambda _game_id: ({"gameId": 9001, "recordStatus": "Scheduled"}, {}),
    )
    app._finish_live = lambda *_args: None

    app.refresh_live()
    app.root.run_all()

    assert app._live_refresh_in_flight is False
