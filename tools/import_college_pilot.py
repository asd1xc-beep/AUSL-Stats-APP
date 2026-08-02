"""Offline command for explicit Phase 7C developer-review pilot imports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ausl_college_import import import_college_pilot  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import one explicit developer-review college pilot."
    )
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--pilot-manifest", type=Path, required=True)
    parser.add_argument("--source-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = import_college_pilot(
            args.roster,
            args.pilot_manifest,
            args.source_records,
            args.output,
            args.review_report,
        )
    except (OSError, ValueError) as exc:
        print(f"IMPORT BLOCKED: {type(exc).__name__}: {exc}")
        return 1
    print(
        "DEVELOPER-REVIEW PILOT PROMOTED: "
        f"envelope_sha256={result.envelope_sha256} "
        f"review_sha256={result.review_report_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
