from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pandas as pd

import ausl_stats_app
from ausl_rundown import RundownSession
from ausl_session import (
    GameIdentity,
    SessionLifecycle,
    SessionLoadResult,
    SessionLoadStatus,
    SessionSaveResult,
    SessionUIState,
)
from test_phase6a_command_center import FakeVar, make_app, selected_game
from test_phase6c_rundown import versioned_fact
from test_phase6d_session_schema import NOW, populated_snapshot


class FakeStore:
    def __init__(self, loaded=None, *, fail=False, archive_fail=False):
        self.loaded = loaded or SessionLoadResult(
            SessionLoadStatus.EMPTY, None, "No saved session."
        )
        self.fail = fail
        self.archive_fail = archive_fail
        self.saved = []
        self.archive_calls = 0
        self.current_path = "private/producer_session.json"

    def load(self):
        return self.loaded

    def save(self, snapshot, *, generation):
        self.saved.append((snapshot, generation))
        if self.fail:
            return SessionSaveResult(
                False,
                self.current_path,
                generation,
                "OSError: disk full",
            )
        return SessionSaveResult(True, self.current_path, generation)

    def archive_current_for_start_fresh(self):
        self.archive_calls += 1
        if self.archive_fail:
            raise OSError("archive blocked")
        return "private/producer_session.start-fresh.json"


class FakeCanvas:
    def __init__(self, fraction=0.0):
        self.fraction = fraction
        self.moves = []

    def yview(self):
        return (self.fraction, min(1.0, self.fraction + 0.2))

    def yview_moveto(self, value):
        self.fraction = float(value)
        self.moves.append(float(value))


class FakeNotebook:
    def __init__(self, labels, selected=0):
        self.labels = list(labels)
        self.selected = selected

    def select(self, value=None):
        if value is None:
            return self.selected
        self.selected = value

    def tab(self, identifier, option):
        assert option == "text"
        return self.labels[int(identifier)]

    def tabs(self):
        return tuple(range(len(self.labels)))


def session_app(store=None):
    app = make_app()
    app._rundown_session = RundownSession()
    app._fact_collection = None
    app.selected_player_id = None
    app.fact_status_filter_var = FakeVar("Air Ready")
    app.fact_team_filter_var = FakeVar("Both teams")
    app.fact_category_filter_var = FakeVar("All categories")
    app.fact_template_profile_var = FakeVar("60 — one line")
    app.fact_show_used_var = FakeVar(False)
    app.scope_var = FakeVar(True)
    app.session_status_var = FakeVar("")
    app.rundown_session_var = FakeVar("")
    app.session_recovery_var = FakeVar("")
    app.fact_cards_canvas = FakeCanvas(0.2)
    app.rundown_canvas = FakeCanvas(0.4)
    app.main_tabs = FakeNotebook(["Game Day", "Player Lookup"], 0)
    app.game_day_views = FakeNotebook(
        ["Air-Ready Facts", "Rundown", "Readiness Details"], 1
    )
    app._configure_session_persistence(
        store=store or FakeStore(),
        now_provider=lambda: NOW,
    )
    return app


def run_latest_timer(app):
    _timer, _delay, callback = app.root.scheduled[-1]
    callback()


def test_debounced_autosave_keeps_only_one_timer_and_newest_generation():
    app = session_app()

    app._schedule_session_autosave("game changed")
    first_timer = app._session_autosave_id
    app._schedule_session_autosave("rundown changed")

    assert first_timer in app.root.cancelled
    assert len(app.root.scheduled) == 2
    assert app.root.scheduled[-1][1] == 500
    run_latest_timer(app)
    snapshot, generation = app._session_store.saved[-1]
    assert generation == 2
    assert snapshot.lifecycle is SessionLifecycle.ACTIVE
    assert "Session saved" in app.session_status_var.get()


def test_save_failure_is_visible_persistent_and_clears_after_recovery():
    store = FakeStore(fail=True)
    app = session_app(store)

    app._schedule_session_autosave("pin")
    run_latest_timer(app)

    assert app._session_save_error
    assert "NOT SAVED" in app.session_status_var.get()
    assert app._session_readiness_issue()["state"] == "warning"

    store.fail = False
    app._schedule_session_autosave("retry")
    run_latest_timer(app)
    assert app._session_save_error == ""
    assert app._session_readiness_issue() is None


