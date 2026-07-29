"""Download and normalize the public data used by the AUSL broadcast app."""

from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import re
import shutil
import ssl
import sys
import tempfile
import threading
import unicodedata
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from ausl_enrichment import (
    DEVELOPER_ONLY_KEYS,
    PRODUCER_ENRICHMENT_KEYS,
    EnrichmentMode,
    approved_enrichment_frames,
)
from ausl_logging import configure_logging, log_event

try:
    import certifi
except ImportError:  # Source installs can still use Python's normal trust store.
    certifi = None


DATA_LOGGER = logging.getLogger("ausl_broadcast_stats.data")


def log_source_result(
    source: str,
    frame: pd.DataFrame | None,
    *,
    status: str,
    used_fallback: bool = False,
    error_summary: str | None = None,
) -> None:
    """Log source health metadata without serializing source or note rows."""

    log_event(
        DATA_LOGGER,
        "source_result",
        source=source,
        row_count=0 if frame is None else len(frame),
        status=status,
        used_fallback=used_fallback,
        error_summary=error_summary,
    )


BASE_URL = "https://theausl.com"
SEASONS = {2025: 270, 2026: 369}


def _latest_season_year() -> int:
    years = sorted(SEASONS)
    if not years:
        raise ValueError("SEASONS must not be empty")
    return max(years)


def media_guide_source_context(*, guide_year: int | None = None) -> dict[str, object]:
    guide_year = int(guide_year or _latest_season_year())
    previous_year = guide_year - 1
    return {
        "guide_year": guide_year,
        "previous_year": previous_year,
        "source_name": f"{guide_year} AUSL Media Guide",
        "source_url": f"https://theausl.com/wp-content/uploads/{guide_year}/06/{guide_year}-AUSL-Media-Guide.pdf",
        "pdf_filename": f"{guide_year}-AUSL-Media-Guide.pdf",
        "note_category_keys": {
            "previous_recap": f"{previous_year}_recap",
            "current_outlook": f"{guide_year}_outlook",
            "current_context": f"{guide_year}_context",
            "previous_notes": f"ausl_{previous_year}_notes",
        },
    }


MEDIA_GUIDE_URL = media_guide_source_context()["source_url"]
TEAM_NAMES = {
    "Bandits": "Chicago Bandits",
    "Blaze": "Carolina Blaze",
    "Cascade": "Portland Cascade",
    "Spark": "Oklahoma City Spark",
    "Talons": "Utah Talons",
    "Volts": "Texas Volts",
}
TEAM_CODES = {
    "Bandits": "CHI",
    "Blaze": "CAR",
    "Cascade": "PDX",
    "Spark": "OKC",
    "Talons": "UTA",
    "Volts": "TEX",
}
CODE_TO_TEAM = {code: TEAM_NAMES[short] for short, code in TEAM_CODES.items()}
CODE_TO_SHORT = {code: short for short, code in TEAM_CODES.items()}
TEAM_HOME_CITY = {
    "CHI": "Chicago",
    "CAR": "Carolina",
    "PDX": "Portland",
    "OKC": "Oklahoma City",
    "UTA": "Utah",
    "TEX": "Texas",
}
SPLIT_TYPES = {
    "regularSeason": "Regular Season",
    "postSeason": "Postseason",
    "vsRight": "Vs Right",
    "vsLeft": "Vs Left",
    "home": "Home",
    "away": "Away",
    "runnersInScoringPosition": "Scoring Position",
    "runnersInScoringPositionTwoOuts": "Scoring Position and 2 Outs",
}


def build_enrichment_sources() -> list[dict]:
    media_context = media_guide_source_context()
    return [
        {
            "source_name": "Official AUSL JSON/API",
            "source_type": "official_stats",
            "source_url": "https://theausl.com",
            "purpose": "Authoritative rosters, player IDs, AUSL stats, live game data, and box scores.",
            "status": "active",
        },
        {
            "source_name": str(media_context["source_name"]),
            "source_type": "media_guide",
            "source_url": str(media_context["source_url"]),
            "purpose": "Static bios, team context, coaches, records, and media-guide story notes.",
            "status": "registered_for_storyline_enrichment",
        },
        {
            "source_name": "Official AUSL Split Stats",
            "source_type": "official_splits",
            "source_url": "https://theausl.com/stats/",
            "purpose": "Vs RHP/LHP, home/away, RISP, and two-out RISP broadcast angles.",
            "status": "active",
        },
        {
            "source_name": "Official AUSL Standings",
            "source_type": "team_context",
            "source_url": "https://theausl.com/standings/",
            "purpose": "Team records, streaks, games back, runs scored/allowed, and run differential.",
            "status": "active",
        },
    {
        "source_name": "Official AUSL Schedule",
        "source_type": "schedule_results",
        "source_url": "https://theausl.com/schedule/",
        "purpose": "Game IDs, results, venues, rematch notes, upcoming games, and game-note links.",
        "status": "active",
    },
    {
        "source_name": "AUSL News",
        "source_type": "news",
        "source_url": "https://theausl.com/news/",
        "purpose": "Recent feature stories, returns from injury, highlights, and human-interest context.",
        "status": "registered_for_storyline_enrichment",
    },
    {
        "source_name": "MLB AUSL News",
        "source_type": "news",
        "source_url": "https://www.mlb.com/ausl",
        "purpose": "Broader feature/context articles related to AUSL.",
        "status": "registered_for_storyline_enrichment",
    },
    {
        "source_name": "AUSL Draft Results",
        "source_type": "draft",
        "source_url": "https://theausl.com/news/2026-ausl-college-draft-results/",
        "purpose": "Draft position, school, team selection, and rookie storylines.",
        "status": "registered_for_storyline_enrichment",
    },
    {
        "source_name": "AUSL Golden Ticket Tracker",
        "source_type": "draft",
        "source_url": "https://theausl.com/golden-ticket-moment-tracker/",
        "purpose": "Golden Ticket selection context and first-pro-season storylines.",
        "status": "registered_for_storyline_enrichment",
    },
    {
        "source_name": "College/Awards Sources",
        "source_type": "external_context",
        "source_url": "NCAA, D1Softball, NFCA, USA Softball, Academic All-America",
        "purpose": "College stats, awards, and background context with manual confidence review.",
        "status": "registered_manual_review_required",
    },
]


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def export_dir() -> Path:
    path = app_root() / "data" / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


REFRESH_ATTEMPT_FILENAME = "refresh_attempt.json"
_CORE_REFRESH_COMMIT_LOCK = threading.Lock()
_REFRESH_EXECUTION_LOCK = threading.Lock()
_REFRESH_ATTEMPT_LOCK = threading.Lock()


def _json_text(payload: object) -> str:
    """Return deterministic UTF-8 JSON text whose line endings survive Git."""

    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    )


def _write_json_atomic(path: Path, payload: object, *, prefix: str = ".json-") -> None:
    """Write deterministic UTF-8/LF JSON and atomically replace ``path``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json_text(payload))
            stream.flush()
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _refresh_attempt_path(output: Path | None = None) -> Path:
    return (Path(output) if output is not None else export_dir()) / REFRESH_ATTEMPT_FILENAME


def load_refresh_attempt(output: Path | None = None) -> dict:
    path = _refresh_attempt_path(output)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _persist_refresh_attempt(attempt: dict, *, output: Path | None = None) -> bool:
    """Persist the newest refresh attempt without letting stale workers win."""

    path = _refresh_attempt_path(output)
    started_at = str(attempt.get("started_at") or "")
    with _REFRESH_ATTEMPT_LOCK:
        current = load_refresh_attempt(path.parent)
        current_started_at = str(current.get("started_at") or "")
        if current_started_at and started_at and current_started_at > started_at:
            return False
        _write_json_atomic(path, attempt, prefix=".refresh-attempt-")
    return True


def _safe_refresh_error_summary(exc: Exception) -> str:
    summary = f"{type(exc).__name__}: {exc}"
    summary = re.sub(
        r"(?i)\b(password|secret|token|credential)=([^\s&]+)",
        r"\1=[REDACTED]",
        summary,
    )
    summary = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", summary)
    return _clean_text(summary)[:500]


# Bounded retry/backoff for transient network failures (REFRESH-006). Attempts
# and the base delay are module-level so tests can shrink the delay to zero
# instead of sleeping for real.
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRYABLE_TRANSPORT_ERRORS = (URLError, TimeoutError, socket.timeout, ConnectionError)


def _is_retryable_http_error(exc: HTTPError) -> bool:
    # 5xx and 429 are worth a retry; 4xx client errors (404, 403, ...) will not
    # resolve themselves on a second attempt.
    return exc.code == 429 or exc.code >= 500


def _retry_delay_seconds(attempt: int, base_delay: float) -> float:
    return base_delay * (2 ** (attempt - 1))


class RefreshCancelled(Exception):
    """Raised when a caller cancels a refresh/live job that is still running."""


class CancelToken:
    """Thread-safe, idempotent cancellation signal for one refresh/live job.

    ``cancel()`` is meant to be called from the main thread, at any time,
    including while the owning background thread is blocked inside a
    network call. Python/``urllib`` give no safe way to force-abort a call
    already inside ``urlopen``, so this does not kill that call; instead,
    every attempt boundary and the backoff wait between attempts check the
    token so a cancelled job stops retrying immediately (rather than
    waiting out its remaining timeout/retry budget) and callers can check
    ``cancelled`` before promoting a result to avoid promoting stale work.
    """

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds; return True if cancelled first."""

        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise RefreshCancelled()


def _cancel_kwargs(cancel_token: CancelToken | None) -> dict:
    """Only pass ``cancel_token`` through when a caller actually supplied one.

    Keeps every call site source-compatible with callers (including test
    doubles) that stub out ``_get_json``/``_get_text``/``fetch_standings_frame``/
    ``fetch_schedule_frame`` with their pre-cancellation, fixed-argument
    signatures and were never asked to opt into cancellation.
    """

    return {} if cancel_token is None else {"cancel_token": cancel_token}


