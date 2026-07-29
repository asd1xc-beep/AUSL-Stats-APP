from __future__ import annotations

from dataclasses import replace

from ausl_changes import build_snapshot_digest
from ausl_data import load_database
from ausl_facts import build_selected_game_facts
from ausl_session import SessionChangeState, SessionSnapshot, session_to_json_bytes
from ausl_stats_app import (
    _canonical_media_review_state,
    official_selected_games,
    official_team_snapshot,
)


def test_checked_in_core_snapshot_builds_private_safe_phase6e_baseline():
    database = load_database(include_enrichment=False)
    games = official_selected_games(database["schedule_results"])
    assert games
    selected = games[0]
    collection = build_selected_game_facts(
        database,
        selected,
        lineup_lock={},
        media_approval_validator=_canonical_media_review_state,
        team_snapshot_provider=lambda code, season: official_team_snapshot(
            code, season, database
        ),
    )
    assert collection.available

    digest = build_snapshot_digest(database, facts=collection.facts)
    session = replace(
        SessionSnapshot.new(),
        change_state=SessionChangeState(baseline=digest),
    )
    rendered = session_to_json_bytes(session)

    assert digest.roster
    assert digest.teams
    assert digest.schedule
    assert digest.facts
    assert all(item.state == "green" for item in digest.source_health)
    assert rendered.endswith(b"\n")
    assert b"\r\n" not in rendered
