"""Deterministic offline Windows/source GUI smoke for Phase 7A."""

from __future__ import annotations

import copy
import json
import platform
import sys
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import tkinter as tk  # noqa: E402

import ausl_data  # noqa: E402
import ausl_stats_app  # noqa: E402
from ausl_data import empty_locked_lineup_store  # noqa: E402
from ausl_enrichment import (  # noqa: E402
    EnrichmentMode,
    approve_official_note_row,
    approved_enrichment_frames,
)
from ausl_facts import FactCollection  # noqa: E402
from ausl_session import SessionStore  # noqa: E402


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


def _fixture_database():
    database = ausl_data.load_database(
        enrichment_mode=EnrichmentMode.CORE_ONLY
    )
    games = ausl_stats_app.official_selected_games(
        database["schedule_results"]
    )
    roster = database["roster"]
    batting = database[f"batting_{ausl_stats_app.CURRENT_YEAR}"]
    batting_ids = {
        _identifier(value)
        for value in batting["player_id"]
        if pd.notna(value)
    }
    selected = None
    team_players = {}
    for game in games:
        candidates = {}
        for code in (game.away_team_code, game.home_team_code):
            rows = roster[
                roster["team_code"].astype(str).str.upper().eq(code)
                & roster["roster_status"].astype(str).str.casefold().eq("active")
            ]
            player = next(
                (
                    row
                    for _, row in rows.iterrows()
                    if _identifier(row.get("player_id")) in batting_ids
                ),
                None,
            )
            if player is not None:
                candidates[code] = player
        if len(candidates) == 2:
            selected = game
            team_players = candidates
            break
    if selected is None:
        raise AssertionError("No official game has one active hitter per team")

    manifest = copy.deepcopy(database["manifest"])
    manifest["source_health"].update(
        {
            "official_game_notes": {"status": "green"},
            "media_guide": {"status": "green"},
            "split_stats": {"status": "green"},
            "optional_enrichment": {"status": "green"},
        }
    )
    raw_notes = []
    media_rows = []
    split_rows = []
    for code, player in team_players.items():
        opposing = (
            selected.home_team_code
            if code == selected.away_team_code
            else selected.away_team_code
        )
        player_id = _identifier(player["player_id"])
        player_name = str(player["player_name"])
        note_text = (
            f"{player_name} enters Game {selected.game_id} on an "
            "official AUSL milestone watch."
        )
        note = {
            "game_id": selected.game_id,
            "source_game_id": selected.game_id,
            "game_date": selected.date_time.date().isoformat(),
            "source_date": selected.date_time.date().isoformat(),
            "team_codes": f"{code},{opposing}",
            "subject_player_id": player_id,
            "subject_player_name": player_name,
            "subject_team_code": code,
            "opposing_team_code": opposing,
            "note_text": note_text,
            "note_category": "milestone_watch",
            "source_url": (
                f"https://theausl.com/notes/{selected.game_id}.pdf"
            ),
            "source_pdf": f"{selected.game_id}.pdf",
            "source_page": 4,
            "parser_version": "official-game-notes-v1",
            "normalized_hash": ausl_data._normalized_game_note_hash(note_text),
            "verification_state": "VERIFY",
            "needs_review": True,
        }
        raw_notes.append(
            approve_official_note_row(
                note,
                reviewer="Phase 7A Smoke Producer",
                approved_at="2026-07-29T16:00:00+00:00",
            )
        )
        media = {
            "entity_type": "player",
            "entity_id": player_id,
            "player_id": player_id,
            "entity_name": player_name,
            "player_name": player_name,
            "team_code": code,
            "media_guide_bio": (
                f"{player_name} has approved media-guide background."
            ),
            "source_name": "2026 AUSL Media Guide",
            "source_url": "https://theausl.com/media-guide.pdf",
            "source_pages": "49",
            "source_page": 49,
            "expected_printed_pages": "47",
            "parsed_pdf_pages": "49",
            "guide_date": "2026-06-01",
            "match_status": "verified",
            "confidence_score": 0.98,
            "needs_review": False,
            "warnings": "",
            "approval_state": "approved",
            "approval_method": "parser_exact_identity",
            "parser_version": "media-toc-v1",
        }
        media["approval_record_id"] = ausl_data.media_approval_record_id(media)
        media_rows.append(media)
        split_rows.append(
            {
                "player_id": player_id,
                "season": selected.season,
                "split_key": "last7Days",
                "split_label": "Last 7 Days",
                "plateAppearances": 12,
                "hits": 5,
                "battingAverage": 0.417,
                "opsPercentage": 1.050,
                "runsBattedIn": 4,
                "source_name": "Official AUSL Split Stats",
                "source_url": "https://theausl.com/splits",
                "imported_at": "2026-07-29T16:00:00+00:00",
            }
        )
    approved = approved_enrichment_frames(
        {
            "official_game_notes": pd.DataFrame(raw_notes),
            "media_players": pd.DataFrame(media_rows),
            "clean_media_notes": pd.DataFrame(media_rows),
            "batting_splits": pd.DataFrame(split_rows),
        },
        roster=roster,
        manifest=manifest,
    )
    database.update(approved)
    database["manifest"] = manifest
    database["enrichment_enabled"] = True
    database["enrichment_mode"] = EnrichmentMode.PRODUCER_APPROVED.value
    database["enrichment_counts"] = {
        key: int(len(frame))
        for key, frame in approved.items()
        if isinstance(frame, pd.DataFrame)
    }
    database["manual_notes"] = pd.DataFrame()
    database["refresh_attempt"] = {"state": "succeeded"}
    return database, selected


