from __future__ import annotations

import math
from types import SimpleNamespace

import pandas as pd
import pytest

from ausl_splits import (
    DEFAULT_SPLIT_SAMPLE_POLICY,
    SplitSampleState,
    apply_split_sample_policy,
)
from ausl_facts import VerificationState, build_selected_game_facts


def _hitter(**overrides):
    row = {
        "player_id": "101",
        "season": 2026,
        "split_key": "last7Days",
        "split_label": "Last 7 Days",
        "plateAppearances": 12,
        "hits": 5,
    }
    row.update(overrides)
    return row


def _pitcher(**overrides):
    row = {
        "player_id": "202",
        "season": 2026,
        "split_key": "last7Days",
        "split_label": "Last 7 Days",
        "inningsPitched": "3.0",
        "strikeOuts": 4,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "split_key",
    ["regularSeason", "Regular Season", "regular-season", " regular_season "],
)
def test_regular_season_aggregate_is_excluded_after_exact_normalization(split_key):
    result = apply_split_sample_policy(
        pd.DataFrame([_hitter(split_key=split_key)]), category="batting"
    )

    assert result.empty


def test_nonaggregate_label_containing_regular_season_words_is_not_overmatched():
    result = apply_split_sample_policy(
        pd.DataFrame(
            [_hitter(split_key="opponentRegularSeasonHistory", split_label="Opponent history")]
        ),
        category="batting",
    )

    assert len(result) == 1
    assert result.iloc[0]["split_sample_state"] == SplitSampleState.ELIGIBLE.value


