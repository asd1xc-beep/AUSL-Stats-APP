from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from ausl_changes import ChangeComparisonContext, build_snapshot_digest, compare_snapshot_digests
from ausl_rundown import ReconciliationState, RundownSession
from ausl_session import SessionSnapshot, session_from_dict, session_to_json_bytes
from test_phase7e_connection_facts import (
    _college,
    _connections,
    _database,
    _game,
)
from ausl_facts import build_college_connection_facts


NOW = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)


def _fact():
    return build_college_connection_facts(
        _database(),
        _game(),
        college_artifact=_college(),
        connection_approval=_connections(),
    )[0]


def test_connection_fact_pins_marks_used_and_restores_exact_evidence_version():
    fact = _fact()
    rundown = RundownSession()
    pinned = rundown.pin_fact("2042", fact, now=NOW)
    used = rundown.mark_entry_used(
        "2042", pinned.active_entries[0].entry_id, now=NOW
    )
    snapshot = replace(SessionSnapshot.new(), rundown_states=rundown.states)

    restored = session_from_dict(json.loads(session_to_json_bytes(snapshot)))
    restored_record = restored.rundown_states[0].used_history[0]

    assert restored_record.fact_snapshot.fact_id == fact.fact_id
    assert restored_record.fact_snapshot.evidence_hash == fact.evidence_hash
    assert restored_record.fact_snapshot.air_copy == fact.air_copy
    assert len(restored_record.fact_snapshot.provenance) == len(fact.provenance)


def test_changed_connection_evidence_invalidates_pinned_snapshot():
    fact = _fact()
    rundown = RundownSession()
    state = rundown.pin_fact("2042", fact, now=NOW)
    changed = replace(fact, air_copy=fact.air_copy + " Updated.")

    reconciled = rundown.reconcile("2042", (changed,), now=NOW)
    entry = reconciled.active_entries[0]

    assert entry.reconciliation_state is ReconciliationState.SOURCE_CHANGED
    assert entry.fact_snapshot.evidence_hash == fact.evidence_hash
    assert entry.latest_fact.evidence_hash == changed.evidence_hash


def test_what_changed_reports_connection_evidence_update_without_identity_loss():
    fact = _fact()
    changed = replace(fact, air_copy=fact.air_copy + " Updated.")
    before = build_snapshot_digest(_database(), facts=(fact,))
    after = build_snapshot_digest(_database(), facts=(changed,))

    comparison = compare_snapshot_digests(
        before,
        after,
        context=ChangeComparisonContext(selected_game_id="2042"),
        detected_at=NOW,
    )

    event = next(item for item in comparison.events if item.fact_id == fact.fact_id)
    assert "fact" in event.category
    assert event.before_evidence_hash == fact.evidence_hash
    assert event.after_evidence_hash == changed.evidence_hash
