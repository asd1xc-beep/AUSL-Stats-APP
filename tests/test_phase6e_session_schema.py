from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from ausl_changes import ChangeComparisonContext, compare_snapshot_digests
from ausl_session import (
    SESSION_SCHEMA_VERSION,
    ComparisonHistorySummary,
    RefreshComparisonMetadata,
    SessionChangeState,
    session_from_json_bytes,
    session_to_json_bytes,
)
from test_phase6e_changes import NOW, _digest, _roster
from test_phase6d_session_schema import populated_snapshot


def _state():
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))
    comparison = compare_snapshot_digests(
        before,
        after,
        context=ChangeComparisonContext(selected_game_id="1042"),
        detected_at=NOW,
    )
    event_id = comparison.events[0].event_id
    return SessionChangeState(
        baseline=after,
        latest_comparison=comparison,
        acknowledged_event_ids=(event_id,),
        recent_history=(
            ComparisonHistorySummary.from_comparison(comparison),
        ),
        refresh_metadata=RefreshComparisonMetadata(
            state="success",
            completed_at=NOW.isoformat(),
            affected_source="official_core_sources",
            error_summary="",
        ),
    )


def test_v1_session_migrates_to_v2_without_losing_phase6d_state():
    original = populated_snapshot()
    payload = json.loads(session_to_json_bytes(original))
    payload["schema_version"] = 1
    payload.pop("change_state", None)
    payload["ui_state"].pop("what_changed_filter", None)
    payload["ui_state"].pop("what_changed_team_filter", None)
    payload["ui_state"].pop("what_changed_category_filter", None)
    payload["ui_state"].pop("what_changed_scroll_fraction", None)

    restored = session_from_json_bytes(json.dumps(payload).encode("utf-8"))

    assert SESSION_SCHEMA_VERSION == 2
    assert restored.schema_version == 2
    assert restored.selected_game == original.selected_game
    assert restored.rundown_states == original.rundown_states
    assert restored.ui_state.fact_status_filter == original.ui_state.fact_status_filter
    assert restored.change_state == SessionChangeState()


def test_change_baseline_result_acknowledgements_and_refresh_metadata_round_trip():
    original = replace(populated_snapshot(), change_state=_state())

    restored = session_from_json_bytes(session_to_json_bytes(original))

    assert restored == original
    assert restored.change_state.baseline.snapshot_id == original.change_state.baseline.snapshot_id
    assert restored.change_state.latest_comparison.events[0].severity.value == "attention"
    assert restored.change_state.acknowledged_event_ids
    assert restored.change_state.refresh_metadata.state == "success"


def test_corrupt_change_feed_recovers_existing_session_instead_of_losing_rundown():
    original = populated_snapshot()
    payload = json.loads(session_to_json_bytes(original))
    payload["change_state"] = {
        "baseline": {"schema_version": 999},
        "latest_comparison": "corrupt",
    }

    restored = session_from_json_bytes(json.dumps(payload).encode("utf-8"))

    assert restored.rundown_states == original.rundown_states
    assert restored.selected_game == original.selected_game
    assert restored.change_state.baseline is None
    assert "unavailable" in restored.change_state.recovery_warning.lower()


def test_change_state_promotes_only_after_success_and_preserves_report_on_failure():
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))
    initial = SessionChangeState(baseline=before)
    failed = initial.with_refresh_outcome(
        state="failed",
        completed_at=NOW,
        affected_source="official_core_sources",
        error_summary="safe fixture failure",
    )

    assert failed.baseline == before
    assert failed.latest_comparison is None

    comparison = compare_snapshot_digests(before, after, detected_at=NOW)
    promoted = failed.promote(after, comparison)
    cancelled = promoted.with_refresh_outcome(
        state="cancelled",
        completed_at=NOW + timedelta(minutes=1),
        affected_source="official_core_sources",
    )

    assert promoted.baseline == after
    assert promoted.latest_comparison == comparison
    assert promoted.refresh_metadata.state == "success"
    assert cancelled.baseline == after
    assert cancelled.latest_comparison == comparison
    assert cancelled.refresh_metadata.state == "cancelled"


def test_first_valid_snapshot_creates_baseline_without_everything_added():
    digest = _digest(roster=(_roster(),))

    state = SessionChangeState().establish_first_baseline(digest, completed_at=NOW)

    assert state.baseline == digest
    assert state.latest_comparison is None
    assert state.recent_history == ()
    assert state.refresh_metadata.state == "baseline_created"


def test_acknowledgement_is_event_identity_only_and_does_not_mutate_comparison():
    state = replace(_state(), acknowledged_event_ids=())
    event = state.latest_comparison.events[0]

    acknowledged = state.acknowledge((event.event_id,))
    cleared = acknowledged.clear_acknowledgements((event.event_id,))

    assert acknowledged.latest_comparison == state.latest_comparison
    assert acknowledged.baseline == state.baseline
    assert acknowledged.acknowledged_event_ids == (event.event_id,)
    assert cleared.acknowledged_event_ids == ()


def test_comparison_history_and_acknowledgements_are_bounded():
    state = _state()
    history = tuple(
        replace(item, after_snapshot_id=f"snapshot-{index}")
        for index in range(20)
        for item in state.recent_history
    )
    bounded = replace(
        state,
        recent_history=history,
        acknowledged_event_ids=tuple(f"event-{index}" for index in range(2_000)),
    )

    assert len(bounded.recent_history) == 5
    assert len(bounded.acknowledged_event_ids) == 1_000


def test_change_filter_preferences_and_scroll_position_round_trip():
    original = populated_snapshot()
    ui = replace(
        original.ui_state,
        what_changed_filter="Needs Attention",
        what_changed_team_filter="CHI",
        what_changed_category_filter="Roster",
        what_changed_scroll_fraction=0.42,
    )
    restored = session_from_json_bytes(
        session_to_json_bytes(replace(original, ui_state=ui))
    )

    assert restored.ui_state.what_changed_filter == "Needs Attention"
    assert restored.ui_state.what_changed_team_filter == "CHI"
    assert restored.ui_state.what_changed_category_filter == "Roster"
    assert restored.ui_state.what_changed_scroll_fraction == 0.42
