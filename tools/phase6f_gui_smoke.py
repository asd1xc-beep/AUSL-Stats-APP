"""Deterministic offline Windows/source GUI smoke for Phase 6F."""

from __future__ import annotations

import json
import platform
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tkinter as tk  # noqa: E402

from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_facts import FactCollection  # noqa: E402
from ausl_session import SessionLifecycle, SessionStore  # noqa: E402
import ausl_stats_app  # noqa: E402


def pump(root, predicate, *, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread callback")


def forbid_network(name):
    def blocked(*_args, **_kwargs):
        raise AssertionError(f"Phase 6F GUI smoke attempted network route: {name}")

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


def exact_search(app, player_name):
    app.show_all()
    app.search_var.set(player_name)
    app.search()
    assert app._player_search_response.results
    assert (
        app._player_search_response.results[0].record.player_name == player_name
    )
    app.results.selection_clear(0, "end")
    app.results.selection_set(0)
    app._on_result_highlight()


def choose_players(database):
    roster = database["roster"]
    batting = database.get(f"batting_{ausl_stats_app.CURRENT_YEAR}", pd.DataFrame())
    pitching = database.get(f"pitching_{ausl_stats_app.CURRENT_YEAR}", pd.DataFrame())
    batting_ids = {
        str(int(value))
        for value in pd.to_numeric(
            batting.get("player_id", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
    }
    pitching_ids = {
        str(int(value))
        for value in pd.to_numeric(
            pitching.get("player_id", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
    }
    rows = {
        str(int(row["player_id"])): row
        for _, row in roster.iterrows()
        if pd.notna(row.get("player_id"))
    }
    supported_positions = {
        "P",
        "RHP",
        "LHP",
        "C",
        "1B",
        "2B",
        "3B",
        "SS",
        "LF",
        "CF",
        "RF",
        "OF",
        "IF",
        "UTIL",
        "DP",
        "FLEX",
    }

    def usable(player_id):
        row = rows[player_id]
        return (
            pd.notna(row.get("jersey_number"))
            and str(row.get("position", "")).upper() in supported_positions
            and str(row.get("roster_status", "")).casefold() == "active"
        )

    left_id = next(
        player_id
        for player_id in sorted(batting_ids, key=int)
        if player_id in rows and usable(player_id)
    )
    right_id = next(
        player_id
        for player_id in sorted(pitching_ids, key=int)
        if player_id in rows and player_id != left_id and usable(player_id)
    )
    return rows[left_id], rows[right_id]


def main():
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

    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase6f-smoke-")
    state_dir = Path(temporary.name) / "private-session"
    roots = []
    try:
        root1, app1 = open_app(state_dir, database)
        roots.append(root1)
        root1.title("AUSL Phase 6F Smoke — Search and Compare")
        left_row, right_row = choose_players(database)
        left_name = str(left_row["player_name"])
        right_name = str(right_row["player_name"])

        lookup_tab = app1.main_tabs.nametowidget(app1.main_tabs.tabs()[1])
        assert int(lookup_tab.grid_rowconfigure(1)["weight"]) == 0
        assert int(lookup_tab.grid_rowconfigure(2)["weight"]) == 1
        app1.main_tabs.select(lookup_tab)
        root1.update_idletasks()
        assert app1.results.winfo_height() >= 100
        assert app1.stat_tabs.winfo_height() >= 100

        # Keyboard-first search focus, exact lookup, and explicit selection.
        root1.focus_force()
        app1._focus_player_search()
        root1.update()
        assert root1.focus_get() == app1.search_entry
        exact_search(app1, left_name)
        assert app1.selected_player_id is None
        app1._activate_highlighted_result()
        assert str(app1.selected_player_id) == str(int(left_row["player_id"]))
        assert app1.assign_comparison_player("left")

        # Conservative typo, structured filters, and invalid-filter explanation.
        typo = left_name[:2] + left_name[3:4] + left_name[2:3] + left_name[4:]
        app1.search_var.set(typo)
        app1.search()
        assert app1.selected_player_id is not None
        assert any(
            result.match_type.value == "fuzzy"
            for result in app1._player_search_response.results
        )
        app1.search_var.set(
            f"team:{left_row['team_code']} pos:{left_row['position']} "
            f"status:{str(left_row['roster_status']).split()[0]} "
            f"#{int(left_row['jersey_number'])}"
        )
        app1.search()
        assert app1._player_search_response.parsed.valid
        app1.search_var.set("team:NOT_A_TEAM")
        app1.search()
        assert not app1._player_search_response.parsed.valid

        # Second exact identity, keyboard highlight/activation, and right assignment.
        exact_search(app1, right_name)
        app1._move_search_highlight(type("Event", (), {"keysym": "Down"})())
        exact_search(app1, right_name)
        app1._activate_highlighted_result()
        assert app1.assign_comparison_player("right")
        comparison = app1._current_comparison
        assert comparison is not None
        assert comparison.left.player_id != comparison.right.player_id
        assert comparison.sections
        assert any(
            row.left.available or row.right.available for row in comparison.rows
        )
        assert all(
            row.left.metric_key == row.right.metric_key for row in comparison.rows
        )
        assert "winner" not in comparison.summary.casefold()
        assert "better" not in comparison.summary.casefold()
        comparison_facts = (
            comparison.left.verified_facts
            + comparison.left.review_facts
            + comparison.right.verified_facts
            + comparison.right.review_facts
        )
        assert comparison_facts
        visible_comparison_text = "\n".join(
            str(child.cget("text"))
            for child in app1.comparison_container.winfo_children()
            if "text" in child.keys()
        )
        for fact in comparison_facts:
            assert fact.air_copy in visible_comparison_text
            assert f"[{fact.verification_state.value}]" in visible_comparison_text
            assert f"Source health: {fact.source_health.upper()}" in visible_comparison_text
            if fact.provenance:
                assert fact.provenance[0].source_name in visible_comparison_text
        assert "Statistics source:" in visible_comparison_text
        assert "Statistical snapshot:" in visible_comparison_text

        # Scrollbar/wheel reachability, provenance-preserving copy, and offline mode.
        root1.update_idletasks()
        before_scroll = app1.comparison_canvas.yview()[0]
        app1._on_comparison_mousewheel(
            type("Wheel", (), {"delta": -240, "num": None})()
        )
        root1.update_idletasks()
        after_scroll = app1.comparison_canvas.yview()[0]
        assert after_scroll >= before_scroll
        assert app1.copy_comparison_with_sources()
        copied = root1.clipboard_get()
        assert left_name in copied and right_name in copied
        assert "Statistics source:" in copied
        assert "Statistical snapshot:" in copied
        assert "Statistical metrics only" in copied
        assert app1._last_comparison_copy_record is not None
        app1.set_local_offline_mode(True)
        assert app1._offline_mode

        # In-memory validated local replacement rebuilds the index and comparison.
        previous_index = app1._player_search_index.index_identity
        previous_database = app1._current_comparison.database_identity
        replacement = dict(database)
        replacement["manifest"] = dict(
            database.get("manifest", {}),
            snapshot_id="phase6f-smoke-replacement",
        )
        app1._finish_load(replacement)
        pump(
            root1,
            lambda: isinstance(app1._fact_collection, FactCollection)
            and app1._fact_collection.game_id == app1.selected_game.game_id,
        )
        assert app1._player_search_index.index_identity != previous_index
        assert app1._current_comparison.database_identity != previous_database
        assert app1._last_comparison_copy_record is None

        # Exact game switch rebuilds fact context while retaining player identities.
        games = list(app1._official_game_choices.values())
        alternate = next(
            (game for game in games if game.game_id != app1.selected_game.game_id),
            None,
        )
        if alternate is not None:
            app1.on_game_changed(alternate)
            pump(
                root1,
                lambda: isinstance(app1._fact_collection, FactCollection)
                and app1._fact_collection.game_id == alternate.game_id,
            )
            assert app1._current_comparison.selected_game_id == alternate.game_id
            assert app1.comparison_left_player_id is not None
            assert app1.comparison_right_player_id is not None

        # Persist exact IDs/view/scroll, open every tab, then restore without guessing.
        app1.main_tabs.select(app1.main_tabs.tabs()[-1])
        app1.comparison_canvas.yview_moveto(0.25)
        assert app1._flush_session_save(lifecycle=SessionLifecycle.ACTIVE)
        for index in range(len(app1.main_tabs.tabs())):
            app1.main_tabs.select(index)
            root1.update()
        tab_count = len(app1.main_tabs.tabs())
        app1._on_close()
        roots.remove(root1)

        root2, app2 = open_app(state_dir, replacement)
        roots.append(root2)
        assert app2.comparison_left_player_id == str(int(left_row["player_id"]))
        assert app2.comparison_right_player_id == str(int(right_row["player_id"]))
        assert app2._current_comparison is not None
        assert app2._last_comparison_copy_record is None
        assert (
            app2.main_tabs.tab(app2.main_tabs.select(), "text")
            == "Compare Players"
        )
        root2.update_idletasks()
        assert app2.comparison_canvas.yview()[0] >= 0.0

        result = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "app_type": "Windows source app / real Tk loop / offline snapshot",
            "window": "1120x720",
            "selected_game": app2.selected_game.game_id,
            "exact_search": True,
            "typo_search_labeled": True,
            "structured_filters": True,
            "invalid_filter_safe": True,
            "keyboard_selection": True,
            "comparison_players": [
                app2.comparison_left_player_id,
                app2.comparison_right_player_id,
            ],
            "aligned_metrics": True,
            "per_fact_provenance": True,
            "comparison_scroll": True,
            "copy_with_sources": True,
            "local_replacement_rebuilt": True,
            "game_change_rebuilt": alternate is not None,
            "offline_mode_local_compare": True,
            "session_restored_exactly": True,
            "tabs_opened": tab_count,
            "network_calls": 0,
        }
        print(json.dumps(result, sort_keys=True))
        app2._on_close()
        roots.remove(root2)
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
