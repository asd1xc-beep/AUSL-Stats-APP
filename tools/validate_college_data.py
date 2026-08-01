"""Offline, developer-only validator for an explicitly supplied college JSON file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ausl_college import load_envelope, validate_envelope  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate one explicit Phase 7B college résumé JSON file."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        envelope = load_envelope(args.path.read_bytes())
        report = validate_envelope(envelope)
    except (OSError, ValueError) as exc:
        print(f"INVALID: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"{'VALID' if report.valid else 'INVALID'}: "
        f"players={report.player_count} sources={report.source_count}"
    )
    for error in report.errors:
        print(f"ERROR: {error}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
