from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ausl_college_approval import load_checked_in_approval  # noqa: E402
from ausl_college_scale import (  # noqa: E402
    batch_bundle_payloads,
    build_batch_manifests,
    build_developer_review_batch,
    build_roster_coverage,
    promote_batch_bundle,
    render_roster_coverage_report,
    serialize_coverage_manifest,
    validate_roster_coverage,
)
from ausl_data import SEASONS  # noqa: E402


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build offline Phase 7E developer-review roster batches."
    )
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--approved-dir", type=Path, required=True)
    parser.add_argument("--update-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--coverage-report", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    return parser.parse_args(argv)


def _atomic_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    staged = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def build_review_bundle(
    *,
    roster_path: Path,
    approved_dir: Path,
    update_manifest_path: Path,
    output_dir: Path,
    coverage_report_path: Path | None = None,
    batch_size: int = 10,
) -> tuple[int, int]:
    season = max(SEASONS)
    update = json.loads(update_manifest_path.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(str(update["updated_at"]))
    health = update.get("source_health", {}).get("official_rosters", {})
    roster_hash = str(health.get("content_hash_or_etag") or "")
    source_url = str(update.get("source") or "")
    with pd.ExcelFile(roster_path) as workbook:
        sheet = f"roster_{season}"
        if sheet not in workbook.sheet_names:
            raise ValueError(f"canonical roster workbook is missing {sheet}")
        roster = pd.read_excel(workbook, sheet_name=sheet)
    approved = load_checked_in_approval(approved_dir)
    coverage = build_roster_coverage(
        roster,
        season=season,
        generated_at=generated_at,
        approved_artifact=approved,
        batch_size=batch_size,
    )
    coverage_report = validate_roster_coverage(coverage, roster, season=season)
    if not coverage_report.valid:
        raise ValueError("roster coverage validation failed: " + "; ".join(coverage_report.errors))
    batches = build_batch_manifests(coverage)
    for batch in batches:
        envelope = build_developer_review_batch(
            batch,
            roster,
            generated_at=generated_at,
            roster_snapshot_hash=roster_hash,
            source_url=source_url,
        )
        manifest_bytes, envelope_bytes, report_bytes = batch_bundle_payloads(
            batch, envelope
        )
        promote_batch_bundle(
            output_dir / "batches" / batch.batch_id,
            manifest_bytes=manifest_bytes,
            envelope_bytes=envelope_bytes,
            report_bytes=report_bytes,
        )
    _atomic_file(
        output_dir / "roster_coverage_manifest.json",
        serialize_coverage_manifest(coverage),
    )
    report_payload = render_roster_coverage_report(coverage).encode("utf-8")
    _atomic_file(output_dir / "Phase_7E_Roster_Coverage_Report.md", report_payload)
    if coverage_report_path is not None:
        _atomic_file(coverage_report_path, report_payload)
    return len(coverage.entries), len(batches)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        players, batches = build_review_bundle(
            roster_path=args.roster,
            approved_dir=args.approved_dir,
            update_manifest_path=args.update_manifest,
            output_dir=args.output_dir,
            coverage_report_path=args.coverage_report,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(f"Phase 7E roster review build failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Phase 7E developer-review roster bundle built: "
        f"players={players} batches={batches} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
