from __future__ import annotations

import json
import threading
from urllib.error import URLError

import pandas as pd
import pytest

import ausl_data


# Captured before any test's autouse network guard replaces ausl_data._get_json
# wholesale, mirroring the pattern in test_refresh_health.py.
_REAL_GET_JSON = ausl_data._get_json


# ---------------------------------------------------------------------------
# REFRESH-006: true mid-flight cancellation of a running refresh/live job
# ---------------------------------------------------------------------------


def test_cancel_token_starts_uncancelled():
    token = ausl_data.CancelToken()
    assert token.cancelled is False
    token.raise_if_cancelled()  # must not raise


def test_cancel_token_cancel_is_idempotent_across_repeated_calls():
    token = ausl_data.CancelToken()
    token.cancel()
    token.cancel()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(ausl_data.RefreshCancelled):
        token.raise_if_cancelled()


def test_fetch_with_retry_cancelled_before_it_starts_never_calls_operation():
    token = ausl_data.CancelToken()
    token.cancel()
    calls = []

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data._fetch_with_retry(lambda: calls.append(1), cancel_token=token)

    assert calls == []


def test_fetch_with_retry_cancelled_while_blocked_stops_before_retrying():
    """Cancelling while the operation is blocked (e.g. inside urlopen) must
    stop the retry loop immediately once the blocked call returns, instead of
    sleeping out the full exponential backoff budget and trying again."""

    started = threading.Event()
    release = threading.Event()
    attempts = []

    def operation():
        attempts.append(1)
        started.set()
        release.wait(5)
        # Simulate the transient network failure that would normally trigger
        # a retry after the blocked call finally returns.
        raise URLError("fixture transient failure while blocked")

    token = ausl_data.CancelToken()
    outcome = {}

    def run():
        try:
            ausl_data._fetch_with_retry(
                operation, attempts=3, base_delay=5.0, cancel_token=token
            )
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            outcome["exc"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(2), "operation did not start in time"

    # Cancel while still blocked inside the operation. This call itself must
    # return immediately; it does not wait for the operation to unblock.
    token.cancel()
    release.set()

    worker.join(2)
    assert not worker.is_alive(), "cancellation did not stop the retry loop promptly"
    assert isinstance(outcome.get("exc"), ausl_data.RefreshCancelled)
    # Only the one attempt that was already in flight ran; no retry followed.
    assert attempts == [1]


def test_fetch_with_retry_success_racing_cancellation_still_returns_the_result():
    """_fetch_with_retry only manages retries; discarding a result that
    finished just as cancellation was requested is the caller's job (see the
    app-layer token-identity checks), not this function's."""

    token = ausl_data.CancelToken()

    def operation():
        token.cancel()  # cancellation lands after the "network call" already succeeded
        return "ok"

    assert ausl_data._fetch_with_retry(operation, cancel_token=token) == "ok"


def test_get_json_checks_cancellation_before_making_a_request(monkeypatch):
    monkeypatch.setattr(ausl_data, "_get_json", _REAL_GET_JSON)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("urlopen must not be called once cancelled")

    monkeypatch.setattr(ausl_data, "urlopen", fail_if_called)
    token = ausl_data.CancelToken()
    token.cancel()

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data._get_json("/data/fixture.json", cancel_token=token)


def test_get_json_without_a_cancel_token_behaves_exactly_as_before(monkeypatch):
    """Existing callers that never pass cancel_token must be unaffected."""

    monkeypatch.setattr(ausl_data, "_get_json", _REAL_GET_JSON)
    monkeypatch.setattr(ausl_data.time, "sleep", lambda _s: None)

    import json

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    monkeypatch.setattr(ausl_data, "urlopen", lambda _request, timeout, context: FakeResponse())

    assert ausl_data._get_json("/data/fixture.json") == {"ok": True}


# ---------------------------------------------------------------------------
# update_all_data: cancellation must not write or promote a partial refresh
# ---------------------------------------------------------------------------


def _configure_valid_core_refresh(monkeypatch, output, *, cancel_token=None):
    """A minimal stand-in for the fixture in test_refresh_staging.py, extended
    so the fakes can themselves raise RefreshCancelled at a chosen point."""

    monkeypatch.setattr(ausl_data, "export_dir", lambda: output)
    monkeypatch.setattr(
        ausl_data,
        "roster_frame",
        lambda _payload, year: pd.DataFrame([{"player_id": year, "player_name": f"Player {year}"}]),
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
    monkeypatch.setattr(ausl_data, "career_batting", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(ausl_data, "career_pitching", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(ausl_data, "career_fielding", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda **_kwargs: pd.DataFrame(
            [{"team_code": "CHI", "seasonId": 369, "standingsTypeLk": "SEASON", "wins": 1, "losses": 0}]
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
                    "status": "final",
                }
            ]
        ),
    )


def test_update_all_data_cancelled_before_start_writes_nothing(tmp_path, monkeypatch):
    _configure_valid_core_refresh(monkeypatch, tmp_path)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("no network call should happen once cancelled")

    monkeypatch.setattr(ausl_data, "_get_json", fail_if_called)
    token = ausl_data.CancelToken()
    token.cancel()

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data.update_all_data(cancel_token=token)

    assert [path.name for path in tmp_path.iterdir()] == ["refresh_attempt.json"]
    attempt = json.loads(
        (tmp_path / "refresh_attempt.json").read_text(encoding="utf-8")
    )
    assert attempt["state"] == "cancelled"
    assert attempt["error_summary"] is None


def test_update_all_data_cancelled_mid_loop_writes_nothing(tmp_path, monkeypatch):
    """Mirrors what the real ``_get_json`` does: check ``cancel_token`` before
    doing any work. Cancelling partway through the roster/stats loop must
    stop the remaining downloads rather than fetching everything first."""

    _configure_valid_core_refresh(monkeypatch, tmp_path)
    token = ausl_data.CancelToken()
    calls = []

    def fake_get_json(path, *, cancel_token=None):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        calls.append(path)
        if len(calls) == 2:
            cancel_token.cancel()
        return {}

    monkeypatch.setattr(ausl_data, "_get_json", fake_get_json)

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data.update_all_data(cancel_token=token)

    # The third roster/stats download is never attempted once cancelled.
    assert len(calls) == 2
    assert [path.name for path in tmp_path.iterdir()] == ["refresh_attempt.json"]
    assert ausl_data.load_refresh_attempt(tmp_path)["state"] == "cancelled"


def test_update_all_data_cancelled_just_before_staging_writes_nothing(tmp_path, monkeypatch):
    """A cancel that lands after the very last network call, but before any
    file is staged/promoted, must still block promotion."""

    _configure_valid_core_refresh(monkeypatch, tmp_path)
    token = ausl_data.CancelToken()
    calls = []

    def fake_get_json(_path, **_kwargs):
        calls.append(_path)
        return {}

    def fake_fetch_schedule_frame(**_kwargs):
        token.cancel()
        return pd.DataFrame(
            [
                {
                    "game_id": 9001,
                    "game_date": "2026-07-20T19:00:00-04:00",
                    "away_team_code": "CHI",
                    "home_team_code": "CAR",
                    "status": "final",
                }
            ]
        )

    monkeypatch.setattr(ausl_data, "_get_json", fake_get_json)
    monkeypatch.setattr(ausl_data, "fetch_schedule_frame", fake_fetch_schedule_frame)

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data.update_all_data(cancel_token=token)

    assert [path.name for path in tmp_path.iterdir()] == ["refresh_attempt.json"]
    assert ausl_data.load_refresh_attempt(tmp_path)["state"] == "cancelled"


def test_update_all_data_without_a_cancel_token_still_writes_normally(tmp_path, monkeypatch):
    """Existing non-cancelling callers (standalone `main()`, existing tests)
    must be completely unaffected."""

    _configure_valid_core_refresh(monkeypatch, tmp_path)
    monkeypatch.setattr(ausl_data, "_get_json", lambda _path: {})

    outputs = ausl_data.update_all_data()

    assert outputs["manifest"].exists()


# ---------------------------------------------------------------------------
# fetch_live_game: cancellation must not fetch further and must not return
# a promotable result once cancelled.
# ---------------------------------------------------------------------------


def test_fetch_live_game_cancelled_before_second_call_never_makes_it(monkeypatch):
    token = ausl_data.CancelToken()
    calls = []

    def fake_get_json(path, **_kwargs):
        calls.append(path)
        token.cancel()
        return {"gameId": "9001"}

    monkeypatch.setattr(ausl_data, "_get_json", fake_get_json)

    with pytest.raises(ausl_data.RefreshCancelled):
        ausl_data.fetch_live_game("9001", cancel_token=token)

    assert len(calls) == 1


def test_fetch_live_game_without_a_cancel_token_behaves_exactly_as_before(monkeypatch):
    monkeypatch.setattr(
        ausl_data,
        "_get_json",
        lambda path: {"gameId": "9001"} if "game-data" in path else {"data": {"boxscore": True}},
    )

    game, box = ausl_data.fetch_live_game("9001")

    assert game == {"gameId": "9001"}
    assert box == {"boxscore": True}
