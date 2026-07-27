"""Generate a deterministic manifest inside a portable source release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.generate_distribution_manifest import _write_json_lf


MANIFEST_NAME = "portable_source_manifest.json"


def generate_portable_source_manifest(
    package_root: Path,
    *,
    snapshot_updated_at: str | None = None,
) -> Path:
    package_root = Path(package_root)
    if snapshot_updated_at is None:
        update_manifest = json.loads(
            (
                package_root / "data" / "exports" / "update_manifest.json"
            ).read_text(encoding="utf-8")
        )
        snapshot_updated_at = update_manifest.get("updated_at")
    if not isinstance(snapshot_updated_at, str) or not snapshot_updated_at.strip():
        raise ValueError("portable source snapshot has no usable updated_at timestamp")

    records = []
    for path in sorted(
        (
            candidate
            for candidate in package_root.rglob("*")
            if candidate.is_file() and candidate.name != MANIFEST_NAME
        ),
        key=lambda candidate: candidate.relative_to(package_root).as_posix(),
    ):
        payload = path.read_bytes()
        records.append(
            {
                "bytes": len(payload),
                "path": path.relative_to(package_root).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "files": records,
        "package_type": "portable_source_release",
        "schema_version": 1,
        "snapshot_updated_at": snapshot_updated_at,
    }
    destination = package_root / MANIFEST_NAME
    _write_json_lf(destination, manifest)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    args = parser.parse_args(argv)
    try:
        destination = generate_portable_source_manifest(args.package_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Generated portable source manifest: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
