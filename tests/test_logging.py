from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def test_structured_log_is_user_writable_and_redacts_private_note_text(monkeypatch, tmp_path):
    from ausl_logging import configure_logging, default_log_dir, log_event

    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    assert default_log_dir() == local_app_data / "AUSL Broadcast Stats" / "logs"

    logger, log_path = configure_logging(log_directory=tmp_path / "logs", max_bytes=10_000)
    log_event(
        logger,
        "source_refresh_finished",
        source="official_standings",
        row_count=6,
        used_fallback=False,
        note_text="PRIVATE PRODUCER NOTE MUST NEVER BE LOGGED",
    )
    for handler in logger.handlers:
        handler.flush()

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "source_refresh_finished"
    assert record["source"] == "official_standings"
    assert record["row_count"] == 6
    assert record["used_fallback"] is False
    assert "note_text" not in record
    assert "PRIVATE PRODUCER NOTE" not in log_path.read_text(encoding="utf-8")


def test_structured_log_rotates_without_losing_current_log(tmp_path):
    from ausl_logging import configure_logging, log_event

    logger, log_path = configure_logging(
        log_directory=tmp_path / "logs",
        max_bytes=320,
        backup_count=1,
    )
    for index in range(20):
        log_event(logger, "refresh_progress", source="fixture", row_count=index)
    for handler in logger.handlers:
        handler.flush()

    assert log_path.exists()
    assert Path(f"{log_path}.1").exists()


def test_data_source_result_logs_row_count_and_fallback_without_row_contents(tmp_path):
    import ausl_data
    from ausl_logging import configure_logging

    logger, log_path = configure_logging(log_directory=tmp_path / "logs")
    frame = pd.DataFrame(
        [{"player_id": 101, "note_text": "PRIVATE ROW CONTENT", "wins": 11}]
    )

    ausl_data.log_source_result(
        "official_standings",
        frame,
        status="validated",
        used_fallback=True,
    )
    for handler in logger.handlers:
        handler.flush()

    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "source_result"
    assert record["source"] == "official_standings"
    assert record["row_count"] == 1
    assert record["status"] == "validated"
    assert record["used_fallback"] is True
    assert "PRIVATE ROW CONTENT" not in log_path.read_text(encoding="utf-8")


def test_standalone_updater_configures_logging_and_records_success(monkeypatch, tmp_path):
    import ausl_data

    events = []
    configured = []
    monkeypatch.setattr(
        ausl_data,
        "configure_logging",
        lambda: configured.append(True) or (object(), tmp_path / "update.jsonl"),
        raising=False,
    )
    monkeypatch.setattr(
        ausl_data,
        "log_event",
        lambda _logger, event, **fields: events.append((event, fields)),
    )
    monkeypatch.setattr(
        ausl_data,
        "update_all_data",
        lambda _progress: {"roster": tmp_path / "roster.xlsx"},
    )

    assert ausl_data.main(lambda _message: None) == 0
    assert configured == [True]
    assert [event for event, _fields in events] == [
        "standalone_update_started",
        "standalone_update_completed",
    ]


def test_standalone_updater_logs_failure_and_returns_nonzero(monkeypatch, tmp_path):
    import ausl_data

    events = []
    monkeypatch.setattr(
        ausl_data,
        "configure_logging",
        lambda: (object(), tmp_path / "update.jsonl"),
        raising=False,
    )
    monkeypatch.setattr(
        ausl_data,
        "log_event",
        lambda _logger, event, **fields: events.append((event, fields)),
    )

    def fail(_progress):
        raise RuntimeError("fixture refresh failed")

    monkeypatch.setattr(ausl_data, "update_all_data", fail)

    assert ausl_data.main(lambda _message: None) == 1
    assert events[-1][0] == "standalone_update_failed"
    assert events[-1][1]["error_type"] == "RuntimeError"
    assert "fixture refresh failed" in events[-1][1]["error_summary"]
