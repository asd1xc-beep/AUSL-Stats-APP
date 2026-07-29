from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

import ausl_data
import ausl_stats_app
from ausl_enrichment import EnrichmentMode


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.state = "normal"

    def configure(self, state=None, **_kwargs):
        if state is not None:
            self.state = state


class ImmediateThread:
    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def bare_app():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.status_var = FakeVar()
    app.enrichment_mode_var = FakeVar()
    app.update_button = FakeButton()
    app.full_update_button = FakeButton()
    app.cancel_update_button = FakeButton()
    app._data_update_in_flight = False
    app._initial_load_in_flight = False
    app._offline_mode = False
    app._data_update_cancel_token = None
    app._data_update_mode = "core"
    app.db = {}
    app._log_event = lambda *_args, **_kwargs: None
    app._ensure_main_thread_dispatch = lambda: None
    app._post_main_thread = lambda callback, *args: callback(*args)
    app._refresh_game_day_if_allowed = lambda: None
    app._record_change_refresh_outcome = lambda *_args, **_kwargs: None
    app.refresh_game_day_dashboard = lambda: None
    return app


def test_offline_mode_blocks_full_refresh_before_confirmation_or_token(monkeypatch):
    app = bare_app()
    app._offline_mode = True
    confirmations = []
    app.network_requests_permitted = lambda *_args, **_kwargs: False
    monkeypatch.setattr(
        ausl_stats_app.messagebox,
        "askyesno",
        lambda *_args, **_kwargs: confirmations.append(True) or True,
    )

    app.update_enrichment_data()

    assert confirmations == []
    assert app._data_update_cancel_token is None
    assert app._data_update_in_flight is False


def test_full_refresh_requires_explicit_confirmation(monkeypatch):
    app = bare_app()
    app.network_requests_permitted = lambda *_args, **_kwargs: True
    monkeypatch.setattr(
        ausl_stats_app.messagebox, "askyesno", lambda *_args, **_kwargs: False
    )

    app.update_enrichment_data()

    assert app._data_update_cancel_token is None
    assert app._data_update_in_flight is False


