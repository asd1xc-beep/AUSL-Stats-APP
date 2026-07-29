from __future__ import annotations

import json
from dataclasses import replace

from ausl_session import (
    SESSION_SCHEMA_VERSION,
    SessionComparisonState,
    SessionSnapshot,
    session_from_dict,
    session_to_json_bytes,
)
from test_phase6d_session_schema import NOW, populated_snapshot


def _as_payload(snapshot):
    return json.loads(session_to_json_bytes(snapshot))


def test_schema_v3_round_trip_persists_only_comparison_identity_and_scroll():
    base = populated_snapshot()
    snapshot = replace(
        base,
        schema_version=SESSION_SCHEMA_VERSION,
        comparison_state=SessionComparisonState(
            left_player_id="101",
            right_player_id="103",
            scroll_fraction=0.42,
        ),
    )

    restored = session_from_dict(_as_payload(snapshot))

    assert SESSION_SCHEMA_VERSION == 3
    assert restored.comparison_state.left_player_id == "101"
    assert restored.comparison_state.right_player_id == "103"
    assert restored.comparison_state.scroll_fraction == 0.42
    payload = _as_payload(restored)
    assert "rows" not in payload["comparison_state"]
    assert "copy_record" not in payload["comparison_state"]


def test_schema_v2_migrates_with_empty_comparison_and_preserves_phase6e_state():
    current = populated_snapshot()
    payload = _as_payload(current)
    payload["schema_version"] = 2
    payload.pop("comparison_state", None)

    restored = session_from_dict(payload)

    assert restored.schema_version == 3
    assert restored.selected_game == current.selected_game
    assert restored.rundown_states == current.rundown_states
    assert restored.change_state == current.change_state
    assert restored.comparison_state == SessionComparisonState()


def test_corrupt_comparison_state_does_not_discard_valid_session_or_changes():
    current = populated_snapshot()
    payload = _as_payload(current)
    payload["comparison_state"] = {
        "left_player_id": "101",
        "right_player_id": "101",
        "scroll_fraction": 50,
    }

    restored = session_from_dict(payload)

    assert restored.selected_game == current.selected_game
    assert restored.rundown_states == current.rundown_states
    assert restored.change_state == current.change_state
    assert restored.comparison_state.left_player_id is None
    assert "unavailable" in restored.comparison_state.recovery_warning.casefold()


def test_comparison_state_rejects_same_identity_without_guessing():
    try:
        SessionComparisonState(left_player_id="101", right_player_id="101")
    except ValueError as exc:
        assert "different" in str(exc)
    else:
        raise AssertionError("Same-player comparison must fail closed")
