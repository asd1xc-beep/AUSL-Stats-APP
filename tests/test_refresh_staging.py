from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

import ausl_data


CORE_FILENAMES = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
    "update_manifest.json",
)


def configure_valid_core_refresh(monkeypatch, output):
    monkeypatch.setattr(ausl_data, "export_dir", lambda: output)
    monkeypatch.setattr(ausl_data, "_get_json", lambda _path: {})
    monkeypatch.setattr(
        ausl_data,
        "roster_frame",
        lambda _payload, year: pd.DataFrame(
            [{"player_id": year, "player_name": f"Player {year}"}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "stat_frames",
        lambda _payload, year: (
            pd.DataFrame([{"player_id": year, "player_name": f"Player {year}"}]),
            pd.DataFrame([{"player_id": year, "player_name": f"Player {year}"}]),
            pd.DataFrame([{"player_id": year, "player_name": f"Player {year}"}]),
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "career_batting",
        lambda _frames: pd.DataFrame([{"player_id": 1}]),
    )
    monkeypatch.setattr(
        ausl_data,
        "career_pitching",
        lambda _frames: pd.DataFrame([{"player_id": 1}]),
    )
    monkeypatch.setattr(
        ausl_data,
        "career_fielding",
        lambda _frames: pd.DataFrame([{"player_id": 1}]),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda: pd.DataFrame(
            [
                {
                    "team_code": "CHI",
                    "seasonId": 369,
                    "standingsTypeLk": "SEASON",
                    "wins": 1,
                    "losses": 0,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_schedule_frame",
        lambda: pd.DataFrame(
            [
                {
                    "game_id": 9001,
                    "game_date": "2026-07-20T19:00:00-04:00",
                    "away_team_code": "CHI",
                    "home_team_code": "CAR",
                    "status": "scheduled",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        ausl_data, "ensure_manual_notes_file", lambda: output / "manual.csv"
    )

    def fake_write(path, sheets):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "|".join(
            f"{name}:{len(frame)}" for name, frame in sheets.items()
        )
        path.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", fake_write)


def seed_last_known_good(output):
    output.mkdir(parents=True, exist_ok=True)
    original = {}
    for filename in CORE_FILENAMES:
        payload = f"last-known-good:{filename}".encode("utf-8")
        (output / filename).write_bytes(payload)
        original[filename] = payload
    return original


def test_standings_failure_preserves_entire_last_known_good_core_snapshot(
    monkeypatch, tmp_path
):
    originals = seed_last_known_good(tmp_path)
    configure_valid_core_refresh(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda: (_ for _ in ()).throw(RuntimeError("fixture standings outage")),
    )

    with pytest.raises(ausl_data.CoreRefreshValidationError, match="standings"):
        ausl_data.update_all_data()

    assert {
        filename: (tmp_path / filename).read_bytes()
        for filename in CORE_FILENAMES
    } == originals


def test_core_promotion_failure_rolls_back_every_already_promoted_file(
    monkeypatch, tmp_path
):
    originals = seed_last_known_good(tmp_path)
    configure_valid_core_refresh(monkeypatch, tmp_path)
    original_replace = os.replace
    failure_seen = False

    def fail_mid_promotion(source, destination):
        nonlocal failure_seen
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            not failure_seen
            and destination_path == tmp_path / "ausl_career_stats.xlsx"
            and source_path.parent.name.startswith(".core-refresh-stage-")
        ):
            failure_seen = True
            raise OSError("fixture promotion failure")
        original_replace(source, destination)

    monkeypatch.setattr(ausl_data.os, "replace", fail_mid_promotion)

    with pytest.raises(OSError, match="fixture promotion failure"):
        ausl_data.update_all_data()

    assert failure_seen is True
    assert {
        filename: (tmp_path / filename).read_bytes()
        for filename in CORE_FILENAMES
    } == originals


def test_failed_optional_sources_do_not_replace_their_last_known_good_files(
    monkeypatch, tmp_path
):
    configure_valid_core_refresh(monkeypatch, tmp_path)
    optional_files = {
        "ausl_batting_splits.xlsx": b"last-known-good batting splits",
        "ausl_pitching_splits.xlsx": b"last-known-good pitching splits",
        "ausl_fielding_splits.xlsx": b"last-known-good fielding splits",
        "official_game_notes.xlsx": b"last-known-good official notes",
        "clean_media_guide_notes.xlsx": b"last-known-good media notes",
    }
    for filename, payload in optional_files.items():
        (tmp_path / filename).write_bytes(payload)
    monkeypatch.setattr(
        ausl_data,
        "fetch_split_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("fixture split outage")
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_official_game_notes_frame",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("fixture note outage")
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_media_guide_frames",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("fixture media outage")
        ),
    )

    ausl_data.update_all_data(include_enrichment=True)

    assert {
        filename: (tmp_path / filename).read_bytes()
        for filename in optional_files
    } == optional_files
