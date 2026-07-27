from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pandas as pd
import pytest

import ausl_data


# Captured before any test's autouse network guard replaces ausl_data._get_json
# wholesale, so the retry-integration test below can restore the real
# implementation and exercise it against a patched urlopen.
_REAL_GET_JSON = ausl_data._get_json


# ---------------------------------------------------------------------------
# REFRESH-006: bounded retry/backoff for transient network failures
# ---------------------------------------------------------------------------


def test_fetch_with_retry_recovers_from_transient_failures_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ausl_data.time, "sleep", lambda seconds: sleeps.append(seconds))

    attempts = []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise URLError("fixture transient outage")
        return "ok"

    result = ausl_data._fetch_with_retry(operation, attempts=3, base_delay=1.0)

    assert result == "ok"
    assert len(attempts) == 3
    # Exponential backoff: 1s then 2s between the three attempts.
    assert sleeps == [1.0, 2.0]


def test_fetch_with_retry_gives_up_after_the_configured_attempts(monkeypatch):
    monkeypatch.setattr(ausl_data.time, "sleep", lambda _seconds: None)
    attempts = []

    def operation():
        attempts.append(1)
        raise URLError("fixture permanent outage")

    with pytest.raises(URLError, match="fixture permanent outage"):
        ausl_data._fetch_with_retry(operation, attempts=3, base_delay=0)

    assert len(attempts) == 3


def test_fetch_with_retry_does_not_retry_a_non_transient_http_error(monkeypatch):
    monkeypatch.setattr(ausl_data.time, "sleep", lambda _seconds: None)
    attempts = []

    def operation():
        attempts.append(1)
        raise HTTPError("https://theausl.com/data/x.json", 404, "not found", None, None)

    with pytest.raises(HTTPError):
        ausl_data._fetch_with_retry(operation, attempts=3, base_delay=0)

    assert len(attempts) == 1


def test_get_json_retries_urlopen_before_succeeding(monkeypatch):
    monkeypatch.setattr(ausl_data.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ausl_data, "_get_json", _REAL_GET_JSON)
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(_request, timeout, context):
        calls.append(1)
        if len(calls) < 2:
            raise URLError("fixture DNS blip")
        return FakeResponse()

    monkeypatch.setattr(ausl_data, "urlopen", fake_urlopen)

    payload = ausl_data._get_json("/data/fixture.json")

    assert payload == {"ok": True}
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# REFRESH-005: cache and incrementally process unchanged PDFs
# ---------------------------------------------------------------------------


def _official_game_notes_schedule():
    return pd.DataFrame(
        [
            {
                "game_id": 9001,
                "game_date": "2026-07-20",
                "away_team_code": "CHI",
                "home_team_code": "CAR",
                "status": "final",
                "game_notes": "https://theausl.com/notes/9001.pdf",
            }
        ]
    )


def _stub_note_parsing(monkeypatch, page_texts_by_call):
    """Stub PdfReader and note-splitting so the test controls parsed content
    without depending on real PDF bytes or the note-classification regexes."""

    parse_calls = []

    class FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakePdfReader:
        def __init__(self, path):
            parse_calls.append(path)
            text = page_texts_by_call[len(parse_calls) - 1]
            self.pages = [FakePage(text)]

    monkeypatch.setattr("pypdf.PdfReader", FakePdfReader)
    monkeypatch.setattr(
        ausl_data,
        "_split_game_note_items",
        lambda page_text, _lookup: [
            {
                "note_text": f"Fixture note: {page_text}",
                "player_name": "",
                "player_id": "",
                "team_code": "",
            }
        ],
    )
    return parse_calls


