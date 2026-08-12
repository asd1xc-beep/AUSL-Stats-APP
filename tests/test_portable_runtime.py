from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.build_portable_runtime import (
    LAUNCHER_NAME,
    TROUBLESHOOT_NAME,
    check_runtime_pin,
    detect_python_tag,
    prune_runtime,
    pth_contents,
    stage_portable_runtime,
    validate_runtime,
)
from tools.verify_distribution import scan_distribution


ROOT = Path(__file__).resolve().parents[1]


def _embeddable_archive(tmp_path: Path, *, tag: str = "python312") -> Path:
    """Build a stand-in for the python.org Windows embeddable package."""

    archive = tmp_path / f"python-3.12.11-embed-amd64.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("python.exe", b"MZ embedded launcher")
        writer.writestr("pythonw.exe", b"MZ embedded windowed launcher")
        writer.writestr(f"{tag}.dll", b"MZ embedded interpreter")
        writer.writestr(f"{tag}.zip", b"PK\x03\x04 stdlib")
        writer.writestr(f"{tag}._pth", f"{tag}.zip\n.\n")
        writer.writestr("_socket.pyd", b"MZ socket")
        writer.writestr("LICENSE.txt", "PSF license\n")
    return archive


def _base_python(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a stand-in for a full CPython install that supplies Tk."""

    base = tmp_path / "base-python"
    lib_dir = base / "Lib"
    dlls_dir = base / "DLLs"
    tcl_dir = base / "tcl"
    (lib_dir / "tkinter").mkdir(parents=True)
    (lib_dir / "tkinter" / "__init__.py").write_text("# tkinter\n", encoding="utf-8")
    (lib_dir / "tkinter" / "ttk.py").write_text("# ttk\n", encoding="utf-8")
    cache = lib_dir / "tkinter" / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-312.pyc").write_bytes(b"\x00compiled")
    dlls_dir.mkdir(parents=True)
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
        (dlls_dir / name).write_bytes(b"MZ " + name.encode("ascii"))
    for name in ("tcl8.6", "tk8.6"):
        (tcl_dir / name).mkdir(parents=True)
        (tcl_dir / name / "init.tcl").write_text("# tcl\n", encoding="utf-8")
    return lib_dir, dlls_dir, tcl_dir


def _staged_package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    (package / "src").mkdir(parents=True)
    (package / "src" / "ausl_stats_app.py").write_text("# app\n", encoding="utf-8")
    (package / "src" / "ausl_data.py").write_text("# data\n", encoding="utf-8")
    lib_dir, dlls_dir, tcl_dir = _base_python(tmp_path)
    stage_portable_runtime(
        package,
        embeddable_archive=_embeddable_archive(tmp_path),
        lib_dir=lib_dir,
        dlls_dir=dlls_dir,
        tcl_dir=tcl_dir,
    )
    return package


def _install_fake_site_packages(package: Path) -> Path:
    site_packages = package / "runtime" / "Lib" / "site-packages"
    for name in ("pandas", "numpy", "openpyxl", "pypdf", "certifi"):
        (site_packages / name).mkdir(parents=True)
        (site_packages / name / "__init__.py").write_text(
            f"# {name}\n", encoding="utf-8"
        )
    return site_packages


def test_pth_puts_app_sources_and_site_packages_on_the_isolated_path():
    lines = pth_contents("python312").splitlines()

    assert lines[0] == "python312.zip"
    # A ._pth forces isolated mode, so the script directory is not added
    # automatically and ..\src has to be declared for `import ausl_data`.
    assert "..\\src" in lines
    assert "Lib\\site-packages" in lines
    assert "Lib" in lines
    assert "import site" in lines
    assert all("/" not in line for line in lines if line != "import site")


def test_stage_produces_a_runtime_that_passes_its_own_verification(tmp_path):
    package = _staged_package(tmp_path)
    _install_fake_site_packages(package)
    prune_runtime(package / "runtime")

    assert validate_runtime(package / "runtime") == []
    assert detect_python_tag(package / "runtime") == "python312"


def test_stage_grafts_the_tk_runtime_the_embeddable_package_omits(tmp_path):
    package = _staged_package(tmp_path)
    runtime = package / "runtime"

    assert (runtime / "Lib" / "tkinter" / "__init__.py").is_file()
    for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
        assert (runtime / name).is_file(), name
    assert (runtime / "tcl" / "tcl8.6" / "init.tcl").is_file()
    assert (runtime / "tcl" / "tk8.6" / "init.tcl").is_file()


def test_stage_overwrites_the_default_pth_from_the_embeddable_archive(tmp_path):
    package = _staged_package(tmp_path)

    contents = (package / "runtime" / "python312._pth").read_text(encoding="ascii")

    assert contents == pth_contents("python312")


def test_prune_removes_bytecode_and_vendored_test_suites(tmp_path):
    package = _staged_package(tmp_path)
    site_packages = _install_fake_site_packages(package)
    tests_dir = site_packages / "pandas" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_frame.py").write_text("# heavy\n", encoding="utf-8")
    keep = site_packages / "numpy" / "testing"
    keep.mkdir(parents=True)
    (keep / "__init__.py").write_text("# public helper\n", encoding="utf-8")
    stray = site_packages / "numpy" / "__pycache__"
    stray.mkdir(parents=True)
    (stray / "core.cpython-312.pyc").write_bytes(b"\x00compiled")

    prune_runtime(package / "runtime")

    assert not tests_dir.exists()
    assert not stray.exists()
    # numpy.testing is a documented public API, unlike the bundled test suites.
    assert (keep / "__init__.py").is_file()
    assert not any((package / "runtime").rglob("*.pyc"))
    assert not any(
        path.name == "__pycache__" for path in (package / "runtime").rglob("*")
    )


def test_validate_reports_a_runtime_that_lost_its_dependencies(tmp_path):
    package = _staged_package(tmp_path)
    prune_runtime(package / "runtime")

    problems = validate_runtime(package / "runtime")

    assert any("site-packages" in problem for problem in problems)


def test_validate_reports_a_runtime_missing_tk(tmp_path):
    package = _staged_package(tmp_path)
    _install_fake_site_packages(package)
    (package / "runtime" / "_tkinter.pyd").unlink()

    problems = validate_runtime(package / "runtime")

    assert any("_tkinter.pyd" in problem for problem in problems)


def test_launchers_are_written_beside_the_app_sources(tmp_path):
    package = _staged_package(tmp_path)

    launcher = (package / LAUNCHER_NAME).read_text(encoding="ascii")
    troubleshoot = (package / TROUBLESHOOT_NAME).read_text(encoding="ascii")

    # pythonw keeps the tkinter GUI from opening a stray console window.
    assert "runtime\\pythonw.exe" in launcher
    assert "src\\ausl_stats_app.py" in launcher
    assert "TCL_LIBRARY" in launcher and "TK_LIBRARY" in launcher
    # The fallback launcher must stay on screen so startup errors are readable.
    assert "runtime\\python.exe" in troubleshoot
    assert "pause" in troubleshoot


def test_portable_package_passes_the_distribution_privacy_scan(tmp_path):
    package = _staged_package(tmp_path)
    _install_fake_site_packages(package)
    prune_runtime(package / "runtime")

    violations = scan_distribution(package)

    assert violations == []


def test_runtime_pin_rejects_an_unpinned_archive(tmp_path):
    archive = _embeddable_archive(tmp_path)
    pins = tmp_path / "pins.json"
    pins.write_text(
        json.dumps({"archives": {}, "schema_version": 1}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no pinned SHA-256"):
        check_runtime_pin(archive, pins)


def test_runtime_pin_records_then_enforces_the_archive_hash(tmp_path):
    archive = _embeddable_archive(tmp_path)
    pins = tmp_path / "pins.json"
    pins.write_text(
        json.dumps({"archives": {}, "schema_version": 1}), encoding="utf-8"
    )

    digest = check_runtime_pin(archive, pins, accept=True)
    assert check_runtime_pin(archive, pins) == digest

    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="does not match its pinned SHA-256"):
        check_runtime_pin(archive, pins)


def test_committed_pin_file_is_a_well_formed_allowlist():
    pins = json.loads(
        (ROOT / "tools" / "embedded_runtime_pins.json").read_text(encoding="utf-8")
    )

    assert pins["schema_version"] == 1
    assert isinstance(pins["archives"], dict)
    for name, digest in pins["archives"].items():
        assert name.startswith("python-3.12.") and name.endswith("-embed-amd64.zip")
        assert isinstance(digest, str) and len(digest) == 64


BUILD_SCRIPTS = (
    "Build Portable AUSL App.ps1",
    "Build Safer No-EXE AUSL App.ps1",
    "Build Shareable AUSL App.ps1",
)


def test_every_tool_a_build_script_invokes_imports_standalone(tmp_path):
    """Guard the by-path invocation the build scripts actually use.

    A build script runs each tool as ``python tools\\<name>.py``, which puts
    tools/ on sys.path instead of the project root, so a module-level
    ``from tools...`` import fails. In-process tests cannot catch this because
    pytest inserts the rootdir for them, so the check has to be a subprocess
    started outside the project directory.
    """

    referenced: set[str] = set()
    for name in BUILD_SCRIPTS:
        script = (ROOT / name).read_text(encoding="utf-8")
        referenced.update(re.findall(r"tools\\(\w+\.py)", script))
    assert referenced, "no build script tool invocations were found"

    for tool in sorted(referenced):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / tool), "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"{tool} failed to start:\n{result.stderr}"


def test_portable_build_script_keeps_the_fail_closed_packaging_contract():
    script = (ROOT / "Build Portable AUSL App.ps1").read_text(encoding="utf-8")

    assert "tools\\verify_distribution.py" in script
    assert "build_portable_runtime.py" in script
    assert "create_portable_zip.py" in script
    # The runtime must come from python.org over HTTPS and be hash-pinned.
    assert "https://www.python.org/ftp/python/" in script
    assert "pin" in script
    # PyInstaller is what triggers the quarantine problem this build avoids.
    assert "PyInstaller" not in script
