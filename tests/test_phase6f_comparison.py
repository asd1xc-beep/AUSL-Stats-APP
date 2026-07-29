from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from ausl_comparison import (
    COMPARISON_METRICS,
    ComparisonBuildError,
    ComparisonCopyRecord,
    MetricSection,
    build_player_comparison,
    comparison_with_sources_text,
)
import ausl_comparison
from ausl_facts import (
    BroadcastFact,
    FactCategory,
    FactCollection,
    FactSubjectType,
    SourceProvenance,
    VerificationState,
)


def _database(fixture_database):
    database = dict(fixture_database)
    database["manifest"] = {
        "updated_at": "2026-07-18T23:45:00+00:00",
        "source": "Official AUSL local snapshot",
        "snapshot_id": "snapshot-2026-a",
    }
    return database


def _fact(player_id: str, *, verified: bool, game_id: str = "9001"):
    provenance = SourceProvenance(
        source_name="Official AUSL Game Notes",
        source_reference="local:game-notes",
        source_date="2026-07-18",
        source_game_id=game_id,
        source_page="4",
        snapshot_timestamp="2026-07-18T23:45:00+00:00",
    )
    return BroadcastFact(
        category=FactCategory.MILESTONE_WATCH,
        subject_type=FactSubjectType.PLAYER,
        subject_id=player_id,
        season=2026,
        selected_game_id=game_id,
        team_code="CHI",
        team_display_name="Chicago Bandits",
        opponent_context="Carolina Blaze",
        source_record_identity=f"milestone:{player_id}",
        concept_key=f"milestone:{player_id}",
        headline="Milestone watch",
        air_copy=f"Player {player_id} is approaching a milestone.",
        supporting_context="",
        subject_display_name=f"Player {player_id}",
        provenance=(provenance,),
        verification_state=(
            VerificationState.VERIFIED if verified else VerificationState.VERIFY
        ),
        source_health="green",
        producer_confirmation_required=not verified,
        warning_reason="" if verified else "Producer verification required.",
        readiness_blocking=False,
    )


def test_metric_registry_has_stable_unique_order_and_sections():
    keys = [metric.metric_key for metric in COMPARISON_METRICS]

    assert len(keys) == len(set(keys))
    assert [metric.order for metric in COMPARISON_METRICS] == list(
        range(len(COMPARISON_METRICS))
    )
    assert {metric.section for metric in COMPARISON_METRICS} == {
        MetricSection.SEASON_BATTING,
        MetricSection.SEASON_PITCHING,
        MetricSection.SEASON_FIELDING,
        MetricSection.CAREER_BATTING,
        MetricSection.CAREER_PITCHING,
        MetricSection.CAREER_FIELDING,
    }


def test_comparison_requires_two_exact_distinct_roster_identities(fixture_database):
    database = _database(fixture_database)

    with pytest.raises(ComparisonBuildError, match="two different"):
        build_player_comparison(database, "101", "101", season=2026)
    with pytest.raises(ComparisonBuildError, match="exactly one"):
        build_player_comparison(database, "101", "999", season=2026)


def test_comparison_keeps_aligned_rows_without_winner_language(fixture_database):
    comparison = build_player_comparison(
        _database(fixture_database), "101", "103", season=2026
    )

    assert comparison.left.player_id == "101"
    assert comparison.right.player_id == "103"
    assert comparison.left.player_name == "Ada Active"
    assert comparison.right.player_name == "Rae Reserve"
    assert comparison.sections
    assert all(row.left.metric_key == row.right.metric_key for row in comparison.rows)
    assert not hasattr(comparison, "winner")
    assert "better" not in comparison.summary.casefold()


def test_batting_and_pitching_formatters_match_canonical_display(fixture_database):
    comparison = build_player_comparison(
        _database(fixture_database), "101", "103", season=2026
    )
    values = {
        row.metric.metric_key: (row.left.display_value, row.right.display_value)
        for row in comparison.rows
    }

    assert values["season_batting.avg"] == (".346", ".421")
    assert values["season_batting.hr"] == ("3", "5")
    assert values["season_pitching.ip"] == ("—", "31.2")
    assert values["season_pitching.whip"] == ("—", "0.88")
    assert values["career_pitching.era"] == ("—", "1.14")