def test_snapshot_captures_exact_game_rundown_and_ui_but_not_offline_runtime():
    app = session_app()
    app._offline_mode = True
    app._rundown_session.pin_fact("9001", versioned_fact(game_id="9001"), now=NOW)

    snapshot = app._capture_session_snapshot(lifecycle=SessionLifecycle.ACTIVE)

    assert snapshot.selected_game == GameIdentity("9001", 2026, "CHI", "CAR")
    assert snapshot.rundown_states[0].game_id == "9001"
    assert snapshot.ui_state.main_tab == "Game Day"
    assert snapshot.ui_state.game_day_view == "Rundown"
    assert snapshot.ui_state.prior_offline_mode is True
    assert app._offline_mode is True


def test_clean_close_cancels_debounce_and_flushes_closed_lifecycle():
    store = FakeStore()
    app = session_app(store)
    app.cancel_data_update = lambda: None
    app.cancel_live_refresh = lambda: None
    app._cancel_live_timer = lambda: None
    app._fact_build_generation = 1
    app._fact_build_lock = None
    app._schedule_session_autosave("pending")
    pending = app._session_autosave_id

    app._on_close()

    assert pending in app.root.cancelled
    assert store.saved[-1][0].lifecycle is SessionLifecycle.CLOSED_CLEANLY
    assert app.root.destroyed


def test_exact_saved_game_and_rundown_restore_without_network_or_offline_restore():
    snapshot = replace(
        populated_snapshot(),
        selected_game=GameIdentity("1042", 2026, "CHI", "TAL"),
        ui_state=replace(
            populated_snapshot().ui_state,
            prior_offline_mode=True,
            selected_player_id=None,
        ),
    )
    loaded = SessionLoadResult(
        SessionLoadStatus.RECOVERED,
        snapshot,
        "Recovered a session that did not close cleanly.",
    )
    app = session_app(FakeStore(loaded))
    app.selected_game = selected_game("1042")
    app.selected_game = replace(
        app.selected_game,
        home_team="Talons",
        home_team_code="TAL",
    )
    app._official_game_choices = {app.selected_game.choice_label: app.selected_game}
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None
    app._restore_pending_session_after_database_load()

    restored = app._rundown_session.get_state("1042", create=False)
    assert restored is not None
    assert restored.active_entries[0].fact_id == snapshot.rundown_states[0].active_entries[0].fact_id
    assert app._offline_mode is False
    assert app._session_restore_game_unresolved is False
    assert app.fact_status_filter_var.get() == "Needs Verification"
    assert app._session_recovery_visible


def test_wrong_team_or_missing_saved_game_is_not_guessed_and_blocks_readiness():
    snapshot = replace(
        populated_snapshot(),
        selected_game=GameIdentity("1042", 2026, "CHI", "TAL"),
    )
    loaded = SessionLoadResult(SessionLoadStatus.RESUME, snapshot, "Resume")
    app = session_app(FakeStore(loaded))
    wrong = selected_game("1042")
    app._official_game_choices = {wrong.choice_label: wrong}
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None

    app._restore_pending_session_after_database_load()

    assert app._session_restore_game_unresolved
    issue = app._session_readiness_issue()
    assert issue["state"] == "fail"
    assert issue["blocking"] is True
    assert "not match" in issue["detail"].lower()
    assert not app._schedule_session_autosave("automatic default")
    closed = app._capture_session_snapshot(
        lifecycle=SessionLifecycle.CLOSED_CLEANLY
    )
    assert closed.selected_game == snapshot.selected_game


