from __future__ import annotations

from pathlib import Path

from ausl_college_connections import (
    ConnectionApprovalState,
    ConnectionType,
    load_connection_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
CONNECTIONS = ROOT / "data" / "college_review" / "phase7e" / "connections"


def test_checked_in_connection_candidates_are_exact_and_unapproved():
    result = load_connection_artifact(
        (CONNECTIONS / "connection_candidates.json").read_bytes()
    )
    counts = {}
    for candidate in result.candidates:
        counts[candidate.connection_type] = counts.get(candidate.connection_type, 0) + 1
        assert candidate.approval_state is ConnectionApprovalState.UNREVIEWED
        assert not candidate.air_ready
        assert candidate.evidence_source_ids
        assert candidate.evidence_record_ids
        assert candidate.evidence_version_hash

    assert counts == {
        ConnectionType.CHAMPIONSHIP_TEAMMATES: 1,
        ConnectionType.SHARED_AWARD: 1,
        ConnectionType.SHARED_PROGRAM: 2,
        ConnectionType.TRANSFER: 4,
    }
    assert len({item.connection_id for item in result.candidates}) == 8


def test_connection_packet_is_reviewable_and_does_not_claim_air_readiness():
    text = (CONNECTIONS / "connection_review_packet.md").read_text(encoding="utf-8")
    assert "CONNECTION ENGINE COMPLETE — CONNECTION REVIEW PENDING" in text
    assert "Candidate connections: 8" in text
    assert "Project-owner decision: PENDING" in text
    assert "air-ready" not in text.casefold()
    assert "Tiare Jennings" in text and "Kelly Maxwell" in text
    assert "Korbe Otis" in text
    assert "Valerie Cagle" in text and "NiJaree Canady" in text
    assert "Suppressed relationship summary" in text
