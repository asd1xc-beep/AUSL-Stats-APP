"""PERF-003 — the refresh target is separate from the canonical snapshot.

`data/exports` is simultaneously a test fixture for twelve-plus modules, the
CI integrity baseline checked by tools/verify_distribution.py, and the payload
the portable build ships. Refresh used to write straight back into it, so
running the app dirtied the tracked snapshot and real changes hid among
modified binaries. Refresh now writes to an untracked `data/runtime/exports`
and the loader prefers that directory only when it holds a complete snapshot.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import ausl_data
from test_refresh_staging import CORE_FILENAMES, configure_valid_core_refresh


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from verify_distribution import scan_distribution  # noqa: E402


def install_fake_app_root(monkeypatch, tmp_path):
    """Point ausl_data at a throwaway installation with a canonical snapshot."""

    root = tmp_path / "app"
    canonical = root / "data" / "exports"
    canonical.mkdir(parents=True)
    monkeypatch.setattr(ausl_data, "app_root", lambda: root)
    # configure_valid_core_refresh redirects export_dir; the split only applies
    # to a default installation, so put the real resolver back.
    monkeypatch.setattr(ausl_data, "export_dir", ausl_data.canonical_export_dir)
    return root, canonical


def seed_canonical_snapshot(canonical):
    """Stand in for the four tracked LFS workbooks plus their manifests."""

    payloads = {}
    for filename in CORE_FILENAMES:
        payload = f"tracked-canonical:{filename}".encode("utf-8")
        (canonical / filename).write_bytes(payload)
        payloads[filename] = payload
    return payloads


def test_refresh_writes_to_the_runtime_directory(monkeypatch, tmp_path):
    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    configure_valid_core_refresh(monkeypatch, tmp_path / "unused")
    monkeypatch.setattr(ausl_data, "export_dir", ausl_data.canonical_export_dir)
    seed_canonical_snapshot(canonical)

    ausl_data.update_all_data()

    runtime = root / "data" / "runtime" / "exports"
    assert runtime.is_dir(), "A refresh must create data/runtime/exports"
    for filename in CORE_FILENAMES:
        assert (runtime / filename).exists(), (
            f"{filename} must be written to the runtime directory"
        )


def test_completed_refresh_leaves_the_tracked_workbooks_byte_identical(
    monkeypatch, tmp_path
):
    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    configure_valid_core_refresh(monkeypatch, tmp_path / "unused")
    monkeypatch.setattr(ausl_data, "export_dir", ausl_data.canonical_export_dir)
    originals = seed_canonical_snapshot(canonical)

    ausl_data.update_all_data()

    for filename, payload in originals.items():
        assert (canonical / filename).read_bytes() == payload, (
            f"Refresh overwrote the canonical tracked snapshot: {filename}"
        )
    assert sorted(path.name for path in canonical.iterdir()) == sorted(originals)


def test_loader_prefers_a_complete_runtime_snapshot(monkeypatch, tmp_path):
    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    seed_canonical_snapshot(canonical)
    runtime = root / "data" / "runtime" / "exports"
    runtime.mkdir(parents=True)
    for filename in CORE_FILENAMES:
        (runtime / filename).write_bytes(f"runtime:{filename}".encode("utf-8"))

    assert ausl_data.active_export_dir() == runtime


def test_loader_falls_back_to_canonical_when_runtime_is_absent(
    monkeypatch, tmp_path
):
    _root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    seed_canonical_snapshot(canonical)

    assert ausl_data.active_export_dir() == canonical


def test_loader_ignores_an_incomplete_runtime_snapshot(monkeypatch, tmp_path):
    """A partial runtime directory must never be mixed with canonical files.

    Combining a fresh runtime roster with a stale canonical workbook would
    produce a snapshot no update_manifest.json describes.
    """

    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    seed_canonical_snapshot(canonical)
    runtime = root / "data" / "runtime" / "exports"
    runtime.mkdir(parents=True)
    (runtime / "ausl_rosters.xlsx").write_bytes(b"runtime roster only")

    assert ausl_data.active_export_dir() == canonical


def test_loader_ignores_an_empty_runtime_workbook(monkeypatch, tmp_path):
    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    seed_canonical_snapshot(canonical)
    runtime = root / "data" / "runtime" / "exports"
    runtime.mkdir(parents=True)
    for filename in CORE_FILENAMES:
        (runtime / filename).write_bytes(f"runtime:{filename}".encode("utf-8"))
    (runtime / "ausl_season_stats.xlsx").write_bytes(b"")

    assert ausl_data.active_export_dir() == canonical


def test_refresh_attempt_is_written_beside_the_runtime_output(
    monkeypatch, tmp_path
):
    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    configure_valid_core_refresh(monkeypatch, tmp_path / "unused")
    monkeypatch.setattr(ausl_data, "export_dir", ausl_data.canonical_export_dir)
    seed_canonical_snapshot(canonical)
    # refresh_attempt.json is tracked too, but is not part of CORE_FILENAMES.
    canonical_attempt = b'{"state": "shipped-with-the-build"}\n'
    (canonical / "refresh_attempt.json").write_bytes(canonical_attempt)

    ausl_data.update_all_data()

    runtime_attempt = root / "data" / "runtime" / "exports" / "refresh_attempt.json"
    assert runtime_attempt.exists()
    assert (canonical / "refresh_attempt.json").read_bytes() == canonical_attempt


def test_an_explicit_export_dir_override_stays_authoritative(
    monkeypatch, tmp_path
):
    """The portable build and the GUI smokes redirect export_dir deliberately.

    A configured directory is authoritative for both read and write; the
    runtime split only applies to a default installation.
    """

    install_fake_app_root(monkeypatch, tmp_path)
    override = tmp_path / "portable" / "exports"
    override.mkdir(parents=True)
    monkeypatch.setattr(ausl_data, "export_dir", lambda: override)

    assert ausl_data.active_export_dir() == override
    assert ausl_data.refresh_output_dir() == override


def test_gitignore_matches_the_runtime_directory():
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in ignored if line.strip()}

    assert "data/runtime/" in entries, (
        "data/runtime/ must be ignored alongside data/exports/game_packets/ "
        "and data/manual/"
    )


def test_runtime_directory_is_not_tracked_by_git():
    tracked = PROJECT_ROOT / "data" / "runtime"
    if not tracked.exists():
        pytest.skip("no local runtime directory to check")
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "--", "data/runtime"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == "", (
        f"data/runtime must never be tracked; git lists: {result.stdout!r}"
    )


def test_verify_distribution_still_validates_the_canonical_snapshot():
    """CI and the portable build must keep resolving data/exports."""

    assert scan_distribution(PROJECT_ROOT / "data" / "exports") == []


def _promotable_runtime(root):
    """A runtime snapshot the promotion tool should accept."""

    runtime = root / "data" / "runtime" / "exports"
    runtime.mkdir(parents=True)
    for name in ("ausl_rosters", "ausl_season_stats", "ausl_career_stats",
                 "ausl_team_context"):
        (runtime / f"{name}.xlsx").write_bytes(b"PK\x03\x04" + name.encode())
    (runtime / "update_manifest.json").write_text(
        '{"updated_at": "2026-08-12T20:58:08.669246+00:00"}\n', encoding="utf-8"
    )
    (runtime / "refresh_attempt.json").write_text(
        '{"state": "succeeded"}\n', encoding="utf-8"
    )
    return runtime


def test_promotion_is_a_dry_run_without_confirm(monkeypatch, tmp_path):
    import promote_runtime_snapshot

    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    originals = seed_canonical_snapshot(canonical)
    _promotable_runtime(root)

    assert promote_runtime_snapshot.promote(confirm=False) == 0

    for filename, payload in originals.items():
        assert (canonical / filename).read_bytes() == payload, (
            "A dry run must not write into the canonical snapshot"
        )


def test_promotion_refuses_an_incomplete_runtime_snapshot(monkeypatch, tmp_path):
    import promote_runtime_snapshot

    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    originals = seed_canonical_snapshot(canonical)
    runtime = _promotable_runtime(root)
    (runtime / "ausl_career_stats.xlsx").unlink()

    assert promote_runtime_snapshot.promote(confirm=True) == 1

    for filename, payload in originals.items():
        assert (canonical / filename).read_bytes() == payload


def test_promotion_refuses_git_lfs_pointer_text(monkeypatch, tmp_path):
    """An LFS pointer would ship an application with no data in it."""

    import promote_runtime_snapshot

    root, canonical = install_fake_app_root(monkeypatch, tmp_path)
    originals = seed_canonical_snapshot(canonical)
    runtime = _promotable_runtime(root)
    (runtime / "ausl_rosters.xlsx").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n"
    )

    assert promote_runtime_snapshot.promote(confirm=True) == 1

    for filename, payload in originals.items():
        assert (canonical / filename).read_bytes() == payload


def test_canonical_export_dir_is_the_tracked_snapshot_path():
    assert ausl_data.canonical_export_dir() == PROJECT_ROOT / "data" / "exports"
    assert (
        ausl_data.runtime_export_dir()
        == PROJECT_ROOT / "data" / "runtime" / "exports"
    )
