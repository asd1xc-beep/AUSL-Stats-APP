from __future__ import annotations

import zipfile
import os
from pathlib import PurePosixPath

from tools.create_portable_zip import create_portable_zip


def test_portable_zip_uses_only_posix_member_paths_and_extracts_nested_files(
    tmp_path,
):
    source = tmp_path / "source"
    (source / "src" / "nested").mkdir(parents=True)
    (source / "src" / "nested" / "fixture.py").write_text(
        "print('fixture')\n", encoding="utf-8"
    )
    (source / "README.txt").write_text("fixture\n", encoding="utf-8")
    archive_path = tmp_path / "portable.zip"

    create_portable_zip(source, archive_path, compression=zipfile.ZIP_STORED)

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert names == ["README.txt", "src/nested/fixture.py"]
        assert all("\\" not in name for name in names)
        assert all(PurePosixPath(name).as_posix() == name for name in names)
        extract_root = tmp_path / "extracted"
        archive.extractall(extract_root)

    assert (extract_root / "src" / "nested" / "fixture.py").read_text(
        encoding="utf-8"
    ) == "print('fixture')\n"


def test_build_scripts_use_cross_platform_zip_writer():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for filename in (
        "Build Safer No-EXE AUSL App.ps1",
        "Build Shareable AUSL App.ps1",
        "Build Portable AUSL App.ps1",
    ):
        script = (root / filename).read_text(encoding="utf-8")
        assert "tools\\create_portable_zip.py" in script
        assert "Compress-Archive" not in script


def test_portable_zip_bytes_are_deterministic_across_source_mtime_changes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    payload = source / "fixture.txt"
    payload.write_text("same bytes\n", encoding="utf-8")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    create_portable_zip(source, first)
    os.utime(payload, (1_900_000_000, 1_900_000_000))
    create_portable_zip(source, second)

    assert first.read_bytes() == second.read_bytes()