@pytest.mark.parametrize("plate_appearances", [0, 1, 11])
def test_small_hitter_sample_is_retained_but_never_air_ready(plate_appearances):
    result = apply_split_sample_policy(
        pd.DataFrame([_hitter(plateAppearances=plate_appearances)]),
        category="batting",
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["split_sample_state"] == SplitSampleState.SMALL_SAMPLE.value
    assert row["split_sample_label"] == "SMALL SAMPLE"
    assert row["split_air_ready"] is False or row["split_air_ready"] == False


def test_default_hitter_threshold_is_twelve_plate_appearances():
    assert DEFAULT_SPLIT_SAMPLE_POLICY.hitter_min_plate_appearances == 12
    result = apply_split_sample_policy(
        pd.DataFrame([_hitter(plateAppearances=12)]), category="batting"
    )
    assert result.iloc[0]["split_air_ready"] is True or result.iloc[0]["split_air_ready"] == True


@pytest.mark.parametrize(
    ("innings", "expected_state"),
    [
        ("2.2", SplitSampleState.SMALL_SAMPLE),
        ("3.0", SplitSampleState.ELIGIBLE),
        (3, SplitSampleState.ELIGIBLE),
    ],
)
def test_pitcher_threshold_uses_canonical_outs(innings, expected_state):
    result = apply_split_sample_policy(
        pd.DataFrame([_pitcher(inningsPitched=innings)]), category="pitching"
    )

    assert result.iloc[0]["split_sample_state"] == expected_state.value
    assert result.iloc[0]["split_sample_outs"] == (8 if innings == "2.2" else 9)


@pytest.mark.parametrize(
    ("category", "row"),
    [
        ("batting", _hitter(plateAppearances=None)),
        ("batting", _hitter(plateAppearances="malformed")),
        ("batting", _hitter(plateAppearances=-1)),
        ("batting", _hitter(plateAppearances=math.nan)),
        ("batting", _hitter(plateAppearances=math.inf)),
        ("pitching", _pitcher(inningsPitched=None)),
        ("pitching", _pitcher(inningsPitched="3.3")),
        ("pitching", _pitcher(inningsPitched=-1)),
        ("pitching", _pitcher(inningsPitched=math.nan)),
        ("pitching", _pitcher(inningsPitched=math.inf)),
    ],
)
def test_invalid_sample_evidence_fails_closed(category, row):
    result = apply_split_sample_policy(pd.DataFrame([row]), category=category)

    assert result.empty


def test_split_policy_is_configurable_and_output_is_deterministic():
    policy = DEFAULT_SPLIT_SAMPLE_POLICY.with_thresholds(
        hitter_min_plate_appearances=20,
        pitcher_min_outs=12,
    )
    rows = pd.DataFrame(
        [
            _hitter(player_id="102", split_key="vsLeft", split_label="vs LHP", plateAppearances=19),
            _hitter(player_id="101", split_key="last7Days", split_label="Last 7 Days", plateAppearances=20),
        ]
    )

    first = apply_split_sample_policy(rows, category="batting", policy=policy)
    second = apply_split_sample_policy(
        rows.iloc[::-1].reset_index(drop=True),
        category="batting",
        policy=policy,
    )

    assert list(first["player_id"]) == list(second["player_id"]) == ["101", "102"]
    assert list(first["split_sample_state"]) == [
        SplitSampleState.ELIGIBLE.value,
        SplitSampleState.SMALL_SAMPLE.value,
    ]


def _fact_database(split_rows):
    snapshot = "2026-07-29T12:00:00+00:00"
    return {
        "roster": pd.DataFrame(
            [
                {
                    "player_id": 101,
                    "player_name": "Ada Active",
                    "team_code": "CHI",
                    "team": "Chicago Bandits",
                    "position": "OF",
                    "roster_status": "Active",
                },
                {
                    "player_id": 202,
                    "player_name": "Carla Current",
                    "team_code": "CAR",
                    "team": "Carolina Blaze",
                    "position": "P",
                    "roster_status": "Active",
                },
            ]
        ),
        "batting_2026": pd.DataFrame(),
        "pitching_2026": pd.DataFrame(),
        "career_batting": pd.DataFrame(),
        "career_pitching": pd.DataFrame(),
        "batting_splits": pd.DataFrame(split_rows),
        "pitching_splits": pd.DataFrame(),
        "fielding_splits": pd.DataFrame(),
        "official_game_notes": pd.DataFrame(),
        "media_players": pd.DataFrame(),
        "manual_notes": pd.DataFrame(),
        "standings": pd.DataFrame(),
        "enrichment_enabled": True,
        "enrichment_mode": "producer_approved",
        "manifest": {
            "updated_at": snapshot,
            "source_health": {
                "official_rosters": {"status": "green"},
                "official_stats": {"status": "green"},
                "official_schedule": {"status": "green"},
                "official_standings": {"status": "green"},
                "official_game_notes": {"status": "green"},
                "media_guide": {"status": "green"},
                "split_stats": {"status": "green"},
            },
        },
        "refresh_attempt": {"state": "succeeded"},
    }


def _selected_game():
    return SimpleNamespace(
        game_id="9001",
        season=2026,
        away_team_code="CHI",
        away_team="Chicago Bandits",
        home_team_code="CAR",
        home_team="Carolina Blaze",
    )


def _split_fact_row(**overrides):
    row = _hitter(
        player_id=101,
        hits=5,
        battingAverage=0.417,
        source_name="Official AUSL Split Stats",
        source_url="https://theausl.com/splits",
        imported_at="2026-07-29T12:00:00+00:00",
    )
    row.update(
        {
            "producer_approved": True,
            "producer_air_ready": True,
            "producer_trust_state": "VERIFIED",
        }
    )
    row.update(overrides)
    return row


def test_split_fact_adapter_promotes_only_qualified_detailed_sample():
    database = _fact_database(
        [
            _split_fact_row(),
            _split_fact_row(
                split_key="regularSeason",
                split_label="Regular Season",
                plateAppearances=80,
            ),
            _split_fact_row(
                split_key="vsLeft",
                split_label="vs LHP",
                plateAppearances=5,
            ),
        ]
    )

    collection = build_selected_game_facts(database, _selected_game())
    split_facts = [
        fact
        for fact in collection.facts
        if fact.source_record_identity.startswith("split:")
    ]

    assert len(split_facts) == 2
    qualified = next(
        fact for fact in split_facts if "last7Days" in fact.source_record_identity
    )
    small = next(
        fact for fact in split_facts if "vsLeft" in fact.source_record_identity
    )
    assert qualified.verification_state is VerificationState.VERIFIED
    assert qualified.air_ready is True
    assert small.verification_state is VerificationState.VERIFY
    assert small.air_ready is False
    assert "SMALL SAMPLE" in small.warning_reason
    assert all("regularSeason" not in fact.source_record_identity for fact in split_facts)


def test_split_fact_missing_provenance_or_wrong_player_is_excluded():
    database = _fact_database(
        [
            _split_fact_row(source_url=""),
            _split_fact_row(player_id=999, split_key="last14Days"),
        ]
    )

    collection = build_selected_game_facts(database, _selected_game())

    assert not any(
        fact.source_record_identity.startswith("split:")
        for fact in collection.facts
    )
