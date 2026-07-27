from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from ausl_facts import (
    BroadcastFact,
    FactCategory,
    FactCopyBlocked,
    FactSubjectType,
    SourceProvenance,
    VerificationState,
    build_copy_event,
    build_selected_game_facts,
    character_count_preview,
    copy_with_source_text,
    deduplicate_facts,
    order_facts,
)


SNAPSHOT = "2026-07-27T15:42:00+00:00"
NOW = datetime(2026, 7, 27, 16, 0, tzinfo=timezone.utc)


def game(game_id="1042", away="CHI", home="CAR"):
    return {
        "game_id": game_id,
        "season": 2026,
        "away_team_code": away,
        "home_team_code": home,
        "away_team": "Chicago Bandits",
        "home_team": "Carolina Blaze",
        "date_time": datetime(2026, 7, 27, 23, 0, tzinfo=timezone.utc),
        "source_name": "Official AUSL Schedule",
        "source_url": "https://theausl.com/schedule/",
        "source_updated_at": SNAPSHOT,
    }


def provenance(**overrides):
    values = {
        "source_name": "Official AUSL Stats",
        "source_reference": "local:ausl_season_stats.xlsx",
        "source_date": "2026-07-27",
        "snapshot_timestamp": SNAPSHOT,
        "source_record_id": "player:11:season:2026:hits",
    }
    values.update(overrides)
    return SourceProvenance(**values)


def fact(**overrides):
    values = {
        "category": FactCategory.SEASON_CONTEXT,
        "subject_type": FactSubjectType.PLAYER,
        "subject_id": "11",
        "season": 2026,
        "selected_game_id": "1042",
        "source_record_identity": "player:11:season:2026:hits",
        "concept_key": "season-hits-rbi",
        "headline": "ACTIVE SETS THE TABLE",
        "air_copy": "Ada Active has 31 hits and 18 RBI in the 2026 AUSL season.",
        "supporting_context": "Official regular-season batting totals.",
        "subject_display_name": "Ada Active",
        "team_code": "CHI",
        "team_display_name": "Chicago Bandits",
        "opponent_context": "vs CAR, Game 1042",
        "provenance": (provenance(),),
        "verification_state": VerificationState.VERIFIED,
        "source_health": "green",
        "producer_confirmation_required": False,
        "warning_reason": "",
        "readiness_blocking": False,
        "evidence": (("hits", "31"), ("rbi", "18")),
    }
    values.update(overrides)
    return BroadcastFact(**values)


def database(*, health="green", enrichment=True):
    return {
        "roster": pd.DataFrame(
            [
                {
                    "player_id": 11,
                    "player_name": "Ada Active",
                    "team_code": "CHI",
                    "team": "Chicago Bandits",
                    "position": "SS",
                    "roster_status": "Active",
                },
                {
                    "player_id": 22,
                    "player_name": "Carla Current",
                    "team_code": "CAR",
                    "team": "Carolina Blaze",
                    "position": "P",
                    "roster_status": "Active",
                },
                {
                    "player_id": 33,
                    "player_name": "Rita Reserve",
                    "team_code": "CHI",
                    "team": "Chicago Bandits",
                    "position": "OF",
                    "roster_status": "Reserve Pool",
                },
                {
                    "player_id": 44,
                    "player_name": "Outsider",
                    "team_code": "OKC",
                    "team": "Oklahoma City Spark",
                    "position": "C",
                    "roster_status": "Active",
                },
            ]
        ),
        "batting_2026": pd.DataFrame(
            [
                {
                    "player_id": 11,
                    "team_code": "CHI",
                    "plateAppearances": 80,
                    "hits": 31,
                    "homeRuns": 4,
                    "runsBattedIn": 18,
                },
                {
                    "player_id": 44,
                    "team_code": "OKC",
                    "plateAppearances": 70,
                    "hits": 22,
                    "homeRuns": 2,
                    "runsBattedIn": 10,
                },
            ]
        ),
        "pitching_2026": pd.DataFrame(
            [
                {
                    "player_id": 22,
                    "team_code": "CAR",
                    "appearances": 8,
                    "strikeOuts": 27,
                    "earnedRunAverage": 2.4,
                }
            ]
        ),
        "career_batting": pd.DataFrame(
            [
                {
                    "player_id": 11,
                    "hits": 48,
                    "homeRuns": 6,
                    "runsBattedIn": 32,
                    "gamesPlayed": 40,
                    "stolenBases": 8,
                }
            ]
        ),
        "career_pitching": pd.DataFrame(
            [
                {
                    "player_id": 22,
                    "strikeOuts": 24,
                    "wins": 4,
                    "appearances": 19,
                }
            ]
        ),
        "standings": pd.DataFrame(),
        "schedule_results": pd.DataFrame(),
        "official_game_notes": pd.DataFrame(),
        "media_players": pd.DataFrame(),
        "manual_notes": pd.DataFrame(),
        "manifest": {
            "updated_at": SNAPSHOT,
            "source_health": {
                "official_rosters": {"status": health},
                "official_stats": {"status": health},
                "official_schedule": {"status": health},
                "official_standings": {"status": health},
                "official_game_notes": {"status": health},
                "official_media_guide": {"status": health},
            },
        },
        "refresh_attempt": {"state": "succeeded", "completed_at": SNAPSHOT},
        "enrichment_enabled": enrichment,
    }


