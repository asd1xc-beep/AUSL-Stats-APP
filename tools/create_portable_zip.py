"""Create a deterministic-path ZIP that extracts correctly on Windows and POSIX."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path


_DETERMINISTIC_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def create_portable_zip(
    source: Path,
    destination: Path,
    *,
    compression: int = zipfile.ZIP_STORED,
) -> Path:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"ZIP source directory does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=compression,
            allowZip64=True,
        ) as archive:
            for path in files:
                info = zipfile.ZipInfo(
                    path.relative_to(source).as_posix(),
                    date_time=_DETERMINISTIC_ZIP_TIMESTAMP,
                )
                info.compress_type = compression
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--deflate",
        action="store_true",
        help="Use deflate compression; the default stores files without compression.",
    )
    args = parser.parse_args()
    compression = zipfile.ZIP_DEFLATED if args.deflate else zipfile.ZIP_STORED
    create_portable_zip(args.source, args.output, compression=compression)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
