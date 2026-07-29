from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

from ausl_changes import (
    BroadcastSnapshotDigest,
    ChangeComparisonContext,
    ChangeSeverity,
    ChangeType,
    FactDigest,
    LineupDigest,
    RosterDigest,
    ScheduleDigest,
    SnapshotMetadata,
    SourceHealthDigest,
    TeamDigest,
    build_snapshot_digest,
    compare_snapshot_digests,
)


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def _digest(
    *,
    roster=(),
    teams=(),
    schedule=(),
    facts=(),
    health=(),
    snapshot_source_id="manifest-sha-1",
    imported_at="2026-07-28T15:00:00+00:00",
):
    return BroadcastSnapshotDigest.create(
        metadata=SnapshotMetadata(
            season=2026,
            source_id=snapshot_source_id,
            imported_at=imported_at,
            parser_version="phase6e-test",
        ),
        roster=roster,
        teams=teams,
        schedule=schedule,
        facts=facts,
        source_health=health,
    )


def _roster(player_id="p-1", *, team="BOS", status="active", name="Ada Active"):
    return RosterDigest(
        player_id=player_id,
        season=2026,
        team_code=team,
        roster_status=status,
        player_name=name,
        jersey_number="7",
        position="P",
    )


def _game(game_id="1042", *, status="scheduled", home="BOS", away="CHI"):
    return ScheduleDigest(
        game_id=game_id,
        season=2026,
        away_team_code=away,
        home_team_code=home,
        scheduled_start="2026-07-28T23:00:00+00:00",
        venue="AUSL Field",
        status=status,
    )


def _team(code="BOS", *, wins=10, losses=7):
    return TeamDigest(
        team_code=code,
        season=2026,
        wins=wins,
        losses=losses,
        rank=2,
        games_back="1.0",
        streak="W2",
        source_id="official-standings",
    )


def _fact(
    fact_id="fact-1",
    *,
    evidence_hash="evidence-1",
    category="milestone_watch",
    game_id="1042",
    team="BOS",
    player_id="p-1",
    air_ready=True,
    verification="VERIFIED",
    concept_key="career-hits-50",
    headline="Milestone watch",
    air_copy="Ada Active is two hits shy of 50 career AUSL hits.",
):
    return FactDigest(
        fact_id=fact_id,
        evidence_hash=evidence_hash,
        category=category,
        subject_type="player",
        subject_id=player_id,
        player_id=player_id,
        team_code=team,
        game_id=game_id,
        season=2026,
        concept_key=concept_key,
        headline=headline,
        air_copy=air_copy,
        verification_state=verification,
        air_ready=air_ready,
        source_name="Official AUSL Game Notes",
        source_reference="game-1042.pdf",
        source_date="2026-07-28",
        source_page="4",
        snapshot_timestamp="2026-07-28T15:00:00+00:00",
    )


def test_digest_identity_is_deterministic_and_input_order_independent():
    left = _digest(
        roster=(_roster("p-2", name="Bea Batter"), _roster()),
        teams=(_team("CHI", wins=9), _team()),
        schedule=(_game("1043"), _game()),
        facts=(_fact("fact-2", player_id="p-2"), _fact()),
    )
    right = _digest(
        roster=tuple(reversed(left.roster)),
        teams=tuple(reversed(left.teams)),
        schedule=tuple(reversed(left.schedule)),
        facts=tuple(reversed(left.facts)),
        imported_at="2026-07-28T15:30:00+00:00",
    )

    assert left.snapshot_id == right.snapshot_id
    left_payload = left.to_dict()
    right_payload = right.to_dict()
    left_payload["metadata"]["imported_at"] = right_payload["metadata"]["imported_at"]
    assert left_payload == right_payload


def test_digest_identity_changes_for_material_authoritative_content():
    baseline = _digest(roster=(_roster(),))
    changed = _digest(roster=(_roster(status="inactive"),))

    assert baseline.snapshot_id != changed.snapshot_id


def test_digest_does_not_store_manual_note_copy_or_private_context():
    manual = replace(
        _fact(category="manual_note"),
        air_copy="PRIVATE: do not persist this producer sentence",
        headline="Private scouting thought",
    )

    digest = _digest(facts=(manual,))
    payload = str(digest.to_dict())

    assert "do not persist this producer sentence" not in payload
    assert "Private scouting thought" not in payload
    assert digest.facts[0].headline == "Producer-approved manual note"
    assert digest.facts[0].air_copy == ""


