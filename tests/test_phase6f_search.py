from __future__ import annotations

import pandas as pd
import pytest

from ausl_search import (
    MatchType,
    PlayerSearchIndex,
    SearchScope,
    parse_player_query,
    search_player_index,
)


def _roster():
    return pd.DataFrame(
        [
            {
                "player_id": 1,
                "player_name": "Rachel Garcia",
                "first_name": "Rachel",
                "last_name": "Garcia",
                "team": "Chicago Bandits",
                "team_code": "CHI",
                "jersey_number": 22,
                "position": "RHP",
                "roster_status": "Active",
                "approved_aliases": "Rach Garcia",
            },
            {
                "player_id": 2,
                "player_name": "Amanda Lorenz",
                "first_name": "Amanda",
                "last_name": "Lorenz",
                "team": "Carolina Blaze",
                "team_code": "CAR",
                "jersey_number": 18,
                "position": "OF",
                "roster_status": "Active",
            },
            {
                "player_id": 3,
                "player_name": "Maya Brady",
                "first_name": "Maya",
                "last_name": "Brady",
                "team": "Oklahoma City Spark",
                "team_code": "OKC",
                "jersey_number": 7,
                "position": "IF",
                "roster_status": "Inactive",
            },
            {
                "player_id": 4,
                "player_name": "Rachelle García",
                "first_name": "Rachelle",
                "last_name": "García",
                "team": "Texas Volts",
                "team_code": "TEX",
                "jersey_number": 22,
                "position": "P",
                "roster_status": "Reserve Athlete Pool",
            },
            {
                "player_id": 5,
                "player_name": "Ana Garza",
                "first_name": "Ana",
                "last_name": "Garza",
                "team": "Utah Talons",
                "team_code": "UTA",
                "jersey_number": None,
                "position": "C",
                "roster_status": None,
            },
        ]
    )


@pytest.fixture
def index():
    return PlayerSearchIndex.build(_roster(), snapshot_identity="snapshot-a")


@pytest.mark.parametrize(
    ("query", "field", "expected"),
    [
        ("team:CHI", "team_code", "CHI"),
        ('team:"Chicago Bandits"', "team_code", "CHI"),
        ("pos:p", "position", "P"),
        ("status:inactive", "roster_status", "Inactive"),
        ("number:#22", "jersey_number", "22"),
        ("#22", "jersey_number", "22"),
        ('name:"Rachel Garcia"', "name_text", "Rachel Garcia"),
    ],
)
def test_parser_supports_structured_filters(query, field, expected):
    parsed = parse_player_query(query)

    assert parsed.valid
    assert getattr(parsed, field) == expected


def test_parser_combines_filters_with_and_semantics():
    parsed = parse_player_query('team:CHI pos:P status:active name:"Rachel Garcia"')

    assert parsed.valid
    assert parsed.team_code == "CHI"
    assert parsed.position == "P"
    assert parsed.roster_status == "Active"
    assert parsed.name_text == "Rachel Garcia"


@pytest.mark.parametrize(
    "query",
    [
        "team:ATL",
        "pos:QB",
        "status:suspended",
        "number:abc",
        'name:"Rachel Garcia',
        "team:CHI team:CAR",
        "unknown:value",
    ],
)
def test_parser_rejects_unknown_malformed_and_conflicting_filters(query):
    parsed = parse_player_query(query)

    assert not parsed.valid
    assert parsed.issues


def test_parser_treats_command_like_text_as_inert():
    parsed = parse_player_query(r'name:"$(Remove-Item *)" C:\Windows\System32')

    assert parsed.valid
    assert parsed.name_text == "$(Remove-Item *)"
    assert parsed.free_text == r"C:\Windows\System32"


def test_index_identity_and_order_are_deterministic():
    forward = PlayerSearchIndex.build(_roster(), snapshot_identity="snapshot-a")
    reverse = PlayerSearchIndex.build(
        _roster().iloc[::-1].reset_index(drop=True),
        snapshot_identity="snapshot-a",
    )

    assert forward.index_identity == reverse.index_identity
    assert forward.records == reverse.records
    assert [record.player_id for record in forward.records] == ["3", "1", "4", "5", "2"]


@pytest.mark.parametrize(
    ("query", "expected_id", "match_type"),
    [
        ("Rachel Garcia", "1", MatchType.EXACT_FULL_NAME),
        ("Rach Garcia", "1", MatchType.EXACT_ALIAS),
        ("Garcia", "1", MatchType.EXACT_TOKEN),
        ("Rach", "1", MatchType.PREFIX),
        ("achel", "1", MatchType.SUBSTRING),
        ("Racheel Garcia", "1", MatchType.FUZZY),
        ("#22", "1", MatchType.FILTER),
    ],
)
def test_ranking_uses_explicit_precedence(index, query, expected_id, match_type):
    response = search_player_index(
        index,
        parse_player_query(query),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=("CHI", "CAR"),
    )

    assert response.results[0].record.player_id == expected_id
    assert response.results[0].match_type is match_type
    assert response.results[0].match_reason


def test_filters_apply_before_text_ranking(index):
    response = search_player_index(
        index,
        parse_player_query("team:TEX #22"),
        scope=SearchScope.SELECTED_GAME,
        selected_team_codes=("CHI", "CAR"),
    )

    assert [result.record.player_id for result in response.results] == ["4"]
    assert response.effective_scope == "Explicit team filter: TEX"


def test_selected_game_scope_reports_exact_out_of_scope_match(index):
    response = search_player_index(
        index,
        parse_player_query("Maya Brady"),
        scope=SearchScope.SELECTED_GAME,
        selected_team_codes=("CHI", "CAR"),
    )

    assert response.results == ()
    assert [record.player_id for record in response.out_of_scope_exact] == ["3"]
    assert "outside the selected game" in response.empty_message


def test_fuzzy_search_is_conservative_and_never_auto_selects(index):
    close = search_player_index(
        index,
        parse_player_query("Racheel Garcia"),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=(),
    )
    short = search_player_index(
        index,
        parse_player_query("Ra"),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=(),
    )
    unrelated = search_player_index(
        index,
        parse_player_query("Zelda Williams"),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=(),
    )

    assert close.is_possible_typo
    assert close.selected_player_id is None
    assert all(result.match_type is not MatchType.FUZZY for result in short.results)
    assert unrelated.results == ()


def test_exact_inactive_result_is_not_hidden_or_penalized(index):
    response = search_player_index(
        index,
        parse_player_query("Maya Brady"),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=("CHI", "CAR"),
    )

    assert response.results[0].record.player_id == "3"
    assert response.results[0].record.roster_status == "Inactive"
    assert "Inactive" in response.results[0].display_text


def test_same_jersey_numbers_remain_distinct(index):
    response = search_player_index(
        index,
        parse_player_query("#22"),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=(),
    )

    assert [result.record.player_id for result in response.results] == ["1", "4"]
    assert all(result.record.team_code for result in response.results)


def test_result_limit_is_bounded_and_deterministic(index):
    response = search_player_index(
        index,
        parse_player_query(""),
        scope=SearchScope.ALL_PLAYERS,
        selected_team_codes=(),
        limit=3,
    )

    assert len(response.results) == 3
    assert response.total_matches == 5
    assert response.truncated
