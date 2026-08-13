"""Fail closed when a distributable contains producer-local or secret data."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ausl_enrichment import approved_enrichment_frames
from ausl_college_approval import (
    APPROVAL_MANIFEST_NAME as COLLEGE_APPROVAL_MANIFEST_NAME,
    APPROVED_ENVELOPE_NAME as COLLEGE_APPROVED_ENVELOPE_NAME,
    validate_approved_payload,
)
from ausl_college_batch_approval import (
    AGGREGATE_ENVELOPE_NAME,
    AGGREGATE_MANIFEST_NAME,
    validate_aggregate_approval,
)
from ausl_college_connection_approval import (
    APPROVED_CONNECTION_ARTIFACT_NAME,
    CONNECTION_APPROVAL_MANIFEST_NAME,
    validate_connection_approval,
)


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
    "college_review": "developer-review college data",
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
    "pilot_envelope.json": "developer-review college pilot",
    "pilot_manifest.json": "developer-review college pilot manifest",
    "review_staging.json": "developer-review college staging data",
    "developer_review_envelope.json": "developer-review college envelope",
    "batch_manifest.json": "developer-review college batch manifest",
    "phase7e_batch_manifest.json": "developer-review college batch manifest",
    "roster_coverage_manifest.json": "developer-review roster coverage",
    "review_packet.md": "developer-review packet",
    "phase7e_connection_review_packet.md": "developer-review connection packet",
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
_APPROVED_ENRICHMENT_MANIFEST = "approved_enrichment_manifest.json"
_APPROVED_ENRICHMENT_WORKBOOKS = {
    "ausl_batting_splits.xlsx": ("batting_splits", "batting_splits"),
    "ausl_pitching_splits.xlsx": ("pitching_splits", "pitching_splits"),
    "ausl_fielding_splits.xlsx": ("fielding_splits", "fielding_splits"),
    "ausl_media_guide_players.xlsx": (
        "media_players",
        "player_bio_enrichment",
    ),
    "ausl_media_guide_teams.xlsx": ("media_teams", "team_media_guide"),
    "ausl_media_guide_notes.xlsx": ("media_notes", "media_guide_notes"),
    "clean_media_guide_notes.xlsx": (
        "clean_media_notes",
        "clean_media_guide_notes",
    ),
    "official_game_notes.xlsx": (
        "official_game_notes",
        "official_game_notes",
    ),
}
_APPROVED_DISTRIBUTION_EXPORT_NAMES = (
    _ALLOWED_DISTRIBUTION_EXPORT_NAMES
    | set(_APPROVED_ENRICHMENT_WORKBOOKS)
    | {
        _APPROVED_ENRICHMENT_MANIFEST,
        COLLEGE_APPROVED_ENVELOPE_NAME,
        COLLEGE_APPROVAL_MANIFEST_NAME,
        AGGREGATE_MANIFEST_NAME,
        APPROVED_CONNECTION_ARTIFACT_NAME,
        CONNECTION_APPROVAL_MANIFEST_NAME,
    }
)
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


def _policy_reason(entry_name: str, *, profile: str = "core") -> str | None:
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
    if name == "producer_session.json" or name.startswith("producer_session."):
        return "private producer session"
    if name in _FORBIDDEN_NAMES:
        return _FORBIDDEN_NAMES[name]
    approved_name = (
        profile == "approved-enrichment"
        and name in _APPROVED_ENRICHMENT_WORKBOOKS
    )
    if name in _UNVERIFIED_ENRICHMENT_NAMES and not approved_name:
        return "unverified enrichment excluded from Phase 1"
    for index in range(len(parts) - 1):
        if parts[index : index + 2] == ("data", "exports"):
            export_parts = parts[index + 2 :]
            allowed = (
                _APPROVED_DISTRIBUTION_EXPORT_NAMES
                if profile == "approved-enrichment"
                else _ALLOWED_DISTRIBUTION_EXPORT_NAMES
            )
            if len(export_parts) != 1 or export_parts[0] not in allowed:
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


def _approved_manifest_violations(
    target: Path,
    entries: Iterable[str],
    read_entry: Callable[[str], bytes],
) -> list[Violation]:
    """Validate the explicit Phase 7A producer-approved profile."""

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
        manifest_entry = f"{prefix}{_APPROVED_ENRICHMENT_MANIFEST}"
        manifest_source = entries_by_key.get(manifest_entry.casefold())
        if manifest_source is None:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment manifest is missing",
                )
            )
            continue
        try:
            manifest_bytes = read_entry(manifest_source)
            manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    f"approved-enrichment manifest is unreadable: {exc}",
                )
            )
            continue
        if b"\r\n" in manifest_bytes or not manifest_bytes.endswith(b"\n"):
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment manifest must use deterministic UTF-8/LF output",
                )
            )
        if not isinstance(manifest, dict):
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment manifest root must be an object",
                )
            )
            continue
        if manifest.get("profile") != "approved-enrichment":
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment profile identity is invalid",
                )
            )
        if manifest.get("approval_schema_version") != 1:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment approval schema is unsupported",
                )
            )
        update_entry = f"{prefix}update_manifest.json"
        update_source = entries_by_key.get(update_entry.casefold())
        roster_entry = f"{prefix}ausl_rosters.xlsx"
        roster_source = entries_by_key.get(roster_entry.casefold())
        if update_source is None or roster_source is None:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment verification requires core roster and update manifest",
                )
            )
            continue
        try:
            update_manifest = json.loads(
                read_entry(update_source).decode("utf-8-sig")
            )
            with pd.ExcelFile(
                io.BytesIO(read_entry(roster_source))
            ) as roster_book:
                roster_sheets = sorted(
                    (
                        name
                        for name in roster_book.sheet_names
                        if name.startswith("roster_")
                        and name.removeprefix("roster_").isdigit()
                    ),
                    key=lambda name: int(name.removeprefix("roster_")),
                )
                if not roster_sheets:
                    raise ValueError("no season roster sheet")
                roster = pd.read_excel(
                    roster_book, sheet_name=roster_sheets[-1]
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    f"approved-enrichment core identity data is unreadable: {exc}",
                )
            )
            continue
        snapshot = (
            update_manifest.get("updated_at")
            if isinstance(update_manifest, dict)
            else None
        )
        if (
            not isinstance(snapshot, str)
            or manifest.get("snapshot_updated_at") != snapshot
            or manifest.get("validation_timestamp") != snapshot
        ):
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment snapshot or validation timestamp is invalid",
                )
            )

        records_payload = manifest.get("files")
        records = {}
        if isinstance(records_payload, list):
            for record in records_payload:
                if (
                    isinstance(record, dict)
                    and isinstance(record.get("name"), str)
                ):
                    records[record["name"]] = record
        else:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment files must be an array",
                )
            )
        packaged_frames: dict[str, pd.DataFrame] = {}
        for filename, (key, sheet) in _APPROVED_ENRICHMENT_WORKBOOKS.items():
            file_entry = f"{prefix}{filename}"
            source_entry = entries_by_key.get(file_entry.casefold())
            record = records.get(filename)
            if source_entry is None:
                if record is not None:
                    violations.append(
                        Violation(
                            target,
                            manifest_entry,
                            f"approved manifest lists missing file: {filename}",
                        )
                    )
                continue
            if record is None:
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        "approved workbook is absent from approval manifest",
                    )
                )
                continue
            try:
                payload = read_entry(source_entry)
                frame = pd.read_excel(io.BytesIO(payload), sheet_name=sheet)
            except (OSError, ValueError) as exc:
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        f"approved workbook is unreadable: {exc}",
                    )
                )
                continue
            actual_hash = hashlib.sha256(payload).hexdigest()
            if record.get("sha256") != actual_hash:
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        "approved-enrichment manifest hash mismatch",
                    )
                )
            if record.get("bytes") != len(payload):
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        "approved-enrichment manifest byte count mismatch",
                    )
                )
            if (
                record.get("row_count") != len(frame)
                or record.get("validation")
                != "producer_approved_phase_7a"
            ):
                violations.append(
                    Violation(
                        target,
                        file_entry,
                        "approved-enrichment manifest row validation is invalid",
                    )
                )
            packaged_frames[key] = frame

        aggregate_manifest_entry = entries_by_key.get(
            f"{prefix}{AGGREGATE_MANIFEST_NAME}".casefold()
        )
        use_aggregate = aggregate_manifest_entry is not None
        college_names = (
            AGGREGATE_ENVELOPE_NAME,
            AGGREGATE_MANIFEST_NAME if use_aggregate else COLLEGE_APPROVAL_MANIFEST_NAME,
        )
        college_sources = {
            name: entries_by_key.get(f"{prefix}{name}".casefold())
            for name in college_names
        }
        college_available = all(college_sources.values())
        if any(college_sources.values()) and not college_available:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved college envelope and approval manifest must be packaged together",
                )
            )
        college_artifact = None
        if college_available:
            college_payloads: dict[str, bytes] = {}
            try:
                college_payloads = {
                    name: read_entry(source_entry)
                    for name, source_entry in college_sources.items()
                    if source_entry is not None
                }
                college_artifact = (
                    validate_aggregate_approval(
                        college_payloads[AGGREGATE_ENVELOPE_NAME],
                        college_payloads[AGGREGATE_MANIFEST_NAME],
                    )
                    if use_aggregate
                    else validate_approved_payload(
                        college_payloads[COLLEGE_APPROVED_ENVELOPE_NAME],
                        college_payloads[COLLEGE_APPROVAL_MANIFEST_NAME],
                    )
                )
                if use_aggregate:
                    roster_ids = []
                    for value in roster["player_id"]:
                        if pd.isna(value):
                            raise ValueError("packaged roster contains a missing player ID")
                        if isinstance(value, float) and value.is_integer():
                            value = int(value)
                        roster_ids.append(str(value).strip())
                    if (
                        len(roster_ids) != len(set(roster_ids))
                        or set(college_artifact.manifest.player_ids) != set(roster_ids)
                    ):
                        raise ValueError(
                            "Phase 7E college player IDs do not exactly match packaged roster"
                        )
            except (OSError, ValueError) as exc:
                violations.append(
                    Violation(
                        target,
                        f"{prefix}{COLLEGE_APPROVED_ENVELOPE_NAME}",
                        f"college approval/hash validation failed: {exc}",
                    )
                )
            for name in college_names:
                record = records.get(name)
                payload = college_payloads.get(name, b"")
                source_entry = college_sources[name]
                if record is None:
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "approved college file is absent from approval manifest",
                        )
                    )
                    continue
                if record.get("sha256") != hashlib.sha256(payload).hexdigest():
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "college approved-enrichment manifest hash mismatch",
                        )
                    )
                if record.get("bytes") != len(payload):
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "college approved-enrichment manifest byte count mismatch",
                        )
                    )
                expected_count = (
                    len(college_artifact.envelope.resumes)
                    if college_artifact is not None
                    else manifest.get("college_player_count")
                )
                if (
                    record.get("row_count") != expected_count
                    or record.get("validation")
                    != (
                        "producer_approved_phase_7e_college"
                        if use_aggregate
                        else "producer_approved_phase_7d_college"
                    )
                ):
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "approved college manifest validation is invalid",
                        )
                    )
        else:
            for name in college_names:
                if name in records:
                    violations.append(
                        Violation(
                            target,
                            manifest_entry,
                            f"approved manifest lists missing college file: {name}",
                        )
                    )
        actual_college_count = (
            len(college_artifact.envelope.resumes)
            if college_artifact is not None
            else 0
        )
        if manifest.get("college_player_count") != actual_college_count:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment college player count is invalid",
                )
            )

        connection_names = (
            APPROVED_CONNECTION_ARTIFACT_NAME,
            CONNECTION_APPROVAL_MANIFEST_NAME,
        )
        connection_sources = {
            name: entries_by_key.get(f"{prefix}{name}".casefold())
            for name in connection_names
        }
        connections_available = all(connection_sources.values())
        if any(connection_sources.values()) and not connections_available:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved college connection artifact and manifest must be packaged together",
                )
            )
        connection_artifact = None
        connection_payloads: dict[str, bytes] = {}
        if connections_available:
            try:
                connection_payloads = {
                    name: read_entry(source_entry)
                    for name, source_entry in connection_sources.items()
                    if source_entry is not None
                }
                if not use_aggregate or college_artifact is None:
                    raise ValueError(
                        "approved connections require validated Phase 7E college data"
                    )
                connection_artifact = validate_connection_approval(
                    connection_payloads[APPROVED_CONNECTION_ARTIFACT_NAME],
                    connection_payloads[CONNECTION_APPROVAL_MANIFEST_NAME],
                )
                player_ids = set(college_artifact.manifest.player_ids)
                source_ids = {
                    source.source_id for source in college_artifact.envelope.sources
                }
                for candidate in connection_artifact.connections.candidates:
                    if not set(candidate.subject_player_ids) <= player_ids:
                        raise ValueError("approved connection has an unknown player ID")
                    if not set(candidate.evidence_source_ids) <= source_ids:
                        raise ValueError("approved connection has an unknown source ID")
            except (OSError, ValueError) as exc:
                violations.append(
                    Violation(
                        target,
                        f"{prefix}{APPROVED_CONNECTION_ARTIFACT_NAME}",
                        f"college connection approval/hash validation failed: {exc}",
                    )
                )
            expected_connection_count = (
                len(connection_artifact.connections.candidates)
                if connection_artifact is not None
                else manifest.get("college_connection_count")
            )
            for name in connection_names:
                record = records.get(name)
                payload = connection_payloads.get(name, b"")
                source_entry = connection_sources[name]
                if record is None:
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "approved college connection file is absent from approval manifest",
                        )
                    )
                    continue
                if (
                    record.get("sha256") != hashlib.sha256(payload).hexdigest()
                    or record.get("bytes") != len(payload)
                    or record.get("row_count") != expected_connection_count
                    or record.get("validation")
                    != "producer_approved_phase_7e_connections"
                ):
                    violations.append(
                        Violation(
                            target,
                            str(source_entry),
                            "approved college connection manifest validation is invalid",
                        )
                    )
        else:
            for name in connection_names:
                if name in records:
                    violations.append(
                        Violation(
                            target,
                            manifest_entry,
                            f"approved manifest lists missing college connection file: {name}",
                        )
                    )
        actual_connection_count = (
            len(connection_artifact.connections.candidates)
            if connection_artifact is not None
            else 0
        )
        if manifest.get("college_connection_count", 0) != actual_connection_count:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment college connection count is invalid",
                )
            )

        unexpected_records = set(records).difference(
            set(_APPROVED_ENRICHMENT_WORKBOOKS)
            | set(college_names)
            | set(connection_names)
        )
        for filename in sorted(unexpected_records):
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    f"approved manifest lists a non-approved file: {filename}",
                )
            )
        try:
            revalidated = approved_enrichment_frames(
                packaged_frames,
                roster=roster,
                manifest=update_manifest,
            )
        except Exception as exc:  # fail closed on any gate implementation error
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    f"approved-enrichment gates could not be evaluated: {type(exc).__name__}",
                )
            )
            continue
        for key, frame in packaged_frames.items():
            filtered = revalidated.get(key, pd.DataFrame())
            if len(filtered) != len(frame) or (
                "producer_approved" not in frame.columns
                or not frame["producer_approved"].astype(bool).all()
            ):
                filename = next(
                    name
                    for name, (candidate, _sheet) in _APPROVED_ENRICHMENT_WORKBOOKS.items()
                    if candidate == key
                )
                violations.append(
                    Violation(
                        target,
                        f"{prefix}{filename}",
                        "one or more rows fail the approved-enrichment approval gate",
                    )
                )
        declared_counts = manifest.get("row_counts")
        actual_counts = {
            key: int(len(frame)) for key, frame in packaged_frames.items()
        }
        if declared_counts != actual_counts:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment row counts do not match packaged workbooks",
                )
            )
        expected_fallback = (
            "core_only"
            if not packaged_frames and not college_available and not connections_available
            else "none"
        )
        if manifest.get("fallback") != expected_fallback:
            violations.append(
                Violation(
                    target,
                    manifest_entry,
                    "approved-enrichment fallback state is invalid",
                )
            )
    return violations


def scan_distribution(
    target: Path | str, *, profile: str = "core"
) -> list[Violation]:
    """Return every forbidden entry in a package directory or ZIP archive."""

    if profile not in {"core", "approved-enrichment"}:
        raise ValueError(f"Unsupported distribution profile: {profile}")
    target_path = Path(target)
    if not target_path.exists():
        raise FileNotFoundError(target_path)
    if target_path.is_dir():
        entries = list(_directory_entries(target_path))

        def read_entry(entry: str) -> bytes:
            normalized = _normalized_entry(entry)
            return target_path.joinpath(*PurePosixPath(normalized).parts).read_bytes()

        manifest_violations = _manifest_violations(target_path, entries, read_entry)
        if profile == "approved-enrichment":
            manifest_violations.extend(
                _approved_manifest_violations(target_path, entries, read_entry)
            )
    elif target_path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(target_path) as archive:
            entries = [info.filename for info in archive.infolist()]
            manifest_violations = _manifest_violations(target_path, entries, archive.read)
            if profile == "approved-enrichment":
                manifest_violations.extend(
                    _approved_manifest_violations(
                        target_path, entries, archive.read
                    )
                )
    else:
        raise ValueError(f"Unsupported distribution target: {target_path}")

    violations = []
    for entry in entries:
        reason = _policy_reason(entry, profile=profile)
        if reason:
            violations.append(Violation(target_path, entry, reason))
    violations.extend(manifest_violations)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that AUSL distributables exclude producer-local data, logs, caches, and credentials."
    )
    parser.add_argument("targets", nargs="+", type=Path, help="Package directories or ZIP archives to inspect")
    parser.add_argument(
        "--profile",
        choices=("core", "approved-enrichment"),
        default="core",
        help="Distribution allowlist and validation profile.",
    )
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    for target in args.targets:
        try:
            violations = scan_distribution(target, profile=args.profile)
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
