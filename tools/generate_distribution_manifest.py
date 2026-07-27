"""Generate the checked/package distribution manifest deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


CORE_EXPORTS = (
    "ausl_rosters.xlsx",
    "ausl_season_stats.xlsx",
    "ausl_career_stats.xlsx",
    "ausl_team_context.xlsx",
    "update_manifest.json",
    "refresh_attempt.json",
)


def _write_json_lf(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".distribution-manifest-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    payload,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            stream.flush()
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def generate_distribution_manifest(exports: Path) -> Path:
    update_path = exports / "update_manifest.json"
    update_manifest = json.loads(update_path.read_text(encoding="utf-8"))
    snapshot_updated_at = update_manifest.get("updated_at")
    if not isinstance(snapshot_updated_at, str) or not snapshot_updated_at.strip():
        raise ValueError("update_manifest.json has no usable updated_at timestamp")

    records = []
    for name in CORE_EXPORTS:
        path = exports / name
        payload = path.read_bytes()
        records.append(
            {
                "bytes": len(payload),
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "validation": "validated_phase_1_core",
            }
        )
    manifest = {
        "files": records,
        "purpose": (
            "Validated distributable core snapshot and nonprivate refresh "
            "attempt health; unverified enrichment is intentionally omitted."
        ),
        "schema_version": 1,
        "snapshot_updated_at": snapshot_updated_at,
    }
    destination = exports / "distribution_manifest.json"
    _write_json_lf(destination, manifest)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("exports", type=Path)
    args = parser.parse_args(argv)
    try:
        destination = generate_distribution_manifest(args.exports)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Generated distribution manifest: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
