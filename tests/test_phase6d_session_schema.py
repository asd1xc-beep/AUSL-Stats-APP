from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ausl_rundown import RundownSession
from ausl_session import (
    SESSION_SCHEMA_VERSION,
    GameIdentity,
    SessionLifecycle,
    SessionSnapshot,
    SessionUIState,
    SessionValidationError,
    session_from_json_bytes,
    session_to_json_bytes,
)
from test_phase6c_rundown import versioned_fact


NOW = datetime(2026, 7, 28, 14, 15, 16, tzinfo=timezone.utc)


def populated_snapshot() -> SessionSnapshot:
    rundown = RundownSession()
    rundown.pin_fact("1042", versioned_fact(), now=NOW)
    rundown.mark_fact_used(
        "1042",
        versioned_fact(subject_id="22"),
        now=NOW + timedelta(seconds=1),
    )
    return SessionSnapshot(
        schema_version=SESSION_SCHEMA_VERSION,
        session_id="session-test-1042",
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=2),
        lifecycle=SessionLifecycle.ACTIVE,
        selected_game=GameIdentity(
            game_id="1042",
            season=2026,
            away_team_code="CHI",
            home_team_code="TAL",
        ),
        rundown_states=rundown.states,
        ui_state=SessionUIState(
            main_tab="Game Day",
            game_day_view="Rundown",
            fact_status_filter="Needs Verification",
            fact_team_filter="CHI",
            fact_category_filter="Milestone Watch",
            fact_template_profile="120 — extended",
            show_used=True,
            selected_player_id="22",
            fact_scroll_fraction=0.25,
            rundown_scroll_fraction=0.75,
            prior_offline_mode=True,
        ),
    )


def test_v1_round_trip_is_deterministic_and_retains_exact_fact_versions():
    original = populated_snapshot()

    first = session_to_json_bytes(original)
    restored = session_from_json_bytes(first)
    second = session_to_json_bytes(restored)

    assert first == second
    assert first.endswith(b"\n")
    assert b"\r\n" not in first
    assert restored == original
    state = restored.rundown_states[0]
    assert state.active_entries[0].fact_id == original.rundown_states[0].active_entries[0].fact_id
    assert state.active_entries[0].evidence_hash == original.rundown_states[0].active_entries[0].evidence_hash
    assert state.used_history[0].evidence_hash == original.rundown_states[0].used_history[0].evidence_hash


def test_session_json_contains_primitives_and_excludes_runtime_state():
    payload = json.loads(session_to_json_bytes(populated_snapshot()))

    def assert_primitive_tree(value):
        assert value is None or isinstance(value, (dict, list, str, int, float, bool))
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str)
                assert_primitive_tree(item)
        elif isinstance(value, list):
            for item in value:
                assert_primitive_tree(item)

    assert_primitive_tree(payload)
    rendered = json.dumps(payload).lower()
    for forbidden in ("clipboard", "timer", "thread", "widget", "credential", "token"):
        assert forbidden not in rendered
    assert payload["ui_state"]["prior_offline_mode"] is True
    assert "offline_mode" not in payload["ui_state"]


def test_missing_optional_fields_receive_safe_defaults():
    payload = json.loads(session_to_json_bytes(populated_snapshot()))
    del payload["ui_state"]
    del payload["selected_game"]
    del payload["rundown_states"]

    restored = session_from_json_bytes(
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    )

    assert restored.ui_state == SessionUIState()
    assert restored.selected_game is None
    assert restored.rundown_states == ()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value.pop("schema_version"), "schema_version"),
        (lambda value: value.__setitem__("schema_version", 999), "newer schema"),
        (lambda value: value.__setitem__("session_id", ""), "session_id"),
        (lambda value: value.__setitem__("lifecycle", "finished-ish"), "lifecycle"),
        (lambda value: value.__setitem__("created_at", "yesterday"), "timestamp"),
        (lambda value: value.__setitem__("rundown_states", {}), "rundown_states"),
        (
            lambda value: value["selected_game"].__setitem__("season", "2026"),
            "season",
        ),
        (
            lambda value: value["ui_state"].__setitem__(
                "rundown_scroll_fraction", 1.5
            ),
            "scroll",
        ),
    ],
)
def test_invalid_or_future_session_data_fails_closed(mutate, match):
    payload = json.loads(session_to_json_bytes(populated_snapshot()))
    mutate(payload)

    with pytest.raises(SessionValidationError, match=match):
        session_from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_identity_and_fact_hash_tampering_is_rejected():
    payload = json.loads(session_to_json_bytes(populated_snapshot()))
    payload["rundown_states"][0]["active_entries"][0]["evidence_hash"] = "wrong"

    with pytest.raises(SessionValidationError, match="evidence hash"):
        session_from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_duplicate_games_and_oversized_collections_are_rejected():
    payload = json.loads(session_to_json_bytes(populated_snapshot()))
    payload["rundown_states"].append(payload["rundown_states"][0])
    with pytest.raises(SessionValidationError, match="[Dd]uplicate"):
        session_from_json_bytes(json.dumps(payload).encode("utf-8"))

    payload = json.loads(session_to_json_bytes(populated_snapshot()))
    payload["rundown_states"] = payload["rundown_states"] * 65
    for index, state in enumerate(payload["rundown_states"]):
        state["game_id"] = str(2000 + index)
    with pytest.raises(SessionValidationError, match="limit"):
        session_from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_snapshot_requires_timezone_aware_ordered_timestamps():
    original = populated_snapshot()
    with pytest.raises(SessionValidationError, match="timezone"):
        replace(original, updated_at=datetime(2026, 7, 28, 14, 15, 16))
    with pytest.raises(SessionValidationError, match="before"):
        replace(original, updated_at=NOW - timedelta(seconds=1))
