"""Apply the recorded project-owner review to one exact Phase 7C pilot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ausl_college_approval import APPROVAL_DECISION, approve_pilot_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument("--reviewer-role", required=True, choices=("project_owner",))
    parser.add_argument("--review-date", required=True)
    args = parser.parse_args(argv)
    try:
        result = approve_pilot_files(
            args.input,
            args.output_directory,
            expected_input_sha256=args.expected_input_sha256,
            reviewer_role=args.reviewer_role,
            review_date=args.review_date,
            decision=APPROVAL_DECISION,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Approved college envelope SHA-256: {result.approved_sha256}")
    print("Review role: project_owner (project-owner acceptance; not producer review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
