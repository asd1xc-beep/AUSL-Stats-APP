"""Tamper-evident Phase 7E batch approval and approved aggregate.

The transaction preserves each developer-review batch, records an explicit
project-owner decision, and combines only independently valid approved
batches with the accepted Phase 7D pilot.  It performs no collection and no
connection approval.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ausl_college import (
    CollegeEnvelope,
    CompletenessState,
    IdentityReviewState,
    assess_completeness,
    load_envelope,
    serialize_envelope,
    validate_envelope,
)
from ausl_college_approval import ApprovedCollegeArtifact, CollegeApprovalManifest
from ausl_college_scale import (
    BATCH_SCHEMA_NAME,
    BATCH_SCHEMA_VERSION,
    load_coverage_manifest,
)


BATCH_APPROVAL_SCHEMA_NAME = "ausl-college-batch-approval"
BATCH_APPROVAL_SCHEMA_VERSION = 1
BATCH_APPROVAL_DECISION = "approved_for_college_resume_display"
BATCH_APPROVAL_SCOPE = "reviewed_minimal_college_resume_school_identity"
BATCH_APPROVED_ENVELOPE_NAME = "approved_envelope.json"
BATCH_APPROVAL_MANIFEST_NAME = "batch_approval_manifest.json"
BATCH_APPROVAL_SUMMARY_NAME = "batch_approval_summary.txt"

AGGREGATE_APPROVAL_SCHEMA_NAME = "ausl-college-aggregate-approval"
AGGREGATE_APPROVAL_SCHEMA_VERSION = 1
AGGREGATE_APPROVAL_DECISION = "approved_full_roster_college_resume_display"
AGGREGATE_APPROVAL_SCOPE = "phase7d_pilot_plus_independently_approved_phase7e_batches"
AGGREGATE_ENVELOPE_NAME = "college_resume_envelope.json"
AGGREGATE_MANIFEST_NAME = "college_aggregate_approval_manifest.json"
AGGREGATE_SUMMARY_NAME = "college_aggregate_approval_summary.txt"


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


def _review_timestamp(review_date: str) -> datetime:
    try:
        value = datetime.strptime(review_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("review_date must use YYYY-MM-DD") from exc
    return value.replace(tzinfo=timezone.utc)


def _sorted_ids(values: Iterable[str]) -> tuple[str, ...]:
    def key(value: str):
        return (0, int(value)) if value.isdigit() else (1, value.casefold(), value)

    return tuple(sorted(values, key=key))


def _player_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return _sorted_ids(resume.player_id for resume in envelope.resumes)


def _resume_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(sorted(resume.resume_id for resume in envelope.resumes))


def _source_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(sorted(source.source_id for source in envelope.sources))


def _candidate_ids(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(
        sorted(
            candidate.candidate_id
            for resume in envelope.resumes
            for record in resume.stat_records
            for candidate in record.candidates
        )
    )


def _incomplete_fields(envelope: CollegeEnvelope) -> tuple[str, ...]:
    return tuple(
        sorted(
            f"{resume.player_id}:{field}"
            for resume in envelope.resumes
            for field in assess_completeness(resume, envelope).missing_fields
        )
    )


def _completeness_totals(envelope: CollegeEnvelope) -> dict[str, int]:
    counts = Counter(
        assess_completeness(resume, envelope).state.value
        for resume in envelope.resumes
    )
    return {state.value: counts[state.value] for state in CompletenessState}


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
class ReviewBatchIdentity:
    batch_id: str
    coverage_manifest_id: str
    season: int
    player_ids: tuple[str, ...]
    display_names: tuple[str, ...]


def _load_review_batch_manifest(payload: bytes) -> ReviewBatchIdentity:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("review batch manifest is not valid UTF-8 JSON") from exc
    expected = {
        "schema_name",
        "schema_version",
        "batch_id",
        "coverage_manifest_id",
        "season",
        "generated_at",
        "mode",
        "players",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError("review batch manifest fields are missing or unknown")
    if raw["schema_name"] != BATCH_SCHEMA_NAME or raw["schema_version"] != BATCH_SCHEMA_VERSION:
        raise ValueError("review batch manifest schema is unsupported")
    if raw["mode"] != "developer_review":
        raise ValueError("review batch must be developer_review")
    if not isinstance(raw["players"], list) or not raw["players"]:
        raise ValueError("review batch players are required")
    player_ids = []
    names = []
    for player in raw["players"]:
        if not isinstance(player, dict) or set(player) != {"player_id", "display_name"}:
            raise ValueError("review batch player fields are missing or unknown")
        player_id = str(player["player_id"]).strip()
        name = str(player["display_name"]).strip()
        if not player_id or not name:
            raise ValueError("review batch player ID and display name are required")
        player_ids.append(player_id)
        names.append(name)
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("review batch contains duplicate player IDs")
    return ReviewBatchIdentity(
        batch_id=str(raw["batch_id"]),
        coverage_manifest_id=str(raw["coverage_manifest_id"]),
        season=int(raw["season"]),
        player_ids=tuple(player_ids),
        display_names=tuple(names),
    )


@dataclass(frozen=True)
class BatchApprovalManifest:
    approval_schema_name: str
    approval_schema_version: int
    batch_id: str
    coverage_manifest_id: str
    input_batch_manifest_sha256: str
    input_envelope_sha256: str
    approved_envelope_sha256: str
    player_ids: tuple[str, ...]
    resume_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    reviewer_role: str
    review_date: str
    decision: str
    review_scope: str
    incomplete_fields: tuple[str, ...]
    completeness_totals: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class BatchApprovalResult:
    approved_envelope_payload: bytes
    approval_manifest_payload: bytes
    summary_payload: bytes
    input_batch_manifest_sha256: str
    input_envelope_sha256: str
    approved_envelope_sha256: str


@dataclass(frozen=True)
class ApprovedBatchArtifact:
    envelope: CollegeEnvelope
    manifest: BatchApprovalManifest
    envelope_payload: bytes
    manifest_payload: bytes


_BATCH_APPROVAL_FIELDS = {
    "approval_schema_name",
    "approval_schema_version",
    "batch_id",
    "coverage_manifest_id",
    "input_batch_manifest_sha256",
    "input_envelope_sha256",
    "approved_envelope_sha256",
    "player_ids",
    "resume_ids",
    "source_ids",
    "candidate_ids",
    "reviewer_role",
    "review_date",
    "decision",
    "review_scope",
    "incomplete_fields",
    "completeness_totals",
}


def _batch_approval_from_mapping(raw: Mapping[str, Any]) -> BatchApprovalManifest:
    if set(raw) != _BATCH_APPROVAL_FIELDS:
        raise ValueError("batch approval manifest fields are missing or unknown")
    if raw["approval_schema_name"] != BATCH_APPROVAL_SCHEMA_NAME:
        raise ValueError("batch approval schema name is unsupported")
    if raw["approval_schema_version"] != BATCH_APPROVAL_SCHEMA_VERSION:
        raise ValueError("batch approval schema version is unsupported")
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("batch approval reviewer_role must be project_owner")
    _review_timestamp(raw["review_date"])
    if raw["decision"] != BATCH_APPROVAL_DECISION:
        raise ValueError("batch approval decision is unsupported")
    if raw["review_scope"] != BATCH_APPROVAL_SCOPE:
        raise ValueError("batch approval review scope is unsupported")
    for name in (
        "batch_id",
        "coverage_manifest_id",
        "input_batch_manifest_sha256",
        "input_envelope_sha256",
        "approved_envelope_sha256",
    ):
        if not isinstance(raw[name], str) or not raw[name]:
            raise ValueError(f"batch approval {name} is required")
    totals = raw["completeness_totals"]
    if not isinstance(totals, dict) or set(totals) != {
        state.value for state in CompletenessState
    }:
        raise ValueError("batch approval completeness totals are invalid")
    return BatchApprovalManifest(
        approval_schema_name=raw["approval_schema_name"],
        approval_schema_version=raw["approval_schema_version"],
        batch_id=raw["batch_id"],
        coverage_manifest_id=raw["coverage_manifest_id"],
        input_batch_manifest_sha256=raw["input_batch_manifest_sha256"],
        input_envelope_sha256=raw["input_envelope_sha256"],
        approved_envelope_sha256=raw["approved_envelope_sha256"],
        player_ids=_string_list(raw, "player_ids"),
        resume_ids=_string_list(raw, "resume_ids"),
        source_ids=_string_list(raw, "source_ids"),
        candidate_ids=_string_list(raw, "candidate_ids"),
        reviewer_role=raw["reviewer_role"],
        review_date=raw["review_date"],
        decision=raw["decision"],
        review_scope=raw["review_scope"],
        incomplete_fields=_string_list(raw, "incomplete_fields"),
        completeness_totals=tuple(sorted((str(k), int(v)) for k, v in totals.items())),
    )


def approve_batch_payloads(
    batch_manifest_payload: bytes,
    envelope_payload: bytes,
    *,
    expected_manifest_sha256: str,
    expected_envelope_sha256: str,
    reviewer_role: str,
    review_date: str,
    decision: str,
) -> BatchApprovalResult:
    manifest_hash = _sha(batch_manifest_payload)
    envelope_hash = _sha(envelope_payload)
    if manifest_hash != expected_manifest_sha256:
        raise ValueError("batch manifest hash does not match reviewed bytes")
    if envelope_hash != expected_envelope_sha256:
        raise ValueError("batch envelope hash does not match reviewed bytes")
    if reviewer_role != "project_owner":
        raise ValueError("reviewer_role must be project_owner")
    if decision != BATCH_APPROVAL_DECISION:
        raise ValueError("unsupported batch approval decision")
    reviewed_at = _review_timestamp(review_date)
    batch = _load_review_batch_manifest(batch_manifest_payload)
    envelope = load_envelope(envelope_payload)
    if _player_ids(envelope) != _sorted_ids(batch.player_ids):
        raise ValueError("batch envelope player IDs do not match reviewed batch manifest")
    names = {resume.player_id: resume.canonical_display_name for resume in envelope.resumes}
    if any(names[player_id].casefold() != name.casefold() for player_id, name in zip(batch.player_ids, batch.display_names)):
        raise ValueError("batch envelope names do not match exact reviewed identities")
    report = validate_envelope(envelope)
    structural = tuple(
        error for error in report.errors if not error.startswith("unresolved identity:")
    )
    if structural:
        raise ValueError("review batch failed Phase 7B validation")

    approved_resumes = []
    for resume in envelope.resumes:
        mappings = tuple(
            replace(
                mapping,
                review_state=IdentityReviewState.VERIFIED,
                reviewer=reviewer_role,
                reviewed_at=reviewed_at,
                evidence_reference=(
                    f"{BATCH_APPROVAL_SCHEMA_NAME}:{batch.batch_id}:"
                    f"{envelope_hash}:{mapping.mapping_id}"
                ),
            )
            for mapping in resume.identity_mappings
        )
        statuses = []
        for name, status in resume.section_statuses:
            if name == "identity":
                status = "verified"
            elif name == "programs" and resume.programs:
                status = "verified"
            statuses.append((name, status))
        approved_resumes.append(
            replace(resume, identity_mappings=mappings, section_statuses=tuple(statuses))
        )
    approved = replace(
        envelope,
        generated_at=reviewed_at,
        resumes=tuple(approved_resumes),
        validation_metadata=tuple(
            sorted(
                {
                    *envelope.validation_metadata,
                    ("approval_batch_id", batch.batch_id),
                    ("approval_decision", decision),
                    ("approval_input_envelope_sha256", envelope_hash),
                    ("approval_input_manifest_sha256", manifest_hash),
                    ("approval_review_date", review_date),
                    ("approval_reviewer_role", reviewer_role),
                }
            )
        ),
    )
    approved_report = validate_envelope(approved)
    if not approved_report.valid or approved_report.unresolved_identities:
        raise ValueError("approved batch failed post-review validation")
    approved_payload = serialize_envelope(approved)
    approved_hash = _sha(approved_payload)
    manifest = {
        "approval_schema_name": BATCH_APPROVAL_SCHEMA_NAME,
        "approval_schema_version": BATCH_APPROVAL_SCHEMA_VERSION,
        "batch_id": batch.batch_id,
        "coverage_manifest_id": batch.coverage_manifest_id,
        "input_batch_manifest_sha256": manifest_hash,
        "input_envelope_sha256": envelope_hash,
        "approved_envelope_sha256": approved_hash,
        "player_ids": list(_player_ids(approved)),
        "resume_ids": list(_resume_ids(approved)),
        "source_ids": list(_source_ids(approved)),
        "candidate_ids": list(_candidate_ids(approved)),
        "reviewer_role": reviewer_role,
        "review_date": review_date,
        "decision": decision,
        "review_scope": BATCH_APPROVAL_SCOPE,
        "incomplete_fields": list(_incomplete_fields(approved)),
        "completeness_totals": _completeness_totals(approved),
    }
    manifest_payload = _json_payload(manifest)
    summary = (
        f"AUSL Phase 7E Batch Approval\n"
        f"Batch: {batch.batch_id}\n"
        f"Review role: {reviewer_role}\n"
        f"Review date: {review_date}\n"
        f"Decision: {decision}\n"
        f"Input manifest SHA-256: {manifest_hash}\n"
        f"Input envelope SHA-256: {envelope_hash}\n"
        f"Approved envelope SHA-256: {approved_hash}\n"
        f"Exact player IDs: {', '.join(_player_ids(approved))}\n"
        f"Completeness: Partial={len(approved.resumes)}\n"
        f"Unavailable sections retained: statistics, achievements\n"
    ).encode("utf-8")
    result = BatchApprovalResult(
        approved_payload,
        manifest_payload,
        summary,
        manifest_hash,
        envelope_hash,
        approved_hash,
    )
    validate_batch_approval(approved_payload, manifest_payload)
    return result


def validate_batch_approval(
    envelope_payload: bytes,
    manifest_payload: bytes,
) -> ApprovedBatchArtifact:
    if b"\r" in manifest_payload or not manifest_payload.endswith(b"\n"):
        raise ValueError("batch approval manifest must use deterministic UTF-8/LF")
    try:
        raw = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("batch approval manifest is invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("batch approval manifest root must be an object")
    manifest = _batch_approval_from_mapping(raw)
    if _sha(envelope_payload) != manifest.approved_envelope_sha256:
        raise ValueError("approved batch envelope hash does not match manifest")
    envelope = load_envelope(envelope_payload)
    report = validate_envelope(envelope)
    if not report.valid or report.unresolved_identities:
        raise ValueError("approved batch envelope failed validation")
    if _player_ids(envelope) != manifest.player_ids:
        raise ValueError("approved batch player IDs do not match manifest")
    if _resume_ids(envelope) != manifest.resume_ids:
        raise ValueError("approved batch resume IDs do not match manifest")
    if _source_ids(envelope) != manifest.source_ids:
        raise ValueError("approved batch source IDs do not match manifest")
    if _candidate_ids(envelope) != manifest.candidate_ids:
        raise ValueError("approved batch candidate IDs do not match manifest")
    if _incomplete_fields(envelope) != manifest.incomplete_fields:
        raise ValueError("approved batch incomplete fields do not match manifest")
    if tuple(sorted(_completeness_totals(envelope).items())) != manifest.completeness_totals:
        raise ValueError("approved batch completeness totals do not match manifest")
    expected_time = _review_timestamp(manifest.review_date)
    for resume in envelope.resumes:
        for mapping in resume.identity_mappings:
            if (
                mapping.ausl_player_id != resume.player_id
                or mapping.review_state is not IdentityReviewState.VERIFIED
                or mapping.reviewer != manifest.reviewer_role
                or mapping.reviewed_at != expected_time
                or manifest.batch_id not in (mapping.evidence_reference or "")
                or manifest.input_envelope_sha256 not in (mapping.evidence_reference or "")
            ):
                raise ValueError("approved batch identity review does not match transaction")
    return ApprovedBatchArtifact(envelope, manifest, envelope_payload, manifest_payload)


@dataclass(frozen=True)
class AggregateBatchBinding:
    batch_id: str
    approval_manifest_sha256: str
    approved_envelope_sha256: str
    player_ids: tuple[str, ...]


@dataclass(frozen=True)
class AggregateApprovalManifest:
    approval_schema_name: str
    approval_schema_version: int
    college_schema_name: str
    college_schema_version: int
    completeness_profile: str
    coverage_manifest_id: str
    coverage_manifest_sha256: str
    pilot_approval_manifest_sha256: str
    approved_batches: tuple[AggregateBatchBinding, ...]
    approved_envelope_sha256: str
    player_ids: tuple[str, ...]
    resume_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    reviewer_role: str
    review_date: str
    decision: str
    review_scope: str
    incomplete_fields: tuple[str, ...]
    completeness_totals: tuple[tuple[str, int], ...]

    @property
    def approved_batch_ids(self) -> tuple[str, ...]:
        return tuple(binding.batch_id for binding in self.approved_batches)

    @property
    def batch_approval_manifest_sha256s(self) -> tuple[str, ...]:
        return tuple(binding.approval_manifest_sha256 for binding in self.approved_batches)


@dataclass(frozen=True)
class AggregateApprovalResult:
    envelope_payload: bytes
    manifest_payload: bytes
    summary_payload: bytes


@dataclass(frozen=True)
class ApprovedAggregateArtifact:
    envelope: CollegeEnvelope
    manifest: AggregateApprovalManifest
    envelope_payload: bytes
    manifest_payload: bytes


_AGGREGATE_FIELDS = {
    "approval_schema_name",
    "approval_schema_version",
    "college_schema_name",
    "college_schema_version",
    "completeness_profile",
    "coverage_manifest_id",
    "coverage_manifest_sha256",
    "pilot_approval_manifest_sha256",
    "approved_batches",
    "approved_envelope_sha256",
    "player_ids",
    "resume_ids",
    "source_ids",
    "candidate_ids",
    "reviewer_role",
    "review_date",
    "decision",
    "review_scope",
    "incomplete_fields",
    "completeness_totals",
}


def _aggregate_from_mapping(raw: Mapping[str, Any]) -> AggregateApprovalManifest:
    if set(raw) != _AGGREGATE_FIELDS:
        raise ValueError("aggregate approval manifest fields are missing or unknown")
    if raw["approval_schema_name"] != AGGREGATE_APPROVAL_SCHEMA_NAME:
        raise ValueError("aggregate approval schema name is unsupported")
    if raw["approval_schema_version"] != AGGREGATE_APPROVAL_SCHEMA_VERSION:
        raise ValueError("aggregate approval schema version is unsupported")
    if raw["reviewer_role"] != "project_owner":
        raise ValueError("aggregate approval reviewer role must be project_owner")
    _review_timestamp(raw["review_date"])
    if raw["decision"] != AGGREGATE_APPROVAL_DECISION:
        raise ValueError("aggregate approval decision is unsupported")
    if raw["review_scope"] != AGGREGATE_APPROVAL_SCOPE:
        raise ValueError("aggregate approval scope is unsupported")
    raw_bindings = raw["approved_batches"]
    if not isinstance(raw_bindings, list):
        raise ValueError("aggregate approved_batches must be a list")
    bindings = []
    for item in raw_bindings:
        if not isinstance(item, dict) or set(item) != {
            "batch_id",
            "approval_manifest_sha256",
            "approved_envelope_sha256",
            "player_ids",
        }:
            raise ValueError("aggregate batch binding fields are missing or unknown")
        bindings.append(
            AggregateBatchBinding(
                batch_id=str(item["batch_id"]),
                approval_manifest_sha256=str(item["approval_manifest_sha256"]),
                approved_envelope_sha256=str(item["approved_envelope_sha256"]),
                player_ids=_string_list(item, "player_ids"),
            )
        )
    if len({item.batch_id for item in bindings}) != len(bindings):
        raise ValueError("aggregate contains duplicate approved batch IDs")
    totals = raw["completeness_totals"]
    if not isinstance(totals, dict) or set(totals) != {
        state.value for state in CompletenessState
    }:
        raise ValueError("aggregate completeness totals are invalid")
    return AggregateApprovalManifest(
        approval_schema_name=raw["approval_schema_name"],
        approval_schema_version=raw["approval_schema_version"],
        college_schema_name=str(raw["college_schema_name"]),
        college_schema_version=int(raw["college_schema_version"]),
        completeness_profile=str(raw["completeness_profile"]),
        coverage_manifest_id=str(raw["coverage_manifest_id"]),
        coverage_manifest_sha256=str(raw["coverage_manifest_sha256"]),
        pilot_approval_manifest_sha256=str(raw["pilot_approval_manifest_sha256"]),
        approved_batches=tuple(bindings),
        approved_envelope_sha256=str(raw["approved_envelope_sha256"]),
        player_ids=_string_list(raw, "player_ids"),
        resume_ids=_string_list(raw, "resume_ids"),
        source_ids=_string_list(raw, "source_ids"),
        candidate_ids=_string_list(raw, "candidate_ids"),
        reviewer_role=raw["reviewer_role"],
        review_date=raw["review_date"],
        decision=raw["decision"],
        review_scope=raw["review_scope"],
        incomplete_fields=_string_list(raw, "incomplete_fields"),
        completeness_totals=tuple(sorted((str(k), int(v)) for k, v in totals.items())),
    )


def build_approved_aggregate(
    *,
    coverage_payload: bytes,
    pilot_artifact: ApprovedCollegeArtifact,
    batch_results: tuple[BatchApprovalResult, ...],
    reviewer_role: str,
    review_date: str,
) -> AggregateApprovalResult:
    if reviewer_role != "project_owner":
        raise ValueError("reviewer_role must be project_owner")
    reviewed_at = _review_timestamp(review_date)
    coverage = load_coverage_manifest(coverage_payload)
    artifacts = tuple(
        validate_batch_approval(
            result.approved_envelope_payload, result.approval_manifest_payload
        )
        for result in batch_results
    )
    bindings = tuple(
        AggregateBatchBinding(
            batch_id=artifact.manifest.batch_id,
            approval_manifest_sha256=_sha(artifact.manifest_payload),
            approved_envelope_sha256=_sha(artifact.envelope_payload),
            player_ids=artifact.manifest.player_ids,
        )
        for artifact in sorted(artifacts, key=lambda item: item.manifest.batch_id)
    )
    approved_batch_players = {
        player_id for binding in bindings for player_id in binding.player_ids
    }
    pilot_players = set(_player_ids(pilot_artifact.envelope))
    coverage_players = {entry.player_id for entry in coverage.entries}
    if approved_batch_players & pilot_players:
        raise ValueError("approved batch overlaps the Phase 7D pilot")
    if approved_batch_players | pilot_players != coverage_players:
        raise ValueError("approved batch set does not exactly cover roster coverage")
    if len(approved_batch_players) != sum(len(item.player_ids) for item in bindings):
        raise ValueError("approved batches contain duplicate exact player IDs")

    resumes = tuple(
        sorted(
            (
                *pilot_artifact.envelope.resumes,
                *(resume for artifact in artifacts for resume in artifact.envelope.resumes),
            ),
            key=lambda item: (0, int(item.player_id)) if item.player_id.isdigit() else (1, item.player_id),
        )
    )
    sources = tuple(
        sorted(
            (
                *pilot_artifact.envelope.sources,
                *(source for artifact in artifacts for source in artifact.envelope.sources),
            ),
            key=lambda item: item.source_id,
        )
    )
    if len({resume.resume_id for resume in resumes}) != len(resumes):
        raise ValueError("aggregate contains duplicate resume IDs")
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("aggregate contains duplicate source IDs")
    envelope = CollegeEnvelope(
        generated_at=reviewed_at,
        completeness_profile=pilot_artifact.envelope.completeness_profile,
        resumes=resumes,
        sources=sources,
        validation_metadata=(
            ("aggregate_approval", AGGREGATE_APPROVAL_DECISION),
            ("aggregate_review_date", review_date),
            ("aggregate_reviewer_role", reviewer_role),
            ("approved_batch_count", str(len(bindings))),
            ("coverage_manifest_id", coverage.manifest_id),
            ("phase7d_pilot_preserved", "true"),
        ),
    )
    report = validate_envelope(envelope)
    if not report.valid or report.unresolved_identities:
        raise ValueError("approved aggregate failed Phase 7B validation")
    envelope_payload = serialize_envelope(envelope)
    manifest = {
        "approval_schema_name": AGGREGATE_APPROVAL_SCHEMA_NAME,
        "approval_schema_version": AGGREGATE_APPROVAL_SCHEMA_VERSION,
        "college_schema_name": envelope.schema_name,
        "college_schema_version": envelope.schema_version,
        "completeness_profile": envelope.completeness_profile,
        "coverage_manifest_id": coverage.manifest_id,
        "coverage_manifest_sha256": _sha(coverage_payload),
        "pilot_approval_manifest_sha256": _sha(pilot_artifact.manifest_payload),
        "approved_batches": [
            {
                "batch_id": binding.batch_id,
                "approval_manifest_sha256": binding.approval_manifest_sha256,
                "approved_envelope_sha256": binding.approved_envelope_sha256,
                "player_ids": list(binding.player_ids),
            }
            for binding in bindings
        ],
        "approved_envelope_sha256": _sha(envelope_payload),
        "player_ids": list(_player_ids(envelope)),
        "resume_ids": list(_resume_ids(envelope)),
        "source_ids": list(_source_ids(envelope)),
        "candidate_ids": list(_candidate_ids(envelope)),
        "reviewer_role": reviewer_role,
        "review_date": review_date,
        "decision": AGGREGATE_APPROVAL_DECISION,
        "review_scope": AGGREGATE_APPROVAL_SCOPE,
        "incomplete_fields": list(_incomplete_fields(envelope)),
        "completeness_totals": _completeness_totals(envelope),
    }
    manifest_payload = _json_payload(manifest)
    totals = _completeness_totals(envelope)
    summary = (
        "AUSL Phase 7E Full-Roster College Approval\n"
        f"Review role: {reviewer_role}\n"
        f"Review date: {review_date}\n"
        f"Exact player IDs: {len(envelope.resumes)}\n"
        f"Approved batches: {len(bindings)}\n"
        f"Completeness: Verified={totals['Verified']}, Partial={totals['Partial']}, Needs Review={totals['Needs Review']}\n"
        "Connection approval: absent\n"
    ).encode("utf-8")
    result = AggregateApprovalResult(envelope_payload, manifest_payload, summary)
    validate_aggregate_approval(result.envelope_payload, result.manifest_payload)
    return result


def validate_aggregate_approval(
    envelope_payload: bytes,
    manifest_payload: bytes,
    *,
    coverage_payload: bytes | None = None,
    pilot_artifact: ApprovedCollegeArtifact | None = None,
    batch_approval_payloads: tuple[bytes, ...] | None = None,
) -> ApprovedAggregateArtifact:
    if b"\r" in manifest_payload or not manifest_payload.endswith(b"\n"):
        raise ValueError("aggregate approval manifest must use deterministic UTF-8/LF")
    try:
        raw = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("aggregate approval manifest is invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("aggregate approval root must be an object")
    manifest = _aggregate_from_mapping(raw)
    if _sha(envelope_payload) != manifest.approved_envelope_sha256:
        raise ValueError("aggregate envelope hash does not match approval manifest")
    envelope = load_envelope(envelope_payload)
    report = validate_envelope(envelope)
    if not report.valid or report.unresolved_identities:
        raise ValueError("aggregate envelope failed validation")
    if envelope.schema_name != manifest.college_schema_name or envelope.schema_version != manifest.college_schema_version:
        raise ValueError("aggregate college schema does not match manifest")
    if envelope.completeness_profile != manifest.completeness_profile:
        raise ValueError("aggregate completeness profile does not match manifest")
    if _player_ids(envelope) != manifest.player_ids:
        raise ValueError("aggregate player IDs do not match manifest")
    if _resume_ids(envelope) != manifest.resume_ids:
        raise ValueError("aggregate resume IDs do not match manifest")
    if _source_ids(envelope) != manifest.source_ids:
        raise ValueError("aggregate source IDs do not match manifest")
    if _candidate_ids(envelope) != manifest.candidate_ids:
        raise ValueError("aggregate candidate IDs do not match manifest")
    if _incomplete_fields(envelope) != manifest.incomplete_fields:
        raise ValueError("aggregate incomplete fields do not match manifest")
    if tuple(sorted(_completeness_totals(envelope).items())) != manifest.completeness_totals:
        raise ValueError("aggregate completeness totals do not match manifest")
    for resume in envelope.resumes:
        if not resume.identity_mappings or any(
            mapping.ausl_player_id != resume.player_id
            or mapping.review_state is not IdentityReviewState.VERIFIED
            or mapping.reviewer != "project_owner"
            or mapping.reviewed_at is None
            or not mapping.evidence_reference
            for mapping in resume.identity_mappings
        ):
            raise ValueError("aggregate contains an unapproved exact identity")
    if coverage_payload is not None:
        coverage = load_coverage_manifest(coverage_payload)
        if _sha(coverage_payload) != manifest.coverage_manifest_sha256:
            raise ValueError("coverage manifest hash does not match aggregate approval")
        if coverage.manifest_id != manifest.coverage_manifest_id:
            raise ValueError("coverage manifest identity does not match aggregate approval")
        if {entry.player_id for entry in coverage.entries} != set(manifest.player_ids):
            raise ValueError("coverage player IDs do not match aggregate approval")
    if pilot_artifact is not None and _sha(pilot_artifact.manifest_payload) != manifest.pilot_approval_manifest_sha256:
        raise ValueError("Phase 7D pilot approval does not match aggregate approval")
    if batch_approval_payloads is not None:
        actual = {_sha(payload) for payload in batch_approval_payloads}
        expected = set(manifest.batch_approval_manifest_sha256s)
        if actual != expected:
            raise ValueError("batch approval set does not match aggregate approval")
    return ApprovedAggregateArtifact(envelope, manifest, envelope_payload, manifest_payload)


def load_aggregate_approval(directory: Path | str) -> ApprovedAggregateArtifact:
    root = Path(directory)
    return validate_aggregate_approval(
        (root / AGGREGATE_ENVELOPE_NAME).read_bytes(),
        (root / AGGREGATE_MANIFEST_NAME).read_bytes(),
    )

