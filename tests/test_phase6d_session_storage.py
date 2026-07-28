from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import ausl_session
from ausl_session import (
    SessionLifecycle,
    SessionLoadStatus,
    SessionStore,
    session_state_dir,
)
from test_phase6d_session_schema import NOW, populated_snapshot


def test_private_state_directory_uses_injected_user_location(tmp_path):
    expected = tmp_path / "AUSL Broadcast Stats"
    assert (
        session_state_dir(
            environ={"LOCALAPPDATA": str(tmp_path)},
            platform_name="win32",
            home=tmp_path / "ignored",
        )
        == expected
    )
    assert session_state_dir(
        environ={"XDG_STATE_HOME": str(tmp_path / "state")},
        platform_name="linux",
        home=tmp_path / "home",
    ) == tmp_path / "state" / "AUSL Broadcast Stats"


def test_atomic_save_and_load_round_trip_with_private_permissions(tmp_path):
    store = SessionStore(tmp_path)
    snapshot = populated_snapshot()

    result = store.save(snapshot, generation=1)
    loaded = store.load()

    assert result.saved
    assert result.path == store.current_path
    assert loaded.status is SessionLoadStatus.RECOVERED
    assert loaded.snapshot == snapshot
    assert store.current_path.read_bytes().endswith(b"\n")
    if os.name != "nt":
        assert store.current_path.stat().st_mode & 0o077 == 0


def test_cleanly_closed_session_loads_as_resume_not_crash_recovery(tmp_path):
    store = SessionStore(tmp_path)
    clean = replace(populated_snapshot(), lifecycle=SessionLifecycle.CLOSED_CLEANLY)
    store.save(clean, generation=1)

    loaded = store.load()

    assert loaded.status is SessionLoadStatus.RESUME
    assert "closed cleanly" in loaded.message.lower()


def test_active_session_loads_with_crash_recovery_notice(tmp_path):
    store = SessionStore(tmp_path)
    store.save(populated_snapshot(), generation=1)

    loaded = store.load()

    assert loaded.status is SessionLoadStatus.RECOVERED
    assert "did not close cleanly" in loaded.message.lower()


def test_failed_replace_keeps_current_bytes_identical_and_cleans_temp(tmp_path):
    store = SessionStore(tmp_path)
    first = populated_snapshot()
    assert store.save(first, generation=1).saved
    before = store.current_path.read_bytes()
    second = replace(first, updated_at=first.updated_at + timedelta(minutes=1))

    real_replace = ausl_session.os.replace

    def fail_current(source, destination):
        if Path(destination) == store.current_path:
            raise OSError("simulated atomic replacement failure")
        return real_replace(source, destination)

    store._replace = fail_current
    result = store.save(second, generation=2)

    assert not result.saved
    assert "replacement failure" in result.error
    assert store.current_path.read_bytes() == before
    assert not tuple(tmp_path.glob(".producer-session-*.tmp"))


def test_backup_is_previous_valid_snapshot_and_recovers_corrupt_current(tmp_path):
    store = SessionStore(tmp_path)
    first = populated_snapshot()
    second = replace(first, updated_at=first.updated_at + timedelta(minutes=1))
    store.save(first, generation=1)
    store.save(second, generation=2)
    assert store.backup_path.exists()

    corrupt = b'{definitely not valid json\n'
    store.current_path.write_bytes(corrupt)
    loaded = store.load()

    assert loaded.status is SessionLoadStatus.BACKUP_RECOVERED
    assert loaded.snapshot == first
    assert loaded.quarantine_path is not None
    assert loaded.quarantine_path.read_bytes() == corrupt
    assert store.current_path.read_bytes() == corrupt


def test_future_schema_is_quarantined_and_backup_is_used(tmp_path):
    store = SessionStore(tmp_path)
    snapshot = populated_snapshot()
    store.save(snapshot, generation=1)
    store.backup_path.write_bytes(store.current_path.read_bytes())
    store.current_path.write_text(
        '{"schema_version":999,"session_id":"future"}\n',
        encoding="utf-8",
        newline="\n",
    )

    loaded = store.load()

    assert loaded.status is SessionLoadStatus.BACKUP_RECOVERED
    assert loaded.snapshot == snapshot
    assert "newer schema" in loaded.message.lower()


def test_invalid_current_and_backup_start_empty_without_modal_loop(tmp_path):
    store = SessionStore(tmp_path)
    store.current_path.write_bytes(b"bad current")
    store.backup_path.write_bytes(b"bad backup")

    first = store.load()
    second = store.load()

    assert first.status is SessionLoadStatus.UNAVAILABLE
    assert first.snapshot is None
    assert second.status is SessionLoadStatus.UNAVAILABLE
    assert len(tuple(tmp_path.glob("producer_session.corrupt-*.json"))) >= 2


def test_generation_order_prevents_older_save_from_overwriting_newer(tmp_path):
    store = SessionStore(tmp_path)
    first = populated_snapshot()
    newest = replace(first, updated_at=first.updated_at + timedelta(minutes=2))
    stale = replace(first, updated_at=first.updated_at + timedelta(minutes=1))

    assert store.save(newest, generation=10).saved
    result = store.save(stale, generation=9)

    assert not result.saved
    assert result.superseded
    assert store.load().snapshot == newest


def test_cleanup_removes_only_owned_temp_files(tmp_path):
    store = SessionStore(tmp_path)
    owned = tmp_path / ".producer-session-deadbeef.tmp"
    unrelated = tmp_path / "somebody-else.tmp"
    owned.write_text("owned", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")

    assert store.cleanup_owned_temps() == 1
    assert not owned.exists()
    assert unrelated.exists()


def test_start_fresh_archive_is_exclusive_and_preserves_exact_bytes(tmp_path):
    store = SessionStore(tmp_path)
    store.save(populated_snapshot(), generation=1)
    before = store.current_path.read_bytes()

    archive = store.archive_current_for_start_fresh()

    assert archive.read_bytes() == before
    with pytest.raises(FileExistsError):
        store._write_exclusive(archive, before)
