from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ausl_college import CompletenessState, assess_completeness, load_envelope
from ausl_college_approval import (
    APPROVAL_DECISION,
    PILOT_PLAYER_IDS,
    approve_pilot_payload,
    validate_approved_payload,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data" / "college_pilot" / "pilot_envelope.json"


def _approved():
    payload = PILOT.read_bytes()
    return payload, approve_pilot_payload(
        payload,
        expected_input_sha256=hashlib.sha256(payload).hexdigest(),
        reviewer_role="project_owner",
        review_date="2026-08-11",
        decision=APPROVAL_DECISION,
    )


def test_project_owner_review_binds_exact_pilot_without_claiming_producer_review():
    original, result = _approved()
    manifest = json.loads(result.manifest_payload)

    assert manifest["input_envelope_sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["player_ids"] == list(PILOT_PLAYER_IDS)
    assert manifest["reviewer_role"] == "project_owner"
    assert manifest["review_date"] == "2026-08-11"
    assert manifest["decision"] == APPROVAL_DECISION
    assert "producer" not in manifest["reviewer_role"]
    assert PILOT.read_bytes() == original


def test_derived_envelope_validates_and_keeps_incomplete_fields_incomplete():
    _original, result = _approved()
    validated = validate_approved_payload(
        result.envelope_payload, result.manifest_payload
    )
    assessments = {
        resume.player_id: assess_completeness(resume, validated.envelope)
        for resume in validated.envelope.resumes
    }

    assert sum(item.state is CompletenessState.VERIFIED for item in assessments.values()) == 9
    assert assessments["1322"].state is CompletenessState.PARTIAL
    assert assessments["1322"].missing_fields == ("sections.achievements",)
    assert "1322:sections.achievements" in validated.manifest.incomplete_fields


def test_altered_approved_envelope_or_player_set_invalidates_transaction():
    _original, result = _approved()
    changed = bytearray(result.envelope_payload)
    changed[-2] = ord(" ")
    with pytest.raises(ValueError, match="hash"):
        validate_approved_payload(bytes(changed), result.manifest_payload)

    manifest = json.loads(result.manifest_payload)
    manifest["player_ids"] = manifest["player_ids"][:-1]
    altered_manifest = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with pytest.raises(ValueError, match="player"):
        validate_approved_payload(result.envelope_payload, altered_manifest)


def test_missing_or_future_review_contract_fails_closed():
    _original, result = _approved()
    manifest = json.loads(result.manifest_payload)
    del manifest["review_scope"]
    with pytest.raises(ValueError, match="fields"):
        validate_approved_payload(
            result.envelope_payload,
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )

    manifest = json.loads(result.manifest_payload)
    manifest["approval_schema_version"] = 2
    with pytest.raises(ValueError, match="version"):
        validate_approved_payload(
            result.envelope_payload,
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )


def test_every_approved_identity_is_exact_and_reviewed():
    _original, result = _approved()
    envelope = load_envelope(result.envelope_payload)
    assert {resume.player_id for resume in envelope.resumes} == set(PILOT_PLAYER_IDS)
    for resume in envelope.resumes:
        assert resume.identity_mappings
        for mapping in resume.identity_mappings:
            assert mapping.ausl_player_id == resume.player_id
            assert mapping.review_state.value == "verified"
            assert mapping.reviewer == "project_owner"
            assert mapping.reviewed_at is not None