def test_full_refresh_uses_producer_approved_reload_and_reports_counts(monkeypatch):
    app = bare_app()
    app.network_requests_permitted = lambda *_args, **_kwargs: True
    monkeypatch.setattr(
        ausl_stats_app.messagebox, "askyesno", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(ausl_stats_app.threading, "Thread", ImmediateThread)
    calls = []
    data = {
        "roster": pd.DataFrame([{"player_id": 1}]),
        "enrichment_mode": EnrichmentMode.PRODUCER_APPROVED.value,
        "enrichment_counts": {
            "official_game_notes": 2,
            "media_players": 3,
            "batting_splits": 4,
            "pitching_splits": 1,
        },
        "manifest": {"source_health": {}},
    }
    monkeypatch.setattr(
        ausl_stats_app,
        "update_all_data",
        lambda progress, **kwargs: calls.append(("refresh", kwargs)),
    )

    def load(*, enrichment_mode):
        calls.append(("load", enrichment_mode))
        return data

    monkeypatch.setattr(ausl_stats_app, "load_database", load)
    app._finish_load = lambda loaded: setattr(app, "db", loaded)
    app._roster_count = lambda _data: 1

    app.update_enrichment_data()

    assert calls[0][0] == "refresh"
    assert calls[0][1]["include_enrichment"] is True
    assert calls[1] == ("load", EnrichmentMode.PRODUCER_APPROVED)
    assert app.db is data
    assert "10 approved enrichment rows" in app.status_var.get()
    assert "PRODUCER APPROVED" in app.enrichment_mode_var.get()


def test_quick_refresh_does_not_fetch_optional_but_reloads_approved_local(monkeypatch):
    app = bare_app()
    app.network_requests_permitted = lambda *_args, **_kwargs: True
    monkeypatch.setattr(ausl_stats_app.threading, "Thread", ImmediateThread)
    calls = []
    data = {
        "roster": pd.DataFrame([{"player_id": 1}]),
        "enrichment_mode": EnrichmentMode.PRODUCER_APPROVED.value,
        "enrichment_counts": {},
        "manifest": {},
    }
    monkeypatch.setattr(
        ausl_stats_app,
        "update_all_data",
        lambda progress, **kwargs: calls.append(("refresh", kwargs)),
    )
    monkeypatch.setattr(
        ausl_stats_app,
        "load_database",
        lambda *, enrichment_mode: calls.append(("load", enrichment_mode)) or data,
    )
    app._finish_load = lambda loaded: setattr(app, "db", loaded)
    app._roster_count = lambda _data: 1

    app.update_data()

    assert calls[0][1]["include_enrichment"] is False
    assert calls[1] == ("load", EnrichmentMode.PRODUCER_APPROVED)


def test_quick_and_full_buttons_share_one_in_flight_gate():
    app = bare_app()
    app._data_update_in_flight = True

    app._sync_update_button()

    assert app.update_button.state == "disabled"
    assert app.full_update_button.state == "disabled"
    assert app.cancel_update_button.state == "normal"


def test_optional_workbooks_promote_in_same_transaction_as_core(monkeypatch, tmp_path):
    stage_entered = threading.Event()
    release_stage = threading.Event()
    monkeypatch.setattr(ausl_data, "_CORE_REFRESH_COMMIT_LOCK", threading.Lock())
    monkeypatch.setattr(
        ausl_data, "career_batting", lambda _frames: pd.DataFrame([{"player_id": 1}])
    )
    monkeypatch.setattr(
        ausl_data, "career_pitching", lambda _frames: pd.DataFrame([{"player_id": 1}])
    )
    monkeypatch.setattr(
        ausl_data, "career_fielding", lambda _frames: pd.DataFrame([{"player_id": 1}])
    )
    original_write = ausl_data._write_excel_atomic

    def blocking_write(path, sheets):
        if Path(path).name == "ausl_rosters.xlsx" and not stage_entered.is_set():
            stage_entered.set()
            assert release_stage.wait(5)
        original_write(path, sheets)

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", blocking_write)
    final_paths = {
        name: tmp_path / name
        for name in (
            "ausl_rosters.xlsx",
            "ausl_season_stats.xlsx",
            "ausl_career_stats.xlsx",
            "ausl_team_context.xlsx",
            "update_manifest.json",
            "official_game_notes.xlsx",
        )
    }
    frames = {2025: pd.DataFrame([{"player_id": 1}]), 2026: pd.DataFrame([{"player_id": 2}])}
    outcome = {}

    def work():
        try:
            ausl_data._stage_and_promote_core_snapshot(
                output=tmp_path,
                roster_path=final_paths["ausl_rosters.xlsx"],
                season_path=final_paths["ausl_season_stats.xlsx"],
                career_path=final_paths["ausl_career_stats.xlsx"],
                team_context_path=final_paths["ausl_team_context.xlsx"],
                manifest_path=final_paths["update_manifest.json"],
                rosters=frames,
                batting=frames,
                pitching=frames,
                fielding=frames,
                standings=pd.DataFrame([{"team_code": "CHI"}]),
                schedule=pd.DataFrame([{"game_id": 9001}]),
                manifest={"updated_at": "fixture"},
                progress=lambda _message: None,
                cancel_token=None,
                additional_workbooks={
                    final_paths["official_game_notes.xlsx"]: {
                        "official_game_notes": pd.DataFrame(
                            [{"game_id": 9001, "marker": "same-snapshot"}]
                        )
                    }
                },
            )
        except Exception as exc:  # pragma: no cover - asserted below
            outcome["error"] = exc

    worker = threading.Thread(target=work)
    worker.start()
    assert stage_entered.wait(5)
    assert not any(path.exists() for path in final_paths.values())
    release_stage.set()
    worker.join(10)

    assert "error" not in outcome
    assert all(path.exists() for path in final_paths.values())
    assert not list(tmp_path.glob(".core-refresh-stage-*"))
    assert not list(tmp_path.glob(".core-refresh-backup-*"))


def test_full_refresh_manifest_keeps_optional_lkg_health_on_partial_failure(
    monkeypatch, tmp_path
):
    prior = {
        "source_health": {
            "media_guide": {
                "last_success_at": "2026-07-29T12:00:00+00:00",
                "row_count": 5,
                "content_hash_or_etag": "prior",
                "parser_version": "fixture",
            }
        }
    }
    (tmp_path / "update_manifest.json").write_text(json.dumps(prior), encoding="utf-8")
    now = pd.Timestamp("2026-07-29T12:30:00+00:00").to_pydatetime()

    entry = ausl_data._enrichment_source_health_entry(
        source_name="AUSL media guide",
        ok=False,
        now_iso=now.isoformat(),
        now=now,
        row_count=0,
        content_hash=None,
        status_detail_ok="unused",
        error_summary="download failed",
        previous_entry=prior["source_health"]["media_guide"],
    )

    assert entry["status"] == "yellow"
    assert entry["used_fallback"] is True
    assert entry["last_success_at"] == "2026-07-29T12:00:00+00:00"
