from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ausl_college_connection_approval import (
    CONNECTION_APPROVAL_DECISION,
    APPROVED_CONNECTION_ARTIFACT_NAME,
    CONNECTION_APPROVAL_MANIFEST_NAME,
    approve_connection_files,
    approve_connection_payload,
    load_checked_in_connection_approval,
    validate_connection_approval,
)
from ausl_college_connections import (
    ConnectionApprovalState,
    load_connection_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "college_review" / "phase7e" / "connections"


def _input_payload() -> bytes:
    return (REVIEW / "connection_candidates.json").read_bytes()


def _decisions(payload: bytes | None = None, **changes) -> bytes:
    candidate_payload = payload or _input_payload()
    result = load_connection_artifact(candidate_payload)
    value = {
        "schema_name": "ausl-college-connection-review-decisions",
        "schema_version": 1,
        "candidate_artifact_sha256": hashlib.sha256(candidate_payload).hexdigest(),
        "reviewer_role": "project_owner",
        "review_date": "2026-08-12",
        "review_note": "All eight exact connection wordings were double-checked and correct.",
        "decisions": [
            {
                "connection_id": item.connection_id,
                "evidence_version_hash": item.evidence_version_hash,
                "decision": CONNECTION_APPROVAL_DECISION,
            }
            for item in result.candidates
        ],
    }
    value.update(changes)
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def test_exact_review_decision_approves_all_eight_and_binds_semantic_fields():
    result = approve_connection_payload(_input_payload(), _decisions())
    artifact = validate_connection_approval(
        result.approved_payload,
        result.manifest_payload,
        original_candidate_payload=_input_payload(),
    )

    assert len(artifact.connections.candidates) == 8
    assert artifact.connections.suppressions == ()
    assert all(
        item.approval_state is ConnectionApprovalState.APPROVED
        and item.air_ready
        for item in artifact.connections.candidates
    )
    assert len(artifact.manifest.bindings) == 8
    for candidate, binding in zip(
        artifact.connections.candidates, artifact.manifest.bindings, strict=True
    ):
        assert binding.connection_id == candidate.connection_id
        assert binding.connection_type == candidate.connection_type.value
        assert binding.player_ids == candidate.subject_player_ids
        assert binding.program_ids == candidate.program_ids
        assert binding.season_scope == candidate.season_scope
        assert binding.wording == candidate.wording
        assert binding.source_ids == candidate.evidence_source_ids
        assert binding.approved_evidence_version_hash == candidate.evidence_version_hash


def test_approval_is_deterministic_and_does_not_modify_review_artifact():
    original = _input_payload()
    first = approve_connection_payload(original, _decisions(original))
    second = approve_connection_payload(original, _decisions(original))

    assert first.approved_payload == second.approved_payload
    assert first.manifest_payload == second.manifest_payload
    assert first.summary_payload == second.summary_payload
    assert _input_payload() == original


@pytest.mark.parametrize("mutation", ["wording", "evidence", "missing", "extra"])
def test_stale_or_incomplete_decision_set_fails_closed(mutation):
    raw = json.loads(_decisions().decode("utf-8"))
    if mutation == "wording":
        raw["candidate_artifact_sha256"] = "0" * 64
    elif mutation == "evidence":
        raw["decisions"][0]["evidence_version_hash"] = "0" * 64
    elif mutation == "missing":
        raw["decisions"].pop()
    else:
        raw["decisions"].append(
            {
                "connection_id": "unknown",
                "evidence_version_hash": "0" * 64,
                "decision": CONNECTION_APPROVAL_DECISION,
            }
        )
    decisions = (
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")

    with pytest.raises(ValueError):
        approve_connection_payload(_input_payload(), decisions)


def test_non_owner_or_unapproved_decision_cannot_create_approval():
    raw = json.loads(_decisions().decode("utf-8"))
    raw["reviewer_role"] = "automation"
    decisions = (json.dumps(raw, sort_keys=True) + "\n").encode()
    with pytest.raises(ValueError, match="project_owner"):
        approve_connection_payload(_input_payload(), decisions)

    raw = json.loads(_decisions().decode("utf-8"))
    raw["decisions"][0]["decision"] = "rejected"
    decisions = (json.dumps(raw, sort_keys=True) + "\n").encode()
    with pytest.raises(ValueError, match="not approved"):
        approve_connection_payload(_input_payload(), decisions)


def test_tampered_approved_wording_or_manifest_is_rejected():
    result = approve_connection_payload(_input_payload(), _decisions())
    raw = json.loads(result.approved_payload.decode("utf-8"))
    raw["candidates"][0]["wording"] += " Changed"
    changed = (
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    with pytest.raises(ValueError):
        validate_connection_approval(changed, result.manifest_payload)

    manifest = bytearray(result.manifest_payload)
    manifest[-3] = ord("x")
    with pytest.raises(ValueError):
        validate_connection_approval(result.approved_payload, bytes(manifest))


def test_atomic_failure_preserves_last_known_good(tmp_path):
    output = tmp_path / "approved"
    output.mkdir()
    old_artifact = b"old artifact\n"
    old_manifest = b"old manifest\n"
    (output / APPROVED_CONNECTION_ARTIFACT_NAME).write_bytes(old_artifact)
    (output / CONNECTION_APPROVAL_MANIFEST_NAME).write_bytes(old_manifest)
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("forced promotion failure")
        Path(destination).write_bytes(Path(source).read_bytes())
        Path(source).unlink()

    with pytest.raises(OSError, match="forced promotion failure"):
        approve_connection_files(
            REVIEW / "connection_candidates.json",
            tmp_path / "decisions.json",
            output,
            decisions_payload=_decisions(),
            replace_func=fail_second,
        )

    assert (output / APPROVED_CONNECTION_ARTIFACT_NAME).read_bytes() == old_artifact
    assert (output / CONNECTION_APPROVAL_MANIFEST_NAME).read_bytes() == old_manifest


def test_checked_in_connection_approval_covers_exact_reviewed_versions():
    artifact = load_checked_in_connection_approval(
        ROOT / "data" / "college_connections_approved"
    )
    assert len(artifact.connections.candidates) == 8
    assert all(item.air_ready for item in artifact.connections.candidates)