def main():
    database, selected = _fixture_database()
    replacement = copy.deepcopy(database)
    replacement["manifest"] = copy.deepcopy(database["manifest"])
    replacement["manifest"]["snapshot_id"] = "phase7a-smoke-replacement"

    originals = {
        "initial": ausl_stats_app.AUSLStatsApp._load_initial,
        "lineups": ausl_stats_app.AUSLStatsApp.load_locked_lineups,
        "update_app": ausl_stats_app.update_all_data,
        "load_app": ausl_stats_app.load_database,
        "impl": ausl_data._update_all_data_impl,
        "persist": ausl_data._persist_refresh_attempt,
        "attempt_path": ausl_data._refresh_attempt_path,
        "askyesno": ausl_stats_app.messagebox.askyesno,
        "showerror": ausl_stats_app.messagebox.showerror,
    }
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: empty_locked_lineup_store()
    )
    ausl_stats_app.messagebox.askyesno = lambda *_args, **_kwargs: True
    dialogs = []
    ausl_stats_app.messagebox.showerror = (
        lambda *args, **_kwargs: dialogs.append(args)
    )
    started = threading.Event()
    release_cancelled = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def fake_impl(progress, *, include_enrichment, cancel_token):
        nonlocal call_count
        with call_lock:
            call_count += 1
            current = call_count
        if current == 1:
            started.set()
            while not release_cancelled.wait(0.01):
                pass
            cancel_token.raise_if_cancelled()
        progress(
            "Fixture full enrichment complete."
            if include_enrichment
            else "Fixture core refresh complete."
        )
        return {}

    temporary = tempfile.TemporaryDirectory(prefix="ausl-phase7a-smoke-")
    attempt_path = Path(temporary.name) / "refresh_attempt.json"
    ausl_data._update_all_data_impl = fake_impl
    ausl_data._persist_refresh_attempt = lambda _attempt, **_kwargs: True
    ausl_data._refresh_attempt_path = lambda _output=None: attempt_path
    ausl_stats_app.update_all_data = ausl_data.update_all_data
    ausl_stats_app.load_database = (
        lambda **_kwargs: copy.deepcopy(replacement)
    )

    root = tk.Tk()
    try:
        app = ausl_stats_app.AUSLStatsApp(
            root,
            session_store=SessionStore(Path(temporary.name) / "session"),
        )
        root.title("AUSL Phase 7A Smoke — Producer Enrichment")
        root.geometry("1120x720")
        app._finish_load(copy.deepcopy(database))
        app.on_game_changed(selected)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == selected.game_id,
        )
        initial_facts = app._fact_collection
        verified_optional = [
            fact
            for fact in initial_facts.facts
            if fact.air_ready
            and (
                fact.source_record_identity.startswith("official-note:")
                or fact.source_record_identity.startswith("split:")
                or fact.source_record_identity.startswith("media-guide:")
            )
        ]
        assert {
            fact.team_code for fact in verified_optional
        } >= {selected.away_team_code, selected.home_team_code}
        assert "PRODUCER APPROVED" in app.enrichment_mode_var.get()
        assert app.full_update_button.instate(["!disabled"])

        app.update_enrichment_data()
        pump(root, started.is_set)
        assert app._data_update_in_flight
        app.cancel_data_update()
        app.update_data()
        pump(
            root,
            lambda: "Waiting for the previous refresh" in app.status_var.get(),
        )
        release_cancelled.set()
        pump(root, lambda: not app._data_update_in_flight)
        pump(
            root,
            lambda: isinstance(app._fact_collection, FactCollection)
            and app._fact_collection.game_id == selected.game_id,
        )
        assert call_count == 2
        assert app.db["manifest"]["snapshot_id"] == "phase7a-smoke-replacement"
        assert dialogs == []
        assert not list(
            (PROJECT_ROOT / "data" / "exports").glob(".core-refresh-stage-*")
        )

        app.set_local_offline_mode(True)
        assert app._offline_mode
        assert app._fact_collection.facts
        for index in range(len(app.main_tabs.tabs())):
            app.main_tabs.select(index)
            root.update()
        tab_count = len(app.main_tabs.tabs())

        print(
            json.dumps(
                {
                    "app_type": "Windows source app / real Tk / offline fixtures",
                    "approved_optional_facts": len(verified_optional),
                    "both_teams": True,
                    "cancel_then_queue": True,
                    "dialogs": len(dialogs),
                    "final_snapshot": app.db["manifest"]["snapshot_id"],
                    "full_button": True,
                    "local_offline_mode": True,
                    "network_calls": 0,
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "tabs_opened": tab_count,
                    "window": "1120x720",
                },
                sort_keys=True,
            )
        )
        app._on_close()
    finally:
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass
        ausl_stats_app.AUSLStatsApp._load_initial = originals["initial"]
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = originals["lineups"]
        ausl_stats_app.update_all_data = originals["update_app"]
        ausl_stats_app.load_database = originals["load_app"]
        ausl_data._update_all_data_impl = originals["impl"]
        ausl_data._persist_refresh_attempt = originals["persist"]
        ausl_data._refresh_attempt_path = originals["attempt_path"]
        ausl_stats_app.messagebox.askyesno = originals["askyesno"]
        ausl_stats_app.messagebox.showerror = originals["showerror"]
        temporary.cleanup()


if __name__ == "__main__":
    main()
