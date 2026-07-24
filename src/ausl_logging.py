"""Small JSON-lines logger for refresh and data-health diagnostics."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "ausl_broadcast_stats"
LOG_FILENAME = "ausl_broadcast_stats.jsonl"
_PRIVATE_KEY_PARTS = (
    "note",
    "lineup",
    "clipboard",
    "credential",
    "password",
    "secret",
    "token",
    "body",
)


def default_log_dir() -> Path:
    """Return a per-user writable log directory outside the app package."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "AUSL Broadcast Stats" / "logs"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        lowered = str(key).lower()
        if any(part in lowered for part in _PRIVATE_KEY_PARTS):
            continue
        safe[str(key)] = _json_value(value)
    return safe


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
        }
        payload.update(_safe_fields(getattr(record, "event_fields", {})))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(
    log_directory: Path | str | None = None,
    *,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> tuple[logging.Logger, Path]:
    """Configure one rotating application logger and return it with its path."""

    directory = Path(log_directory) if log_directory is not None else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / LOG_FILENAME

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if getattr(handler, "_ausl_handler", False):
            logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler._ausl_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return logger, log_path


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Write a structured event while dropping private producer-authored fields."""

    logger.info(
        event,
        extra={
            "event_name": event,
            "event_fields": _safe_fields(fields),
        },
    )