def test_identical_material_snapshot_produces_no_events_despite_import_time():
    before = _digest(roster=(_roster(),), imported_at="2026-07-28T14:00:00Z")
    after = _digest(roster=(_roster(),), imported_at="2026-07-28T15:00:00Z")

    comparison = compare_snapshot_digests(before, after, detected_at=NOW)

    assert comparison.events == ()
    assert comparison.before_snapshot_id == comparison.after_snapshot_id


def test_roster_status_change_is_attention_and_exactly_scoped():
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))

    event = compare_snapshot_digests(before, after, detected_at=NOW).events[0]

    assert event.category == "roster"
    assert event.change_type is ChangeType.UPDATED
    assert event.severity is ChangeSeverity.ATTENTION
    assert event.player_id == "p-1"
    assert event.team_code == "BOS"
    assert "active" in event.before_summary.lower()
    assert "inactive" in event.after_summary.lower()


def test_player_team_move_is_attention_without_duplicate_added_removed_noise():
    before = _digest(roster=(_roster(team="BOS"),))
    after = _digest(roster=(_roster(team="CHI"),))

    events = compare_snapshot_digests(before, after, detected_at=NOW).events

    assert len(events) == 1
    assert events[0].category == "roster"
    assert "BOS" in events[0].before_summary
    assert "CHI" in events[0].after_summary


def test_official_record_change_is_informational_by_default():
    before = _digest(teams=(_team(wins=10, losses=7),))
    after = _digest(teams=(_team(wins=11, losses=7),))

    event = compare_snapshot_digests(before, after, detected_at=NOW).events[0]

    assert event.category == "team"
    assert event.severity is ChangeSeverity.INFO
    assert event.before_summary.startswith("BOS 10-7")
    assert event.after_summary.startswith("BOS 11-7")


def test_selected_game_schedule_change_is_attention_and_other_game_is_info():
    before = _digest(schedule=(_game("1042"), _game("1043")))
    after = _digest(
        schedule=(
            replace(_game("1042"), venue="Changed Park"),
            replace(_game("1043"), status="postponed"),
        )
    )
    context = ChangeComparisonContext(selected_game_id="1042")

    events = compare_snapshot_digests(
        before, after, context=context, detected_at=NOW
    ).events

    by_game = {event.game_id: event for event in events}
    assert by_game["1042"].selected_game_impact is True
    assert by_game["1042"].severity is ChangeSeverity.ATTENTION
    assert by_game["1043"].severity is ChangeSeverity.INFO


def test_final_score_change_is_exact_game_schedule_evidence():
    before_game = replace(_game(), status="final", away_score=3, home_score=2)
    after_game = replace(before_game, away_score=4)

    event = compare_snapshot_digests(
        _digest(schedule=(before_game,)),
        _digest(schedule=(after_game,)),
        context=ChangeComparisonContext(selected_game_id="1042"),
        detected_at=NOW,
    ).events[0]

    assert "CHI 3, BOS 2" in event.before_summary
    assert "CHI 4, BOS 2" in event.after_summary
    assert event.game_id == "1042"


def test_source_health_regression_and_recovery_are_conservative():
    green = SourceHealthDigest("official_stats", "green", "", "hash-1")
    red = SourceHealthDigest("official_stats", "red", "refresh failed", "hash-1")
    before = _digest(health=(green,))
    after = _digest(health=(red,))
    recovered = _digest(health=(green,))

    down = compare_snapshot_digests(before, after, detected_at=NOW).events[0]
    up = compare_snapshot_digests(after, recovered, detected_at=NOW).events[0]

    assert down.change_type is ChangeType.SOURCE_HEALTH_CHANGED
    assert down.severity is ChangeSeverity.BLOCKING
    assert up.change_type is ChangeType.RESTORED
    assert up.severity is ChangeSeverity.INFO


def test_selected_game_confirmed_lineup_invalidation_is_blocking():
    confirmed = LineupDigest(
        game_id="1042",
        season=2026,
        team_code="BOS",
        source_state="confirmed",
        player_ids=("p-1", "p-2"),
        revision="7",
    )
    projected = replace(
        confirmed,
        source_state="projected",
        revision="8",
    )

    event = compare_snapshot_digests(
        BroadcastSnapshotDigest.create(
            metadata=_digest().metadata,
            lineups=(confirmed,),
        ),
        BroadcastSnapshotDigest.create(
            metadata=_digest().metadata,
            lineups=(projected,),
        ),
        context=ChangeComparisonContext(selected_game_id="1042"),
        detected_at=NOW,
    ).events[0]

    assert event.category == "lineup"
    assert event.change_type is ChangeType.INVALIDATED
    assert event.severity is ChangeSeverity.BLOCKING
    assert event.readiness_impact is True