def _fetch_with_retry(
    operation,
    *,
    attempts: int = NETWORK_RETRY_ATTEMPTS,
    base_delay: float = NETWORK_RETRY_BASE_DELAY_SECONDS,
    cancel_token: CancelToken | None = None,
):
    """Run ``operation`` with bounded retry/backoff on transient network errors.

    Non-transient failures (4xx other than 429) fail immediately. Any error
    still failing on the final attempt is re-raised unchanged. If
    ``cancel_token`` is cancelled before an attempt starts, or during the
    backoff wait between attempts, this raises ``RefreshCancelled`` instead
    of retrying.
    """

    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        try:
            return operation()
        except HTTPError as exc:
            if not _is_retryable_http_error(exc) or attempt == attempts:
                raise
            last_exc = exc
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            if attempt == attempts:
                raise
            last_exc = exc
        delay = _retry_delay_seconds(attempt, base_delay)
        if cancel_token is not None:
            if cancel_token.wait(delay):
                raise RefreshCancelled()
        else:
            time.sleep(delay)
    if last_exc is not None:  # pragma: no cover - defensive, loop always returns/raises above
        raise last_exc
    raise RuntimeError("retry loop exited without a result")  # pragma: no cover


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frame_fingerprint(frame) -> str | None:
    """A stable content hash for a validated frame, for the source-health manifest."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    payload = frame.to_csv(index=False).encode("utf-8")
    return _sha256_hex(payload)


def _get_json(path: str, *, cancel_token: CancelToken | None = None) -> dict:
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    url = path if path.startswith("http") else BASE_URL + path
    request = Request(
        url,
        headers={"User-Agent": "AUSL-Broadcast-Stats/1.0 (local desktop tool)"},
    )
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()

    def _do_request():
        with urlopen(request, timeout=45, context=context) as response:
            return json.loads(response.read().decode("utf-8"))

    return _fetch_with_retry(_do_request, cancel_token=cancel_token)


def _get_text(path: str, *, cancel_token: CancelToken | None = None) -> str:
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    url = path if path.startswith("http") else BASE_URL + path
    request = Request(
        url,
        headers={"User-Agent": "AUSL-Broadcast-Stats/1.0 (local desktop tool)"},
    )
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()

    def _do_request():
        with urlopen(request, timeout=45, context=context) as response:
            return response.read().decode("utf-8", "ignore")

    return _fetch_with_retry(_do_request, cancel_token=cancel_token)


def _download_file(url: str, path: Path, *, cancel_token: CancelToken | None = None) -> str:
    """Download ``url`` to ``path`` and return a sha256 hex hash of its bytes."""

    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "AUSL-Broadcast-Stats/1.0 (local desktop tool)"})
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()

    def _do_request():
        with urlopen(request, timeout=90, context=context) as response:
            return response.read()

    payload = _fetch_with_retry(_do_request, cancel_token=cancel_token)
    path.write_bytes(payload)
    return _sha256_hex(payload)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _snippet_around(text: str, needle: str, radius: int = 360) -> str:
    lower = text.lower()
    index = lower.find(needle.lower())
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    snippet = _clean_text(text[start:end])
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def _media_guide_noise_patterns() -> list[str]:
    guide_year = _latest_season_year()
    return [
        rf"\b\d+\s*\|\s*{guide_year} AUSL MEDIA GUIDE\b",
        rf"\b{guide_year} AUSL MEDIA GUIDE\s*\|\s*\d+\b",
        rf"\b\d+\s+{guide_year} AUSL MEDIA GUIDE\b",
        r"\bBIOS\s+\d+\s+@THEAUSLOFFICIAL\s*\|",
        r"\b[A-Z ]+\s*\|\s*\d+\s*\|\s*@THEAUSLOFFICIAL\s*\|\s*THEAUSL\.COM\b",
        r"\b@THEAUSLOFFICIAL\b",
        r"\bTHEAUSL\.COM\b",
        r"\bINTRODUCTION\b",
        r"\bTABLE OF CONTENTS\b",
    ]


class MediaGuideValidationError(RuntimeError):
    """The guide cannot be mapped safely enough to replace verified data."""


MEDIA_GUIDE_PLAYER_ALIASES = {
    "Odicci Alexander": "Odicci Alexander-Bennett",
    "Jocelyn Alo": "Jocelyn Alo Evans",
    "Kinzie Hansen": "Kinzie Hansen-McKinzie",
    "Bubba Nickles": "Bubba Nickles-Camarena",
    "Dallas Escobedo": "Dallas Escobedo Magee",
    "Kelsey Stewart": "Kelsey Stewart-Hunter",
}


def _clean_media_guide_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"(?<=[A-Za-z])-\s*\r?\n\s*(?=[a-z])", "", text)
    text = re.sub(r"\b((?:19|20)\d)\s+(\d)\b", r"\1\2", text)
    text = re.sub(r"\b(19|20)\s+(\d{2})\b", r"\1\2", text)
    text = _clean_text(text)
    for pattern in _media_guide_noise_patterns():
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(
        r"Year\s+Team\s+GP\s+GS\s+Avg\.?\s+OB%?\s+SLG%?.*?(?=(AUSL/ATHLETES|OTHER PROFESSIONAL|INTERNATIONAL|COLLEGE EXPERIENCE|PERSONAL|JUST THE FACTS|$))",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Date\s+Opponent\s+Location\s+Score\s+Pitcher of Record.*?(?=(AUSL/ATHLETES|OTHER PROFESSIONAL|INTERNATIONAL|COLLEGE EXPERIENCE|PERSONAL|JUST THE FACTS|$))",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_text(text)


def _normalize_media_guide_identity(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _media_guide_toc_entries(page_rows) -> list[dict]:
    entries = []
    pattern = re.compile(
        r"^\s*(.+?)\s*\.{3,}\s*(\d+)(?:\s*-\s*(\d+))?\s*$"
    )
    for page in page_rows:
        raw_text = str(page.get("raw_text", "") or "")
        if "TABLE OF CONTENTS" not in raw_text.upper():
            continue
        for line in raw_text.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            start = int(match.group(2))
            end = int(match.group(3) or start)
            if end < start:
                continue
            toc_name = _clean_text(match.group(1))
            entries.append(
                {
                    "toc_name": toc_name,
                    "normalized_name": _normalize_media_guide_identity(toc_name),
                    "printed_start": start,
                    "printed_end": end,
                    "toc_pdf_page": int(page.get("page")),
                }
            )
    if not entries:
        raise MediaGuideValidationError("media guide TOC entries were not found")
    return entries


def _media_guide_date(page_rows) -> str:
    text = "\n".join(str(page.get("raw_text", "") or "") for page in page_rows)
    match = re.search(
        r"\baccurate\s+as\s+of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise MediaGuideValidationError("media guide effective date was not found")
    try:
        return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
    except ValueError as exc:
        raise MediaGuideValidationError("media guide effective date is invalid") from exc


def _media_guide_name_occurs(name: str, text: str) -> bool:
    normalized_name = _normalize_media_guide_identity(name)
    normalized_text = _normalize_media_guide_identity(text)
    if not normalized_name:
        return False
    return re.search(rf"(?:^| )({re.escape(normalized_name)})(?: |$)", normalized_text) is not None


def _media_guide_page_offset(entries, roster, page_rows) -> int:
    entries_by_name = {}
    for entry in entries:
        entries_by_name.setdefault(entry["normalized_name"], []).append(entry)
    aliases = {
        _normalize_media_guide_identity(source): _normalize_media_guide_identity(target)
        for source, target in MEDIA_GUIDE_PLAYER_ALIASES.items()
    }
    matched_entries = []
    for player_name in roster.get("player_name", pd.Series(dtype=str)).dropna():
        normalized = _normalize_media_guide_identity(player_name)
        candidates = entries_by_name.get(normalized, [])
        if not candidates and normalized in aliases:
            candidates = entries_by_name.get(aliases[normalized], [])
        if len(candidates) == 1:
            matched_entries.append(candidates[0])
    if not matched_entries:
        raise MediaGuideValidationError(
            "media guide page offset cannot be verified without exact TOC identities"
        )

    page_by_number = {
        int(page["page"]): str(page.get("raw_text", "") or "")
        for page in page_rows
    }
    candidate_offsets = set()
    for entry in matched_entries:
        for page_number, page_text in page_by_number.items():
            if _media_guide_name_occurs(entry["toc_name"], page_text):
                candidate_offsets.add(page_number - entry["printed_start"])
    if not candidate_offsets:
        raise MediaGuideValidationError("media guide page offset has no header evidence")

    scores = {}
    for offset in candidate_offsets:
        score = 0
        for entry in matched_entries:
            mapped_text = "\n".join(
                page_by_number.get(printed_page + offset, "")
                for printed_page in range(
                    entry["printed_start"], entry["printed_end"] + 1
                )
            )
            if _media_guide_name_occurs(entry["toc_name"], mapped_text):
                score += 1
        scores[offset] = score
    ranked = sorted(scores.items(), key=lambda item: (item[1], -abs(item[0])), reverse=True)
    best_offset, best_score = ranked[0]
    runner_score = ranked[1][1] if len(ranked) > 1 else -1
    required_score = 1 if len(matched_entries) == 1 else math.ceil(len(matched_entries) * 0.6)
    if best_score < required_score or best_score == runner_score:
        raise MediaGuideValidationError(
            "media guide page offset could not be verified unambiguously"
        )
    return best_offset


def _extract_between_headers(text: str, header: str, headers: list[str]) -> str:
    pattern = re.compile(rf"\b{re.escape(header)}\b", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    starts = []
    for other in headers:
        if other == header:
            continue
        other_match = re.search(rf"\b{re.escape(other)}\b", text[match.end() :], flags=re.IGNORECASE)
        if other_match:
            starts.append(match.end() + other_match.start())
    end = min(starts) if starts else len(text)
    return _clean_media_guide_text(text[match.end() : end])


def _sentences_with_terms(text: str, terms: tuple[str, ...], limit: int = 4) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    found = [sentence.strip() for sentence in sentences if any(term.lower() in sentence.lower() for term in terms)]
    return _clean_text(" ".join(found[:limit]))


MEDIA_APPROVAL_PARSER_VERSION = "media-toc-v1"
media_context = media_guide_source_context()
MEDIA_APPROVAL_HASH_FIELDS = (
    "entity_type",
    "entity_id",
    "entity_name",
    "note_text",
    "note_category",
    "media_guide_bio",
    "team_history",
    f"{media_context['guide_year']}_context",
    "source_name",
    "source_url",
    "expected_printed_pages",
    "parsed_pdf_pages",
    "guide_date",
    "match_status",
    "confidence_score",
    "warnings",
    "parser_version",
    "approval_state",
    "approval_method",
    "approved_by",
    "approved_at",
)


def _media_approval_text(value) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


def media_approval_record_id(row) -> str:
    """Hash the exact identity, note, source pages, and parser evidence approved."""

    payload = {
        field_name: _media_approval_text(
            row.get(field_name) if hasattr(row, "get") else ""
        )
        for field_name in MEDIA_APPROVAL_HASH_FIELDS
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _apply_media_approval_fields(row: dict) -> dict:
    approved = (
        _media_approval_text(row.get("match_status")).casefold() == "verified"
        and not _media_approval_text(row.get("warnings"))
        and bool(_media_approval_text(row.get("entity_type")))
        and bool(_media_approval_text(row.get("entity_id")))
        and bool(_media_approval_text(row.get("entity_name")))
        and bool(_media_approval_text(row.get("source_name")))
        and bool(_media_approval_text(row.get("expected_printed_pages")))
        and bool(_media_approval_text(row.get("parsed_pdf_pages")))
        and bool(_media_approval_text(row.get("guide_date")))
    )
    row["parser_version"] = MEDIA_APPROVAL_PARSER_VERSION
    row["approval_state"] = "approved" if approved else "review_required"
    row["approval_method"] = "parser_exact_identity" if approved else ""
    row["approval_record_id"] = media_approval_record_id(row) if approved else ""
    row["approved_by"] = ""
    row["approved_at"] = ""
    return row


def approve_media_row(row, *, reviewer: str, approved_at: str) -> dict:
    """Create a complete manual approval record without inferring missing evidence."""

    candidate = dict(row)
    reviewer_text = _media_approval_text(reviewer)
    approved_at_text = _media_approval_text(approved_at)
    try:
        parsed_approval = datetime.fromisoformat(
            approved_at_text.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("A valid timezone-aware approval timestamp is required") from exc
    required = (
        "entity_type",
        "entity_id",
        "entity_name",
        "source_name",
        "expected_printed_pages",
        "parsed_pdf_pages",
        "guide_date",
    )
    if not reviewer_text:
        raise ValueError("An approval reviewer is required")
    if parsed_approval.tzinfo is None:
        raise ValueError("A valid timezone-aware approval timestamp is required")
    if any(not _media_approval_text(candidate.get(field)) for field in required):
        raise ValueError("Complete identity and page provenance are required")
    if _media_approval_text(candidate.get("match_status")).casefold() != "verified":
        raise ValueError("Media identity must be verified before approval")
    if _media_approval_text(candidate.get("warnings")):
        raise ValueError("Unresolved media identity warnings block approval")
    candidate.update(
        {
            "needs_review": False,
            "approval_state": "approved",
            "approval_method": "manual",
            "approved_by": reviewer_text,
            "approved_at": parsed_approval.isoformat(),
        }
    )
    candidate["approval_record_id"] = media_approval_record_id(candidate)
    return candidate


def _media_note_rows(
    entity_type,
    entity_id,
    entity_name,
    sections: dict[str, str],
    source_pages,
    imported_at,
    confidence_score,
    *,
    match_status="",
    expected_printed_pages="",
    parsed_pdf_pages="",
    guide_date="",
    warnings="",
):
    media_context = media_guide_source_context()
    note_keys = media_context["note_category_keys"]
    categories = {
        "clean_bio": "bio",
        "college_notes": "college",
        "awards_notes": "award",
        "personal_notes": "personal",
        note_keys["previous_notes"]: f"{media_context['previous_year']}_AUSL",
        "fun_facts": "fun_fact",
        "team_overview": "team_context",
        "head_coach": "coach",
        note_keys["previous_recap"]: "history",
        note_keys["current_outlook"]: "team_context",
    }
    rows = []
    for key, category in categories.items():
        note = _clean_media_guide_text(sections.get(key, ""))
        if not note:
            continue
        needs_review = (
            match_status not in {"", "verified"} or confidence_score < 0.75
        )
        rows.append(
            _apply_media_approval_fields({
                "note_id": f"clean-media-{entity_type}-{entity_id}-{category}",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "note_text": note,
                "note_category": category,
                "source_name": str(media_context["source_name"]),
                "source_url": str(media_context["source_url"]),
                "source_pages": source_pages,
                "confidence_score": confidence_score,
                "needs_review": needs_review,
                "match_status": match_status,
                "expected_printed_pages": expected_printed_pages,
                "parsed_pdf_pages": parsed_pdf_pages,
                "guide_date": guide_date,
                "warnings": warnings,
                "imported_at": imported_at,
            })
        )
    return rows


MEDIA_NOTE_CATEGORY_SPECIFICITY = {
    "award": 0,
    "2025_AUSL": 1,
    "college": 2,
    "fun_fact": 3,
    "personal": 4,
    "coach": 5,
    "history": 6,
    "team_context": 7,
    "bio": 8,
}


def _deduplicate_media_note_rows(rows) -> list[dict]:
    """Keep the most specific source row for equivalent normalized note text."""

    selected = {}
    order = []
    for source_row in rows:
        row = dict(source_row)
        normalized_note = re.sub(
            r"[^a-z0-9]+", " ", str(row.get("note_text", "")).casefold()
        ).strip()
        key = (
            str(row.get("entity_type", "")),
            str(row.get("entity_id", "")),
            normalized_note,
        )
        if not normalized_note:
            continue
        priority = MEDIA_NOTE_CATEGORY_SPECIFICITY.get(
            str(row.get("note_category", "")), 99
        )
        if key not in selected:
            selected[key] = (priority, row)
            order.append(key)
        elif priority < selected[key][0]:
            selected[key] = (priority, row)
    return [selected[key][1] for key in order]


def _extract_labeled_media_value(text: str, label: str, next_labels: tuple[str, ...]) -> str:
    lookahead = "|".join(re.escape(item) + r":" for item in next_labels)
    pattern = rf"{re.escape(label)}:\s*(.*?)(?=\s+(?:{lookahead})|$)"
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    return _clean_text(match.group(1)) if match else ""


def _page_range_text(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def _media_guide_player_frames(
    roster: pd.DataFrame,
    page_rows,
    *,
    imported_at: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map roster identities to TOC ranges and return fail-closed player notes."""

    entries = _media_guide_toc_entries(page_rows)
    guide_date = _media_guide_date(page_rows)
    pdf_page_offset = _media_guide_page_offset(entries, roster, page_rows)
    entries_by_name = {}
    for entry in entries:
        entries_by_name.setdefault(entry["normalized_name"], []).append(entry)
    aliases = {
        _normalize_media_guide_identity(source): _normalize_media_guide_identity(target)
        for source, target in MEDIA_GUIDE_PLAYER_ALIASES.items()
    }
    page_by_number = {int(page["page"]): page for page in page_rows}
    section_headers = [
        "JUST THE FACTS",
        "AUSL/ATHLETES UNLIMITED EXPERIENCE",
        "OTHER PROFESSIONAL EXPERIENCE",
        "INTERNATIONAL EXPERIENCE",
        "COLLEGE EXPERIENCE",
        "PERSONAL",
    ]
    player_rows = []
    clean_note_rows = []
    for _, player in roster.iterrows():
        player_name = str(player.get("player_name", "") or "").strip()
        if not player_name:
            continue
        player_id = player.get("player_id")
        normalized = _normalize_media_guide_identity(player_name)
        alias_used = False
        entry_matches = entries_by_name.get(normalized, [])
        if not entry_matches and normalized in aliases:
            entry_matches = entries_by_name.get(aliases[normalized], [])
            alias_used = bool(entry_matches)

        if not entry_matches:
            player_rows.append(
                {
                    "player_id": player_id,
                    "player_name": player_name,
                    "media_guide_page_start": "",
                    "media_guide_page_end": "",
                    "clean_bio": "",
                    "personal_notes": "",
                    "college_notes": "",
                    f"ausl_{media_context['previous_year']}_notes": "",
                    "awards_notes": "",
                    "fun_facts": "",
                    "previous_teams": "",
                    "career_summary": "",
                    "media_guide_bio": "",
                    "source_name": str(media_context["source_name"]),
                    "source_url": str(media_context["source_url"]),
                    "source_pages": "",
                    "source_page": "",
                    "expected_printed_pages": "",
                    "parsed_pdf_pages": "",
                    "pdf_page_offset": pdf_page_offset,
                    "guide_date": guide_date,
                    "match_status": "not_in_guide",
                    "confidence_score": 0.0,
                    "needs_review": True,
                    "warnings": "Exact player identity is absent from the media guide TOC.",
                    "note_count": 0,
                    "imported_at": imported_at,
                }
            )
            continue

        if len(entry_matches) != 1:
            player_rows.append(
                {
                    "player_id": player_id,
                    "player_name": player_name,
                    "media_guide_page_start": "",
                    "media_guide_page_end": "",
                    "clean_bio": "",
                    "personal_notes": "",
                    "college_notes": "",
                    f"ausl_{media_context['previous_year']}_notes": "",
                    "awards_notes": "",
                    "fun_facts": "",
                    "previous_teams": "",
                    "career_summary": "",
                    "media_guide_bio": "",
                    "source_name": str(media_context["source_name"]),
                    "source_url": str(media_context["source_url"]),
                    "source_pages": "",
                    "source_page": "",
                    "expected_printed_pages": "",
                    "parsed_pdf_pages": "",
                    "pdf_page_offset": pdf_page_offset,
                    "guide_date": guide_date,
                    "match_status": "needs_review",
                    "confidence_score": 0.0,
                    "needs_review": True,
                    "warnings": "Multiple exact TOC entries match this player identity.",
                    "note_count": 0,
                    "imported_at": imported_at,
                }
            )
            continue

        entry = entry_matches[0]
        printed_start = entry["printed_start"]
        printed_end = entry["printed_end"]
        pdf_start = printed_start + pdf_page_offset
        pdf_end = printed_end + pdf_page_offset
        expected_printed_pages = _page_range_text(printed_start, printed_end)
        parsed_pdf_pages = _page_range_text(pdf_start, pdf_end)
        missing_pages = [
            page_number
            for page_number in range(pdf_start, pdf_end + 1)
            if page_number not in page_by_number
        ]
        merged_raw = "\n".join(
            str(page_by_number[page_number].get("raw_text", "") or "")
            for page_number in range(pdf_start, pdf_end + 1)
            if page_number in page_by_number
        )
        merged_text = _clean_media_guide_text(merged_raw)
        warnings = []
        if alias_used:
            warnings.append(f"Explicit identity alias matched TOC name {entry['toc_name']}.")
        if missing_pages:
            warnings.append(
                "Mapped PDF pages are missing: "
                + ", ".join(str(page_number) for page_number in missing_pages)
                + "."
            )
        if not _media_guide_name_occurs(entry["toc_name"], merged_raw):
            warnings.append("Expected player name/header was not found in the mapped range.")

        ausl_notes = _extract_between_headers(
            merged_text, "AUSL/ATHLETES UNLIMITED EXPERIENCE", section_headers
        )
        other_pro = _extract_between_headers(
            merged_text, "OTHER PROFESSIONAL EXPERIENCE", section_headers
        )
        international = _extract_between_headers(
            merged_text, "INTERNATIONAL EXPERIENCE", section_headers
        )
        college = _extract_between_headers(
            merged_text, "COLLEGE EXPERIENCE", section_headers
        )
        personal = _extract_between_headers(merged_text, "PERSONAL", section_headers)
        career_summary = _clean_media_guide_text(
            " ".join(
                part for part in (other_pro, international, college) if part
            )
        )
        awards = _sentences_with_terms(
            " ".join((ausl_notes, other_pro, international, college, personal)),
            (
                "award",
                "honor",
                "all-american",
                "all-region",
                "player of the year",
                "all-conference",
                "gold",
                "team usa",
                "world series",
            ),
        )
        fun_facts = _sentences_with_terms(
            personal,
            (
                "hobby",
                "favorite",
                "family",
                "daughter",
                "sister",
                "brother",
                "father",
                "mother",
                "majored",
                "aspires",
                "proudest",
                "lists",
            ),
        )
        clean_bio = _clean_media_guide_text(
            " ".join(
                part
                for part in (ausl_notes, other_pro, international, college, personal)
                if part
            )
        )
        if not clean_bio:
            warnings.append("Mapped range contains no extractable biography sections.")
        match_status = "verified" if not warnings else "needs_review"
        confidence = 0.95 if match_status == "verified" and alias_used else (
            0.98 if match_status == "verified" else 0.45
        )
        warning_text = " | ".join(warnings)
        row = _apply_media_approval_fields({
            "entity_type": "player",
            "entity_id": player_id,
            "entity_name": player_name,
            "player_id": player_id,
            "player_name": player_name,
            "media_guide_page_start": printed_start,
            "media_guide_page_end": printed_end,
            "clean_bio": clean_bio,
            "personal_notes": personal,
            "college_notes": college,
            f"ausl_{media_context['previous_year']}_notes": ausl_notes,
            "awards_notes": awards,
            "fun_facts": fun_facts,
            "previous_teams": other_pro,
            "career_summary": career_summary,
            "media_guide_bio": clean_bio,
            "source_name": str(media_context["source_name"]),
            "source_url": str(media_context["source_url"]),
            "source_pages": parsed_pdf_pages,
            "source_page": pdf_start,
            "expected_printed_pages": expected_printed_pages,
            "parsed_pdf_pages": parsed_pdf_pages,
            "pdf_page_offset": pdf_page_offset,
            "guide_date": guide_date,
            "match_status": match_status,
            "confidence_score": confidence,
            "needs_review": match_status != "verified",
            "warnings": warning_text,
            "note_count": 0,
            "imported_at": imported_at,
        })
        notes = _deduplicate_media_note_rows(_media_note_rows(
            "player",
            player_id,
            player_name,
            row,
            parsed_pdf_pages,
            imported_at,
            confidence,
            match_status=match_status,
            expected_printed_pages=expected_printed_pages,
            parsed_pdf_pages=parsed_pdf_pages,
            guide_date=guide_date,
            warnings=warning_text,
        ))
        row["note_count"] = len(notes)
        player_rows.append(row)
        clean_note_rows.extend(notes)

    players = pd.DataFrame(player_rows)
    if players.empty or not players["match_status"].eq("verified").any():
        raise MediaGuideValidationError(
            "media guide parsing produced no verified player biographies"
        )
    return players, pd.DataFrame(_deduplicate_media_note_rows(clean_note_rows))


