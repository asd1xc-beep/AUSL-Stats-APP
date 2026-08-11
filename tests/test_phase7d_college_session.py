from __future__ import annotations

import json
from datetime import datetime, timezone

from ausl_session import (
    SESSION_SCHEMA_VERSION,
    SessionLifecycle,
    SessionSnapshot,
    SessionUIState,
    session_from_json_bytes,
    session_to_json_bytes,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def test_session_v3_restores_college_tab_and_exact_player_without_schema_bump():
    snapshot = SessionSnapshot(
        schema_version=SESSION_SCHEMA_VERSION,
        session_id="phase7d-session",
        created_at=NOW,
        updated_at=NOW,
        lifecycle=SessionLifecycle.ACTIVE,
        ui_state=SessionUIState(
            main_tab="College Résumé", selected_player_id="950"
        ),
    )
    restored = session_from_json_bytes(session_to_json_bytes(snapshot))
    assert SESSION_SCHEMA_VERSION == 3
    assert restored.ui_state.main_tab == "College Résumé"
    assert restored.ui_state.selected_player_id == "950"


def test_session_never_persists_rendered_college_or_copy_payloads():
    snapshot = SessionSnapshot(
        schema_version=SESSION_SCHEMA_VERSION,
        session_id="phase7d-session-private",
        created_at=NOW,
        updated_at=NOW,
        lifecycle=SessionLifecycle.ACTIVE,
        ui_state=SessionUIState(
            main_tab="College Résumé", selected_player_id="950"
        ),
    )
    payload = json.loads(session_to_json_bytes(snapshot))
    text = json.dumps(payload).casefold()
    assert "college_resume" not in text
    assert "candidate_id" not in text
    assert "college career" not in text
    assert "clipboard" not in text