def test_missing_values_are_unavailable_not_zero_or_nan(fixture_database):
    comparison = build_player_comparison(
        _database(fixture_database), "104", "106", season=2026
    )

    assert all(
        value.display_value == "—"
        for row in comparison.rows
        for value in (row.left, row.right)
        if not value.available
    )
    copied = comparison_with_sources_text(comparison)
    assert "nan" not in copied.casefold()
    assert "unavailable" in copied.casefold()


def test_two_way_player_retains_batting_and_pitching_sections(fixture_database):
    comparison = build_player_comparison(
        _database(fixture_database), "102", "103", season=2026
    )
    values = {
        row.metric.metric_key: row.left
        for row in comparison.rows
    }

    assert values["season_batting.avg"].available
    assert values["season_pitching.era"].available


def test_inactive_unknown_and_teamless_players_keep_warnings(fixture_database):
    inactive = build_player_comparison(
        _database(fixture_database), "102", "104", season=2026
    )
    teamless = build_player_comparison(
        _database(fixture_database), "101", "106", season=2026
    )

    assert any("Inactive" in warning for warning in inactive.left.warnings)
    assert any("unknown" in warning.casefold() for warning in inactive.right.warnings)
    assert any("team" in warning.casefold() for warning in teamless.right.warnings)


def test_fact_context_is_independently_scoped_by_player_and_game(fixture_database):
    collection = FactCollection(
        game_id="9001",
        snapshot_timestamp="2026-07-18T23:45:00+00:00",
        database_version="fixture",
        facts=(
            _fact("101", verified=True),
            _fact("103", verified=False),
            _fact("999", verified=True),
        ),
        available=True,
        empty_reason="",
    )

    comparison = build_player_comparison(
        _database(fixture_database),
        "101",
        "103",
        season=2026,
        selected_game_id="9001",
        facts=collection,
    )

    assert [fact.subject_id for fact in comparison.left.verified_facts] == ["101"]
    assert comparison.left.review_facts == ()
    assert [fact.subject_id for fact in comparison.right.review_facts] == ["103"]
    assert comparison.right.verified_facts == ()


def test_comparison_fact_display_keeps_each_players_independent_source(
    fixture_database,
):
    left = replace(
        _fact("101", verified=True),
        provenance=(
            SourceProvenance(
                source_name="Left Official Notes",
                source_reference="local:left-notes",
                source_date="2026-07-18",
                source_game_id="9001",
                source_page="4",
                snapshot_timestamp="2026-07-18T23:45:00+00:00",
            ),
        ),
    )
    right = replace(
        _fact("103", verified=True),
        provenance=(
            SourceProvenance(
                source_name="Right Approved Guide",
                source_reference="local:right-guide",
                source_date="2026-06-01",
                source_game_id="9001",
                source_page="22",
                snapshot_timestamp="2026-07-19T01:15:00+00:00",
            ),
        ),
    )
    collection = FactCollection(
        game_id="9001",
        snapshot_timestamp="2026-07-19T01:15:00+00:00",
        database_version="fixture",
        facts=(left, right),
        available=True,
        empty_reason="",
    )
    comparison = build_player_comparison(
        _database(fixture_database),
        "101",
        "103",
        season=2026,
        selected_game_id="9001",
        facts=collection,
    )

    left_text = ausl_comparison.comparison_fact_display_text(
        comparison.left.verified_facts[0]
    )
    right_text = ausl_comparison.comparison_fact_display_text(
        comparison.right.verified_facts[0]
    )

    assert "Left Official Notes" in left_text
    assert "local:left-notes" in left_text
    assert "Right Approved Guide" not in left_text
    assert "Right Approved Guide" in right_text
    assert "local:right-guide" in right_text
    assert "Left Official Notes" not in right_text


def test_comparison_fact_display_renders_available_provenance_and_trust_fields():
    fact = _fact("101", verified=True)
    before = (fact.verification_state, fact.air_ready, fact.evidence_hash)

    text = ausl_comparison.comparison_fact_display_text(fact)

    assert "[VERIFIED]" in text
    assert "Official AUSL Game Notes" in text
    assert "local:game-notes" in text
    assert "Source date: 2026-07-18" in text
    assert "Page: 4" in text
    assert "Game: 9001" in text
    assert "Snapshot: 2026-07-18T23:45:00+00:00" in text
    assert "Source health: GREEN" in text
    assert (fact.verification_state, fact.air_ready, fact.evidence_hash) == before


