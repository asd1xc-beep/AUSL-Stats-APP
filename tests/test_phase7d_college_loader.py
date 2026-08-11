from __future__ import annotations

import hashlib
from pathlib import Path

from ausl_college_approval import APPROVAL_DECISION, approve_pilot_payload
from ausl_college_store import CollegeDataMode, CollegeStore


ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> CollegeStore:
    pilot = ROOT / "data" / "college_pilot" / "pilot_envelope.json"
    payload = pilot.read_bytes()
    approved = approve_pilot_payload(
        payload,
        expected_input_sha256=hashlib.sha256(payload).hexdigest(),
        reviewer_role="project_owner",
        review_date="2026-08-11",
        decision=APPROVAL_DECISION,
    )
    approved_dir = tmp_path / "approved"
    approved_dir.mkdir()
    (approved_dir / "college_resume_envelope.json").write_bytes(approved.envelope_payload)
    (approved_dir / "college_approval_manifest.json").write_bytes(approved.manifest_payload)
    return CollegeStore(approved_directories=(approved_dir,), developer_pilot_path=pilot)


def test_core_only_loads_no_college_data(tmp_path):
    loaded = _store(tmp_path).load(CollegeDataMode.CORE_ONLY)
    assert not loaded.available
    assert loaded.envelope is None
    assert "CORE ONLY" in loaded.message


def test_producer_mode_loads_only_hash_validated_approved_data(tmp_path):
    store = _store(tmp_path)
    loaded = store.load(CollegeDataMode.PRODUCER_APPROVED)
    assert loaded.available and loaded.copy_allowed
    assert len(loaded.envelope.resumes) == 10
    assert loaded.warning == ""


def test_developer_review_is_visible_and_never_copyable(tmp_path):
    loaded = _store(tmp_path).load(CollegeDataMode.DEVELOPER_REVIEW)
    assert loaded.available
    assert not loaded.copy_allowed
    assert "DEVELOPER REVIEW" in loaded.warning
    assert "NOT AIR READY" in loaded.warning


def test_invalid_approved_data_never_falls_back_to_developer_review(tmp_path):
    store = _store(tmp_path)
    manifest = store.approved_directories[0] / "college_approval_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    loaded = store.load(CollegeDataMode.PRODUCER_APPROVED)
    assert not loaded.available
    assert loaded.envelope is None
    assert "approval" in loaded.message.casefold()


def test_last_known_good_survives_failed_replacement(tmp_path):
    store = _store(tmp_path)
    first = store.load(CollegeDataMode.PRODUCER_APPROVED)
    envelope_path = store.approved_directories[0] / "college_resume_envelope.json"
    envelope_path.write_text("{}\n", encoding="utf-8")
    second = store.load(CollegeDataMode.PRODUCER_APPROVED)
    assert first.available and second.available
    assert second.envelope is first.envelope
    assert "last-known-good" in second.warning


def test_loader_does_not_use_network(monkeypatch, tmp_path):
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    assert _store(tmp_path).load(CollegeDataMode.PRODUCER_APPROVED).available

