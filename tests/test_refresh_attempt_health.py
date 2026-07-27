from __future__ import annotations

import json

import ausl_data
import ausl_stats_app


def _green_manifest():
    return {
        "updated_at": "2026-07-23T18:08:06+00:00",
        "source_health": {
            "official_rosters": {
                "status": "green",
                "status_detail": "validated roster refresh",
                "last_success_at": "2026-07-23T18:08:06+00:00",
            },
            "official_stats": {
                "status": "green",
                "status_detail": "validated stat refresh",
                "last_success_at": "2026-07-23T18:08:06+00:00",
            },
        },
    }


def test_failed_latest_attempt_warns_without_reclassifying_stored_snapshot_red():
    attempt = {
        "state": "failed",
        "started_at": "2026-07-27T10:00:00+00:00",
        "completed_at": "2026-07-27T10:00:03+00:00",
        "affected_source": "official_core_sources",
        "error_summary": "CoreRefreshValidationError: official standings failed",
    }

    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)

    assert app._data_health_state(_green_manifest(), attempt) == "yellow"
    text = app.format_data_health(_green_manifest(), attempt)
    assert "Stored snapshot valid; latest refresh failed" in text
    assert "official_core_sources" in text


def test_cancelled_attempt_is_not_presented_as_a_source_failure():
    attempt = {
        "state": "cancelled",
        "started_at": "2026-07-27T10:00:00+00:00",
        "completed_at": "2026-07-27T10:00:01+00:00",
        "affected_source": "official_core_sources",
        "error_summary": None,
    }

    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)

    assert app._data_health_state(_green_manifest(), attempt) == "green"
    text = app.format_data_health(_green_manifest(), attempt)
    assert "latest refresh failed" not in text.lower()
    assert "cancelled" in text.lower()


def test_refresh_attempt_round_trips_atomically_and_ignores_stale_completion(
    tmp_path,
):
    newer = {
        "state": "succeeded",
        "started_at": "2026-07-27T10:00:01+00:00",
        "completed_at": "2026-07-27T10:00:04+00:00",
        "affected_source": "official_core_sources",
        "error_summary": None,
    }
    older = {
        "state": "cancelled",
        "started_at": "2026-07-27T10:00:00+00:00",
        "completed_at": "2026-07-27T10:00:05+00:00",
        "affected_source": "official_core_sources",
        "error_summary": None,
    }

    ausl_data._persist_refresh_attempt(newer, output=tmp_path)
    ausl_data._persist_refresh_attempt(older, output=tmp_path)

    path = tmp_path / "refresh_attempt.json"
    assert ausl_data.load_refresh_attempt(tmp_path) == newer
    assert json.loads(path.read_text(encoding="utf-8")) == newer
    assert b"\r\n" not in path.read_bytes()
    assert not list(tmp_path.glob(".refresh-attempt-*"))
