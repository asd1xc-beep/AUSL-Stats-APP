from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ausl_college_connection_approval import (  # noqa: E402
    approve_connection_files,
)


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply explicit project-owner approval to Phase 7E connections."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        result = approve_connection_files(
            args.candidates, args.decisions, args.output_dir
        )
    except Exception as exc:
        print(f"Phase 7E connection approval failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Phase 7E connection approval complete: "
        f"input={result.input_sha256} approved={result.approved_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
