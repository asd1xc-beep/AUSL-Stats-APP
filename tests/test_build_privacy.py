from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from tools.verify_distribution import main, scan_distribution
from tools.generate_distribution_manifest import generate_distribution_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_file(root: Path, relative_path: str) -> None:
    path = root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test sentinel", encoding="utf-8")


def _write_manifested_core_package(root: Path) -> Path:
    exports = root / "data" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    payloads = {
        "ausl_rosters.xlsx": b"PK\x03\x04validated roster fixture",
        "ausl_season_stats.xlsx": b"PK\x03\x04validated season fixture",
        "ausl_career_stats.xlsx": b"PK\x03\x04validated career fixture",
        "ausl_team_context.xlsx": b"PK\x03\x04validated team context fixture",
        "update_manifest.json": json.dumps(
            {"updated_at": "2026-07-09T14:56:07.992182+00:00"}
        ).encode("utf-8"),
        "refresh_attempt.json": json.dumps(
            {
                "state": "succeeded",
                "started_at": "2026-07-09T14:56:00+00:00",
                "completed_at": "2026-07-09T14:56:07.992182+00:00",
                "affected_source": "official_core_sources",
                "error_summary": None,
            }
        ).encode("utf-8"),
    }
    for name, payload in payloads.items():
        (exports / name).write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "snapshot_updated_at": "2026-07-09T14:56:07.992182+00:00",
        "files": [
            {
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "validation": "validated_phase_1_core",
            }
            for name, payload in payloads.items()
        ],
    }
    (exports / "distribution_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return exports / "ausl_rosters.xlsx"


def test_clean_package_directory_passes(tmp_path):
    _write_file(tmp_path, "src/ausl_stats_app.py")
    _write_file(tmp_path, "data/exports/update_manifest.json")
    _write_file(tmp_path, "_internal/certifi/cacert.pem")

    assert scan_distribution(tmp_path) == []


def test_manifested_core_snapshot_passes_and_tampering_fails(tmp_path):
    export_path = _write_manifested_core_package(tmp_path)

    assert scan_distribution(tmp_path) == []

    export_path.write_bytes(b"tampered roster fixture")
    violations = scan_distribution(tmp_path)

    assert any("manifest hash" in violation.reason for violation in violations)


def test_checked_in_core_snapshot_passes_distribution_verification():
    exports = PROJECT_ROOT / "data" / "exports"

    assert scan_distribution(exports) == []
    for workbook in (
        "ausl_rosters.xlsx",
        "ausl_season_stats.xlsx",
        "ausl_career_stats.xlsx",
        "ausl_team_context.xlsx",
    ):
        payload = (exports / workbook).read_bytes()
        assert payload.startswith(b"PK\x03\x04"), f"{workbook} is not a real XLSX payload"
        assert not payload.startswith(b"version https://git-lfs.github.com/spec/")


def test_distribution_manifest_generation_is_deterministic_utf8_lf(tmp_path):
    source = PROJECT_ROOT / "data" / "exports"
    exports = tmp_path / "exports"
    exports.mkdir()
    for name in (
        "ausl_rosters.xlsx",
        "ausl_season_stats.xlsx",
        "ausl_career_stats.xlsx",
        "ausl_team_context.xlsx",
        "update_manifest.json",
        "refresh_attempt.json",
    ):
        shutil.copyfile(source / name, exports / name)

    manifest_path = generate_distribution_manifest(exports)
    first = manifest_path.read_bytes()
    generate_distribution_manifest(exports)

    assert manifest_path.read_bytes() == first
    assert b"\r\n" not in first
    assert first.endswith(b"\n")
    assert scan_distribution(exports) == []


@pytest.mark.parametrize(
    ("entry", "expected_reason"),
    [
        ("data/manual/player_notes.csv", "manual notes"),
        ("data/manual/locked_lineups.json", "lineup locks"),
        ("data/exports/game_packets/game_969.txt", "game packets"),
        (
            "data/exports/ausl_media_guide_raw_chunks.xlsx",
            "debug-only raw export",
        ),
        (
            "data/exports/ausl_media_guide_players.xlsx",
            "unverified enrichment",
        ),
        (
            "data/exports/ausl_media_guide_audit.xlsx",
            "unverified enrichment",
        ),
        (
            "data/exports/official_game_notes.xlsx",
            "unverified enrichment",
        ),
        (
            "data/exports/ausl_batting_splits.xlsx",
            "unverified enrichment",
        ),
        (
            "data/exports/private_custom_export.xlsx",
            "Phase 1 distributable allowlist",
        ),
        ("logs/ausl_stats.log", "log"),
        ("cache/live_response.json", "cache"),
        ("__pycache__/ausl_data.pyc", "cache"),
        (".pytest_cache/v/cache/nodeids", "cache"),
        (".env", "credential"),
        ("credentials.json", "credential"),
        ("client_secret-prod.json", "credential"),
        ("oauth_token.json", "token"),
    ],
)
def test_package_directory_rejects_private_or_cached_entries(tmp_path, entry, expected_reason):
    _write_file(tmp_path, entry)

    violations = scan_distribution(tmp_path)

    assert len(violations) == 1
    assert violations[0].entry.replace("\\", "/") == entry
    assert expected_reason in violations[0].reason


def test_zip_normalizes_windows_paths_and_rejects_empty_sensitive_directory(tmp_path):
    archive_path = tmp_path / "package.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(r"data\exports\update_manifest.json", "{}")
        archive.writestr("data\\manual\\", "")

    violations = scan_distribution(archive_path)

    assert len(violations) == 1
    assert violations[0].entry.replace("\\", "/") == "data/manual/"
    assert "manual" in violations[0].reason


def test_clean_zip_and_cli_pass(tmp_path, capsys):
    archive_path = tmp_path / "clean.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.txt", "AUSL")
        archive.writestr("data/exports/update_manifest.json", "{}")

    assert main([str(archive_path)]) == 0
    assert "Clean distribution verified" in capsys.readouterr().out


