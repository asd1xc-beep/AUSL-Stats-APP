"""Deterministic Windows/source GUI smoke for Phase 6B.

The harness uses the checked-in installed snapshot and never invokes refresh
entry points.  It exercises real Tk widgets at the supported minimum size,
then closes normally.  Pass ``--hold-seconds`` to leave the uniquely titled
window visible briefly for an external accessibility inspection.
"""

from __future__ import annotations

import argparse
import copy
import json
import platform
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tkinter as tk  # noqa: E402

from ausl_data import empty_locked_lineup_store, load_database  # noqa: E402
from ausl_facts import FactCategory, FactCollection  # noqa: E402
from ausl_session import SessionStore  # noqa: E402
import ausl_stats_app  # noqa: E402


def pump(root, predicate, *, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for the Tk/main-thread fact callback")


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
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: empty_locked_lineup_store()
    )
    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase6b-session-")
    root = tk.Tk()
    try:
        app = ausl_stats_app.AUSLStatsApp(
            root,
            session_store=SessionStore(Path(temporary.name)),
        )
        root.title("AUSL Phase 6B Smoke")
        root.geometry("1120x720")
        root.update()

        assert app.selected_game is None
        assert app._fact_collection is None
        assert "select" in app._fact_empty_message().casefold()

        app._finish_load(database)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection),
        )
        initial = app._fact_collection
        assert initial.available
        assert initial.game_id == app.selected_game.game_id
        verified_teams = {
            fact.team_code for fact in initial.facts if fact.air_ready
        }
        assert {
            app.selected_game.away_team_code,
            app.selected_game.home_team_code,
        }.issubset(verified_teams)

        app.fact_status_filter_var.set("Needs Verification")
        app._render_fact_cards()
        review_facts = app._filtered_fact_cards()
        assert review_facts and all(not fact.air_ready for fact in review_facts)
        app.fact_status_filter_var.set("Air Ready")
        app._render_fact_cards()
        air_ready = app._filtered_fact_cards()
        assert air_ready and all(fact.air_ready for fact in air_ready)

        copied_fact = air_ready[0]
        assert app.copy_fact_air_line(copied_fact.fact_id)
        assert root.clipboard_get() == copied_fact.air_copy
        assert copied_fact.character_count == len(root.clipboard_get())
        assert app._last_fact_copy_event.evidence_hash == copied_fact.evidence_hash

        assert app.copy_fact_with_source(copied_fact.fact_id)
        copied_with_source = root.clipboard_get()
        assert copied_fact.air_copy in copied_with_source
        assert "Status: VERIFIED" in copied_with_source
        assert "Data snapshot:" in copied_with_source

        blocked = review_facts[0]
        assert not app.copy_fact_air_line(blocked.fact_id)
        assert root.clipboard_get() == copied_with_source
        assert blocked.verification_state.value != "VERIFIED"

        first, second = repeat_matchup(
            ausl_stats_app.official_selected_games(database["schedule_results"])
        )
        app.on_game_changed(first)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == first.game_id,
        )
        first_ids = {fact.fact_id for fact in app._fact_collection.facts}
        app.on_game_changed(second)
        assert app._fact_collection is None
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == second.game_id,
        )
        second_ids = {fact.fact_id for fact in app._fact_collection.facts}
        assert first_ids.isdisjoint(second_ids)
        assert all(
            fact.selected_game_id == second.game_id
            for fact in app._fact_collection.facts
        )

        current_stat = next(
            fact
            for fact in app._fact_collection.facts
            if fact.air_ready and fact.category is FactCategory.RECENT_TREND
        )
        assert app.copy_fact_air_line(current_stat.fact_id)
        old_hash = current_stat.evidence_hash
        replacement = copy.deepcopy(database)
        replacement["manifest"] = dict(replacement["manifest"])
        replacement["manifest"]["updated_at"] = "2026-07-27T18:00:00+00:00"
        batting = replacement["batting_2026"]
        batting_ids = batting["player_id"].map(ausl_stats_app._manual_note_identifier)
        pitching = replacement["pitching_2026"]
        pitching_ids = pitching["player_id"].map(
            ausl_stats_app._manual_note_identifier
        )
        if batting_ids.eq(current_stat.subject_id).any():
            index = batting_ids[batting_ids.eq(current_stat.subject_id)].index[0]
            batting.loc[index, "hits"] = int(batting.loc[index, "hits"]) + 1
        elif pitching_ids.eq(current_stat.subject_id).any():
            index = pitching_ids[pitching_ids.eq(current_stat.subject_id)].index[0]
            pitching.loc[index, "strikeOuts"] = (
                int(pitching.loc[index, "strikeOuts"]) + 1
            )
        else:
            raise AssertionError("Selected current-form fact lacks its source row")
        app._finish_load(replacement)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.snapshot_timestamp
            == "2026-07-27T18:00:00+00:00",
        )
        rebuilt = next(
            fact
            for fact in app._fact_collection.facts
            if fact.fact_id == current_stat.fact_id
        )
        assert rebuilt.evidence_hash != old_hash
        assert app._last_fact_copy_event is None
        assert app.current_broadcast_note == ""

        app.set_local_offline_mode(True)
        app.request_fact_rebuild()
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == app.selected_game.game_id,
        )
        assert app._offline_mode
        assert app._fact_collection.available
        assert "Local/Offline" in app.fact_panel_status_var.get()

        assert app.fact_cards_canvas.winfo_height() >= 180
        assert app.fact_cards_canvas.cget("yscrollcommand")
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
            "selected_game": app.selected_game.game_id,
            "facts": len(app._fact_collection.facts),
            "air_ready": sum(fact.air_ready for fact in app._fact_collection.facts),
            "blocking_review": app._fact_collection.blocking_verification_count,
            "offline_mode": app._offline_mode,
            "scrollable_height": app.fact_cards_canvas.winfo_height(),
        }
        print(json.dumps(result, sort_keys=True))
        app._on_close()
    finally:
        ausl_stats_app.AUSLStatsApp._load_initial = original_initial_load
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = original_lineup_load
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass
        temporary.cleanup()


if __name__ == "__main__":
    main()