def test_comparison_fact_display_is_honest_when_provenance_is_missing():
    fact = replace(
        _fact("101", verified=False),
        provenance=(),
        verification_state=VerificationState.UNAVAILABLE,
        source_health="unknown",
        warning_reason="Source provenance unavailable.",
    )

    text = ausl_comparison.comparison_fact_display_text(fact)

    assert "[UNAVAILABLE]" in text
    assert "Fact source: Unavailable" in text
    assert "Snapshot: Unavailable" in text
    assert "Source health: UNKNOWN" in text
    assert "Review: Source provenance unavailable." in text


def test_comparison_review_fact_displays_warning_without_promoting_state():
    fact = _fact("103", verified=False)
    before = (fact.verification_state, fact.air_ready, fact.evidence_hash)

    text = ausl_comparison.comparison_fact_display_text(fact)

    assert "[VERIFY]" in text
    assert "Review: Producer verification required." in text
    assert (fact.verification_state, fact.air_ready, fact.evidence_hash) == before


def test_wrong_game_fact_collection_is_not_reused(fixture_database):
    collection = FactCollection(
        game_id="9002",
        snapshot_timestamp="2026-07-18T23:45:00+00:00",
        database_version="fixture",
        facts=(_fact("101", verified=True, game_id="9002"),),
        available=True,
        empty_reason="",
    )

    comparison = build_player_comparison(
        _database(fixture_database),
        "101",
        "103",
        season=2026,
        selected_game_id="9001",
        facts=collection,
    )

    assert comparison.left.verified_facts == ()
    assert comparison.fact_context_warning


def test_copy_comparison_retains_both_identities_and_provenance(fixture_database):
    comparison = build_player_comparison(
        _database(fixture_database), "101", "103", season=2026
    )
    copied_at = datetime(2026, 7, 19, 12, 30, tzinfo=timezone.utc)
    text = comparison_with_sources_text(comparison)
    record = ComparisonCopyRecord.create(comparison, text=text, copied_at=copied_at)

    assert "Ada Active" in text
    assert "Rae Reserve" in text
    assert "Official AUSL local snapshot" in text
    assert "2026 AUSL season" in text
    assert record.left_player_id == "101"
    assert record.right_player_id == "103"
    assert record.database_identity == comparison.database_identity
    assert record.copied_at == copied_at
    assert record.text == text


def test_global_statistical_provenance_is_distinct_and_copy_stays_metrics_only(
    fixture_database,
):
    comparison = build_player_comparison(
        _database(fixture_database),
        "101",
        "103",
        season=2026,
        selected_game_id="9001",
        facts=FactCollection(
            game_id="9001",
            snapshot_timestamp="2026-07-18T23:45:00+00:00",
            database_version="fixture",
            facts=(_fact("101", verified=True),),
            available=True,
            empty_reason="",
        ),
    )

    context = ausl_comparison.comparison_statistics_context_text(comparison)
    copied = comparison_with_sources_text(comparison)

    assert "Statistics source: Official AUSL local snapshot" in context
    assert "Statistical snapshot: 2026-07-18T23:45:00+00:00" in context
    assert "Statistics source: Official AUSL local snapshot" in copied
    assert "Statistical metrics only" in copied
    assert _fact("101", verified=True).air_copy not in copied


def test_refresh_changes_database_identity_and_values(fixture_database):
    before_db = _database(fixture_database)
    after_db = _database(fixture_database)
    after_db["manifest"] = dict(after_db["manifest"], snapshot_id="snapshot-2026-b")
    changed = after_db["batting_2026"].copy()
    changed.loc[changed["player_id"].eq(101), "hits"] = 19
    after_db["batting_2026"] = changed

    before = build_player_comparison(before_db, "101", "103", season=2026)
    after = build_player_comparison(after_db, "101", "103", season=2026)

    assert before.database_identity != after.database_identity
    before_hits = next(
        row.left.display_value
        for row in before.rows
        if row.metric.metric_key == "season_batting.h"
    )
    after_hits = next(
        row.left.display_value
        for row in after.rows
        if row.metric.metric_key == "season_batting.h"
    )
    assert (before_hits, after_hits) == ("18", "19")


def test_fabricated_air_ready_flag_cannot_enter_comparison(fixture_database):
    unsafe = _fact("101", verified=False)

    with pytest.raises(TypeError):
        replace(unsafe, air_ready=True)
