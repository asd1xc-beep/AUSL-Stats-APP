from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ausl_college_approval import load_checked_in_approval  # noqa: E402
from ausl_college_batch_approval import (  # noqa: E402
    AGGREGATE_ENVELOPE_NAME,
    AGGREGATE_MANIFEST_NAME,
    AGGREGATE_SUMMARY_NAME,
    BATCH_APPROVAL_DECISION,
    BATCH_APPROVAL_MANIFEST_NAME,
    BATCH_APPROVAL_SUMMARY_NAME,
    BATCH_APPROVED_ENVELOPE_NAME,
    approve_batch_payloads,
    build_approved_aggregate,
    validate_aggregate_approval,
    validate_batch_approval,
)


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply explicit project-owner approval to Phase 7E review batches."
    )
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--pilot-approved-dir", type=Path, required=True)
    parser.add_argument("--approved-batches-dir", type=Path, required=True)
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _load_decisions(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_name",
        "schema_version",
        "reviewer_role",
        "review_date",
        "review_note",
        "decisions",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError("batch review decision fields are missing or unknown")
    if raw["schema_name"] != "ausl-college-batch-review-decisions" or raw["schema_version"] != 1:
        raise ValueError("batch review decision schema is unsupported")
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("batch review decision role must be project_owner")
    if not isinstance(raw["review_note"], str) or not raw["review_note"].strip():
        raise ValueError("batch review note is required")
    if not isinstance(raw["decisions"], list):
        raise ValueError("batch review decisions must be a list")
    expected_decision_fields = {
        "batch_id",
        "decision",
        "batch_manifest_sha256",
        "developer_review_envelope_sha256",
    }
    ids = []
    for decision in raw["decisions"]:
        if not isinstance(decision, dict) or set(decision) != expected_decision_fields:
            raise ValueError("batch decision fields are missing or unknown")
        if decision["decision"] != BATCH_APPROVAL_DECISION:
            raise ValueError(f"batch {decision.get('batch_id')} is not explicitly approved")
        ids.append(decision["batch_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("batch review decisions contain duplicate batch IDs")
    return raw


def _atomic_directory(destination: Path, payloads: dict[str, bytes]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
    )
    backup: Path | None = None
    try:
        for name, payload in payloads.items():
            path = stage / name
            with path.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        if destination.exists():
            backup = Path(
                tempfile.mkdtemp(
                    prefix=f".{destination.name}.",
                    suffix=".backup",
                    dir=destination.parent,
                )
            )
            backup.rmdir()
            os.replace(destination, backup)
        try:
            os.replace(stage, destination)
        except Exception:
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            raise
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def approve_all(
    *,
    review_root: Path,
    decisions_path: Path,
    pilot_approved_dir: Path,
    approved_batches_dir: Path,
    aggregate_dir: Path,
) -> tuple[int, int]:
    decisions = _load_decisions(decisions_path)
    actual_dirs = {
        path.name: path
        for path in (review_root / "batches").iterdir()
        if path.is_dir()
    }
    decision_ids = {item["batch_id"] for item in decisions["decisions"]}
    if decision_ids != set(actual_dirs):
        raise ValueError("batch review decisions do not exactly cover review batches")

    results = []
    for decision in sorted(decisions["decisions"], key=lambda item: item["batch_id"]):
        source = actual_dirs[decision["batch_id"]]
        manifest_payload = (source / "batch_manifest.json").read_bytes()
        envelope_payload = (source / "developer_review_envelope.json").read_bytes()
        result = approve_batch_payloads(
            manifest_payload,
            envelope_payload,
            expected_manifest_sha256=decision["batch_manifest_sha256"],
            expected_envelope_sha256=decision["developer_review_envelope_sha256"],
            reviewer_role=decisions["reviewer_role"],
            review_date=decisions["review_date"],
            decision=decision["decision"],
        )
        validate_batch_approval(
            result.approved_envelope_payload, result.approval_manifest_payload
        )
        _atomic_directory(
            approved_batches_dir / decision["batch_id"],
            {
                BATCH_APPROVED_ENVELOPE_NAME: result.approved_envelope_payload,
                BATCH_APPROVAL_MANIFEST_NAME: result.approval_manifest_payload,
                BATCH_APPROVAL_SUMMARY_NAME: result.summary_payload,
            },
        )
        results.append(result)

    coverage_payload = (review_root / "roster_coverage_manifest.json").read_bytes()
    pilot = load_checked_in_approval(pilot_approved_dir)
    aggregate = build_approved_aggregate(
        coverage_payload=coverage_payload,
        pilot_artifact=pilot,
        batch_results=tuple(results),
        reviewer_role=decisions["reviewer_role"],
        review_date=decisions["review_date"],
    )
    validate_aggregate_approval(
        aggregate.envelope_payload,
        aggregate.manifest_payload,
        coverage_payload=coverage_payload,
        pilot_artifact=pilot,
        batch_approval_payloads=tuple(
            result.approval_manifest_payload for result in results
        ),
    )
    _atomic_directory(
        aggregate_dir,
        {
            AGGREGATE_ENVELOPE_NAME: aggregate.envelope_payload,
            AGGREGATE_MANIFEST_NAME: aggregate.manifest_payload,
            AGGREGATE_SUMMARY_NAME: aggregate.summary_payload,
        },
    )
    return len(results), len(load_checked_in_approval(pilot_approved_dir).envelope.resumes) + sum(
        len(validate_batch_approval(result.approved_envelope_payload, result.approval_manifest_payload).envelope.resumes)
        for result in results
    )


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        batches, players = approve_all(
            review_root=args.review_root,
            decisions_path=args.decisions,
            pilot_approved_dir=args.pilot_approved_dir,
            approved_batches_dir=args.approved_batches_dir,
            aggregate_dir=args.aggregate_dir,
        )
    except Exception as exc:
        print(f"Phase 7E batch approval failed: {exc}", file=sys.stderr)
        return 1
    print(f"Phase 7E batch approval complete: batches={batches} players={players}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

