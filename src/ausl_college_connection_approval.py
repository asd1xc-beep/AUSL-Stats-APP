"""Tamper-evident approval for exact Phase 7E college connections."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ausl_college_connections import (
    CONNECTION_SCHEMA_NAME,
    CONNECTION_SCHEMA_VERSION,
    CollegeConnectionBuildResult,
    CollegeConnectionCandidate,
    ConnectionApprovalState,
    ConnectionReviewState,
    load_connection_artifact,
    serialize_connection_artifact,
)


CONNECTION_APPROVAL_SCHEMA_NAME = "ausl-college-connection-approval"
CONNECTION_APPROVAL_SCHEMA_VERSION = 1
CONNECTION_APPROVAL_DECISION = "approved_for_college_connection_display"
CONNECTION_APPROVAL_SCOPE = "eight_reviewed_phase7e_connection_wordings"
APPROVED_CONNECTION_ARTIFACT_NAME = "college_connection_candidates.json"
CONNECTION_APPROVAL_MANIFEST_NAME = "college_connection_approval_manifest.json"
CONNECTION_APPROVAL_SUMMARY_NAME = "college_connection_approval_summary.txt"
DECISION_SCHEMA_NAME = "ausl-college-connection-review-decisions"
DECISION_SCHEMA_VERSION = 1


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_payload(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _review_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("review_date must use YYYY-MM-DD") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _string_list(raw: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{name} must be a nonempty-string array")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} contains duplicates")
    return tuple(value)


@dataclass(frozen=True)
class ConnectionApprovalBinding:
    connection_id: str
    connection_type: str
    player_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    season_scope: tuple[str, ...]
    wording: str
    source_ids: tuple[str, ...]
    input_evidence_version_hash: str
    approved_evidence_version_hash: str


@dataclass(frozen=True)
class ConnectionApprovalManifest:
    approval_schema_name: str
    approval_schema_version: int
    connection_schema_name: str
    connection_schema_version: int
    input_candidate_sha256: str
    approved_candidate_sha256: str
    reviewer_role: str
    review_date: str
    review_note_sha256: str
    decision: str
    review_scope: str
    bindings: tuple[ConnectionApprovalBinding, ...]


@dataclass(frozen=True)
class ConnectionApprovalResult:
    approved_payload: bytes
    manifest_payload: bytes
    summary_payload: bytes
    input_sha256: str
    approved_sha256: str


@dataclass(frozen=True)
class ApprovedConnectionArtifact:
    connections: CollegeConnectionBuildResult
    manifest: ConnectionApprovalManifest
    candidate_payload: bytes
    manifest_payload: bytes


def _binding(
    approved: CollegeConnectionCandidate,
    *,
    input_evidence_version_hash: str,
) -> ConnectionApprovalBinding:
    return ConnectionApprovalBinding(
        connection_id=approved.connection_id,
        connection_type=approved.connection_type.value,
        player_ids=approved.subject_player_ids,
        program_ids=approved.program_ids,
        season_scope=approved.season_scope,
        wording=approved.wording,
        source_ids=approved.evidence_source_ids,
        input_evidence_version_hash=input_evidence_version_hash,
        approved_evidence_version_hash=approved.evidence_version_hash,
    )


def _binding_wire(binding: ConnectionApprovalBinding) -> dict[str, Any]:
    return {
        "approved_evidence_version_hash": binding.approved_evidence_version_hash,
        "connection_id": binding.connection_id,
        "connection_type": binding.connection_type,
        "input_evidence_version_hash": binding.input_evidence_version_hash,
        "player_ids": list(binding.player_ids),
        "program_ids": list(binding.program_ids),
        "season_scope": list(binding.season_scope),
        "source_ids": list(binding.source_ids),
        "wording": binding.wording,
    }


def _load_decisions(payload: bytes, candidate_payload: bytes) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    if b"\r" in payload or not payload.endswith(b"\n"):
        raise ValueError("connection decisions must use deterministic UTF-8/LF")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("connection decisions are invalid UTF-8 JSON") from exc
    expected = {
        "schema_name",
        "schema_version",
        "candidate_artifact_sha256",
        "reviewer_role",
        "review_date",
        "review_note",
        "decisions",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError("connection decision fields are missing or unknown")
    if raw["schema_name"] != DECISION_SCHEMA_NAME or raw["schema_version"] != DECISION_SCHEMA_VERSION:
        raise ValueError("connection decision schema is unsupported")
    if raw["candidate_artifact_sha256"] != _sha(candidate_payload):
        raise ValueError("connection decision artifact hash does not match reviewed bytes")
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("connection reviewer_role must be project_owner")
    _review_timestamp(raw["review_date"])
    note = raw["review_note"]
    if not isinstance(note, str) or not note.strip():
        raise ValueError("connection review_note is required")
    if not isinstance(raw["decisions"], list):
        raise ValueError("connection decisions must be an array")
    seen = set()
    decisions = []
    for item in raw["decisions"]:
        if not isinstance(item, dict) or set(item) != {
            "connection_id",
            "evidence_version_hash",
            "decision",
        }:
            raise ValueError("connection decision entry fields are missing or unknown")
        connection_id = str(item["connection_id"]).strip()
        evidence_hash = str(item["evidence_version_hash"]).strip()
        if not connection_id or not evidence_hash:
            raise ValueError("connection decision identity and evidence hash are required")
        if connection_id in seen:
            raise ValueError("connection decisions contain duplicate IDs")
        if item["decision"] != CONNECTION_APPROVAL_DECISION:
            raise ValueError(f"connection {connection_id} is not approved")
        seen.add(connection_id)
        decisions.append((connection_id, evidence_hash))
    return raw["review_date"], note, tuple(decisions)


def approve_connection_payload(
    candidate_payload: bytes, decisions_payload: bytes
) -> ConnectionApprovalResult:
    review_date, review_note, decisions = _load_decisions(
        decisions_payload, candidate_payload
    )
    reviewed = load_connection_artifact(candidate_payload)
    if not reviewed.candidates:
        raise ValueError("connection review artifact contains no candidates")
    if any(
        item.review_state is not ConnectionReviewState.ELIGIBLE_FOR_REVIEW
        or item.approval_state is not ConnectionApprovalState.UNREVIEWED
        or item.air_ready
        for item in reviewed.candidates
    ):
        raise ValueError("connection input is not an unreviewed candidate set")
    by_id = {item.connection_id: item for item in reviewed.candidates}
    decision_map = dict(decisions)
    if set(decision_map) != set(by_id):
        raise ValueError("connection decisions do not exactly cover candidate IDs")
    for connection_id, candidate in by_id.items():
        if decision_map[connection_id] != candidate.evidence_version_hash:
            raise ValueError(
                f"connection {connection_id} evidence changed after project-owner review"
            )
    approved_candidates = tuple(
        replace(candidate, approval_state=ConnectionApprovalState.APPROVED)
        for candidate in reviewed.candidates
    )
    approved = CollegeConnectionBuildResult(approved_candidates, ())
    approved_payload = serialize_connection_artifact(
        approved, generated_at=_review_timestamp(review_date)
    )
    bindings = tuple(
        _binding(
            approved_candidate,
            input_evidence_version_hash=decision_map[approved_candidate.connection_id],
        )
        for approved_candidate in approved_candidates
    )
    manifest = {
        "approval_schema_name": CONNECTION_APPROVAL_SCHEMA_NAME,
        "approval_schema_version": CONNECTION_APPROVAL_SCHEMA_VERSION,
        "approved_candidate_sha256": _sha(approved_payload),
        "bindings": [_binding_wire(item) for item in bindings],
        "connection_schema_name": CONNECTION_SCHEMA_NAME,
        "connection_schema_version": CONNECTION_SCHEMA_VERSION,
        "decision": CONNECTION_APPROVAL_DECISION,
        "input_candidate_sha256": _sha(candidate_payload),
        "review_date": review_date,
        "review_note_sha256": _sha(review_note.strip().encode("utf-8")),
        "review_scope": CONNECTION_APPROVAL_SCOPE,
        "reviewer_role": "project_owner",
    }
    manifest_payload = _json_payload(manifest)
    summary_payload = (
        "AUSL Phase 7E College Connection Approval\n"
        f"Review role: project_owner\n"
        f"Review date: {review_date}\n"
        f"Approved connections: {len(approved_candidates)}\n"
        f"Input SHA-256: {_sha(candidate_payload)}\n"
        f"Approved SHA-256: {_sha(approved_payload)}\n"
    ).encode("utf-8")
    result = ConnectionApprovalResult(
        approved_payload=approved_payload,
        manifest_payload=manifest_payload,
        summary_payload=summary_payload,
        input_sha256=_sha(candidate_payload),
        approved_sha256=_sha(approved_payload),
    )
    validate_connection_approval(
        result.approved_payload,
        result.manifest_payload,
        original_candidate_payload=candidate_payload,
    )
    return result


_MANIFEST_FIELDS = {
    "approval_schema_name",
    "approval_schema_version",
    "connection_schema_name",
    "connection_schema_version",
    "input_candidate_sha256",
    "approved_candidate_sha256",
    "reviewer_role",
    "review_date",
    "review_note_sha256",
    "decision",
    "review_scope",
    "bindings",
}


def _manifest_from_mapping(raw: Mapping[str, Any]) -> ConnectionApprovalManifest:
    if set(raw) != _MANIFEST_FIELDS:
        raise ValueError("connection approval manifest fields are missing or unknown")
    if raw["approval_schema_name"] != CONNECTION_APPROVAL_SCHEMA_NAME:
        raise ValueError("connection approval schema name is unsupported")
    if raw["approval_schema_version"] != CONNECTION_APPROVAL_SCHEMA_VERSION:
        raise ValueError("connection approval schema version is unsupported")
    if raw["connection_schema_name"] != CONNECTION_SCHEMA_NAME or raw["connection_schema_version"] != CONNECTION_SCHEMA_VERSION:
        raise ValueError("connection candidate schema is unsupported")
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("connection approval reviewer role must be project_owner")
    _review_timestamp(raw["review_date"])
    if raw["decision"] != CONNECTION_APPROVAL_DECISION:
        raise ValueError("connection approval decision is unsupported")
    if raw["review_scope"] != CONNECTION_APPROVAL_SCOPE:
        raise ValueError("connection approval scope is unsupported")
    if not isinstance(raw["bindings"], list) or not raw["bindings"]:
        raise ValueError("connection approval bindings are required")
    expected_binding = {
        "approved_evidence_version_hash",
        "connection_id",
        "connection_type",
        "input_evidence_version_hash",
        "player_ids",
        "program_ids",
        "season_scope",
        "source_ids",
        "wording",
    }
    bindings = []
    for item in raw["bindings"]:
        if not isinstance(item, dict) or set(item) != expected_binding:
            raise ValueError("connection approval binding fields are missing or unknown")
        for name in (
            "connection_id",
            "connection_type",
            "wording",
            "input_evidence_version_hash",
            "approved_evidence_version_hash",
        ):
            if not isinstance(item[name], str) or not item[name].strip():
                raise ValueError(f"connection approval binding {name} is required")
        bindings.append(
            ConnectionApprovalBinding(
                connection_id=item["connection_id"],
                connection_type=item["connection_type"],
                player_ids=_string_list(item, "player_ids"),
                program_ids=_string_list(item, "program_ids"),
                season_scope=_string_list(item, "season_scope"),
                wording=item["wording"],
                source_ids=_string_list(item, "source_ids"),
                input_evidence_version_hash=item["input_evidence_version_hash"],
                approved_evidence_version_hash=item["approved_evidence_version_hash"],
            )
        )
    if len({item.connection_id for item in bindings}) != len(bindings):
        raise ValueError("connection approval bindings contain duplicate IDs")
    return ConnectionApprovalManifest(
        approval_schema_name=raw["approval_schema_name"],
        approval_schema_version=raw["approval_schema_version"],
        connection_schema_name=raw["connection_schema_name"],
        connection_schema_version=raw["connection_schema_version"],
        input_candidate_sha256=str(raw["input_candidate_sha256"]),
        approved_candidate_sha256=str(raw["approved_candidate_sha256"]),
        reviewer_role=raw["reviewer_role"],
        review_date=raw["review_date"],
        review_note_sha256=str(raw["review_note_sha256"]),
        decision=raw["decision"],
        review_scope=raw["review_scope"],
        bindings=tuple(bindings),
    )


def validate_connection_approval(
    approved_payload: bytes,
    manifest_payload: bytes,
    *,
    original_candidate_payload: bytes | None = None,
) -> ApprovedConnectionArtifact:
    if b"\r" in manifest_payload or not manifest_payload.endswith(b"\n"):
        raise ValueError("connection approval manifest must use deterministic UTF-8/LF")
    try:
        raw = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("connection approval manifest is invalid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("connection approval manifest root must be an object")
    manifest = _manifest_from_mapping(raw)
    if _sha(approved_payload) != manifest.approved_candidate_sha256:
        raise ValueError("approved connection artifact hash does not match manifest")
    if original_candidate_payload is not None and _sha(original_candidate_payload) != manifest.input_candidate_sha256:
        raise ValueError("reviewed connection artifact hash does not match manifest")
    approved = load_connection_artifact(approved_payload)
    if approved.suppressions:
        raise ValueError("approved connection artifact must not contain suppressions")
    if len(approved.candidates) != len(manifest.bindings):
        raise ValueError("approved connection count does not match manifest")
    for candidate, binding in zip(approved.candidates, manifest.bindings, strict=True):
        if (
            candidate.approval_state is not ConnectionApprovalState.APPROVED
            or not candidate.air_ready
        ):
            raise ValueError("approved connection is not eligible for producer use")
        unreviewed = replace(
            candidate, approval_state=ConnectionApprovalState.UNREVIEWED
        )
        expected = _binding(
            candidate,
            input_evidence_version_hash=unreviewed.evidence_version_hash,
        )
        if expected != binding:
            raise ValueError("approved connection fields do not match manifest binding")
    if original_candidate_payload is not None:
        original = load_connection_artifact(original_candidate_payload)
        if original.suppressions is None:
            raise ValueError("reviewed connection suppressions are invalid")
        originals = {item.connection_id: item for item in original.candidates}
        if set(originals) != {item.connection_id for item in manifest.bindings}:
            raise ValueError("reviewed connection IDs do not match approval manifest")
        for binding in manifest.bindings:
            candidate = originals[binding.connection_id]
            if candidate.evidence_version_hash != binding.input_evidence_version_hash:
                raise ValueError("reviewed connection evidence does not match approval manifest")
    return ApprovedConnectionArtifact(
        connections=approved,
        manifest=manifest,
        candidate_payload=approved_payload,
        manifest_payload=manifest_payload,
    )


def load_checked_in_connection_approval(
    directory: Path | str,
) -> ApprovedConnectionArtifact:
    root = Path(directory)
    return validate_connection_approval(
        (root / APPROVED_CONNECTION_ARTIFACT_NAME).read_bytes(),
        (root / CONNECTION_APPROVAL_MANIFEST_NAME).read_bytes(),
    )


def _temporary(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def approve_connection_files(
    candidate_path: Path | str,
    decisions_path: Path | str,
    output_directory: Path | str,
    *,
    decisions_payload: bytes | None = None,
    replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] = os.replace,
) -> ConnectionApprovalResult:
    input_payload = Path(candidate_path).read_bytes()
    decision_bytes = (
        decisions_payload
        if decisions_payload is not None
        else Path(decisions_path).read_bytes()
    )
    result = approve_connection_payload(input_payload, decision_bytes)
    root = Path(output_directory)
    destinations = (
        root / APPROVED_CONNECTION_ARTIFACT_NAME,
        root / CONNECTION_APPROVAL_MANIFEST_NAME,
        root / CONNECTION_APPROVAL_SUMMARY_NAME,
    )
    payloads = (
        result.approved_payload,
        result.manifest_payload,
        result.summary_payload,
    )
    temporaries = [
        _temporary(path, payload) for path, payload in zip(destinations, payloads)
    ]
    backups: list[tuple[Path, bytes | None]] = []
    try:
        for temporary, destination in zip(temporaries, destinations):
            backups.append(
                (destination, destination.read_bytes() if destination.exists() else None)
            )
            replace_func(temporary, destination)
        validate_connection_approval(
            destinations[0].read_bytes(),
            destinations[1].read_bytes(),
            original_candidate_payload=input_payload,
        )
    except Exception:
        for destination, previous in reversed(backups):
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                restore = _temporary(destination, previous)
                os.replace(restore, destination)
        raise
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
    return result
