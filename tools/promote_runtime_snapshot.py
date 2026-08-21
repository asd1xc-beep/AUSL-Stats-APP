"""Promote a local runtime refresh into the canonical tracked snapshot.

`PERF-003` routes refresh output to an untracked `data/runtime/exports` so
running the app no longer overwrites the checked-in snapshot in place. This
tool is the deliberate, explicit step that replaces that side effect.

Promotion copies only the six core exports the distribution allowlist
permits, regenerates `distribution_manifest.json`, and re-runs the same
verification CI runs. It is a dry run unless `--confirm` is passed, and it
refuses to promote anything that would not pass verification.

    python tools/promote_runtime_snapshot.py            # report only
    python tools/promote_runtime_snapshot.py --confirm  # promote

The four core workbooks are tracked in Git LFS. After promoting, review
`git diff --stat -- data/exports` and commit the change deliberately.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from generate_distribution_manifest import (  # noqa: E402
    CORE_EXPORTS,
    generate_distribution_manifest,
)
from verify_distribution import scan_distribution  # noqa: E402

MINIMUM_PYTHON = (3, 12)
CORE_WORKBOOKS = tuple(name for name in CORE_EXPORTS if name.endswith(".xlsx"))


def _require_pinned_interpreter() -> None:
    """CI and the virtual environment pin 3.12; fail loudly on anything else."""

    if sys.version_info[:2] != MINIMUM_PYTHON:
        raise SystemExit(
            f"This tool must run on Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}, "
            f"not {sys.version.split()[0]}. Use the pinned virtual environment."
        )


def _problems(runtime: Path) -> list[str]:
    problems = []
    if not runtime.is_dir():
        return [f"no runtime snapshot at {runtime}"]
    for name in CORE_EXPORTS:
        path = runtime / name
        if not path.is_file():
            problems.append(f"missing core export: {name}")
            continue
        payload = path.read_bytes()
        if not payload:
            problems.append(f"core export is empty: {name}")
        elif name in CORE_WORKBOOKS and not payload.startswith(b"PK\x03\x04"):
            problems.append(
                f"core workbook is not a real XLSX payload: {name}"
            )
    return problems


def promote(*, confirm: bool) -> int:
    import ausl_data

    runtime = ausl_data.runtime_export_dir()
    canonical = ausl_data.canonical_export_dir()

    problems = _problems(runtime)
    if problems:
        print(f"Refusing to promote {runtime}:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    # Verify a staged copy before touching the canonical snapshot, so a
    # runtime snapshot that would fail CI never lands in data/exports.
    with tempfile.TemporaryDirectory(prefix="ausl-promote-") as staging_name:
        staging = Path(staging_name) / "exports"
        staging.mkdir(parents=True)
        for name in CORE_EXPORTS:
            shutil.copy2(runtime / name, staging / name)
        generate_distribution_manifest(staging)
        violations = scan_distribution(staging)
        if violations:
            print("Refusing to promote; verification failed:", file=sys.stderr)
            for violation in violations:
                print(f"- {violation.entry} ({violation.reason})", file=sys.stderr)
            return 1

        print(f"Runtime snapshot verified: {runtime}")
        for name in sorted(CORE_EXPORTS):
            payload = (staging / name).read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            current = canonical / name
            state = "unchanged"
            if not current.is_file():
                state = "new"
            elif hashlib.sha256(current.read_bytes()).hexdigest() != digest:
                state = "CHANGED"
            print(f"  {state:>9}  {name}  {len(payload)} bytes  {digest[:12]}")

        if not confirm:
            print(
                "\nDry run. Nothing was written. "
                "Re-run with --confirm to promote into the tracked snapshot."
            )
            return 0

        for name in CORE_EXPORTS:
            shutil.copy2(staging / name, canonical / name)
        generate_distribution_manifest(canonical)

    violations = scan_distribution(canonical)
    if violations:
        print(
            "Promotion wrote a snapshot that fails verification; "
            "restore it with: git checkout -- data/exports",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"- {violation.entry} ({violation.reason})", file=sys.stderr)
        return 1

    print(f"\nPromoted into {canonical}.")
    print("Review `git diff --stat -- data/exports` and commit deliberately.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _require_pinned_interpreter()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Write the promotion. Without this the tool only reports.",
    )
    args = parser.parse_args(argv)
    return promote(confirm=args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
