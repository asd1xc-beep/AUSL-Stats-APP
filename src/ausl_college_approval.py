"""Tamper-evident approval transaction for reviewed college résumé data.

The developer-review pilot remains immutable.  This module derives a separate
producer-visible envelope whose exact bytes, identities, candidate values, and
known incomplete fields are bound by a small deterministic manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ausl_college import (
    CollegeEnvelope,
    CompletenessState,
    IdentityReviewState,
    assess_completeness,
    load_envelope,
    serialize_envelope,
    validate_envelope,
)


APPROVAL_SCHEMA_NAME = "ausl-college-approval"
APPROVAL_SCHEMA_VERSION = 1
APPROVAL_DECISION = "approved_for_college_resume_display"
APPROVAL_REVIEW_SCOPE = "reviewed_ten_player_college_resume_display"
APPROVED_ENVELOPE_NAME = "college_resume_envelope.json"
APPROVAL_MANIFEST_NAME = "college_approval_manifest.json"
APPROVAL_SUMMARY_NAME = "college_approval_summary.txt"
PILOT_PLAYER_IDS = (
    "169",
    "278",
    "933",
    "950",
    "1075",
    "1102",
    "1285",
    "1322",
    "1324",
    "1327",
)

_MANIFEST_FIELDS = {
    "approval_schema_name",
    "approval_schema_version",
    "college_schema_name",
    "college_schema_version",
    "completeness_profile",
    "input_envelope_sha256",
    "approved_envelope_sha256",
    "player_ids",
    "resume_ids",
    "candidate_ids",
    "reviewer_role",
    "review_date",
    "decision",
    "review_scope",
    "incomplete_fields",
    "completeness_totals",
}


def sha256_payload(payload: bytes) -> str:
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


def _review_timestamp(review_date: str) -> datetime:
    try:
        parsed = datetime.strptime(review_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("review_date must use YYYY-MM-DD") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _candidate_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(
        sorted(
            candidate.candidate_id
            for resume in envelope.resumes
            for record in resume.stat_records
            for candidate in record.candidates
        )
    )


def _resume_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(sorted(resume.resume_id for resume in envelope.resumes))


def _player_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(sorted((resume.player_id for resume in envelope.resumes), key=int))


def _incomplete_fields(envelope: CollegeEnvelope) -> tuple[str, ...]:
    values = []
    for resume in envelope.resumes:
        assessment = assess_completeness(resume, envelope)
        values.extend(
            f"{resume.player_id}:{field}" for field in assessment.missing_fields
        )
    return tuple(sorted(values))


def _completeness_totals(envelope: CollegeEnvelope) -> dict[str, int]:
    counts = Counter(
        assess_completeness(resume, envelope).state.value
        for resume in envelope.resumes
    )
    return {
        state.value: counts[state.value]
        for state in CompletenessState
    }


@dataclass(frozen=True)
class CollegeApprovalManifest:
    approval_schema_name: str
    approval_schema_version: int
    college_schema_name: str
    college_schema_version: int
    completeness_profile: str
    input_envelope_sha256: str
    approved_envelope_sha256: str
    player_ids: tuple[str, ...]
    resume_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    reviewer_role: str
    review_date: str
    decision: str
    review_scope: str
    incomplete_fields: tuple[str, ...]
    completeness_totals: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ApprovedCollegeArtifact:
    envelope: CollegeEnvelope
    manifest: CollegeApprovalManifest
    envelope_payload: bytes
    manifest_payload: bytes


@dataclass(frozen=True)
class CollegeApprovalResult:
    envelope_payload: bytes
    manifest_payload: bytes
    summary_payload: bytes
    input_sha256: str
    approved_sha256: str


def _manifest_from_mapping(raw: Mapping[str, Any]) -> CollegeApprovalManifest:
    unknown = set(raw) - _MANIFEST_FIELDS
    missing = _MANIFEST_FIELDS - set(raw)
    if unknown or missing:
        raise ValueError(
            f"college approval manifest fields are missing or unknown: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if raw["approval_schema_name"] != APPROVAL_SCHEMA_NAME:
        raise ValueError("college approval schema name is unsupported")
    if raw["approval_schema_version"] != APPROVAL_SCHEMA_VERSION:
        raise ValueError("college approval schema version is unsupported")
    for name in (
        "college_schema_name",
        "input_envelope_sha256",
        "approved_envelope_sha256",
        "reviewer_role",
        "review_date",
        "decision",
        "review_scope",
        "completeness_profile",
    ):
        if not isinstance(raw[name], str) or not raw[name].strip():
            raise ValueError(f"college approval {name} is required")
    _review_timestamp(raw["review_date"])
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("college approval reviewer role must be project_owner")
    if raw["decision"] != APPROVAL_DECISION:
        raise ValueError("college approval decision is unsupported")
    if raw["review_scope"] != APPROVAL_REVIEW_SCOPE:
        raise ValueError("college approval review scope is unsupported")
    for name in ("player_ids", "resume_ids", "candidate_ids", "incomplete_fields"):
        value = raw[name]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ValueError(f"college approval {name} must be a string array")
        if len(value) != len(set(value)):
            raise ValueError(f"college approval {name} contains duplicates")
    totals = raw["completeness_totals"]
    if not isinstance(totals, dict) or set(totals) != {
        state.value for state in CompletenessState
    }:
        raise ValueError("college approval completeness_totals are invalid")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in totals.values()):
        raise ValueError("college approval completeness totals must be nonnegative integers")
    return CollegeApprovalManifest(
        approval_schema_name=raw["approval_schema_name"],
        approval_schema_version=raw["approval_schema_version"],
        college_schema_name=raw["college_schema_name"],
        college_schema_version=raw["college_schema_version"],
        completeness_profile=raw["completeness_profile"],
        input_envelope_sha256=raw["input_envelope_sha256"],
        approved_envelope_sha256=raw["approved_envelope_sha256"],
        player_ids=tuple(raw["player_ids"]),
        resume_ids=tuple(raw["resume_ids"]),
        candidate_ids=tuple(raw["candidate_ids"]),
        reviewer_role=raw["reviewer_role"],
        review_date=raw["review_date"],
        decision=raw["decision"],
        review_scope=raw["review_scope"],
        incomplete_fields=tuple(raw["incomplete_fields"]),
        completeness_totals=tuple(sorted(totals.items())),
    )


def approve_pilot_payload(
    input_payload: bytes,
    *,
    expected_input_sha256: str,
    reviewer_role: str,
    review_date: str,
    decision: str,
) -> CollegeApprovalResult:
    """Derive one deterministic reviewed artifact without mutating the pilot."""

    input_hash = sha256_payload(input_payload)
    if input_hash != expected_input_sha256:
        raise ValueError("pilot input-envelope hash does not match the reviewed hash")
    if reviewer_role != "project_owner":
        raise ValueError("reviewer_role must be project_owner")
    if decision != APPROVAL_DECISION:
        raise ValueError("unsupported college review decision")
    reviewed_at = _review_timestamp(review_date)
    envelope = load_envelope(input_payload)
    report = validate_envelope(envelope)
    if not report.valid:
        raise ValueError("developer-review pilot failed Phase 7B validation")
    if _player_ids(envelope) != PILOT_PLAYER_IDS:
        raise ValueError("reviewed college pilot player IDs do not match the exact ten-player set")

    approved_resumes = []
    for resume in envelope.resumes:
        mappings = tuple(
            replace(
                mapping,
                review_state=IdentityReviewState.VERIFIED,
                reviewer=reviewer_role,
                reviewed_at=reviewed_at,
                evidence_reference=(
                    f"{APPROVAL_SCHEMA_NAME}:{input_hash}:{mapping.mapping_id}"
                ),
            )
            for mapping in resume.identity_mappings
        )
        statuses = tuple(
            (name, "verified" if name == "identity" else status)
            for name, status in resume.section_statuses
        )
        approved_resumes.append(
            replace(resume, identity_mappings=mappings, section_statuses=statuses)
        )
    approved_envelope = replace(
        envelope,
        generated_at=reviewed_at,
        resumes=tuple(approved_resumes),
        validation_metadata=tuple(
            sorted(
                {
                    *envelope.validation_metadata,
                    ("approval_decision", decision),
                    ("approval_input_sha256", input_hash),
                    ("approval_review_date", review_date),
                    ("approval_reviewer_role", reviewer_role),
                }
            )
        ),
    )
    approved_report = validate_envelope(approved_envelope)
    if not approved_report.valid or approved_report.unresolved_identities:
        raise ValueError("approved college envelope failed post-review validation")
    envelope_payload = serialize_envelope(approved_envelope)
    approved_hash = sha256_payload(envelope_payload)
    manifest = {
        "approval_schema_name": APPROVAL_SCHEMA_NAME,
        "approval_schema_version": APPROVAL_SCHEMA_VERSION,
        "college_schema_name": approved_envelope.schema_name,
        "college_schema_version": approved_envelope.schema_version,
        "completeness_profile": approved_envelope.completeness_profile,
        "input_envelope_sha256": input_hash,
        "approved_envelope_sha256": approved_hash,
        "player_ids": list(_player_ids(approved_envelope)),
        "resume_ids": list(_resume_ids(approved_envelope)),
        "candidate_ids": list(_candidate_ids(approved_envelope)),
        "reviewer_role": reviewer_role,
        "review_date": review_date,
        "decision": decision,
        "review_scope": APPROVAL_REVIEW_SCOPE,
        "incomplete_fields": list(_incomplete_fields(approved_envelope)),
        "completeness_totals": _completeness_totals(approved_envelope),
    }
    manifest_payload = _json_payload(manifest)
    summary_lines = [
        "AUSL College Résumé Approval Summary",
        f"Review role: {reviewer_role}",
        f"Review date: {review_date}",
        f"Decision: {decision}",
        f"Input SHA-256: {input_hash}",
        f"Approved SHA-256: {approved_hash}",
        f"Exact player IDs: {', '.join(_player_ids(approved_envelope))}",
        "Completeness: "
        + ", ".join(
            f"{name}={count}"
            for name, count in _completeness_totals(approved_envelope).items()
        ),
        "Incomplete fields: "
        + (", ".join(_incomplete_fields(approved_envelope)) or "none"),
        "",
    ]
    summary_payload = "\n".join(summary_lines).encode("utf-8")
    result = CollegeApprovalResult(
        envelope_payload,
        manifest_payload,
        summary_payload,
        input_hash,
        approved_hash,
    )
    validate_approved_payload(result.envelope_payload, result.manifest_payload)
    return result


def validate_approved_payload(
    envelope_payload: bytes,
    manifest_payload: bytes,
    *,
    original_pilot_payload: bytes | None = None,
) -> ApprovedCollegeArtifact:
    if b"\r" in manifest_payload or not manifest_payload.endswith(b"\n"):
        raise ValueError("college approval manifest must use deterministic UTF-8/LF output")
    try:
        raw = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("college approval manifest is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("college approval manifest root must be an object")
    manifest = _manifest_from_mapping(raw)
    if sha256_payload(envelope_payload) != manifest.approved_envelope_sha256:
        raise ValueError("approved college envelope hash does not match approval manifest")
    if original_pilot_payload is not None and sha256_payload(original_pilot_payload) != manifest.input_envelope_sha256:
        raise ValueError("developer pilot hash does not match approval manifest")
    envelope = load_envelope(envelope_payload)
    report = validate_envelope(envelope)
    if not report.valid:
        raise ValueError("approved college envelope failed schema validation")
    if envelope.schema_name != manifest.college_schema_name or envelope.schema_version != manifest.college_schema_version:
        raise ValueError("college schema identity does not match approval manifest")
    if envelope.completeness_profile != manifest.completeness_profile:
        raise ValueError("college completeness profile does not match approval manifest")
    if _player_ids(envelope) != manifest.player_ids or manifest.player_ids != PILOT_PLAYER_IDS:
        raise ValueError("approved college player IDs do not match approval manifest")
    if _resume_ids(envelope) != manifest.resume_ids:
        raise ValueError("approved college resume IDs do not match approval manifest")
    if _candidate_ids(envelope) != manifest.candidate_ids:
        raise ValueError("approved college candidate IDs do not match approval manifest")
    if _incomplete_fields(envelope) != manifest.incomplete_fields:
        raise ValueError("approved college incomplete fields do not match approval manifest")
    if tuple(sorted(_completeness_totals(envelope).items())) != manifest.completeness_totals:
        raise ValueError("approved college completeness totals do not match approval manifest")
    expected_time = _review_timestamp(manifest.review_date)
    for resume in envelope.resumes:
        if not resume.identity_mappings:
            raise ValueError("approved college resume is missing exact identity mappings")
        for mapping in resume.identity_mappings:
            if (
                mapping.ausl_player_id != resume.player_id
                or mapping.review_state is not IdentityReviewState.VERIFIED
                or mapping.reviewer != manifest.reviewer_role
                or mapping.reviewed_at != expected_time
                or not mapping.evidence_reference
                or manifest.input_envelope_sha256 not in mapping.evidence_reference
            ):
                raise ValueError("approved college identity review does not match approval transaction")
    return ApprovedCollegeArtifact(
        envelope=envelope,
        manifest=manifest,
        envelope_payload=envelope_payload,
        manifest_payload=manifest_payload,
    )


def load_checked_in_approval(directory: Path | str) -> ApprovedCollegeArtifact:
    root = Path(directory)
    return validate_approved_payload(
        (root / APPROVED_ENVELOPE_NAME).read_bytes(),
        (root / APPROVAL_MANIFEST_NAME).read_bytes(),
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


def approve_pilot_files(
    input_path: Path | str,
    output_directory: Path | str,
    *,
    expected_input_sha256: str,
    reviewer_role: str,
    review_date: str,
    decision: str = APPROVAL_DECISION,
    replace_func: Callable[[str | os.PathLike, str | os.PathLike], None] = os.replace,
) -> CollegeApprovalResult:
    """Build and atomically promote the validated envelope/manifest/summary set."""

    result = approve_pilot_payload(
        Path(input_path).read_bytes(),
        expected_input_sha256=expected_input_sha256,
        reviewer_role=reviewer_role,
        review_date=review_date,
        decision=decision,
    )
    root = Path(output_directory)
    destinations = (
        root / APPROVED_ENVELOPE_NAME,
        root / APPROVAL_MANIFEST_NAME,
        root / APPROVAL_SUMMARY_NAME,
    )
    payloads = (
        result.envelope_payload,
        result.manifest_payload,
        result.summary_payload,
    )
    temporaries = [_temporary(path, payload) for path, payload in zip(destinations, payloads)]
    backups: list[tuple[Path, bytes | None]] = []
    try:
        for temporary, destination in zip(temporaries, destinations):
            backups.append((destination, destination.read_bytes() if destination.exists() else None))
            replace_func(temporary, destination)
        validate_approved_payload(destinations[0].read_bytes(), destinations[1].read_bytes())
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