def test_unchanged_pdf_is_reused_from_cache_without_reparsing(monkeypatch, tmp_path):
    monkeypatch.setattr(ausl_data, "app_root", lambda: tmp_path)
    schedule = _official_game_notes_schedule()
    roster = pd.DataFrame(columns=["player_name", "player_id", "team_code"])

    pdf_bytes = b"%PDF-1.4 fixture" + b"0" * 10_000

    downloads = []

    def fake_download(_url, path):
        downloads.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes)
        return ausl_data._sha256_hex(pdf_bytes)

    monkeypatch.setattr(ausl_data, "_download_file", fake_download)
    parse_calls = _stub_note_parsing(monkeypatch, ["fixture text", "should not be used"])

    first = ausl_data.fetch_official_game_notes_frame(schedule, roster)
    assert len(parse_calls) == 1
    assert len(first) == 1

    # A deliberate full refresh revalidates the same URL, but unchanged bytes
    # reuse the cached rows without a second PdfReader pass.
    second = ausl_data.fetch_official_game_notes_frame(schedule, roster)
    assert len(downloads) == 2
    assert len(parse_calls) == 1
    assert len(second) == 1
    assert second.iloc[0]["note_text"] == first.iloc[0]["note_text"]

    cache_path = tmp_path / "data" / "sources" / "game_notes" / ".notes_parse_cache.json"
    assert cache_path.exists()