def _media_guide_audit_frame(media_players: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "player_id",
        "player_name",
        "match_status",
        "expected_printed_pages",
        "parsed_pdf_pages",
        "confidence",
        "note_count",
        "warnings",
        "guide_date",
    ]
    required = {
        "player_id",
        "player_name",
        "match_status",
        "expected_printed_pages",
        "parsed_pdf_pages",
        "confidence_score",
        "note_count",
        "warnings",
        "guide_date",
    }
    if media_players is None or media_players.empty:
        raise MediaGuideValidationError("media guide audit has no roster rows")
    missing = required.difference(media_players.columns)
    if missing:
        raise MediaGuideValidationError(
            "media guide audit is missing columns: " + ", ".join(sorted(missing))
        )
    if media_players["player_id"].isna().any() or media_players["player_id"].duplicated().any():
        raise MediaGuideValidationError("media guide audit player identities are not unique")
    allowed_statuses = {"verified", "needs_review", "not_in_guide"}
    statuses = set(media_players["match_status"].dropna().astype(str))
    if not statuses.issubset(allowed_statuses):
        raise MediaGuideValidationError("media guide audit contains an invalid match status")
    audit = media_players[
        [
            "player_id",
            "player_name",
            "match_status",
            "expected_printed_pages",
            "parsed_pdf_pages",
            "confidence_score",
            "note_count",
            "warnings",
            "guide_date",
        ]
    ].copy()
    audit = audit.rename(columns={"confidence_score": "confidence"})
    return audit[columns]


def _parse_media_guide_frames_from_pdf(
    roster: pd.DataFrame, pdf_path: Path, progress=None
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Parse one already-downloaded media guide candidate."""
    progress = progress or (lambda _message: None)
    imported_at = datetime.now(timezone.utc).isoformat()
    media_context = media_guide_source_context()

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for media guide parsing. Run Setup AUSL Environment.bat.") from exc

    progress("Extracting media guide text...")
    reader = PdfReader(str(pdf_path))
    page_rows = []
    for page_number, page in enumerate(reader.pages, 1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        clean = _clean_media_guide_text(raw)
        if clean:
            page_rows.append({"page": page_number, "raw_text": raw, "text": clean})

    team_rows, raw_chunk_rows = [], []

    for page in page_rows:
        raw_chunk_rows.append(
            {
                "chunk_id": f"media-page-{page['page']}",
                "source_page": page["page"],
                "raw_text": page["text"],
                "source_name": str(media_context["source_name"]),
                "source_url": str(media_context["source_url"]),
                "imported_at": imported_at,
            }
        )

    media_players, player_note_rows = _media_guide_player_frames(
        roster,
        page_rows,
        imported_at=imported_at,
    )
    guide_date = _media_guide_date(page_rows)
    pdf_page_offset = int(media_players["pdf_page_offset"].iloc[0])
    clean_note_rows = player_note_rows.to_dict("records")

    page_by_number = {page["page"]: page["text"] for page in page_rows}
    for short, team_name in TEAM_NAMES.items():
        code = TEAM_CODES[short]
        team_candidates = []
        for page in page_rows:
            text = page["text"]
            lower = text.lower()
            score = 0
            roster_header = f"{media_context['guide_year']} {team_name} roster".lower()
            if roster_header in lower:
                score += 12
            elif team_name.lower() in lower and "roster (as of" in lower:
                score += 8
            elif team_name.lower() in lower:
                score += 2
            if short.lower() in lower and "roster" in lower:
                score += 2
            if "roster (as of" in lower:
                score += 4
            if "general manager" in lower or "head coach" in lower or "support staff" in lower:
                score += 2
            if "media guide credits" in lower or page["page"] <= 4:
                score -= 20
            if "regular season schedule" in lower or "broadcast schedule" in lower:
                score -= 8
            if score > 0:
                team_candidates.append((score, page["page"], text))
        if team_candidates:
            team_candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            score, page_number, text = team_candidates[0]
            confidence = min(0.9, max(0.45, score / 10))
            context_pages = [page_number + offset for offset in (1, 2, 3) if page_by_number.get(page_number + offset)]
            context_text = " ".join(page_by_number.get(page, "") for page in context_pages)
            if not context_text:
                context_text = text
                context_pages = [page_number]
            overview = _clean_media_guide_text(context_text)
            overview = re.sub(r"\bNo\.\s+Name\s+Pos\.\s+Ht\.\s+B/T\s+Hometown\s+School\b.*?(?=(?:[A-Z][A-Z '-]{3,}\s+(?:GENERAL MANAGER|HEAD COACH)|$))", " ", overview)
            overview = _clean_media_guide_text(overview)
            source_pages = f"{page_number}-{max(context_pages)}" if context_pages else str(page_number)
            printed_start = page_number - pdf_page_offset
            printed_end = max(context_pages) - pdf_page_offset
            expected_printed_pages = _page_range_text(printed_start, printed_end)
            parsed_pdf_pages = source_pages
        else:
            page_number, confidence, overview, source_pages = "", 0.3, "", ""
            expected_printed_pages, parsed_pdf_pages = "", ""
        staff_following_labels = (
            "Head Coach",
            "Associate Head Coach",
            "Assistant Coaches",
            "Equipment Manager",
            "Assistant Equipment Manager",
            "Strength & Conditioning",
            "Head Athletic Trainer",
            "Assistant Athletic Trainer",
            "Team Operations Manager",
            "Softball Operations Coordinator",
        )
        general_manager = _extract_labeled_media_value(text if team_candidates else "", "General Manager", staff_following_labels)
        head_coach = _extract_labeled_media_value(text if team_candidates else "", "Head Coach", staff_following_labels)
        assistant_coaches = _extract_labeled_media_value(text if team_candidates else "", "Assistant Coaches", staff_following_labels)
        coach_match = None if head_coach else re.search(r"(?:Head Coach|Coach)\s+([A-Z][A-Za-z .'-]+)", overview)
        if not coach_match:
            coach_match = re.search(r"\b([A-Z][A-Z .'-]{3,})\s+HEAD COACH\b", overview)
        if not head_coach and coach_match:
            head_coach = _clean_text(coach_match.group(1).title())
        match_status = (
            "verified" if confidence >= 0.75 and overview else "needs_review"
        )
        warnings = (
            ""
            if match_status == "verified"
            else "Team media-guide section requires identity/source review."
        )
        row = _apply_media_approval_fields({
            "entity_type": "team",
            "entity_id": code,
            "entity_name": team_name,
            "team_code": code,
            "team_name": team_name,
            "general_manager": general_manager,
            "head_coach": head_coach,
            "assistant_coaches": assistant_coaches,
            "home_city": TEAM_HOME_CITY.get(code, ""),
            "venue": "Verify in official game notes",
            "team_overview": overview,
            f"{media_context['previous_year']}_recap": _sentences_with_terms(
                overview,
                (str(media_context["previous_year"]), "last season", "regular season", "champion", "record"),
            ),
            f"{media_context['guide_year']}_outlook": _sentences_with_terms(
                overview,
                (str(media_context["guide_year"]), "roster", "coach", "returns", "selected"),
            ),
            "team_history": overview,
            f"{media_context['guide_year']}_context": overview,
            "source_name": str(media_context["source_name"]),
            "source_url": str(media_context["source_url"]),
            "source_pages": source_pages,
            "source_page": page_number,
            "expected_printed_pages": expected_printed_pages,
            "parsed_pdf_pages": parsed_pdf_pages,
            "pdf_page_offset": pdf_page_offset,
            "guide_date": guide_date,
            "match_status": match_status,
            "confidence_score": confidence,
            "needs_review": match_status != "verified",
            "warnings": warnings,
            "imported_at": imported_at,
        })
        team_rows.append(row)
        clean_note_rows.extend(
            _media_note_rows(
                "team",
                code,
                team_name,
                row,
                source_pages,
                imported_at,
                confidence,
                match_status=match_status,
                expected_printed_pages=expected_printed_pages,
                parsed_pdf_pages=parsed_pdf_pages,
                guide_date=guide_date,
                warnings=warnings,
            )
        )

    media_notes = pd.DataFrame(_deduplicate_media_note_rows(clean_note_rows))
    media_audit = _media_guide_audit_frame(media_players)
    return (
        media_players,
        pd.DataFrame(team_rows),
        media_notes,
        pd.DataFrame(raw_chunk_rows),
        media_audit,
    )


def fetch_media_guide_frames(
    roster: pd.DataFrame,
    progress=None,
    *,
    cancel_token: CancelToken | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Revalidate the media guide and promote revised bytes only after parsing."""

    progress = progress or (lambda _message: None)
    media_context = media_guide_source_context()
    pdf_path = app_root() / "data" / "sources" / str(media_context["pdf_filename"])
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    handle, candidate_name = tempfile.mkstemp(
        prefix=".media-guide-download-", suffix=".pdf", dir=pdf_path.parent
    )
    os.close(handle)
    candidate_path = Path(candidate_name)
    try:
        progress(f"Revalidating {media_context['source_name']} PDF...")
        candidate_hash = _download_file(
            str(media_context["source_url"]),
            candidate_path,
            **_cancel_kwargs(cancel_token),
        )
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        existing_hash = None
        if pdf_path.exists():
            try:
                existing_hash = _sha256_hex(pdf_path.read_bytes())
            except OSError:
                existing_hash = None
        if existing_hash == candidate_hash:
            candidate_path.unlink()
            parse_path = pdf_path
        else:
            parse_path = candidate_path

        frames = _parse_media_guide_frames_from_pdf(
            roster, parse_path, progress
        )
        if parse_path == candidate_path:
            os.replace(candidate_path, pdf_path)
        return frames
    finally:
        if candidate_path.exists():
            candidate_path.unlink()


def source_registry_frame() -> pd.DataFrame:
    imported_at = datetime.now(timezone.utc).isoformat()
    return pd.DataFrame([{**row, "imported_at": imported_at} for row in build_enrichment_sources()])


def _json_array_after(text: str, marker: str) -> list[dict]:
    index = text.find(marker)
    if index < 0:
        return []
    start = text.find("[", index)
    if start < 0:
        return []
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : position + 1])
    return []


def _safe(value, default=""):
    return default if value is None else value


def _is_missing_scalar(value) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, type(pd.NA))) else False


def _clean_scalar_text(value) -> str:
    return "" if _is_missing_scalar(value) else str(value).strip()


_TEAM_CODE_ALIASES = {
    alias.casefold(): code
    for short, code in TEAM_CODES.items()
    for alias in (short, TEAM_NAMES[short], code)
}


def normalize_team_code(value) -> str | None:
    """Return a known AUSL team code without guessing from partial text."""
    text = _clean_scalar_text(value)
    return _TEAM_CODE_ALIASES.get(text.casefold()) if text else None


def normalize_roster_status(value) -> str:
    """Preserve an official status, making missing status explicitly unknown."""
    text = _clean_scalar_text(value)
    if not text or text.casefold() in {"nan", "none", "null", "n/a", "na", "—", "-"}:
        return "Status unknown"
    return text


def _nested(data: dict, *keys, default=""):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _team_fields(franchise: dict | None) -> tuple[str, str, str]:
    raw_name = _clean_scalar_text((franchise or {}).get("teamName"))
    code = normalize_team_code(raw_name)
    if code is None:
        return raw_name, raw_name, ""
    short = CODE_TO_SHORT[code]
    return short, CODE_TO_TEAM[code], code


