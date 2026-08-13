from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from ausl_college_batch_approval import load_aggregate_approval
from ausl_college_connection_approval import load_checked_in_connection_approval
from ausl_facts import (
    FactCategory,
    VerificationState,
    build_college_connection_facts,
    build_copy_event,
    build_selected_game_facts,
    copy_with_source_text,
)


ROOT = Path(__file__).resolve().parents[1]


def _college():
    return load_aggregate_approval(ROOT / "data" / "college_approved_phase7e")


def _connections():
    return load_checked_in_connection_approval(
        ROOT / "data" / "college_connections_approved"
    )


def _database(*, reverse=False):
    rows = [
        {"player_id": "1075", "player_name": "Tiare Jennings", "team_code": "TEX", "team": "Texas Volts", "roster_status": "Active", "position": "IF"},
        {"player_id": "1285", "player_name": "Kelly Maxwell", "team_code": "PDX", "team": "Portland Cascade", "roster_status": "Active", "position": "P"},
        {"player_id": "1322", "player_name": "Ailana Agbayani", "team_code": "CHI", "team": "Chicago Bandits", "roster_status": "Active", "position": "IF"},
        {"player_id": "1102", "player_name": "Korbe Otis", "team_code": "PDX", "team": "Portland Cascade", "roster_status": "Active", "position": "OF"},
        {"player_id": "1327", "player_name": "NiJaree Canady", "team_code": "TEX", "team": "Texas Volts", "roster_status": "Active", "position": "P"},
        {"player_id": "950", "player_name": "Valerie Cagle", "team_code": "CAR", "team": "Carolina Blaze", "roster_status": "Active", "position": "UT"},
    ]
    if reverse:
        rows.reverse()
    return {
        "roster": pd.DataFrame(rows),
        "manifest": {
            "updated_at": "2026-08-12T20:58:08+00:00",
            "source": "phase7e-test",
            "seasons": {"2026": 1},
            "source_health": {},
        },
    }


def _game(game_id="2042", away="TEX", home="PDX"):
    return {
        "game_id": game_id,
        "season": 2026,
        "away_team_code": away,
        "home_team_code": home,
        "away_team": away,
        "home_team": home,
    }


def test_approved_connection_adapts_to_canonical_multisource_broadcast_fact():
    facts = build_college_connection_facts(
        _database(),
        _game(),
        college_artifact=_college(),
        connection_approval=_connections(),
    )
    championship = next(item for item in facts if "championship" in item.air_copy)

    assert championship.category is FactCategory.COLLEGE_CONNECTION
    assert championship.verification_state is VerificationState.VERIFIED
    assert championship.air_ready
    assert championship.selected_game_id == "2042"
    assert championship.subject_id == "1075+1285"
    assert len(championship.provenance) == 2
    assert {item.source_record_id for item in championship.provenance}
    assert dict(championship.evidence)["connection_id"].startswith(
        "college-connection-"
    )
    event = build_copy_event(championship)
    assert event.evidence_hash == championship.evidence_hash
    source_copy = copy_with_source_text(championship)
    assert "Source:" in source_copy and "Status: VERIFIED" in source_copy


def test_game_selection_excludes_unrelated_connections_and_caps_diversity():
    facts = build_college_connection_facts(
        _database(),
        _game(away="CHI", home="CAR"),
        college_artifact=_college(),
        connection_approval=_connections(),
    )

    assert 1 <= len(facts) <= 3
    assert all(
        set(dict(item.evidence)["subject_player_ids"].split(","))
        & {"1322", "950"}
        for item in facts
    )
    per_player = {}
    for item in facts:
        for player_id in dict(item.evidence)["subject_player_ids"].split(","):
            per_player[player_id] = per_player.get(player_id, 0) + 1
    assert max(per_player.values()) <= 2


def test_fact_output_is_deterministic_and_game_identity_is_exact():
    first = build_college_connection_facts(
        _database(),
        _game("2042"),
        college_artifact=_college(),
        connection_approval=_connections(),
    )
    reordered = build_college_connection_facts(
        _database(reverse=True),
        _game("2042"),
        college_artifact=_college(),
        connection_approval=_connections(),
    )
    repeat_opponent = build_college_connection_facts(
        _database(),
        _game("2099"),
        college_artifact=_college(),
        connection_approval=_connections(),
    )

    assert [(item.fact_id, item.evidence_hash) for item in first] == [
        (item.fact_id, item.evidence_hash) for item in reordered
    ]
    assert {item.fact_id for item in first}.isdisjoint(
        {item.fact_id for item in repeat_opponent}
    )


def test_missing_or_tampered_approval_yields_no_college_facts():
    assert build_college_connection_facts(
        _database(),
        _game(),
        college_artifact=_college(),
        connection_approval=None,
    ) == []

    artifact = _connections()
    changed = replace(
        artifact,
        candidate_payload=artifact.candidate_payload.replace(
            b"national championship team", b"changed wording"
        ),
    )
    assert build_college_connection_facts(
        _database(),
        _game(),
        college_artifact=_college(),
        connection_approval=changed,
    ) == []


def test_selected_game_collection_includes_college_facts_without_replacing_current_facts():
    collection = build_selected_game_facts(
        _database(),
        _game(),
        college_artifact=_college(),
        connection_approval=_connections(),
    )

    college = [
        item for item in collection.facts if item.category is FactCategory.COLLEGE_CONNECTION
    ]
    assert college
    assert len(college) <= 3
    assert all(item.selected_game_id == collection.game_id for item in college)
