from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ausl_college_batch_approval import load_aggregate_approval  # noqa: E402
from ausl_college_connections import (  # noqa: E402
    CollegeConnectionBuildResult,
    build_college_connections,
    serialize_connection_artifact,
)


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic Phase 7E college connection review candidates."
    )
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


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
            target = stage / name
            with target.open("wb") as stream:
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


def _review_packet(result: CollegeConnectionBuildResult, *, sources: dict) -> bytes:
    lines = [
        "# Phase 7E College Connection Review Packet",
        "",
        "Status: CONNECTION ENGINE COMPLETE — CONNECTION REVIEW PENDING",
        "",
        f"Candidate connections: {len(result.candidates)}",
        "",
        (
            "Each candidate below is deterministic and tied to its exact evidence "
            "version. No candidate has project-owner connection approval."
        ),
        "",
    ]
    for number, candidate in enumerate(result.candidates, 1):
        lines.extend(
            [
                f"## {number}. {candidate.connection_type.value.replace('_', ' ').title()}",
                "",
                f"- Connection ID: `{candidate.connection_id}`",
                f"- Evidence version: `{candidate.evidence_version_hash}`",
                f"- Exact AUSL player IDs: {', '.join(candidate.subject_player_ids)}",
                f"- Players: {', '.join(candidate.subject_display_names)}",
                f"- Programs: {', '.join(candidate.program_display_names) or 'Not applicable'}",
                f"- Season scope: {', '.join(candidate.season_scope) or 'Unavailable'}",
                f"- Candidate wording: {candidate.wording}",
                "- Project-owner decision: PENDING",
                "- Evidence records: " + ", ".join(f"`{item}`" for item in candidate.evidence_record_ids),
                "- Evidence sources:",
                "",
            ]
        )
        for source_id in candidate.evidence_source_ids:
            source = sources[source_id]
            reference = source.url or source.local_document_id or "reference unavailable"
            lines.append(
                f"  - `{source_id}` — {source.organization}, {source.title}; "
                f"{source.locator}; {reference}"
            )
        lines.append("")

    reason_counts = Counter(item.reason for item in result.suppressions)
    type_counts = Counter(item.connection_type.value for item in result.suppressions)
    lines.extend(
        [
            "## Suppressed relationship summary",
            "",
            f"Exact suppressed records: {len(result.suppressions)}",
            "",
            "By reason:",
            "",
        ]
    )
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "By relationship type:", ""])
    for connection_type, count in sorted(type_counts.items()):
        lines.append(f"- {connection_type}: {count}")
    lines.extend(
        [
            "",
            (
                "The companion JSON retains the exact subject IDs, program IDs, "
                "evidence references, reason, and diagnostic for every suppression."
            ),
            "",
            "## Review instructions",
            "",
            (
                "Approve, reject, or correct each connection ID and its exact wording. "
                "Approval of the eleven résumé batches does not approve these connections."
            ),
            "",
        ]
    )
    return ("\n".join(lines)).encode("utf-8")


def build(*, aggregate_dir: Path, output_dir: Path) -> tuple[int, int]:
    aggregate = load_aggregate_approval(aggregate_dir)
    result = build_college_connections(aggregate.envelope)
    candidate_payload = serialize_connection_artifact(
        result, generated_at=aggregate.envelope.generated_at
    )
    packet_payload = _review_packet(
        result,
        sources={source.source_id: source for source in aggregate.envelope.sources},
    )
    _atomic_directory(
        output_dir,
        {
            "connection_candidates.json": candidate_payload,
            "connection_review_packet.md": packet_payload,
        },
    )
    return len(result.candidates), len(result.suppressions)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        candidate_count, suppression_count = build(
            aggregate_dir=args.aggregate_dir, output_dir=args.output_dir
        )
    except Exception as exc:
        print(f"Phase 7E connection build failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Phase 7E connection review build complete: "
        f"candidates={candidate_count} suppressions={suppression_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