def test_fact_evidence_change_preserves_fact_identity_and_flags_pinned_impact():
    before = _digest(facts=(_fact(),))
    after = _digest(
        facts=(
            _fact(
                evidence_hash="evidence-2",
                air_copy="Ada Active is one hit shy of 50 career AUSL hits.",
            ),
        )
    )
    context = ChangeComparisonContext(
        pinned_fact_versions=(("fact-1", "evidence-1"),)
    )

    event = compare_snapshot_digests(
        before, after, context=context, detected_at=NOW
    ).events[0]

    assert event.fact_id == "fact-1"
    assert event.change_type is ChangeType.UPDATED
    assert event.pinned_impact is True
    assert event.severity is ChangeSeverity.ATTENTION
    assert event.can_replace_pinned is True


def test_fact_verification_downgrade_is_blocking_when_pinned():
    before = _digest(facts=(_fact(),))
    after = _digest(
        facts=(
            _fact(
                evidence_hash="evidence-2",
                air_ready=False,
                verification="VERIFY",
            ),
        )
    )
    context = ChangeComparisonContext(
        pinned_fact_versions=(("fact-1", "evidence-1"),)
    )

    event = compare_snapshot_digests(
        before, after, context=context, detected_at=NOW
    ).events[0]

    assert event.change_type is ChangeType.VERIFICATION_DOWNGRADED
    assert event.severity is ChangeSeverity.BLOCKING
    assert event.readiness_impact is True
    assert event.can_replace_pinned is False


def test_removed_pinned_fact_is_blocking_but_never_mutates_rundown():
    before = _digest(facts=(_fact(),))
    after = _digest()
    context = ChangeComparisonContext(
        pinned_fact_versions=(("fact-1", "evidence-1"),)
    )

    event = compare_snapshot_digests(
        before, after, context=context, detected_at=NOW
    ).events[0]

    assert event.change_type is ChangeType.REMOVED
    assert event.pinned_impact is True
    assert event.severity is ChangeSeverity.BLOCKING
    assert event.suggested_action == "Review pinned fact"


def test_used_fact_change_is_historical_attention_not_automatic_unuse():
    before = _digest(facts=(_fact(),))
    after = _digest(facts=(_fact(evidence_hash="evidence-2"),))
    context = ChangeComparisonContext(
        used_fact_versions=(("fact-1", "evidence-1"),)
    )

    event = compare_snapshot_digests(
        before, after, context=context, detected_at=NOW
    ).events[0]

    assert event.used_impact is True
    assert event.severity is ChangeSeverity.ATTENTION
    assert event.suggested_action == "Review used-on-air history"


def test_milestone_watch_to_reached_is_one_canonical_transition():
    watch = _fact(
        fact_id="watch-fact",
        category="milestone_watch",
        concept_key="career-hits-50",
    )
    reached = _fact(
        fact_id="reached-fact",
        evidence_hash="evidence-reached",
        category="milestone_reached",
        concept_key="career-hits-50",
        headline="Milestone reached",
        air_copy="Ada Active reached 50 career AUSL hits.",
    )

    events = compare_snapshot_digests(
        _digest(facts=(watch,)),
        _digest(facts=(reached,)),
        detected_at=NOW,
    ).events

    assert len(events) == 1
    assert events[0].change_type is ChangeType.UPDATED
    assert events[0].before_fact_id == "watch-fact"
    assert events[0].fact_id == "reached-fact"
    assert events[0].category == "milestone"


def test_same_prose_with_different_concept_keys_is_not_heuristically_linked():
    left = _fact(fact_id="left", concept_key="hits-50", air_copy="Same prose.")
    right = _fact(
        fact_id="right",
        concept_key="strikeouts-50",
        air_copy="Same prose.",
    )

    events = compare_snapshot_digests(
        _digest(facts=(left,)),
        _digest(facts=(right,)),
        detected_at=NOW,
    ).events

    assert {event.change_type for event in events} == {
        ChangeType.ADDED,
        ChangeType.REMOVED,
    }


def test_event_identity_is_stable_and_detection_time_is_not_material():
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))

    one = compare_snapshot_digests(before, after, detected_at=NOW).events[0]
    two = compare_snapshot_digests(
        before,
        after,
        detected_at=NOW.replace(hour=17),
    ).events[0]

    assert one.event_id == two.event_id
    assert one.detected_at != two.detected_at