def test_stable_fact_id_is_separate_from_evidence_version():
    original = fact()
    same = fact()
    updated = fact(
        air_copy="Ada Active has 32 hits and 18 RBI in the 2026 AUSL season.",
        evidence=(("hits", "32"), ("rbi", "18")),
    )

    assert original.fact_id == same.fact_id == updated.fact_id
    assert original.evidence_hash == same.evidence_hash
    assert original.evidence_hash != updated.evidence_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("air_copy", "Reworded evidence."),
        ("verification_state", VerificationState.VERIFY),
        ("source_health", "yellow"),
        ("provenance", (provenance(source_page="4"),)),
        ("evidence", (("hits", "99"),)),
    ],
)
def test_evidence_hash_changes_for_content_source_or_trust(field, value):
    original = fact()
    changed = replace(original, **{field: value})

    assert changed.fact_id == original.fact_id
    assert changed.evidence_hash != original.evidence_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject_id", "12"),
        ("team_code", "CAR"),
        ("selected_game_id", "1043"),
        ("season", 2027),
        ("category", FactCategory.CAREER_SUMMARY),
        ("concept_key", "career-hits"),
    ],
)
def test_identity_dimensions_cannot_collide(field, value):
    assert replace(fact(), **{field: value}).fact_id != fact().fact_id


def test_repeat_opponent_games_remain_separate_for_game_specific_fact():
    first = fact(selected_game_id="1042")
    rematch = fact(selected_game_id="1079")
    assert first.fact_id != rematch.fact_id


def test_air_ready_is_derived_and_cannot_be_independently_constructed():
    assert fact().air_ready is True
    assert replace(fact(), source_health="yellow").air_ready is False
    assert replace(fact(), warning_reason="review required").air_ready is False
    with pytest.raises(TypeError):
        BroadcastFact(**{**fact().__dict__, "air_ready": True})


@pytest.mark.parametrize(
    ("health", "state", "ready"),
    [
        ("green", VerificationState.VERIFIED, True),
        ("yellow", VerificationState.STALE, False),
        ("red", VerificationState.UNAVAILABLE, False),
        ("unknown", VerificationState.UNAVAILABLE, False),
    ],
)
def test_official_stat_health_gate(health, state, ready):
    collection = build_selected_game_facts(database(health=health), game())
    player = next(
        item for item in collection.facts if item.subject_id == "11"
    )
    assert player.verification_state is state
    assert player.air_ready is ready


def test_missing_or_malformed_statistic_never_fabricates_zero():
    data = database()
    data["batting_2026"].loc[0, "hits"] = float("nan")
    collection = build_selected_game_facts(data, game())

    copies = [item.air_copy.casefold() for item in collection.facts]
    assert not any("ada active has 0 hits" in item for item in copies)
    assert all("nan" not in item for item in copies)


def official_note(**overrides):
    values = {
        "game_id": "1042",
        "source_game_id": "1042",
        "note_category": "milestone_watch",
        "note_text": "Ada Active is two hits shy of 50 career AUSL hits.",
        "subject_player_id": "11",
        "subject_player_name": "Ada Active",
        "subject_team_code": "CHI",
        "opposing_team_code": "CAR",
        "verification_state": "VERIFIED",
        "needs_review": False,
        "source_date": "2026-07-27",
        "source_url": "https://theausl.com/game/1042/notes.pdf",
        "source_pdf": "notes.pdf",
        "source_page": 4,
        "parser_version": "official-game-notes-v1",
        "normalized_hash": "note-ada-50-hits",
        "confidence_score": 0.98,
    }
    values.update(overrides)
    return values


