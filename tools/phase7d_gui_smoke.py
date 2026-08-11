"""Offline real-Tk smoke for the Phase 7D College RÃ©sumÃ© workflow."""

from __future__ import annotations

import copy
import json
import platform
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import tkinter as tk  # noqa: E402

import ausl_stats_app  # noqa: E402
from ausl_college_store import CollegeStore  # noqa: E402
from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_enrichment import EnrichmentMode  # noqa: E402
from ausl_session import SessionLifecycle, SessionStore  # noqa: E402


PILOT_IDS = ("950", "1285", "1327", "1102", "1322")


def pump(root, predicate, *, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread callback")


def blocked_network(name):
    def blocked(*_args, **_kwargs):
        raise AssertionError(f"Phase 7D smoke attempted network access: {name}")

    return blocked


def _identifier(value):
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _row(database, player_id):
    roster = database["roster"]
    rows = roster[roster["player_id"].map(_identifier).eq(player_id)]
    if len(rows) != 1:
        raise AssertionError(f"Exact roster identity unavailable: {player_id}")
    return rows.iloc[0]


def _select(app, database, player_id):
    row = _row(database, player_id)
    app.selected_player_id = int(player_id)
    app.render_player(row)
    assert app.render_college_resume()
    assert app._current_college_view.player_id == player_id
    return app._current_college_view


def _database():
    database = load_database(enrichment_mode=EnrichmentMode.CORE_ONLY)
    database["_college_load_result"] = CollegeStore.default().load(
        EnrichmentMode.PRODUCER_APPROVED
    )
    assert database["_college_load_result"].available
    return database


def main() -> int:
    database = _database()
    original_initial = ausl_stats_app.AUSLStatsApp._load_initial
    original_lineups = ausl_stats_app.AUSLStatsApp.load_locked_lineups
    original_update = ausl_stats_app.update_all_data
    original_load = ausl_stats_app.load_database
    original_live = ausl_stats_app.fetch_live_game
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: empty_locked_lineup_store()
    )
    ausl_stats_app.update_all_data = (
        lambda progress, *, include_enrichment, cancel_token: progress(
            "Offline fixture refresh complete."
        )
    )
    ausl_stats_app.load_database = lambda **_kwargs: copy.deepcopy(database)
    ausl_stats_app.fetch_live_game = blocked_network("live game")

    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase7d-smoke-")
    state_dir = Path(temporary.name) / "session"
    roots = []
    checks = []
    try:
        root = tk.Tk()
        roots.append(root)
        root.geometry("1120x720")
        root.title("AUSL Phase 7D Smoke â€” College RÃ©sumÃ©")
        app = ausl_stats_app.AUSLStatsApp(
            root, session_store=SessionStore(state_dir)
        )
        app._finish_load(copy.deepcopy(database))
        root.update()

        tabs = tuple(app.main_tabs.tab(tab_id, "text") for tab_id in app.main_tabs.tabs())
        assert len(tabs) == 9 and "College RÃ©sumÃ©" in tabs
        for tab_id in app.main_tabs.tabs():
            app.main_tabs.select(tab_id)
            root.update_idletasks()
        checks.append("nine_tabs")

        # Exact Player Lookup handoff with the existing search engine.
        target = _row(database, "950")
        app.main_tabs.select(app.main_tabs.tabs()[1])
        app.scope_var.set(False)
        app.search_var.set(str(target["player_name"]))
        app.search()
        assert app.search_rows
        app.results.selection_clear(0, "end")
        app.results.selection_set(0)
        app.select_result()
        assert _identifier(app.selected_player_id) == "950"
        assert app.view_selected_college_resume()
        assert app.main_tabs.tab(app.main_tabs.select(), "text") == "College RÃ©sumÃ©"
        checks.append("lookup_handoff")

        views = {player_id: _select(app, database, player_id) for player_id in PILOT_IDS}
        assert views["950"].batting_fields and views["950"].pitching_fields
        assert views["1285"].pitching_fields
        assert views["1327"].batting_fields and views["1327"].pitching_fields
        assert views["1102"].school_timeline == ("Louisville", "Florida")
        assert views["1322"].completeness == "Partial"
        checks.append("varied_resumes")

        app.selected_player_id = 999999
        assert not app.render_college_resume()
        assert "no college history has been inferred" in app.college_status_var.get()
        checks.append("nonpilot_unavailable")

        view = _select(app, database, "950")
        field = view.stat_fields[0]
        assert app.copy_college_field(field.field_id)
        assert root.clipboard_get() == field.copy_text
        assert app.copy_college_field(field.field_id, with_source=True)
        assert root.clipboard_get() == field.copy_with_source
        assert view.source_summaries
        checks.append("approved_copy_and_sources")

        root.clipboard_clear()
        root.clipboard_append("clipboard sentinel")
        app._college_load_result = app._college_store.load(
            EnrichmentMode.DEVELOPER_REVIEW
        )
        assert app.render_college_resume()
        blocked_field = app._current_college_view.stat_fields[0]
        assert not app.copy_college_field(blocked_field.field_id)
        assert root.clipboard_get() == "clipboard sentinel"
        app._college_load_result = app._college_store.load(
            EnrichmentMode.PRODUCER_APPROVED
        )
        app.render_college_resume()
        checks.append("blocked_copy_preserves_clipboard")

        root.update_idletasks()
        app.college_canvas.focus_set()
        before = app.college_canvas.yview()[0]
        app._on_college_mousewheel(type("Event", (), {"delta": -120, "num": None})())
        root.update_idletasks()
        after = app.college_canvas.yview()[0]
        assert after >= before
        app._college_keyboard_scroll(1, "pages")
        checks.append("mouse_keyboard_scroll")

        # A local Quick Refresh revalidates college artifacts without fetching them.
        app.set_local_offline_mode(False)
        app.update_data()
        pump(root, lambda: not app._data_update_in_flight)
        assert app._college_load_result.available
        assert app._current_college_view.player_id == "950"
        app.set_local_offline_mode(True)
        assert app._current_college_view.available
        assert "Local/Offline" in app.college_status_var.get()
        checks.append("refresh_and_offline")

        # Rapid exact identity changes must end on the newest player.
        for player_id in ("950", "1285", "1327", "1102", "1322"):
            _select(app, database, player_id)
        root.update()
        assert app._current_college_view.player_id == "1322"
        checks.append("no_stale_selection")

        _select(app, database, "950")
        app.main_tabs.select(app.main_tabs.tabs()[2])
        assert app._flush_session_save(lifecycle=SessionLifecycle.CLOSED_CLEANLY)
        app._on_close()
        roots.remove(root)

        root2 = tk.Tk()
        roots.append(root2)
        root2.geometry("1120x720")
        app2 = ausl_stats_app.AUSLStatsApp(
            root2, session_store=SessionStore(state_dir)
        )
        app2._finish_load(copy.deepcopy(database))
        root2.update()
        assert _identifier(app2.selected_player_id) == "950"
        assert app2.main_tabs.tab(app2.main_tabs.select(), "text") == "College RÃ©sumÃ©"
        assert app2._current_college_view.player_id == "950"
        checks.append("session_restore")

        output = {
            "status": "passed",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "tk": root2.tk.call("info", "patchlevel"),
            "geometry": "1120x720",
            "checks": checks,
            "network": "blocked/offline fixtures",
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    finally:
        ausl_stats_app.AUSLStatsApp._load_initial = original_initial
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = original_lineups
        ausl_stats_app.update_all_data = original_update
        ausl_stats_app.load_database = original_load
        ausl_stats_app.fetch_live_game = original_live
        for root in roots:
            try:
                if root.winfo_exists():
                    for after_id in root.tk.call("after", "info"):
                        root.after_cancel(after_id)
                    root.destroy()
            except tk.TclError:
                pass
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