def test_unknown_fields_are_rejected_in_persisted_digest():
    payload = _digest().to_dict()
    payload["unexpected"] = "unsafe"

    try:
        BroadcastSnapshotDigest.from_dict(payload)
    except ValueError as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("Unknown digest fields must fail closed")


def _database_fixture(*, imported_at="2026-07-28T15:00:00+00:00"):
    return {
        "manifest": {
            "updated_at": imported_at,
            "source": "https://theausl.com",
            "seasons": {"2026": 369},
            "source_health": {
                "official_rosters": {
                    "source_name": "Official AUSL rosters",
                    "status": "green",
                    "content_hash_or_etag": "roster-hash",
                    "parser_version": "test",
                },
                "official_stats": {
                    "source_name": "Official AUSL stats",
                    "status": "green",
                    "content_hash_or_etag": "stats-hash",
                    "parser_version": "test",
                },
            },
        },
        "roster": pd.DataFrame(
            [
                {
                    "season": 2026,
                    "player_id": "p-1",
                    "player_name": "Ada Active",
                    "team_code": "BOS",
                    "roster_status": "Active",
                    "jersey_number": 7,
                    "position": "P",
                },
                {
                    "season": 2026,
                    "player_id": "p-2",
                    "player_name": "Rae Reserve",
                    "team_code": None,
                    "roster_status": "Reserve Pool",
                    "jersey_number": None,
                    "position": "IF",
                },
            ]
        ),
        "standings": pd.DataFrame(
            [
                {
                    "seasonId": 369,
                    "team_code": "BOS",
                    "wins": 10,
                    "losses": 7,
                    "rank": 2,
                    "gamesBehind": 1.0,
                    "winStreak": "W2",
                    "standingsTypeLk": "SEASON",
                    "source_url": "official-standings",
                }
            ]
        ),
        "schedule_results": pd.DataFrame(
            [
                {
                    "game_id": "1042",
                    "season": 2026,
                    "away_team_code": "CHI",
                    "home_team_code": "BOS",
                    "game_date": "2026-07-28T23:00:00+00:00",
                    "venue": "AUSL Field",
                    "status": "Scheduled",
                }
            ]
        ),
        "batting_2026": pd.DataFrame([{"player_id": "p-1", "hits": 20}]),
    }


def test_database_adapter_is_order_independent_and_ignores_routine_stat_noise():
    left_db = _database_fixture()
    right_db = _database_fixture(imported_at="2026-07-28T16:00:00+00:00")
    right_db["roster"] = right_db["roster"].iloc[::-1].reset_index(drop=True)
    right_db["batting_2026"].loc[0, "hits"] = 21

    left = build_snapshot_digest(left_db)
    right = build_snapshot_digest(right_db)

    assert left.snapshot_id == right.snapshot_id
    assert len(left.roster) == 2
    assert next(item for item in left.roster if item.player_id == "p-2").team_code == "UNASSIGNED"
    assert compare_snapshot_digests(left, right, detected_at=NOW).events == ()


def test_database_adapter_uses_canonical_fact_evidence_for_stat_change():
    left = build_snapshot_digest(_database_fixture(), facts=(_fact(),))
    right_db = _database_fixture(imported_at="2026-07-28T16:00:00+00:00")
    right_db["batting_2026"].loc[0, "hits"] = 21
    right = build_snapshot_digest(
        right_db,
        facts=(
            _fact(
                evidence_hash="hits-21",
                air_copy="Ada Active is one hit shy of 50 career AUSL hits.",
            ),
        ),
    )

    events = compare_snapshot_digests(left, right, detected_at=NOW).events

    assert len(events) == 1
    assert events[0].category == "fact"


def test_database_adapter_normalizes_exact_game_locked_lineup_structure():
    lock = {
        "games": {
            "1042": {
                "game_id": "1042",
                "source": "official",
                "revision": 3,
                "lineups": {
                    "away": {
                        "team_code": "CHI",
                        "lineup": [
                            {"player_id": "p-3", "batting_order": 1},
                            {"player_id": "p-4", "batting_order": 2},
                        ],
                    },
                    "home": {
                        "team_code": "BOS",
                        "lineup": [
                            {"player_id": "p-1", "batting_order": 1},
                            {"player_id": "p-2", "batting_order": 2},
                        ],
                    },
                },
            }
        }
    }

    digest = build_snapshot_digest(_database_fixture(), locked_lineups=lock)

    assert [(item.team_code, item.player_ids) for item in digest.lineups] == [
        ("BOS", ("p-1", "p-2")),
        ("CHI", ("p-3", "p-4")),
    ]
    assert all(item.source_state == "official" for item in digest.lineups)