def test_official_note_requires_verified_exact_game_complete_provenance():
    data = database()
    data["official_game_notes"] = pd.DataFrame(
        [
            official_note(),
            official_note(
                source_game_id="9999",
                game_id="9999",
                normalized_hash="wrong-game",
            ),
        ]
    )
    collection = build_selected_game_facts(data, game())
    notes = [
        item
        for item in collection.facts
        if item.source_record_identity.startswith("official-note:")
    ]

    assert len(notes) == 1
    assert notes[0].verification_state is VerificationState.VERIFIED
    assert notes[0].air_ready is True


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"verification_state": "VERIFY"}, VerificationState.VERIFY),
        ({"needs_review": True}, VerificationState.VERIFY),
        ({"source_page": ""}, VerificationState.VERIFY),
        ({"subject_team_code": "OKC"}, None),
        ({"note_text": "statistics player c 1b 2b"}, None),
    ],
)
def test_official_note_gate_fails_closed(changes, expected):
    data = database()
    data["official_game_notes"] = pd.DataFrame([official_note(**changes)])
    collection = build_selected_game_facts(data, game())
    notes = [
        item
        for item in collection.facts
        if item.source_record_identity.startswith("official-note:")
    ]
    if expected is None:
        assert notes == []
    else:
        assert len(notes) == 1
        assert notes[0].verification_state is expected
        assert notes[0].air_ready is False


def test_projected_lineup_cannot_become_confirmed_starter_fact():
    projected = {
        "game_id": "1042",
        "source": "projected",
        "locked_at": SNAPSHOT,
        "lineups": {
            "away": {"starting_pitcher": "11", "lineup": []},
            "home": {"starting_pitcher": "22", "lineup": []},
        },
    }
    collection = build_selected_game_facts(database(), game(), lineup_lock=projected)
    starters = [
        item
        for item in collection.facts
        if item.category in {
            FactCategory.CONFIRMED_STARTER,
            FactCategory.PROJECTED_STARTER,
        }
    ]
    assert starters
    assert all(item.category is FactCategory.PROJECTED_STARTER for item in starters)
    assert all(not item.air_ready for item in starters)


def test_official_lineup_requires_complete_approval_provenance():
    official = {
        "game_id": "1042",
        "source": "official",
        "locked_at": SNAPSHOT,
        "official_provenance": {
            "verified": True,
            "source_name": "Official lineup card",
            "source_id": "lineup-1042-r3",
            "verified_at": SNAPSHOT,
            "verified_by": "Producer A",
        },
        "lineups": {
            "away": {"starting_pitcher": "11", "lineup": []},
            "home": {"starting_pitcher": "22", "lineup": []},
        },
    }
    collection = build_selected_game_facts(database(), game(), lineup_lock=official)
    starters = [
        item
        for item in collection.facts
        if item.category is FactCategory.CONFIRMED_STARTER
    ]
    assert len(starters) == 2
    assert all(item.air_ready for item in starters)

    official["official_provenance"] = {"verified": True}
    unsafe = build_selected_game_facts(database(), game(), lineup_lock=official)
    assert not any(
        item.category is FactCategory.CONFIRMED_STARTER and item.air_ready
        for item in unsafe.facts
    )


def test_inactive_reserve_and_unknown_status_keep_warning():
    collection = build_selected_game_facts(database(), game())
    reserve = next(
        item for item in collection.facts if item.subject_id == "33"
    )
    assert reserve.category is FactCategory.AVAILABILITY
    assert reserve.verification_state is VerificationState.VERIFY
    assert reserve.producer_confirmation_required is True
    assert "reserve" in reserve.warning_reason.casefold()


def test_canonical_roster_status_preserves_specific_injury_warning():
    data = database()
    data["roster"].loc[
        data["roster"]["player_id"].eq(33), "roster_status"
    ] = "Injured - Temporary"

    collection = build_selected_game_facts(data, game())
    injured = next(item for item in collection.facts if item.subject_id == "33")
    assert "Injured - Temporary" in injured.air_copy
    assert injured.verification_state is VerificationState.VERIFY


def test_one_away_milestone_uses_a_singular_unit():
    data = database()
    data["career_batting"].loc[0, "hits"] = 49

    collection = build_selected_game_facts(data, game())
    milestone = next(
        item
        for item in collection.facts
        if item.subject_id == "11"
        and item.category is FactCategory.MILESTONE_WATCH
    )
    assert "needs 1 more hit to reach 50 career AUSL hits" in milestone.air_copy
    assert "1 more hits" not in milestone.air_copy