def test_cli_fails_closed_for_private_data(tmp_path, capsys):
    archive_path = tmp_path / "private.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("data/manual/player_notes.csv", "private sentinel")

    assert main([str(archive_path)]) == 1
    captured = capsys.readouterr()
    assert "privacy verification failed" in captured.err
    assert "private sentinel" not in captured.err


def test_cli_reports_missing_target_as_verification_error(tmp_path, capsys):
    missing = tmp_path / "missing.zip"

    assert main([str(missing)]) == 2
    assert "could not verify" in capsys.readouterr().err


def test_runtime_build_and_test_dependencies_are_exactly_pinned():
    expected_lines = {
        "requirements.txt": {
            "pandas==3.0.3",
            "openpyxl==3.1.5",
            "certifi==2026.6.17",
            "pypdf==6.14.2",
        },
        "requirements-build.txt": {
            "-r requirements.txt",
            "pyinstaller==6.21.0",
            "pyinstaller-hooks-contrib==2026.6",
        },
        "requirements-dev.txt": {
            "-r requirements.txt",
            "pytest==8.4.1",
        },
        "constraints.txt": {
            "pandas==3.0.3",
            "openpyxl==3.1.5",
            "certifi==2026.6.17",
            "pypdf==6.14.2",
            "numpy==2.5.1",
            "python-dateutil==2.9.0.post0",
            "six==1.17.0",
            "tzdata==2026.2",
            "et_xmlfile==2.0.0",
            "pyinstaller==6.21.0",
            "pyinstaller-hooks-contrib==2026.6",
            "altgraph==0.17.5",
            "packaging==26.2",
            "pefile==2024.8.26",
            "pywin32-ctypes==0.2.3",
            "setuptools==83.0.0",
            "pytest==8.4.1",
            "colorama==0.4.6",
            "iniconfig==2.3.0",
            "pluggy==1.6.0",
            "pygments==2.20.0",
        },
    }

    for filename, expected in expected_lines.items():
        actual = {
            line.strip()
            for line in (PROJECT_ROOT / filename).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        assert actual == expected, filename


def test_build_scripts_are_clean_by_default_and_fail_closed():
    script_names = ["Build Shareable AUSL App.ps1", "Build Safer No-EXE AUSL App.ps1"]
    scripts = [(PROJECT_ROOT / name).read_text(encoding="utf-8") for name in script_names]

    for script in scripts:
        lowered = script.casefold()
        assert r"data\manual" not in lowered
        assert "player_notes" not in lowered
        assert "locked_lineups" not in lowered
        assert r'data\exports\*' not in lowered
        assert "verify_distribution.py" in lowered
        assert "write-portablechecksum" in lowered
        assert "ausl_media_guide_raw_chunks.xlsx" not in lowered
        assert "ausl_media_guide_players.xlsx" not in lowered
        assert "official_game_notes.xlsx" not in lowered
        assert "ausl_batting_splits.xlsx" not in lowered
        assert "ausl_team_context.xlsx" in lowered
        assert "generate_distribution_manifest.py" in lowered
        assert "refresh_attempt.json" in lowered
        assert "param([switch]$noninteractive)" in "".join(lowered.split())
        assert "if(-not$noninteractive)" in "".join(lowered.split())

    assert "--upgrade" not in "\n".join(scripts).casefold()
    assert "$lastexitcode" in scripts[0].casefold()
    assert "-c constraints.txt" in scripts[0].casefold()
    assert "$tkinterlib" in scripts[0].casefold()
    assert "$tclroot" in scripts[0].casefold()
    assert "--paths $tkinterlib" in scripts[0].casefold()
    assert r'--add-data "$tclroot\tcl8.6;_tcl_data"' in scripts[0].casefold()
    assert r'--add-data "$tclroot\tk8.6;_tk_data"' in scripts[0].casefold()
    assert r'--add-data "$tkinterlib\tkinter;tkinter"' in scripts[0].casefold()
    assert "--hidden-import tkinter" in scripts[0].casefold()
    assert "--hidden-import _tkinter" in scripts[0].casefold()
    assert r"_internal\tkinter\__pycache__" in scripts[0].casefold()
    assert all('copy-item "constraints.txt"' in script.casefold() for script in scripts)

    setup_script = (PROJECT_ROOT / "Setup AUSL Environment.bat").read_text(encoding="utf-8").casefold()
    assert "-r requirements.txt -c constraints.txt" in setup_script
    assert "--upgrade" not in setup_script
