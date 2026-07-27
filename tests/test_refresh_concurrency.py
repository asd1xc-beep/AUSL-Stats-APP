from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

import ausl_data


def _configure_thread_identified_refresh(monkeypatch, output):
    monkeypatch.setattr(ausl_data, "export_dir", lambda: output)
    monkeypatch.setattr(ausl_data, "load_manual_notes", lambda: pd.DataFrame())

    def thread_tag():
        return threading.current_thread().name

    def fake_get_json(_path, **_kwargs):
        return {"tag": thread_tag()}

    def roster_frame(payload, year):
        count = 1 if payload["tag"] == "cancelled-refresh" else 2
        return pd.DataFrame(
            [
                {
                    "player_id": f"{payload['tag']}-{year}-{index}",
                    "player_name": f"{payload['tag']} Player {index}",
                    "marker": payload["tag"],
                }
                for index in range(count)
            ]
        )

    def stat_frames(payload, year):
        frame = pd.DataFrame(
            [
                {
                    "player_id": f"{payload['tag']}-{year}",
                    "marker": payload["tag"],
                }
            ]
        )
        return frame.copy(), frame.copy(), frame.copy()

    monkeypatch.setattr(ausl_data, "_get_json", fake_get_json)
    monkeypatch.setattr(ausl_data, "roster_frame", roster_frame)
    monkeypatch.setattr(ausl_data, "stat_frames", stat_frames)
    monkeypatch.setattr(
        ausl_data,
        "career_batting",
        lambda frames: pd.DataFrame(
            [{"player_id": "career", "marker": frames[-1].iloc[0]["marker"]}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "career_pitching",
        lambda frames: pd.DataFrame(
            [{"player_id": "career", "marker": frames[-1].iloc[0]["marker"]}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "career_fielding",
        lambda frames: pd.DataFrame(
            [{"player_id": "career", "marker": frames[-1].iloc[0]["marker"]}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda **_kwargs: pd.DataFrame(
            [
                {
                    "team_code": "CHI",
                    "seasonId": 369,
                    "standingsTypeLk": "SEASON",
                    "marker": thread_tag(),
                }
            ]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_schedule_frame",
        lambda **_kwargs: pd.DataFrame(
            [
                {
                    "game_id": 9001,
                    "game_date": "2026-07-20T19:00:00-04:00",
                    "away_team_code": "CHI",
                    "home_team_code": "CAR",
                    "status": "scheduled",
                    "marker": thread_tag(),
                }
            ]
        ),
    )


def test_cancelled_commit_finishes_before_newer_refresh_and_newer_snapshot_wins(
    monkeypatch, tmp_path
):
    _configure_thread_identified_refresh(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ausl_data, "_CORE_REFRESH_COMMIT_LOCK", threading.Lock(), raising=False
    )
    original_write = ausl_data._write_excel_atomic
    old_entered_staging = threading.Event()
    release_old_staging = threading.Event()
    writes = []

    def blocking_write(path, sheets):
        tag = threading.current_thread().name
        writes.append((tag, Path(path).name))
        if tag == "cancelled-refresh" and not old_entered_staging.is_set():
            old_entered_staging.set()
            assert release_old_staging.wait(5)
        original_write(path, sheets)

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", blocking_write)
    old_token = ausl_data.CancelToken()
    new_token = ausl_data.CancelToken()
    outcomes = {}
    new_progress = []

    def run_old():
        try:
            outcomes["old"] = ausl_data.update_all_data(cancel_token=old_token)
        except Exception as exc:  # noqa: BLE001 - asserted below
            outcomes["old_exc"] = exc

    def run_new():
        try:
            outcomes["new"] = ausl_data.update_all_data(
                new_progress.append, cancel_token=new_token
            )
        except Exception as exc:  # noqa: BLE001 - asserted below
            outcomes["new_exc"] = exc

    old_worker = threading.Thread(target=run_old, name="cancelled-refresh")
    old_worker.start()
    assert old_entered_staging.wait(5), "old refresh never entered staging"

    old_token.cancel()
    new_worker = threading.Thread(target=run_new, name="replacement-refresh")
    new_worker.start()

    assert not any(tag == "replacement-refresh" for tag, _name in writes)
    release_old_staging.set()
    old_worker.join(10)
    new_worker.join(10)

    assert not old_worker.is_alive()
    assert not new_worker.is_alive()
    assert "old_exc" not in outcomes
    assert "new_exc" not in outcomes
    assert any("waiting for the previous refresh" in message.lower() for message in new_progress)

    manifest = json.loads((tmp_path / "update_manifest.json").read_text(encoding="utf-8"))
    database = ausl_data.load_database(include_enrichment=False)
    assert manifest["current_roster_players"] == 2
    assert set(database["roster"]["marker"]) == {"replacement-refresh"}
    for key in (
        "batting_2025",
        "pitching_2025",
        "fielding_2025",
        "batting_2026",
        "pitching_2026",
        "fielding_2026",
        "career_batting",
        "career_pitching",
        "career_fielding",
        "standings",
        "schedule_results",
    ):
        assert set(database[key]["marker"]) == {"replacement-refresh"}, key
    assert not list(tmp_path.glob(".core-refresh-stage-*"))
    assert not list(tmp_path.glob(".core-refresh-backup-*"))


def test_cancelled_worker_waiting_for_commit_lock_exits_without_core_writes(
    monkeypatch, tmp_path
):
    _configure_thread_identified_refresh(monkeypatch, tmp_path)
    commit_lock = threading.Lock()
    monkeypatch.setattr(
        ausl_data, "_CORE_REFRESH_COMMIT_LOCK", commit_lock, raising=False
    )
    token = ausl_data.CancelToken()
    waiting = threading.Event()
    outcome = {}

    def progress(message):
        if "waiting for the previous refresh" in message.lower():
            waiting.set()

    def run():
        try:
            ausl_data.update_all_data(progress, cancel_token=token)
        except Exception as exc:  # noqa: BLE001 - asserted below
            outcome["exc"] = exc

    commit_lock.acquire()
    worker = threading.Thread(target=run, name="cancelled-refresh")
    worker.start()
    assert waiting.wait(5), "worker never reached the serialized commit section"
    token.cancel()
    commit_lock.release()
    worker.join(10)

    assert not worker.is_alive()
    assert isinstance(outcome.get("exc"), ausl_data.RefreshCancelled)
    assert not any(
        (tmp_path / name).exists()
        for name in (
            "ausl_rosters.xlsx",
            "ausl_season_stats.xlsx",
            "ausl_career_stats.xlsx",
            "ausl_team_context.xlsx",
            "update_manifest.json",
        )
    )
    assert not list(tmp_path.glob(".core-refresh-stage-*"))
    assert not list(tmp_path.glob(".core-refresh-backup-*"))
