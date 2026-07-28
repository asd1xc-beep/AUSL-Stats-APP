"""Deterministic offline Windows/source GUI smoke for Phase 6C."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tkinter as tk  # noqa: E402

from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_facts import FactCollection  # noqa: E402
from ausl_rundown import ReconciliationState  # noqa: E402
from ausl_session import SessionStore  # noqa: E402
import ausl_stats_app  # noqa: E402


def pump(root, predicate, *, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread callback")


def repeat_matchup(games):
    groups = defaultdict(list)
    for game in games:
        groups[tuple(sorted((game.away_team_code, game.home_team_code)))].append(
            game
        )
    candidates = [items for items in groups.values() if len(items) >= 2]
    if not candidates:
        raise AssertionError("Checked-in schedule has no repeat-opponent fixture")
    return sorted(candidates[0], key=lambda game: (game.date_time, game.game_id))[:2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    args = parser.parse_args()

    database = load_database(include_enrichment=False)
    original_initial_load = ausl_stats_app.AUSLStatsApp._load_initial
    original_lineup_load = ausl_stats_app.AUSLStatsApp.load_locked_lineups
    original_export_dir = ausl_stats_app.export_dir
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: empty_locked_lineup_store()
    )
    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase6c-smoke-")
    private_root = Path(temporary.name)
    ausl_stats_app.export_dir = lambda: private_root
    root = tk.Tk()
    try:
        app = ausl_stats_app.AUSLStatsApp(
            root,
            session_store=SessionStore(private_root / "session"),
        )
        root.title("AUSL Phase 6C Smoke")
        root.geometry("1120x720")
        root.update()

        assert app.selected_game is None
        assert app._current_rundown_state(create=False) is None
        app._finish_load(database)
        pump(root, lambda: isinstance(app._fact_collection, FactCollection))
        first_game = app.selected_game
        facts = app._fact_collection.facts
        ready_by_team = {}
        for item in facts:
            if item.air_ready and item.team_code not in ready_by_team:
                ready_by_team[item.team_code] = item
        first_team_fact = ready_by_team[first_game.away_team_code]
        second_team_fact = ready_by_team[first_game.home_team_code]
        review_fact = next(item for item in facts if not item.air_ready)
        unpinned_used = next(
            item
            for item in facts
            if item.air_ready
            and item.fact_id
            not in {first_team_fact.fact_id, second_team_fact.fact_id}
        )

        assert app.pin_fact_to_rundown(first_team_fact.fact_id)
        assert app.pin_fact_to_rundown(second_team_fact.fact_id)
        assert app.pin_fact_to_rundown(review_fact.fact_id)
        state = app._current_rundown_state()
        assert len(state.active_air_ready_entries) == 2
        assert len(state.review_entries) == 1
        assert {
            entry.fact_snapshot.team_code
            for entry in state.active_air_ready_entries
        } == {first_game.away_team_code, first_game.home_team_code}
        original_second_entry = next(
            entry
            for entry in state.active_entries
            if entry.fact_id == second_team_fact.fact_id
        )
        assert app.move_rundown_entry(original_second_entry.entry_id, -1)
        assert app._current_rundown_state().active_entries[0].fact_id == second_team_fact.fact_id

        app.rundown_break_target_var.set("30")
        assert app.apply_rundown_break_target()
        state = app._current_rundown_state()
        assert state.break_target_seconds == 30
        assert state.remaining_read_seconds == sum(
            entry.read_time_seconds for entry in state.active_air_ready_entries
        )

        first_entry = next(
            entry
            for entry in state.active_entries
            if entry.fact_id == first_team_fact.fact_id
        )
        assert app.mark_rundown_entry_used(first_entry.entry_id)
        assert app.mark_fact_used_from_card(unpinned_used.fact_id)
        app.fact_status_filter_var.set("Air Ready")
        app.fact_show_used_var.set(False)
        hidden_ids = {fact.fact_id for fact in app._filtered_fact_cards()}
        assert first_team_fact.fact_id not in hidden_ids
        assert unpinned_used.fact_id not in hidden_ids
        app.fact_show_used_var.set(True)
        shown_ids = {fact.fact_id for fact in app._filtered_fact_cards()}
        assert first_team_fact.fact_id in shown_ids
        assert unpinned_used.fact_id in shown_ids
        assert len(app._current_rundown_state().used_history) == 2

        assert app.undo_rundown_used(first_team_fact.fact_id)
        assert not app._ensure_rundown_session().is_fact_used(
            first_game.game_id, first_team_fact.fact_id
        )
        assert any(
            entry.fact_id == first_team_fact.fact_id
            for entry in app._current_rundown_state().active_entries
        )

        repeat_first, repeat_second = repeat_matchup(
            ausl_stats_app.official_selected_games(database["schedule_results"])
        )
        app.on_game_changed(repeat_first)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == repeat_first.game_id,
        )
        repeat_fact = next(item for item in app._fact_collection.facts if item.air_ready)
        assert app.pin_fact_to_rundown(repeat_fact.fact_id)
        repeat_entry_id = app._current_rundown_state().active_entries[0].entry_id
        app.on_game_changed(repeat_second)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == repeat_second.game_id,
        )
        second_state = app._current_rundown_state(create=False)
        assert second_state is not None
        assert second_state.active_entries == ()
        assert second_state.used_history == ()
        app.on_game_changed(repeat_first)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == repeat_first.game_id,
        )
        assert app._current_rundown_state().active_entries[0].entry_id == repeat_entry_id

        pinned = app._current_rundown_state().active_entries[0]
        current = next(
            item for item in app._fact_collection.facts if item.fact_id == pinned.fact_id
        )
        latest = replace(current, air_copy=current.air_copy + " Source update.")
        rebuilt = FactCollection(
            game_id=app._fact_collection.game_id,
            snapshot_timestamp=app._fact_collection.snapshot_timestamp,
            database_version="phase6c-smoke-changed",
            facts=tuple(
                latest if item.fact_id == latest.fact_id else item
                for item in app._fact_collection.facts
            ),
            available=True,
            empty_reason="",
        )
        generation = app._fact_build_generation
        assert app._finish_fact_rebuild(
            rebuilt,
            generation,
            repeat_first.game_id,
            id(app.db),
        )
        reconciled = app._current_rundown_state().active_entries[0]
        assert reconciled.fact_snapshot.air_copy == current.air_copy
        assert reconciled.latest_fact is latest
        assert reconciled.reconciliation_state is ReconciliationState.SOURCE_CHANGED
        assert not reconciled.is_air_ready_for_timing

        assert app.export_rundown()
        exported = list(
            (private_root / "game_packets" / "rundowns").glob("*_rundown.txt")
        )
        assert len(exported) == 1
        export_text = exported[0].read_text(encoding="utf-8")
        assert f"OFFICIAL GAME ID: {repeat_first.game_id}" in export_text
        assert "ACTIVE AIR-READY RUNDOWN" in export_text
        assert "NEEDS VERIFICATION" in export_text
        assert "USED-ON-AIR HISTORY" in export_text

        app.set_local_offline_mode(True)
        assert app._offline_mode
        assert app.apply_rundown_break_target()
        app.game_day_views.select(1)
        root.update()
        rundown_height = app.rundown_canvas.winfo_height()
        assert rundown_height >= 100, rundown_height
        before = app.rundown_canvas.yview()
        app.rundown_container.event_generate("<MouseWheel>", delta=-120)
        root.update()
        after = app.rundown_canvas.yview()
        assert after != before
        for index in range(len(app.main_tabs.tabs())):
            app.main_tabs.select(index)
            root.update()
        app.main_tabs.select(0)
        root.update()

        if args.hold_seconds > 0:
            deadline = time.monotonic() + min(args.hold_seconds, 60.0)
            while time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)

        result = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "window": root.title(),
            "geometry": f"{root.winfo_width()}x{root.winfo_height()}",
            "tabs_opened": len(app.main_tabs.tabs()),
            "game": repeat_first.game_id,
            "active": len(app._current_rundown_state().active_air_ready_entries),
            "review": len(app._current_rundown_state().review_entries),
            "used": len(app._current_rundown_state().used_history),
            "target": app._current_rundown_state().break_target_seconds,
            "offline_mode": app._offline_mode,
            "export": exported[0].name,
            "scroll_before": before,
            "scroll_after": after,
        }
        print(json.dumps(result, sort_keys=True))
        app._on_close()
    finally:
        ausl_stats_app.AUSLStatsApp._load_initial = original_initial_load
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = original_lineup_load
        ausl_stats_app.export_dir = original_export_dir
        temporary.cleanup()
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
