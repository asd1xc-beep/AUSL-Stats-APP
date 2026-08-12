"""Stage a bundled CPython runtime so a shared package needs no installed Python.

The runtime is assembled from the official python.org Windows embeddable
package plus the Tk files that package deliberately omits. Nothing here is
compiled locally: every binary that ships is a signed, high-prevalence file
from an official CPython release, which is what keeps a freshly built package
out of Defender quarantine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


RUNTIME_DIRNAME = "runtime"
SITE_PACKAGES_RELATIVE = Path("Lib") / "site-packages"
LAUNCHER_NAME = "Start AUSL Broadcast Stats.bat"
TROUBLESHOOT_NAME = "Troubleshoot AUSL Portable.bat"

_PYTHON_TAG = re.compile(r"^python(\d{2,3})\.dll$", re.IGNORECASE)

TKINTER_BINARIES = ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll")
OPTIONAL_BINARIES = ("zlib1.dll",)
TCL_DATA_DIRS = ("tcl8.6", "tk8.6")

_PRUNED_DIR_NAMES = {"__pycache__", "tests", "test", "idlelib", "turtledemo"}
_PRUNED_SUFFIXES = {".pyc", ".pyo"}


PINS_NAME = "embedded_runtime_pins.json"


def _write_json_lf(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def check_runtime_pin(
    archive: Path, pins_path: Path, *, accept: bool = False
) -> str:
    """Verify a downloaded embeddable archive against its committed SHA-256.

    An unpinned archive is refused unless ``accept`` records it, so a build
    machine never silently ships a runtime nobody reviewed.
    """

    archive = Path(archive)
    pins_path = Path(pins_path)
    if not archive.is_file():
        raise ValueError(f"Embeddable runtime archive is missing: {archive}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    if pins_path.is_file():
        pins = json.loads(pins_path.read_text(encoding="utf-8"))
    else:
        pins = {"archives": {}, "schema_version": 1}
    if not isinstance(pins, dict) or not isinstance(pins.get("archives"), dict):
        raise ValueError(f"Runtime pin file is malformed: {pins_path}")

    archives = pins["archives"]
    expected = archives.get(archive.name)
    if isinstance(expected, str) and expected.strip():
        if expected.strip().casefold() != digest:
            raise ValueError(
                f"{archive.name} does not match its pinned SHA-256.\n"
                f"  pinned:     {expected.strip().casefold()}\n"
                f"  downloaded: {digest}\n"
                "Refusing to package an unexpected interpreter."
            )
        return digest

    if not accept:
        raise ValueError(
            f"{archive.name} has no pinned SHA-256 in {pins_path.name}.\n"
            f"  downloaded: {digest}\n"
            "Compare it against the checksum published on python.org, then "
            "re-run the build once with -AcceptRuntimeHash to record it."
        )

    archives[archive.name] = digest
    pins["archives"] = archives
    pins.setdefault("schema_version", 1)
    _write_json_lf(pins_path, pins)
    return digest


def detect_python_tag(runtime_root: Path) -> str:
    """Return the embedded interpreter tag (for example ``python312``)."""

    for path in sorted(Path(runtime_root).glob("python*.dll")):
        match = _PYTHON_TAG.match(path.name)
        if match:
            return f"python{match.group(1)}"
    raise ValueError(f"No embedded CPython DLL found in {runtime_root}")


def pth_contents(python_tag: str) -> str:
    """Return the ``._pth`` text that pins the embedded interpreter's sys.path.

    A ``._pth`` file puts the interpreter in isolated mode, so PYTHONPATH and
    PYTHONHOME on the recipient's machine cannot break the package. That also
    means the script directory is *not* added automatically, so ``..\\src`` has
    to be listed explicitly.
    """

    return (
        "\n".join(
            (
                f"{python_tag}.zip",
                ".",
                "Lib",
                "Lib\\site-packages",
                "..\\src",
                "import site",
            )
        )
        + "\n"
    )


def write_pth(runtime_root: Path, python_tag: str) -> Path:
    runtime_root = Path(runtime_root)
    destination = runtime_root / f"{python_tag}._pth"
    destination.write_text(pth_contents(python_tag), encoding="ascii", newline="\n")
    return destination


def extract_embeddable(archive: Path, runtime_root: Path) -> Path:
    """Unpack the python.org embeddable ZIP into the package runtime folder."""

    archive = Path(archive)
    runtime_root = Path(runtime_root)
    if not archive.is_file():
        raise ValueError(f"Embeddable runtime archive is missing: {archive}")
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as reader:
        for name in sorted(reader.namelist()):
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Unsafe embeddable archive entry: {name}")
            reader.extract(name, runtime_root)
    return runtime_root


def graft_tkinter(
    runtime_root: Path,
    *,
    lib_dir: Path,
    dlls_dir: Path,
    tcl_dir: Path,
) -> None:
    """Copy the Tk runtime the embeddable package omits.

    ``lib_dir``, ``dlls_dir`` and ``tcl_dir`` come from a full CPython install
    of the same minor version, so the grafted files match the embedded ABI.
    """

    runtime_root = Path(runtime_root)
    lib_dir = Path(lib_dir)
    dlls_dir = Path(dlls_dir)
    tcl_dir = Path(tcl_dir)

    source_package = lib_dir / "tkinter"
    if not (source_package / "__init__.py").is_file():
        raise ValueError(f"Tkinter package not found under {lib_dir}")
    destination_package = runtime_root / "Lib" / "tkinter"
    destination_package.parent.mkdir(parents=True, exist_ok=True)
    if destination_package.exists():
        shutil.rmtree(destination_package)
    shutil.copytree(source_package, destination_package)

    for name in TKINTER_BINARIES:
        source = dlls_dir / name
        if not source.is_file():
            raise ValueError(f"Required Tk binary is missing: {source}")
        shutil.copyfile(source, runtime_root / name)
    for name in OPTIONAL_BINARIES:
        source = dlls_dir / name
        if source.is_file():
            shutil.copyfile(source, runtime_root / name)

    for name in TCL_DATA_DIRS:
        source = tcl_dir / name
        if not source.is_dir():
            raise ValueError(f"Required Tk runtime data is missing: {source}")
        destination = runtime_root / "tcl" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)


def prune_runtime(runtime_root: Path) -> int:
    """Drop bytecode caches and vendored test suites from a staged runtime.

    tools/verify_distribution.py fails closed on ``__pycache__`` directories and
    ``.pyc`` files, and the pandas/numpy test suites add roughly 20 MB that a
    shared package never needs.
    """

    runtime_root = Path(runtime_root)
    removed = 0
    for path in sorted(
        runtime_root.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if path.is_dir() and path.name.casefold() in _PRUNED_DIR_NAMES:
            removed += sum(1 for item in path.rglob("*") if item.is_file())
            shutil.rmtree(path)
        elif path.is_file() and path.suffix.casefold() in _PRUNED_SUFFIXES:
            path.unlink()
            removed += 1
    for path in sorted(
        runtime_root.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed


def validate_runtime(runtime_root: Path) -> list[str]:
    """Return every reason a staged runtime would fail on a recipient machine."""

    runtime_root = Path(runtime_root)
    problems: list[str] = []
    try:
        python_tag = detect_python_tag(runtime_root)
    except ValueError as exc:
        return [str(exc)]

    required_files = [
        "python.exe",
        "pythonw.exe",
        f"{python_tag}.dll",
        f"{python_tag}.zip",
        f"{python_tag}._pth",
        *TKINTER_BINARIES,
    ]
    for name in required_files:
        if not (runtime_root / name).is_file():
            problems.append(f"runtime is missing {name}")

    if not (runtime_root / "Lib" / "tkinter" / "__init__.py").is_file():
        problems.append("runtime is missing the tkinter package")
    for name in TCL_DATA_DIRS:
        if not (runtime_root / "tcl" / name).is_dir():
            problems.append(f"runtime is missing Tk data: tcl/{name}")

    site_packages = runtime_root / SITE_PACKAGES_RELATIVE
    if not site_packages.is_dir():
        problems.append("runtime is missing Lib/site-packages")
    else:
        for package in ("pandas", "numpy", "openpyxl", "pypdf", "certifi"):
            if not (site_packages / package).is_dir():
                problems.append(f"runtime is missing the {package} package")

    pth = runtime_root / f"{python_tag}._pth"
    if pth.is_file():
        lines = pth.read_text(encoding="ascii").splitlines()
        for required_line in ("Lib\\site-packages", "..\\src", "import site"):
            if required_line not in lines:
                problems.append(f"{pth.name} is missing the line: {required_line}")

    for path in runtime_root.rglob("*"):
        if path.is_dir() and path.name == "__pycache__":
            problems.append(f"bytecode cache survived pruning: {path.name}")
            break
    for path in runtime_root.rglob("*.pyc"):
        problems.append(f"bytecode file survived pruning: {path.name}")
        break

    return problems


def launcher_contents() -> str:
    """Return the double-click launcher that starts the GUI with no console."""

    return (
        "@echo off\r\n"
        "setlocal\r\n"
        'cd /d "%~dp0"\r\n'
        'set "TCL_LIBRARY=%~dp0runtime\\tcl\\tcl8.6"\r\n'
        'set "TK_LIBRARY=%~dp0runtime\\tcl\\tk8.6"\r\n'
        'if not exist "%~dp0runtime\\pythonw.exe" (\r\n'
        "  echo The bundled AUSL runtime folder is missing.\r\n"
        "  echo Extract the whole ZIP folder before starting the app.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        'start "" "%~dp0runtime\\pythonw.exe" "%~dp0src\\ausl_stats_app.py"\r\n'
    )


def troubleshoot_contents() -> str:
    """Return a console launcher that keeps startup errors on screen."""

    return (
        "@echo off\r\n"
        "setlocal\r\n"
        'cd /d "%~dp0"\r\n'
        'set "TCL_LIBRARY=%~dp0runtime\\tcl\\tcl8.6"\r\n'
        'set "TK_LIBRARY=%~dp0runtime\\tcl\\tk8.6"\r\n'
        "echo Starting AUSL Broadcast Stats with the console visible.\r\n"
        "echo Leave this window open and copy any error text it shows.\r\n"
        "echo.\r\n"
        '"%~dp0runtime\\python.exe" "%~dp0src\\ausl_stats_app.py"\r\n'
        "echo.\r\n"
        "echo The app exited with code %errorlevel%.\r\n"
        "pause\r\n"
    )


def write_launchers(package_root: Path) -> list[Path]:
    package_root = Path(package_root)
    written = []
    for name, text in (
        (LAUNCHER_NAME, launcher_contents()),
        (TROUBLESHOOT_NAME, troubleshoot_contents()),
    ):
        destination = package_root / name
        destination.write_bytes(text.encode("ascii"))
        written.append(destination)
    return written


def stage_portable_runtime(
    package_root: Path,
    *,
    embeddable_archive: Path,
    lib_dir: Path,
    dlls_dir: Path,
    tcl_dir: Path,
) -> Path:
    """Assemble the runtime folder and launchers inside a staged package."""

    package_root = Path(package_root)
    if not (package_root / "src" / "ausl_stats_app.py").is_file():
        raise ValueError(f"Package sources are not staged under {package_root}")
    runtime_root = package_root / RUNTIME_DIRNAME
    extract_embeddable(embeddable_archive, runtime_root)
    write_pth(runtime_root, detect_python_tag(runtime_root))
    graft_tkinter(
        runtime_root, lib_dir=lib_dir, dlls_dir=dlls_dir, tcl_dir=tcl_dir
    )
    write_launchers(package_root)
    return runtime_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage", help="Extract and graft the runtime.")
    stage.add_argument("package_root", type=Path)
    stage.add_argument("--embeddable-archive", required=True, type=Path)
    stage.add_argument("--lib-dir", required=True, type=Path)
    stage.add_argument("--dlls-dir", required=True, type=Path)
    stage.add_argument("--tcl-dir", required=True, type=Path)

    prune = subparsers.add_parser("prune", help="Remove caches and test suites.")
    prune.add_argument("runtime_root", type=Path)

    verify = subparsers.add_parser("verify", help="Validate a staged runtime.")
    verify.add_argument("runtime_root", type=Path)

    pin = subparsers.add_parser("pin", help="Check the embeddable archive hash.")
    pin.add_argument("archive", type=Path)
    pin.add_argument(
        "--pins", type=Path, default=Path(__file__).resolve().parent / PINS_NAME
    )
    pin.add_argument(
        "--accept",
        action="store_true",
        help="Record the downloaded hash instead of failing on an unpinned archive.",
    )

    args = parser.parse_args(argv)
    if args.command == "pin":
        try:
            digest = check_runtime_pin(args.archive, args.pins, accept=args.accept)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # The unpinned-archive message carries the operator's next step, so
            # it must stay readable instead of trailing an argparse usage dump.
            print(f"Embeddable runtime pin check failed: {exc}", file=sys.stderr)
            return 1
        print(f"Embeddable runtime SHA-256 verified: {digest}")
        return 0
    try:
        if args.command == "stage":
            runtime_root = stage_portable_runtime(
                args.package_root,
                embeddable_archive=args.embeddable_archive,
                lib_dir=args.lib_dir,
                dlls_dir=args.dlls_dir,
                tcl_dir=args.tcl_dir,
            )
            print(f"Staged portable runtime: {runtime_root}")
            return 0
        if args.command == "prune":
            removed = prune_runtime(args.runtime_root)
            print(f"Pruned {removed} cache and test files from {args.runtime_root}")
            return 0
        problems = validate_runtime(args.runtime_root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    if problems:
        for problem in problems:
            print(f"Portable runtime problem: {problem}")
        return 1
    print(f"Portable runtime verified: {args.runtime_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
