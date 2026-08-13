"""Offline real-Tk smoke for approved Phase 7E college data and connections."""

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

import tkinter as tk  # noqa: E402

import ausl_stats_app  # noqa: E402
from ausl_college_store import CollegeStore  # noqa: E402
from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_enrichment import EnrichmentMode  # noqa: E402
from ausl_facts import FactCategory, FactCollection  # noqa: E402
from ausl_session import SessionLifecycle, SessionStore  # noqa: E402


def pump(root, predicate, *, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread callback")


def _identifier(value):
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _row(database, player_id):
    rows = database["roster"][
        database["roster"]["player_id"].map(_identifier).eq(player_id)
    ]
    if len(rows) != 1:
        raise AssertionError(f"Exact roster identity unavailable: {player_id}")
    return rows.iloc[0]


def _select_player(app, database, player_id):
    app.selected_player_id = int(player_id)
    app.render_player(_row(database, player_id))
    assert app.render_college_resume()
    assert app._current_college_view.player_id == player_id
    return app._current_college_view


def _database():
    database = load_database(enrichment_mode=EnrichmentMode.CORE_ONLY)
    loaded = CollegeStore.default().load(EnrichmentMode.PRODUCER_APPROVED)
    assert loaded.available and loaded.connection_approval is not None
    assert len(loaded.envelope.resumes) == 118
    assert len(loaded.connection_approval.connections.candidates) == 8
    database["_college_load_result"] = loaded
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
    ausl_stats_app.fetch_live_game = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Phase 7E smoke attempted network access")
    )

    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase7e-smoke-")
    roots = []
    checks = []
    try:
        root = tk.Tk()
        roots.append(root)
        root.geometry("1120x720")
        root.title("AUSL Phase 7E Smoke")
        app = ausl_stats_app.AUSLStatsApp(
            root, session_store=SessionStore(Path(temporary.name) / "session")
        )
        app._finish_load(copy.deepcopy(database))
        root.update()

        tabs = tuple(app.main_tabs.tab(tab, "text") for tab in app.main_tabs.tabs())
        assert len(tabs) == 9 and any("College" in tab for tab in tabs), tabs
        for tab in app.main_tabs.tabs():
            app.main_tabs.select(tab)
            root.update_idletasks()
        checks.append("nine_tabs_1120x720")

        connected = _select_player(app, database, "1075")
        assert connected.connection_fields
        connection = connected.connection_fields[0]
        assert app.copy_college_connection(connection.connection_id)
        assert root.clipboard_get() == connection.copy_text
        assert app.copy_college_connection(connection.connection_id, with_source=True)
        assert "Status: APPROVED" in root.clipboard_get()
        checks.append("approved_connection_copy_and_source")

        no_connection = _select_player(app, database, "10")
        assert no_connection.connection_fields == ()
        partial = _select_player(app, database, "1322")
        assert partial.completeness == "Partial"
        checks.append("no_connection_and_partial_states")

        # Find an exact official game whose current roster contains one of the
        # approved connection subjects. The fact worker must do no network I/O.
        college_fact = None
        for game in ausl_stats_app.official_selected_games(database["schedule_results"]):
            app.on_game_changed(game)
            pump(
                root,
                lambda current=game: isinstance(app._fact_collection, FactCollection)
                and app._fact_collection.game_id == current.game_id,
            )
            college_fact = next(
                (
                    fact
                    for fact in app._fact_collection.facts
                    if fact.category is FactCategory.COLLEGE_CONNECTION
                ),
                None,
            )
            if college_fact is not None:
                break
        assert college_fact is not None and college_fact.air_ready
        assert app.copy_fact_air_line(college_fact.fact_id)
        assert root.clipboard_get() == college_fact.air_copy
        assert app.copy_fact_with_source(college_fact.fact_id)
        assert len(college_fact.provenance) >= 1
        checks.append("game_day_connection_fact")

        assert app.pin_fact_to_rundown(college_fact.fact_id)
        state = app._current_rundown_state()
        entry = next(item for item in state.active_entries if item.fact_id == college_fact.fact_id)
        assert entry.fact_snapshot.evidence_hash == college_fact.evidence_hash
        assert app.mark_rundown_entry_used(entry.entry_id)
        used = app._current_rundown_state().used_history[-1]
        assert used.fact_snapshot.evidence_hash == college_fact.evidence_hash
        checks.append("pin_used_exact_evidence")

        app.set_local_offline_mode(True)
        app.request_fact_rebuild()
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == app.selected_game.game_id,
        )
        assert any(
            fact.category is FactCategory.COLLEGE_CONNECTION
            for fact in app._fact_collection.facts
        )
        checks.append("local_offline_rebuild")

        assert app._flush_session_save(lifecycle=SessionLifecycle.CLOSED_CLEANLY)
        output = {
            "checks": checks,
            "college_connections": 8,
            "college_resumes": 118,
            "geometry": "1120x720",
            "network": "blocked/offline fixtures",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "status": "passed",
            "tk": root.tk.call("info", "patchlevel"),
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
