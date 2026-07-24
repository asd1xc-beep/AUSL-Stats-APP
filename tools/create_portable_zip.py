"""Create a deterministic-path ZIP that extracts correctly on Windows and POSIX."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path


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
                archive.write(
                    path,
                    arcname=path.relative_to(source).as_posix(),
                )
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