def roster_frame(payload: dict, season: int) -> pd.DataFrame:
    rows = []
    for player in payload.get("players", []):
        info = _nested(player, "sportInfoBySport", "ausl", default={})
        franchise = player.get("franchise") or {}
        short, team, code = _team_fields(franchise)
        status_value = info.get("currentRosterStatus")
        status = status_value if isinstance(status_value, dict) else {}
        position = info.get("primaryPosition") or {}
        school = player.get("school") or {}
        birth = player.get("birthAddress") or {}
        image = player.get("imageResource") or {}
        height = player.get("height")
        rows.append(
            {
                "season": season,
                "player_id": player.get("playerId"),
                "player_name": f"{_safe(player.get('firstName'))} {_safe(player.get('lastName'))}".strip(),
                "first_name": _safe(player.get("firstName")),
                "last_name": _safe(player.get("lastName")),
                "team": team,
                "team_short": short,
                "team_code": code,
                "jersey_number": _safe(info.get("uniformNumberDisplay"), _safe(info.get("uniformNumber"))),
                "position": _safe(position.get("positionLk")),
                "position_name": _safe(position.get("description")),
                "bats_throws": _safe(info.get("batsThrows")),
                "roster_status": normalize_roster_status(
                    status.get("description") if isinstance(status_value, dict) else status_value
                ),
                "status_comments": _safe(status.get("comments")),
                "transaction_type": _safe(status.get("transactionType")),
                "college": _safe(school.get("schoolNameShort"), _safe(school.get("schoolName"))),
                "graduation_year": _safe(school.get("graduationYear")),
                "hometown": ", ".join(str(x) for x in [birth.get("city"), birth.get("state")] if x),
                "height_inches": _safe(height),
                "height": f"{int(height)//12}-{int(height)%12}" if isinstance(height, (int, float)) and not math.isnan(height) else "",
                "age": _safe(player.get("age")),
                "date_of_birth": _safe(player.get("dateOfBirth")),
                "headshot_url": _safe(image.get("imageUrl")),
                "player_slug": _safe(player.get("playerSlug")),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.dropna(subset=["player_id"])
        frame = frame[frame["player_name"].str.strip().ne("")]
        frame = frame.sort_values(["team", "jersey_number", "last_name"], kind="stable")
    return frame


def _base_stat_row(row: dict, season: int) -> dict:
    short, team, team_code = _team_fields({"teamName": row.get("franchiseName")})
    position = row.get("primaryPosition")
    position_code = position.get("positionLk") if isinstance(position, dict) else position
    position_description = position.get("description") if isinstance(position, dict) else position
    return {
        "season": season,
        "player_id": row.get("playerId"),
        "player_name": f"{_safe(row.get('firstName'))} {_safe(row.get('lastName'))}".strip(),
        "team": team,
        "team_short": short,
        "team_code": team_code,
        "jersey_number": _safe(row.get("uniformNumberDisplay"), _safe(row.get("uniformNumber"))),
        "position": _safe(position_code),
        "position_code": _safe(position_code),
        "position_description": _safe(position_description),
    }


def _flatten_stat_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    if "statIndicator" in frame:
        indicators = frame["statIndicator"].apply(lambda item: item if isinstance(item, dict) else {})
        frame["season_type"] = indicators.apply(lambda item: item.get("label") or item.get("split") or "")
        frame["game_type"] = frame.get("seasonType", "")
        if "split_key" not in frame:
            frame["split_key"] = indicators.apply(lambda item: item.get("split") or "")
        if "split_label" not in frame:
            frame["split_label"] = indicators.apply(lambda item: item.get("label") or item.get("split") or "Total Season")
        frame = frame.drop(columns=["statIndicator"])
    if "plateAppearances" in frame and "plate_appearances" not in frame:
        frame["plate_appearances"] = frame["plateAppearances"]
    for column in list(frame.columns):
        if frame[column].apply(lambda item: isinstance(item, (dict, list))).any():
            frame[column] = frame[column].apply(lambda item: json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item)
    return frame


def stat_frames(payload: dict, season: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    batting, pitching, fielding = [], [], []
    for row in payload.get("stats", []):
        if row.get("playerId") is None:
            continue
        base = _base_stat_row(row, season)
        if row.get("battingStats"):
            batting.append({**base, **row["battingStats"][0]})
        if row.get("pitchingStats"):
            pitching.append({**base, **row["pitchingStats"][0]})
        total_fielding = next((x for x in row.get("fieldingStats", []) if x.get("position") == "TOTAL"), None)
        if total_fielding is None and row.get("fieldingStats"):
            total_fielding = row["fieldingStats"][0]
        if total_fielding:
            positions = sorted({str(x.get("position")) for x in row.get("fieldingStats", []) if x.get("position") not in (None, "TOTAL")})
            fielding.append({**base, **total_fielding, "fielding_positions": "/".join(positions)})
    batting_frame = _flatten_stat_frame(pd.DataFrame(batting))
    pitching_frame = normalize_pitching_frame(_flatten_stat_frame(pd.DataFrame(pitching)))
    fielding_frame = _flatten_stat_frame(pd.DataFrame(fielding))
    return batting_frame, pitching_frame, fielding_frame


def split_stat_frames(payload: dict, season: int, split_key: str, split_label: str, source_url: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    imported_at = datetime.now(timezone.utc).isoformat()
    batting, pitching, fielding = stat_frames(payload, season)
    for frame in (batting, pitching, fielding):
        if not frame.empty:
            frame["split_key"] = split_key
            frame["split_label"] = split_label
            frame["source_name"] = "Official AUSL Split Stats"
            frame["source_url"] = source_url
            frame["imported_at"] = imported_at
    return batting, pitching, fielding


def fetch_split_payload(
    season_id: int,
    split_key: str,
    *,
    cancel_token: CancelToken | None = None,
) -> tuple[dict, str]:
    static_path = f"/data/statsApiData_{season_id}_{split_key}.json"
    try:
        return _get_json(
            static_path, **_cancel_kwargs(cancel_token)
        ), BASE_URL + static_path
    except HTTPError as exc:
        if exc.code != 404:
            raise
    api_path = f"/api/season-stats/{season_id}?statSplitType={split_key}"
    return _get_json(
        api_path, **_cancel_kwargs(cancel_token)
    ), BASE_URL + api_path


def fetch_standings_frame(*, cancel_token: CancelToken | None = None) -> pd.DataFrame:
    imported_at = datetime.now(timezone.utc).isoformat()
    page = _get_text("/standings/", **_cancel_kwargs(cancel_token))
    decoded = page.encode("utf-8").decode("unicode_escape", errors="ignore")
    rows = _json_array_after(decoded, '"standings":')
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["team_code"] = frame["franchiseSlug"].map(normalize_team_code)
    frame["team_name"] = frame["team_code"].map(CODE_TO_TEAM).fillna(frame["franchiseSlug"])
    frame["source_name"] = "Official AUSL Standings"
    frame["source_url"] = BASE_URL + "/standings/"
    frame["imported_at"] = imported_at
    return frame


def fetch_schedule_frame(*, cancel_token: CancelToken | None = None) -> pd.DataFrame:
    imported_at = datetime.now(timezone.utc).isoformat()
    page = _get_text("/schedule/", **_cancel_kwargs(cancel_token))
    decoded = page.encode("utf-8").decode("unicode_escape", errors="ignore")
    games = _json_array_after(decoded, '"games":')
    rows = []
    for game in games:
        competitors = game.get("competitors") or []
        competitor_by_id = {item.get("competitorId"): item for item in competitors if isinstance(item, dict)}
        home_team = game.get("homeTeam") or {}
        away_team = game.get("awayTeam") or {}
        home_team_obj = home_team if isinstance(home_team, dict) else {"name": home_team}
        away_team_obj = away_team if isinstance(away_team, dict) else {"name": away_team}
        home_competitor = competitor_by_id.get(game.get("homeTeamId"), {})
        away_competitor = competitor_by_id.get(game.get("awayTeamId"), {})
        # Home/away identity must come from the official side-specific IDs or
        # fields. Competitor list order is not an identity guarantee.
        home_name = home_competitor.get("name") or home_team_obj.get("name") or ""
        away_name = away_competitor.get("name") or away_team_obj.get("name") or ""
        if home_name in TEAM_NAMES:
            home_name = TEAM_NAMES[home_name]
        if away_name in TEAM_NAMES:
            away_name = TEAM_NAMES[away_name]
        venue = game.get("venue") or {}
        address = venue.get("address") or {}
        game_notes = game.get("previewNotes") or game.get("boxScoreNotes") or []
        if isinstance(game_notes, list):
            game_notes = "; ".join(
                str(item.get("url") or item.get("link") or item.get("title") or item) if isinstance(item, dict) else str(item)
                for item in game_notes
            )
        away_code = next(
            (
                code
                for code in (
                    normalize_team_code(away_competitor.get("name")),
                    normalize_team_code(away_team_obj.get("name")),
                    normalize_team_code(away_name),
                )
                if code is not None
            ),
            None,
        )
        home_code = next(
            (
                code
                for code in (
                    normalize_team_code(home_competitor.get("name")),
                    normalize_team_code(home_team_obj.get("name")),
                    normalize_team_code(home_name),
                )
                if code is not None
            ),
            None,
        )
        if away_code:
            away_name = CODE_TO_TEAM[away_code]
        if home_code:
            home_name = CODE_TO_TEAM[home_code]
        rows.append(
            {
                "season": game.get("seasonId"),
                "game_id": game.get("gameId"),
                "game_date": game.get("gameDateIso") or game.get("gameDate"),
                "game_time": game.get("gameTime"),
                "game_time_zone": game.get("gameTimeZone"),
                "away_team": away_name,
                "home_team": home_name,
                "away_team_code": away_code or "",
                "home_team_code": home_code or "",
                "away_score": game.get("awayTeamScore"),
                "home_score": game.get("homeTeamScore"),
                "venue": venue.get("name"),
                "city": address.get("city"),
                "state": address.get("state"),
                "status": game.get("recordStatus"),
                "game_type": game.get("gameTypeLk"),
                "broadcast": ", ".join(str(item.get("name")) for item in (game.get("broadcasts") or []) if item.get("name")),
                "game_notes": game_notes,
                "source_name": "Official AUSL Schedule",
                "source_url": f"{BASE_URL}/game/{game.get('gameId')}",
                "imported_at": imported_at,
            }
        )
    return pd.DataFrame(rows)


def _urls_from_text(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"https?://[^\s;]+", text)


def _game_note_category(text: str) -> str:
    lower = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    if re.search(
        r"\b(injur(?:y|ed)|illness|ill|inactive|unavailable|availability|"
        r"transaction|transferred|released|waived|roster (?:move|change))\b",
        lower,
    ):
        return "availability"
    if (
        re.search(r"\b(?:probable|projected) starter\b", lower)
        or re.search(
            r"\b(?:scheduled|announced|expected|slated)\b.{0,80}"
            r"(?:\b(?:start|starter|starting pitcher)\b.{0,80}"
            r"\b(?:today|tonight|this game|game \d+)\b|"
            r"\b(?:today|tonight|this game|game \d+)['’s ]{0,3}.{0,80}"
            r"\b(?:start|starter|starting pitcher)\b)",
            lower,
        )
        or re.search(r"\b(?:will start|starts? (?:today|tonight)|starting (?:today|tonight))\b", lower)
    ):
        return "probable_starter"
    if (
        re.search(
            r"\b(?:became the first|first (?:ausl )?(?:player|pitcher|batter))\b",
            lower,
        )
        or re.search(r"\b(?:broke|tied|set)\b.{0,50}\b(?:record|mark)\b", lower)
        or re.search(r"\breached\b.{0,80}\b(?:\d+[,.]?\d*|career|record|milestone)\b", lower)
    ):
        return "milestone_reached"
    if (
        re.search(r"\b(?:needs?|within|approaching)\b.{0,100}\b\d+[,.]?\d*\b", lower)
        or re.search(r"\bneeds?\b.{0,80}\bmilestone\b", lower)
        or re.search(r"\b(?:\d+|one|two|three|four|five)\b.{0,30}\b(?:shy|away) from\b.{0,60}\b\d+\b", lower)
    ):
        return "milestone_watch"
    if re.search(r"\b(?:head-to-head|rematch|season series|series (?:between|against)|exact-opponent)\b", lower):
        return "matchup_history"
    if (
        re.search(r"\b(?:streak|straight games?|last (?:week|night|game|\d+)|over the last \d+|since [a-z]+ \d{1,2})\b", lower)
        or re.search(r"\b(?:won|lost)\b.{0,20}\b(?:straight|in a row)\b", lower)
    ):
        return "recent_trend"
    if re.search(r"\b(?:this|current|\d{4}|ausl) season\b", lower):
        return "season_context"
    if "career" in lower:
        return "career_summary"
    return "background"


def _clean_game_note_text(text: str) -> str:
    text = str(text or "").replace("\x83", " • ").replace("\uf0b7", " • ").replace("â€¢", " • ")
    text = _clean_media_guide_text(text)
    text = re.sub(r"\b[A-Z ]+\s+•\s+\d{4} AUSL Season\b", " ", text)
    text = re.sub(r"\b(?:PITCHER|BATTER) BIOS?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -•")
    return _clean_text(text)


def _looks_like_game_note_table(text: str) -> bool:
    lower = str(text or "").lower()
    if "date opponent score/time" in lower or "date opponent location score" in lower:
        return True
    if "statistics player c 1b 2b" in lower or "statistics team runs, game" in lower:
        return True
    if "player c 1b 2b 3b ss lf cf rf" in lower:
        return True
    numberish = len(re.findall(r"\b\d+(?:[./:-]\d+)*\b", lower))
    return numberish >= 18 and len(lower) < 900


def _game_note_name_key(name: str) -> str:
    return re.sub(r"[^A-Z]", "", str(name or "").upper())


def _resolve_game_note_header_name(header_name: str, player_lookup: list[dict]) -> tuple[str, str, str]:
    header_key = _game_note_name_key(header_name)
    if not header_key:
        return "", "", ""
    for player in player_lookup:
        if player["key"] == header_key:
            return player["name"], player["player_id"], player.get("team_code", "")
    for player in player_lookup:
        if player["last_key"] and player["last_key"] in header_key and header_key.startswith(player["first_initial"]):
            return player["name"], player["player_id"], player.get("team_code", "")
    return _clean_text(str(header_name).title()), "", ""


def _extract_game_note_header(section_text: str, player_lookup: list[dict]) -> tuple[str, str, str]:
    header_match = re.search(
        r"#\d+\s*[-•]\s*([A-Z][A-Za-z .'\-]+?)(?=\s+(?:\d|[•]\s*(?:P|CATCHER|INFIELD|OUTFIELD|UTILITY|INF|OF|C|UTIL)|(?:P|C|INF|OF|UTIL)\b))",
        section_text,
    )
    if not header_match:
        return "", "", ""
    return _resolve_game_note_header_name(header_match.group(1), player_lookup)


def _note_already_names_player(note: str, player_name: str) -> bool:
    if not player_name:
        return True
    note_key = _game_note_name_key(note[:80])
    name_parts = [part for part in str(player_name).split() if part]
    first_key = _game_note_name_key(name_parts[0]) if name_parts else ""
    last_key = _game_note_name_key(name_parts[-1]) if name_parts else ""
    full_key = _game_note_name_key(player_name)
    return bool((full_key and full_key in note_key) or (last_key and last_key in note_key) or (first_key and note_key.startswith(first_key)))


def _split_game_note_items(page_text: str, player_lookup: list[dict] | None = None) -> list[dict]:
    player_lookup = player_lookup or []
    text = str(page_text or "").replace("\x83", " • ").replace("\uf0b7", " • ").replace("â€¢", " • ")
    if _looks_like_game_note_table(text):
        return []

    header_pattern = re.compile(
        r"#\d+\s*[-•]\s*[A-Z][A-Za-z .'\-]+?(?=\s+(?:\d|[•]\s*(?:P|CATCHER|INFIELD|OUTFIELD|UTILITY|INF|OF|C|UTIL)|(?:P|C|INF|OF|UTIL)\b))"
    )
    header_matches = list(header_pattern.finditer(text))
    if header_matches:
        sections = [
            text[match.start() : header_matches[index + 1].start() if index + 1 < len(header_matches) else len(text)]
            for index, match in enumerate(header_matches)
        ]
    else:
        sections = [text]

    cleaned = []
    for section in sections:
        player_name, player_id, team_code = _extract_game_note_header(section, player_lookup)
        parts = re.split(r"\s+•\s+", section)
        items = parts[1:] if len(parts) > 1 else re.split(r"(?<=[.!?])\s+(?=[A-Z#])", section)
        for item in items:
            note = _clean_game_note_text(item)
            note = re.split(r"\s+#\d+\s+[-•]\s+[A-Z][A-Za-z .'-]{4,}\s+(?:\d|\.|[A-Z]{2,})", note)[0]
            note = re.split(r"\s+\d{4} AUSL SEASON SINGLE-GAME HIGHS\b", note, flags=re.IGNORECASE)[0]
            note = re.split(r"\s+SINGLE-GAME HIGHS\b", note, flags=re.IGNORECASE)[0]
            note = re.split(r"\s+CAREER HIGHS\b", note, flags=re.IGNORECASE)[0]
            if len(note) < 35:
                continue
            if _looks_like_game_note_table(note):
                continue
            if player_name and not _note_already_names_player(note, player_name):
                note = f"{player_name}: {note}"
            if len(note) > 500:
                note = note[:500].rstrip() + "..."
            cleaned.append(
                {
                    "note_text": note,
                    "player_name": player_name,
                    "player_id": player_id,
                    "team_code": team_code,
                }
            )
    return cleaned


OFFICIAL_GAME_NOTES_PARSER_VERSION = "2.0"


def _normalized_game_note_hash(note_text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(note_text or "")).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _official_game_note_row(
    game: pd.Series,
    parsed_note: dict,
    *,
    source_url: str,
    source_page: int,
    imported_at: str,
    mentioned_ids: list[str] | None = None,
) -> dict:
    note = str(parsed_note.get("note_text", "")).strip()
    game_id = game.get("game_id", "")
    game_date = game.get("game_date", "")
    away_code = str(game.get("away_team_code", "") or "")
    home_code = str(game.get("home_team_code", "") or "")
    subject_team_code = str(parsed_note.get("team_code", "") or "")
    opposing_team_code = ""
    if subject_team_code == away_code:
        opposing_team_code = home_code
    elif subject_team_code == home_code:
        opposing_team_code = away_code
    player_id = str(parsed_note.get("player_id", "") or "").strip()
    player_ids = [str(item).strip() for item in (mentioned_ids or []) if str(item).strip()]
    if player_id:
        player_ids = [player_id, *[item for item in player_ids if item != player_id]]
    source_pdf = source_url.rsplit("/", 1)[-1].split("?", 1)[0]
    return {
        "game_id": game_id,
        "game_date": game_date,
        "team_codes": ",".join(code for code in (away_code, home_code) if code),
        "note_text": note,
        "note_category": _game_note_category(note),
        "player_ids": ",".join(player_ids[:12]),
        "subject_player_id": player_id,
        "subject_player_name": str(parsed_note.get("player_name", "") or "").strip(),
        "subject_team_code": subject_team_code,
        "opposing_team_code": opposing_team_code,
        "effective_date": game_date,
        "source_date": game_date,
        "source_game_id": game_id,
        "source_url": source_url,
        "source_pdf": source_pdf,
        "source_page": source_page,
        "parser_version": OFFICIAL_GAME_NOTES_PARSER_VERSION,
        "normalized_hash": _normalized_game_note_hash(note),
        "verification_state": "VERIFY",
        "imported_at": imported_at,
        "confidence_score": 0.78 if player_ids else 0.68,
        "needs_review": True,
    }


def _deduplicate_official_game_notes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    rows = frame.copy()
    rows["normalized_hash"] = rows.get("note_text", pd.Series("", index=rows.index)).map(
        _normalized_game_note_hash
    )
    player_ids = rows.get("subject_player_id", pd.Series("", index=rows.index)).fillna("").astype(str)
    player_names = rows.get("subject_player_name", pd.Series("", index=rows.index)).fillna("").astype(str).str.casefold()
    team_codes = rows.get("subject_team_code", pd.Series("", index=rows.index)).fillna("").astype(str)
    rows["_dedup_subject"] = player_ids.where(player_ids.ne(""), player_names)
    rows["_dedup_subject"] = rows["_dedup_subject"].where(rows["_dedup_subject"].ne(""), team_codes)
    rows["_source_sort"] = pd.to_datetime(
        rows.get("source_date", pd.Series(pd.NaT, index=rows.index)), errors="coerce", utc=True
    )
    rows["_import_sort"] = pd.to_datetime(
        rows.get("imported_at", pd.Series(pd.NaT, index=rows.index)), errors="coerce", utc=True
    )
    states = rows.get("verification_state", pd.Series("VERIFY", index=rows.index)).fillna("VERIFY").astype(str).str.upper()
    rows["_verified"] = states.eq("VERIFIED")
    history_fields = (
        "source_url",
        "source_pdf",
        "source_page",
        "source_date",
        "source_game_id",
        "game_id",
        "verification_state",
    )
    kept_rows = []
    for _, group in rows.groupby(["normalized_hash", "_dedup_subject"], sort=False, dropna=False):
        ranked = group.sort_values(
            ["_verified", "_source_sort", "_import_sort"],
            ascending=[False, False, False],
            na_position="last",
        )
        kept = ranked.iloc[0].copy()
        history_group = group.sort_values(
            ["_source_sort", "_import_sort"], ascending=[True, True], na_position="last"
        )
        history = []
        for _, source in history_group.iterrows():
            item = {
                field: source.get(field, "")
                for field in history_fields
                if field in source.index and not pd.isna(source.get(field))
            }
            if item not in history:
                history.append(item)
        kept["source_history"] = json.dumps(history, default=str, separators=(",", ":"))
        kept_rows.append(kept)
    result = pd.DataFrame(kept_rows).drop(
        columns=["_dedup_subject", "_source_sort", "_import_sort", "_verified"],
        errors="ignore",
    )
    return result.reset_index(drop=True)


def _game_notes_cache_path() -> Path:
    return app_root() / "data" / "sources" / "game_notes" / ".notes_parse_cache.json"


def _load_game_notes_cache() -> dict:
    """Load the per-PDF parsed-note cache, keyed by local PDF filename.

    Each entry records the sha256 of the PDF bytes it was parsed from, so an
    unchanged file can reuse its cached rows instead of being re-parsed
    (REFRESH-005: cache and incrementally process unchanged PDFs).
    """

    cache_path = _game_notes_cache_path()
    if not cache_path.exists():
        return {}
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


def _save_game_notes_cache(cache: dict) -> None:
    cache_path = _game_notes_cache_path()

    def _json_safe(value):
        if hasattr(value, "item"):
            return value.item()
        return str(value)

    safe_cache = json.loads(json.dumps(cache, default=_json_safe))
    _write_json_atomic(cache_path, safe_cache, prefix=".notes-cache-")


def fetch_official_game_notes_frame(
    schedule: pd.DataFrame,
    roster: pd.DataFrame,
    progress=None,
    limit: int | None = None,
    *,
    cancel_token: CancelToken | None = None,
) -> pd.DataFrame:
    progress = progress or (lambda _message: None)
    if schedule.empty or "game_notes" not in schedule:
        return pd.DataFrame()
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for official game notes parsing. Run Setup AUSL Environment.bat.") from exc

    imported_at = datetime.now(timezone.utc).isoformat()
    rows = []
    note_urls = []
    for _, game in schedule.iterrows():
        for url in _urls_from_text(str(game.get("game_notes", ""))):
            note_urls.append((game, url))
    if limit:
        note_urls = note_urls[:limit]

    player_lookup = []
    if not roster.empty:
        for _, player in roster.iterrows():
            name = str(player.get("player_name", "")).strip()
            if name:
                parts = name.split()
                player_lookup.append(
                    {
                        "name": name,
                        "player_id": str(player.get("player_id", "")),
                        "team_code": str(player.get("team_code", "") or ""),
                        "key": _game_note_name_key(name),
                        "first_initial": _game_note_name_key(parts[0])[:1] if parts else "",
                        "last_key": _game_note_name_key(parts[-1]) if parts else "",
                    }
                )

    notes_cache = _load_game_notes_cache()
    cache_dirty = False

    for game, url in note_urls:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        game_id = game.get("game_id", "")
        safe_url_tail = re.sub(r"[^A-Za-z0-9]+", "_", url.split("/")[-1]).strip("_")[:80] or "notes"
        pdf_path = app_root() / "data" / "sources" / "game_notes" / f"game_{game_id}_{safe_url_tail}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        cache_key = pdf_path.name
        cached_entry = notes_cache.get(cache_key)
        handle, candidate_name = tempfile.mkstemp(
            prefix=".game-notes-download-", suffix=".pdf", dir=pdf_path.parent
        )
        os.close(handle)
        candidate_path = Path(candidate_name)
        try:
            progress(f"Revalidating official game notes for game {game_id}...")
            try:
                content_hash = _download_file(
                    url, candidate_path, **_cancel_kwargs(cancel_token)
                )
            except RefreshCancelled:
                raise
            except Exception as exc:
                progress(f"Skipping game notes {game_id}: {exc}")
                if (
                    pdf_path.exists()
                    and isinstance(cached_entry, dict)
                    and cached_entry.get("rows")
                ):
                    rows.extend(cached_entry.get("rows") or [])
                continue

            if (
                isinstance(cached_entry, dict)
                and cached_entry.get("content_hash") == content_hash
            ):
                progress(f"Reusing cached parse for unchanged game notes {game_id}.")
                rows.extend(cached_entry.get("rows") or [])
                continue

            try:
                reader = PdfReader(str(candidate_path))
            except Exception as exc:
                progress(f"Skipping unreadable revised game notes {game_id}: {exc}")
                if (
                    pdf_path.exists()
                    and isinstance(cached_entry, dict)
                    and cached_entry.get("rows")
                ):
                    rows.extend(cached_entry.get("rows") or [])
                continue
            file_rows = []
            for page_number, page in enumerate(reader.pages, 1):
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                for parsed_note in _split_game_note_items(page_text, player_lookup):
                    note = parsed_note["note_text"]
                    mentioned_ids = [
                        player["player_id"]
                        for player in player_lookup
                        if player["name"].lower() in note.lower()
                    ]
                    file_rows.append(
                        _official_game_note_row(
                            game,
                            parsed_note,
                            source_url=url,
                            source_page=page_number,
                            imported_at=imported_at,
                            mentioned_ids=mentioned_ids,
                        )
                    )
            if not file_rows:
                progress(
                    f"Skipping revised game notes {game_id}: no validated note rows."
                )
                if (
                    pdf_path.exists()
                    and isinstance(cached_entry, dict)
                    and cached_entry.get("rows")
                ):
                    rows.extend(cached_entry.get("rows") or [])
                continue
            os.replace(candidate_path, pdf_path)
            rows.extend(file_rows)
            notes_cache[cache_key] = {
                "content_hash": content_hash,
                "rows": file_rows,
            }
            cache_dirty = True
        finally:
            if candidate_path.exists():
                candidate_path.unlink()

    if cache_dirty:
        _save_game_notes_cache(notes_cache)

    return _deduplicate_official_game_notes(pd.DataFrame(rows))


MANUAL_NOTE_REQUIRED_COLUMNS = [
    "note_id",
    "scope",
    "player_id",
    "player_name",
    "team_code",
    "game_id",
    "note_text",
    "author",
    "source",
    "created_at",
    "updated_at",
]

# New stores retain the current application's optional fields. Existing stores
# are only given the required scope fields above, so an already-current file is
# not rewritten merely to add optional columns.
MANUAL_NOTE_COLUMNS = MANUAL_NOTE_REQUIRED_COLUMNS + [
    "note_type",
    "entered_by",
    "last_verified_date",
    "air_safe",
]


def write_manual_notes_atomic(path: Path | str, frame: pd.DataFrame) -> Path:
    """Atomically replace a manual-note CSV in its existing directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    try:
        frame.to_csv(temp_name, index=False, encoding="utf-8", lineterminator="\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)
    return path


LINEUP_STORE_SCHEMA_VERSION = 2


def empty_locked_lineup_store() -> dict:
    """Return the game-ID-keyed lineup store without attaching legacy data."""
    return {
        "schema_version": LINEUP_STORE_SCHEMA_VERSION,
        "games": {},
        "legacy_unassigned": [],
    }


def write_locked_lineups_atomic(path: Path | str, store: dict) -> Path:
    """Atomically replace a lineup-lock JSON file in its existing directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(store, indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    try:
        Path(temp_name).write_text(serialized, encoding="utf-8")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)
    return path


def _is_current_locked_lineup_store(store) -> bool:
    return (
        isinstance(store, dict)
        and store.get("schema_version") == LINEUP_STORE_SCHEMA_VERSION
        and isinstance(store.get("games"), dict)
        and isinstance(store.get("legacy_unassigned"), list)
    )


def migrate_locked_lineups_file(path: Path | str) -> tuple[dict, Path | None]:
    """Load exact-game locks and safely quarantine legacy matchup-keyed locks.

    A legacy matchup can refer to more than one official game, so every legacy
    payload is retained verbatim under ``legacy_unassigned``. The original file
    is copied byte-for-byte before the migrated store atomically replaces it.
    """
    path = Path(path)
    if not path.exists():
        return empty_locked_lineup_store(), None

    original_bytes = path.read_bytes()
    try:
        loaded = json.loads(original_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Lineup-lock file is unreadable and was left unchanged: {path}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError(
            f"Lineup-lock file must contain a JSON object and was left unchanged: {path}"
        )
    if _is_current_locked_lineup_store(loaded):
        return loaded, None
    if not loaded:
        return empty_locked_lineup_store(), None

    migrated = empty_locked_lineup_store()
    migrated["legacy_unassigned"] = [
        {
            "status": "legacy_unassigned",
            "legacy_key": str(key),
            "payload": payload,
        }
        for key, payload in loaded.items()
    ]
    backup = _write_exact_backup(path, original_bytes)
    write_locked_lineups_atomic(path, migrated)
    return migrated, backup


def _manual_note_value_present(value) -> bool:
    return bool(_clean_scalar_text(value))


def _legacy_note_scope(row: pd.Series) -> str:
    player_present = _manual_note_value_present(row.get("player_id"))
    game_present = _manual_note_value_present(row.get("game_id"))
    team_present = _manual_note_value_present(row.get("team_code"))
    if player_present and not game_present:
        return "player"
    if game_present and not player_present:
        return "game"
    if team_present and not player_present and not game_present:
        return "team"
    return "legacy_unassigned"


def _write_exact_backup(path: Path, original_bytes: bytes) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for suffix in range(1000):
        counter = "" if suffix == 0 else f"-{suffix}"
        backup = path.with_name(f"{path.name}.backup-{stamp}{counter}")
        try:
            with backup.open("xb") as stream:
                stream.write(original_bytes)
            if backup.read_bytes() != original_bytes:
                raise OSError(f"Backup verification failed: {backup}")
            return backup
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not allocate a unique backup name for {path}")


def migrate_manual_notes_file(
    path: Path | str,
) -> tuple[pd.DataFrame, Path | None]:
    """Upgrade a legacy note CSV without discarding rows or unknown columns.

    The exact original bytes are copied to the returned backup path before the
    migrated CSV replaces the source. Ambiguous rows are retained with
    ``legacy_unassigned`` scope instead of being guessed into an air-visible
    player, team, game, or global scope.
    """
    path = Path(path)
    if not path.exists():
        frame = pd.DataFrame(columns=MANUAL_NOTE_COLUMNS)
        write_manual_notes_atomic(path, frame)
        return frame, None

    original_bytes = path.read_bytes()
    try:
        frame = pd.read_csv(path, dtype=object, keep_default_na=False)
    except pd.errors.EmptyDataError:
        frame = pd.DataFrame()
    migrated = frame.copy()
    changed = False

    for column in MANUAL_NOTE_REQUIRED_COLUMNS:
        if column not in migrated:
            migrated[column] = ""
            changed = True

    for index, row in migrated.iterrows():
        if not _manual_note_value_present(row.get("scope")):
            migrated.at[index, "scope"] = _legacy_note_scope(row)
            changed = True

        if not _manual_note_value_present(row.get("note_text")) and _manual_note_value_present(
            row.get("text")
        ):
            migrated.at[index, "note_text"] = row.get("text")
            changed = True

        if not _manual_note_value_present(row.get("author")) and _manual_note_value_present(
            row.get("entered_by")
        ):
            migrated.at[index, "author"] = row.get("entered_by")
            changed = True
        if (
            "entered_by" in migrated
            and not _manual_note_value_present(row.get("entered_by"))
            and _manual_note_value_present(row.get("author"))
        ):
            migrated.at[index, "entered_by"] = row.get("author")
            changed = True

        if not _manual_note_value_present(row.get("updated_at")) and _manual_note_value_present(
            row.get("created_at")
        ):
            migrated.at[index, "updated_at"] = row.get("created_at")
            changed = True
        if not _manual_note_value_present(row.get("source")):
            migrated.at[index, "source"] = "manual"
            changed = True

    if not changed:
        return migrated, None

    backup = _write_exact_backup(path, original_bytes)
    write_manual_notes_atomic(path, migrated)
    return migrated, backup


def ensure_manual_notes_file() -> Path:
    path = app_root() / "data" / "manual" / "player_notes.csv"
    migrate_manual_notes_file(path)
    return path


def load_manual_notes() -> pd.DataFrame:
    path = ensure_manual_notes_file()
    return pd.read_csv(path)


def innings_to_outs(value) -> int | None:
    """Parse baseball innings notation, returning unavailable for bad input.

    The fractional digit is an out count, not a decimal fraction. A small
    tolerance accepts binary spreadsheet representations such as
    ``9.199999999999999`` while rejecting genuine values such as ``1.3``.
    """
    if isinstance(value, bool) or _is_missing_scalar(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    whole = math.floor(number)
    fraction = number - whole
    partial_outs = round(fraction * 10)
    if partial_outs not in (0, 1, 2):
        return None
    if not math.isclose(fraction, partial_outs / 10, rel_tol=0, abs_tol=1e-8):
        return None
    return int(whole * 3 + partial_outs)


def outs_to_innings(outs) -> str | None:
    """Format a nonnegative whole number of outs as exact innings notation."""
    if isinstance(outs, bool) or _is_missing_scalar(outs):
        return None
    try:
        number = float(outs)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    whole_outs = int(number)
    return f"{whole_outs // 3}.{whole_outs % 3}"


# Private compatibility aliases for older imports. New code should use the
# public helpers so an unavailable value cannot be mistaken for zero.
def _ip_to_outs(value) -> int | None:
    return innings_to_outs(value)


def _outs_to_ip(outs) -> str | None:
    return outs_to_innings(outs)


def _finite_numeric_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.map(
        lambda item: bool(pd.notna(item) and math.isfinite(float(item)))
    )
    return numeric.where(finite, pd.NA)


def _finite_nonnegative_number(value) -> float | None:
    if isinstance(value, bool) or _is_missing_scalar(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def canonical_pitching_whip(row) -> float | None:
    """Derive WHIP from official counting inputs and canonical baseball outs.

    The imported ``whip`` field is never a fallback. Incomplete, malformed,
    negative, or zero-inning inputs make the result unavailable.
    """

    if row is None:
        return None
    try:
        innings = row.get("inningsPitched")
        hits = _finite_nonnegative_number(row.get("hitsAllowed"))
        walks = _finite_nonnegative_number(row.get("baseOnBalls"))
    except AttributeError:
        return None
    outs = innings_to_outs(innings)
    if outs is None or outs <= 0 or hits is None or walks is None:
        return None
    return (hits + walks) * 3 / outs


def normalize_pitching_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Retain imported WHIP and replace producer-facing WHIP canonically."""

    normalized = frame.copy()
    if normalized.empty:
        return normalized
    if "source_whip" not in normalized:
        normalized["source_whip"] = (
            normalized["whip"]
            if "whip" in normalized
            else pd.Series(pd.NA, index=normalized.index, dtype="Float64")
        )
    innings_values = (
        normalized["inningsPitched"]
        if "inningsPitched" in normalized
        else pd.Series(pd.NA, index=normalized.index, dtype=object)
    )
    normalized["innings_outs"] = innings_values.map(innings_to_outs).astype("Int64")
    hits = _numeric_column_or_na(normalized, "hitsAllowed")
    walks = _numeric_column_or_na(normalized, "baseOnBalls")
    outs = pd.to_numeric(normalized["innings_outs"], errors="coerce")
    innings_invalid = outs.isna() | outs.le(0)
    hits_invalid = hits.isna() | hits.lt(0)
    walks_invalid = walks.isna() | walks.lt(0)
    available = ~(innings_invalid | hits_invalid | walks_invalid)
    normalized["whip_inputs_available"] = available.astype("boolean")
    normalized["whip_input_invalid_count"] = (
        innings_invalid.astype(int) + hits_invalid.astype(int) + walks_invalid.astype(int)
    ).astype("Int64")
    normalized["whip"] = (((hits + walks) * 3) / outs).where(available, pd.NA)
    return normalized


def _complete_group_sums(
    source: pd.DataFrame,
    group_keys: list[str],
    columns: list[str],
) -> pd.DataFrame:
    """Sum only fully observed numeric columns for each player.

    A partial career total is more dangerous than an unavailable one because
    pandas otherwise treats a missing season contribution like zero.
    """

    present = [column for column in columns if column in source]
    if not present:
        return source[group_keys].drop_duplicates(ignore_index=True)

    numeric = source[group_keys].copy()
    for column in present:
        numeric[column] = _finite_numeric_series(source[column])
    groups = numeric.groupby(group_keys, dropna=False, sort=False)
    sums = groups[present].sum(min_count=1)
    complete = groups[present].count().eq(groups.size(), axis=0)
    return sums.where(complete).reset_index()


def _merge_season_counts(
    grouped: pd.DataFrame,
    source: pd.DataFrame,
    group_keys: list[str],
) -> pd.DataFrame:
    if "season" not in source:
        grouped["seasons"] = pd.NA
        return grouped
    season_counts = (
        source.groupby(group_keys, as_index=False, dropna=False)["season"]
        .nunique()
        .rename(columns={"season": "seasons"})
    )
    return grouped.merge(season_counts, on=group_keys, how="left", validate="one_to_one")


def _numeric_column_or_na(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return _finite_numeric_series(frame[column])


def _json_source_values(rows: pd.DataFrame, column: str) -> str:
    raw_values = rows[column] if column in rows else pd.Series(pd.NA, index=rows.index)
    source_values = []
    for raw_value in raw_values:
        if _is_missing_scalar(raw_value):
            source_values.append(None)
        elif hasattr(raw_value, "item"):
            try:
                source_values.append(raw_value.item())
            except (TypeError, ValueError):
                source_values.append(str(raw_value))
        else:
            source_values.append(raw_value)
    return json.dumps(source_values, ensure_ascii=False, default=str)


def career_batting(frames: list[pd.DataFrame]) -> pd.DataFrame:
    source = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if source.empty:
        return source
    group_keys = ["player_id", "player_name"]
    sum_cols = ["gamesPlayed", "gamesStarted", "plateAppearances", "atBat", "runs", "hits", "doubles", "triples", "homeRuns", "runsBattedIn", "baseonBalls", "intentionalWalks", "hitByPitch", "strikeOuts", "stolenBases", "stolenBasesAttempts", "caughtStealing", "totalBases", "sacrificeFly", "sacrificeHit"]
    grouped = _complete_group_sums(source, group_keys, sum_cols)
    grouped = _merge_season_counts(grouped, source, group_keys)

    ab = _numeric_column_or_na(grouped, "atBat")
    hits = _numeric_column_or_na(grouped, "hits")
    total_bases = _numeric_column_or_na(grouped, "totalBases")
    walks = _numeric_column_or_na(grouped, "baseonBalls")
    hbp = _numeric_column_or_na(grouped, "hitByPitch")
    sacrifice_flies = _numeric_column_or_na(grouped, "sacrificeFly")
    valid_ab = ab.notna() & ab.gt(0)
    ob_denominator = ab + walks + hbp + sacrifice_flies

    grouped["battingAverage"] = (hits / ab).where(valid_ab & hits.notna(), pd.NA)
    grouped["sluggingPercentage"] = (total_bases / ab).where(
        valid_ab & total_bases.notna(), pd.NA
    )
    grouped["onBasePercentage"] = ((hits + walks + hbp) / ob_denominator).where(
        hits.notna()
        & walks.notna()
        & hbp.notna()
        & sacrifice_flies.notna()
        & ob_denominator.gt(0),
        pd.NA,
    )
    grouped["opsPercentage"] = (
        grouped["onBasePercentage"] + grouped["sluggingPercentage"]
    ).where(
        grouped["onBasePercentage"].notna()
        & grouped["sluggingPercentage"].notna(),
        pd.NA,
    )
    return grouped


def career_pitching(frames: list[pd.DataFrame]) -> pd.DataFrame:
    source = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if source.empty:
        return source
    source = source.copy()
    if "inningsPitched" not in source:
        source["inningsPitched"] = pd.Series(pd.NA, index=source.index, dtype=object)
    source["_outs"] = source["inningsPitched"].map(innings_to_outs)
    source["_innings_valid"] = source["_outs"].notna()

    group_keys = ["player_id", "player_name"]
    sum_cols = ["appearances", "gamesStarted", "wins", "losses", "saves", "completeGames", "shutout", "hitsAllowed", "runs", "earnedRuns", "baseOnBalls", "intentionalWalksAllowed", "hitByPitch", "strikeOuts", "homeRuns", "numberOfPitches", "balls", "strikes", "wildPitch"]
    grouped = _complete_group_sums(source, group_keys, sum_cols)
    grouped = _merge_season_counts(grouped, source, group_keys)

    audit_rows = []
    for keys, rows in source.groupby(group_keys, sort=False, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        invalid_count = int((~rows["_innings_valid"]).sum())
        available = invalid_count == 0
        total_outs = int(rows["_outs"].sum()) if available else None
        earned_runs_invalid = int(
            _finite_numeric_series(
                rows["earnedRuns"]
                if "earnedRuns" in rows
                else pd.Series(pd.NA, index=rows.index)
            ).isna().sum()
        )
        hits_allowed_invalid = int(
            _finite_numeric_series(
                rows["hitsAllowed"]
                if "hitsAllowed" in rows
                else pd.Series(pd.NA, index=rows.index)
            ).isna().sum()
        )
        walks_invalid = int(
            _finite_numeric_series(
                rows["baseOnBalls"]
                if "baseOnBalls" in rows
                else pd.Series(pd.NA, index=rows.index)
            ).isna().sum()
        )
        audit_rows.append(
            {
                **dict(zip(group_keys, keys)),
                "_total_outs": total_outs,
                "innings_available": available,
                "innings_invalid_count": invalid_count,
                "innings_source_values": _json_source_values(rows, "inningsPitched"),
                "era_inputs_available": available and earned_runs_invalid == 0,
                "era_input_invalid_count": invalid_count + earned_runs_invalid,
                "whip_inputs_available": available
                and hits_allowed_invalid == 0
                and walks_invalid == 0,
                "whip_input_invalid_count": invalid_count
                + hits_allowed_invalid
                + walks_invalid,
                "earned_runs_source_values": _json_source_values(rows, "earnedRuns"),
                "hits_allowed_source_values": _json_source_values(rows, "hitsAllowed"),
                "walks_source_values": _json_source_values(rows, "baseOnBalls"),
                "source_era_values": _json_source_values(rows, "earnedRunAverage"),
                "source_whip_values": _json_source_values(
                    rows, "source_whip" if "source_whip" in rows else "whip"
                ),
            }
        )

    grouped = grouped.merge(
        pd.DataFrame(audit_rows), on=group_keys, how="left", validate="one_to_one"
    )
    grouped["inningsPitched"] = grouped["_total_outs"].map(outs_to_innings)
    innings = pd.to_numeric(grouped["_total_outs"], errors="coerce") / 3
    valid_denominator = grouped["innings_available"].fillna(False) & innings.gt(0)

    if "earnedRuns" in grouped:
        earned_runs = pd.to_numeric(grouped["earnedRuns"], errors="coerce")
        grouped["earnedRunAverage"] = (earned_runs * 7 / innings).where(
            valid_denominator
            & grouped["era_inputs_available"].fillna(False)
            & earned_runs.notna(),
            pd.NA,
        )
    else:
        grouped["earnedRunAverage"] = pd.NA

    if "hitsAllowed" in grouped and "baseOnBalls" in grouped:
        hits = pd.to_numeric(grouped["hitsAllowed"], errors="coerce")
        walks = pd.to_numeric(grouped["baseOnBalls"], errors="coerce")
        grouped["whip"] = ((hits + walks) / innings).where(
            valid_denominator
            & grouped["whip_inputs_available"].fillna(False)
            & hits.notna()
            & walks.notna(),
            pd.NA,
        )
    else:
        grouped["whip"] = pd.NA
    return grouped.drop(columns=["_total_outs"])


def career_fielding(frames: list[pd.DataFrame]) -> pd.DataFrame:
    source = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if source.empty:
        return source
    sum_cols = ["gamesPlayed", "putOuts", "assists", "errors", "doublePlays", "totalChances"]
    group_keys = ["player_id", "player_name"]
    grouped = _complete_group_sums(source, group_keys, sum_cols)
    grouped = _merge_season_counts(grouped, source, group_keys)
    putouts = _numeric_column_or_na(grouped, "putOuts")
    assists = _numeric_column_or_na(grouped, "assists")
    chances = _numeric_column_or_na(grouped, "totalChances")
    grouped["fieldingPercent"] = ((putouts + assists) / chances).where(
        putouts.notna() & assists.notna() & chances.gt(0), pd.NA
    )
    return grouped


def _write_excel_atomic(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    fd, temp_name = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(fd)
    try:
        with pd.ExcelWriter(temp_name, engine="openpyxl") as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name[:31], index=False)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


class CoreRefreshValidationError(RuntimeError):
    """Raised before promotion when a core source is missing or ambiguous."""


def _validate_refresh_frame(frame, name, required_columns, unique_columns=()):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise CoreRefreshValidationError(f"{name} returned no usable rows")
    missing = set(required_columns).difference(frame.columns)
    if missing:
        raise CoreRefreshValidationError(
            f"{name} is missing required columns: {', '.join(sorted(missing))}"
        )
    if unique_columns and frame.duplicated(list(unique_columns)).any():
        raise CoreRefreshValidationError(
            f"{name} contains duplicate authoritative keys"
        )


def _validate_core_refresh_frames(
    *,
    rosters,
    batting,
    pitching,
    fielding,
    standings,
    schedule,
    source_errors=(),
):
    if source_errors:
        raise CoreRefreshValidationError("; ".join(source_errors))
    for year in SEASONS:
        _validate_refresh_frame(
            rosters.get(year), f"{year} roster", {"player_id"}, ("player_id",)
        )
        for label, frames in (
            ("batting", batting),
            ("pitching", pitching),
            ("fielding", fielding),
        ):
            _validate_refresh_frame(
                frames.get(year),
                f"{year} {label} stats",
                {"player_id"},
                ("player_id",),
            )
    _validate_refresh_frame(
        standings,
        "official standings",
        {"team_code", "seasonId", "standingsTypeLk"},
        ("team_code", "seasonId", "standingsTypeLk"),
    )
    _validate_refresh_frame(
        schedule,
        "official schedule",
        {
            "game_id",
            "game_date",
            "away_team_code",
            "home_team_code",
            "status",
        },
        ("game_id",),
    )
    parsed_dates = pd.to_datetime(
        schedule["game_date"], errors="coerce", utc=True, format="mixed"
    )
    if parsed_dates.isna().any():
        raise CoreRefreshValidationError(
            "official schedule contains an unparseable game date"
        )
    away = schedule["away_team_code"].astype(str).str.strip()
    home = schedule["home_team_code"].astype(str).str.strip()
    if away.eq("").any() or home.eq("").any() or away.eq(home).any():
        raise CoreRefreshValidationError(
            "official schedule contains an invalid team identity"
        )


# Freshness target for the yellow (usable-but-aging) source-health state
# (5C). Only reachable for optional/enrichment sources: a core-source
# failure fails the whole refresh closed (REFRESH-003) before any manifest
# is written, so it never reaches this state by design.
ENRICHMENT_FRESHNESS_TARGET_SECONDS = 24 * 3600


def _previous_source_health(manifest_path: Path) -> dict:
    """Best-effort read of the prior manifest's ``source_health`` block."""

    if not manifest_path.exists():
        return {}
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = previous.get("source_health") if isinstance(previous, dict) else None
    return entries if isinstance(entries, dict) else {}


def _age_seconds(timestamp, *, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()


def _enrichment_source_health_entry(
    *,
    source_name: str,
    ok: bool,
    now_iso: str,
    now: datetime,
    row_count: int,
    content_hash: str | None,
    status_detail_ok: str,
    error_summary: str | None,
    previous_entry: dict | None,
    freshness_target_seconds: int = ENRICHMENT_FRESHNESS_TARGET_SECONDS,
) -> dict:
    """Build a source-health entry for an optional/enrichment source.

    A successful attempt is green. A failed attempt that still has usable
    last-known-good data (REFRESH-003 keeps that file on disk untouched) is
    yellow while that data is within its freshness target, and red once it
    ages out or none has ever been promoted.
    """

    if ok:
        return {
            "source_name": source_name,
            "source_type": "optional_enrichment",
            "status": "green",
            "last_attempt_at": now_iso,
            "last_success_at": now_iso,
            "row_count": row_count,
            "content_hash_or_etag": content_hash,
            "status_detail": status_detail_ok,
            "error_summary": None,
            "used_fallback": False,
            "parser_version": "2026-07-24",
        }

    previous_entry = previous_entry or {}
    previous_success = previous_entry.get("last_success_at")
    age = _age_seconds(previous_success, now=now)
    if previous_success and age is not None and age <= freshness_target_seconds:
        status = "yellow"
        age_minutes = int(age // 60)
        detail = (
            f"using last-known-good data ({age_minutes}m old); "
            f"{error_summary or 'this refresh did not update it'}"
        )
    else:
        status = "red"
        detail = error_summary or "no usable data has ever been promoted"
    return {
        "source_name": source_name,
        "source_type": "optional_enrichment",
        "status": status,
        "last_attempt_at": now_iso,
        "last_success_at": previous_success,
        "row_count": previous_entry.get("row_count", 0) if status == "yellow" else 0,
        "content_hash_or_etag": (
            previous_entry.get("content_hash_or_etag") if status == "yellow" else None
        ),
        "status_detail": detail,
        "error_summary": error_summary,
        "used_fallback": True,
        "parser_version": previous_entry.get("parser_version", "2026-07-24"),
    }


def _promote_file_set(staged_to_final: dict[Path, Path]) -> None:
    """Promote a file set transactionally and restore every prior file on failure."""

    if not staged_to_final:
        return
    final_parent = next(iter(staged_to_final.values())).parent
    backup_dir = Path(
        tempfile.mkdtemp(prefix=".core-refresh-backup-", dir=final_parent)
    )
    backups = {}
    promoted = []
    try:
        for final_path in staged_to_final.values():
            if final_path.exists():
                backup_path = backup_dir / final_path.name
                os.replace(final_path, backup_path)
                backups[final_path] = backup_path
        for staged_path, final_path in staged_to_final.items():
            os.replace(staged_path, final_path)
            promoted.append(final_path)
    except Exception:
        for final_path in promoted:
            if final_path not in backups and final_path.exists():
                final_path.unlink()
        for final_path, backup_path in backups.items():
            if backup_path.exists():
                os.replace(backup_path, final_path)
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _stage_and_promote_core_snapshot(
    *,
    output: Path,
    roster_path: Path,
    season_path: Path,
    career_path: Path,
    team_context_path: Path,
    manifest_path: Path,
    rosters: dict,
    batting: dict,
    pitching: dict,
    fielding: dict,
    standings: pd.DataFrame,
    schedule: pd.DataFrame,
    manifest: dict,
    progress,
    cancel_token: CancelToken | None,
    additional_workbooks: dict[Path, dict[str, pd.DataFrame]] | None = None,
) -> None:
    """Serialize one complete installed core-and-enrichment transaction."""

    output.mkdir(parents=True, exist_ok=True)
    progress("Waiting for the previous refresh to finish committing, if any...")
    with _CORE_REFRESH_COMMIT_LOCK:
        # A worker can be cancelled while blocked on the lock. It must not
        # create a staging directory or write anything after it finally enters.
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        progress("Staging validated core Excel databases...")
        stage_dir = Path(
            tempfile.mkdtemp(prefix=".core-refresh-stage-", dir=output)
        )
        try:
            staged_roster = stage_dir / roster_path.name
            staged_season = stage_dir / season_path.name
            staged_career = stage_dir / career_path.name
            staged_team_context = stage_dir / team_context_path.name
            staged_manifest = stage_dir / manifest_path.name
            _write_excel_atomic(
                staged_roster,
                {f"roster_{year}": frame for year, frame in rosters.items()},
            )
            _write_excel_atomic(
                staged_season,
                {
                    **{f"batting_{year}": batting[year] for year in SEASONS},
                    **{f"pitching_{year}": pitching[year] for year in SEASONS},
                    **{f"fielding_{year}": fielding[year] for year in SEASONS},
                },
            )
            _write_excel_atomic(
                staged_career,
                {
                    "career_batting": career_batting(list(batting.values())),
                    "career_pitching": career_pitching(list(pitching.values())),
                    "career_fielding": career_fielding(list(fielding.values())),
                },
            )
            _write_excel_atomic(
                staged_team_context,
                {"standings": standings, "schedule_results": schedule},
            )
            _write_json_atomic(staged_manifest, manifest, prefix=".manifest-")
            staged_to_final = {
                staged_roster: roster_path,
                staged_season: season_path,
                staged_career: career_path,
                staged_team_context: team_context_path,
                staged_manifest: manifest_path,
            }
            for final_path, sheets in (additional_workbooks or {}).items():
                staged_path = stage_dir / final_path.name
                _write_excel_atomic(staged_path, sheets)
                staged_to_final[staged_path] = final_path
            _promote_file_set(staged_to_final)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)


def _update_all_data_impl(
    progress=None,
    *,
    include_enrichment: bool = False,
    cancel_token: CancelToken | None = None,
) -> dict[str, Path]:
    """Refresh validated core data, with enrichment opt-in for development only.

    If ``cancel_token`` is cancelled, this raises ``RefreshCancelled`` as soon
    as the next cancellation checkpoint is reached (before each network call,
    and once more before any file is staged/promoted) instead of continuing.
    Once staging/promotion begins, the refresh runs to completion rather than
    cancelling mid-write, so the atomic REFRESH-002 promotion is never left
    partially applied.
    """
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    progress = progress or (lambda _message: None)
    imported_at = datetime.now(timezone.utc).isoformat()
    refresh_source = (
        "experimental_full_sources" if include_enrichment else "official_core_sources"
    )
    log_event(DATA_LOGGER, "refresh_started", source=refresh_source)
    roster_payloads, stats_payloads = {}, {}
    for year, season_id in SEASONS.items():
        progress(f"Downloading {year} AUSL rosters...")
        roster_payloads[year] = _get_json(f"/data/playersApiData_{season_id}.json", **_cancel_kwargs(cancel_token))
        progress(f"Downloading {year} AUSL stats...")
        stats_payloads[year] = _get_json(f"/data/statsApiData_{season_id}.json", **_cancel_kwargs(cancel_token))

    rosters = {year: roster_frame(payload, year) for year, payload in roster_payloads.items()}
    batting, pitching, fielding = {}, {}, {}
    for year, payload in stats_payloads.items():
        batting[year], pitching[year], fielding[year] = stat_frames(payload, year)
        log_source_result(f"roster_{year}", rosters[year], status="parsed")
        log_source_result(f"batting_{year}", batting[year], status="parsed")
        log_source_result(f"pitching_{year}", pitching[year], status="parsed")
        log_source_result(f"fielding_{year}", fielding[year], status="parsed")

    split_batting, split_pitching, split_fielding = [], [], []
    split_refresh_complete = True
    split_errors = []
    if include_enrichment:
        for year, season_id in SEASONS.items():
            for split_key, split_label in SPLIT_TYPES.items():
                progress(f"Downloading {year} AUSL split stats: {split_label}...")
                try:
                    if cancel_token is None:
                        payload, source_url = fetch_split_payload(
                            season_id, split_key
                        )
                    else:
                        payload, source_url = fetch_split_payload(
                            season_id,
                            split_key,
                            cancel_token=cancel_token,
                        )
                except RefreshCancelled:
                    raise
                except Exception as exc:
                    split_refresh_complete = False
                    split_errors.append(
                        f"{year} {split_label}: {type(exc).__name__}: {exc}"
                    )
                    progress(f"Skipping {year} {split_label} split stats: {exc}")
                    log_source_result(
                        f"split_{year}_{split_key}",
                        None,
                        status="failed",
                        error_summary=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                b, p, f = split_stat_frames(
                    payload, year, split_key, split_label, source_url
                )
                split_batting.append(b)
                split_pitching.append(p)
                split_fielding.append(f)
    else:
        progress("Core refresh: optional split and document enrichment is disabled.")

    progress("Downloading AUSL standings and schedule context...")
    core_source_errors = []
    try:
        standings = fetch_standings_frame(**_cancel_kwargs(cancel_token))
    except RefreshCancelled:
        raise
    except Exception as exc:
        progress(f"Skipping standings context: {exc}")
        standings = pd.DataFrame()
        core_source_errors.append(
            f"official standings failed: {type(exc).__name__}: {exc}"
        )
        log_source_result(
            "official_standings",
            standings,
            status="failed",
            error_summary=f"{type(exc).__name__}: {exc}",
        )
    else:
        log_source_result("official_standings", standings, status="parsed")
    try:
        schedule = fetch_schedule_frame(**_cancel_kwargs(cancel_token))
    except RefreshCancelled:
        raise
    except Exception as exc:
        progress(f"Skipping schedule context: {exc}")
        schedule = pd.DataFrame()
        core_source_errors.append(
            f"official schedule failed: {type(exc).__name__}: {exc}"
        )
        log_source_result(
            "official_schedule",
            schedule,
            status="failed",
            error_summary=f"{type(exc).__name__}: {exc}",
        )
    else:
        log_source_result("official_schedule", schedule, status="parsed")

    # Last checkpoint before any file is staged/promoted: a cancellation that
    # arrives after the final network call still lands here before anything
    # is written, so a cancelled refresh cannot promote a partial result.
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()

    _validate_core_refresh_frames(
        rosters=rosters,
        batting=batting,
        pitching=pitching,
        fielding=fielding,
        standings=standings,
        schedule=schedule,
        source_errors=core_source_errors,
    )

    official_game_notes = pd.DataFrame()
    official_game_notes_ready = False
    official_game_notes_error = None
    media_players = pd.DataFrame()
    media_teams = pd.DataFrame()
    media_notes = pd.DataFrame()
    media_raw_chunks = pd.DataFrame()
    media_audit = pd.DataFrame()
    media_guide_ready = False
    media_guide_error = None
    if include_enrichment:
        progress("Importing official AUSL game notes PDFs...")
        try:
            if cancel_token is None:
                official_game_notes = fetch_official_game_notes_frame(
                    schedule, rosters[max(SEASONS)], progress
                )
            else:
                official_game_notes = fetch_official_game_notes_frame(
                    schedule,
                    rosters[max(SEASONS)],
                    progress,
                    cancel_token=cancel_token,
                )
        except RefreshCancelled:
            raise
        except Exception as exc:
            official_game_notes_error = f"{type(exc).__name__}: {exc}"
            progress(f"Skipping official game notes: {exc}")
            log_source_result(
                "official_game_notes",
                official_game_notes,
                status="failed",
                error_summary=f"{type(exc).__name__}: {exc}",
            )
        else:
            official_game_notes_ready = not official_game_notes.empty
            if not official_game_notes_ready:
                official_game_notes_error = "empty response was not promoted"
            log_source_result(
                "official_game_notes",
                official_game_notes,
                status="parsed" if official_game_notes_ready else "invalid",
                used_fallback=not official_game_notes_ready,
                error_summary=(
                    None
                    if official_game_notes_ready
                    else "empty response was not promoted"
                ),
            )

        progress("Importing AUSL media guide enrichment...")
        try:
            if cancel_token is None:
                media_result = fetch_media_guide_frames(
                    rosters[max(SEASONS)], progress
                )
            else:
                media_result = fetch_media_guide_frames(
                    rosters[max(SEASONS)],
                    progress,
                    cancel_token=cancel_token,
                )
            (
                media_players,
                media_teams,
                media_notes,
                media_raw_chunks,
                media_audit,
            ) = media_result
        except RefreshCancelled:
            raise
        except Exception as exc:
            media_guide_error = f"{type(exc).__name__}: {exc}"
            progress(f"Skipping media guide enrichment: {exc}")
            log_source_result(
                "media_guide",
                None,
                status="failed",
                error_summary=f"{type(exc).__name__}: {exc}",
            )
        else:
            media_guide_ready = True
            log_source_result("media_players", media_players, status="parsed")
            log_source_result("media_teams", media_teams, status="parsed")
            log_source_result("media_notes", media_notes, status="parsed")
            log_source_result("media_audit", media_audit, status="parsed")

    def combined(frames):
        frames = [frame for frame in frames if not frame.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    output = export_dir()
    roster_path = output / "ausl_rosters.xlsx"
    season_path = output / "ausl_season_stats.xlsx"
    career_path = output / "ausl_career_stats.xlsx"
    batting_splits_path = output / "ausl_batting_splits.xlsx"
    pitching_splits_path = output / "ausl_pitching_splits.xlsx"
    fielding_splits_path = output / "ausl_fielding_splits.xlsx"
    team_context_path = output / "ausl_team_context.xlsx"
    source_registry_path = output / "ausl_storyline_sources.xlsx"
    media_players_path = output / "ausl_media_guide_players.xlsx"
    media_teams_path = output / "ausl_media_guide_teams.xlsx"
    media_notes_path = output / "ausl_media_guide_notes.xlsx"
    media_audit_path = output / "ausl_media_guide_audit.xlsx"
    clean_media_notes_path = output / "clean_media_guide_notes.xlsx"
    raw_media_chunks_path = output / "ausl_media_guide_raw_chunks.xlsx"
    official_game_notes_path = output / "official_game_notes.xlsx"
    manifest_path = output / "update_manifest.json"
    now_dt = datetime.now(timezone.utc)
    previous_health = _previous_source_health(manifest_path)
    latest_roster = rosters[max(SEASONS)] if rosters else None
    latest_stats_frames = [
        frames[max(SEASONS)] for frames in (batting, pitching, fielding) if frames
    ]
    source_health = {
        "official_rosters": {
            "source_name": "Official AUSL rosters",
            "source_type": "core",
            "status": "green" if rosters else "red",
            "last_attempt_at": imported_at,
            "last_success_at": imported_at if rosters else None,
            "row_count": int(len(rosters[max(SEASONS)])) if rosters else 0,
            "content_hash_or_etag": _frame_fingerprint(latest_roster),
            "status_detail": "validated roster refresh",
            "error_summary": None,
            "used_fallback": False,
            "parser_version": "2026-07-24",
        },
        "official_stats": {
            "source_name": "Official AUSL season/career stats",
            "source_type": "core",
            "status": "green" if batting and pitching and fielding else "red",
            "last_attempt_at": imported_at,
            "last_success_at": imported_at if (batting and pitching and fielding) else None,
            "row_count": sum(len(frames[max(SEASONS)]) for frames in (batting, pitching, fielding) if frames),
            "content_hash_or_etag": (
                _sha256_hex(
                    "".join(sorted(frame.to_csv(index=False) for frame in latest_stats_frames)).encode("utf-8")
                )
                if latest_stats_frames
                else None
            ),
            "status_detail": "validated stat refresh",
            "error_summary": None,
            "used_fallback": False,
            "parser_version": "2026-07-24",
        },
        "official_standings": {
            "source_name": "Official AUSL standings",
            "source_type": "core",
            "status": "green" if not standings.empty else "red",
            "last_attempt_at": imported_at,
            "last_success_at": imported_at if not standings.empty else None,
            "row_count": int(len(standings)) if isinstance(standings, pd.DataFrame) else 0,
            "content_hash_or_etag": _frame_fingerprint(standings),
            "status_detail": "validated standings refresh",
            "error_summary": None if not standings.empty else "official standings failed validation",
            "used_fallback": standings.empty,
            "parser_version": "2026-07-24",
        },
        "official_schedule": {
            "source_name": "Official AUSL schedule",
            "source_type": "core",
            "status": "green" if not schedule.empty else "red",
            "last_attempt_at": imported_at,
            "last_success_at": imported_at if not schedule.empty else None,
            "row_count": int(len(schedule)) if isinstance(schedule, pd.DataFrame) else 0,
            "content_hash_or_etag": _frame_fingerprint(schedule),
            "status_detail": "validated schedule refresh",
            "error_summary": None if not schedule.empty else "official schedule failed validation",
            "used_fallback": schedule.empty,
            "parser_version": "2026-07-24",
        },
    }
    if include_enrichment:
        combined_batting_splits = combined(split_batting)
        combined_pitching_splits = combined(split_pitching)
        combined_fielding_splits = combined(split_fielding)
        split_workbooks_ready = bool(
            split_refresh_complete
            and not combined_batting_splits.empty
            and not combined_pitching_splits.empty
            and not combined_fielding_splits.empty
        )
        source_health["official_game_notes"] = _enrichment_source_health_entry(
            source_name="Official AUSL game notes",
            ok=official_game_notes_ready,
            now_iso=imported_at,
            now=now_dt,
            row_count=int(len(official_game_notes)) if isinstance(official_game_notes, pd.DataFrame) else 0,
            content_hash=_frame_fingerprint(official_game_notes),
            status_detail_ok="validated official note refresh",
            error_summary=official_game_notes_error,
            previous_entry=previous_health.get("official_game_notes"),
        )
        source_health["media_guide"] = _enrichment_source_health_entry(
            source_name="AUSL media guide",
            ok=media_guide_ready,
            now_iso=imported_at,
            now=now_dt,
            row_count=int(len(media_players)) if isinstance(media_players, pd.DataFrame) else 0,
            content_hash=_frame_fingerprint(media_players),
            status_detail_ok="validated media-guide enrichment",
            error_summary=media_guide_error,
            previous_entry=previous_health.get("media_guide"),
        )
        combined_split_frame = combined([*split_batting, *split_pitching, *split_fielding])
        source_health["split_stats"] = _enrichment_source_health_entry(
            source_name="Official AUSL split stats",
            ok=split_workbooks_ready,
            now_iso=imported_at,
            now=now_dt,
            row_count=int(len(combined_split_frame)),
            content_hash=_frame_fingerprint(combined_split_frame),
            status_detail_ok="validated split refresh",
            error_summary=(
                None
                if split_workbooks_ready
                else "; ".join(split_errors)[:800]
                or "split statistics were incomplete and were not promoted"
            ),
            previous_entry=previous_health.get("split_stats"),
        )
        optional_statuses = [
            source_health[key]["status"]
            for key in ("official_game_notes", "media_guide", "split_stats")
        ]
        aggregate_status = (
            "green"
            if set(optional_statuses) == {"green"}
            else "yellow"
            if "red" not in optional_statuses
            else "red"
        )
        source_health["optional_enrichment"] = {
            "source_name": "Optional producer enrichment",
            "source_type": "optional_enrichment",
            "status": aggregate_status,
            "last_attempt_at": imported_at,
            "last_success_at": (
                imported_at if aggregate_status == "green" else None
            ),
            "row_count": sum(
                int(source_health[key].get("row_count", 0))
                for key in ("official_game_notes", "media_guide", "split_stats")
            ),
            "content_hash_or_etag": None,
            "status_detail": (
                "all optional sources refreshed and validated"
                if aggregate_status == "green"
                else "one or more optional sources use fallback or are unavailable"
            ),
            "error_summary": None,
            "used_fallback": aggregate_status != "green",
            "parser_version": "phase7a-enrichment-gates-v1",
        }
    else:
        for source_key in (
            "official_game_notes",
            "media_guide",
            "split_stats",
        ):
            previous_entry = previous_health.get(source_key)
            if isinstance(previous_entry, dict):
                source_health[source_key] = dict(previous_entry)
        source_health["optional_enrichment"] = {
            "source_name": "Optional enrichment",
            "source_type": "optional_enrichment",
            "status": "disabled",
            "last_attempt_at": imported_at,
            "last_success_at": None,
            "row_count": 0,
            "content_hash_or_etag": None,
            "status_detail": (
                "core refresh only; validated local optional enrichment was "
                "not fetched or rewritten"
            ),
            "error_summary": None,
            "used_fallback": True,
            "parser_version": "2026-07-24",
        }
    manifest = {
        "updated_at": imported_at,
        "seasons": SEASONS,
        "current_roster_players": int(len(rosters[max(SEASONS)])),
        "source": BASE_URL,
        "enrichment_enabled": bool(include_enrichment),
        "enrichment_sources": (
            [row["source_name"] for row in build_enrichment_sources()]
            if include_enrichment
            else []
        ),
        "source_health": source_health,
        "normalizations": {
            "season_pitching_whip": {
                "method": "(hitsAllowed + baseOnBalls) * 3 / innings_outs",
                "source_field_retained_as": "source_whip",
                "applied_at": "2026-07-19",
                "failure_policy": "unavailable",
            }
        },
    }
    additional_workbooks: dict[Path, dict[str, pd.DataFrame]] = {}
    if include_enrichment:
        if split_workbooks_ready:
            additional_workbooks.update(
                {
                    batting_splits_path: {
                        "batting_splits": combined_batting_splits
                    },
                    pitching_splits_path: {
                        "pitching_splits": combined_pitching_splits
                    },
                    fielding_splits_path: {
                        "fielding_splits": combined_fielding_splits
                    },
                }
            )
        additional_workbooks[source_registry_path] = {
            "sources": source_registry_frame()
        }
        if media_guide_ready:
            additional_workbooks.update(
                {
                    media_players_path: {
                        "player_bio_enrichment": media_players
                    },
                    media_teams_path: {"team_media_guide": media_teams},
                    media_notes_path: {"media_guide_notes": media_notes},
                    media_audit_path: {"media_guide_audit": media_audit},
                    clean_media_notes_path: {
                        "clean_media_guide_notes": media_notes
                    },
                    raw_media_chunks_path: {
                        "raw_media_guide_chunks": media_raw_chunks
                    },
                }
            )
        if official_game_notes_ready:
            additional_workbooks[official_game_notes_path] = {
                "official_game_notes": official_game_notes
            }
    _stage_and_promote_core_snapshot(
        output=output,
        roster_path=roster_path,
        season_path=season_path,
        career_path=career_path,
        team_context_path=team_context_path,
        manifest_path=manifest_path,
        rosters=rosters,
        batting=batting,
        pitching=pitching,
        fielding=fielding,
        standings=standings,
        schedule=schedule,
        manifest=manifest,
        progress=progress,
        cancel_token=cancel_token,
        additional_workbooks=additional_workbooks,
    )
    progress("AUSL database update complete.")
    log_event(
        DATA_LOGGER,
        "refresh_finished",
        source=refresh_source,
        current_roster_players=len(rosters[max(SEASONS)]),
        status="written",
    )
    outputs = {
        "rosters": roster_path,
        "season": season_path,
        "career": career_path,
        "team_context": team_context_path,
        "manifest": manifest_path,
    }
    if include_enrichment:
        outputs["sources"] = source_registry_path
        if split_workbooks_ready:
            outputs.update(
                {
                    "batting_splits": batting_splits_path,
                    "pitching_splits": pitching_splits_path,
                    "fielding_splits": fielding_splits_path,
                }
            )
        if official_game_notes_ready:
            outputs["official_game_notes"] = official_game_notes_path
        if media_guide_ready:
            outputs.update(
                {
                    "media_players": media_players_path,
                    "media_teams": media_teams_path,
                    "media_notes": media_notes_path,
                    "media_audit": media_audit_path,
                    "clean_media_notes": clean_media_notes_path,
                    "raw_media_chunks": raw_media_chunks_path,
                }
            )
    return outputs


def update_all_data(
    progress=None,
    *,
    include_enrichment: bool = False,
    cancel_token: CancelToken | None = None,
) -> dict[str, Path]:
    """Serialize refresh jobs and persist outcomes separately from the LKG."""

    progress = progress or (lambda _message: None)
    started_at = datetime.now(timezone.utc).isoformat()
    affected_source = (
        "optional_enrichment_sources"
        if include_enrichment
        else "official_core_sources"
    )

    def attempt(state: str, *, error_summary: str | None = None) -> dict:
        return {
            "schema_version": 1,
            "state": state,
            "started_at": started_at,
            "completed_at": (
                None
                if state == "in_progress"
                else datetime.now(timezone.utc).isoformat()
            ),
            "affected_source": affected_source,
            "error_summary": error_summary,
        }

    progress("Waiting for the previous refresh to finish before starting...")
    with _REFRESH_EXECUTION_LOCK:
        if cancel_token is not None and cancel_token.cancelled:
            _persist_refresh_attempt(attempt("cancelled"))
            raise RefreshCancelled("Refresh cancelled")

        _persist_refresh_attempt(attempt("in_progress"))
        try:
            outputs = _update_all_data_impl(
                progress,
                include_enrichment=include_enrichment,
                cancel_token=cancel_token,
            )
        except RefreshCancelled:
            _persist_refresh_attempt(attempt("cancelled"))
            raise
        except Exception as exc:
            _persist_refresh_attempt(
                attempt("failed", error_summary=_safe_refresh_error_summary(exc))
            )
            raise
        _persist_refresh_attempt(attempt("succeeded"))
        outputs["refresh_attempt"] = _refresh_attempt_path()
        return outputs


def _resolve_enrichment_mode(
    *,
    enrichment_mode: EnrichmentMode | str | None,
    include_enrichment: bool | None,
) -> EnrichmentMode:
    """Resolve typed producer modes; the legacy true flag is review-only."""

    if enrichment_mode is not None and include_enrichment is not None:
        raise ValueError("Choose enrichment_mode or include_enrichment, not both")
    if include_enrichment is not None:
        return (
            EnrichmentMode.DEVELOPER_REVIEW
            if include_enrichment
            else EnrichmentMode.CORE_ONLY
        )
    if enrichment_mode is None:
        return EnrichmentMode.CORE_ONLY
    try:
        return EnrichmentMode(enrichment_mode)
    except ValueError as exc:
        raise ValueError(f"Unknown enrichment mode: {enrichment_mode}") from exc


def load_database(
    *,
    enrichment_mode: EnrichmentMode | str | None = None,
    include_enrichment: bool | None = None,
) -> dict[str, pd.DataFrame]:
    mode = _resolve_enrichment_mode(
        enrichment_mode=enrichment_mode,
        include_enrichment=include_enrichment,
    )
    output = export_dir()
    paths = {
        "roster": output / "ausl_rosters.xlsx",
        "season": output / "ausl_season_stats.xlsx",
        "career": output / "ausl_career_stats.xlsx",
    }
    if not all(path.exists() for path in paths.values()):
        update_all_data(include_enrichment=mode is not EnrichmentMode.CORE_ONLY)
    manifest_path = output / "update_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    else:
        manifest = {}
    result = {"roster": pd.read_excel(paths["roster"], sheet_name=f"roster_{max(SEASONS)}")}
    log_source_result("roster", result["roster"], status="loaded")
    for year in SEASONS:
        for category in ("batting", "pitching", "fielding"):
            frame = pd.read_excel(paths["season"], sheet_name=f"{category}_{year}")
            if category == "pitching":
                frame = normalize_pitching_frame(frame)
            result[f"{category}_{year}"] = frame
            log_source_result(
                f"{category}_{year}", result[f"{category}_{year}"], status="loaded"
            )
    for category in ("batting", "pitching", "fielding"):
        result[f"career_{category}"] = pd.read_excel(paths["career"], sheet_name=f"career_{category}")
        log_source_result(
            f"career_{category}", result[f"career_{category}"], status="loaded"
        )
    core_context = {
        "standings": (output / "ausl_team_context.xlsx", "standings"),
        "schedule_results": (output / "ausl_team_context.xlsx", "schedule_results"),
    }
    enrichment_workbooks = {
        "batting_splits": (output / "ausl_batting_splits.xlsx", "batting_splits"),
        "pitching_splits": (output / "ausl_pitching_splits.xlsx", "pitching_splits"),
        "fielding_splits": (output / "ausl_fielding_splits.xlsx", "fielding_splits"),
        "storyline_sources": (output / "ausl_storyline_sources.xlsx", "sources"),
        "media_players": (output / "ausl_media_guide_players.xlsx", "player_bio_enrichment"),
        "media_teams": (output / "ausl_media_guide_teams.xlsx", "team_media_guide"),
        "media_notes": (output / "ausl_media_guide_notes.xlsx", "media_guide_notes"),
        "media_audit": (output / "ausl_media_guide_audit.xlsx", "media_guide_audit"),
        "clean_media_notes": (output / "clean_media_guide_notes.xlsx", "clean_media_guide_notes"),
        "raw_media_chunks": (output / "ausl_media_guide_raw_chunks.xlsx", "raw_media_guide_chunks"),
        "official_game_notes": (output / "official_game_notes.xlsx", "official_game_notes"),
    }
    for key, (path, sheet) in core_context.items():
        if path.exists():
            try:
                result[key] = pd.read_excel(path, sheet_name=sheet)
            except Exception as exc:
                result[key] = pd.DataFrame()
                log_source_result(
                    key,
                    result[key],
                    status="failed",
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
            else:
                log_source_result(key, result[key], status="loaded")
        else:
            result[key] = pd.DataFrame()
            log_source_result(key, result[key], status="unavailable")
    raw_enrichment = {}
    for key, (path, sheet) in enrichment_workbooks.items():
        if mode is EnrichmentMode.CORE_ONLY:
            result[key] = pd.DataFrame()
            log_source_result(key, result[key], status="disabled")
            continue
        if path.exists():
            try:
                frame = pd.read_excel(path, sheet_name=sheet)
                if key == "pitching_splits":
                    frame = normalize_pitching_frame(frame)
                raw_enrichment[key] = frame
                result[key] = frame
            except Exception as exc:
                result[key] = pd.DataFrame()
                log_source_result(
                    key,
                    result[key],
                    status="failed",
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
            else:
                log_source_result(key, result[key], status="loaded")
        else:
            result[key] = pd.DataFrame()
            log_source_result(key, result[key], status="unavailable")
    if mode is EnrichmentMode.PRODUCER_APPROVED:
        filtered = approved_enrichment_frames(
            raw_enrichment,
            roster=result["roster"],
            manifest=manifest,
        )
        for key in (*PRODUCER_ENRICHMENT_KEYS, *DEVELOPER_ONLY_KEYS):
            result[key] = filtered.get(key, pd.DataFrame())
            log_source_result(
                key,
                result[key],
                status=(
                    "loaded_approved"
                    if isinstance(result[key], pd.DataFrame)
                    and not result[key].empty
                    else "unavailable"
                ),
            )
    result["enrichment_enabled"] = mode is not EnrichmentMode.CORE_ONLY
    result["enrichment_mode"] = mode.value
    result["enrichment_counts"] = {
        key: int(len(result.get(key, pd.DataFrame())))
        for key in PRODUCER_ENRICHMENT_KEYS
    }
    result["manual_notes"] = load_manual_notes()
    log_source_result("manual_notes", result["manual_notes"], status="loaded")
    result["manifest"] = manifest
    result["refresh_attempt"] = load_refresh_attempt(output)
    return result


def fetch_live_game(game_id: str, *, cancel_token: CancelToken | None = None) -> tuple[dict, dict]:
    game_id = str(game_id).strip()
    if not game_id.isdigit():
        raise ValueError("Enter the numeric game ID from an AUSL game-page URL.")
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    game = _get_json(f"/api/game-data/{game_id}/?sport=AUSL", **_cancel_kwargs(cancel_token))
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()
    box = _get_json(f"/api/box-score/ausl/{game_id}", **_cancel_kwargs(cancel_token))
    return game, box.get("data", box)


def main(progress=print) -> int:
    """Run a standalone refresh with the same private-data-safe diagnostics as the GUI."""

    logger, log_path = configure_logging()
    log_event(logger, "standalone_update_started", source="official_ausl_data")
    try:
        outputs = update_all_data(progress)
    except Exception as exc:
        log_event(
            logger,
            "standalone_update_failed",
            source="official_ausl_data",
            error_type=type(exc).__name__,
            error_summary=str(exc),
            log_path=log_path,
        )
        progress(f"AUSL data update failed: {exc}")
        progress(f"Diagnostic log: {log_path}")
        return 1

    log_event(
        logger,
        "standalone_update_completed",
        source="official_ausl_data",
        artifact_count=len(outputs),
        log_path=log_path,
    )
    progress(f"Diagnostic log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