def test_exact_player_restore_requires_one_matching_identity():
    snapshot = replace(
        populated_snapshot(),
        selected_game=GameIdentity("9001", 2026, "CHI", "CAR"),
        rundown_states=(),
        ui_state=replace(
            populated_snapshot().ui_state,
            selected_player_id="1",
        ),
    )
    app = session_app(
        FakeStore(SessionLoadResult(SessionLoadStatus.RESUME, snapshot, "Resume"))
    )
    app._official_game_choices = {app.selected_game.choice_label: app.selected_game}
    rendered = []
    app.render_player = lambda row: rendered.append(str(row["player_id"]))
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None

    app._restore_pending_session_after_database_load()

    assert rendered == ["1"]
    assert app.selected_player_id == 1

    app = session_app(
        FakeStore(SessionLoadResult(SessionLoadStatus.RESUME, snapshot, "Resume"))
    )
    app.db["roster"] = pd.concat([app.db["roster"], app.db["roster"].iloc[[0]]])
    app._official_game_choices = {app.selected_game.choice_label: app.selected_game}
    app._clear_selected_player = lambda: setattr(app, "selected_player_id", None)
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None
    app._restore_pending_session_after_database_load()
    assert app.selected_player_id is None


def test_scroll_restore_is_deferred_until_layout_and_normalized():
    snapshot = replace(
        populated_snapshot(),
        selected_game=GameIdentity("9001", 2026, "CHI", "CAR"),
        rundown_states=(),
        ui_state=replace(
            populated_snapshot().ui_state,
            fact_scroll_fraction=0.3,
            rundown_scroll_fraction=0.8,
        ),
    )
    app = session_app(
        FakeStore(SessionLoadResult(SessionLoadStatus.RESUME, snapshot, "Resume"))
    )
    app._official_game_choices = {app.selected_game.choice_label: app.selected_game}
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None

    app._restore_pending_session_after_database_load()
    assert app.fact_cards_canvas.moves == []
    run_latest_timer(app)
    assert app.fact_cards_canvas.moves == [0.3]
    assert app.rundown_canvas.moves == [0.8]


def test_start_fresh_requires_archive_before_runtime_clear():
    snapshot = populated_snapshot()
    store = FakeStore(
        SessionLoadResult(SessionLoadStatus.RECOVERED, snapshot, "Recovered"),
        archive_fail=True,
    )
    app = session_app(store)
    app._rundown_session.restore_states(snapshot.rundown_states)
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None

    assert not app.start_fresh_session(confirmed=True)
    assert app._rundown_session.states
    assert "NOT CLEARED" in app.session_status_var.get()

    store.archive_fail = False
    assert app.start_fresh_session(confirmed=True)
    assert app._rundown_session.states == ()
    assert app._session_recovery_visible is False
    assert store.archive_calls == 2


def test_dismiss_hides_notice_without_clearing_restored_state():
    app = session_app()
    app._session_recovery_visible = True
    app._rundown_session.pin_fact("9001", versioned_fact(game_id="9001"), now=NOW)

    app.dismiss_session_recovery()

    assert app._session_recovery_visible is False
    assert app._rundown_session.states


def test_rundown_mutation_and_game_change_schedule_autosave(monkeypatch):
    canonical = versioned_fact(game_id="9001")
    app = session_app()
    app._fact_collection = ausl_stats_app.FactCollection(
        game_id="9001",
        snapshot_timestamp="2026-07-28T14:00:00+00:00",
        database_version="db",
        facts=(canonical,),
        available=True,
        empty_reason="",
    )
    app._render_rundown = lambda: None
    app._render_fact_cards = lambda: None
    app.refresh_game_day_dashboard = lambda: None
    reasons = []
    app._schedule_session_autosave = reasons.append

    assert app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    assert "rundown" in reasons[-1].lower()


def test_database_restore_reconciles_saved_fact_against_current_collection():
    old = versioned_fact(game_id="9001", copy="Old supported wording.")
    latest = versioned_fact(game_id="9001", copy="Updated supported wording.")
    app = session_app()
    app._rundown_session.pin_fact("9001", old, now=NOW)
    app._fact_collection = ausl_stats_app.FactCollection(
        game_id="9001",
        snapshot_timestamp="2026-07-28T14:00:00+00:00",
        database_version="db-new",
        facts=(latest,),
        available=True,
        empty_reason="",
    )
    app._fact_build_generation = 2
    app._render_fact_cards = lambda: None
    app._render_rundown = lambda: None
    app.refresh_game_day_dashboard = lambda: None

    assert app._finish_fact_rebuild(
        app._fact_collection, 2, "9001", id(app.db)
    )
    entry = app._rundown_session.get_state("9001").active_entries[0]
    assert entry.latest_fact == latest
    assert entry.evidence_hash == old.evidence_hash
