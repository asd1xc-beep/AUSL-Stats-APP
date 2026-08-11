"""Stage the default core or explicit producer-approved distribution profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ausl_enrichment import approved_enrichment_frames
from ausl_college_approval import (
    APPROVAL_MANIFEST_NAME as COLLEGE_APPROVAL_MANIFEST_NAME,
    APPROVED_ENVELOPE_NAME as COLLEGE_APPROVED_ENVELOPE_NAME,
    validate_approved_payload,
)
from tools.generate_distribution_manifest import (
    CORE_EXPORTS,
    generate_distribution_manifest,
)


APPROVED_MANIFEST_NAME = "approved_enrichment_manifest.json"
APPROVAL_SCHEMA_VERSION = 1
_OPTIONAL_WORKBOOKS = {
    "batting_splits": ("ausl_batting_splits.xlsx", "batting_splits"),
    "pitching_splits": ("ausl_pitching_splits.xlsx", "pitching_splits"),
    "fielding_splits": ("ausl_fielding_splits.xlsx", "fielding_splits"),
    "media_players": (
        "ausl_media_guide_players.xlsx",
        "player_bio_enrichment",
    ),
    "media_teams": ("ausl_media_guide_teams.xlsx", "team_media_guide"),
    "media_notes": ("ausl_media_guide_notes.xlsx", "media_guide_notes"),
    "clean_media_notes": (
        "clean_media_guide_notes.xlsx",
        "clean_media_guide_notes",
    ),
    "official_game_notes": (
        "official_game_notes.xlsx",
        "official_game_notes",
    ),
}
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_CORE_XML_TIMESTAMP = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>).*?(</dcterms:(?:created|modified)>)"
)


def _write_json_lf(path: Path, payload: object) -> None:
    text = json.dumps(
        payload, indent=2, ensure_ascii=False, sort_keys=True
    ) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _canonicalize_xlsx(source: Path, destination: Path) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(source) as reader, zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as writer:
            for name in sorted(reader.namelist()):
                payload = reader.read(name)
                if name == "docProps/core.xml":
                    payload = _CORE_XML_TIMESTAMP.sub(
                        rb"\g<1>2026-01-01T00:00:00Z\g<2>", payload
                    )
                info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                writer.writestr(info, payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_deterministic_excel(
    path: Path, *, sheet_name: str, frame: pd.DataFrame
) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.source-", suffix=".xlsx", dir=path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
        _canonicalize_xlsx(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_optional_frames(source: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for key, (filename, sheet) in _OPTIONAL_WORKBOOKS.items():
        path = source / filename
        if not path.exists():
            frames[key] = pd.DataFrame()
            continue
        try:
            frames[key] = pd.read_excel(path, sheet_name=sheet)
        except Exception:
            # A malformed optional source must never make it into a package.
            frames[key] = pd.DataFrame()
    return frames


def _hash_record(
    path: Path, *, row_count: int, validation: str = "producer_approved_phase_7a"
) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "bytes": len(payload),
        "name": path.name,
        "row_count": int(row_count),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "validation": validation,
    }


def stage_distribution_profile(
    source_exports: Path,
    destination_exports: Path,
    *,
    profile: str = "core",
) -> Path:
    source = Path(source_exports).resolve()
    destination = Path(destination_exports).resolve()
    if profile not in {"core", "approved-enrichment"}:
        raise ValueError(f"Unsupported distribution profile: {profile}")
    if not source.is_dir():
        raise ValueError(f"Source exports do not exist: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError(
            f"Distribution destination must be empty: {destination}"
        )

    for name in CORE_EXPORTS:
        source_path = source / name
        if not source_path.is_file():
            raise ValueError(f"Required core export is missing: {name}")
        shutil.copyfile(source_path, destination / name)
    generate_distribution_manifest(destination)
    if profile == "core":
        return destination

    update_manifest = json.loads(
        (source / "update_manifest.json").read_text(encoding="utf-8")
    )
    with pd.ExcelFile(source / "ausl_rosters.xlsx") as roster_book:
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
            raise ValueError("Roster workbook has no season roster sheet")
        roster = pd.read_excel(roster_book, sheet_name=roster_sheets[-1])
    approved = approved_enrichment_frames(
        _read_optional_frames(source),
        roster=roster,
        manifest=update_manifest,
    )
    file_records = []
    row_counts = {}
    provenance_columns = {}
    for key, (filename, sheet) in _OPTIONAL_WORKBOOKS.items():
        frame = approved.get(key, pd.DataFrame())
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        path = destination / filename
        _write_deterministic_excel(path, sheet_name=sheet, frame=frame)
        count = int(len(frame))
        row_counts[key] = count
        file_records.append(_hash_record(path, row_count=count))
        provenance_columns[key] = sorted(
            column
            for column in frame.columns
            if column.startswith(("source", "approval", "approved", "parser"))
            or column
            in {
                "guide_date",
                "expected_printed_pages",
                "parsed_pdf_pages",
                "normalized_hash",
                "producer_trust_state",
            }
        )

    college_sources = []
    for name in (COLLEGE_APPROVED_ENVELOPE_NAME, COLLEGE_APPROVAL_MANIFEST_NAME):
        direct = source / name
        checked_in = source.parent / "college_approved" / name
        college_sources.append(direct if direct.is_file() else checked_in)
    college_player_count = 0
    if any(path.is_file() for path in college_sources):
        if not all(path.is_file() for path in college_sources):
            raise ValueError(
                "Approved college packaging requires both envelope and approval manifest"
            )
        artifact = validate_approved_payload(
            college_sources[0].read_bytes(), college_sources[1].read_bytes()
        )
        college_player_count = len(artifact.envelope.resumes)
        for source_path in college_sources:
            destination_path = destination / source_path.name
            shutil.copyfile(source_path, destination_path)
            file_records.append(
                _hash_record(
                    destination_path,
                    row_count=college_player_count,
                    validation="producer_approved_phase_7d_college",
                )
            )

    snapshot = update_manifest.get("updated_at")
    manifest = {
        "approval_schema_version": APPROVAL_SCHEMA_VERSION,
        "fallback": "none" if file_records else "core_only",
        "files": sorted(file_records, key=lambda item: item["name"]),
        "profile": "approved-enrichment",
        "college_player_count": college_player_count,
        "provenance_columns": provenance_columns,
        "row_counts": row_counts,
        "schema_version": 1,
        "snapshot_updated_at": snapshot,
        "validation_timestamp": snapshot,
    }
    manifest_path = destination / APPROVED_MANIFEST_NAME
    _write_json_lf(manifest_path, manifest)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_exports", type=Path)
    parser.add_argument("destination_exports", type=Path)
    parser.add_argument(
        "--profile",
        choices=("core", "approved-enrichment"),
        default="core",
    )
    args = parser.parse_args(argv)
    try:
        stage_distribution_profile(
            args.source_exports,
            args.destination_exports,
            profile=args.profile,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Staged {args.profile} distribution: {args.destination_exports}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
