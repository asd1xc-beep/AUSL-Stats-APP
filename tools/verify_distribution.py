"""Fail closed when a distributable contains producer-local or secret data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


_FORBIDDEN_PATHS = {
    ("data", "manual"): "producer manual notes or lineup locks",
    ("data", "exports", "game_packets"): "producer-generated game packets",
}
_FORBIDDEN_SEGMENTS = {
    ".cache": "cache directory",
    ".mypy_cache": "cache directory",
    ".pytest_cache": "cache directory",
    ".ruff_cache": "cache directory",
    "__pycache__": "Python bytecode cache",
    "cache": "cache directory",
    "caches": "cache directory",
    "credentials": "credential directory",
    "log": "application log directory",
    "logs": "application log directory",
    "secrets": "secret-data directory",
}
_FORBIDDEN_NAMES = {
    ".netrc": "cached network credentials",
    "ausl_media_guide_raw_chunks.xlsx": "debug-only raw export",
    "id_ed25519": "private key",
    "id_rsa": "private key",
    "locked_lineups.json": "producer lineup locks",
    "player_notes.csv": "producer manual notes",
    "thumbs.db": "operating-system cache",
}
_UNVERIFIED_ENRICHMENT_NAMES = {
    "ausl_batting_splits.xlsx",
    "ausl_fielding_splits.xlsx",
    "ausl_media_guide_audit.xlsx",
    "ausl_media_guide_notes.xlsx",
    "ausl_media_guide_players.xlsx",
    "ausl_media_guide_teams.xlsx",
    "ausl_pitching_splits.xlsx",
    "ausl_storyline_sources.xlsx",
    "clean_media_guide_notes.xlsx",
    "official_game_notes.xlsx",
}
_CORE_WORKBOOKS = {
    "ausl_career_stats.xlsx",
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_team_context.xlsx",
}
_CORE_EXPORTS = _CORE_WORKBOOKS | {
    "refresh_attempt.json",
    "update_manifest.json",
}
_DISTRIBUTION_MANIFEST = "distribution_manifest.json"
_CORE_VALIDATION_STATE = "validated_phase_1_core"
_ALLOWED_DISTRIBUTION_EXPORT_NAMES = _CORE_EXPORTS | {_DISTRIBUTION_MANIFEST}
_SECRET_DATA_SUFFIXES = {".cfg", ".db", ".ini", ".json", ".pickle", ".sqlite", ".txt", ".yaml", ".yml"}
_SECRET_STEM = re.compile(
    r"^(?:client[-_]?secret|credentials?|oauth[-_]?token|refresh[-_]?token)(?:[-_].*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    target: Path
    entry: str
    reason: str


def _contains_sequence(parts: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(parts[index : index + width] == sequence for index in range(len(parts) - width + 1))


def _policy_reason(entry_name: str) -> str | None:
    normalized = entry_name.replace("\\", "/")
    pure_path = PurePosixPath(normalized)
    parts = tuple(part.casefold() for part in pure_path.parts if part not in ("", ".", "/"))

    if normalized.startswith("/") or ".." in parts:
        return "unsafe archive path"

    for sequence, reason in _FORBIDDEN_PATHS.items():
        if _contains_sequence(parts, sequence):
            return reason

    for part in parts:
        if part in _FORBIDDEN_SEGMENTS:
            return _FORBIDDEN_SEGMENTS[part]

    if not parts:
        return None

    name = parts[-1]
    if name in _FORBIDDEN_NAMES:
        return _FORBIDDEN_NAMES[name]
    if name in _UNVERIFIED_ENRICHMENT_NAMES:
        return "unverified enrichment excluded from Phase 1"
    for index in range(len(parts) - 1):
        if parts[index : index + 2] == ("data", "exports"):
            export_parts = parts[index + 2 :]
            if len(export_parts) != 1 or export_parts[0] not in _ALLOWED_DISTRIBUTION_EXPORT_NAMES:
                return "file is outside the Phase 1 distributable allowlist"
    if name == ".env" or name.startswith(".env."):
        return "environment/credential file"
    if name.endswith((".log", ".pyc", ".pyo")):
        return "log or cache file"

    suffix = PurePosixPath(name).suffix.casefold()
    stem = PurePosixPath(name).stem
    if suffix in _SECRET_DATA_SUFFIXES and _SECRET_STEM.fullmatch(stem):
        return "credential or token data"
    return None


def _directory_entries(root: Path) -> Iterable[str]:
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            yield path.relative_to(root).as_posix()
        elif path.is_dir() and not any(path.iterdir()):
            # Empty sensitive directories are still evidence that a package
            # was staged from producer-local state.
            yield path.relative_to(root).as_posix()


def _zip_entries(archive_path: Path) -> Iterable[str]:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            yield info.filename


def _normalized_entry(entry_name: str) -> str:
    return PurePosixPath(entry_name.replace("\\", "/")).as_posix()


def _manifest_violations(
    target: Path,
    entries: Iterable[str],
    read_entry: Callable[[str], bytes],
) -> list[Violation]:
    """Validate each packaged core snapshot against its sibling manifest."""

    entries_by_key: dict[str, str] = {}
    core_directories: set[str] = set()
    for entry in entries:
        normalized = _normalized_entry(entry)
        if normalized.endswith("/"):
            continue
        pure_path = PurePosixPath(normalized)
        entries_by_key[normalized.casefold()] = entry
        if pure_path.name.casefold() in _CORE_WORKBOOKS:
            core_directories.add(pure_path.parent.as_posix())

    violations: list[Violation] = []
    for directory in sorted(core_directories):
        prefix = "" if directory == "." else f"{directory}/"
        manifest_entry = f"{prefix}{_DISTRIBUTION_MANIFEST}"
        manifest_source = entries_by_key.get(manifest_entry.casefold())
        if manifest_source is None:
            violations.append(
                Violation(target, manifest_entry, "distribution manifest missing for packaged core exports")
            )
            continue

        try:
            manifest = json.loads(read_entry(manifest_source).decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            violations.append(
                Violation(target, manifest_entry, f"distribution manifest is unreadable: {exc}")
            )
            continue

        if not isinstance(manifest, dict):
            violations.append(
                Violation(target, manifest_entry, "distribution manifest root must be an object")
            )
            continue
        if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1:
            violations.append(
                Violation(target, manifest_entry, "distribution manifest schema_version must be 1")
            )

        update_entry = f"{prefix}update_manifest.json"
        update_source = entries_by_key.get(update_entry.casefold())
        expected_snapshot: str | None = None
        if update_source is None:
            violations.append(Violation(target, update_entry, "required Phase 1 core export is missing"))
        else:
            try:
                update_manifest = json.loads(read_entry(update_source).decode("utf-8-sig"))
                updated_at = update_manifest.get("updated_at") if isinstance(update_manifest, dict) else None
                if not isinstance(updated_at, str) or not updated_at.strip():
                    raise ValueError("updated_at must be a non-empty string")
                expected_snapshot = updated_at
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                violations.append(
                    Violation(target, update_entry, f"source update manifest is unreadable: {exc}")
                )
        if expected_snapshot is not None and manifest.get("snapshot_updated_at") != expected_snapshot:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "distribution manifest snapshot_updated_at does not match update_manifest.json",
                )
            )

        files = manifest.get("files")
        if not isinstance(files, list):
            violations.append(
                Violation(target, manifest_entry, "distribution manifest files must be an array")
            )
            continue

        records: dict[str, dict] = {}
        invalid_record = False
        for record in files:
            if not isinstance(record, dict) or not isinstance(record.get("name"), str):
                invalid_record = True
                continue
            name = record["name"]
            if name in records:
                violations.append(
                    Violation(target, manifest_entry, f"distribution manifest has duplicate file entry: {name}")
                )
            records[name] = record
        if invalid_record:
            violations.append(
                Violation(target, manifest_entry, "distribution manifest contains an invalid file entry")
            )

        unexpected_records = sorted(set(records) - _CORE_EXPORTS)
        for name in unexpected_records:
            violations.append(
                Violation(target, manifest_entry, f"distribution manifest lists non-core export: {name}")
            )

        for name in sorted(_CORE_EXPORTS):
            file_entry = f"{prefix}{name}"
            source_entry = entries_by_key.get(file_entry.casefold())
            record = records.get(name)
            if source_entry is None:
                if name != "update_manifest.json":
                    violations.append(Violation(target, file_entry, "required Phase 1 core export is missing"))
                continue
            if record is None:
                violations.append(
                    Violation(target, manifest_entry, f"distribution manifest is missing core file: {name}")
                )
                continue

            try:
                payload = read_entry(source_entry)
            except OSError as exc:
                violations.append(Violation(target, file_entry, f"core export is unreadable: {exc}"))
                continue
            if name in _CORE_WORKBOOKS and (
                payload.startswith(b"version https://git-lfs.github.com/spec/")
                or not payload.startswith(b"PK\x03\x04")
            ):
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        "core workbook is not a real XLSX payload (Git LFS content missing)",
                    )
                )
            actual_hash = hashlib.sha256(payload).hexdigest()
            declared_hash = record.get("sha256")
            if not isinstance(declared_hash, str) or declared_hash.casefold() != actual_hash:
                violations.append(Violation(target, file_entry, "distribution manifest hash mismatch"))
            declared_bytes = record.get("bytes")
            if type(declared_bytes) is not int or declared_bytes != len(payload):
                violations.append(Violation(target, file_entry, "distribution manifest byte count mismatch"))
            if record.get("validation") != _CORE_VALIDATION_STATE:
                violations.append(
                    Violation(target, file_entry, "distribution manifest validation state is not approved")
                )

    return violations


def scan_distribution(target: Path | str) -> list[Violation]:
    """Return every forbidden entry in a package directory or ZIP archive."""

    target_path = Path(target)
    if not target_path.exists():
        raise FileNotFoundError(target_path)
    if target_path.is_dir():
        entries = list(_directory_entries(target_path))

        def read_entry(entry: str) -> bytes:
            normalized = _normalized_entry(entry)
            return target_path.joinpath(*PurePosixPath(normalized).parts).read_bytes()

        manifest_violations = _manifest_violations(target_path, entries, read_entry)
    elif target_path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(target_path) as archive:
            entries = [info.filename for info in archive.infolist()]
            manifest_violations = _manifest_violations(target_path, entries, archive.read)
    else:
        raise ValueError(f"Unsupported distribution target: {target_path}")

    violations = []
    for entry in entries:
        reason = _policy_reason(entry)
        if reason:
            violations.append(Violation(target_path, entry, reason))
    violations.extend(manifest_violations)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that AUSL distributables exclude producer-local data, logs, caches, and credentials."
    )
    parser.add_argument("targets", nargs="+", type=Path, help="Package directories or ZIP archives to inspect")
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    for target in args.targets:
        try:
            violations = scan_distribution(target)
        except (FileNotFoundError, OSError, ValueError, zipfile.BadZipFile) as exc:
            print(f"ERROR: could not verify {target}: {exc}", file=sys.stderr)
            return 2
        all_violations.extend(violations)
        if not violations:
            print(f"Clean distribution verified: {target}")

    if all_violations:
        print("Distribution privacy verification failed:", file=sys.stderr)
        for violation in all_violations:
            print(f"- {violation.target}: {violation.entry} ({violation.reason})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
