"""Deterministic offline Windows/source GUI smoke for Phase 6D."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tkinter as tk  # noqa: E402

from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_facts import FactCollection  # noqa: E402
from ausl_session import (  # noqa: E402
    SessionLifecycle,
    SessionLoadStatus,
    SessionStore,
)
import ausl_stats_app  # noqa: E402


def pump(root, predicate, *, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread callback")


def forbid_network(name):
    def blocked(*_args, **_kwargs):
        raise AssertionError(f"Phase 6D GUI smoke attempted network route: {name}")

    return blocked


def open_app(state_dir, database):
    root = tk.Tk()
    app = ausl_stats_app.AUSLStatsApp(
        root,
        session_store=SessionStore(state_dir),
    )
    root.geometry("1120x720")
    root.update()
    app._finish_load(database)
    pump(
        root,
        lambda: isinstance(app._fact_collection, FactCollection)
        and app._fact_collection.game_id == app.selected_game.game_id,
    )
    return root, app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    parser.add_argument("--hold-recovery-seconds", type=float, default=0.0)
    args = parser.parse_args()

    database = load_database(include_enrichment=True)
    original_initial_load = ausl_stats_app.AUSLStatsApp._load_initial
    original_lineup_load = ausl_stats_app.AUSLStatsApp.load_locked_lineups
    original_core_refresh = ausl_stats_app.update_all_data
    original_live_refresh = ausl_stats_app.fetch_live_game
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: empty_locked_lineup_store()
    )
    ausl_stats_app.update_all_data = forbid_network("core_refresh")
    ausl_stats_app.fetch_live_game = forbid_network("live_refresh")

    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase6d-smoke-")
    state_dir = Path(temporary.name) / "private-session"
    roots = []
    try:
        # First launch: create meaningful producer state and close normally.
        root1, app1 = open_app(state_dir, database)
        roots.append(root1)
        root1.title("AUSL Phase 6D Smoke — First Launch")
        selected_id = app1.selected_game.game_id
        ready = [item for item in app1._fact_collection.facts if item.air_ready]
        if len(ready) < 2:
            raise AssertionError("GUI smoke needs two air-ready fixture facts")
        assert app1.pin_fact_to_rundown(ready[0].fact_id)
        assert app1.pin_fact_to_rundown(ready[1].fact_id)
        first_entry = app1._current_rundown_state().active_entries[0]
        assert app1.mark_rundown_entry_used(first_entry.entry_id)
        app1.rundown_break_target_var.set("45")
        assert app1.apply_rundown_break_target()
        app1.fact_status_filter_var.set("All facts")
        app1.fact_team_filter_var.set("Both teams")
        app1.fact_show_used_var.set(True)
        app1.game_day_views.select(1)
        roster = database["roster"]
        player = roster[
            roster["team_code"].isin(
                {
                    app1.selected_game.away_team_code,
                    app1.selected_game.home_team_code,
                }
            )
        ].iloc[0]
        app1.selected_player_id = int(player["player_id"])
        app1.render_player(player)
        player_id = str(app1.selected_player_id)
        app1.fact_cards_canvas.yview_moveto(0.2)
        app1.rundown_canvas.yview_moveto(0.3)
        app1.set_local_offline_mode(True)
        assert app1._flush_session_save(lifecycle=SessionLifecycle.ACTIVE)
        assert SessionStore(state_dir).load().status is SessionLoadStatus.RECOVERED
        app1._on_close()
        roots.remove(root1)
        clean = SessionStore(state_dir).load()
        assert clean.status is SessionLoadStatus.RESUME

        # Clean relaunch: restore exact identities and canonical Phase 6C state.
        root2, app2 = open_app(state_dir, database)
        roots.append(root2)
        root2.title("AUSL Phase 6D Smoke — Clean Resume")
        assert app2._session_load_result.status is SessionLoadStatus.RESUME
        assert app2.selected_game.game_id == selected_id
        restored = app2._current_rundown_state()
        assert len(restored.active_entries) == 1
        assert len(restored.used_history) == 1
        assert restored.break_target_seconds == 45
        assert app2.fact_status_filter_var.get() == "All facts"
        assert app2.fact_show_used_var.get() is True
        assert str(app2.selected_player_id) == player_id
        assert app2._offline_mode is False
        assert app2.offline_mode_var.get() is False
        assert app2._last_fact_copy_event is None
        root2.update()
        assert app2.rundown_canvas.yview()[0] >= 0.0
        for index in range(len(app2.main_tabs.tabs())):
            app2.main_tabs.select(index)
            root2.update()
        app2.main_tabs.select(0)
        app2.game_day_views.select(1)
        app2.fact_category_filter_var.set("All categories")
        assert app2._flush_session_save(lifecycle=SessionLifecycle.ACTIVE)
        for timer_id in (
            app2._session_autosave_id,
            app2._main_thread_poll_id,
            app2._live_timer_id,
        ):
            if timer_id is not None:
                try:
                    root2.after_cancel(timer_id)
                except tk.TclError:
                    pass
        root2.destroy()  # Deliberate unclean termination for recovery classification.
        roots.remove(root2)

        # Crash relaunch: show recovery, fail visibly, then archive and start fresh.
        root3, app3 = open_app(state_dir, database)
        roots.append(root3)
        root3.title("AUSL Phase 6D Smoke — Crash Recovery")
        assert app3._session_load_result.status is SessionLoadStatus.RECOVERED
        assert app3._session_recovery_visible
        assert app3.session_recovery_frame.winfo_ismapped()
        assert app3._current_rundown_state().active_entries
        app3.review_recovered_session()
        root3.update()
        assert app3.game_day_views.tab(app3.game_day_views.select(), "text") == "Rundown"
        if args.hold_recovery_seconds > 0:
            deadline = time.monotonic() + min(args.hold_recovery_seconds, 60.0)
            while time.monotonic() < deadline:
                root3.update()
                time.sleep(0.02)

        real_replace = app3._session_store._replace

        def fail_replace(_source, _destination):
            raise OSError("simulated disk full")

        app3._session_store._replace = fail_replace
        assert not app3._flush_session_save(lifecycle=SessionLifecycle.ACTIVE)
        assert "NOT SAVED" in app3.session_status_var.get()
        assert app3._session_readiness_issue()["state"] == "warning"
        app3._session_store._replace = real_replace
        assert app3.start_fresh_session(confirmed=True)
        fresh = app3._current_rundown_state(create=False)
        assert fresh is None or (
            fresh.active_entries == () and fresh.used_history == ()
        )
        assert not app3._session_recovery_visible
        archives = tuple(state_dir.glob("producer_session.start-fresh-*.json"))
        assert len(archives) == 1

        if args.hold_seconds > 0:
            deadline = time.monotonic() + min(args.hold_seconds, 60.0)
            while time.monotonic() < deadline:
                root3.update()
                time.sleep(0.02)

        result = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "app_type": "Windows source app / real Tk loop / offline snapshot",
            "selected_game": selected_id,
            "clean_resume": True,
            "crash_recovery": True,
            "exact_player_restored": player_id,
            "rundown_restored": True,
            "used_history_restored": True,
            "offline_mode_not_restored": True,
            "clipboard_state_not_restored": True,
            "save_failure_visible": True,
            "start_fresh_archive": archives[0].name,
            "tabs_opened": len(app3.main_tabs.tabs()),
            "network_calls": 0,
        }
        print(json.dumps(result, sort_keys=True))
        app3._on_close()
        roots.remove(root3)
    finally:
        ausl_stats_app.AUSLStatsApp._load_initial = original_initial_load
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = original_lineup_load
        ausl_stats_app.update_all_data = original_core_refresh
        ausl_stats_app.fetch_live_game = original_live_refresh
        for root in roots:
            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass
        temporary.cleanup()


if __name__ == "__main__":
    main()