def test_changed_pdf_content_invalidates_the_cache_and_is_reparsed(monkeypatch, tmp_path):
    monkeypatch.setattr(ausl_data, "app_root", lambda: tmp_path)
    schedule = _official_game_notes_schedule()
    roster = pd.DataFrame(columns=["player_name", "player_id", "team_code"])

    first_bytes = b"%PDF-1.4 fixture-a" + b"0" * 10_000
    second_bytes = b"%PDF-1.4 fixture-b" + b"1" * 10_000
    payloads = [first_bytes, second_bytes]

    def fake_download(_url, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = payloads.pop(0)
        path.write_bytes(payload)
        return ausl_data._sha256_hex(payload)

    monkeypatch.setattr(ausl_data, "_download_file", fake_download)
    parse_calls = _stub_note_parsing(monkeypatch, ["first version", "revised version"])

    first = ausl_data.fetch_official_game_notes_frame(schedule, roster)
    assert len(parse_calls) == 1

    game_notes_dir = tmp_path / "data" / "sources" / "game_notes"
    pdf_paths = [path for path in game_notes_dir.glob("*.pdf")]
    assert len(pdf_paths) == 1
    original_path = pdf_paths[0]

    second = ausl_data.fetch_official_game_notes_frame(schedule, roster)

    assert len(parse_calls) == 2
    assert second.iloc[0]["note_text"] != first.iloc[0]["note_text"]
    assert original_path.read_bytes() == second_bytes


def test_failed_revised_download_preserves_last_known_good_game_notes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ausl_data, "app_root", lambda: tmp_path)
    schedule = _official_game_notes_schedule()
    roster = pd.DataFrame(columns=["player_name", "player_id", "team_code"])
    first_bytes = b"%PDF-1.4 fixture-a" + b"0" * 10_000
    calls = []

    def fake_download(_url, path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("fixture revised download failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(first_bytes)
        return ausl_data._sha256_hex(first_bytes)

    monkeypatch.setattr(ausl_data, "_download_file", fake_download)
    parse_calls = _stub_note_parsing(monkeypatch, ["last-known-good text"])

    first = ausl_data.fetch_official_game_notes_frame(schedule, roster)
    pdf_path = next((tmp_path / "data" / "sources" / "game_notes").glob("*.pdf"))
    cache_path = ausl_data._game_notes_cache_path()
    original_pdf = pdf_path.read_bytes()
    original_cache = cache_path.read_bytes()

    second = ausl_data.fetch_official_game_notes_frame(schedule, roster)

    assert len(calls) == 2
    assert len(parse_calls) == 1
    assert second.iloc[0]["note_text"] == first.iloc[0]["note_text"]
    assert pdf_path.read_bytes() == original_pdf
    assert cache_path.read_bytes() == original_cache
    assert not list(pdf_path.parent.glob(".game-notes-download-*"))


def test_invalid_revised_pdf_cannot_replace_valid_cached_game_notes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ausl_data, "app_root", lambda: tmp_path)
    schedule = _official_game_notes_schedule()
    roster = pd.DataFrame(columns=["player_name", "player_id", "team_code"])
    first_bytes = b"%PDF-1.4 valid" + b"0" * 10_000
    revised_bytes = b"not a valid PDF" + b"1" * 10_000
    payloads = [first_bytes, revised_bytes]

    def fake_download(_url, path):
        payload = payloads.pop(0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return ausl_data._sha256_hex(payload)

    parse_calls = []

    class FakePage:
        def extract_text(self):
            return "valid parsed text"

    class FakePdfReader:
        def __init__(self, path):
            parse_calls.append(path)
            if Path(path).read_bytes() == revised_bytes:
                raise ValueError("fixture invalid revised PDF")
            self.pages = [FakePage()]

    monkeypatch.setattr(ausl_data, "_download_file", fake_download)
    monkeypatch.setattr("pypdf.PdfReader", FakePdfReader)
    monkeypatch.setattr(
        ausl_data,
        "_split_game_note_items",
        lambda _text, _lookup: [
            {
                "note_text": "Fixture note from valid PDF.",
                "player_name": "",
                "player_id": "",
                "team_code": "",
            }
        ],
    )

    first = ausl_data.fetch_official_game_notes_frame(schedule, roster)
    pdf_path = next((tmp_path / "data" / "sources" / "game_notes").glob("*.pdf"))
    cache_path = ausl_data._game_notes_cache_path()
    original_cache = cache_path.read_bytes()

    second = ausl_data.fetch_official_game_notes_frame(schedule, roster)

    assert len(parse_calls) == 2
    assert second.iloc[0]["note_text"] == first.iloc[0]["note_text"]
    assert pdf_path.read_bytes() == first_bytes
    assert cache_path.read_bytes() == original_cache
    assert not list(pdf_path.parent.glob(".game-notes-download-*"))


def test_media_guide_same_url_revalidation_preserves_valid_cached_pdf_on_bad_revision(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ausl_data, "app_root", lambda: tmp_path)
    media_context = ausl_data.media_guide_source_context()
    pdf_path = (
        tmp_path / "data" / "sources" / str(media_context["pdf_filename"])
    )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    original = b"%PDF-1.4 cached media guide" + b"0" * 100_000
    pdf_path.write_bytes(original)
    downloads = []

    def fake_download(_url, destination):
        downloads.append(destination)
        destination.write_bytes(b"invalid revised media guide")
        return ausl_data._sha256_hex(destination.read_bytes())

    class InvalidReader:
        def __init__(self, _path):
            raise ValueError("fixture invalid media-guide revision")

    monkeypatch.setattr(ausl_data, "_download_file", fake_download)
    monkeypatch.setattr("pypdf.PdfReader", InvalidReader)

    with pytest.raises(ValueError, match="invalid media-guide revision"):
        ausl_data.fetch_media_guide_frames(pd.DataFrame())

    assert len(downloads) == 1
    assert pdf_path.read_bytes() == original
    assert not list(pdf_path.parent.glob(".media-guide-download-*"))


# ---------------------------------------------------------------------------
# 5C: reachable yellow (usable-but-aging) source-health state
# ---------------------------------------------------------------------------


def test_enrichment_health_entry_is_green_on_success():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    entry = ausl_data._enrichment_source_health_entry(
        source_name="Official AUSL game notes",
        ok=True,
        now_iso=now.isoformat(),
        now=now,
        row_count=42,
        content_hash="deadbeef",
        status_detail_ok="validated official note refresh",
        error_summary=None,
        previous_entry=None,
    )
    assert entry["status"] == "green"
    assert entry["used_fallback"] is False
    assert entry["row_count"] == 42


def test_enrichment_health_entry_is_yellow_within_freshness_target():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    previous_success = (now - timedelta(hours=2)).isoformat()
    entry = ausl_data._enrichment_source_health_entry(
        source_name="Official AUSL game notes",
        ok=False,
        now_iso=now.isoformat(),
        now=now,
        row_count=0,
        content_hash=None,
        status_detail_ok="validated official note refresh",
        error_summary="fixture outage",
        previous_entry={
            "last_success_at": previous_success,
            "row_count": 42,
            "content_hash_or_etag": "deadbeef",
            "parser_version": "2026-07-24",
        },
        freshness_target_seconds=ausl_data.ENRICHMENT_FRESHNESS_TARGET_SECONDS,
    )
    assert entry["status"] == "yellow"
    assert entry["used_fallback"] is True
    assert entry["last_success_at"] == previous_success
    assert entry["row_count"] == 42
    assert entry["content_hash_or_etag"] == "deadbeef"
    assert "fixture outage" in entry["status_detail"]


def test_enrichment_health_entry_is_red_once_last_known_good_ages_out():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    previous_success = (now - timedelta(hours=48)).isoformat()
    entry = ausl_data._enrichment_source_health_entry(
        source_name="Official AUSL game notes",
        ok=False,
        now_iso=now.isoformat(),
        now=now,
        row_count=0,
        content_hash=None,
        status_detail_ok="validated official note refresh",
        error_summary="fixture outage",
        previous_entry={"last_success_at": previous_success, "row_count": 42},
        freshness_target_seconds=ausl_data.ENRICHMENT_FRESHNESS_TARGET_SECONDS,
    )
    assert entry["status"] == "red"
    assert entry["row_count"] == 0
    assert entry["content_hash_or_etag"] is None


def test_enrichment_health_entry_is_red_when_nothing_ever_succeeded():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    entry = ausl_data._enrichment_source_health_entry(
        source_name="Official AUSL game notes",
        ok=False,
        now_iso=now.isoformat(),
        now=now,
        row_count=0,
        content_hash=None,
        status_detail_ok="validated official note refresh",
        error_summary="fixture outage",
        previous_entry=None,
    )
    assert entry["status"] == "red"
    assert entry["last_success_at"] is None


def _configure_valid_core_refresh_with_enrichment(monkeypatch, output, *, game_notes_frame):
    monkeypatch.setattr(ausl_data, "export_dir", lambda: output)
    monkeypatch.setattr(ausl_data, "_get_json", lambda _path: {})
    monkeypatch.setattr(
        ausl_data,
        "roster_frame",
        lambda _payload, year: pd.DataFrame(
            [{"player_id": year, "player_name": f"Player {year}", "team_code": "CHI"}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "stat_frames",
        lambda _payload, year: tuple(
            pd.DataFrame([{"player_id": year}]) for _ in range(3)
        ),
    )
    monkeypatch.setattr(ausl_data, "career_batting", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(ausl_data, "career_pitching", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(ausl_data, "career_fielding", lambda _frames: pd.DataFrame([{"player_id": 1}]))
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda: pd.DataFrame(
            [{"team_code": "CHI", "seasonId": 369, "standingsTypeLk": "SEASON", "wins": 1, "losses": 0}]
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
    monkeypatch.setattr(ausl_data, "ensure_manual_notes_file", lambda: output / "manual.csv")
    monkeypatch.setattr(ausl_data, "fetch_split_payload", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("splits disabled for this fixture")))
    monkeypatch.setattr(ausl_data, "fetch_media_guide_frames", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("media disabled for this fixture")))
    monkeypatch.setattr(ausl_data, "fetch_official_game_notes_frame", game_notes_frame)

    def fake_write(path, sheets):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "|".join(f"{name}:{len(frame)}" for name, frame in sheets.items())
        path.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", fake_write)


def test_manifest_carries_yellow_status_when_game_notes_fail_after_a_recent_success(
    monkeypatch, tmp_path
):
    succeeding = lambda *_a, **_k: pd.DataFrame(  # noqa: E731
        [{"game_id": 9001, "note_text": "Fixture note.", "player_ids": ""}]
    )
    _configure_valid_core_refresh_with_enrichment(monkeypatch, tmp_path, game_notes_frame=succeeding)
    ausl_data.update_all_data(include_enrichment=True)

    manifest_path = tmp_path / "update_manifest.json"
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert first_manifest["source_health"]["official_game_notes"]["status"] == "green"

    failing = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fixture note outage"))  # noqa: E731
    _configure_valid_core_refresh_with_enrichment(monkeypatch, tmp_path, game_notes_frame=failing)
    ausl_data.update_all_data(include_enrichment=True)

    second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = second_manifest["source_health"]["official_game_notes"]
    assert entry["status"] == "yellow"
    assert entry["used_fallback"] is True
    assert entry["last_success_at"] == first_manifest["source_health"]["official_game_notes"]["last_success_at"]