def manual_note(**overrides):
    values = {
        "note_id": "manual-1",
        "scope": "player",
        "player_id": "11",
        "player_name": "Ada Active",
        "team_code": "CHI",
        "game_id": "",
        "note_text": "Prefers the first-name pronunciation AY-duh.",
        "author": "Producer A",
        "source": "Producer interview",
        "created_at": SNAPSHOT,
        "updated_at": SNAPSHOT,
        "note_type": "background",
        "last_verified_date": "2026-07-27",
        "air_safe": True,
    }
    values.update(overrides)
    return values


def test_safe_and_unsafe_manual_notes_keep_their_scope_and_gate():
    data = database()
    data["manual_notes"] = pd.DataFrame(
        [
            manual_note(),
            manual_note(note_id="manual-2", air_safe=False, note_text="Research lead"),
        ]
    )
    collection = build_selected_game_facts(data, game())
    manual = [
        item
        for item in collection.facts
        if item.source_record_identity.startswith("manual-note:")
    ]
    assert len(manual) == 2
    assert manual[0].air_ready is True
    assert manual[1].verification_state is VerificationState.VERIFY


def test_manual_note_missing_reviewer_or_exact_scope_is_not_air_ready():
    data = database()
    data["manual_notes"] = pd.DataFrame(
        [
            manual_note(author=""),
            manual_note(note_id="manual-wrong", player_id="44", team_code="OKC"),
        ]
    )
    collection = build_selected_game_facts(data, game())
    manual = [
        item
        for item in collection.facts
        if item.source_record_identity.startswith("manual-note:")
    ]
    assert len(manual) == 1
    assert manual[0].verification_state is VerificationState.VERIFY


def test_approved_media_row_requires_identity_pages_and_no_warning():
    data = database()
    data["media_players"] = pd.DataFrame(
        [
            {
                "entity_type": "player",
                "entity_id": "11",
                "entity_name": "Ada Active",
                "team_code": "CHI",
                "media_guide_bio": "Played collegiately at State University.",
                "source_name": "2026 AUSL Media Guide",
                "source_url": "https://theausl.com/media-guide.pdf",
                "guide_date": "2026-07-01",
                "expected_printed_pages": "44",
                "parsed_pdf_pages": "46",
                "approval_record_id": "approval-11",
                "match_status": "verified",
                "approval_state": "approved",
                "needs_review": False,
                "warnings": "",
            },
            {
                "entity_type": "player",
                "entity_id": "22",
                "entity_name": "Carla Current",
                "team_code": "CAR",
                "match_status": "not_in_guide",
                "media_guide_bio": "Must not appear.",
            },
        ]
    )

    def validator(row, **_kwargs):
        return (
            "VERIFIED"
            if row.get("entity_id") == "11" and not row.get("warnings")
            else "VERIFY"
        )

    collection = build_selected_game_facts(
        data, game(), media_approval_validator=validator
    )
    media = [
        item
        for item in collection.facts
        if item.source_record_identity.startswith("media-guide:")
    ]
    assert len(media) == 1
    assert media[0].air_ready is True

    data["media_players"].loc[0, "warnings"] = "page mismatch"
    warned = build_selected_game_facts(
        data, game(), media_approval_validator=validator
    )
    warned_media = next(
        item
        for item in warned.facts
        if item.source_record_identity.startswith("media-guide:")
    )
    assert warned_media.verification_state is VerificationState.VERIFY


def test_latest_failed_refresh_does_not_claim_new_evidence_succeeded():
    data = database()
    data["refresh_attempt"] = {
        "state": "failed",
        "completed_at": "2026-07-27T15:55:00+00:00",
        "affected_source": "official_stats",
        "error_summary": "timeout",
    }
    collection = build_selected_game_facts(data, game())
    stats = [
        item
        for item in collection.facts
        if item.provenance[0].source_name == "Official AUSL Stats"
    ]
    assert stats
    assert all(item.verification_state is VerificationState.VERIFY for item in stats)
    assert all(SNAPSHOT in item.provenance[0].snapshot_timestamp for item in stats)
    assert all("latest refresh failed" in item.warning_reason.casefold() for item in stats)


def test_selected_game_scope_excludes_unrelated_players_and_games():
    data = database()
    data["official_game_notes"] = pd.DataFrame(
        [official_note(), official_note(game_id="9999", source_game_id="9999")]
    )
    collection = build_selected_game_facts(data, game())

    assert collection.game_id == "1042"
    assert all(item.selected_game_id == "1042" for item in collection.facts)
    assert not any(item.subject_id == "44" for item in collection.facts)


