from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ausl_college import CompletenessState, assess_completeness
from ausl_college_approval import load_checked_in_approval
from ausl_college_batch_approval import (
    BATCH_APPROVAL_DECISION,
    approve_batch_payloads,
    build_approved_aggregate,
    validate_aggregate_approval,
    validate_batch_approval,
)
from ausl_college_scale import load_coverage_manifest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "college_review" / "phase7e"


def _batch(batch_id="phase7e-2026-batch-01"):
    root = REVIEW / "batches" / batch_id
    manifest = (root / "batch_manifest.json").read_bytes()
    envelope = (root / "developer_review_envelope.json").read_bytes()
    return manifest, envelope


def _approved_batch(batch_id="phase7e-2026-batch-01"):
    manifest, envelope = _batch(batch_id)
    result = approve_batch_payloads(
        manifest,
        envelope,
        expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        expected_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        reviewer_role="project_owner",
        review_date="2026-08-12",
        decision=BATCH_APPROVAL_DECISION,
    )
    return manifest, envelope, result


def test_batch_approval_binds_exact_inputs_and_owner_decision():
    manifest, envelope, result = _approved_batch()
    approval = json.loads(result.approval_manifest_payload)

    assert approval["batch_id"] == "phase7e-2026-batch-01"
    assert approval["input_batch_manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    assert approval["input_envelope_sha256"] == hashlib.sha256(envelope).hexdigest()
    assert approval["reviewer_role"] == "project_owner"
    assert approval["review_date"] == "2026-08-12"
    assert approval["decision"] == BATCH_APPROVAL_DECISION
    assert len(approval["player_ids"]) == 10
    assert approval["completeness_totals"] == {
        "Needs Review": 0,
        "Partial": 10,
        "Verified": 0,
    }


def test_batch_approval_marks_identity_and_school_reviewed_but_keeps_missing_fields():
    _manifest, _envelope, result = _approved_batch()
    artifact = validate_batch_approval(
        result.approved_envelope_payload,
        result.approval_manifest_payload,
    )

    for resume in artifact.envelope.resumes:
        assessment = assess_completeness(resume, artifact.envelope)
        assert assessment.state is CompletenessState.PARTIAL
        assert assessment.missing_fields == (
            "sections.statistics",
            "sections.achievements",
        )
        assert dict(resume.section_statuses)["identity"] == "verified"
        assert dict(resume.section_statuses)["programs"] == "verified"
        assert all(mapping.reviewer == "project_owner" for mapping in resume.identity_mappings)
        assert all(mapping.reviewed_at is not None for mapping in resume.identity_mappings)
        assert resume.stat_records == ()
        assert resume.achievements == ()


def test_tampering_or_incomplete_review_contract_fails_closed():
    _manifest, _envelope, result = _approved_batch()
    changed = bytearray(result.approved_envelope_payload)
    changed[-2] = ord(" ")
    with pytest.raises(ValueError, match="hash"):
        validate_batch_approval(bytes(changed), result.approval_manifest_payload)

    approval = json.loads(result.approval_manifest_payload)
    approval["player_ids"] = approval["player_ids"][:-1]
    changed_manifest = (
        json.dumps(approval, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    with pytest.raises(ValueError, match="player"):
        validate_batch_approval(result.approved_envelope_payload, changed_manifest)

    manifest, envelope = _batch()
    with pytest.raises(ValueError, match="reviewer_role"):
        approve_batch_payloads(
            manifest,
            envelope,
            expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
            expected_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            reviewer_role="producer",
            review_date="2026-08-12",
            decision=BATCH_APPROVAL_DECISION,
        )

def test_batch_approval_is_deterministic_and_does_not_mutate_review_inputs():
    manifest, envelope, first = _approved_batch()
    _manifest, _envelope, second = _approved_batch()

    assert first == second
    assert _batch() == (manifest, envelope)


def test_aggregate_contains_exact_current_roster_once_and_only_approved_batches():
    coverage_payload = (REVIEW / "roster_coverage_manifest.json").read_bytes()
    coverage = load_coverage_manifest(coverage_payload)
    pilot = load_checked_in_approval(ROOT / "data" / "college_approved")
    batch_results = []
    for batch_dir in sorted((REVIEW / "batches").iterdir()):
        manifest = (batch_dir / "batch_manifest.json").read_bytes()
        envelope = (batch_dir / "developer_review_envelope.json").read_bytes()
        batch_results.append(
            approve_batch_payloads(
                manifest,
                envelope,
                expected_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                expected_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
                reviewer_role="project_owner",
                review_date="2026-08-12",
                decision=BATCH_APPROVAL_DECISION,
            )
        )

    aggregate = build_approved_aggregate(
        coverage_payload=coverage_payload,
        pilot_artifact=pilot,
        batch_results=tuple(batch_results),
        reviewer_role="project_owner",
        review_date="2026-08-12",
    )
    artifact = validate_aggregate_approval(
        aggregate.envelope_payload,
        aggregate.manifest_payload,
        coverage_payload=coverage_payload,
        pilot_artifact=pilot,
        batch_approval_payloads=tuple(
            result.approval_manifest_payload for result in batch_results
        ),
    )

    player_ids = tuple(resume.player_id for resume in artifact.envelope.resumes)
    assert len(player_ids) == len(set(player_ids)) == 118
    assert set(player_ids) == {entry.player_id for entry in coverage.entries}
    totals = dict(artifact.manifest.completeness_totals)
    assert totals == {"Needs Review": 0, "Partial": 109, "Verified": 9}
    assert len(artifact.manifest.approved_batch_ids) == 11

    with pytest.raises(ValueError, match="coverage"):
        build_approved_aggregate(
            coverage_payload=coverage_payload,
            pilot_artifact=pilot,
            batch_results=tuple(batch_results[:-1]),
            reviewer_role="project_owner",
            review_date="2026-08-12",
        )
