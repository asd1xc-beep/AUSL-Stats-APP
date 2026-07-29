"""Deterministic, local-only player discovery for Phase 6F.

The module owns query parsing, roster indexing, ranking, and scope explanations.
It never performs I/O and never selects a player on the caller's behalf.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import pandas as pd

from ausl_data import CODE_TO_TEAM, TEAM_CODES, TEAM_NAMES, normalize_roster_status


class SearchScope(str, Enum):
    SELECTED_GAME = "selected_game"
    ALL_PLAYERS = "all_players"


class MatchType(str, Enum):
    EXACT_FULL_NAME = "exact_full_name"
    EXACT_ALIAS = "exact_alias"
    EXACT_TOKEN = "exact_token"
    PREFIX = "prefix"
    SUBSTRING = "substring"
    FUZZY = "fuzzy"
    FILTER = "filter"


@dataclass(frozen=True)
class QueryIssue:
    message: str
    token: str = ""


@dataclass(frozen=True)
class ParsedPlayerQuery:
    raw_query: str
    free_text: str = ""
    name_text: str = ""
    team_code: str | None = None
    position: str | None = None
    roster_status: str | None = None
    jersey_number: str | None = None
    issues: tuple[QueryIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def search_text(self) -> str:
        parts = [part for part in (self.name_text, self.free_text) if part]
        return " ".join(parts).strip()

    @property
    def has_filters(self) -> bool:
        return any(
            value is not None
            for value in (
                self.team_code,
                self.position,
                self.roster_status,
                self.jersey_number,
            )
        )


@dataclass(frozen=True)
class PlayerSearchRecord:
    player_id: str
    player_name: str
    normalized_name: str
    name_tokens: tuple[str, ...]
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]
    team_name: str
    team_code: str
    jersey_number: str
    position: str
    roster_status: str

    @property
    def is_active(self) -> bool:
        return self.roster_status.casefold() == "active"


@dataclass(frozen=True)
class PlayerSearchIndex:
    snapshot_identity: str
    index_identity: str
    records: tuple[PlayerSearchRecord, ...]

    @classmethod
    def build(
        cls, roster: pd.DataFrame, *, snapshot_identity: str
    ) -> "PlayerSearchIndex":
        if not isinstance(roster, pd.DataFrame):
            roster = pd.DataFrame()
        records: list[PlayerSearchRecord] = []
        if "player_id" not in roster.columns:
            roster = roster.iloc[0:0]
        for _, row in roster.iterrows():
            player_id = _identifier(row.get("player_id"))
            player_name = _clean_text(row.get("player_name"))
            if not player_id or not player_name:
                continue
            aliases = tuple(
                sorted(
                    {
                        alias
                        for alias in _approved_aliases(row.get("approved_aliases"))
                        if normalize_search_text(alias)
                        != normalize_search_text(player_name)
                    },
                    key=lambda item: normalize_search_text(item),
                )
            )
            team_code = _clean_text(row.get("team_code")).upper()
            team_name = _clean_text(row.get("team")) or CODE_TO_TEAM.get(
                team_code, "Team unavailable"
            )
            normalized_name = normalize_search_text(player_name)
            records.append(
                PlayerSearchRecord(
                    player_id=player_id,
                    player_name=player_name,
                    normalized_name=normalized_name,
                    name_tokens=tuple(normalized_name.split()),
                    aliases=aliases,
                    normalized_aliases=tuple(
                        normalize_search_text(alias) for alias in aliases
                    ),
                    team_name=team_name,
                    team_code=team_code or "UNASSIGNED",
                    jersey_number=_jersey(row.get("jersey_number")),
                    position=normalize_position(row.get("position")),
                    roster_status=normalize_roster_status(row.get("roster_status")),
                )
            )
        records.sort(
            key=lambda item: (
                normalize_search_text(item.player_name.split()[-1]),
                item.normalized_name,
                item.player_id,
            )
        )
        payload = [
            {
                "player_id": item.player_id,
                "player_name": item.player_name,
                "aliases": item.aliases,
                "team_code": item.team_code,
                "jersey_number": item.jersey_number,
                "position": item.position,
                "roster_status": item.roster_status,
            }
            for item in records
        ]
        index_identity = hashlib.sha256(
            json.dumps(
                {
                    "snapshot_identity": str(snapshot_identity),
                    "records": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            snapshot_identity=str(snapshot_identity),
            index_identity=index_identity,
            records=tuple(records),
        )


@dataclass(frozen=True)
class PlayerSearchResult:
    record: PlayerSearchRecord
    match_type: MatchType
    match_reason: str
    selected_game_relevant: bool
    distance: int | None = None

    @property
    def display_text(self) -> str:
        number = f"#{self.record.jersey_number}" if self.record.jersey_number else "#—"
        return (
            f"{self.record.player_name} · {self.record.team_code} · {number} · "
            f"{self.record.position or 'Position unavailable'} · "
            f"{self.record.roster_status}"
        )


@dataclass(frozen=True)
class PlayerSearchResponse:
    parsed: ParsedPlayerQuery
    results: tuple[PlayerSearchResult, ...]
    total_matches: int
    effective_scope: str
    out_of_scope_exact: tuple[PlayerSearchRecord, ...] = ()
    truncated: bool = False
    empty_message: str = ""
    selected_player_id: str | None = None

    @property
    def is_possible_typo(self) -> bool:
        return bool(self.results) and all(
            result.match_type is MatchType.FUZZY for result in self.results
        )


def normalize_search_text(value) -> str:
    if value is None:
        source = ""
    else:
        try:
            source = "" if pd.isna(value) else str(value)
        except (TypeError, ValueError):
            source = str(value)
    text = unicodedata.normalize("NFKD", source.strip().casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_position(value) -> str:
    text = _clean_text(value).upper()
    if text in {"RHP", "LHP", "PITCHER"}:
        return "P"
    return text


_TEAM_ALIASES = {
    normalize_search_text(alias): code
    for short, code in TEAM_CODES.items()
    for alias in (short, TEAM_NAMES[short], code)
}
_POSITIONS = {
    "P",
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "LF",
    "CF",
    "RF",
    "OF",
    "IF",
    "UTIL",
    "DP",
    "FLEX",
}
_STATUS_ALIASES = {
    "active": "Active",
    "inactive": "Inactive",
    "reserve": "Reserve Athlete Pool",
    "reserve athlete pool": "Reserve Athlete Pool",
    "unknown": "Status Unknown",
    "status unknown": "Status Unknown",
}
_FILTER_KEYS = {
    "team": "team_code",
    "pos": "position",
    "position": "position",
    "status": "roster_status",
    "number": "jersey_number",
    "name": "name_text",
}


def parse_player_query(query) -> ParsedPlayerQuery:
    raw = str(query or "").strip()
    if not raw:
        return ParsedPlayerQuery(raw_query="")
    backslash_sentinel = "\u0000"
    try:
        lexer = shlex.shlex(
            raw.replace("\\", backslash_sentinel),
            posix=True,
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.quotes = '"'
        tokens = [
            token.replace(backslash_sentinel, "\\")
            for token in lexer
        ]
    except ValueError as exc:
        return ParsedPlayerQuery(
            raw_query=raw,
            issues=(QueryIssue(f"Malformed quoted value: {exc}", raw),),
        )

    values: dict[str, str | None] = {
        "team_code": None,
        "position": None,
        "roster_status": None,
        "jersey_number": None,
        "name_text": "",
    }
    free: list[str] = []
    issues: list[QueryIssue] = []
    for token in tokens:
        if re.fullmatch(r"#\d+", token):
            key, raw_value = "jersey_number", token[1:]
        elif re.fullmatch(r"\d+", token):
            key, raw_value = "jersey_number", token
        elif ":" in token:
            raw_key, raw_value = token.split(":", 1)
            if len(raw_key) == 1 and raw_key.isalpha():
                free.append(token)
                continue
            key = _FILTER_KEYS.get(raw_key.casefold())
            if key is None:
                issues.append(QueryIssue(f"Unknown filter '{raw_key}'", token))
                continue
        else:
            free.append(token)
            continue
        if not raw_value.strip():
            issues.append(QueryIssue("Filter value cannot be empty", token))
            continue
        normalized = _normalize_filter_value(key, raw_value)
        if normalized is None:
            issues.append(QueryIssue(f"Invalid value for {key.replace('_', ' ')}", token))
            continue
        existing = values[key]
        if existing not in (None, "") and existing != normalized:
            issues.append(QueryIssue(f"Conflicting values for {key.replace('_', ' ')}", token))
            continue
        values[key] = normalized
    return ParsedPlayerQuery(
        raw_query=raw,
        free_text=" ".join(free),
        name_text=str(values["name_text"] or ""),
        team_code=values["team_code"],
        position=values["position"],
        roster_status=values["roster_status"],
        jersey_number=values["jersey_number"],
        issues=tuple(issues),
    )


def search_player_index(
    index: PlayerSearchIndex,
    parsed: ParsedPlayerQuery,
    *,
    scope: SearchScope,
    selected_team_codes: Iterable[str],
    limit: int = 50,
) -> PlayerSearchResponse:
    if not parsed.valid:
        return PlayerSearchResponse(
            parsed=parsed,
            results=(),
            total_matches=0,
            effective_scope=_scope_label(scope, selected_team_codes),
            empty_message="Fix the search filters shown above.",
        )
    limit = max(1, min(int(limit), 200))
    selected_codes = {
        _clean_text(code).upper() for code in selected_team_codes if _clean_text(code)
    }
    if parsed.team_code:
        scope_records = tuple(
            record for record in index.records if record.team_code == parsed.team_code
        )
        effective_scope = f"Explicit team filter: {parsed.team_code}"
    elif scope is SearchScope.SELECTED_GAME:
        scope_records = tuple(
            record for record in index.records if record.team_code in selected_codes
        )
        effective_scope = (
            "Selected game teams: " + " / ".join(sorted(selected_codes))
            if selected_codes
            else "Selected game teams unavailable"
        )
    else:
        scope_records = index.records
        effective_scope = "All players"

    filtered = tuple(record for record in scope_records if _passes_filters(record, parsed))
    ranked = [
        _rank_record(record, parsed.search_text, selected_codes)
        for record in filtered
    ]
    ranked = [result for result in ranked if result is not None]
    ranked.sort(key=_result_sort_key)

    out_of_scope: tuple[PlayerSearchRecord, ...] = ()
    if (
        not ranked
        and not parsed.team_code
        and scope is SearchScope.SELECTED_GAME
        and parsed.search_text
    ):
        candidates = [
            record
            for record in index.records
            if record.team_code not in selected_codes and _passes_filters(record, parsed)
        ]
        exact = []
        for record in candidates:
            result = _rank_record(record, parsed.search_text, selected_codes)
            if result and result.match_type in {
                MatchType.EXACT_FULL_NAME,
                MatchType.EXACT_ALIAS,
            }:
                exact.append(record)
        out_of_scope = tuple(
            sorted(exact, key=lambda item: (item.normalized_name, item.player_id))
        )

    total = len(ranked)
    visible = tuple(ranked[:limit])
    if out_of_scope:
        empty_message = (
            f"Exact player found outside the selected game: "
            f"{out_of_scope[0].player_name} ({out_of_scope[0].team_code}). "
            "Switch to All Players or add an explicit team filter."
        )
    elif not visible:
        empty_message = (
            "No players match these filters in the current scope."
            if parsed.has_filters or parsed.search_text
            else "No players are available in the current scope."
        )
    else:
        empty_message = ""
    return PlayerSearchResponse(
        parsed=parsed,
        results=visible,
        total_matches=total,
        effective_scope=effective_scope,
        out_of_scope_exact=out_of_scope,
        truncated=total > len(visible),
        empty_message=empty_message,
    )


def _normalize_filter_value(key: str, value: str) -> str | None:
    text = _clean_text(value)
    if key == "team_code":
        return _TEAM_ALIASES.get(normalize_search_text(text))
    if key == "position":
        position = normalize_position(text)
        return position if position in _POSITIONS else None
    if key == "roster_status":
        return _STATUS_ALIASES.get(normalize_search_text(text))
    if key == "jersey_number":
        match = re.fullmatch(r"#?\s*(\d{1,3})", text)
        return str(int(match.group(1))) if match else None
    if key == "name_text":
        return text or None
    return None


def _passes_filters(record: PlayerSearchRecord, parsed: ParsedPlayerQuery) -> bool:
    return (
        (parsed.team_code is None or record.team_code == parsed.team_code)
        and (parsed.position is None or record.position == parsed.position)
        and (
            parsed.roster_status is None
            or record.roster_status == parsed.roster_status
        )
        and (
            parsed.jersey_number is None
            or record.jersey_number == parsed.jersey_number
        )
    )


def _rank_record(
    record: PlayerSearchRecord, search_text: str, selected_codes: set[str]
) -> PlayerSearchResult | None:
    query = normalize_search_text(search_text)
    relevant = record.team_code in selected_codes
    if not query:
        return PlayerSearchResult(
            record=record,
            match_type=MatchType.FILTER,
            match_reason="Matches all selected filters",
            selected_game_relevant=relevant,
        )
    if query == record.normalized_name:
        return PlayerSearchResult(
            record, MatchType.EXACT_FULL_NAME, "Exact full-name match", relevant
        )
    if query in record.normalized_aliases:
        return PlayerSearchResult(
            record, MatchType.EXACT_ALIAS, "Exact approved-alias match", relevant
        )
    if query in record.name_tokens:
        return PlayerSearchResult(
            record, MatchType.EXACT_TOKEN, "Exact name-token match", relevant
        )
    fields = (record.normalized_name, *record.normalized_aliases)
    if any(field.startswith(query) for field in fields) or any(
        token.startswith(query) for token in record.name_tokens
    ):
        return PlayerSearchResult(
            record, MatchType.PREFIX, "Name prefix match", relevant
        )
    if query and any(query in field for field in fields):
        return PlayerSearchResult(
            record, MatchType.SUBSTRING, "Name substring match", relevant
        )
    maximum = _fuzzy_max_distance(query)
    if maximum <= 0:
        return None
    fuzzy_fields = (*fields, *record.name_tokens)
    distances = [
        bounded_damerau_levenshtein(query, field, maximum)
        for field in fuzzy_fields
    ]
    distance = min((value for value in distances if value is not None), default=None)
    if distance is None:
        return None
    return PlayerSearchResult(
        record,
        MatchType.FUZZY,
        f"Possible typo match ({distance} edit{'s' if distance != 1 else ''})",
        relevant,
        distance=distance,
    )


_MATCH_ORDER = {
    MatchType.EXACT_FULL_NAME: 0,
    MatchType.EXACT_ALIAS: 1,
    MatchType.EXACT_TOKEN: 2,
    MatchType.PREFIX: 3,
    MatchType.SUBSTRING: 4,
    MatchType.FUZZY: 5,
    MatchType.FILTER: 6,
}


def _result_sort_key(result: PlayerSearchResult):
    return (
        _MATCH_ORDER[result.match_type],
        result.distance if result.distance is not None else 0,
        0 if result.selected_game_relevant else 1,
        0 if result.record.is_active else 1,
        result.record.normalized_name,
        result.record.player_id,
    )


def _scope_label(scope: SearchScope, team_codes: Iterable[str]) -> str:
    codes = sorted({_clean_text(code).upper() for code in team_codes if _clean_text(code)})
    if scope is SearchScope.SELECTED_GAME:
        return "Selected game teams: " + " / ".join(codes) if codes else "Selected game teams unavailable"
    return "All players"


def _fuzzy_max_distance(query: str) -> int:
    compact_length = len(query.replace(" ", ""))
    if compact_length < 5:
        return 0
    if compact_length < 9:
        return 1
    return 2


def bounded_damerau_levenshtein(
    left: str, right: str, maximum: int
) -> int | None:
    """Return edit distance up to ``maximum``, including adjacent swaps."""

    if abs(len(left) - len(right)) > maximum:
        return None
    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_minimum = left_index
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                current[right_index - 1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + cost,
            )
            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left_char == right[right_index - 2]
                and left[left_index - 2] == right_char
            ):
                value = min(value, previous_previous[right_index - 2] + 1)
            current.append(value)
            row_minimum = min(row_minimum, value)
        if row_minimum > maximum:
            return None
        previous_previous, previous = previous, current
    distance = previous[-1]
    return distance if distance <= maximum else None


def _clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).strip().split())


def _identifier(value) -> str:
    text = _clean_text(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _jersey(value) -> str:
    text = _identifier(value)
    if not text:
        return ""
    match = re.fullmatch(r"\d{1,3}", text)
    return str(int(text)) if match else ""


def _approved_aliases(value) -> tuple[str, ...]:
    text = _clean_text(value)
    if not text:
        return ()
    return tuple(
        item.strip()
        for item in re.split(r"[|;]", text)
        if item.strip()
    )