def test_deterministic_output_is_independent_of_input_row_order():
    first = database()
    second = database()
    for key in ("roster", "batting_2026", "pitching_2026"):
        second[key] = second[key].iloc[::-1].reset_index(drop=True)

    first_facts = build_selected_game_facts(first, game()).facts
    second_facts = build_selected_game_facts(second, game()).facts
    assert [(item.fact_id, item.evidence_hash) for item in first_facts] == [
        (item.fact_id, item.evidence_hash) for item in second_facts
    ]


def test_deduplication_keeps_strongest_evidence_and_source_history():
    weak = fact(
        verification_state=VerificationState.VERIFY,
        source_health="yellow",
        provenance=(provenance(source_name="Producer Prep"),),
    )
    strong = fact(
        provenance=(
            provenance(source_name="Official AUSL Game Notes", source_page="4"),
        )
    )

    result = deduplicate_facts([weak, strong])
    assert len(result) == 1
    assert result[0].air_ready is True
    assert {item.source_name for item in result[0].provenance} == {
        "Producer Prep",
        "Official AUSL Game Notes",
    }


def test_order_prioritizes_safety_categories_and_balances_teams():
    facts = [
        fact(
            category=FactCategory.BACKGROUND,
            concept_key="background-a",
            source_record_identity="bg-a",
            team_code="CHI",
        ),
        fact(
            category=FactCategory.AVAILABILITY,
            concept_key="availability-a",
            source_record_identity="availability-a",
            team_code="CHI",
        ),
        fact(
            category=FactCategory.AVAILABILITY,
            concept_key="availability-b",
            source_record_identity="availability-b",
            subject_id="22",
            team_code="CAR",
        ),
    ]
    ordered = order_facts(facts, team_codes=("CHI", "CAR"))
    assert [item.category for item in ordered[:2]] == [
        FactCategory.AVAILABILITY,
        FactCategory.AVAILABILITY,
    ]
    assert {item.team_code for item in ordered[:2]} == {"CHI", "CAR"}


def test_verified_copy_uses_exact_visible_text_and_records_provenance():
    item = fact()
    event = build_copy_event(item, copied_at=NOW)

    assert event.copied_text == item.air_copy
    assert event.fact_id == item.fact_id
    assert event.evidence_hash == item.evidence_hash
    assert event.provenance == item.provenance
    assert event.snapshot_timestamp == SNAPSHOT
    assert event.copied_at == NOW


@pytest.mark.parametrize(
    "state",
    [
        VerificationState.VERIFY,
        VerificationState.STALE,
        VerificationState.UNAVAILABLE,
    ],
)
def test_non_air_ready_copy_is_blocked_without_changing_verification(state):
    item = replace(fact(), verification_state=state)
    with pytest.raises(FactCopyBlocked):
        build_copy_event(item, copied_at=NOW)
    assert item.verification_state is state


def test_copy_with_source_includes_status_source_freshness_and_warning():
    item = replace(
        fact(),
        verification_state=VerificationState.VERIFY,
        warning_reason="Reviewer confirmation required.",
    )
    copied = copy_with_source_text(item)

    assert copied.startswith("[VERIFY]")
    assert item.air_copy in copied
    assert "Official AUSL Stats" in copied
    assert "Data snapshot:" in copied
    assert "Status: VERIFY" in copied
    assert "Reviewer confirmation required." in copied


@pytest.mark.parametrize(
    ("text", "profile", "expected_count", "expected_state"),
    [
        ("Apostrophe’s test — #22 José", "one_line", 28, "fits"),
        ("x" * 58, "one_line", 58, "near_limit"),
        ("x" * 61, "one_line", 61, "likely_wrap"),
        ("x" * 118, "extended", 118, "near_limit"),
    ],
)
def test_character_count_uses_exact_unicode_string(text, profile, expected_count, expected_state):
    preview = character_count_preview(text, profile)
    assert preview.character_count == expected_count
    assert preview.state == expected_state
    assert preview.text == text


def test_character_profiles_are_configurable_and_never_truncate():
    text = "Exact factual copy must remain intact."
    preview = character_count_preview(text, {"name": "custom", "limit": 12})
    assert preview.limit == 12
    assert preview.text == text
    assert preview.character_count == len(text)


def test_missing_selected_game_or_database_is_honestly_unavailable():
    no_game = build_selected_game_facts(database(), None)
    no_database = build_selected_game_facts({}, game())
    assert no_game.available is False
    assert "no game" in no_game.empty_reason.casefold()
    assert no_database.available is False
    assert "source data" in no_database.empty_reason.casefold()
