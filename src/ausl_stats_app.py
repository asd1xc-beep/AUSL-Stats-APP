"""Tkinter game-day lookup tool for Athletes Unlimited Softball League."""

from __future__ import annotations

import copy
import json
import math
import queue
import re
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from tkinter import messagebox, ttk

import pandas as pd

from ausl_data import (
    SEASONS,
    TEAM_CODES,
    TEAM_NAMES,
    media_guide_source_context,
    _deduplicate_official_game_notes,
    CancelToken,
    RefreshCancelled,
    canonical_pitching_whip,
    empty_locked_lineup_store,
    export_dir,
    fetch_live_game,
    innings_to_outs,
    load_database,
    load_refresh_attempt,
    media_approval_record_id,
    migrate_locked_lineups_file,
    migrate_manual_notes_file,
    normalize_roster_status,
    outs_to_innings,
    update_all_data,
    write_locked_lineups_atomic,
    write_manual_notes_atomic,
)
from ausl_logging import configure_logging, log_event
from ausl_readiness import GameDayReadiness, aggregate_game_day_readiness


CURRENT_YEAR = max(SEASONS)
TEAM_OPTIONS = sorted(TEAM_NAMES.values())
TEAM_TO_CODE = {full: TEAM_CODES[short] for short, full in TEAM_NAMES.items()}
CODE_TO_TEAM = {code: team for team, code in TEAM_TO_CODE.items()}
VERIFY_NOTE = "Verify lineups, player availability, and milestones before air."
CAREER_LABEL = f"AUSL Career Totals, {min(SEASONS)}-{max(SEASONS)}"
CAREER_COPY_LABEL = f"AUSL CAREER {min(SEASONS)}–{str(max(SEASONS))[-2:]}"
PITCHER_POSITIONS = {"P", "RHP", "LHP"}
LINEUP_POSITIONS = {
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
COPY_KIND_ALIASES = {
    "player_id": "player_id",
    "season_stat": "season_stat",
    "career_stat": "career_stat",
    "announcer_note": "announcer_note",
    "jersey": "player_id",
    "lower": "season_stat",
    "full": "career_stat",
    "note": "announcer_note",
}
PACKET_FILENAME_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{12}Z)_game_(?P<game_id>\d+)"
    r"(?:_r(?P<revision>\d+))?_producer_packet\.txt$"
)


def value(row, key, default="—"):
    if row is None or key not in row or pd.isna(row[key]) or row[key] == "":
        return default
    return row[key]


def whole(row, key):
    item = value(row, key, None)
    if pd.api.types.is_bool(item):
        return "—"
    try:
        number = float(item)
        if not math.isfinite(number) or not number.is_integer():
            return "—"
        return str(int(number))
    except (TypeError, ValueError, OverflowError):
        return "—"


def _air_ready_enrichment_rows(frame):
    """Return only rows explicitly marked as not needing review."""

    if frame is None or frame.empty or "needs_review" not in frame.columns:
        return pd.DataFrame(columns=getattr(frame, "columns", None))

    def approved(value):
        if value is None or pd.isna(value):
            return False
        if pd.api.types.is_bool(value):
            return not bool(value)
        return str(value).strip().lower() in {"false", "0", "no"}

    return frame[frame["needs_review"].map(approved)].copy()


def _explicitly_false(value):
    if value is None or pd.isna(value):
        return False
    if pd.api.types.is_bool(value):
        return not bool(value)
    return str(value).strip().casefold() in {"false", "0", "no"}


def _canonical_media_review_state(
    row, *, expected_entity_type=None, expected_entity_id=None
):
    """Return VERIFIED only for one internally consistent approval record."""

    if row is None or not hasattr(row, "get"):
        return "VERIFY"
    entity_type = _manual_note_text(row.get("entity_type")).casefold()
    entity_id = _manual_note_identifier(row.get("entity_id"))
    expected_id = _manual_note_identifier(expected_entity_id)
    page_pattern = re.compile(r"^\d+(?:-\d+)?$")
    printed_pages = _manual_note_text(row.get("expected_printed_pages"))
    pdf_pages = _manual_note_text(row.get("parsed_pdf_pages"))
    try:
        confidence = float(row.get("confidence_score"))
    except (TypeError, ValueError, OverflowError):
        confidence = float("nan")
    try:
        date.fromisoformat(_manual_note_text(row.get("guide_date")))
        guide_date_valid = True
    except ValueError:
        guide_date_valid = False

    record_id = _manual_note_text(row.get("approval_record_id"))
    record_matches = bool(record_id) and record_id == media_approval_record_id(row)
    method = _manual_note_text(row.get("approval_method")).casefold()
    if method == "parser_exact_identity":
        approval_actor_valid = (
            _manual_note_text(row.get("parser_version")).casefold()
            == "media-toc-v1"
        )
    elif method == "manual":
        try:
            approved_at = datetime.fromisoformat(
                _manual_note_text(row.get("approved_at")).replace("Z", "+00:00")
            )
            approval_actor_valid = (
                approved_at.tzinfo is not None
                and bool(_manual_note_text(row.get("approved_by")))
            )
        except ValueError:
            approval_actor_valid = False
    else:
        approval_actor_valid = False

    valid = (
        _explicitly_false(row.get("needs_review"))
        and _manual_note_text(row.get("match_status")).casefold() == "verified"
        and _manual_note_text(row.get("approval_state")).casefold() == "approved"
        and not _manual_note_text(row.get("warnings"))
        and math.isfinite(confidence)
        and confidence >= 0.75
        and bool(_manual_note_text(row.get("entity_name")))
        and bool(_manual_note_text(row.get("source_name")))
        and page_pattern.fullmatch(printed_pages) is not None
        and page_pattern.fullmatch(pdf_pages) is not None
        and guide_date_valid
        and record_matches
        and approval_actor_valid
    )
    if expected_entity_type is not None:
        valid = valid and entity_type == str(expected_entity_type).strip().casefold()
    if expected_entity_id is not None:
        valid = valid and entity_id == expected_id
    return "VERIFIED" if valid else "VERIFY"


def _air_ready_media_rows(
    frame, *, expected_entity_type=None, expected_entity_id=None
):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=getattr(frame, "columns", None))
    approved = frame.apply(
        lambda row: _canonical_media_review_state(
            row,
            expected_entity_type=expected_entity_type,
            expected_entity_id=expected_entity_id,
        )
        == "VERIFIED",
        axis=1,
    )
    return frame[approved].copy()


def _media_guide_date_label(item):
    text = str(item or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text or "date unavailable"
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _format_rate_value(item, places=3):
    try:
        number = float(item)
        if not math.isfinite(number):
            return "—"
    except (TypeError, ValueError, OverflowError):
        return "—"
    rendered = f"{number:.{places}f}"
    if rendered.startswith("0."):
        return rendered[1:]
    if rendered.startswith("-0."):
        return "-" + rendered[2:]
    return rendered


def rate(row, key, places=3):
    return _format_rate_value(value(row, key, None), places)


def _format_decimal_value(item, places=2):
    try:
        number = float(item)
        if not math.isfinite(number):
            return "—"
        return f"{number:.{places}f}"
    except (TypeError, ValueError, OverflowError):
        return "—"


def _format_whole_value(item):
    if pd.api.types.is_bool(item):
        return "—"
    try:
        number = float(item)
        if not math.isfinite(number) or not number.is_integer():
            return "—"
        return str(int(number))
    except (TypeError, ValueError, OverflowError):
        return "—"


def _format_innings_value(item):
    outs = innings_to_outs(item)
    return outs_to_innings(outs) or "—"


def decimal(row, key, places=2):
    item = value(row, key, None)
    return _format_decimal_value(item, places)


def _optional_int(row, key):
    item = value(row, key, None)
    if pd.api.types.is_bool(item):
        return None
    try:
        number = float(item)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _optional_float(row, key):
    item = value(row, key, None)
    if pd.api.types.is_bool(item):
        return None
    try:
        number = float(item)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _optional_text(row, key):
    item = value(row, key, None)
    if item is None:
        return None
    text = str(item).strip()
    return text if text and text.lower() not in {"nan", "none"} else None


def _verified_source_timestamp(row, *keys):
    """Return a parseable timezone-aware source timestamp, or no fact."""

    for key in keys:
        text = _optional_text(row, key)
        if text in {None, "-1", "-1.0"}:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return text
    return None


def _manual_note_text(item):
    if item is None:
        return ""
    try:
        if pd.isna(item):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(item).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _manual_note_identifier(item):
    """Normalize CSV integer artifacts without guessing between distinct IDs."""

    text = _manual_note_text(item)
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        return str(int(float(text)))
    return text


def select_manual_notes(
    notes,
    *,
    player_id=None,
    team_code=None,
    game_id=None,
    include_global=False,
):
    """Select only explicitly scoped notes for the supplied exact identities."""

    if not isinstance(notes, pd.DataFrame):
        return pd.DataFrame()
    if notes.empty or "scope" not in notes:
        return notes.iloc[0:0].copy()

    scopes = notes["scope"].map(_manual_note_text).str.lower()
    selected = pd.Series(False, index=notes.index, dtype=bool)

    player_token = _manual_note_identifier(player_id)
    if player_token and "player_id" in notes:
        selected |= scopes.eq("player") & notes["player_id"].map(
            _manual_note_identifier
        ).eq(player_token)

    team_token = _manual_note_text(team_code).upper()
    if team_token and "team_code" in notes:
        selected |= scopes.eq("team") & notes["team_code"].map(
            lambda item: _manual_note_text(item).upper()
        ).eq(team_token)

    game_token = _manual_note_identifier(game_id)
    if game_token and "game_id" in notes:
        selected |= scopes.eq("game") & notes["game_id"].map(
            _manual_note_identifier
        ).eq(game_token)

    if include_global:
        selected |= scopes.eq("global")

    return notes.loc[selected].copy()


def manual_note_player_choices(roster):
    if not isinstance(roster, pd.DataFrame) or roster.empty:
        return []
    if not {"player_id", "player_name"}.issubset(roster.columns):
        return []
    choices = []
    for _, row in roster.iterrows():
        player_id = _manual_note_identifier(row.get("player_id"))
        player_name = _manual_note_text(row.get("player_name"))
        if not player_id or not player_name:
            continue
        team_code = _manual_note_text(row.get("team_code")).upper() or "NO TEAM"
        choices.append(f"{player_name} | {team_code} | ID {player_id}")
    return sorted(set(choices), key=str.casefold)


def resolve_manual_note_player(roster, selection):
    """Resolve a picker value or unique exact name; never use substring matching."""

    typed = _manual_note_text(selection)
    if not typed:
        return None, "Select an exact player before saving"
    if not isinstance(roster, pd.DataFrame) or roster.empty:
        return None, "Player roster is unavailable; note was not saved"
    if not {"player_id", "player_name"}.issubset(roster.columns):
        return None, "Player roster identities are unavailable; note was not saved"

    explicit_id = ""
    id_match = re.search(r"\|\s*ID\s+(.+?)\s*$", typed, flags=re.IGNORECASE)
    if id_match:
        explicit_id = _manual_note_identifier(id_match.group(1))
        matches = roster[
            roster["player_id"].map(_manual_note_identifier).eq(explicit_id)
        ]
        if len(matches) == 1:
            row = matches.iloc[0]
            expected = (
                f"{_manual_note_text(row.get('player_name'))} | "
                f"{_manual_note_text(row.get('team_code')).upper() or 'NO TEAM'} | "
                f"ID {_manual_note_identifier(row.get('player_id'))}"
            )
            if typed.casefold() == expected.casefold():
                return row, ""
        return None, "Player selection is unresolved; choose an exact picker entry"

    matches = roster[
        roster["player_name"].map(_manual_note_text).str.casefold().eq(typed.casefold())
    ]
    if len(matches) > 1:
        return None, "Multiple players have that name; choose an exact ID from the picker"
    if len(matches) == 1:
        return matches.iloc[0], ""
    return None, "Player selection is unresolved; choose an exact picker entry"


@dataclass(frozen=True)
class SelectedGame:
    game_id: str
    season: int
    date_time: datetime
    away_team: str
    home_team: str
    away_team_code: str
    home_team_code: str
    time_zone: str
    venue: str
    status: str
    source_updated_at: str
    source_name: str
    source_url: str | None = None

    @property
    def first_pitch_label(self):
        clock = self.date_time.strftime("%b %d, %Y %I:%M %p").replace(
            " 0", " "
        )
        return f"{clock} {self.time_zone}".strip()

    @property
    def choice_label(self):
        return (
            f"{self.first_pitch_label} | {self.away_team_code} at {self.home_team_code} | "
            f"GAME {self.game_id} | {self.status}"
        )

    @property
    def context_label(self):
        venue = self.venue or "Venue unavailable"
        return (
            f"[OFFICIAL] Game ID {self.game_id} | {self.away_team} at "
            f"{self.home_team} | {self.first_pitch_label} | {venue} | "
            f"{self.status} | Source: "
            f"{self.source_name} | Updated: {self.source_updated_at}"
        )


@dataclass(frozen=True)
class LiveRequestToken:
    selected_game_id: str
    generation: int


@dataclass(frozen=True)
class LiveFeedHealth:
    state: str
    connection_state: str
    stale: bool | None
    last_updated: str
    age_seconds: int | None
    detail: str

    @property
    def label(self):
        return (
            f"[{self.state} | {self.connection_state} | {self.detail}] "
            f"Last updated: {self.last_updated or 'unavailable'}"
        )


def live_feed_health(game, *, now=None, stale_after_seconds=120):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Live-health comparison time must be timezone-aware")
    raw_updated = (
        _manual_note_text(game.get("lastUpdated"))
        if isinstance(game, dict)
        else ""
    )
    if not raw_updated:
        return LiveFeedHealth(
            "RED",
            "CONNECTED",
            None,
            "",
            None,
            "UPDATE TIME UNAVAILABLE",
        )
    try:
        parsed = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
    except ValueError:
        return LiveFeedHealth(
            "RED",
            "CONNECTED",
            None,
            raw_updated,
            None,
            "UPDATE TIME INVALID",
        )
    if parsed.tzinfo is None:
        return LiveFeedHealth(
            "RED",
            "CONNECTED",
            None,
            raw_updated,
            None,
            "UPDATE TIME INVALID",
        )
    age = int((current.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    if age < -300:
        return LiveFeedHealth(
            "RED",
            "CONNECTED",
            None,
            parsed.isoformat(),
            age,
            "UPDATE TIME IN FUTURE",
        )
    if age > stale_after_seconds:
        return LiveFeedHealth(
            "YELLOW",
            "CONNECTED",
            True,
            parsed.isoformat(),
            age,
            f"STALE — {age // 60} MIN OLD",
        )
    return LiveFeedHealth(
        "GREEN",
        "CONNECTED",
        False,
        parsed.isoformat(),
        max(age, 0),
        "CURRENT",
    )


@dataclass(frozen=True)
class OfficialGameNote:
    game_id: str
    category: str
    text: str
    subject_player_id: str
    subject_player_name: str
    subject_team_code: str
    opposing_team_code: str
    verification_state: str
    source_date: str
    source_pdf: str
    source_page: str
    source_url: str
    source_history: str
    confidence_score: float

    @property
    def air_ready(self):
        return self.verification_state == "VERIFIED"


@dataclass(frozen=True)
class ProducerStoryline:
    title: str
    summary: str
    source_label: str

    def render(self):
        source = f" | {self.source_label}" if self.source_label else ""
        return f"- {self.title}: {self.summary}{source}"


@dataclass(frozen=True)
class ProducerPrep:
    title: str
    game_context: tuple[str, ...]
    top_storylines: tuple[ProducerStoryline, ...]
    availability: tuple[str, ...]
    offense: tuple[str, ...]
    pitching: tuple[str, ...]
    matchup_history: tuple[str, ...]
    milestones: tuple[str, ...]
    official_notes: tuple[str, ...]
    players_to_watch: tuple[str, ...]
    graphics_queue: tuple[str, ...]
    verification_queue: tuple[str, ...]

    def section_items(self, section):
        if section == "TOP STORYLINES":
            return tuple(storyline.render() for storyline in self.top_storylines)
        mapping = {
            "GAME CONTEXT": self.game_context,
            "AVAILABILITY": self.availability,
            "OFFENSE": self.offense,
            "PITCHING": self.pitching,
            "MATCHUP HISTORY": self.matchup_history,
            "MILESTONES": self.milestones,
            "OFFICIAL GAME NOTES": self.official_notes,
            "PLAYERS TO WATCH": self.players_to_watch,
            "READY-MADE GRAPHICS QUEUE": self.graphics_queue,
            "VERIFICATION QUEUE": self.verification_queue,
        }
        return mapping[section]

    def render_sections(self, sections):
        lines = []
        for section in sections:
            if lines:
                lines.append("")
            lines.extend([section, *self.section_items(section)])
        return lines

    def render_lines(self):
        sections = (
            "GAME CONTEXT",
            "TOP STORYLINES",
            "AVAILABILITY",
            "OFFENSE",
            "PITCHING",
            "MATCHUP HISTORY",
            "MILESTONES",
            "OFFICIAL GAME NOTES",
            "PLAYERS TO WATCH",
            "READY-MADE GRAPHICS QUEUE",
            "VERIFICATION QUEUE",
        )
        return [self.title, "", *self.render_sections(sections)]


@dataclass(frozen=True)
class LineupIssue:
    code: str
    message: str
    line_number: int | None = None


@dataclass
class LineupValidationResult:
    errors: list[LineupIssue] = field(default_factory=list)
    warnings: list[LineupIssue] = field(default_factory=list)
    normalized_lineup: list[dict] = field(default_factory=list)
    flex: dict | None = None
    starting_pitcher: dict | None = None


def _lineup_text_parts(raw, line_number):
    line = raw.strip()
    flex_match = re.match(r"^FLEX[\).:\-\s]+(.*)$", line, flags=re.IGNORECASE)
    order_match = re.match(r"^(\d+)[\).\-\s]+(.*)$", line)
    is_flex_label = flex_match is not None
    if flex_match:
        batting_order = None
        body = flex_match.group(1).strip()
    elif order_match:
        batting_order = int(order_match.group(1))
        body = order_match.group(2).strip()
    else:
        batting_order = None
        body = line
    jersey_match = re.search(r"#\s*(\d+)", body)
    jersey = jersey_match.group(1) if jersey_match else ""
    body = re.sub(r"#\s*\d+", "", body).strip(" -|")
    parts = [
        part.strip()
        for part in re.split(r"\s+[-|]\s+|\s{2,}", body)
        if part.strip()
    ]
    name = parts[0] if parts else body
    position = parts[1].upper() if len(parts) > 1 else ""
    return {
        "batting_order": batting_order,
        "player_name": name,
        "jersey_number": jersey,
        "position": position,
        "raw_line": raw,
        "line_number": line_number,
        "is_flex_label": is_flex_label,
    }


def _lineup_player_matches(roster, name, jersey=""):
    if not isinstance(roster, pd.DataFrame) or roster.empty:
        return pd.DataFrame(columns=getattr(roster, "columns", None))
    if "player_name" not in roster.columns:
        return roster.iloc[0:0]
    matches = roster[
        roster["player_name"].astype(str).str.strip().str.casefold().eq(name.strip().casefold())
    ]
    if jersey and len(matches) > 1 and "jersey_number" in matches.columns:
        normalized_jerseys = (
            matches["jersey_number"].astype(str).str.replace(".0", "", regex=False).str.strip()
        )
        matches = matches[normalized_jerseys.eq(str(jersey))]
    return matches


def _normalized_lineup_player(entry, row):
    jersey = _optional_text(row, "jersey_number") or entry["jersey_number"]
    if jersey and jersey.endswith(".0"):
        jersey = jersey[:-2]
    position = entry["position"] or (_optional_text(row, "position") or "").upper()
    return {
        "batting_order": entry["batting_order"],
        "player_id": _manual_note_identifier(row.get("player_id")),
        "player_name": _optional_text(row, "player_name") or entry["player_name"],
        "jersey_number": jersey,
        "position": position,
        "roster_status": normalize_roster_status(row.get("roster_status")),
        "raw_line": entry["raw_line"],
        "line_number": entry["line_number"],
    }


def validate_lineup_text(
    text,
    *,
    roster,
    team,
    starter,
    source="manual",
    game_time=None,
    lineup_timestamp=None,
    starter_position_exception=None,
):
    """Parse and validate one team's lineup without guessing player identity."""
    result = LineupValidationResult()
    parsed = [
        _lineup_text_parts(raw, line_number)
        for line_number, raw in enumerate(str(text or "").splitlines(), 1)
        if raw.strip()
    ]
    resolved_entries = []
    flex_entries = []
    dp_entries = []

    for entry in parsed:
        line_number = entry["line_number"]
        position = entry["position"]
        numbered_flex = position == "FLEX" and entry["batting_order"] is not None
        if numbered_flex or (entry["is_flex_label"] and position != "FLEX"):
            result.errors.append(
                LineupIssue(
                    "malformed_dp_flex",
                    "FLEX must be a separate unnumbered 'FLEX.' entry with position FLEX.",
                    line_number,
                )
            )
        if position == "DP/FLEX" or (position and position not in LINEUP_POSITIONS):
            result.errors.append(
                LineupIssue(
                    "invalid_position",
                    f"Position '{position}' is not a supported lineup position.",
                    line_number,
                )
            )

        matches = _lineup_player_matches(
            roster, entry["player_name"], entry["jersey_number"]
        )
        if len(matches) == 0:
            result.errors.append(
                LineupIssue(
                    "unresolved_player",
                    f"Player '{entry['player_name']}' was not resolved exactly.",
                    line_number,
                )
            )
            continue
        if len(matches) > 1:
            result.errors.append(
                LineupIssue(
                    "ambiguous_player",
                    f"Player '{entry['player_name']}' matches more than one roster identity.",
                    line_number,
                )
            )
            continue

        row = matches.iloc[0]
        resolved = _normalized_lineup_player(entry, row)
        if (_optional_text(row, "team") or "").casefold() != str(team).casefold():
            result.errors.append(
                LineupIssue(
                    "wrong_team",
                    f"{resolved['player_name']} is not assigned to {team}.",
                    line_number,
                )
            )
        status = resolved["roster_status"]
        if status.casefold() != "active":
            result.warnings.append(
                LineupIssue(
                    "roster_status",
                    f"{resolved['player_name']} roster status is {status}; confirmation required.",
                    line_number,
                )
            )
        if not _optional_text(row, "jersey_number"):
            result.warnings.append(
                LineupIssue(
                    "missing_jersey",
                    f"{resolved['player_name']} has no roster jersey number.",
                    line_number,
                )
            )
        if not _optional_text(row, "position"):
            result.warnings.append(
                LineupIssue(
                    "missing_position",
                    f"{resolved['player_name']} has no roster position.",
                    line_number,
                )
            )
        resolved_entries.append(resolved)
        if entry["is_flex_label"]:
            flex_entries.append(resolved)
        elif position == "DP":
            dp_entries.append(resolved)

    hitters = [
        entry
        for entry in resolved_entries
        if entry not in flex_entries and entry["position"] != "FLEX"
    ]
    orders = [entry["batting_order"] for entry in hitters]
    if sorted(order for order in orders if isinstance(order, int)) != list(range(1, 10)):
        result.errors.append(
            LineupIssue(
                "batting_order",
                "Batting order must contain each position 1 through 9 exactly once.",
                next(
                    (
                        entry["line_number"]
                        for entry in hitters
                        if entry["batting_order"] not in range(1, 10)
                        or orders.count(entry["batting_order"]) > 1
                    ),
                    1,
                ),
            )
        )

    player_lines = {}
    for entry in resolved_entries:
        player_id = entry["player_id"]
        if player_id in player_lines:
            result.errors.append(
                LineupIssue(
                    "duplicate_player",
                    f"{entry['player_name']} appears more than once.",
                    entry["line_number"],
                )
            )
        else:
            player_lines[player_id] = entry["line_number"]

    if len(flex_entries) > 1 or (flex_entries and len(dp_entries) != 1) or (
        dp_entries and len(flex_entries) != 1
    ):
        result.errors.append(
            LineupIssue(
                "malformed_dp_flex",
                "DP/FLEX requires one DP in the nine-player order and one separate FLEX entry.",
                (flex_entries or dp_entries or [{"line_number": 1}])[0]["line_number"],
            )
        )

    starter_text = str(starter or "").strip()
    if not starter_text:
        result.errors.append(
            LineupIssue("missing_starter", "A starting pitcher is required.", 0)
        )
    else:
        starter_matches = _lineup_player_matches(roster, starter_text)
        if len(starter_matches) == 0:
            result.errors.append(
                LineupIssue(
                    "unresolved_player",
                    f"Starting pitcher '{starter_text}' was not resolved exactly.",
                    0,
                )
            )
        elif len(starter_matches) > 1:
            result.errors.append(
                LineupIssue(
                    "ambiguous_player",
                    f"Starting pitcher '{starter_text}' matches more than one roster identity.",
                    0,
                )
            )
        else:
            starter_row = starter_matches.iloc[0]
            starter_entry = {
                "batting_order": None,
                "player_name": starter_text,
                "jersey_number": "",
                "position": "",
                "raw_line": starter_text,
                "line_number": 0,
            }
            result.starting_pitcher = _normalized_lineup_player(
                starter_entry, starter_row
            )
            if (_optional_text(starter_row, "team") or "").casefold() != str(team).casefold():
                result.errors.append(
                    LineupIssue(
                        "wrong_team",
                        f"Starting pitcher {starter_text} is not assigned to {team}.",
                        0,
                    )
                )
            starter_position = (
                result.starting_pitcher.get("position") or ""
            ).strip().upper()
            exception = (
                starter_position_exception
                if isinstance(starter_position_exception, dict)
                else {}
            )
            exception_valid = (
                _manual_note_identifier(exception.get("player_id"))
                == result.starting_pitcher["player_id"]
                and bool(_manual_note_text(exception.get("reviewer")))
                and bool(_manual_note_text(exception.get("approved_at")))
                and bool(_manual_note_text(exception.get("source")))
            )
            if starter_position not in PITCHER_POSITIONS:
                if exception_valid:
                    result.starting_pitcher["position_exception"] = copy.deepcopy(
                        exception
                    )
                    result.warnings.append(
                        LineupIssue(
                            "two_way_starter_exception",
                            f"Starting pitcher {starter_text} is rostered at "
                            f"{starter_position or 'an unresolved position'}; use requires "
                            "confirmation of the recorded two-way-player exception.",
                            0,
                        )
                    )
                else:
                    result.errors.append(
                        LineupIssue(
                            "starter_position",
                            f"Starting pitcher {starter_text} is rostered at "
                            f"{starter_position or 'an unresolved position'}, not P/RHP/LHP.",
                            0,
                        )
                    )
            starter_status = result.starting_pitcher["roster_status"]
            if starter_status.casefold() != "active":
                result.warnings.append(
                    LineupIssue(
                        "roster_status",
                        f"Starting pitcher {starter_text} roster status is {starter_status}.",
                        0,
                    )
                )

    if str(source or "").strip().casefold().startswith("projected"):
        result.warnings.append(
            LineupIssue(
                "projected_source",
                "This is a projected lineup, not an officially confirmed lineup.",
            )
        )
    if game_time is not None and lineup_timestamp is not None:
        try:
            if lineup_timestamp < game_time - timedelta(hours=6):
                result.warnings.append(
                    LineupIssue(
                        "stale_lineup",
                        "Lineup timestamp is more than six hours before game time.",
                    )
                )
        except TypeError:
            result.warnings.append(
                LineupIssue(
                    "stale_lineup",
                    "Lineup age cannot be verified against game time.",
                )
            )

    result.normalized_lineup = sorted(
        hitters, key=lambda entry: entry["batting_order"] if isinstance(entry["batting_order"], int) else 99
    )
    result.flex = flex_entries[0] if len(flex_entries) == 1 else None
    return result


def producer_packet_filename(selected_game, generated_at, revision=None):
    """Build a collision-resistant filename from authoritative game identity."""
    if (
        not isinstance(selected_game, SelectedGame)
        or not re.fullmatch(r"\d+", str(selected_game.game_id or ""))
    ):
        raise ValueError("An exact official game ID is required for a producer packet")
    if not isinstance(generated_at, datetime) or generated_at.tzinfo is None:
        raise ValueError("A timezone-aware packet generation time is required")
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        revision_number = int(revision) if revision is not None else None
    except (TypeError, ValueError):
        revision_number = None
    revision_part = (
        f"_r{revision_number}" if revision_number is not None and revision_number > 0 else ""
    )
    return (
        f"{stamp}_game_{selected_game.game_id}{revision_part}_producer_packet.txt"
    )


def _official_lineup_provenance_valid(lock):
    if not isinstance(lock, dict):
        return False
    provenance = lock.get("official_provenance")
    if not isinstance(provenance, dict) or provenance.get("verified") is not True:
        return False
    return all(
        _manual_note_text(provenance.get(field_name))
        for field_name in (
            "source_name",
            "source_id",
            "verified_at",
            "verified_by",
        )
    )


def packet_lineup_heading(lock):
    source = (
        str(lock.get("source", "")).strip().casefold()
        if isinstance(lock, dict)
        else ""
    )
    if source == "projected":
        return "SAVED PROJECTED LINEUP — NOT OFFICIAL"
    if source == "manual":
        return "MANUAL LINEUP — VERIFY AGAINST OFFICIAL CARD"
    if source == "imported":
        return "IMPORTED LINEUP — VERIFY SOURCE"
    if source == "official" and _official_lineup_provenance_valid(lock):
        return "OFFICIAL STARTING LINEUP"
    return "LINEUP SOURCE UNAVAILABLE OR UNVERIFIED — DO NOT USE ON AIR"


def packet_starting_pitcher_heading(lock):
    lineup_heading = packet_lineup_heading(lock)
    if lineup_heading == "OFFICIAL STARTING LINEUP":
        return "OFFICIAL STARTING PITCHER"
    return lineup_heading.replace("LINEUP", "STARTING PITCHER")


def _stored_lineup_entry_text(item, *, flex=False):
    if not isinstance(item, dict):
        return ""
    name = _manual_note_text(item.get("player_name"))
    if not name:
        return ""
    jersey_text = _manual_note_text(item.get("jersey_number"))
    jersey = f"#{jersey_text} " if jersey_text else ""
    position_text = _manual_note_text(item.get("position"))
    position = f" — {position_text}" if position_text else ""
    status = _manual_note_text(item.get("roster_status")) or "VERIFY STATUS"
    prefix = "FLEX." if flex else f"{item.get('batting_order')}."
    return f"{prefix} {jersey}{name}{position} | {status}"


def format_stored_packet_lineup(team_data):
    if not isinstance(team_data, dict):
        return []
    lines = [
        rendered
        for rendered in (
            _stored_lineup_entry_text(item)
            for item in team_data.get("lineup", [])
        )
        if rendered
    ]
    flex_line = _stored_lineup_entry_text(team_data.get("flex"), flex=True)
    if flex_line:
        lines.append(flex_line)
    return lines


def write_producer_packet_exclusive(path, content):
    """Create a producer packet without replacing any existing packet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return path


def filter_roster_search(roster, query):
    """Filter roster rows without altering the caller's scope selection."""
    if not isinstance(roster, pd.DataFrame):
        return pd.DataFrame()
    frame = roster.copy()
    query_text = str(query or "").strip().casefold()
    if not query_text:
        return frame

    number_match = re.fullmatch(r"#?\s*(\d+)", query_text)
    if number_match:
        if "jersey_number" not in frame.columns:
            return frame.iloc[0:0]
        number = number_match.group(1)
        jerseys = (
            frame["jersey_number"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.strip()
        )
        return frame[jerseys.eq(number)]

    searchable = []
    for column in ("player_name", "team", "team_code", "position", "college"):
        if column in frame.columns:
            searchable.append(frame[column].fillna("").astype(str))
    if "roster_status" in frame.columns:
        searchable.append(frame["roster_status"].map(normalize_roster_status))
    if not searchable:
        return frame.iloc[0:0]
    fields = pd.concat(searchable, axis=1)
    mask = fields.apply(
        lambda column: column.str.casefold().str.contains(query_text, regex=False)
    ).any(axis=1)
    return frame[mask]


def _selected_game_season(row, game_datetime):
    raw_season = _optional_int(row, "season")
    if raw_season in SEASONS:
        return raw_season
    for calendar_year, official_season_id in SEASONS.items():
        if raw_season == official_season_id:
            return calendar_year
    if game_datetime.year in SEASONS:
        return game_datetime.year
    return None


def official_selected_games(schedule):
    """Return only uniquely identified, source-verifiable official games."""

    if not isinstance(schedule, pd.DataFrame) or schedule.empty:
        return []
    required = {
        "game_id",
        "game_date",
        "away_team_code",
        "home_team_code",
        "source_name",
    }
    if not required.issubset(schedule.columns):
        return []

    identifiers = schedule["game_id"].map(_manual_note_identifier)
    identifier_counts = identifiers[identifiers.ne("")].value_counts()
    games = []
    for index, row in schedule.iterrows():
        game_id = identifiers.loc[index]
        if not game_id or identifier_counts.get(game_id, 0) != 1:
            continue
        if not game_id.isdigit():
            continue

        away_code = (_optional_text(row, "away_team_code") or "").upper()
        home_code = (_optional_text(row, "home_team_code") or "").upper()
        if (
            away_code not in CODE_TO_TEAM
            or home_code not in CODE_TO_TEAM
            or away_code == home_code
        ):
            continue
        away_team = _optional_text(row, "away_team") or CODE_TO_TEAM[away_code]
        home_team = _optional_text(row, "home_team") or CODE_TO_TEAM[home_code]
        if away_team != CODE_TO_TEAM[away_code] or home_team != CODE_TO_TEAM[home_code]:
            continue

        try:
            parsed = pd.to_datetime(row.get("game_date"), errors="raise")
            game_datetime = parsed.to_pydatetime()
        except (TypeError, ValueError, OverflowError):
            continue
        if game_datetime.tzinfo is None:
            continue
        season = _selected_game_season(row, game_datetime)
        if season is None:
            continue

        source_name = _optional_text(row, "source_name")
        source_updated_at = _verified_source_timestamp(
            row, "imported_at", "source_updated_at"
        )
        if source_name != "Official AUSL Schedule" or source_updated_at is None:
            continue

        games.append(
            SelectedGame(
                game_id=game_id,
                season=season,
                date_time=game_datetime,
                away_team=away_team,
                home_team=home_team,
                away_team_code=away_code,
                home_team_code=home_code,
                time_zone=(
                    _optional_text(row, "game_time_zone")
                    or game_datetime.tzname()
                    or "Time zone unavailable"
                ),
                venue=_optional_text(row, "venue") or "Venue unavailable",
                status=_optional_text(row, "status") or "Status unavailable",
                source_updated_at=source_updated_at,
                source_name=source_name,
                source_url=_optional_text(row, "source_url"),
            )
        )
    return sorted(games, key=lambda game: (game.date_time, game.game_id))


def choose_default_selected_game(games, *, today=None):
    if not games:
        return None
    current_date = today or date.today()
    upcoming = [game for game in games if game.date_time.date() >= current_date]
    if upcoming:
        return min(upcoming, key=lambda game: (game.date_time, game.game_id))
    return max(games, key=lambda game: (game.date_time, game.game_id))


@dataclass(frozen=True)
class TeamSnapshot:
    available: bool
    team_code: str
    season: int
    wins: int | None = None
    losses: int | None = None
    runs_for: int | None = None
    runs_against: int | None = None
    run_differential: int | None = None
    streak: str | None = None
    games_back: float | None = None
    rank: int | None = None
    win_percentage: float | None = None
    source_name: str | None = None
    source_url: str | None = None
    source_timestamp: str | None = None
    availability_flags: dict[str, bool] = field(default_factory=dict)
    unavailable_reason: str | None = None

    @property
    def record_text(self):
        if self.wins is None or self.losses is None:
            return "Record unavailable"
        return f"{self.wins}-{self.losses}"

    @property
    def games_played(self):
        if self.wins is None or self.losses is None:
            return None
        return self.wins + self.losses


def official_team_snapshot(team_code, season, database):
    """Return the unique official regular-season row without calculated fallbacks."""

    code = str(team_code or "").strip().upper()
    try:
        calendar_year = int(season)
    except (TypeError, ValueError):
        calendar_year = 0

    def unavailable(reason):
        return TeamSnapshot(
            available=False,
            team_code=code,
            season=calendar_year,
            unavailable_reason=reason,
        )

    season_id = SEASONS.get(calendar_year)
    if not code or season_id is None:
        return unavailable("unknown team or season")
    standings = database.get("standings", pd.DataFrame()) if isinstance(database, dict) else pd.DataFrame()
    required = {"team_code", "seasonId", "standingsTypeLk"}
    if standings.empty or not required.issubset(standings.columns):
        return unavailable("official standings unavailable")

    rows = standings[
        standings["team_code"].astype(str).str.strip().str.upper().eq(code)
        & pd.to_numeric(standings["seasonId"], errors="coerce").eq(season_id)
        & standings["standingsTypeLk"].astype(str).str.strip().eq("SEASON")
    ]
    if len(rows) != 1:
        reason = "official standings row ambiguous" if len(rows) > 1 else "official standings row unavailable"
        return unavailable(reason)

    row = rows.iloc[0]
    source_timestamp = _verified_source_timestamp(
        row, "lastChangeTimestamp", "imported_at"
    )
    facts = {
        "wins": _optional_int(row, "wins"),
        "losses": _optional_int(row, "losses"),
        "runs_for": _optional_int(row, "runsScored"),
        "runs_against": _optional_int(row, "runsAllowed"),
        "run_differential": _optional_int(row, "runDifferential"),
        "streak": _optional_text(row, "winStreak"),
        "games_back": _optional_float(row, "gamesBehind"),
        "rank": _optional_int(row, "rank"),
        "win_percentage": _optional_float(row, "winPercentage"),
    }
    if (
        facts["wins"] is None
        or facts["losses"] is None
        or facts["wins"] < 0
        or facts["losses"] < 0
    ):
        return unavailable("invalid official record")
    if any(
        item is not None and item < 0
        for item in (facts["runs_for"], facts["runs_against"])
    ):
        return unavailable("invalid official run totals")
    if facts["games_back"] is not None and facts["games_back"] < 0:
        return unavailable("invalid official games behind")
    if facts["rank"] is not None and facts["rank"] <= 0:
        return unavailable("invalid official rank")
    if facts["win_percentage"] is not None and not (
        0 <= facts["win_percentage"] <= 1
    ):
        return unavailable("invalid official win percentage")
    if (
        facts["runs_for"] is not None
        and facts["runs_against"] is not None
        and facts["run_differential"] is not None
        and facts["run_differential"]
        != facts["runs_for"] - facts["runs_against"]
    ):
        return unavailable("official run differential is inconsistent")
    source_name = _optional_text(row, "source_name")
    if source_name is None:
        return unavailable("official standings provenance unavailable")
    if source_timestamp is None:
        return unavailable("official standings freshness unavailable")
    return TeamSnapshot(
        available=True,
        team_code=code,
        season=calendar_year,
        **facts,
        source_name=source_name,
        source_url=_optional_text(row, "source_url"),
        source_timestamp=source_timestamp,
        availability_flags={key: item is not None for key, item in facts.items()},
    )


class AUSLStatsApp:
    def __init__(self, root: tk.Tk, logger=None):
        self.root = root
        self.logger = logger
        self.root.title("AUSL Broadcast Stats Lookup")
        self.root.geometry("1440x880")
        self.root.minsize(1120, 720)
        self.db = {}
        self.selected_game = None
        self._lineup_editor_game_id = None
        self._lineup_editor_source = "manual"
        self._lineup_editor_loaded_at = None
        self._lineup_store_backup = None
        self._lineup_store_error = ""
        self._official_game_choices = {}
        self._search_view = None
        self._search_team = None
        self.selected_player_id = None
        self.search_rows = []
        self.live_game = None
        self.live_box = None
        self.live_health = LiveFeedHealth(
            "RED", "DISCONNECTED", None, "", None, "NOT LOADED"
        )
        self.live_player_copy_text = ""
        self.current_broadcast_note = ""
        self.data_freshness_text = f"Data updated: unknown - {VERIFY_NOTE}"
        self.producer_prep_copy_text = ""
        self._initial_load_in_flight = False
        self._data_update_in_flight = False
        self._data_update_cancel_token = None
        self._live_refresh_in_flight = False
        self._live_refresh_cancel_token = None
        self._live_request_generation = 0
        self._active_live_request = None
        self._live_timer_id = None
        self._offline_mode = False
        self._packet_metadata = {}
        self._verification_count_cache = {}
        self.game_day_readiness = None
        self._main_thread_results = queue.Queue()
        self._main_thread_poll_id = None
        self.locked_lineups = self.load_locked_lineups()
        self._style()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._load_initial()

    def _on_close(self):
        """Cancel any in-flight refresh/live jobs before closing.

        Their abandoned background threads are daemons and would not block
        shutdown either way, but cancelling first stops wasted retries and
        keeps behavior consistent with an explicit cancel action.
        """
        self.cancel_data_update()
        self.cancel_live_refresh()
        self._cancel_live_timer()
        self.root.destroy()

    def _style(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Player.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#555555")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("ReadinessReady.TLabel", font=("Segoe UI", 20, "bold"), foreground="#146c43")
        style.configure("ReadinessAttention.TLabel", font=("Segoe UI", 20, "bold"), foreground="#9a6700")
        style.configure("ReadinessNotReady.TLabel", font=("Segoe UI", 20, "bold"), foreground="#b42318")
        style.configure("Offline.TCheckbutton", font=("Segoe UI", 10, "bold"))
        style.configure("OfflineBanner.TLabel", font=("Segoe UI", 11, "bold"), foreground="#b42318")

    def _build(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        self._build_ausl_logo(top).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
        ttk.Label(top, text="AUSL Broadcast Stats", style="Header.TLabel").grid(row=0, column=1, sticky="w", padx=(0, 18))
        self.update_button = ttk.Button(top, text="Quick Refresh (Core)", style="Accent.TButton", command=self.update_data)
        self.update_button.grid(row=0, column=2, padx=4)
        self.cancel_update_button = ttk.Button(top, text="Cancel Refresh", state="disabled", command=self.cancel_data_update)
        self.cancel_update_button.grid(row=0, column=3, padx=4)
        self.offline_mode_var = tk.BooleanVar(value=False)
        self.offline_toggle = ttk.Checkbutton(
            top,
            text="LOCAL/OFFLINE MODE",
            variable=self.offline_mode_var,
            command=lambda: self.set_local_offline_mode(self.offline_mode_var.get()),
            style="Offline.TCheckbutton",
        )
        self.offline_toggle.grid(row=0, column=4, padx=(10, 4))
        self.status_var = tk.StringVar(value="Loading local database...")
        ttk.Label(top, textvariable=self.status_var, style="Sub.TLabel").grid(row=0, column=5, sticky="w", padx=10)
        self.data_freshness_var = tk.StringVar(value=self.data_freshness_text)
        ttk.Label(top, textvariable=self.data_freshness_var, style="Sub.TLabel").grid(row=1, column=1, columnspan=5, sticky="w", pady=(4, 0))
        self.data_health_var = tk.StringVar(value="Data health: loading...")
        self.data_health_label = ttk.Label(top, textvariable=self.data_health_var, style="Sub.TLabel")
        self.data_health_label.grid(row=2, column=1, columnspan=5, sticky="w", pady=(2, 0))
        self.offline_banner_var = tk.StringVar(value="")
        ttk.Label(
            top,
            textvariable=self.offline_banner_var,
            style="OfflineBanner.TLabel",
        ).grid(row=3, column=1, columnspan=5, sticky="w", pady=(2, 0))
        top.columnconfigure(5, weight=1)

        game = ttk.LabelFrame(self.root, text="Game Setup", padding=8)
        game.pack(fill="x", padx=10, pady=(0, 8))
        self.game_choice_var = tk.StringVar(value="Loading official schedule...")
        self.game_context_var = tk.StringVar(
            value="Official game identity is loading — do not use matchup context yet."
        )
        ttk.Label(game, text="Official Game").grid(row=0, column=0, padx=4)
        self.game_picker = ttk.Combobox(
            game,
            textvariable=self.game_choice_var,
            state="disabled",
            width=92,
        )
        self.game_picker.grid(
            row=0, column=1, columnspan=7, padx=4, sticky="ew"
        )
        self.game_picker.bind("<<ComboboxSelected>>", self._on_game_choice_selected)
        self.away_var = tk.StringVar(value=TEAM_OPTIONS[0])
        self.home_var = tk.StringVar(value=TEAM_OPTIONS[1])
        ttk.Label(game, text="Away Team").grid(row=1, column=0, padx=4, pady=(6, 0))
        self.away_box = ttk.Combobox(
            game,
            values=TEAM_OPTIONS,
            textvariable=self.away_var,
            state="disabled",
            width=23,
        )
        self.away_box.grid(row=1, column=1, padx=4, pady=(6, 0))
        self.away_box.bind("<<ComboboxSelected>>", self._on_custom_team_selected)
        ttk.Label(game, text="Home Team").grid(row=1, column=2, padx=(16, 4), pady=(6, 0))
        self.home_box = ttk.Combobox(
            game,
            values=TEAM_OPTIONS,
            textvariable=self.home_var,
            state="disabled",
            width=23,
        )
        self.home_box.grid(row=1, column=3, padx=4, pady=(6, 0))
        self.home_box.bind("<<ComboboxSelected>>", self._on_custom_team_selected)
        self.scope_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(game, text="Search game teams only", variable=self.scope_var, command=self._on_search_scope_changed).grid(row=1, column=4, padx=18, pady=(6, 0))
        ttk.Button(game, text="Show Away Roster", command=lambda: self.show_team(self.away_var.get())).grid(row=1, column=5, padx=4, pady=(6, 0))
        ttk.Button(game, text="Show Home Roster", command=lambda: self.show_team(self.home_var.get())).grid(row=1, column=6, padx=4, pady=(6, 0))
        ttk.Button(game, text="Generate Producer Packet", style="Accent.TButton", command=self.generate_pregame_report).grid(row=1, column=7, padx=(16, 4), pady=(6, 0))
        ttk.Label(
            game,
            textvariable=self.game_context_var,
            style="Sub.TLabel",
            wraplength=1340,
        ).grid(row=2, column=0, columnspan=8, sticky="w", padx=4, pady=(6, 0))
        game.columnconfigure(1, weight=1)

        self.main_tabs = ttk.Notebook(self.root)
        self.main_tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        game_day = ttk.Frame(self.main_tabs, padding=8)
        lookup = ttk.Frame(self.main_tabs, padding=8)
        team_totals = ttk.Frame(self.main_tabs, padding=8)
        producer = ttk.Frame(self.main_tabs, padding=8)
        lineups = ttk.Frame(self.main_tabs, padding=8)
        manual = ttk.Frame(self.main_tabs, padding=8)
        live = ttk.Frame(self.main_tabs, padding=8)
        self.main_tabs.add(game_day, text="Game Day")
        self.main_tabs.add(lookup, text="Player Lookup")
        self.main_tabs.add(team_totals, text="Team Totals")
        self.main_tabs.add(producer, text="Producer Prep")
        self.main_tabs.add(lineups, text="Lineup Lock")
        self.main_tabs.add(manual, text="Manual Notes")
        self.main_tabs.add(live, text="Live Game")
        self._build_game_day(game_day)
        self._build_lookup(lookup)
        self._build_team_totals(team_totals)
        self._build_producer_prep(producer)
        self._build_lineup_lock(lineups)
        self._build_manual_notes(manual)
        self._build_live(live)

    def _build_ausl_logo(self, parent):
        logo = tk.Canvas(parent, width=82, height=46, highlightthickness=0, bg="#f0f0f0")
        logo.create_rectangle(2, 2, 80, 44, fill="#111827", outline="#111827")
        logo.create_rectangle(6, 6, 76, 40, outline="#ffffff", width=2)
        logo.create_text(41, 20, text="AUSL", fill="#ffffff", font=("Segoe UI", 17, "bold"))
        logo.create_text(41, 34, text="SOFTBALL", fill="#facc15", font=("Segoe UI", 7, "bold"))
        return logo

    def _build_game_day(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(2, weight=1)

        status = ttk.Frame(parent)
        status.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        status.columnconfigure(1, weight=1)
        self.game_day_overall_var = tk.StringVar(value="NOT READY")
        self.game_day_overall_label = ttk.Label(
            status,
            textvariable=self.game_day_overall_var,
            style="ReadinessNotReady.TLabel",
        )
        self.game_day_overall_label.grid(row=0, column=0, sticky="w")
        self.game_day_counts_var = tk.StringVar(
            value="Waiting for authoritative game-day state."
        )
        ttk.Label(
            status,
            textvariable=self.game_day_counts_var,
            style="Sub.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=14)
        ttk.Button(
            status,
            text="Go to Game Setup",
            command=self._focus_game_setup,
        ).grid(row=0, column=2, padx=4)
        ttk.Checkbutton(
            status,
            text="LOCAL/OFFLINE MODE",
            variable=self.offline_mode_var,
            command=lambda: self.set_local_offline_mode(
                self.offline_mode_var.get()
            ),
            style="Offline.TCheckbutton",
        ).grid(row=0, column=3, padx=(12, 0))

        self.game_day_selected_var = tk.StringVar(
            value="No official game selected."
        )
        self.game_day_data_var = tk.StringVar(value="Data health is loading.")
        self.game_day_lineup_var = tk.StringVar(value="Lineup state unavailable.")
        self.game_day_live_var = tk.StringVar(value="Live-feed state unavailable.")
        self.game_day_verification_var = tk.StringVar(
            value="Verification queue unavailable."
        )
        self.game_day_packet_var = tk.StringVar(
            value="Producer packet not generated."
        )
        self.game_day_network_var = tk.StringVar(
            value="Network requests permitted by producer action."
        )

        sections = (
            ("Selected game", self.game_day_selected_var, 0, 0),
            ("Data health", self.game_day_data_var, 0, 1),
            ("Lineup readiness", self.game_day_lineup_var, 1, 0),
            ("Live-feed state", self.game_day_live_var, 1, 1),
            ("Verification queue", self.game_day_verification_var, 2, 0),
            ("Producer packet", self.game_day_packet_var, 2, 1),
        )
        cards = ttk.Frame(parent)
        cards.grid(row=1, column=0, columnspan=2, sticky="nsew")
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        for title, variable, row, column in sections:
            card = ttk.LabelFrame(cards, text=title, padding=7)
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0, 4) if column == 0 else (4, 0),
                pady=3,
            )
            ttk.Label(
                card,
                textvariable=variable,
                justify="left",
                wraplength=500,
            ).pack(fill="x")

        bottom = ttk.Frame(parent)
        bottom.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)
        checklist = ttk.LabelFrame(bottom, text="Ready-for-Air checklist", padding=6)
        checklist.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        checklist.rowconfigure(0, weight=1)
        checklist.columnconfigure(0, weight=1)
        self.game_day_checklist = tk.Text(
            checklist,
            wrap="word",
            height=8,
            font=("Consolas", 10),
            padx=8,
            pady=8,
            relief="flat",
        )
        self.game_day_checklist.grid(row=0, column=0, sticky="nsew")
        checklist_scroll = ttk.Scrollbar(
            checklist,
            orient="vertical",
            command=self.game_day_checklist.yview,
        )
        checklist_scroll.grid(row=0, column=1, sticky="ns")
        self.game_day_checklist.configure(
            yscrollcommand=checklist_scroll.set,
            state="disabled",
        )

        network = ttk.LabelFrame(bottom, text="Network permission", padding=8)
        network.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ttk.Label(
            network,
            textvariable=self.game_day_network_var,
            justify="left",
            wraplength=350,
        ).pack(fill="x")
        ttk.Label(
            network,
            text=(
                "Offline Mode keeps local search, lineups, notes, packets, "
                "and copy actions available. Turning it off never starts a request."
            ),
            style="Sub.TLabel",
            justify="left",
            wraplength=350,
        ).pack(fill="x", pady=(8, 0))

    def _focus_game_setup(self):
        picker = getattr(self, "game_picker", None)
        if picker is not None:
            try:
                picker.focus_set()
            except tk.TclError:
                return

    def _build_lookup(self, parent):
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=3)
        parent.rowconfigure(1, weight=1)
        search = ttk.Frame(parent)
        search.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(search, text="Player, team, position, or #number:").pack(side="left")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var, width=36)
        entry.pack(side="left", padx=8)
        entry.bind("<KeyRelease>", lambda _e: self.search())
        entry.bind("<Return>", lambda _e: self.search())
        ttk.Button(search, text="Search", command=self.search).pack(side="left")
        ttk.Button(search, text="All Players", command=self.show_all).pack(side="left", padx=5)
        self.search_scope_var = tk.StringVar(value="Showing: selected game teams")
        ttk.Label(search, textvariable=self.search_scope_var, style="Sub.TLabel").pack(
            side="left", padx=10
        )

        left = ttk.LabelFrame(parent, text="Players", padding=6)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.results = tk.Listbox(left, font=("Consolas", 11), activestyle="none")
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        self.results.bind("<<ListboxSelect>>", self.select_result)

        right = ttk.LabelFrame(parent, text="Broadcast Player Card", padding=10)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(4, weight=1)
        self.player_title = tk.StringVar(value="Select a player")
        self.player_meta = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.player_title, style="Player.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.player_meta, style="Sub.TLabel", wraplength=720).grid(row=1, column=0, sticky="w", pady=(2, 8))
        buttons = ttk.Frame(right)
        buttons.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for label, kind in [
            ("Copy Player ID", "player_id"),
            ("Copy Season Stat", "season_stat"),
            ("Copy Career Stat", "career_stat"),
            ("Copy Announcer Note", "announcer_note"),
        ]:
            ttk.Button(buttons, text=label, command=lambda k=kind: self.copy_gfx(k)).pack(side="left", padx=(0, 5))
        self.copy_status = tk.StringVar()
        ttk.Label(right, textvariable=self.copy_status, style="Sub.TLabel").grid(row=3, column=0, sticky="w")
        self.stat_tabs = ttk.Notebook(right)
        self.stat_tabs.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        self.stat_texts = {}
        for key, label in [
            ("card", "Quick Card"),
            ("storylines", "Storylines"),
            ("splits", "Best Splits"),
            ("sources", "Sources / Notes"),
            ("career", "AUSL Career"),
            ("current", str(CURRENT_YEAR)),
            ("previous", str(CURRENT_YEAR - 1)),
            ("fielding", "Fielding"),
        ]:
            frame = ttk.Frame(self.stat_tabs)
            text = tk.Text(frame, wrap="word", font=("Consolas", 12), relief="flat", padx=12, pady=12)
            text.pack(fill="both", expand=True)
            text.configure(state="disabled")
            self.stat_tabs.add(frame, text=label)
            self.stat_texts[key] = text

    def _build_producer_prep(self, parent):
        controls = ttk.LabelFrame(parent, text="Producer Prep Assistant", padding=8)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Refresh Storylines / Graphics", command=self.render_producer_prep).pack(side="left")
        ttk.Button(controls, text="Copy Graphic Queue", command=self.copy_producer_prep).pack(side="left", padx=8)
        ttk.Button(controls, text="Generate Producer Packet", style="Accent.TButton", command=self.generate_pregame_report).pack(side="left", padx=8)
        self.producer_prep_status = tk.StringVar(value="Select game teams, then refresh.")
        ttk.Label(controls, textvariable=self.producer_prep_status, style="Sub.TLabel").pack(side="left", padx=8)

        body = ttk.LabelFrame(parent, text="Suggested Prep Notes", padding=6)
        body.pack(fill="both", expand=True)
        self.producer_prep_text = tk.Text(body, wrap="word", font=("Consolas", 12), padx=12, pady=12)
        self.producer_prep_text.pack(fill="both", expand=True)
        self._set_text(self.producer_prep_text, "Producer prep suggestions will appear here once the database loads.")

    def _build_lineup_lock(self, parent):
        controls = ttk.LabelFrame(parent, text="Official / Manual Lineup Lock", padding=8)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Load Projected Lineups", command=self.load_projected_lineups_into_editor).pack(side="left")
        ttk.Button(
            controls,
            text="Validate & Save Lineups",
            style="Accent.TButton",
            command=self.lock_lineups_from_editor,
        ).pack(side="left", padx=8)
        ttk.Button(controls, text="Clear Locked Lineups", command=self.clear_locked_lineups).pack(side="left", padx=8)
        initial_status = self._lineup_storage_notice() or (
            "Select an official game, then load or enter its lineups."
        )
        self.lineup_lock_status = tk.StringVar(value=initial_status)
        ttk.Label(controls, textvariable=self.lineup_lock_status, style="Sub.TLabel").pack(side="left", padx=8)

        editor = ttk.Frame(parent)
        editor.pack(fill="both", expand=True)
        editor.columnconfigure(0, weight=1)
        editor.columnconfigure(1, weight=1)
        editor.rowconfigure(0, weight=1)
        self.lineup_widgets = {}
        for column, side in enumerate(("away", "home")):
            frame = ttk.LabelFrame(editor, text=f"{side.title()} Team Lineup", padding=8)
            frame.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if side == "away" else (6, 0))
            frame.columnconfigure(1, weight=1)
            frame.rowconfigure(3, weight=1)
            starter_var = tk.StringVar()
            status_var = tk.StringVar(value="Projected until locked")
            ttk.Label(frame, text="Starting pitcher").grid(row=0, column=0, sticky="w")
            ttk.Entry(frame, textvariable=starter_var, width=34).grid(row=0, column=1, sticky="ew", padx=6)
            ttk.Label(frame, text="Lineup status").grid(row=1, column=0, sticky="w", pady=(6, 0))
            ttk.Label(frame, textvariable=status_var, style="Sub.TLabel").grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
            ttk.Label(frame, text="Paste lineup lines like: 1. #13 Player Name - CF").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 2))
            text = tk.Text(frame, wrap="word", font=("Consolas", 11), height=18, padx=8, pady=8)
            text.grid(row=3, column=0, columnspan=2, sticky="nsew")
            self.lineup_widgets[side] = {"starter": starter_var, "text": text, "status": status_var}

    def _build_manual_notes(self, parent):
        form = ttk.LabelFrame(parent, text="Manual Producer Note", padding=10)
        form.pack(fill="x", pady=(0, 8))
        self.note_scope_var = tk.StringVar(value="player")
        self.note_player_var = tk.StringVar()
        self.note_team_var = tk.StringVar(value="")
        self.note_game_var = tk.StringVar(value="")
        self.note_type_var = tk.StringVar(value="producer")
        self.note_author_var = tk.StringVar(value="producer")
        self.note_air_safe_var = tk.BooleanVar(value=False)

        ttk.Label(form, text="Scope").grid(row=0, column=0, sticky="w")
        self.note_scope_picker = ttk.Combobox(
            form,
            values=["player", "team", "game", "global"],
            textvariable=self.note_scope_var,
            state="readonly",
            width=10,
        )
        self.note_scope_picker.grid(row=0, column=1, padx=6, sticky="w")
        self.note_scope_picker.bind("<<ComboboxSelected>>", self._manual_note_scope_changed)

        ttk.Label(form, text="Exact player").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.note_player_picker = ttk.Combobox(
            form, textvariable=self.note_player_var, state="normal", width=38
        )
        self.note_player_picker.grid(row=0, column=3, padx=6, sticky="ew")
        self.note_player_picker.bind("<KeyRelease>", self._filter_manual_note_players)

        ttk.Label(form, text="Team").grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.note_team_picker = ttk.Combobox(
            form,
            values=sorted(set(TEAM_TO_CODE.values())),
            textvariable=self.note_team_var,
            state="disabled",
            width=8,
        )
        self.note_team_picker.grid(row=0, column=5, padx=6, sticky="w")

        ttk.Label(form, text="Official game ID").grid(row=0, column=6, sticky="w", padx=(12, 0))
        self.note_game_entry = ttk.Entry(form, textvariable=self.note_game_var, width=13, state="disabled")
        self.note_game_entry.grid(row=0, column=7, padx=6, sticky="w")

        ttk.Label(form, text="Author").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.note_author_var, width=14).grid(row=1, column=1, padx=6, sticky="w", pady=(8, 0))
        ttk.Label(form, text="Type").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Combobox(form, values=["producer", "pronunciation", "injury", "story", "do-not-use", "verified"], textvariable=self.note_type_var, state="readonly", width=16).grid(row=1, column=3, padx=6, sticky="w", pady=(8, 0))
        ttk.Checkbutton(form, text="Air safe", variable=self.note_air_safe_var).grid(row=1, column=4, columnspan=2, padx=8, sticky="w", pady=(8, 0))

        ttk.Label(form, text="Note").grid(row=2, column=0, sticky="nw", pady=(8, 0))
        self.note_text = tk.Text(form, height=4, wrap="word", width=90)
        self.note_text.grid(row=2, column=1, columnspan=7, sticky="ew", padx=6, pady=(8, 0))
        form.columnconfigure(3, weight=1)
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=1, columnspan=7, sticky="w", pady=8, padx=6)
        ttk.Button(buttons, text="Save Manual Note", style="Accent.TButton", command=self.save_manual_note).pack(side="left")
        ttk.Button(buttons, text="Reload Notes", command=self.reload_manual_notes).pack(side="left", padx=8)
        self.manual_note_status = tk.StringVar(value="Manual notes are saved locally under data/manual/player_notes.csv")
        ttk.Label(form, textvariable=self.manual_note_status, style="Sub.TLabel").grid(row=4, column=1, columnspan=7, sticky="w", padx=6)

        list_frame = ttk.LabelFrame(parent, text="Current Manual Notes", padding=6)
        list_frame.pack(fill="both", expand=True)
        self.manual_notes_view = tk.Text(list_frame, wrap="word", font=("Consolas", 11), padx=10, pady=10)
        self.manual_notes_view.pack(fill="both", expand=True)
        self._set_text(self.manual_notes_view, "Manual notes will appear here after the database loads.")
        self._note_player_all_choices = []
        self._manual_note_scope_changed()

    def _build_live(self, parent):
        controls = ttk.LabelFrame(parent, text="Official AUSL Live Feed", padding=8)
        controls.pack(fill="x")
        ttk.Label(controls, text="Selected official Game ID").pack(side="left")
        self.game_id_var = tk.StringVar()
        self.live_game_id_entry = ttk.Entry(
            controls,
            textvariable=self.game_id_var,
            width=12,
            state="readonly",
        )
        self.live_game_id_entry.pack(side="left", padx=6)
        self.live_refresh_button = ttk.Button(controls, text="Load / Refresh Game", command=self.refresh_live)
        self.live_refresh_button.pack(side="left")
        self.cancel_live_button = ttk.Button(controls, text="Cancel", state="disabled", command=self.cancel_live_refresh)
        self.cancel_live_button.pack(side="left", padx=(6, 0))
        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Auto-refresh every 30 seconds", variable=self.auto_var, command=self._schedule_live).pack(side="left", padx=16)
        self.live_status = tk.StringVar(value="Enter the number at the end of an AUSL game-page URL.")
        ttk.Label(controls, textvariable=self.live_status, style="Sub.TLabel").pack(side="left", padx=8)

        search = ttk.Frame(parent, padding=(0, 8))
        search.pack(fill="x")
        ttk.Label(search, text="Live player search:").pack(side="left")
        self.live_search_var = tk.StringVar()
        live_entry = ttk.Entry(search, textvariable=self.live_search_var, width=30)
        live_entry.pack(side="left", padx=6)
        live_entry.bind("<KeyRelease>", lambda _e: self.search_live_player())
        ttk.Button(search, text="Find Player", command=self.search_live_player).pack(side="left")
        ttk.Button(search, text="Copy Player Line", command=self.copy_live_player).pack(side="left", padx=(6, 0))
        ttk.Button(search, text="Copy Game Comparison", command=self.copy_live_comparison).pack(side="left", padx=12)

        pane = ttk.Panedwindow(parent, orient="horizontal")
        pane.pack(fill="both", expand=True)
        summary_frame = ttk.LabelFrame(pane, text="Game / Team Comparison", padding=6)
        player_frame = ttk.LabelFrame(pane, text="Live Player Lines", padding=6)
        pane.add(summary_frame, weight=3)
        pane.add(player_frame, weight=2)
        self.live_summary = tk.Text(summary_frame, wrap="word", font=("Consolas", 12), padx=10, pady=10)
        self.live_summary.pack(fill="both", expand=True)
        self.live_player = tk.Text(player_frame, wrap="word", font=("Consolas", 12), padx=10, pady=10)
        self.live_player.pack(fill="both", expand=True)
        self._set_text(self.live_summary, "Waiting for a game ID.\n\nLive data is marked YELLOW until checked against the official game book.")
        self._set_text(self.live_player, "Load a game, then type a player name above.")

    def _build_team_totals(self, parent):
        controls = ttk.LabelFrame(parent, text="Team Season Totals", padding=10)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Team").pack(side="left")
        self.team_totals_team_var = tk.StringVar(value=TEAM_OPTIONS[0])
        team_box = ttk.Combobox(controls, values=TEAM_OPTIONS, textvariable=self.team_totals_team_var, state="readonly", width=25)
        team_box.pack(side="left", padx=(6, 16))
        team_box.bind("<<ComboboxSelected>>", lambda _event: self.render_team_totals())
        ttk.Label(controls, text="Season").pack(side="left")
        self.team_totals_season_var = tk.StringVar(value=str(CURRENT_YEAR))
        season_box = ttk.Combobox(controls, values=[str(year) for year in sorted(SEASONS, reverse=True)], textvariable=self.team_totals_season_var, state="readonly", width=8)
        season_box.pack(side="left", padx=6)
        season_box.bind("<<ComboboxSelected>>", lambda _event: self.render_team_totals())
        ttk.Button(controls, text="Copy Team Totals", command=self.copy_team_totals).pack(side="left", padx=12)
        self.team_totals_status = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.team_totals_status, style="Sub.TLabel").pack(side="left", padx=6)

        self.team_totals_summary_var = tk.StringVar(value="Loading team totals...")
        ttk.Label(parent, textvariable=self.team_totals_summary_var, font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(2, 8))
        tables = ttk.Notebook(parent)
        tables.pack(fill="both", expand=True)
        self.team_stat_trees = {}
        specs = {
            "batting": ("PLAYER", "G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "SO", "SB", "AVG", "OBP", "SLG", "OPS"),
            "pitching": ("PLAYER", "APP", "GS", "W", "L", "ERA", "IP", "H", "R", "ER", "BB", "SO", "WHIP", "SV"),
            "fielding": ("PLAYER", "POS", "G", "PO", "A", "E", "FLD%", "DP"),
        }
        for key, columns in specs.items():
            frame = ttk.Frame(tables)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
            for column in columns:
                width = 210 if column == "PLAYER" else 72
                tree.heading(column, text=column, command=lambda c=column, t=tree: self.sort_stats_tree(t, c, False))
                tree.column(column, width=width, minwidth=55, anchor="w" if column == "PLAYER" else "center")
            vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vertical.grid(row=0, column=1, sticky="ns")
            horizontal.grid(row=1, column=0, sticky="ew")
            tree.tag_configure("total", background="#dfe8f3", font=("Segoe UI", 10, "bold"))
            tables.add(frame, text=key.title())
            self.team_stat_trees[key] = tree
        self.team_totals_copy_text = ""

    @staticmethod
    def sort_stats_tree(tree, column, reverse):
        def sort_key(item_id):
            item = tree.set(item_id, column)
            try:
                return (0, float(str(item).replace("—", "nan")))
            except ValueError:
                return (1, str(item).lower())
        normal = [item for item in tree.get_children("") if "total" not in tree.item(item, "tags")]
        totals = [item for item in tree.get_children("") if "total" in tree.item(item, "tags")]
        normal.sort(key=sort_key, reverse=reverse)
        for index, item in enumerate(normal + totals):
            tree.move(item, "", index)
        tree.heading(column, command=lambda: AUSLStatsApp.sort_stats_tree(tree, column, not reverse))

    def _log_event(self, event, **fields):
        logger = getattr(self, "logger", None)
        if logger is None:
            return
        try:
            log_event(logger, event, **fields)
        except Exception:
            # Logging must never make the live application unusable.
            return

    @staticmethod
    def _set_button_state(button, state):
        if button is not None:
            button.configure(state=state)

    def network_requests_permitted(self, action, *, status_var=None):
        """Central producer-facing network permission decision.

        Future network buttons must call this before creating a token, timer,
        or worker.  Blocking is quiet and visible rather than modal.
        """

        if not bool(getattr(self, "_offline_mode", False)):
            return True
        message = (
            f"LOCAL/OFFLINE MODE — {action} blocked; "
            "last-known-good local data remains available."
        )
        target = status_var or getattr(self, "status_var", None)
        if target is not None:
            target.set(message)
        return False

    def set_local_offline_mode(self, enabled=None):
        desired = (
            bool(enabled)
            if enabled is not None
            else bool(getattr(self, "offline_mode_var", None).get())
        )
        already = bool(getattr(self, "_offline_mode", False))
        self._offline_mode = desired
        variable = getattr(self, "offline_mode_var", None)
        if variable is not None and bool(variable.get()) != desired:
            variable.set(desired)

        if desired:
            self._suppress_game_day_refresh = True
            try:
                self.cancel_data_update()
                self.cancel_live_refresh()
                self._cancel_live_timer()
            finally:
                self._suppress_game_day_refresh = False
            auto_var = getattr(self, "auto_var", None)
            if auto_var is not None:
                auto_var.set(False)
            message = (
                "LOCAL/OFFLINE MODE — network requests and live timers are blocked; "
                "using installed last-known-good data."
            )
            if hasattr(self, "status_var"):
                self.status_var.set(message)
            if hasattr(self, "live_status"):
                self.live_status.set(message)
            if hasattr(self, "offline_banner_var"):
                self.offline_banner_var.set(
                    "◆ LOCAL/OFFLINE MODE — NETWORK REQUESTS BLOCKED"
                )
            if not already:
                self._log_event(
                    "local_offline_mode_enabled",
                    source="producer_network_permission",
                )
        else:
            if hasattr(self, "offline_banner_var"):
                self.offline_banner_var.set("")
            if hasattr(self, "status_var"):
                self.status_var.set(
                    "Local/Offline Mode disabled. No refresh was started; "
                    "choose when to request new data."
                )
            if hasattr(self, "live_status"):
                self.live_status.set(
                    "Network requests permitted. No live refresh was started."
                )
            if already:
                self._log_event(
                    "local_offline_mode_disabled",
                    source="producer_network_permission",
                )
        self._sync_update_button()
        self._sync_live_refresh_button()
        refresh = getattr(self, "refresh_game_day_dashboard", None)
        if callable(refresh):
            refresh()

    def _refresh_game_day_if_allowed(self):
        if bool(getattr(self, "_suppress_game_day_refresh", False)):
            return
        refresh = getattr(self, "refresh_game_day_dashboard", None)
        if callable(refresh):
            refresh()

    def _sync_update_button(self):
        in_flight = bool(getattr(self, "_data_update_in_flight", False))
        disabled = (
            bool(getattr(self, "_initial_load_in_flight", False))
            or in_flight
            or bool(getattr(self, "_offline_mode", False))
        )
        self._set_button_state(
            getattr(self, "update_button", None),
            "disabled" if disabled else "normal",
        )
        self._set_button_state(
            getattr(self, "cancel_update_button", None),
            "normal" if in_flight else "disabled",
        )

    def _sync_live_refresh_button(self):
        in_flight = bool(getattr(self, "_live_refresh_in_flight", False))
        disabled = in_flight or bool(getattr(self, "_offline_mode", False))
        self._set_button_state(
            getattr(self, "live_refresh_button", None),
            "disabled" if disabled else "normal",
        )
        self._set_button_state(
            getattr(self, "cancel_live_button", None),
            "normal" if in_flight else "disabled",
        )

    def _ensure_main_thread_dispatch(self):
        if not hasattr(self, "_main_thread_results"):
            self._main_thread_results = queue.Queue()
        if getattr(self, "_main_thread_poll_id", None) is None:
            self._main_thread_poll_id = self.root.after(
                25, self._drain_main_thread_results
            )

    def _post_main_thread(self, callback, *args):
        self._main_thread_results.put((callback, args))

    def _drain_main_thread_results(self):
        self._main_thread_poll_id = None
        while True:
            try:
                callback, args = self._main_thread_results.get_nowait()
            except queue.Empty:
                break
            callback(*args)
        if (
            not self._main_thread_results.empty()
            or getattr(self, "_initial_load_in_flight", False)
            or getattr(self, "_data_update_in_flight", False)
            or getattr(self, "_live_refresh_in_flight", False)
        ):
            self._ensure_main_thread_dispatch()

    @staticmethod
    def _roster_count(data):
        roster = data.get("roster", ()) if isinstance(data, dict) else ()
        try:
            return len(roster)
        except TypeError:
            return 0

    def _load_initial(self):
        if getattr(self, "_initial_load_in_flight", False):
            self.status_var.set("Initial database load is already in progress.")
            return
        if getattr(self, "_data_update_in_flight", False):
            self.status_var.set("A data update is already in progress.")
            return

        self._initial_load_in_flight = True
        self._ensure_main_thread_dispatch()
        self._sync_update_button()
        self.status_var.set("Loading local database...")
        self._log_event("initial_load_started", source="local_database")

        def work():
            try:
                data = load_database(include_enrichment=False)
            except Exception as exc:
                self._post_main_thread(self._finish_initial_load_error, exc)
                return
            self._post_main_thread(self._finish_initial_load_success, data)

        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            self._finish_initial_load_error(exc)

    def _finish_initial_load_success(self, data):
        try:
            self._finish_load(data)
        except Exception as exc:
            self._finish_initial_load_error(exc)
            return
        self._initial_load_in_flight = False
        self._sync_update_button()
        self._log_event(
            "initial_load_succeeded",
            source="local_database",
            row_count=self._roster_count(data),
        )

    def _finish_initial_load_error(self, exc):
        self._initial_load_in_flight = False
        self._sync_update_button()
        self._log_event(
            "initial_load_failed",
            source="local_database",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        self._load_failed(exc)

    def _finish_load(self, data):
        previous_selected_id = getattr(self, "selected_player_id", None)
        self.db = data
        self._verification_count_cache = {}
        self.data_freshness_text = self.format_data_freshness(data.get("manifest", {}))
        if hasattr(self, "data_freshness_var"):
            self.data_freshness_var.set(self.data_freshness_text)
        if hasattr(self, "data_health_var"):
            self._apply_data_health_display(
                data.get("manifest", {}), data.get("refresh_attempt", {})
            )
        if hasattr(self, "status_var"):
            self.status_var.set(f"Ready — {len(data['roster'])} current players loaded")
        self._refresh_manual_note_players()
        self.refresh_game_choices()
        self._sync_selected_player_after_load(previous_selected_id)
        self.show_all()
        self.render_team_totals()
        self.render_producer_prep()
        self.render_manual_notes()
        self.refresh_game_day_dashboard()

    def _sync_selected_player_after_load(self, previous_selected_id):
        """Rerender one exact selected identity or clear all stale player copy."""
        if previous_selected_id is None:
            return
        if getattr(self, "selected_player_id", None) != previous_selected_id:
            return
        roster = self.db.get("roster", pd.DataFrame()) if self.db else pd.DataFrame()
        if not isinstance(roster, pd.DataFrame) or "player_id" not in roster.columns:
            self._clear_selected_player()
            return
        identity = _manual_note_identifier(previous_selected_id)
        rows = roster[
            roster["player_id"].map(_manual_note_identifier).eq(identity)
        ]
        if len(rows) != 1:
            self._clear_selected_player()
            return
        self.render_player(rows.iloc[0])

    def refresh_game_choices(self, *, today=None):
        schedule = self.db.get("schedule_results", pd.DataFrame()) if self.db else pd.DataFrame()
        games = official_selected_games(schedule)
        self._official_game_choices = {game.choice_label: game for game in games}
        if games:
            labels = tuple(self._official_game_choices)
            if hasattr(self, "game_picker"):
                self.game_picker.configure(values=labels, state="readonly")
            for box_name in ("away_box", "home_box"):
                box = getattr(self, box_name, None)
                if box is not None:
                    box.configure(state="disabled")
            current_id = getattr(getattr(self, "selected_game", None), "game_id", None)
            selected = next((game for game in games if game.game_id == current_id), None)
            selected = selected or choose_default_selected_game(games, today=today)
            self.on_game_changed(selected)
            return

        self._official_game_choices = {}
        if hasattr(self, "game_picker"):
            self.game_picker.configure(values=(), state="disabled")
        if hasattr(self, "game_choice_var"):
            self.game_choice_var.set(
                "CUSTOM GAME — OFFICIAL SCHEDULE UNAVAILABLE — VERIFY"
            )
        for box_name in ("away_box", "home_box"):
            box = getattr(self, box_name, None)
            if box is not None:
                box.configure(state="readonly")
        self._apply_custom_game_context()

    def _on_game_choice_selected(self, _event=None):
        label = self.game_choice_var.get() if hasattr(self, "game_choice_var") else ""
        selected = getattr(self, "_official_game_choices", {}).get(label)
        if selected is not None:
            self.on_game_changed(selected)

    def _on_custom_team_selected(self, _event=None):
        if getattr(self, "selected_game", None) is None:
            self._apply_custom_game_context()

    def _apply_custom_game_context(self):
        previous = getattr(self, "selected_game", None)
        self.selected_game = None
        away = self.away_var.get() if hasattr(self, "away_var") else ""
        home = self.home_var.get() if hasattr(self, "home_var") else ""
        if hasattr(self, "game_context_var"):
            self.game_context_var.set(
                f"[CUSTOM — VERIFY] {away or 'Away team unavailable'} at "
                f"{home or 'Home team unavailable'} | Official game ID unavailable"
            )
        if hasattr(self, "note_game_var"):
            self.note_game_var.set("")
        if hasattr(self, "game_id_var"):
            self.game_id_var.set("")
        if previous is not None:
            self._reset_lineup_editor_for_game(None)
            self._reset_live_for_game(None)
        if getattr(self, "selected_player_id", None) is not None:
            codes = {TEAM_TO_CODE.get(away), TEAM_TO_CODE.get(home)}
            if not self._selected_player_in_team_codes(codes):
                self._clear_selected_player()
        self.search()
        self.render_producer_prep()
        self.render_manual_notes()
        self._verification_count_cache = {}
        self.refresh_game_day_dashboard()

    def _selected_player_in_team_codes(self, team_codes):
        player_id = getattr(self, "selected_player_id", None)
        roster = self.db.get("roster", pd.DataFrame()) if self.db else pd.DataFrame()
        if player_id is None or roster.empty or not {"player_id", "team_code"}.issubset(roster.columns):
            return False
        rows = roster[
            pd.to_numeric(roster["player_id"], errors="coerce").eq(player_id)
        ]
        if len(rows) != 1:
            return False
        code = (_optional_text(rows.iloc[0], "team_code") or "").upper()
        return bool(code and code in {item for item in team_codes if item})

    def on_game_changed(self, selected_game):
        if not isinstance(selected_game, SelectedGame):
            raise ValueError("An exact official SelectedGame is required")
        previous_id = getattr(getattr(self, "selected_game", None), "game_id", None)
        self.selected_game = selected_game
        self.away_var.set(selected_game.away_team)
        self.home_var.set(selected_game.home_team)
        if hasattr(self, "game_choice_var"):
            self.game_choice_var.set(selected_game.choice_label)
        if hasattr(self, "game_context_var"):
            self.game_context_var.set(selected_game.context_label)
        if hasattr(self, "note_game_var"):
            self.note_game_var.set(selected_game.game_id)
        if hasattr(self, "game_id_var"):
            self.game_id_var.set(selected_game.game_id)

        if previous_id != selected_game.game_id:
            self._reset_lineup_editor_for_game(selected_game)
            self._reset_live_for_game(selected_game)
            if getattr(self, "_search_view", None) == "team":
                self._search_view = None
                self._search_team = None
        if getattr(self, "selected_player_id", None) is not None and not self._selected_player_in_team_codes(
            {selected_game.away_team_code, selected_game.home_team_code}
        ):
            self._clear_selected_player()
        self.search()
        self.render_producer_prep()
        self.render_manual_notes()
        self._verification_count_cache = {}
        self.refresh_game_day_dashboard()

    def _clear_selected_player(self):
        self.selected_player_id = None
        self.current_broadcast_note = ""
        if hasattr(self, "results"):
            self.results.selection_clear(0, "end")
        if hasattr(self, "player_title"):
            self.player_title.set("Select a player")
        if hasattr(self, "player_meta"):
            self.player_meta.set("")
        if hasattr(self, "copy_status"):
            self.copy_status.set("")
        for text in getattr(self, "stat_texts", {}).values():
            self._set_text(text, "Select a player for this game.")

    def _reset_lineup_editor_for_game(self, selected_game):
        game_label = (
            f"Game {selected_game.game_id}"
            if isinstance(selected_game, SelectedGame)
            else "custom game"
        )
        self._lineup_editor_game_id = (
            selected_game.game_id if isinstance(selected_game, SelectedGame) else None
        )
        self._lineup_editor_source = "manual"
        self._lineup_editor_loaded_at = datetime.now(timezone.utc)
        for widget in getattr(self, "lineup_widgets", {}).values():
            widget["starter"].set("")
            widget["text"].delete("1.0", "end")
            widget["status"].set(f"No lineup loaded for {game_label}")
        if hasattr(self, "lineup_lock_status"):
            message = (
                f"Lineup editor cleared for {game_label}; load or enter this game's lineup."
            )
            notice = self._lineup_storage_notice()
            self.lineup_lock_status.set(f"{message} {notice}".strip())

    def _reset_live_for_game(self, selected_game):
        game_id = selected_game.game_id if isinstance(selected_game, SelectedGame) else ""
        self._invalidate_live_context()
        self.live_game = None
        self.live_box = None
        self.live_health = LiveFeedHealth(
            "RED", "DISCONNECTED", None, "", None, "NOT LOADED"
        )
        self.live_player_copy_text = ""
        if hasattr(self, "game_id_var"):
            self.game_id_var.set(game_id)
        if hasattr(self, "auto_var"):
            self.auto_var.set(False)
        if hasattr(self, "live_search_var"):
            self.live_search_var.set("")
        if hasattr(self, "live_status"):
            self.live_status.set(
                f"Game {game_id} selected — live data not loaded."
                if game_id
                else "Official game ID unavailable; live data not loaded."
            )
        if hasattr(self, "live_summary"):
            message = (
                f"Waiting to load official Game {game_id}."
                if game_id
                else "Waiting for an official game ID."
            )
            self._set_text(
                self.live_summary,
                f"{message}\n\nLive data is marked YELLOW until checked against the official game book.",
            )
        if hasattr(self, "live_player"):
            self._set_text(self.live_player, "Load this game, then search for a player.")

    def _cancel_live_timer(self):
        timer_id = getattr(self, "_live_timer_id", None)
        self._live_timer_id = None
        if timer_id is None:
            return
        try:
            self.root.after_cancel(timer_id)
        except (AttributeError, tk.TclError):
            return

    def _invalidate_live_context(self):
        self._cancel_live_timer()
        self._live_request_generation = (
            getattr(self, "_live_request_generation", 0) + 1
        )
        self._active_live_request = None
        # Also stop the abandoned request's own retries immediately, rather
        # than just marking it stale for the app to discover once its
        # network call eventually returns.
        token = getattr(self, "_live_refresh_cancel_token", None)
        if token is not None:
            token.cancel()
        self._live_refresh_cancel_token = None
        self._live_refresh_in_flight = False
        self._sync_live_refresh_button()

    def _load_failed(self, exc):
        self.status_var.set(f"Initial load failed: {exc}")
        messagebox.showerror("AUSL Data", str(exc))

    def manual_notes_path(self):
        path = export_dir().parent / "manual" / "player_notes.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def locked_lineups_path(self):
        path = export_dir().parent / "manual" / "locked_lineups.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load_locked_lineups(self):
        path = self.locked_lineups_path()
        try:
            store, backup_path = migrate_locked_lineups_file(path)
            self._lineup_store_backup = backup_path
            return store
        except Exception as exc:
            self._lineup_store_error = (
                "Lineup locks unavailable; the existing file was left unchanged. "
                f"{exc}"
            )
            return empty_locked_lineup_store()

    def save_locked_lineups(self, store=None):
        store_error = getattr(self, "_lineup_store_error", "")
        if store_error:
            raise RuntimeError(store_error)
        path = self.locked_lineups_path()
        candidate = self.locked_lineups if store is None else store
        write_locked_lineups_atomic(path, candidate)

    def _lineup_storage_notice(self):
        if getattr(self, "_lineup_store_error", ""):
            return self._lineup_store_error
        legacy = getattr(self, "locked_lineups", {}).get("legacy_unassigned", [])
        if not legacy:
            return ""
        backup = getattr(self, "_lineup_store_backup", None)
        backup_suffix = f" Recoverable backup: {backup.name}." if backup else ""
        return (
            f"{len(legacy)} legacy lineup lock(s) are NOT ATTACHED; re-enter or "
            f"explicitly import them for an official game.{backup_suffix}"
        )

    def lineup_key(self, away=None, home=None):
        selected = getattr(self, "selected_game", None)
        return selected.game_id if isinstance(selected, SelectedGame) else ""

    def _current_lineup_lock(self):
        game_id = self.lineup_key()
        games = getattr(self, "locked_lineups", {}).get("games", {})
        locked = games.get(game_id) if game_id and isinstance(games, dict) else None
        if not isinstance(locked, dict) or str(locked.get("game_id", "")) != game_id:
            return {}
        return locked

    def current_locked_lineups(self):
        locked = self._current_lineup_lock()
        lineups = locked.get("lineups", {})
        return lineups if isinstance(lineups, dict) else {}

    def _lineup_status_text(self):
        locked = self._current_lineup_lock()
        if not locked:
            return "Projected until locked"
        source = str(locked.get("source", "unavailable")).strip().lower()
        source_label = (
            "Saved projection - NOT OFFICIAL"
            if source == "projected"
            else f"Locked {source or 'source unavailable'} lineup"
        )
        return (
            f"{source_label} for Game {locked.get('game_id')} - "
            f"saved {locked.get('locked_at', 'unknown time')} - revision "
            f"{locked.get('revision', 'unknown')}"
        )

    def _lineup_broadcast_status(self):
        locked = self._current_lineup_lock()
        if not locked:
            return "PROJECTED LINEUPS ONLY — NOT OFFICIAL"
        source = str(locked.get("source", "")).strip().casefold()
        if source == "projected":
            return "SAVED PROJECTION — NOT OFFICIAL"
        if source == "imported":
            return "IMPORTED LINEUPS — VERIFY SOURCE BEFORE AIR"
        if source == "manual":
            return "MANUAL LINEUPS SAVED — VERIFY AGAINST OFFICIAL CARD"
        return "LINEUP SOURCE UNAVAILABLE — DO NOT USE ON AIR"

    @staticmethod
    def _lineup_issue_text(issue):
        if issue.line_number == 0:
            location = "Starter"
        elif issue.line_number is None:
            location = "Lineup"
        else:
            location = f"Line {issue.line_number}"
        return f"{location}: {issue.message}"

    def _validate_lineup_editor_side(self, side, team):
        widget = self.lineup_widgets[side]
        roster = self.db.get("roster", pd.DataFrame()) if self.db else pd.DataFrame()
        selected = getattr(self, "selected_game", None)
        locked_team = self.current_locked_lineups().get(side, {})
        stored_exception = (
            locked_team.get("starting_pitcher_position_exception")
            if isinstance(locked_team, dict)
            else None
        )
        pending_exceptions = getattr(self, "_starter_position_exceptions", {})
        return validate_lineup_text(
            widget["text"].get("1.0", "end"),
            roster=roster,
            team=team,
            starter=widget["starter"].get().strip(),
            source=getattr(self, "_lineup_editor_source", "manual"),
            game_time=selected.date_time if isinstance(selected, SelectedGame) else None,
            lineup_timestamp=getattr(self, "_lineup_editor_loaded_at", None),
            starter_position_exception=(
                stored_exception
                or (
                    pending_exceptions.get(side)
                    if isinstance(pending_exceptions, dict)
                    else None
                )
            ),
        )

    def parse_lineup_text(self, text, team):
        roster = self.db.get("roster", pd.DataFrame()) if self.db else pd.DataFrame()
        team_roster = roster[roster["team"].eq(team)] if not roster.empty and "team" in roster else pd.DataFrame()
        entries = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            order_match = re.match(r"^(\d+)[\).\-\s]+(.*)$", line)
            batting_order = int(order_match.group(1)) if order_match else len(entries) + 1
            body = order_match.group(2).strip() if order_match else line
            jersey_match = re.search(r"#\s*(\d+)", body)
            jersey = jersey_match.group(1) if jersey_match else ""
            body = re.sub(r"#\s*\d+", "", body).strip(" -|")
            parts = [part.strip() for part in re.split(r"\s+[-|]\s+|\s{2,}", body) if part.strip()]
            name = parts[0] if parts else body
            position = parts[1] if len(parts) > 1 else ""
            player_id = ""
            status = ""
            if not team_roster.empty:
                match = team_roster[team_roster["player_name"].astype(str).str.lower().eq(name.lower())]
                if match.empty and jersey:
                    match = team_roster[team_roster["jersey_number"].astype(str).str.replace(".0", "", regex=False).eq(jersey)]
                if match.empty and name:
                    match = team_roster[team_roster["player_name"].astype(str).str.lower().str.contains(name.lower(), regex=False)]
                if not match.empty:
                    row = match.iloc[0]
                    player_id = row.get("player_id", "")
                    name = row.get("player_name", name)
                    jersey = jersey or str(value(row, "jersey_number", "")).replace(".0", "")
                    position = position or value(row, "position", "")
                    status = self.roster_status(row)
            entries.append(
                {
                    "batting_order": batting_order,
                    "player_id": "" if pd.isna(player_id) else str(player_id),
                    "player_name": name,
                    "jersey_number": jersey,
                    "position": position,
                    "roster_status": status,
                    "raw_line": raw,
                }
            )
        return sorted(entries, key=lambda item: item["batting_order"])

    @staticmethod
    def format_flex_entry(flex):
        if not isinstance(flex, dict) or not flex.get("player_name"):
            return ""
        jersey = f"#{flex.get('jersey_number')} " if flex.get("jersey_number") else ""
        return f"FLEX. {jersey}{flex.get('player_name')} - FLEX"

    def format_lineup_entries(self, entries, flex=None):
        lines = []
        for item in entries:
            jersey = f"#{item.get('jersey_number')} " if item.get("jersey_number") else ""
            position = f" - {item.get('position')}" if item.get("position") else ""
            lines.append(f"{item.get('batting_order')}. {jersey}{item.get('player_name')}{position}")
        flex_line = self.format_flex_entry(flex)
        if flex_line:
            lines.append(flex_line)
        return "\n".join(lines)

    def projected_lineup_entries(self, team):
        entries = []
        for order, item in enumerate(self._projected_lineup(team, CURRENT_YEAR), 1):
            player = item["player"]
            entries.append(
                {
                    "batting_order": order,
                    "player_id": str(player.get("player_id", "")),
                    "player_name": player.get("player_name", ""),
                    "jersey_number": str(value(player, "jersey_number", "")).replace(".0", ""),
                    "position": value(player, "position", ""),
                    "roster_status": self.roster_status(player),
                    "raw_line": "",
                }
            )
        return entries

    def load_projected_lineups_into_editor(self):
        if not self.db:
            self.lineup_lock_status.set("Database is still loading")
            return
        game_id = self.lineup_key()
        if not game_id:
            self.lineup_lock_status.set(
                "Select an official game ID before loading a lineup editor."
            )
            return
        locked = self.current_locked_lineups()
        for side, team in (("away", self.away_var.get()), ("home", self.home_var.get())):
            widget = self.lineup_widgets[side]
            team_data = locked.get(side)
            entries = team_data.get("lineup", []) if team_data else self.projected_lineup_entries(team)
            flex = team_data.get("flex") if team_data else None
            starter = team_data.get("starting_pitcher", "") if team_data else ""
            if not starter:
                pitchers = self._projected_pitchers(team, CURRENT_YEAR)
                starter = pitchers[0][3]["player_name"] if pitchers else ""
            widget["starter"].set(starter)
            widget["text"].delete("1.0", "end")
            widget["text"].insert("1.0", self.format_lineup_entries(entries, flex))
            widget["status"].set(self._lineup_status_text() if locked else "Projected lineup loaded - not official")
        self._lineup_editor_game_id = game_id
        current_lock = self._current_lineup_lock()
        if current_lock:
            self._lineup_editor_source = str(current_lock.get("source", "manual"))
            try:
                loaded_at = datetime.fromisoformat(
                    str(current_lock.get("locked_at", "")).replace("Z", "+00:00")
                )
            except ValueError:
                loaded_at = None
            self._lineup_editor_loaded_at = loaded_at
        else:
            self._lineup_editor_source = "projected"
            self._lineup_editor_loaded_at = datetime.now(timezone.utc)
        self.lineup_lock_status.set(f"Lineup editor loaded for Game {game_id}")

    def lock_lineups_from_editor(self):
        if not self.db:
            self.lineup_lock_status.set("Database is still loading")
            return
        if getattr(self, "_lineup_store_error", ""):
            self.lineup_lock_status.set(
                f"Lineup not saved. {self._lineup_store_error}"
            )
            return
        selected = getattr(self, "selected_game", None)
        key = self.lineup_key()
        if not isinstance(selected, SelectedGame) or not key:
            self.lineup_lock_status.set(
                "Lineup not saved: select an exact official game ID first."
            )
            return
        editor_game_id = getattr(self, "_lineup_editor_game_id", None)
        if editor_game_id != key:
            prior = f"Game {editor_game_id}" if editor_game_id else "an unassigned game"
            self.lineup_lock_status.set(
                f"Lineup not saved: editor contents belong to {prior}, not Game {key}. "
                "Clear/reload or explicitly import them for this game."
            )
            return
        away, home = selected.away_team, selected.home_team
        validations = {
            side: self._validate_lineup_editor_side(side, team)
            for side, team in (("away", away), ("home", home))
        }
        blocking = []
        warnings = []
        for side, result in validations.items():
            side_label = side.title()
            if result.errors:
                rendered = "; ".join(
                    self._lineup_issue_text(issue) for issue in result.errors
                )
                self.lineup_widgets[side]["status"].set(rendered)
                blocking.extend(
                    f"{side_label} {self._lineup_issue_text(issue)}"
                    for issue in result.errors
                )
            elif result.warnings:
                rendered = "; ".join(
                    self._lineup_issue_text(issue) for issue in result.warnings
                )
                self.lineup_widgets[side]["status"].set(
                    f"Confirmation required: {rendered}"
                )
            else:
                self.lineup_widgets[side]["status"].set("Validation passed")
            warnings.extend(
                f"{side_label} {self._lineup_issue_text(issue)}"
                for issue in result.warnings
            )
        if blocking:
            self.lineup_lock_status.set(
                "Lineups not locked — " + " | ".join(blocking[:4])
            )
            return
        warning_confirmation = None
        if warnings:
            warning_confirmation = datetime.now(timezone.utc).isoformat()
            warning_text = "\n".join(f"• {warning}" for warning in warnings)
            if not messagebox.askyesno(
                "Confirm lineup warnings",
                "These warnings require confirmation before saving:\n\n"
                f"{warning_text}\n\nSave this lineup with the warnings recorded?",
            ):
                self.lineup_lock_status.set(
                    "Lineups not locked — warning confirmation was declined"
                )
                return
        previous = self.locked_lineups.get("games", {}).get(key, {})
        try:
            revision = int(previous.get("revision", 0)) + 1
        except (TypeError, ValueError):
            revision = 1
        payload = {
            "game_id": key,
            "date_time": selected.date_time.isoformat(),
            "away_team": away,
            "home_team": home,
            "venue": selected.venue,
            "source": getattr(self, "_lineup_editor_source", "manual"),
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "revision": revision,
            "verify_note": VERIFY_NOTE,
            "lineups": {},
            "validation": {
                "warnings": warnings,
                "warnings_confirmed_at": warning_confirmation,
            },
        }
        for side, team in (("away", away), ("home", home)):
            result = validations[side]
            starter = result.starting_pitcher or {}
            source = payload["source"]
            source_timestamp = getattr(self, "_lineup_editor_loaded_at", None)
            if isinstance(source_timestamp, datetime):
                source_timestamp = source_timestamp.isoformat()
            else:
                source_timestamp = ""
            side_warning_text = [
                self._lineup_issue_text(issue) for issue in result.warnings
            ]
            flex = copy.deepcopy(result.flex) if result.flex else None
            if flex is not None:
                flex.update(
                    {
                        "source": source,
                        "source_timestamp": source_timestamp,
                        "warnings": side_warning_text,
                    }
                )
            payload["lineups"][side] = {
                "team": team,
                "team_code": TEAM_TO_CODE.get(team, ""),
                "starting_pitcher": starter.get("player_name", ""),
                "starting_pitcher_player_id": starter.get("player_id", ""),
                "starting_pitcher_position": starter.get("position", ""),
                "starting_pitcher_position_exception": starter.get(
                    "position_exception"
                ),
                "lineup": result.normalized_lineup,
                "flex": flex,
            }
        candidate_store = copy.deepcopy(self.locked_lineups)
        candidate_store.setdefault("games", {})[key] = payload
        try:
            self.save_locked_lineups(candidate_store)
        except Exception as exc:
            self.lineup_lock_status.set(
                f"Lineups not saved for Game {key}: {exc}. "
                "The previous saved lineup remains active."
            )
            return
        self.locked_lineups = candidate_store
        for side in ("away", "home"):
            self.lineup_widgets[side]["status"].set(self._lineup_status_text())
        source_label = payload["source"].title()
        self.lineup_lock_status.set(
            f"{source_label} lineups saved for official Game {key}; verify before air"
        )
        self.render_producer_prep()
        self.refresh_game_day_dashboard()

    def clear_locked_lineups(self):
        if getattr(self, "_lineup_store_error", ""):
            self.lineup_lock_status.set(
                f"Lineup lock not changed. {self._lineup_store_error}"
            )
            return
        key = self.lineup_key()
        games = self.locked_lineups.get("games", {})
        if key and key in games:
            candidate_store = copy.deepcopy(self.locked_lineups)
            del candidate_store["games"][key]
            try:
                self.save_locked_lineups(candidate_store)
            except Exception as exc:
                self.lineup_lock_status.set(
                    f"Lineup not cleared for Game {key}: {exc}. "
                    "The previous saved lineup remains active."
                )
                return
            self.locked_lineups = candidate_store
        for side in ("away", "home"):
            self.lineup_widgets[side]["status"].set("Projected until locked")
        self.lineup_lock_status.set(
            f"Locked lineups cleared for Game {key}"
            if key
            else "No official game selected; no lineup lock was changed"
        )
        self.render_producer_prep()
        self.refresh_game_day_dashboard()

    def _refresh_manual_note_players(self):
        if not hasattr(self, "note_player_picker"):
            return
        roster = self.db.get("roster", pd.DataFrame()) if self.db else pd.DataFrame()
        self._note_player_all_choices = manual_note_player_choices(roster)
        self.note_player_picker.configure(values=self._note_player_all_choices)

    def _filter_manual_note_players(self, _event=None):
        if not hasattr(self, "note_player_picker"):
            return
        query = self.note_player_var.get().strip().casefold()
        choices = getattr(self, "_note_player_all_choices", [])
        filtered = [choice for choice in choices if query in choice.casefold()]
        self.note_player_picker.configure(values=filtered or choices)

    def _manual_note_scope_changed(self, _event=None):
        scope = self.note_scope_var.get().strip().lower()
        states = {
            "player": ("normal", "disabled", "disabled"),
            "team": ("disabled", "readonly", "disabled"),
            "game": ("disabled", "disabled", "normal"),
            "global": ("disabled", "disabled", "disabled"),
        }
        player_state, team_state, game_state = states.get(
            scope, ("disabled", "disabled", "disabled")
        )
        if hasattr(self, "note_player_picker"):
            self.note_player_picker.configure(state=player_state)
            self.note_team_picker.configure(state=team_state)
            self.note_game_entry.configure(state=game_state)
        prompts = {
            "player": "Player scope requires one exact roster identity.",
            "team": "Team scope applies to every player on the selected team.",
            "game": "Game scope requires an exact ID from the official schedule.",
            "global": "Global notes appear only when a view explicitly opts in.",
        }
        if hasattr(self, "manual_note_status"):
            self.manual_note_status.set(prompts.get(scope, "Choose an explicit note scope."))

    def _official_manual_note_game_id(self, game_id):
        token = _manual_note_identifier(game_id)
        if not token:
            return "", "Enter an exact official game ID before saving"
        schedule = self.db.get("schedule_results", pd.DataFrame()) if self.db else pd.DataFrame()
        if not isinstance(schedule, pd.DataFrame) or schedule.empty:
            return "", "Official schedule is unavailable; game note was not saved"
        column = next(
            (name for name in ("game_id", "gameId") if name in schedule.columns),
            None,
        )
        if column is None:
            return "", "Official schedule game IDs are unavailable; game note was not saved"
        matches = schedule[schedule[column].map(_manual_note_identifier).eq(token)]
        if len(matches) != 1:
            if matches.empty:
                return "", "Game ID was not found in the official schedule; note was not saved"
            return "", "Official schedule has an ambiguous game ID; note was not saved"
        return _manual_note_identifier(matches.iloc[0][column]), ""

    def render_manual_notes(self):
        if not hasattr(self, "manual_notes_view"):
            return
        notes = self.db.get("manual_notes", pd.DataFrame()) if self.db else pd.DataFrame()
        if notes.empty:
            self._set_text(self.manual_notes_view, "No manual producer notes saved yet.")
            return
        lines = [
            "MANUAL PRODUCER NOTES",
            "Explicit scope controls where each note appears. Verify before air unless marked AIR SAFE.",
            "",
        ]
        for _, row in notes.tail(60).iterrows():
            scope = _manual_note_text(row.get("scope")).lower()
            if scope == "player":
                subject = f"{_manual_note_text(row.get('player_name'))} (ID {_manual_note_identifier(row.get('player_id'))})"
            elif scope == "team":
                subject = _manual_note_text(row.get("team_code")).upper()
            elif scope == "game":
                subject = f"Game {_manual_note_identifier(row.get('game_id'))}"
            elif scope == "global":
                subject = "Explicit global note"
            else:
                scope = "legacy_unassigned"
                subject = "NOT ATTACHED - hidden from scoped views"
            air_safe = _manual_note_text(row.get("air_safe")).lower() in {"true", "1", "yes"}
            verified = _manual_note_text(row.get("last_verified_date"))
            verification = (
                f"AIR SAFE; verified {verified or 'date unavailable'}"
                if air_safe
                else "VERIFY BEFORE AIR"
            )
            author = _manual_note_text(row.get("author")) or _manual_note_text(row.get("entered_by")) or "author unavailable"
            source = _manual_note_text(row.get("source")) or "source unavailable"
            timestamp = _manual_note_text(row.get("updated_at")) or _manual_note_text(row.get("created_at")) or "timestamp unavailable"
            note_type = _manual_note_text(row.get("note_type")) or "producer"
            lines.extend(
                [
                    f"[{scope.upper()} | {verification}] {subject}",
                    f"{note_type}: {_manual_note_text(row.get('note_text'))}",
                    f"Author: {author} | Source: {source} | Updated: {timestamp}",
                    "",
                ]
            )
        self._set_text(self.manual_notes_view, "\n".join(lines))

    def reload_manual_notes(self):
        path = self.manual_notes_path()
        try:
            notes, backup_path = migrate_manual_notes_file(path)
        except Exception as exc:
            self.manual_note_status.set(f"Manual notes could not be reloaded: {exc}")
            return
        self.db["manual_notes"] = notes
        self.render_manual_notes()
        if backup_path:
            self.manual_note_status.set(
                f"Manual notes migrated and reloaded; recoverable backup: {backup_path.name}"
            )
        else:
            self.manual_note_status.set("Manual notes reloaded with scope and verification metadata")

    def save_manual_note(self):
        if not self.db:
            self.manual_note_status.set("Database is still loading")
            return
        scope = self.note_scope_var.get().strip().lower()
        if scope not in {"player", "team", "game", "global"}:
            self.manual_note_status.set("Choose an explicit player, team, game, or global scope")
            return
        note_text = self.note_text.get("1.0", "end").strip()
        if not note_text:
            self.manual_note_status.set("Type a note before saving")
            return

        player_id = ""
        player_name = ""
        team_code = ""
        game_id = ""
        roster = self.db.get("roster", pd.DataFrame())
        if scope == "player":
            player, error = resolve_manual_note_player(roster, self.note_player_var.get())
            if player is None:
                self.manual_note_status.set(error)
                return
            player_id = _manual_note_identifier(player.get("player_id"))
            player_name = _manual_note_text(player.get("player_name"))
            team_code = _manual_note_text(player.get("team_code")).upper()
            self.note_player_var.set(
                f"{player_name} | {team_code or 'NO TEAM'} | ID {player_id}"
            )
        elif scope == "team":
            team_code = _manual_note_text(self.note_team_var.get()).upper()
            if team_code not in set(TEAM_TO_CODE.values()):
                self.manual_note_status.set("Choose an exact team from the team dropdown")
                return
        elif scope == "game":
            game_id, error = self._official_manual_note_game_id(self.note_game_var.get())
            if error:
                self.manual_note_status.set(error)
                return

        path = self.manual_notes_path()
        try:
            existing, backup_path = migrate_manual_notes_file(path)
        except Exception as exc:
            self.manual_note_status.set(f"Manual note not saved; migration failed: {exc}")
            return
        existing_ids = pd.to_numeric(existing.get("note_id", pd.Series(dtype=float)), errors="coerce") if not existing.empty else pd.Series(dtype=float)
        note_id = int(existing_ids.max()) + 1 if not existing_ids.empty and pd.notna(existing_ids.max()) else 1
        timestamp = datetime.now(timezone.utc).isoformat()
        author_var = getattr(self, "note_author_var", None)
        author = _manual_note_text(author_var.get()) if author_var is not None else "producer"
        row = {
            "note_id": note_id,
            "scope": scope,
            "player_id": player_id,
            "player_name": player_name,
            "team_code": team_code,
            "game_id": game_id,
            "note_text": note_text,
            "note_type": self.note_type_var.get(),
            "author": author,
            "entered_by": author,
            "source": "manual",
            "last_verified_date": date.today().isoformat() if self.note_air_safe_var.get() else "",
            "air_safe": bool(self.note_air_safe_var.get()),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        try:
            write_manual_notes_atomic(path, updated)
        except Exception as exc:
            self.manual_note_status.set(f"Manual note was not saved: {exc}")
            return
        self.db["manual_notes"] = updated
        self.note_text.delete("1.0", "end")
        backup_suffix = f"; legacy backup: {backup_path.name}" if backup_path else ""
        self.manual_note_status.set(
            f"{scope.title()} note saved locally with source and timestamp{backup_suffix}"
        )
        self.render_manual_notes()

    def update_data(self):
        if not self.network_requests_permitted(
            "Quick Refresh (Core)",
            status_var=getattr(self, "status_var", None),
        ):
            return
        if getattr(self, "_data_update_in_flight", False):
            self.status_var.set("Data update is already in progress.")
            return
        if getattr(self, "_initial_load_in_flight", False):
            self.status_var.set("Wait for the initial database load to finish before updating.")
            return

        cancel_token = CancelToken()
        self._data_update_cancel_token = cancel_token
        self._data_update_in_flight = True
        self._ensure_main_thread_dispatch()
        self._sync_update_button()
        self.status_var.set("Updating official AUSL core data...")
        self._log_event("data_update_started", source="official_ausl_core_data")

        def progress(message):
            self._post_main_thread(
                self._set_data_update_progress, message, cancel_token
            )

        def work():
            try:
                update_all_data(progress, include_enrichment=False, cancel_token=cancel_token)
                data = load_database(include_enrichment=False)
            except RefreshCancelled:
                self._post_main_thread(self._finish_data_update_cancelled, cancel_token)
                return
            except Exception as exc:
                self._post_main_thread(self._finish_data_update_error, exc, cancel_token)
                return
            self._post_main_thread(self._finish_data_update_success, data, cancel_token)

        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            self._finish_data_update_error(exc, cancel_token)

    def _data_update_token_is_current(self, token):
        return token is not None and token is getattr(self, "_data_update_cancel_token", None)

    def _set_data_update_progress(self, message, token):
        if not self._data_update_token_is_current(token):
            return
        self.status_var.set(message)

    def cancel_data_update(self):
        """Cancel an in-flight Quick Refresh immediately.

        Frees the in-flight flag and re-enables the update button right
        away, without waiting for the abandoned background thread's network
        call to finish or time out. That thread's eventual success/error
        callback is discarded as stale once it arrives (see
        ``_data_update_token_is_current``).
        """

        token = getattr(self, "_data_update_cancel_token", None)
        if token is None:
            return
        token.cancel()
        self._data_update_cancel_token = None
        self._data_update_in_flight = False
        self._sync_update_button()
        self.status_var.set("Cancelling data update; last-known-good data retained.")
        if isinstance(getattr(self, "db", None), dict):
            self.db["refresh_attempt"] = {
                "state": "cancelled",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "affected_source": "official_core_sources",
                "error_summary": None,
            }
        self._refresh_game_day_if_allowed()
        self._log_event("data_update_cancel_requested", source="official_ausl_core_data")

    def _finish_data_update_success(self, data, token):
        if not self._data_update_token_is_current(token):
            return
        try:
            self._finish_load(data)
        except Exception as exc:
            self._finish_data_update_error(exc, token)
            return
        row_count = self._roster_count(data)
        self._data_update_in_flight = False
        self._data_update_cancel_token = None
        self._sync_update_button()
        self.status_var.set(f"Update complete — {row_count} current players loaded")
        self._log_event(
            "data_update_succeeded",
            source="official_ausl_data",
            row_count=row_count,
        )

    def _finish_data_update_error(self, exc, token):
        if not self._data_update_token_is_current(token):
            return
        self._data_update_in_flight = False
        self._data_update_cancel_token = None
        self._sync_update_button()
        self.status_var.set(f"Data update failed: {exc}")
        if hasattr(self, "data_health_var"):
            attempt = load_refresh_attempt()
            if isinstance(getattr(self, "db", None), dict):
                self.db["refresh_attempt"] = attempt
            self._apply_data_health_display(
                getattr(self, "db", {}).get("manifest", {}),
                attempt,
            )
        self.refresh_game_day_dashboard()
        self._log_event(
            "data_update_failed",
            source="official_ausl_data",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        messagebox.showerror("AUSL Data Update", str(exc))

    def _finish_data_update_cancelled(self, token):
        if not self._data_update_token_is_current(token):
            return
        self._data_update_in_flight = False
        self._data_update_cancel_token = None
        self._sync_update_button()
        self.status_var.set("Data update cancelled; last-known-good data retained.")
        if isinstance(getattr(self, "db", None), dict):
            self.db["refresh_attempt"] = load_refresh_attempt()
        self.refresh_game_day_dashboard()
        self._log_event("data_update_cancelled", source="official_ausl_core_data")

    @staticmethod
    def _data_health_color(state):
        return {
            "green": "#2e8b57",
            "yellow": "#b8860b",
            "red": "#c0392b",
            "unknown": "#6c757d",
        }.get(state, "#6c757d")

    @staticmethod
    def _data_health_marker(state):
        return {
            "green": "●",
            "yellow": "●",
            "red": "●",
            "unknown": "○",
        }.get(state, "○")

    def _data_health_state(self, manifest, refresh_attempt=None):
        entries = (
            (manifest or {}).get("source_health")
            if isinstance(manifest, dict)
            else {}
        )
        if not isinstance(entries, dict) or not entries:
            snapshot_state = "unknown"
        else:
            statuses = []
            for info in entries.values():
                if not isinstance(info, dict):
                    continue
                status = str(info.get("status", "unknown")).lower()
                if status == "disabled":
                    status = "green"
                if status not in {"green", "yellow", "red"}:
                    status = "yellow"
                statuses.append(status)
            if "red" in statuses:
                snapshot_state = "red"
            elif "yellow" in statuses:
                snapshot_state = "yellow"
            elif statuses:
                snapshot_state = "green"
            else:
                snapshot_state = "unknown"
        attempt_state = (
            str((refresh_attempt or {}).get("state") or "").strip().lower()
            if isinstance(refresh_attempt, dict)
            else ""
        )
        if attempt_state == "failed":
            if snapshot_state in {"green", "yellow"}:
                return "yellow"
            return "red"
        return snapshot_state

    def _apply_data_health_display(self, manifest, refresh_attempt=None):
        if not hasattr(self, "data_health_var"):
            return
        state = self._data_health_state(manifest, refresh_attempt)
        text = self.format_data_health(manifest, refresh_attempt)
        if hasattr(self, "data_health_label"):
            self.data_health_label.configure(foreground=self._data_health_color(state))
        if hasattr(self, "data_health_var"):
            self.data_health_var.set(f"{self._data_health_marker(state)} {text}")

    @staticmethod
    def format_data_freshness(manifest):
        updated_at = (manifest or {}).get("updated_at")
        if not updated_at:
            return f"Data updated: unknown - VERIFY BEFORE AIR: {VERIFY_NOTE}"
        try:
            timestamp = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp = timestamp.astimezone(timezone.utc)
            time_text = timestamp.strftime("%I:%M %p").lstrip("0")
            return f"Data updated: {timestamp.strftime('%B')} {timestamp.day}, {timestamp.year} at {time_text} UTC - VERIFY BEFORE AIR: {VERIFY_NOTE}"
        except ValueError:
            return f"Data updated: {updated_at} - VERIFY BEFORE AIR: {VERIFY_NOTE}"

    @staticmethod
    def _relative_age_text(timestamp, *, now=None):
        if not timestamp:
            return ""
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        age_seconds = int((current.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
        if age_seconds < 0:
            return "future"
        if age_seconds < 60:
            return "just now"
        if age_seconds < 3600:
            minutes = max(1, age_seconds // 60)
            return f"{minutes}m ago"
        if age_seconds < 86400:
            hours = max(1, age_seconds // 3600)
            return f"{hours}h ago"
        days = max(1, age_seconds // 86400)
        return f"{days}d ago"

    @classmethod
    def format_data_health(cls, manifest, refresh_attempt=None):
        entries = (manifest or {}).get("source_health") if isinstance(manifest, dict) else {}
        if not isinstance(entries, dict) or not entries:
            return "Data health: UNKNOWN — no source health manifest available"

        normalized = []
        states = []
        for source_name, info in entries.items():
            if not isinstance(info, dict):
                continue
            status = str(info.get("status", "unknown")).lower()
            if status == "disabled":
                status = "green"
            if status not in {"green", "yellow", "red"}:
                status = "yellow"
            states.append(status)
            detail = str(info.get("status_detail") or info.get("detail") or "validated").strip()
            age_text = cls._relative_age_text(info.get("last_success_at"))
            if age_text:
                detail = f"{detail} ({age_text})"
            normalized.append((source_name, status, detail))

        if "red" in states:
            overall = "RED"
        elif "yellow" in states:
            overall = "YELLOW"
        else:
            overall = "GREEN"

        summary_items = []
        for source_name, status, detail in normalized[:4]:
            display_name = source_name.replace("official_", "").replace("_", " ").strip()
            summary_items.append(f"{display_name}: {status.upper()} — {detail}")
        if len(normalized) > 4:
            summary_items.append(f"+{len(normalized) - 4} more")
        snapshot_text = f"Data health: {overall} — " + "; ".join(summary_items)
        attempt = refresh_attempt if isinstance(refresh_attempt, dict) else {}
        attempt_state = str(attempt.get("state") or "").strip().lower()
        if attempt_state == "failed":
            source = str(attempt.get("affected_source") or "refresh source")
            detail = str(attempt.get("error_summary") or "refresh failed")
            return (
                f"Stored snapshot valid; latest refresh failed ({source}): "
                f"{detail}. {snapshot_text}"
            )
        if attempt_state == "cancelled":
            return (
                f"Latest refresh cancelled; stored snapshot unchanged. {snapshot_text}"
            )
        if attempt_state == "in_progress":
            return f"Refresh in progress; stored snapshot remains active. {snapshot_text}"
        return snapshot_text

    def _scoped_verification_count(self):
        selected = getattr(self, "selected_game", None)
        database = getattr(self, "db", {})
        if not isinstance(selected, SelectedGame) or not isinstance(database, dict):
            return None
        if not database.get("enrichment_enabled"):
            return None
        frame = database.get("official_game_notes")
        required = {"game_id", "subject_team_code", "verification_state"}
        if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
            return None
        if frame.empty:
            return 0
        cache_key = (
            id(frame),
            len(frame),
            selected.game_id,
            selected.away_team_code,
            selected.home_team_code,
        )
        cache = getattr(self, "_verification_count_cache", {})
        if cache_key in cache:
            return cache[cache_key]
        game_ids = frame["game_id"].map(_manual_note_identifier)
        team_codes = frame["subject_team_code"].astype(str).str.strip().str.upper()
        states = frame["verification_state"].astype(str).str.strip().str.upper()
        scoped = game_ids.eq(selected.game_id) & team_codes.isin(
            {selected.away_team_code, selected.home_team_code}
        )
        count = int((scoped & ~states.eq("VERIFIED")).sum())
        self._verification_count_cache = {cache_key: count}
        return count

    def _record_packet_generated(
        self,
        path,
        *,
        generated_at,
        game_id,
        lineup_revision=None,
        lineup_source=None,
    ):
        self._packet_metadata = {
            "path": str(path),
            "game_id": str(game_id),
            "generated_at": generated_at.isoformat(),
            "lineup_revision": lineup_revision,
            "lineup_source": str(lineup_source or "").strip().lower() or None,
        }
        self.refresh_game_day_dashboard()

    def _latest_packet_metadata(self):
        selected = getattr(self, "selected_game", None)
        if not isinstance(selected, SelectedGame):
            return None
        current = getattr(self, "_packet_metadata", {})
        if (
            isinstance(current, dict)
            and str(current.get("game_id", "")) == selected.game_id
        ):
            return dict(current)
        packet_dir = export_dir() / "game_packets"
        if not packet_dir.exists():
            return None
        candidates = []
        for path in packet_dir.glob(f"*_game_{selected.game_id}*_producer_packet.txt"):
            match = PACKET_FILENAME_RE.fullmatch(path.name)
            if match is None or match.group("game_id") != selected.game_id:
                continue
            try:
                generated = datetime.strptime(
                    match.group("stamp"), "%Y%m%dT%H%M%S%fZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            candidates.append((generated, path, match.group("revision")))
        if not candidates:
            return None
        generated, path, revision = max(candidates, key=lambda item: item[0])
        lock = self._current_lineup_lock()
        metadata = {
            "path": str(path),
            "game_id": selected.game_id,
            "generated_at": generated.isoformat(),
            "lineup_revision": int(revision) if revision is not None else None,
            "lineup_source": (
                str(lock.get("source") or "").strip().lower() or None
                if lock
                else None
            ),
        }
        self._packet_metadata = metadata
        return dict(metadata)

    def _rosters_available_for_game(self):
        selected = getattr(self, "selected_game", None)
        roster = getattr(self, "db", {}).get("roster")
        if not isinstance(selected, SelectedGame):
            return None
        if not isinstance(roster, pd.DataFrame) or "team_code" not in roster.columns:
            return None
        codes = roster["team_code"].astype(str).str.strip().str.upper()
        return all(
            bool(codes.eq(team_code).any())
            for team_code in (
                selected.away_team_code,
                selected.home_team_code,
            )
        )

    def _live_readiness_input(self):
        selected = getattr(self, "selected_game", None)
        if not isinstance(selected, SelectedGame):
            return None
        live_game = getattr(self, "live_game", None)
        health = getattr(self, "live_health", None)
        game_id = (
            _manual_note_identifier(live_game.get("gameId"))
            if isinstance(live_game, dict)
            else selected.game_id
        )
        if bool(getattr(self, "_offline_mode", False)):
            state = "disabled"
        elif not isinstance(live_game, dict):
            state = "disconnected"
        elif getattr(health, "state", "").upper() == "GREEN":
            state = "connected"
        elif getattr(health, "state", "").upper() == "YELLOW":
            state = "stale"
        elif getattr(health, "connection_state", "").upper() == "DISCONNECTED":
            state = "disconnected"
        else:
            state = "unavailable"
        return {
            "state": state,
            "game_id": game_id,
            "last_updated": getattr(health, "last_updated", "") or None,
            "age_seconds": getattr(health, "age_seconds", None),
            "game_status": (
                live_game.get("recordStatus")
                if isinstance(live_game, dict)
                else selected.status
            ),
            "auto_refresh": bool(
                getattr(self, "auto_var", None)
                and self.auto_var.get()
                and not bool(getattr(self, "_offline_mode", False))
            ),
        }

    def _lineup_command_center_detail(self, readiness):
        check = next(item for item in readiness.checks if item.key == "lineups")
        provenance = next(
            item for item in readiness.checks if item.key == "lineup_provenance"
        )
        lock = self._current_lineup_lock()
        if not lock:
            return f"[{check.state.upper()}] {check.detail}"
        source = str(lock.get("source") or "unavailable").upper()
        locked_at = str(lock.get("locked_at") or "time unavailable")
        age = self._relative_age_text(lock.get("locked_at"))
        age_text = f" ({age})" if age else ""
        revision = lock.get("revision", "unavailable")
        lineups = lock.get("lineups", {})
        side_parts = []
        nonactive = 0
        warnings = []
        for side in ("away", "home"):
            team = lineups.get(side, {}) if isinstance(lineups, dict) else {}
            entries = team.get("lineup", []) if isinstance(team, dict) else []
            side_parts.append(
                f"{side.title()}: {'saved' if len(entries) == 9 else 'not usable'}"
            )
            for entry in entries:
                status = normalize_roster_status(entry.get("roster_status"))
                if status != "Active":
                    nonactive += 1
            team_warnings = team.get("warnings", []) if isinstance(team, dict) else []
            if isinstance(team_warnings, list):
                warnings.extend(str(item) for item in team_warnings if str(item).strip())
        warning_text = (
            f" Nonactive/unresolved warnings: {nonactive + len(warnings)}."
            if nonactive or warnings
            else " No nonactive or unresolved-player warnings recorded."
        )
        return (
            f"[{check.state.upper()}] {'; '.join(side_parts)} | Game {lock.get('game_id')} | "
            f"source {source} | saved {locked_at}{age_text} | revision {revision}. "
            f"{provenance.detail}{warning_text}"
        )

    def refresh_game_day_dashboard(self):
        database = getattr(self, "db", {})
        manifest = database.get("manifest", {}) if isinstance(database, dict) else {}
        refresh_attempt = (
            database.get("refresh_attempt", {})
            if isinstance(database, dict)
            else {}
        )
        health_state = self._data_health_state(manifest, refresh_attempt)
        health_detail = self.format_data_health(manifest, refresh_attempt)
        packet = self._latest_packet_metadata()
        readiness = aggregate_game_day_readiness(
            selected_game=getattr(self, "selected_game", None),
            data_health_state=health_state,
            data_health_detail=health_detail,
            refresh_attempt=refresh_attempt,
            rosters_available=self._rosters_available_for_game(),
            lineup_lock=self._current_lineup_lock(),
            live_feed=self._live_readiness_input(),
            verification_count=self._scoped_verification_count(),
            packet=packet,
            offline_mode=bool(getattr(self, "_offline_mode", False)),
        )
        self.game_day_readiness = readiness

        overall = {
            "ready": ("READY FOR AIR", "ReadinessReady.TLabel"),
            "needs-attention": (
                "NEEDS ATTENTION",
                "ReadinessAttention.TLabel",
            ),
            "not-ready": ("NOT READY", "ReadinessNotReady.TLabel"),
        }[readiness.overall_state]
        if hasattr(self, "game_day_overall_var"):
            self.game_day_overall_var.set(overall[0])
        if hasattr(self, "game_day_overall_label"):
            self.game_day_overall_label.configure(style=overall[1])
        if hasattr(self, "game_day_counts_var"):
            self.game_day_counts_var.set(
                f"{readiness.blocking_issue_count} blocking issue(s) · "
                f"{readiness.warning_count} warning/unavailable item(s)"
            )

        checks = {check.key: check for check in readiness.checks}
        selected = getattr(self, "selected_game", None)
        if hasattr(self, "game_day_selected_var"):
            if isinstance(selected, SelectedGame):
                away_record = official_team_snapshot(
                    selected.away_team_code, selected.season, database
                ).record_text
                home_record = official_team_snapshot(
                    selected.home_team_code, selected.season, database
                ).record_text
                self.game_day_selected_var.set(
                    f"[PASS] {selected.away_team} ({away_record}) at "
                    f"{selected.home_team} ({home_record})\n"
                    f"{selected.first_pitch_label} | {selected.venue} | "
                    f"{selected.status} | Game ID {selected.game_id}\n"
                    f"Schedule: {selected.source_name} | Updated "
                    f"{selected.source_updated_at}"
                )
            else:
                self.game_day_selected_var.set(
                    "[FAIL] No official game selected. Use Game Setup above."
                )
        if hasattr(self, "game_day_data_var"):
            self.game_day_data_var.set(
                f"[{checks['core_data'].state.upper()}] {checks['core_data'].detail}\n"
                f"Snapshot: {(manifest or {}).get('updated_at', 'unavailable')}\n"
                f"[{checks['latest_refresh'].state.upper()}] "
                f"{checks['latest_refresh'].detail}"
            )
        if hasattr(self, "game_day_lineup_var"):
            self.game_day_lineup_var.set(
                self._lineup_command_center_detail(readiness)
            )
        if hasattr(self, "game_day_live_var"):
            live = self._live_readiness_input() or {}
            age = live.get("age_seconds")
            age_text = f"{age}s old" if isinstance(age, int) else "age unavailable"
            self.game_day_live_var.set(
                f"[{checks['live_feed'].state.upper()}] "
                f"{checks['live_feed'].detail}\n"
                f"Game ID {live.get('game_id') or 'unavailable'} | "
                f"lastUpdated {live.get('last_updated') or 'unavailable'} | "
                f"{age_text} | auto-refresh "
                f"{'ON' if live.get('auto_refresh') else 'OFF'}"
            )
        if hasattr(self, "game_day_verification_var"):
            self.game_day_verification_var.set(
                f"[{checks['verification_queue'].state.upper()}] "
                f"{checks['verification_queue'].detail}"
            )
        if hasattr(self, "game_day_packet_var"):
            source = (
                f" | lineup source {packet.get('lineup_source') or 'unavailable'}"
                if packet
                else ""
            )
            revision = (
                f" | lineup revision {packet.get('lineup_revision')}"
                if packet and packet.get("lineup_revision") is not None
                else ""
            )
            self.game_day_packet_var.set(
                f"[{checks['producer_packet'].state.upper()}] "
                f"{checks['producer_packet'].detail}\n"
                f"Generated "
                f"{packet.get('generated_at') if packet else 'not generated'}"
                f"{revision}{source}"
            )
        if hasattr(self, "game_day_network_var"):
            self.game_day_network_var.set(
                f"[{checks['network_permission'].state.upper()}] "
                f"{checks['network_permission'].detail}"
            )
        if hasattr(self, "game_day_checklist"):
            marker = {
                "pass": "[PASS]",
                "warning": "[WARN]",
                "fail": "[FAIL]",
                "unavailable": "[N/A]",
                "not-applicable": "[—]",
            }
            lines = [
                f"{marker[check.state]} {check.label}: {check.detail}"
                for check in readiness.checks
            ]
            self._set_text(self.game_day_checklist, "\n\n".join(lines))
        return readiness

    def game_codes(self):
        selected = getattr(self, "selected_game", None)
        if isinstance(selected, SelectedGame):
            return {selected.away_team_code, selected.home_team_code}
        return {TEAM_TO_CODE.get(self.away_var.get()), TEAM_TO_CODE.get(self.home_var.get())}

    @staticmethod
    def roster_status(row):
        raw_status = row.get("roster_status") if row is not None and "roster_status" in row else None
        return normalize_roster_status(raw_status)

    @classmethod
    def roster_list_text(cls, row):
        team_code = (_optional_text(row, "team_code") or "TEAM UNKNOWN").upper()
        raw_number = _optional_text(row, "jersey_number")
        number = raw_number[:-2] if raw_number and raw_number.endswith(".0") else raw_number
        number = number or "—"
        position = (_optional_text(row, "position") or "POSITION UNKNOWN").upper()
        player_name = _optional_text(row, "player_name") or "Player name unavailable"
        return (
            f"{team_code:<12}  #{number:<3} {position:<16} "
            f"{player_name}  [{cls.roster_status(row)}]"
        )

    @staticmethod
    def player_title_text(row):
        team_code = (_optional_text(row, "team_code") or "TEAM UNKNOWN").upper()
        raw_number = _optional_text(row, "jersey_number")
        number = raw_number[:-2] if raw_number and raw_number.endswith(".0") else raw_number
        number_label = f"#{number}" if number else "NUMBER UNAVAILABLE"
        position = (_optional_text(row, "position") or "POSITION UNKNOWN").upper()
        player_name = (_optional_text(row, "player_name") or "Player name unavailable").upper()
        return f"{player_name}   {number_label}   {position}   {team_code}"

    @classmethod
    def player_meta_text(cls, row):
        details = [
            f"Status: {cls.roster_status(row)}",
            f"B/T: {value(row, 'bats_throws')}",
            f"College: {value(row, 'college')}",
            f"Hometown: {value(row, 'hometown')}",
            f"Height: {value(row, 'height')}",
        ]
        draft_info = cls.compact_draft_info(row)
        if draft_info:
            details[-1] += f"  |  Draft: {draft_info}"
        warning = cls.availability_warning(row)
        if warning:
            details.append(warning)
        return "  |  ".join(details)

    @classmethod
    def is_active_roster(cls, row):
        return cls.roster_status(row).strip().lower() == "active"

    @classmethod
    def availability_warning(cls, row):
        status = cls.roster_status(row)
        if status.lower() == "active":
            return ""
        if status.lower() == "status unknown":
            return "Warning: roster status is unknown. Verify availability before using on air."
        return f"Warning: player is listed as {status}. Verify availability before using on air."


    def show_all(self):
        self._search_view = "all"
        self._search_team = None
        self.search_var.set("")
        self.search()

    def show_team(self, team):
        self._search_view = "team"
        self._search_team = team
        self.search_var.set("")
        self.search()

    def _on_search_scope_changed(self):
        self._search_view = None
        self._search_team = None
        self.search()

    def search(self):
        if not self.db:
            return
        frame = self.db["roster"].copy()
        view = getattr(self, "_search_view", None)
        if view == "team":
            frame = frame[frame["team"].eq(getattr(self, "_search_team", None))]
            scope_label = f"Showing: {getattr(self, '_search_team', '')} roster"
        elif view == "all":
            scope_label = "Showing: all players"
        elif self.scope_var.get():
            frame = frame[frame["team_code"].isin(self.game_codes())]
            scope_label = "Showing: selected game teams"
        else:
            scope_label = "Showing: all players"
        query = self.search_var.get().strip()
        frame = filter_roster_search(frame, query)
        if hasattr(self, "search_scope_var"):
            self.search_scope_var.set(scope_label)
        frame = frame.sort_values(["team_code", "last_name", "first_name"])
        self.search_rows = [row for _, row in frame.iterrows()]
        self.results.delete(0, "end")
        for row in self.search_rows:
            flag = "" if self.is_active_roster(row) else " !"
            self.results.insert("end", self.roster_list_text(row) + flag)
        if not self.search_rows and re.fullmatch(r"#?\s*\d+", query):
            self.results.insert("end", f"No matching number — {scope_label.lower()}")

    def select_result(self, _event=None):
        selected = self.results.curselection()
        if not selected or selected[0] >= len(self.search_rows):
            return
        row = self.search_rows[selected[0]]
        self.selected_player_id = int(row["player_id"])
        self.render_player(row)

    def stat_row(self, key):
        frame = self.db.get(key, pd.DataFrame())
        if frame.empty or self.selected_player_id is None or "player_id" not in frame:
            return None
        rows = frame[pd.to_numeric(frame["player_id"], errors="coerce").eq(self.selected_player_id)]
        return rows.iloc[0] if len(rows) == 1 else None

    def batting_line(self, row):
        if row is None:
            return "No batting stats available"
        return f"{whole(row,'gamesPlayed')} G | {whole(row,'plateAppearances')} PA | {whole(row,'hits')} H | {whole(row,'homeRuns')} HR | {whole(row,'runsBattedIn')} RBI | {rate(row,'battingAverage')} AVG | {rate(row,'onBasePercentage')} OBP | {rate(row,'sluggingPercentage')} SLG | {rate(row,'opsPercentage')} OPS"

    def pitching_line(self, row):
        if row is None:
            return "No pitching stats available"
        outs = self._innings_to_outs(value(row, "inningsPitched", None))
        innings = self._outs_to_innings(outs) if outs is not None else "—"
        whip = canonical_pitching_whip(row)
        return f"{whole(row,'appearances')} APP / {whole(row,'gamesStarted')} GS | {whole(row,'wins')}-{whole(row,'losses')} | {innings} IP | {decimal(row,'earnedRunAverage')} ERA | {whole(row,'strikeOuts')} SO | {whole(row,'baseOnBalls')} BB | {_format_decimal_value(whip)} WHIP | {whole(row,'saves')} SV"

    def fielding_line(self, row):
        if row is None:
            return "No fielding stats available"
        return f"{whole(row,'gamesPlayed')} G | {whole(row,'putOuts')} PO | {whole(row,'assists')} A | {whole(row,'errors')} E | {rate(row,'fieldingPercent')} FLD%"

    @staticmethod
    def _frame_sum(frame, column):
        if frame.empty or column not in frame:
            return None
        numeric = pd.to_numeric(frame[column], errors="coerce")
        finite = numeric.notna() & numeric.map(
            lambda item: bool(pd.notna(item) and math.isfinite(float(item)))
        )
        if numeric.empty or not bool(finite.all()):
            return None
        return float(numeric.sum())

    @staticmethod
    def _innings_to_outs(value_to_convert):
        return innings_to_outs(value_to_convert)

    @staticmethod
    def _outs_to_innings(outs):
        return outs_to_innings(outs)

    @classmethod
    def _sum_innings_outs(cls, values):
        parsed = [cls._innings_to_outs(item) for item in values]
        if not parsed or any(item is None for item in parsed):
            return None
        return sum(parsed)

    def render_team_totals(self):
        if not self.db or not hasattr(self, "team_stat_trees"):
            return
        team = self.team_totals_team_var.get()
        year = int(self.team_totals_season_var.get())
        code = TEAM_TO_CODE.get(team, "")
        snapshot = official_team_snapshot(code, year, self.db)

        def team_frame(category):
            frame = self.db.get(f"{category}_{year}", pd.DataFrame())
            if frame.empty or "team_code" not in frame:
                return frame.iloc[0:0]
            return frame[frame["team_code"].astype(str).eq(code)]

        batting = team_frame("batting")
        pitching = team_frame("pitching")
        fielding = team_frame("fielding")
        for tree in self.team_stat_trees.values():
            tree.delete(*tree.get_children(""))
        if batting.empty and pitching.empty:
            self.team_totals_copy_text = f"No {year} totals are available for {team}."
            self.team_totals_summary_var.set(self.team_totals_copy_text)
            return

        ab = self._frame_sum(batting, "atBat")
        hits = self._frame_sum(batting, "hits")
        walks = self._frame_sum(batting, "baseonBalls")
        hbp = self._frame_sum(batting, "hitByPitch")
        sac_flies = self._frame_sum(batting, "sacrificeFly")
        total_bases = self._frame_sum(batting, "totalBases")
        avg = hits / ab if hits is not None and ab is not None and ab > 0 else None
        obp_inputs = (ab, hits, walks, hbp, sac_flies)
        obp_denominator = (
            ab + walks + hbp + sac_flies
            if all(item is not None for item in obp_inputs)
            else None
        )
        obp = (
            (hits + walks + hbp) / obp_denominator
            if obp_denominator is not None and obp_denominator > 0
            else None
        )
        slg = (
            total_bases / ab
            if total_bases is not None and ab is not None and ab > 0
            else None
        )
        ops = obp + slg if obp is not None and slg is not None else None

        pitcher_wins = self._frame_sum(pitching, "wins")
        pitcher_losses = self._frame_sum(pitching, "losses")
        innings_outs = self._sum_innings_outs(
            pitching.get("inningsPitched", pd.Series(dtype=float))
        )
        innings_decimal = innings_outs / 3 if innings_outs is not None else None
        hits_allowed = self._frame_sum(pitching, "hitsAllowed")
        earned_runs = self._frame_sum(pitching, "earnedRuns")
        pitching_walks = self._frame_sum(pitching, "baseOnBalls")
        era = (
            earned_runs * 7 / innings_decimal
            if earned_runs is not None and innings_decimal
            else None
        )
        whip = (
            (hits_allowed + pitching_walks) / innings_decimal
            if hits_allowed is not None
            and pitching_walks is not None
            and innings_decimal
            else None
        )

        putouts = self._frame_sum(fielding, "putOuts")
        assists = self._frame_sum(fielding, "assists")
        errors = self._frame_sum(fielding, "errors")
        chances = self._frame_sum(fielding, "totalChances")
        fielding_percent = (
            (putouts + assists) / chances
            if putouts is not None
            and assists is not None
            and chances is not None
            and chances > 0
            else None
        )

        self.team_totals_summary_var.set(
            f"{team}  |  {year}  |  {snapshot.record_text}  •  Click any column heading to sort"
        )
        batting_tree = self.team_stat_trees["batting"]
        batting_rows = (
            batting.sort_values("atBat", ascending=False, na_position="last")
            if "atBat" in batting
            else batting
        )
        for _, row in batting_rows.iterrows():
            batting_tree.insert("", "end", values=(
                value(row, "player_name"), whole(row, "gamesPlayed"), whole(row, "atBat"), whole(row, "runs"), whole(row, "hits"),
                whole(row, "doubles"), whole(row, "triples"), whole(row, "homeRuns"), whole(row, "runsBattedIn"), whole(row, "baseonBalls"),
                whole(row, "strikeOuts"), whole(row, "stolenBases"), rate(row, "battingAverage"), rate(row, "onBasePercentage"),
                rate(row, "sluggingPercentage"), rate(row, "opsPercentage"),
            ))
        batting_tree.insert("", "end", tags=("total",), values=(
            "TEAM TOTALS", snapshot.games_played if snapshot.games_played is not None else "—", _format_whole_value(ab), _format_whole_value(self._frame_sum(batting, "runs")), _format_whole_value(hits), _format_whole_value(self._frame_sum(batting, "doubles")),
            _format_whole_value(self._frame_sum(batting, "triples")), _format_whole_value(self._frame_sum(batting, "homeRuns")), _format_whole_value(self._frame_sum(batting, "runsBattedIn")),
            _format_whole_value(walks), _format_whole_value(self._frame_sum(batting, "strikeOuts")), _format_whole_value(self._frame_sum(batting, "stolenBases")), _format_rate_value(avg), _format_rate_value(obp),
            _format_rate_value(slg), _format_rate_value(ops),
        ))

        pitching_tree = self.team_stat_trees["pitching"]
        pitching_rows = list(pitching.iterrows())
        pitching_rows.sort(
            key=lambda item: self._innings_to_outs(
                value(item[1], "inningsPitched", None)
            )
            if self._innings_to_outs(value(item[1], "inningsPitched", None)) is not None
            else -1,
            reverse=True,
        )
        for _, row in pitching_rows:
            player_outs = self._innings_to_outs(value(row, "inningsPitched", None))
            player_innings = player_outs / 3 if player_outs is not None else None
            player_hits = self._stat_optional_number(row, "hitsAllowed")
            player_walks = self._stat_optional_number(row, "baseOnBalls")
            player_whip = (
                (player_hits + player_walks) / player_innings
                if player_hits is not None
                and player_walks is not None
                and player_innings
                else None
            )
            pitching_tree.insert("", "end", values=(
                value(row, "player_name"), whole(row, "appearances"), whole(row, "gamesStarted"), whole(row, "wins"), whole(row, "losses"),
                decimal(row, "earnedRunAverage", 2), _format_innings_value(value(row, "inningsPitched", None)), whole(row, "hitsAllowed"), whole(row, "runs"), whole(row, "earnedRuns"),
                whole(row, "baseOnBalls"), whole(row, "strikeOuts"), _format_decimal_value(player_whip), whole(row, "saves"),
            ))
        pitching_tree.insert("", "end", tags=("total",), values=(
            "CALCULATED PITCHER TOTALS", _format_whole_value(self._frame_sum(pitching, "appearances")), "—", _format_whole_value(pitcher_wins), _format_whole_value(pitcher_losses), _format_decimal_value(era), self._outs_to_innings(innings_outs) or "—",
            _format_whole_value(hits_allowed), _format_whole_value(self._frame_sum(pitching, "runs")), _format_whole_value(earned_runs), _format_whole_value(pitching_walks), _format_whole_value(self._frame_sum(pitching, "strikeOuts")),
            _format_decimal_value(whip), _format_whole_value(self._frame_sum(pitching, "saves")),
        ))

        fielding_tree = self.team_stat_trees["fielding"]
        fielding_rows = (
            fielding.sort_values("gamesPlayed", ascending=False, na_position="last")
            if "gamesPlayed" in fielding
            else fielding
        )
        for _, row in fielding_rows.iterrows():
            fielding_tree.insert("", "end", values=(
                value(row, "player_name"), value(row, "fielding_positions", value(row, "position")), whole(row, "gamesPlayed"), whole(row, "putOuts"),
                whole(row, "assists"), whole(row, "errors"), rate(row, "fieldingPercent"), whole(row, "doublePlays"),
            ))
        fielding_tree.insert("", "end", tags=("total",), values=(
            "TEAM TOTALS", "—", snapshot.games_played if snapshot.games_played is not None else "—", _format_whole_value(putouts), _format_whole_value(assists), _format_whole_value(errors), _format_rate_value(fielding_percent), _format_whole_value(self._frame_sum(fielding, "doublePlays")),
        ))

        record_lines = [snapshot.record_text]
        if snapshot.games_played is not None:
            record_lines[0] += f"  |  {snapshot.games_played} games"
        if snapshot.source_name or snapshot.source_timestamp:
            record_lines.append(
                "Source: "
                + " | ".join(
                    item
                    for item in (snapshot.source_name, snapshot.source_timestamp)
                    if item
                )
            )
        elif not snapshot.available:
            record_lines.append("Official standings source unavailable or ambiguous.")

        batting_output = ["BATTING"]
        if batting.empty:
            batting_output.append("Totals unavailable — source data missing.")
        else:
            batting_output.extend(
                [
                    f"{_format_whole_value(ab)} AB  |  {_format_whole_value(self._frame_sum(batting, 'runs'))} R  |  {_format_whole_value(hits)} H  |  {_format_whole_value(self._frame_sum(batting, 'doubles'))} 2B  |  {_format_whole_value(self._frame_sum(batting, 'triples'))} 3B",
                    f"{_format_whole_value(self._frame_sum(batting, 'homeRuns'))} HR  |  {_format_whole_value(self._frame_sum(batting, 'runsBattedIn'))} RBI  |  {_format_whole_value(walks)} BB  |  {_format_whole_value(self._frame_sum(batting, 'strikeOuts'))} SO  |  {_format_whole_value(self._frame_sum(batting, 'stolenBases'))} SB",
                    f"{_format_rate_value(avg)} AVG  |  {_format_rate_value(obp)} OBP  |  {_format_rate_value(slg)} SLG  |  {_format_rate_value(ops)} OPS",
                ]
            )

        pitching_output = ["PITCHING"]
        if pitching.empty:
            pitching_output.append("Totals unavailable — source data missing.")
        else:
            decision_text = (
                f"{_format_whole_value(pitcher_wins)}-{_format_whole_value(pitcher_losses)}"
                if pitcher_wins is not None and pitcher_losses is not None
                else "unavailable"
            )
            pitching_output.extend(
                [
                    f"Calculated pitcher decisions: {decision_text}  |  {self._outs_to_innings(innings_outs) or '—'} IP  |  {_format_decimal_value(era)} ERA  |  {_format_decimal_value(whip)} WHIP  |  {_format_whole_value(self._frame_sum(pitching, 'saves'))} SV",
                    f"{_format_whole_value(hits_allowed)} H  |  {_format_whole_value(self._frame_sum(pitching, 'runs'))} R  |  {_format_whole_value(earned_runs)} ER  |  {_format_whole_value(pitching_walks)} BB  |  {_format_whole_value(self._frame_sum(pitching, 'strikeOuts'))} SO  |  {_format_whole_value(self._frame_sum(pitching, 'homeRuns'))} HR",
                ]
            )

        fielding_output = ["FIELDING"]
        if fielding.empty:
            fielding_output.append("Totals unavailable — source data missing.")
        else:
            fielding_output.append(
                f"{_format_whole_value(putouts)} PO  |  {_format_whole_value(assists)} A  |  {_format_whole_value(errors)} E  |  {_format_rate_value(fielding_percent)} FLD%  |  {_format_whole_value(self._frame_sum(fielding, 'doublePlays'))} DP"
            )

        output = [
            f"{team.upper()} — {year} TEAM TOTALS",
            self.data_freshness_text,
            "IMPORTED DATA - VERIFY BEFORE AIR",
            "",
            "TEAM RECORD",
            *record_lines,
            "",
            *batting_output,
            "",
            *pitching_output,
            "",
            *fielding_output,
        ]
        self.team_totals_copy_text = "\n".join(output)

    def copy_team_totals(self):
        if not self.team_totals_copy_text:
            self.team_totals_status.set("Select a team with available totals")
            return
        self.root.clipboard_clear(); self.root.clipboard_append(self.team_totals_copy_text); self.root.update()
        self.team_totals_status.set("Team totals copied to clipboard")

    def _player_row(self, key, player_id):
        frame = self.db.get(key, pd.DataFrame())
        if frame.empty or "player_id" not in frame:
            return None
        rows = frame[pd.to_numeric(frame["player_id"], errors="coerce").eq(int(player_id))]
        return rows.iloc[0] if len(rows) == 1 else None

    def _active_team_roster(self, team):
        roster = self.db.get("roster", pd.DataFrame())
        if roster.empty or "team" not in roster:
            return roster.iloc[0:0]
        roster = roster[roster["team"].astype(str).eq(str(team))].copy()
        if roster.empty:
            return roster
        return roster[roster.apply(self.is_active_roster, axis=1)]

    def _projected_lineup(self, team, year):
        roster = self._active_team_roster(team)
        candidates = []
        for _, player in roster.iterrows():
            stats = self._player_row(f"batting_{year}", player["player_id"])
            if stats is None:
                continue
            position = str(value(player, "position", "")).upper()
            plate_appearances = self._stat_optional_number(stats, "plateAppearances")
            on_base = self._stat_optional_number(stats, "onBasePercentage")
            ops = self._stat_optional_number(stats, "opsPercentage")
            if plate_appearances is None or plate_appearances <= 0 or on_base is None or ops is None:
                continue
            candidates.append(
                {
                    "player": player,
                    "stats": stats,
                    "pitcher_only": position in {"P", "RHP", "LHP"},
                    "starts": self._stat_optional_number(stats, "gamesStarted") or 0,
                    "pa": plate_appearances,
                    "obp": on_base,
                    "ops": ops,
                    "sb": self._stat_optional_number(stats, "stolenBases") or 0,
                }
            )
        regulars = [item for item in candidates if not item["pitcher_only"] and item["pa"] > 0]
        regulars.sort(key=lambda item: (item["starts"], item["pa"], item["ops"]), reverse=True)
        selected = regulars[:9]
        if len(selected) < 9:
            selected_player_ids = {
                int(item["player"]["player_id"]) for item in selected
            }
            extras = [
                item
                for item in candidates
                if int(item["player"]["player_id"]) not in selected_player_ids
                and item["pa"] > 0
            ]
            extras.sort(key=lambda item: (item["starts"], item["pa"], item["ops"]), reverse=True)
            selected.extend(extras[: 9 - len(selected)])
        if not selected:
            return []
        leadoff = max(selected, key=lambda item: (item["obp"] + item["sb"] * 0.01, item["pa"]))
        remainder = [item for item in selected if item is not leadoff]
        remainder.sort(key=lambda item: (item["ops"], item["obp"], item["pa"]), reverse=True)
        return [leadoff, *remainder]

    def _projected_pitchers(self, team, year):
        roster = self._active_team_roster(team)
        choices = []
        for _, player in roster.iterrows():
            if str(value(player, "position", "")).strip().upper() not in {"P", "RHP", "LHP"}:
                continue
            stats = self._player_row(f"pitching_{year}", player["player_id"])
            if stats is None:
                continue
            appearances = self._stat_optional_number(stats, "appearances")
            if appearances is None or appearances <= 0:
                continue
            outs = self._innings_to_outs(value(stats, "inningsPitched", None))
            if outs is None:
                continue
            choices.append(
                (
                    self._stat_optional_number(stats, "gamesStarted") or 0,
                    outs,
                    appearances,
                    player,
                    stats,
                )
            )
        return sorted(choices, key=lambda item: item[:3], reverse=True)

    def _packet_broadcast_note(self, player, year):
        player_id = player["player_id"]
        is_pitcher = str(value(player, "position", "")).upper() in {"P", "RHP", "LHP"}
        return self.build_broadcast_note(
            is_pitcher,
            self._player_row("career_batting", player_id),
            self._player_row("career_pitching", player_id),
            self._player_row(f"batting_{year}", player_id),
            self._player_row(f"pitching_{year}", player_id),
        )

    def _packet_team_snapshot(self, team, year):
        code = TEAM_TO_CODE.get(team, "")
        snapshot = official_team_snapshot(code, year, self.db)
        batting = self.db.get(f"batting_{year}", pd.DataFrame())
        pitching = self.db.get(f"pitching_{year}", pd.DataFrame())
        batting = (
            batting[batting["team_code"].astype(str).eq(code)]
            if not batting.empty and "team_code" in batting
            else batting.iloc[0:0]
        )
        pitching = (
            pitching[pitching["team_code"].astype(str).eq(code)]
            if not pitching.empty and "team_code" in pitching
            else pitching.iloc[0:0]
        )
        ab = self._frame_sum(batting, "atBat")
        hits = self._frame_sum(batting, "hits")
        walks = self._frame_sum(batting, "baseonBalls")
        hbp = self._frame_sum(batting, "hitByPitch")
        sf = self._frame_sum(batting, "sacrificeFly")
        tb = self._frame_sum(batting, "totalBases")
        avg = hits / ab if hits is not None and ab is not None and ab > 0 else None
        obp_denominator = (
            ab + walks + hbp + sf
            if all(item is not None for item in (ab, hits, walks, hbp, sf))
            else None
        )
        obp = (
            (hits + walks + hbp) / obp_denominator
            if obp_denominator is not None and obp_denominator > 0
            else None
        )
        slg = tb / ab if tb is not None and ab is not None and ab > 0 else None
        ops = obp + slg if obp is not None and slg is not None else None
        outs = self._sum_innings_outs(
            pitching.get("inningsPitched", pd.Series(dtype=float))
        )
        innings = outs / 3 if outs is not None else None
        earned_runs = self._frame_sum(pitching, "earnedRuns")
        era = earned_runs * 7 / innings if earned_runs is not None and innings else None
        lines = [f"Record: {snapshot.record_text}" if snapshot.available else snapshot.record_text]
        if batting.empty:
            lines.append("Offense: unavailable — source data missing.")
        else:
            lines.extend(
                [
                    f"Offense: {_format_whole_value(self._frame_sum(batting, 'runs'))} R | {_format_whole_value(hits)} H | {_format_whole_value(self._frame_sum(batting, 'homeRuns'))} HR | {_format_whole_value(self._frame_sum(batting, 'runsBattedIn'))} RBI",
                    f"Slash line: {_format_rate_value(avg)} AVG | {_format_rate_value(obp)} OBP | {_format_rate_value(slg)} SLG | {_format_rate_value(ops)} OPS",
                ]
            )
        if pitching.empty:
            lines.append("Pitching: unavailable — source data missing.")
        else:
            lines.append(
                f"Pitching: {self._outs_to_innings(outs) or '—'} IP | {_format_decimal_value(era)} ERA | {_format_whole_value(self._frame_sum(pitching, 'strikeOuts'))} SO"
            )
        if snapshot.source_name or snapshot.source_timestamp:
            lines.append(
                "Official standings source: "
                + " | ".join(
                    item
                    for item in (snapshot.source_name, snapshot.source_timestamp)
                    if item
                )
            )
        else:
            lines.append("Official standings source unavailable or ambiguous.")
        return lines

    def _media_guide_player_lines(self, player_id, limit=2, *, include_review=False):
        clean_notes = _air_ready_media_rows(
            self.db.get("clean_media_notes", pd.DataFrame()),
            expected_entity_type="player",
            expected_entity_id=player_id,
        )
        if not clean_notes.empty and {"entity_type", "entity_id", "note_text"}.issubset(clean_notes.columns):
            rows = clean_notes[
                clean_notes["entity_type"].astype(str).str.lower().eq("player")
                & pd.to_numeric(clean_notes["entity_id"], errors="coerce").eq(int(player_id))
            ].copy()
            if not rows.empty:
                media_context = media_guide_source_context()
                previous_year = int(media_context["previous_year"])
                category_order = {"bio": 0, f"{previous_year}_AUSL": 1, "college": 2, "award": 3, "fun_fact": 4, "personal": 5}
                rows["_priority"] = rows.get("note_category", pd.Series(dtype=str)).map(category_order).fillna(9)
                rows["_confidence"] = pd.to_numeric(
                    rows.get("confidence_score", pd.Series(pd.NA, index=rows.index)),
                    errors="coerce",
                )
                rows = rows.sort_values(
                    ["_priority", "_confidence"],
                    ascending=[True, False],
                    na_position="last",
                )
                lines = []
                for _, row in rows.iterrows():
                    note = str(value(row, "note_text", "")).strip()
                    if len(note) > 420:
                        note = note[:420].rstrip() + "..."
                    category = value(row, "note_category", "bio")
                    printed_pages = value(row, "expected_printed_pages", "verify")
                    pdf_pages = value(
                        row,
                        "parsed_pdf_pages",
                        value(row, "source_pages", "verify"),
                    )
                    guide_date = _media_guide_date_label(
                        value(row, "guide_date", "")
                    )
                    review_state = _canonical_media_review_state(
                        row,
                        expected_entity_type="player",
                        expected_entity_id=player_id,
                    )
                    lines.append(
                        f"- [{review_state} | {category}] "
                        f"{value(row, 'entity_name', 'Identity unavailable')}: {note} "
                        f"({value(row, 'source_name', 'media guide')}; "
                        f"printed pages {printed_pages}; PDF pages {pdf_pages}; "
                        f"guide date {guide_date})"
                    )
                    if len(lines) >= limit:
                        return lines
                if lines:
                    return lines

        raw_frame = self.db.get("media_players", pd.DataFrame())
        frame = (
            raw_frame.copy()
            if include_review
            else _air_ready_media_rows(
                raw_frame,
                expected_entity_type="player",
                expected_entity_id=player_id,
            )
        )
        if frame.empty or "player_id" not in frame:
            return []
        rows = frame[pd.to_numeric(frame["player_id"], errors="coerce").eq(int(player_id))]
        if rows.empty:
            return []
        if include_review:
            status = str(value(rows.iloc[0], "match_status", "")).strip().lower()
            guide_date = _media_guide_date_label(
                value(rows.iloc[0], "guide_date", "")
            )
            if status == "not_in_guide":
                return [
                    f"- [NOT IN GUIDE] Not included in the {guide_date} media guide; "
                    "no biography inferred."
                ]
            if status == "needs_review":
                row = rows.iloc[0]
                printed_pages = value(row, "expected_printed_pages", "unavailable")
                pdf_pages = value(row, "parsed_pdf_pages", "unavailable")
                warning = value(row, "warnings", "Identity validation incomplete.")
                return [
                    f"- [VERIFY] Media guide material is browse-only and not air-ready "
                    f"(printed pages {printed_pages}; PDF pages {pdf_pages}; "
                    f"guide date {guide_date}). {warning}"
                ]
        rows = rows.assign(
            _page=pd.to_numeric(rows.get("source_page", pd.Series(dtype=float)), errors="coerce").fillna(0),
            _toc=rows.get("media_guide_bio", pd.Series(dtype=str)).astype(str).str.count(r"\.{6,}"),
        ).sort_values(["_toc", "_page"], ascending=[True, True])
        lines = []
        for _, row in rows.iterrows():
            note = str(value(row, "media_guide_bio", "")).strip()
            if note.count("......") >= 2:
                continue
            if len(note) > 420:
                note = note[:420].rstrip() + "..."
            status = _canonical_media_review_state(
                row,
                expected_entity_type="player",
                expected_entity_id=player_id,
            )
            printed_pages = value(row, "expected_printed_pages", "verify")
            pdf_pages = value(
                row, "parsed_pdf_pages", value(row, "source_pages", "verify")
            )
            guide_date = _media_guide_date_label(value(row, "guide_date", ""))
            lines.append(
                f"- [{status}] {note} (printed pages {printed_pages}; "
                f"PDF pages {pdf_pages}; guide date {guide_date})"
            )
            if len(lines) >= limit:
                break
        return lines

    def _media_guide_team_lines(self, team, limit=2):
        code = TEAM_TO_CODE.get(team, "")
        clean_notes = _air_ready_media_rows(
            self.db.get("clean_media_notes", pd.DataFrame()),
            expected_entity_type="team",
            expected_entity_id=code,
        )
        if not clean_notes.empty and {"entity_type", "entity_id", "note_text"}.issubset(clean_notes.columns):
            rows = clean_notes[
                clean_notes["entity_type"].astype(str).str.lower().eq("team")
                & clean_notes["entity_id"].astype(str).eq(code)
            ].copy()
            if not rows.empty:
                category_order = {"team_context": 0, "history": 1, "coach": 2}
                rows["_priority"] = rows.get("note_category", pd.Series(dtype=str)).map(category_order).fillna(9)
                rows["_confidence"] = pd.to_numeric(
                    rows.get("confidence_score", pd.Series(pd.NA, index=rows.index)),
                    errors="coerce",
                )
                rows = rows.sort_values(
                    ["_priority", "_confidence"],
                    ascending=[True, False],
                    na_position="last",
                )
                lines = []
                seen_notes = set()
                for _, row in rows.iterrows():
                    note = str(value(row, "note_text", "")).strip()
                    if len(note) > 420:
                        note = note[:420].rstrip() + "..."
                    normalized_note = re.sub(r"\W+", " ", note.lower()).strip()[:140]
                    if normalized_note in seen_notes:
                        continue
                    seen_notes.add(normalized_note)
                    category = value(row, "note_category", "team_context")
                    printed_pages = value(row, "expected_printed_pages", "verify")
                    pdf_pages = value(
                        row,
                        "parsed_pdf_pages",
                        value(row, "source_pages", "verify"),
                    )
                    guide_date = _media_guide_date_label(
                        value(row, "guide_date", "")
                    )
                    review_state = _canonical_media_review_state(
                        row,
                        expected_entity_type="team",
                        expected_entity_id=code,
                    )
                    lines.append(
                        f"- [{review_state} | {category}] "
                        f"{value(row, 'entity_name', 'Identity unavailable')}: {note} "
                        f"({value(row, 'source_name', 'media guide')}; "
                        f"printed pages {printed_pages}; PDF pages {pdf_pages}; "
                        f"guide date {guide_date})"
                    )
                    if len(lines) >= limit:
                        return lines
                if lines:
                    return lines

        frame = _air_ready_media_rows(
            self.db.get("media_teams", pd.DataFrame()),
            expected_entity_type="team",
            expected_entity_id=code,
        )
        if frame.empty or "team_code" not in frame:
            return []
        rows = frame[frame["team_code"].astype(str).eq(code)]
        lines = []
        for _, row in rows.head(limit).iterrows():
            note = str(
                value(
                    row,
                    f"{media_guide_source_context()['guide_year']}_context",
                    value(row, "team_history", ""),
                )
            ).strip()
            if len(note) > 420:
                note = note[:420].rstrip() + "..."
            lines.append(f"- Page {whole(row, 'source_page')}: {note}")
        return lines

    def _team_frames(self, team, year):
        code = TEAM_TO_CODE.get(team, "")
        batting = self.db.get(f"batting_{year}", pd.DataFrame())
        pitching = self.db.get(f"pitching_{year}", pd.DataFrame())
        fielding = self.db.get(f"fielding_{year}", pd.DataFrame())
        if not batting.empty and "team_code" in batting:
            batting = batting[batting["team_code"].astype(str).eq(code)]
        if not pitching.empty and "team_code" in pitching:
            pitching = pitching[pitching["team_code"].astype(str).eq(code)]
        if not fielding.empty and "team_code" in fielding:
            fielding = fielding[fielding["team_code"].astype(str).eq(code)]
        return batting, pitching, fielding

    def _team_metrics(self, team, year):
        batting, pitching, fielding = self._team_frames(team, year)
        snapshot = official_team_snapshot(TEAM_TO_CODE.get(team, ""), year, self.db)
        ab = self._frame_sum(batting, "atBat")
        hits = self._frame_sum(batting, "hits")
        walks = self._frame_sum(batting, "baseonBalls")
        hbp = self._frame_sum(batting, "hitByPitch")
        sf = self._frame_sum(batting, "sacrificeFly")
        total_bases = self._frame_sum(batting, "totalBases")
        outs = self._sum_innings_outs(
            pitching.get("inningsPitched", pd.Series(dtype=float))
        )
        innings = outs / 3 if outs is not None else None
        earned_runs = self._frame_sum(pitching, "earnedRuns")
        pitching_walks = self._frame_sum(pitching, "baseOnBalls")
        hits_allowed = self._frame_sum(pitching, "hitsAllowed")
        chances = self._frame_sum(fielding, "totalChances")
        runs = self._frame_sum(batting, "runs")
        home_runs = self._frame_sum(batting, "homeRuns")
        rbi = self._frame_sum(batting, "runsBattedIn")
        stolen_bases = self._frame_sum(batting, "stolenBases")
        strikeouts = self._frame_sum(pitching, "strikeOuts")
        fielding_errors = self._frame_sum(fielding, "errors")
        putouts = self._frame_sum(fielding, "putOuts")
        assists = self._frame_sum(fielding, "assists")
        avg = hits / ab if hits is not None and ab is not None and ab > 0 else None
        obp_denominator = (
            ab + walks + hbp + sf
            if all(item is not None for item in (ab, hits, walks, hbp, sf))
            else None
        )
        obp = (
            (hits + walks + hbp) / obp_denominator
            if obp_denominator is not None and obp_denominator > 0
            else None
        )
        slg = (
            total_bases / ab
            if total_bases is not None and ab is not None and ab > 0
            else None
        )
        ops = obp + slg if obp is not None and slg is not None else None
        era = (
            earned_runs * 7 / innings
            if earned_runs is not None and innings
            else None
        )
        whip = (
            (hits_allowed + pitching_walks) / innings
            if hits_allowed is not None and pitching_walks is not None and innings
            else None
        )
        fielding_pct = (
            (putouts + assists) / chances
            if putouts is not None
            and assists is not None
            and chances is not None
            and chances > 0
            else None
        )

        def optional_int(item):
            return int(item) if item is not None else None

        offense_available = not batting.empty and all(
            item is not None for item in (runs, hits, home_runs, rbi, ops)
        )
        pitching_available = not pitching.empty and all(
            item is not None for item in (era, whip, strikeouts)
        )
        return {
            "wins": snapshot.wins,
            "losses": snapshot.losses,
            "record_text": snapshot.record_text,
            "record_source": snapshot.source_name,
            "record_source_timestamp": snapshot.source_timestamp,
            "calculated_pitcher_wins": optional_int(self._frame_sum(pitching, "wins")),
            "calculated_pitcher_losses": optional_int(self._frame_sum(pitching, "losses")),
            "runs": optional_int(runs),
            "hits": optional_int(hits),
            "home_runs": optional_int(home_runs),
            "rbi": optional_int(rbi),
            "stolen_bases": optional_int(stolen_bases),
            "avg": avg,
            "obp": obp,
            "slg": slg,
            "ops": ops,
            "era": era,
            "whip": whip,
            "strikeouts": optional_int(strikeouts),
            "errors": optional_int(fielding_errors),
            "fielding_pct": fielding_pct,
            "offense_available": offense_available,
            "pitching_available": pitching_available,
            "fielding_available": not fielding.empty
            and fielding_errors is not None
            and fielding_pct is not None,
        }

    def _standings_row(self, team, year=CURRENT_YEAR):
        standings = self.db.get("standings", pd.DataFrame())
        if standings.empty:
            return None
        code = TEAM_TO_CODE.get(team, "")
        rows = standings[
            standings.get("team_code", pd.Series(dtype=str)).astype(str).eq(code)
            & pd.to_numeric(standings.get("seasonId", pd.Series(dtype=float)), errors="coerce").eq(SEASONS.get(year, year))
            & standings.get("standingsTypeLk", pd.Series(dtype=str)).astype(str).eq("SEASON")
        ]
        return None if rows.empty else rows.iloc[0]

    def _team_context_line(self, team, year=CURRENT_YEAR):
        snapshot = official_team_snapshot(TEAM_TO_CODE.get(team, ""), year, self.db)
        if not snapshot.available:
            metrics = self._team_metrics(team, year)
            if not metrics["offense_available"] and not metrics["pitching_available"]:
                return (
                    f"{team}: Record unavailable | Calculated player-stat aggregates "
                    "unavailable — source data missing or incomplete; verify before air."
                )
            return (
                f"{team}: Record unavailable | Calculated player-stat aggregates: "
                f"{_format_whole_value(metrics['runs'])} runs, "
                f"{_format_whole_value(metrics['home_runs'])} HR, "
                f"{_format_decimal_value(metrics['era'])} ERA."
            )
        pct = _format_rate_value(snapshot.win_percentage)
        streak = snapshot.streak or "—"
        gb = "—" if snapshot.games_back is None else str(snapshot.games_back)
        diff = "—" if snapshot.run_differential is None else str(snapshot.run_differential)
        rank = "—" if snapshot.rank is None else str(snapshot.rank)
        source = " | ".join(
            item
            for item in (snapshot.source_name, snapshot.source_timestamp)
            if item
        )
        source_suffix = f" | Source {source}" if source else ""
        return f"{team}: {snapshot.record_text} ({pct}) | Streak {streak} | GB {gb} | Run diff {diff} | Standings rank {rank}{source_suffix}"

    @staticmethod
    def _format_schedule_date(raw_date):
        try:
            parsed = pd.to_datetime(raw_date)
            return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
        except Exception:
            return str(raw_date or "Date TBD")

    @staticmethod
    def _format_first_pitch(row):
        time_text = str(value(row, "game_time", "")).strip()
        zone = str(value(row, "game_time_zone", "")).strip()
        if not time_text or time_text == "—":
            return "First pitch TBD"
        try:
            parsed = datetime.strptime(time_text, "%I:%M:%S %p")
            time_text = parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            try:
                parsed = datetime.strptime(time_text, "%I:%M %p")
                time_text = parsed.strftime("%I:%M %p").lstrip("0")
            except ValueError:
                time_text = time_text.replace(":00 ", " ")
        return f"{time_text}{f' {zone}' if zone and zone != '—' else ''}"

    def _selected_game_line(self, away, home):
        selected = getattr(self, "selected_game", None)
        if not isinstance(selected, SelectedGame):
            return (
                "Selected game: CUSTOM / UNVERIFIED — official game ID, time, "
                "venue, and status unavailable."
            )
        if selected.away_team != away or selected.home_team != home:
            return "Selected game: unavailable — visible teams do not match the official game."
        first_pitch = selected.date_time.strftime("%B %d, %Y at %I:%M %p").replace(
            " 0", " "
        )
        return (
            f"Selected game: Game ID {selected.game_id} | {first_pitch} {selected.time_zone} | "
            f"{selected.venue} | {selected.status} | Source {selected.source_name} | "
            f"Updated {selected.source_updated_at}"
        )

    def _recent_matchup_line(self, away, home):
        schedule = self.db.get("schedule_results", pd.DataFrame())
        if schedule.empty:
            return "No schedule/rematch context imported yet."
        selected = getattr(self, "selected_game", None)
        if not isinstance(selected, SelectedGame):
            return "No prior matchup is available without an exact official selected game."
        if selected.away_team != away or selected.home_team != home:
            return (
                "No prior matchup is available because the visible teams do not "
                "match the selected game."
            )
        away_code, home_code = TEAM_TO_CODE.get(away, ""), TEAM_TO_CODE.get(home, "")
        mask = (
            (
                schedule.get("away_team_code", pd.Series(dtype=str))
                .astype(str)
                .eq(away_code)
                & schedule.get("home_team_code", pd.Series(dtype=str))
                .astype(str)
                .eq(home_code)
            )
            | (
                schedule.get("away_team_code", pd.Series(dtype=str))
                .astype(str)
                .eq(home_code)
                & schedule.get("home_team_code", pd.Series(dtype=str))
                .astype(str)
                .eq(away_code)
            )
        ) & (
            schedule.get("status", pd.Series(dtype=str))
            .astype(str)
            .str.lower()
            .eq("completed")
        )
        rows = schedule[mask].copy()
        rows["_parsed_game_date"] = pd.to_datetime(
            rows.get("game_date", pd.Series(index=rows.index, dtype=object)),
            errors="coerce",
            utc=True,
            format="mixed",
        )
        selected_time = pd.Timestamp(selected.date_time).tz_convert("UTC")
        identifiers = rows.get(
            "game_id", pd.Series("", index=rows.index, dtype=object)
        ).map(_manual_note_identifier)
        rows = rows[
            rows["_parsed_game_date"].notna()
            & rows["_parsed_game_date"].lt(selected_time)
            & identifiers.ne(selected.game_id)
        ].sort_values("_parsed_game_date", ascending=False)
        if rows.empty:
            return "No prior completed head-to-head meeting is available before this game."
        row = rows.iloc[0]
        return (
            f"Recent matchup: {value(row, 'away_team_code')} {whole(row, 'away_score')} at "
            f"{value(row, 'home_team_code')} {whole(row, 'home_score')} on {self._format_schedule_date(row.get('game_date'))}."
        )

    def _select_official_game_notes(self, away, home, limit=5):
        selected = getattr(self, "selected_game", None)
        if (
            not isinstance(selected, SelectedGame)
            or selected.away_team != away
            or selected.home_team != home
        ):
            return []
        frame = self.db.get("official_game_notes", pd.DataFrame())
        if frame is None or frame.empty or "needs_review" not in frame.columns:
            return []

        def game_id_text(item):
            if item is None or pd.isna(item):
                return ""
            try:
                number = float(item)
                if math.isfinite(number) and number.is_integer():
                    return str(int(number))
            except (TypeError, ValueError, OverflowError):
                pass
            return str(item).strip()

        source_ids = frame.get(
            "source_game_id", frame.get("game_id", pd.Series("", index=frame.index))
        ).map(game_id_text)
        rows = frame[source_ids.eq(selected.game_id)].copy()
        if rows.empty:
            return []
        rows = _deduplicate_official_game_notes(rows)

        category_priority = {
            "availability": 0,
            "probable_starter": 1,
            "milestone_reached": 2,
            "milestone_watch": 3,
            "matchup_history": 4,
            "recent_trend": 5,
            "season_context": 6,
            "career_summary": 7,
            "background": 8,
        }
        valid_team_codes = {selected.away_team_code, selected.home_team_code}
        candidates = []
        for _, row in rows.iterrows():
            note_text = _optional_text(row, "note_text") or ""
            lower = note_text.lower()
            if not note_text or any(
                marker in lower
                for marker in (
                    "date opponent score/time",
                    "statistics player c 1b 2b",
                    "statistics team runs, game",
                    "player c 1b 2b 3b ss lf cf rf",
                )
            ):
                continue
            subject_team = _optional_text(row, "subject_team_code") or ""
            source_game_id = game_id_text(
                value(row, "source_game_id", value(row, "game_id", None))
            )
            source_date = _optional_text(row, "source_date") or ""
            source_page_number = _optional_int(row, "source_page")
            source_page = str(source_page_number) if source_page_number is not None else ""
            source_url = _optional_text(row, "source_url") or ""
            source_pdf = _optional_text(row, "source_pdf") or ""
            if not source_pdf and source_url:
                source_pdf = source_url.rsplit("/", 1)[-1].split("?", 1)[0]
            source_date_valid = not pd.isna(
                pd.to_datetime(source_date, errors="coerce", utc=True)
            )
            raw_state = (_optional_text(row, "verification_state") or "VERIFY").upper()
            if raw_state not in {"VERIFIED", "VERIFY", "STALE"}:
                raw_state = "VERIFY"
            review_value = row.get("needs_review")
            explicitly_approved = (
                review_value is not None
                and not pd.isna(review_value)
                and (
                    (pd.api.types.is_bool(review_value) and not bool(review_value))
                    or str(review_value).strip().lower() in {"false", "0", "no"}
                )
            )
            complete_source = bool(
                subject_team in valid_team_codes
                and source_date_valid
                and source_game_id == selected.game_id
                and source_pdf
                and source_page
            )
            state = raw_state
            if state == "VERIFIED" and not (explicitly_approved and complete_source):
                state = "VERIFY"
            try:
                confidence = float(value(row, "confidence_score", 0.0))
                if not math.isfinite(confidence):
                    confidence = 0.0
            except (TypeError, ValueError, OverflowError):
                confidence = 0.0
            candidates.append(
                OfficialGameNote(
                    game_id=source_game_id,
                    category=_optional_text(row, "note_category") or "background",
                    text=note_text,
                    subject_player_id=_optional_text(row, "subject_player_id") or "",
                    subject_player_name=_optional_text(row, "subject_player_name") or "",
                    subject_team_code=subject_team,
                    opposing_team_code=_optional_text(row, "opposing_team_code") or "",
                    verification_state=state,
                    source_date=source_date,
                    source_pdf=source_pdf,
                    source_page=source_page,
                    source_url=source_url,
                    source_history=_optional_text(row, "source_history") or "",
                    confidence_score=confidence,
                )
            )

        def sort_key(note):
            state_priority = {"VERIFIED": 0, "STALE": 1, "VERIFY": 2}
            return (
                state_priority[note.verification_state],
                category_priority.get(note.category, 9),
                -note.confidence_score,
                note.subject_team_code,
                note.text.casefold(),
            )

        ordered = sorted(candidates, key=sort_key)
        verified_teams = {
            note.subject_team_code for note in ordered if note.air_ready
        } & valid_team_codes
        chosen = []
        if len(verified_teams) == 2 and limit >= 2:
            for team_code in (selected.away_team_code, selected.home_team_code):
                team_note = next(
                    note
                    for note in ordered
                    if note.air_ready and note.subject_team_code == team_code
                )
                if team_note not in chosen:
                    chosen.append(team_note)
        used_categories = {note.category for note in chosen}
        for note in ordered:
            if note in chosen:
                continue
            if note.category in used_categories and len(chosen) >= 3:
                continue
            chosen.append(note)
            used_categories.add(note.category)
            if len(chosen) >= limit:
                break
        return sorted(chosen[:limit], key=sort_key)

    def _format_official_game_note(self, note):
        subject = note.subject_player_name or CODE_TO_TEAM.get(
            note.subject_team_code, note.subject_team_code or "Subject unavailable"
        )
        text = note.text
        if len(text) > 360:
            text = text[:360].rstrip() + "..."
        return (
            f"- [{note.verification_state}] [{note.category}] "
            f"{subject} ({note.subject_team_code or 'team unavailable'}): {text} | "
            f"Source: {note.source_date or 'date unavailable'} | "
            f"{note.source_pdf or 'PDF unavailable'} | Game {note.game_id or 'unavailable'} | "
            f"page {note.source_page or 'unavailable'}"
        )

    def _official_game_note_review_lines(self, away, home, limit=5):
        return [
            self._format_official_game_note(note)
            for note in self._select_official_game_notes(away, home, limit=limit)
            if not note.air_ready
        ]

    def _official_game_note_lines(self, away, home, limit=5):
        selected_notes = self._select_official_game_notes(away, home, limit=limit)
        notes = [note for note in selected_notes if note.air_ready]
        if not selected_notes:
            return []
        output = [self._format_official_game_note(note) for note in notes]
        verified_teams = {
            note.subject_team_code for note in notes if note.air_ready
        }
        selected = self.selected_game
        for team_code in (selected.away_team_code, selected.home_team_code):
            if team_code not in verified_teams:
                output.append(
                    f"- [VERIFY] No verified official-note candidate is available for "
                    f"{CODE_TO_TEAM.get(team_code, team_code)} in Game {selected.game_id}."
                )
        return output

    def _why_game_matters(self, away, home, year):
        away_snapshot = official_team_snapshot(
            TEAM_TO_CODE.get(away, ""), year, self.db
        )
        home_snapshot = official_team_snapshot(
            TEAM_TO_CODE.get(home, ""), year, self.db
        )
        if away_snapshot.available and home_snapshot.available:
            selected = getattr(self, "selected_game", None)
            if (
                isinstance(selected, SelectedGame)
                and selected.away_team == away
                and selected.home_team == home
                and selected.status.strip().casefold() == "completed"
            ):
                return (
                    "Current standings (not an as-of-game snapshot): "
                    f"{away} is currently {away_snapshot.record_text} with a "
                    f"{away_snapshot.streak or '—'} streak, while {home} is currently "
                    f"{home_snapshot.record_text} with a "
                    f"{home_snapshot.streak or '—'} streak. "
                    f"{self._recent_matchup_line(away, home)} Do not describe these "
                    "current records as what either team entered this historical game with."
                )
            return (
                f"{away} enters {away_snapshot.record_text} "
                f"with a {away_snapshot.streak or '—'} streak, while {home} enters "
                f"{home_snapshot.record_text} with a "
                f"{home_snapshot.streak or '—'} streak. {self._recent_matchup_line(away, home)} "
                "Use this for stakes/rematch context, then verify standings against the latest official notes before air."
            )
        away_metrics = self._team_metrics(away, year)
        home_metrics = self._team_metrics(home, year)
        if not (
            away_metrics["offense_available"]
            and home_metrics["offense_available"]
            and away_metrics["pitching_available"]
            and home_metrics["pitching_available"]
        ):
            return (
                "Official record context and complete calculated player-stat context are "
                f"unavailable. {self._recent_matchup_line(away, home)} Verify the latest "
                "official standings and game notes before air."
            )
        away_power = away_metrics["home_runs"] >= home_metrics["home_runs"]
        offense = away if away_power else home
        pitching = home if away_power else away
        pitching_metrics = home_metrics if away_power else away_metrics
        return (
            f"Official record context is unavailable. {offense} brings the stronger calculated power profile "
            f"in the local player-stat database, while the {pitching} staff has a calculated "
            f"{_format_decimal_value(pitching_metrics['era'])} team ERA. Build this as a matchup between run creation "
            "and run prevention, then verify any official standings or playoff context before air."
        )

    def _best_split_rows(self, player_id, is_pitcher, year=CURRENT_YEAR, limit=4):
        key = "pitching_splits" if is_pitcher else "batting_splits"
        frame = _air_ready_enrichment_rows(self.db.get(key, pd.DataFrame()))
        if frame.empty or "player_id" not in frame:
            return []
        rows = frame[
            pd.to_numeric(frame["player_id"], errors="coerce").eq(int(player_id))
            & pd.to_numeric(frame.get("season", pd.Series(dtype=float)), errors="coerce").eq(year)
        ].copy()
        if rows.empty:
            return []
        if is_pitcher:
            rows["_canonical_whip"] = rows.apply(canonical_pitching_whip, axis=1)
            rows["_innings_outs"] = rows.get(
                "inningsPitched", pd.Series(pd.NA, index=rows.index)
            ).map(innings_to_outs)
            rows["_score"] = (
                pd.to_numeric(rows.get("strikeOuts", 0), errors="coerce").fillna(0)
                - pd.to_numeric(rows.get("earnedRunAverage", 99), errors="coerce").fillna(99)
                - pd.to_numeric(rows["_canonical_whip"], errors="coerce").fillna(3)
            )
            rows = rows[pd.to_numeric(rows["_innings_outs"], errors="coerce").fillna(0) >= 3]
        else:
            rows["_score"] = pd.to_numeric(rows.get("opsPercentage", 0), errors="coerce").fillna(0) * 1000 + pd.to_numeric(rows.get("runsBattedIn", 0), errors="coerce").fillna(0)
            rows = rows[pd.to_numeric(rows.get("plateAppearances", 0), errors="coerce").fillna(0) >= 6]
        return [row for _, row in rows.sort_values("_score", ascending=False).head(limit).iterrows()]

    def _best_split_lines(self, player_id, is_pitcher, year=CURRENT_YEAR):
        rows = self._best_split_rows(player_id, is_pitcher, year)
        if not rows:
            return [
                "Optional split data is unavailable until its verification gates pass."
            ]
        lines = []
        for row in rows:
            if is_pitcher:
                whip = canonical_pitching_whip(row)
                lines.append(
                    f"- {value(row, 'split_label')}: {_format_innings_value(value(row, 'inningsPitched', None))} IP | "
                    f"{decimal(row, 'earnedRunAverage', 2)} ERA | {whole(row, 'strikeOuts')} SO | {_format_decimal_value(whip)} WHIP"
                )
            else:
                plate_appearances = whole(row, "plateAppearances")
                lines.append(
                    f"- {value(row, 'split_label')}: {plate_appearances} PA | "
                    f"{rate(row, 'battingAverage')} AVG | {rate(row, 'opsPercentage')} OPS | "
                    f"{whole(row, 'runsBattedIn')} RBI | sample size: {plate_appearances} PA"
                )
        return lines

    def _manual_note_lines(
        self,
        player_id=None,
        team_code=None,
        game_id=None,
        include_global=False,
    ):
        notes = self.db.get("manual_notes", pd.DataFrame())
        if notes.empty:
            return []
        rows = select_manual_notes(
            notes,
            player_id=player_id,
            team_code=team_code,
            game_id=game_id,
            include_global=include_global,
        )
        lines = []
        for _, row in rows.iterrows():
            scope = _manual_note_text(row.get("scope")).upper()
            safe = "AIR SAFE" if _manual_note_text(row.get("air_safe")).lower() in {"true", "1", "yes"} else "VERIFY BEFORE AIR"
            source = _manual_note_text(row.get("source")) or "source unavailable"
            updated = _manual_note_text(row.get("updated_at")) or _manual_note_text(row.get("created_at")) or "timestamp unavailable"
            lines.append(
                f"- [{scope} | {safe}] {_manual_note_text(row.get('note_text'))} "
                f"(source: {source}; updated: {updated})"
            )
        return lines

    def _storyline_lines(self, roster, is_pitcher):
        player_id = roster["player_id"]
        lines = [
            f"PLAYER STORY CARD - {roster['player_name'].upper()}",
            self.data_freshness_text,
            "",
            "STATUS / VERIFY",
            self.availability_warning(roster) or "Listed active in the current roster file.",
            "",
            "STAT ANGLE",
            self.current_broadcast_note,
            "",
            "SPLIT ANGLE",
            *(self._best_split_lines(player_id, is_pitcher)[:2]),
            "",
            "BIO / CONTEXT ANGLE",
            f"College: {value(roster, 'college')} | Hometown: {value(roster, 'hometown')} | B/T: {value(roster, 'bats_throws')}",
        ]
        draft = self.compact_draft_info(roster)
        if draft:
            lines.append(f"Draft/context note: {draft}")
        media = self._media_guide_player_lines(player_id)
        if media:
            lines.extend(["", "MEDIA GUIDE NOTES", *media])
        selected_game = getattr(self, "selected_game", None)
        manual = self._manual_note_lines(
            player_id=player_id,
            team_code=value(roster, "team_code", ""),
            game_id=(
                selected_game.game_id
                if isinstance(selected_game, SelectedGame)
                else None
            ),
        )
        if manual:
            lines.extend(["", "MANUAL PRODUCER NOTES", *manual])
        lines.extend(
            [
                "",
                "GFX IDEA",
                f"{roster['player_name'].upper()} - {('Pitching Spotlight' if is_pitcher else 'Player to Watch')}",
                "",
                "BIG-SPOT NOTE",
                "Use this card if she comes up in a high-leverage spot or is central to the inning. Verify all generated notes before air.",
            ]
        )
        return lines

    def _players_to_watch(self, team, year):
        roster = self._active_team_roster(team)
        hitters, pitchers = [], []
        for _, player in roster.iterrows():
            batting = self._player_row(f"batting_{year}", player["player_id"])
            pitching = self._player_row(f"pitching_{year}", player["player_id"])
            plate_appearances = self._stat_optional_number(batting, "plateAppearances")
            ops = self._stat_optional_number(batting, "opsPercentage")
            rbi = self._stat_optional_number(batting, "runsBattedIn")
            home_runs = self._stat_optional_number(batting, "homeRuns")
            if (
                batting is not None
                and plate_appearances is not None
                and plate_appearances > 0
                and ops is not None
                and rbi is not None
                and home_runs is not None
            ):
                score = ops * 1000 + rbi + home_runs * 4
                hitters.append((score, player, batting))
            position = str(value(player, "position", "")).strip().upper()
            appearances = self._stat_optional_number(pitching, "appearances")
            strikeouts = self._stat_optional_number(pitching, "strikeOuts")
            starts = self._stat_optional_number(pitching, "gamesStarted")
            era = self._stat_optional_number(pitching, "earnedRunAverage")
            if (
                position in {"P", "RHP", "LHP"}
                and pitching is not None
                and appearances is not None
                and appearances > 0
                and strikeouts is not None
                and starts is not None
                and era is not None
            ):
                score = strikeouts + starts * 5 - era
                pitchers.append((score, player, pitching))
        hitters.sort(key=lambda item: item[0], reverse=True)
        pitchers.sort(key=lambda item: item[0], reverse=True)

        watched = []
        for _score, player, stats in hitters[:2]:
            watched.append((player, f"{rate(stats, 'battingAverage')} AVG | {whole(stats, 'homeRuns')} HR | {whole(stats, 'runsBattedIn')} RBI", self._packet_broadcast_note(player, year)))
        if pitchers:
            _score, player, stats = pitchers[0]
            watched.append((player, f"{whole(stats, 'wins')}-{whole(stats, 'losses')} | {decimal(stats, 'earnedRunAverage', 2)} ERA | {whole(stats, 'strikeOuts')} SO", self._packet_broadcast_note(player, year)))
        return watched

    def _milestone_watch(self, team, year, limit=6):
        roster = self._active_team_roster(team)
        notes = []
        for _, player in roster.iterrows():
            note = self._packet_broadcast_note(player, year)
            if note.startswith("Needs"):
                notes.append(f"- {player['player_name']}: {note}")
        return notes[:limit]

    def _availability_impact(self, team):
        roster = self.db.get("roster", pd.DataFrame())
        if roster.empty or "team" not in roster:
            return [self.data_freshness_text, "- Roster availability data unavailable."]
        team_roster = roster[roster["team"].astype(str).eq(str(team))]
        if team_roster.empty:
            unavailable = team_roster
        else:
            active_mask = team_roster.apply(self.is_active_roster, axis=1).astype(bool)
            unavailable = team_roster.loc[~active_mask]
        lines = [self.data_freshness_text]
        for _, player in unavailable.iterrows():
            name = _optional_text(player, "player_name") or "Player name unavailable"
            position = _optional_text(player, "position") or "Position unavailable"
            status = self.roster_status(player)
            lines.append(
                f"- {name} — {position} — Status: {status} | "
                "NOT AUTO-RECOMMENDED | VERIFY AVAILABILITY BEFORE AIR"
            )
        if len(lines) == 1:
            lines.append("- No nonactive or unknown-status players listed for this team.")
        return lines

    def _unassigned_availability_impact(self):
        """List nonactive roster entries that cannot be safely linked to a team."""

        roster = self.db.get("roster", pd.DataFrame())
        if roster.empty:
            return [self.data_freshness_text, "- Roster availability data unavailable."]

        lines = [self.data_freshness_text]
        for _, player in roster.iterrows():
            if self.is_active_roster(player):
                continue
            if _optional_text(player, "team") or _optional_text(player, "team_code"):
                continue
            name = _optional_text(player, "player_name") or "Player name unavailable"
            position = _optional_text(player, "position") or "Position unavailable"
            status = self.roster_status(player)
            lines.append(
                f"- {name} — {position} — TEAM UNKNOWN — Status: {status} | "
                "NOT LINKED TO A SELECTED TEAM | VERIFY AVAILABILITY BEFORE AIR"
            )
        if len(lines) == 1:
            lines.append("- No nonactive team-unassigned roster entries listed.")
        return lines

    def _graphic_suggestions(self, away, home, year):
        suggestions = [
            ("Opening Matchup", f"{away} at {home} with data timestamp and verification note."),
            ("Team Offensive Comparison", "Runs, hits, home runs, RBI, AVG/OBP/SLG/OPS for both clubs."),
            ("Starting Pitcher Comparison", "Use projected pitchers until official starters are confirmed."),
            ("Players to Watch", "Two hitters plus one pitcher per team based on current AUSL stats."),
            ("Milestone Watch", "AUSL-only career milestones that are close enough to track during the game."),
            ("Lineup Card", "Build from official lineup once released; projected lineup is prep-only."),
            ("Verification Checklist", "Lineups, starting pitchers, availability, pronunciations, and milestones."),
        ]
        return [f"{index}. {title} - {reason}" for index, (title, reason) in enumerate(suggestions, 1)]

    def _producer_prep_model(self, away, home, year):
        selected_notes = self._select_official_game_notes(away, home, limit=8)
        air_ready_notes = [note for note in selected_notes if note.air_ready]
        review_notes = [note for note in selected_notes if not note.air_ready]

        storylines = [
            ProducerStoryline(
                title="Game stakes",
                summary="Official standings and matchup context frame this game; see GAME CONTEXT and MATCHUP HISTORY.",
                source_label=self.data_freshness_text,
            )
        ]
        consumed_notes = []
        category_titles = {
            "availability": "Availability",
            "probable_starter": "Announced starter",
            "milestone_reached": "Milestone reached",
            "milestone_watch": "Milestone watch",
            "matchup_history": "Matchup history",
            "recent_trend": "Recent trend",
            "season_context": "Season context",
            "career_summary": "Career context",
            "background": "Background",
        }
        for note in air_ready_notes[:3]:
            subject = note.subject_player_name or CODE_TO_TEAM.get(
                note.subject_team_code, note.subject_team_code or "Official note"
            )
            storylines.append(
                ProducerStoryline(
                    title=f"{category_titles.get(note.category, 'Official note')} — {subject}",
                    summary=note.text,
                    source_label=(
                        f"[{note.verification_state}] {note.source_date} | "
                        f"{note.source_pdf} | Game {note.game_id} | page {note.source_page}"
                    ),
                )
            )
            consumed_notes.append(note)

        offense_lines = []
        pitching_lines = []
        for team in (away, home):
            metrics = self._team_metrics(team, year)
            offense_lines.append(
                f"- {team} calculated player-stat offense: {_format_whole_value(metrics['runs'])} R | {_format_whole_value(metrics['home_runs'])} HR | {_format_whole_value(metrics['rbi'])} RBI | {_format_rate_value(metrics['ops'])} OPS."
                if metrics["offense_available"]
                else f"- {team} calculated player-stat offense: unavailable — source data missing or incomplete; verify before air."
            )
            pitching_lines.append(
                f"- {team} calculated player-stat pitching: {_format_decimal_value(metrics['era'])} ERA | {_format_decimal_value(metrics['whip'])} WHIP | {_format_whole_value(metrics['strikeouts'])} SO."
                if metrics["pitching_available"]
                else f"- {team} calculated player-stat pitching: unavailable — source data missing or incomplete; verify before air."
            )

        player_lines = []
        for team in (away, home):
            player_lines.append(f"{team}:")
            players = self._players_to_watch(team, year)
            for player, line, note in players:
                warning = self.availability_warning(player)
                player_lines.append(
                    f"- {player['player_name']} ({value(player, 'position')}): {line}. {note}"
                )
                if warning:
                    player_lines.append(f"  {warning}")
            if not players:
                player_lines.append("- No player-to-watch candidate found in the current database.")

        milestone_lines = self._milestone_watch(away, year) + self._milestone_watch(home, year)
        availability_lines = []
        for team in (away, home):
            impact = [
                line
                for line in self._availability_impact(team)
                if line != self.data_freshness_text
            ]
            availability_lines.extend([f"{team}:", *impact])
        unassigned = [
            line
            for line in self._unassigned_availability_impact()
            if line != self.data_freshness_text
        ]
        availability_lines.extend(["Unassigned / reserve pool:", *unassigned])

        remaining_official = [
            self._format_official_game_note(note)
            for note in air_ready_notes
            if note not in consumed_notes
        ]
        verification_lines = [
            *[self._format_official_game_note(note) for note in review_notes],
            "- Confirm official lineups and DP/FLEX information.",
            "- Confirm starting pitchers.",
            "- Confirm player availability, injuries, reserve status, and excused absences.",
            "- Confirm pronunciations and any producer/talent notes.",
            "- Confirm AUSL-only milestones against official notes before air.",
        ]
        return ProducerPrep(
            title=f"{away.upper()} at {home.upper()} - AUSL PRODUCER PREP",
            game_context=(
                self.data_freshness_text,
                self._selected_game_line(away, home),
                f"Lineup status: {self._lineup_broadcast_status()}",
                self._why_game_matters(away, home, year),
                self._team_context_line(away, year),
                self._team_context_line(home, year),
            ),
            top_storylines=tuple(storylines),
            availability=tuple(availability_lines),
            offense=tuple(offense_lines),
            pitching=tuple(pitching_lines),
            matchup_history=(self._recent_matchup_line(away, home),),
            milestones=tuple(
                milestone_lines
                or ["- No nearby standard AUSL-only milestone identified."]
            ),
            official_notes=tuple(
                remaining_official
                or ["- No additional verified official-note item is available for this game."]
            ),
            players_to_watch=tuple(player_lines),
            graphics_queue=tuple(self._graphic_suggestions(away, home, year)),
            verification_queue=tuple(verification_lines),
        )

    def _producer_packet_prep_lines(self, prep):
        return prep.render_sections(
            (
                "GAME CONTEXT",
                "TOP STORYLINES",
                "OFFICIAL GAME NOTES",
                "VERIFICATION QUEUE",
            )
        )

    def _producer_prep_lines(self, away, home, year):
        return self._producer_prep_model(away, home, year).render_lines()

    def render_producer_prep(self):
        if not self.db or not hasattr(self, "producer_prep_text"):
            return
        away, home = self.away_var.get(), self.home_var.get()
        if not away or not home or away == home:
            message = "Select two different game teams to build producer prep."
            self.producer_prep_copy_text = ""
            self._set_text(self.producer_prep_text, message)
            self.producer_prep_status.set(message)
            return
        lines = self._producer_prep_lines(away, home, CURRENT_YEAR)
        self.producer_prep_copy_text = "\n".join(self._graphic_suggestions(away, home, CURRENT_YEAR))
        self._set_text(self.producer_prep_text, "\n".join(lines))
        self.producer_prep_status.set("Producer prep refreshed")

    def copy_producer_prep(self):
        if not self.producer_prep_copy_text:
            self.render_producer_prep()
        if not self.producer_prep_copy_text:
            self.producer_prep_status.set("No graphic queue to copy yet")
            return
        text = f"READY-MADE GRAPHICS QUEUE\n{self.data_freshness_text}\n\n{self.producer_prep_copy_text}"
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()
        self.producer_prep_status.set("Graphic queue copied to clipboard")

    def _producer_packet_path(self, generated_at):
        locked = self._current_lineup_lock()
        revision = locked.get("revision") if locked else None
        filename = producer_packet_filename(
            getattr(self, "selected_game", None), generated_at, revision=revision
        )
        return export_dir() / "game_packets" / filename

    def generate_pregame_report(self):
        if not self.db:
            messagebox.showwarning("AUSL Broadcast Stats", "The database is still loading.")
            return
        away, home = self.away_var.get(), self.home_var.get()
        if not away or not home or away == home:
            messagebox.showwarning("AUSL Broadcast Stats", "Select two different game teams first.")
            return
        selected_game = getattr(self, "selected_game", None)
        if not isinstance(selected_game, SelectedGame):
            messagebox.showwarning(
                "AUSL Broadcast Stats",
                "Producer packet not created: select an exact official game ID first.",
            )
            return
        generated_at = datetime.now(timezone.utc)
        year = CURRENT_YEAR
        lineup_lock = self._current_lineup_lock()
        locked_lineups = self.current_locked_lineups()
        prep = self._producer_prep_model(away, home, year)
        lines = [
            f"{away.upper()} at {home.upper()} - AUSL PRODUCER PRE-GAME PACKET",
            f"Generated: {generated_at.isoformat()}",
            f"Packet identity: Official Game ID {selected_game.game_id}",
            "",
            "IMPORTANT",
            "Saved lineup provenance is shown above; verify against official lineup cards before air." if locked_lineups else "Projected lineups and starting pitchers are stat-based estimates, not official submissions.",
            VERIFY_NOTE,
            "",
            *self._producer_packet_prep_lines(prep),
            "",
            "READY-MADE GRAPHICS QUEUE",
            *prep.graphics_queue,
            "",
        ]

        for label, team, side in (("AWAY", away, "away"), ("HOME", home, "home")):
            locked_team = locked_lineups.get(side) if locked_lineups else None
            lines.extend(
                [
                    f"{label} — {team.upper()}",
                    "",
                    (
                        packet_lineup_heading(lineup_lock)
                        if locked_team
                        else "PROJECTED STARTING LINEUP — NOT OFFICIAL"
                    ),
                ]
            )
            if locked_team and locked_team.get("lineup"):
                lines.extend(format_stored_packet_lineup(locked_team))
            else:
                lineup = self._projected_lineup(team, year)
                if lineup:
                    for order, item in enumerate(lineup, 1):
                        player, stats = item["player"], item["stats"]
                        jersey = str(value(player, "jersey_number", "?")).replace(".0", "")
                        status = self.roster_status(player)
                        warning = " | VERIFY AVAILABILITY" if self.availability_warning(player) else ""
                        lines.append(
                            f"{order}. #{jersey} {player['player_name']} — {value(player, 'position')} | "
                            f"{rate(stats, 'battingAverage')} AVG | {whole(stats, 'homeRuns')} HR | {whole(stats, 'runsBattedIn')} RBI | {status}{warning}"
                        )
                else:
                    lines.append("No stat-based lineup projection is available.")

            lines.extend(
                [
                    "",
                    (
                        packet_starting_pitcher_heading(lineup_lock)
                        if locked_team
                        else "PROJECTED STARTING PITCHER — NOT OFFICIAL"
                    ),
                ]
            )
            if locked_team and locked_team.get("starting_pitcher"):
                starter_position = locked_team.get(
                    "starting_pitcher_position", "position unavailable"
                )
                lines.append(
                    f"{locked_team['starting_pitcher']} — {starter_position} | "
                    f"{packet_starting_pitcher_heading(lineup_lock)}"
                )
            else:
                pitchers = self._projected_pitchers(team, year)
                if pitchers:
                    _starts, _outs, _apps, pitcher, pitching = pitchers[0]
                    jersey = str(value(pitcher, "jersey_number", "?")).replace(".0", "")
                    status = self.roster_status(pitcher)
                    warning = " | VERIFY AVAILABILITY" if self.availability_warning(pitcher) else ""
                    lines.append(
                        f"#{jersey} {pitcher['player_name']} — {whole(pitching, 'wins')}-{whole(pitching, 'losses')} | "
                        f"{_format_innings_value(value(pitching, 'inningsPitched', None))} IP | {decimal(pitching, 'earnedRunAverage', 2)} ERA | {whole(pitching, 'strikeOuts')} SO | {status}{warning}"
                    )
                    if len(pitchers) > 1:
                        alternatives = ", ".join(item[3]["player_name"] for item in pitchers[1:3])
                        lines.append(f"Other likely options by season usage: {alternatives}")
                else:
                    lines.append("No stat-based pitcher projection is available.")

            media_team_lines = self._media_guide_team_lines(team)
            lines.extend(["", "TEAM SNAPSHOT", *self._packet_team_snapshot(team, year)])
            if media_team_lines:
                lines.extend(["", "MEDIA GUIDE TEAM CONTEXT", *media_team_lines])
            lines.extend(["", "MILESTONE / BROADCAST NOTES"])
            roster = self.db["roster"][self.db["roster"]["team"].eq(team)]
            notes = self._milestone_watch(team, year, limit=10)
            lines.extend(notes[:10] or ["- No nearby standard milestone identified."])

            lines.extend(
                [
                    "",
                    "AVAILABILITY IMPACT (SEPARATE FROM AUTO-RECOMMENDATIONS)",
                    *self._availability_impact(team),
                ]
            )

            lines.extend(["", "QUICK ROSTER / JERSEY LOOKUP"])
            ordered = roster.assign(_number=pd.to_numeric(roster["jersey_number"], errors="coerce")).sort_values(["_number", "player_name"], na_position="last")
            for _, player in ordered.iterrows():
                jersey = str(value(player, "jersey_number", "?")).replace(".0", "")
                status = self.roster_status(player)
                draft = self.compact_draft_info(player)
                extra = f" | Draft: {draft}" if draft else ""
                warning = " | VERIFY AVAILABILITY" if self.availability_warning(player) else ""
                lines.append(f"#{jersey} — {player['player_name']} — {value(player, 'position')} — {status}{warning}{extra}")
            lines.extend(["", "=" * 72, ""])

        lines.extend(
            [
                "UNASSIGNED / RESERVE-POOL AVAILABILITY",
                *self._unassigned_availability_impact(),
                "",
            ]
        )

        lines.extend(
            [
                "SOFTBALL / AUSL CONTEXT",
                "- AUSL games are scheduled for seven innings unless extras are needed.",
                "- Confirm DP/FLEX and official batting order details before building lineup graphics.",
                "- Players may have college, AU, Team USA, or international history that is not included in AUSL Career totals.",
                "- Treat media guide, news, awards, and college notes as context layers, not live stat authority.",
                "",
                "SOURCE LINKS",
                "- Official AUSL stats/splits: https://theausl.com/stats/",
                "- Official AUSL standings: https://theausl.com/standings/",
                "- Official AUSL schedule/results: https://theausl.com/schedule/",
                f"- {media_guide_source_context()['source_name']}: {media_guide_source_context()['source_url']}",
                "",
                "BROADCAST CHECKLIST",
                "- Replace projected lineups when official batting orders are released.",
                "- Confirm the announced starting pitchers before air.",
                "- Confirm DP/FLEX, bench, and unavailable players.",
                "- Confirm pronunciations and any talent/producer notes.",
                "- Verify imported milestones and team totals against official game notes.",
                "- Use the Live Game tab once the official AUSL box-score feed begins.",
            ]
        )
        path = self._producer_packet_path(generated_at)
        try:
            write_producer_packet_exclusive(path, "\n".join(lines))
        except FileExistsError:
            messagebox.showerror(
                "AUSL Broadcast Stats",
                f"Producer packet was not overwritten because this filename already exists:\n\n{path}",
            )
            return
        self._record_packet_generated(
            path,
            generated_at=generated_at,
            game_id=selected_game.game_id,
            lineup_revision=(
                lineup_lock.get("revision") if lineup_lock else None
            ),
            lineup_source=(
                lineup_lock.get("source") if lineup_lock else "projected"
            ),
        )
        self.status_var.set(f"Producer packet saved: {path}")

    def _media_guide_citation_line(self):
        return f"Media guide source: {media_guide_source_context()['source_url']}"

    def render_player(self, roster):
        self.player_title.set(self.player_title_text(roster))
        warning = self.availability_warning(roster)
        self.player_meta.set(self.player_meta_text(roster))
        cb, cp, cf = self.stat_row("career_batting"), self.stat_row("career_pitching"), self.stat_row("career_fielding")
        yb, yp, yf = self.stat_row(f"batting_{CURRENT_YEAR}"), self.stat_row(f"pitching_{CURRENT_YEAR}"), self.stat_row(f"fielding_{CURRENT_YEAR}")
        pb, pp, pf = self.stat_row(f"batting_{CURRENT_YEAR-1}"), self.stat_row(f"pitching_{CURRENT_YEAR-1}"), self.stat_row(f"fielding_{CURRENT_YEAR-1}")
        is_pitcher = str(value(roster, "position", "")).strip().upper() in PITCHER_POSITIONS
        self.current_broadcast_note = self.build_broadcast_note(is_pitcher, cb, cp, yb, yp)
        quick = [self.data_freshness_text, "IMPORTED DATA - VERIFY BEFORE AIR"]
        if warning:
            quick.extend(["", "AVAILABILITY WARNING", warning])
        quick.extend(["", "BROADCAST NOTE", self.current_broadcast_note, "", CAREER_LABEL.upper(), self.pitching_line(cp) if is_pitcher else self.batting_line(cb), "", f"{CURRENT_YEAR} SEASON", self.pitching_line(yp) if is_pitcher else self.batting_line(yb)])
        if is_pitcher and cb is not None:
            quick.extend(["", "AT THE PLATE", self.batting_line(cb)])
        self._set_text(self.stat_texts["card"], "\n".join(quick))
        self._set_text(self.stat_texts["storylines"], "\n".join(self._storyline_lines(roster, is_pitcher)))
        self._set_text(self.stat_texts["splits"], "\n".join([f"OFFICIAL AUSL SPLITS - {CURRENT_YEAR}", self.data_freshness_text, "", *self._best_split_lines(roster["player_id"], is_pitcher)]))
        source_lines = [
            "SOURCE LINKS / PRODUCER VERIFICATION",
            self.data_freshness_text,
            "",
            "Primary stat source: Official AUSL JSON/API and local Excel exports.",
            "Official split source: https://theausl.com/stats/",
            "Official standings source: https://theausl.com/standings/",
            "Official schedule source: https://theausl.com/schedule/",
            self._media_guide_citation_line(),
            "",
            "Media guide notes:",
            *(
                self._media_guide_player_lines(
                    roster["player_id"], include_review=True
                )
                or ["- No player-specific media guide match imported yet."]
            ),
            "",
            "Manual producer notes:",
            *(
                self._manual_note_lines(
                    player_id=roster["player_id"],
                    team_code=value(roster, "team_code", ""),
                    game_id=(
                        self.selected_game.game_id
                        if isinstance(getattr(self, "selected_game", None), SelectedGame)
                        else None
                    ),
                )
                or ["- No manual notes entered yet."]
            ),
        ]
        self._set_text(self.stat_texts["sources"], "\n".join(source_lines))
        self._set_text(self.stat_texts["career"], CAREER_LABEL.upper() + "\n\nBATTING\n" + self.batting_line(cb) + "\n\nPITCHING\n" + self.pitching_line(cp) + "\n\nFIELDING\n" + self.fielding_line(cf))
        self._set_text(self.stat_texts["current"], "BATTING\n" + self.batting_line(yb) + "\n\nPITCHING\n" + self.pitching_line(yp) + "\n\nFIELDING\n" + self.fielding_line(yf))
        self._set_text(self.stat_texts["previous"], "BATTING\n" + self.batting_line(pb) + "\n\nPITCHING\n" + self.pitching_line(pp) + "\n\nFIELDING\n" + self.fielding_line(pf))
        self._set_text(self.stat_texts["fielding"], CAREER_LABEL.upper() + "\n" + self.fielding_line(cf) + f"\n\n{CURRENT_YEAR}\n" + self.fielding_line(yf) + f"\n\n{CURRENT_YEAR-1}\n" + self.fielding_line(pf))

    def gfx_text(self, kind):
        semantic_kind = COPY_KIND_ALIASES.get(kind)
        if semantic_kind is None or self.selected_player_id is None:
            return ""
        roster_frame = self.db.get("roster", pd.DataFrame())
        if roster_frame.empty or "player_id" not in roster_frame:
            return ""
        roster_rows = roster_frame[
            pd.to_numeric(roster_frame["player_id"], errors="coerce").eq(
                self.selected_player_id
            )
        ]
        if len(roster_rows) != 1:
            return ""
        roster = roster_rows.iloc[0]
        raw_number = _optional_text(roster, "jersey_number")
        number = raw_number[:-2] if raw_number and raw_number.endswith(".0") else raw_number
        number_label = f"#{number}" if number else "NUMBER UNAVAILABLE"
        player_name = _optional_text(roster, "player_name") or "Player name unavailable"
        team = _optional_text(roster, "team") or "Team unknown"
        position = _optional_text(roster, "position") or "Position unknown"
        status = self.roster_status(roster)
        is_pitcher = position.strip().upper() in PITCHER_POSITIONS
        freshness = getattr(
            self,
            "data_freshness_text",
            "Data updated: unknown - VERIFY BEFORE AIR",
        )
        common = [
            f"STATUS: {status}",
            "SOURCE: Official AUSL roster and imported stat snapshot",
            freshness,
        ]
        if not self.is_active_roster(roster):
            common.insert(1, f"AVAILABILITY WARNING: {status} - VERIFY BEFORE AIR")

        if semantic_kind == "player_id":
            body = f"{number_label} — {player_name.upper()} — {position} — {team.upper()}"
        elif semantic_kind == "season_stat":
            stat_row = self.stat_row(
                f"pitching_{CURRENT_YEAR}" if is_pitcher else f"batting_{CURRENT_YEAR}"
            )
            stat = self.pitching_line(stat_row) if is_pitcher else self.batting_line(stat_row)
            body = f"{player_name.upper()} — {CURRENT_YEAR} AUSL SEASON\n{stat}"
        elif semantic_kind == "career_stat":
            stat_row = self.stat_row("career_pitching" if is_pitcher else "career_batting")
            stat = self.pitching_line(stat_row) if is_pitcher else self.batting_line(stat_row)
            body = f"{player_name.upper()} — {CAREER_COPY_LABEL}\n{stat}"
        else:
            narrative = _manual_note_text(
                getattr(self, "current_broadcast_note", "")
            ) or "No verified announcer note is available."
            body = f"[VERIFY] {player_name}: {narrative}"
        return "\n".join([body, *common])

    @staticmethod
    def _stat_optional_number(row, key):
        if row is None or key not in row:
            return None
        try:
            number = float(row[key])
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _stat_number(row, key):
        number = AUSLStatsApp._stat_optional_number(row, key)
        return number if number is not None else 0.0

    @staticmethod
    def compact_draft_info(roster):
        """Keep useful draft context in the bio line without making it the note."""
        comments = str(value(roster, "status_comments", "")).strip()
        transaction = str(value(roster, "transaction_type", "")).strip()
        draft_terms = ("draft", "round", "pick", "protect")
        if comments and comments != "—" and any(term in comments.lower() for term in draft_terms):
            return comments.replace("[", "").replace("]", "")
        if transaction and transaction != "—" and any(term in transaction.lower() for term in draft_terms):
            return transaction
        return ""

    def build_broadcast_note(self, is_pitcher, career_batting, career_pitching, season_batting, season_pitching):
        """Create a concise milestone-first note for the selected player."""
        if is_pitcher:
            career = career_pitching
            milestones = [
                ("strikeOuts", 25, 7, "career strikeouts"),
                ("wins", 5, 2, "career wins"),
                ("appearances", 25, 5, "career appearances"),
            ]
        else:
            career = career_batting
            milestones = [
                ("hits", 25, 7, "career hits"),
                ("homeRuns", 5, 2, "career home runs"),
                ("runsBattedIn", 25, 7, "career RBI"),
                ("stolenBases", 10, 2, "career stolen bases"),
                ("gamesPlayed", 25, 5, "career games"),
            ]

        candidates = []
        for priority, (key, interval, max_gap, label) in enumerate(milestones):
            current_value = self._stat_optional_number(career, key)
            if current_value is None or current_value <= 0:
                continue
            current = int(current_value)
            target = ((current // interval) + 1) * interval
            gap = target - current
            if gap <= max_gap:
                candidates.append((gap / interval, priority, gap, target, label))
        if candidates:
            _ratio, _priority, gap, target, label = min(candidates)
            verb = "Needs" if gap != 1 else "Needs just"
            unit = "more" if gap != 1 else "more"
            return f"{verb} {gap} {unit} to reach {target} AUSL {label}; this is a clean milestone to track if she appears."

        if is_pitcher and season_pitching is not None:
            strikeouts = self._stat_optional_number(season_pitching, "strikeOuts")
            outs = self._innings_to_outs(value(season_pitching, "inningsPitched", None))
            era_value = self._stat_optional_number(season_pitching, "earnedRunAverage")
            appearances = self._stat_optional_number(season_pitching, "appearances")
            if (
                strikeouts is not None
                and outs is not None
                and outs > 0
                and era_value is not None
                and appearances is not None
                and appearances > 0
            ):
                innings = self._outs_to_innings(outs)
                era = _format_decimal_value(era_value)
                return f"Has {int(strikeouts)} strikeouts over {innings} innings with a {era} ERA this season, giving the booth a current-form pitching note."
        if season_batting is not None:
            plate_appearances = self._stat_optional_number(season_batting, "plateAppearances")
            hits = self._stat_optional_number(season_batting, "hits")
            home_runs = self._stat_optional_number(season_batting, "homeRuns")
            rbi = self._stat_optional_number(season_batting, "runsBattedIn")
            if (
                plate_appearances is not None
                and plate_appearances > 0
                and hits is not None
                and home_runs is not None
                and rbi is not None
            ):
                return f"Has {int(hits)} hits, {int(home_runs)} home runs and {int(rbi)} RBI this season, making her an easy hitter spotlight if she comes up in a key spot."
        return "No verified current-season stat narrative is available; check the live game tab and official notes before air."

    def copy_gfx(self, kind):
        if kind not in COPY_KIND_ALIASES:
            self.copy_status.set("Copy type unavailable")
            return
        roster_frame = self.db.get("roster", pd.DataFrame())
        roster_rows = (
            roster_frame[
                pd.to_numeric(roster_frame["player_id"], errors="coerce").eq(
                    self.selected_player_id
                )
            ]
            if not roster_frame.empty and "player_id" in roster_frame
            else pd.DataFrame()
        )
        if len(roster_rows) != 1:
            self.copy_status.set(
                "Player identity is unavailable or ambiguous; nothing copied."
            )
            return
        text = self.gfx_text(kind)
        if not text:
            self.copy_status.set("Player copy is unavailable; nothing copied.")
            return
        roster = roster_rows.iloc[0]
        if not self.is_active_roster(roster):
            status = self.roster_status(roster)
            confirmed = messagebox.askyesno(
                "Verify player availability",
                f"This player is listed as {status}. Verify availability before air. Copy anyway?",
            )
            if not confirmed:
                self.copy_status.set(f"Not copied; {status} requires confirmation")
                return
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()
        self.copy_status.set("Copied to clipboard")

    def refresh_live(self):
        if not self.network_requests_permitted(
            "manual live refresh",
            status_var=getattr(self, "live_status", None),
        ):
            return
        game_id = self.game_id_var.get().strip()
        selected = getattr(self, "selected_game", None)
        if not isinstance(selected, SelectedGame):
            self.live_status.set(
                "Select an exact official game before loading live data."
            )
            return
        if game_id != selected.game_id:
            self.live_status.set(
                f"Live Game ID must match selected official Game {selected.game_id}; "
                f"typed/requested ID {game_id or 'unavailable'} was blocked."
            )
            return
        if getattr(self, "_live_refresh_in_flight", False):
            suffix = f" for game {game_id}" if game_id else ""
            self.live_status.set(f"Live refresh is already in progress{suffix}.")
            return

        generation = getattr(self, "_live_request_generation", 0) + 1
        self._live_request_generation = generation
        request_token = LiveRequestToken(selected.game_id, generation)
        cancel_token = CancelToken()
        self._active_live_request = request_token
        self._live_refresh_cancel_token = cancel_token
        self._live_refresh_in_flight = True
        self._ensure_main_thread_dispatch()
        self._sync_live_refresh_button()
        self.live_status.set("Refreshing official game data...")
        self._log_event("live_refresh_started", source="official_live_feed", game_id=game_id)

        def work():
            try:
                game, box = fetch_live_game(game_id, cancel_token=cancel_token)
            except RefreshCancelled:
                self._post_main_thread(
                    self._finish_live_refresh_cancelled,
                    request_token,
                )
                return
            except Exception as exc:
                self._post_main_thread(
                    self._finish_live_refresh_error,
                    exc,
                    request_token,
                )
                return
            self._post_main_thread(
                self._finish_live_refresh_success,
                game,
                box,
                request_token,
            )

        try:
            threading.Thread(target=work, daemon=True).start()
        except Exception as exc:
            self._finish_live_refresh_error(exc, request_token)

    def cancel_live_refresh(self):
        """Cancel an in-flight live refresh immediately.

        Frees the in-flight flag and re-enables the live refresh button
        right away, without waiting for the abandoned background thread's
        network call to finish or time out. Its eventual callback is
        discarded as stale once it arrives (see ``_live_request_is_current``).
        """

        token = getattr(self, "_live_refresh_cancel_token", None)
        request_token = getattr(self, "_active_live_request", None)
        if token is None and request_token is None:
            return
        if token is not None:
            token.cancel()
        self._live_refresh_cancel_token = None
        self._active_live_request = None
        self._live_refresh_in_flight = False
        self._sync_live_refresh_button()
        self.live_status.set("Live refresh cancelled; last-known-good live data retained.")
        self._refresh_game_day_if_allowed()
        self._log_event(
            "live_refresh_cancel_requested",
            source="official_live_feed",
            game_id=getattr(request_token, "selected_game_id", ""),
        )

    def _live_request_is_current(self, request_token):
        selected = getattr(self, "selected_game", None)
        return (
            isinstance(request_token, LiveRequestToken)
            and request_token == getattr(self, "_active_live_request", None)
            and isinstance(selected, SelectedGame)
            and selected.game_id == request_token.selected_game_id
            and self.game_id_var.get().strip() == request_token.selected_game_id
        )

    def _discard_stale_live_callback(self, request_token):
        if request_token == getattr(self, "_active_live_request", None):
            self._active_live_request = None
            self._live_refresh_in_flight = False
            self._sync_live_refresh_button()
            self.live_status.set(
                "Discarded late live response for Game "
                f"{request_token.selected_game_id}; the selected game changed."
            )
        self._log_event(
            "live_refresh_discarded",
            source="official_live_feed",
            requested_game_id=getattr(request_token, "selected_game_id", ""),
            reason="selected_game_changed",
        )

    def _finish_live_refresh_success(self, game, box, request_token):
        if not self._live_request_is_current(request_token):
            self._discard_stale_live_callback(request_token)
            return
        returned_game_id = (
            _manual_note_identifier(game.get("gameId"))
            if isinstance(game, dict)
            else ""
        )
        requested_game_id = request_token.selected_game_id
        if not returned_game_id or returned_game_id != requested_game_id:
            self._finish_live_refresh_error(
                ValueError(
                    "Official live response game ID "
                    f"{returned_game_id or 'unavailable'} did not match requested game ID "
                    f"{requested_game_id or 'unavailable'}; no live data was loaded."
                ),
                request_token,
            )
            return
        try:
            self._finish_live(game, box)
        except Exception as exc:
            self._finish_live_refresh_error(exc, request_token)
            return
        self._active_live_request = None
        self._live_refresh_cancel_token = None
        self._live_refresh_in_flight = False
        self._sync_live_refresh_button()
        self._log_event(
            "live_refresh_succeeded",
            source="official_live_feed",
            requested_game_id=requested_game_id,
            game_id=game.get("gameId") if isinstance(game, dict) else None,
            record_status=game.get("recordStatus") if isinstance(game, dict) else None,
        )

    def _finish_live_refresh_error(self, exc, request_token):
        if not self._live_request_is_current(request_token):
            self._discard_stale_live_callback(request_token)
            return
        requested_game_id = request_token.selected_game_id
        self._active_live_request = None
        self._live_refresh_cancel_token = None
        self._live_refresh_in_flight = False
        self.live_health = LiveFeedHealth(
            "RED", "DISCONNECTED", None, "", None, "REFRESH FAILED"
        )
        self._sync_live_refresh_button()
        self.live_status.set(f"Live feed error: {exc}")
        self.refresh_game_day_dashboard()
        self._log_event(
            "live_refresh_failed",
            source="official_live_feed",
            game_id=requested_game_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    def _finish_live_refresh_cancelled(self, request_token):
        if not self._live_request_is_current(request_token):
            self._discard_stale_live_callback(request_token)
            return
        requested_game_id = request_token.selected_game_id
        self._active_live_request = None
        self._live_refresh_cancel_token = None
        self._live_refresh_in_flight = False
        self._sync_live_refresh_button()
        self.live_status.set("Live refresh cancelled; last-known-good live data retained.")
        self.refresh_game_day_dashboard()
        self._log_event(
            "live_refresh_cancelled",
            source="official_live_feed",
            game_id=requested_game_id,
        )

    def _finish_live(self, game, box):
        self.live_game, self.live_box = game, box
        self.live_health = live_feed_health(game)
        self.live_status.set(
            f"Loaded game {game.get('gameId')} — "
            f"{game.get('recordStatus','Unknown status')} | {self.live_health.label}"
        )
        self._set_text(self.live_summary, self.format_live_comparison())
        self.search_live_player()
        self._schedule_live()
        self.refresh_game_day_dashboard()

    def _schedule_live(self):
        self._cancel_live_timer()
        if bool(getattr(self, "_offline_mode", False)):
            auto_var = getattr(self, "auto_var", None)
            if auto_var is not None:
                auto_var.set(False)
            return
        selected = getattr(self, "selected_game", None)
        if (
            self.auto_var.get()
            and isinstance(selected, SelectedGame)
            and self.game_id_var.get().strip() == selected.game_id
        ):
            self._live_timer_id = self.root.after(30000, self._auto_refresh)

    def _auto_refresh(self):
        self._live_timer_id = None
        if bool(getattr(self, "_offline_mode", False)):
            return
        if self.auto_var.get():
            self.refresh_live()

    def format_live_comparison(self):
        if not self.live_box:
            return "No live box score loaded."
        competitors = self.live_box.get("competitors") or []
        lines = self.live_box.get("lineScores") or []
        title = " vs ".join(c.get("name", "Team") for c in competitors)
        health = getattr(self, "live_health", None)
        if not isinstance(health, LiveFeedHealth):
            health = live_feed_health(getattr(self, "live_game", None))
        output = [
            title.upper(),
            "LIVE / OFFICIAL FEED — VERIFY BEFORE AIR",
            health.label,
            "",
        ]
        team_by_id = {c.get("eventTeamId"): c for c in competitors}
        if lines:
            for line in lines:
                team = team_by_id.get(line.get("eventTeamId"), {})
                name = line.get("abbreviation") or line.get("teamName") or line.get("name") or team.get("abbreviation") or team.get("name") or str(line.get("eventTeamId", "TEAM"))
                runs = line.get("runs", line.get("score", "—")); hits = line.get("hits", "—"); errors = line.get("errors", "—")
                innings = line.get("innings") or line.get("lineScore") or []
                if isinstance(innings, list): innings = " ".join(str(x.get("runs", x)) if isinstance(x, dict) else str(x) for x in innings)
                output.append(f"{name:<12} R {runs}   H {hits}   E {errors}   | {innings}")
        else:
            output.append("The official box score is available, but play has not started or no line score has been posted.")
        for section in ("batting", "pitching"):
            count = sum(1 for category, _row in self._flatten_live_players() if category == section)
            output.append(f"\n{section.title()} player lines available: {count}")
        return "\n".join(output)

    def _flatten_live_players(self):
        if not self.live_box:
            return []
        found = []
        for category in ("batting", "pitching"):
            section = self.live_box.get(category) or {}
            groups = section.values() if isinstance(section, dict) else [section]
            for group in groups:
                if isinstance(group, dict):
                    group = group.get("players") or group.get("stats") or [group]
                if isinstance(group, list):
                    for row in group:
                        if isinstance(row, dict): found.append((category, row))
        return found

    def search_live_player(self):
        query = self.live_search_var.get().strip().lower()
        if not self.live_box:
            self._set_text(self.live_player, "Load a live game first.")
            return
        matches = []
        for category, row in self._flatten_live_players():
            name = row.get("playerName") or row.get("displayName") or row.get("statName") or row.get("name") or f"{row.get('firstName','')} {row.get('lastName','')}".strip()
            if not query or query in name.lower():
                matches.append((category, name, row))
        if not matches:
            self.live_player_copy_text = ""
            self._set_text(self.live_player, "No matching player line is currently in the official box score.")
            return
        team_by_id = {c.get("eventTeamId"): c for c in self.live_box.get("competitors", [])}
        chunks = []
        for category, name, row in matches[:20]:
            team = team_by_id.get(row.get("eventTeamId"), {})
            heading = f"{name.upper()} — {team.get('abbreviation', '')} {row.get('position', '')}".strip()
            if category == "batting":
                stat_line = " | ".join(
                    f"{label} {row.get(key, '—')}"
                    for label, key in [("AB", "ab"), ("R", "r"), ("H", "h"), ("RBI", "rbi"), ("BB", "bb"), ("SO", "so"), ("LOB", "lob")]
                )
            else:
                stat_line = " | ".join(
                    f"{label} {row.get(key, '—')}"
                    for label, key in [("IP", "ip"), ("H", "h"), ("R", "r"), ("ER", "er"), ("BB", "bb"), ("SO", "so"), ("HR", "hr"), ("NP", "np")]
                )
                if row.get("decision"):
                    stat_line += f" | {row['decision']} {row.get('record', '')}".rstrip()
            action_note = self.live_action_note(category, row)
            chunks.append(f"{heading}\n{stat_line}\nACTION NOTE: {action_note}")
        self.live_player_copy_text = "\n\n".join(chunks)
        self._set_text(self.live_player, self.live_player_copy_text)

    def copy_live_player(self):
        if not self.live_player_copy_text:
            self.live_status.set("Search for a live player first")
            return
        self.root.clipboard_clear(); self.root.clipboard_append(self.live_player_copy_text); self.root.update()
        self.live_status.set("Live player line copied to clipboard")

    @staticmethod
    def live_action_note(category, row):
        """Turn a box-score row into an action-focused broadcast angle."""
        def stat(key, *, count=False):
            raw_value = row.get(key)
            if raw_value is None or raw_value == "" or pd.api.types.is_bool(raw_value):
                return None
            try:
                number = float(raw_value)
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(number):
                return None
            if count and (number < 0 or not number.is_integer()):
                return None
            return number

        notes = []
        if category == "batting":
            batting_values = [
                stat(key, count=True) for key in ("h", "rbi", "r", "hr")
            ]
            if any(item is None for item in batting_values):
                return "Action note unavailable — official live stats are incomplete; verify before air."
            hits, rbi, runs, home_runs = (int(item) for item in batting_values)
            if home_runs:
                notes.append(f"has homered{' twice' if home_runs == 2 else f' {home_runs} times' if home_runs > 2 else ''}")
            if hits >= 2:
                notes.append(f"has a {hits}-hit game")
            if rbi >= 2:
                notes.append(f"has driven in {rbi} runs")
            if runs >= 2:
                notes.append(f"has scored {runs} runs")
            if not notes:
                notes.append("game line is ready for the next plate appearance")
        else:
            innings_value, strikeouts_value, earned_runs_value = (
                stat("ip"),
                stat("so", count=True),
                stat("er", count=True),
            )
            if any(
                item is None
                for item in (innings_value, strikeouts_value, earned_runs_value)
            ):
                return "Action note unavailable — official live stats are incomplete; verify before air."
            innings = _format_innings_value(row.get("ip"))
            if innings == "—":
                return "Action note unavailable — official live stats are incomplete; verify before air."
            strikeouts, earned_runs = int(strikeouts_value), int(earned_runs_value)
            if innings_value >= 3 and earned_runs == 0:
                notes.append(f"has worked {innings} scoreless innings")
            if strikeouts >= 4:
                notes.append(f"has struck out {strikeouts}")
            if row.get("decision"):
                notes.append(f"is credited with the {str(row['decision']).lower()}")
            if not notes:
                notes.append(f"has allowed {earned_runs} earned run{'s' if earned_runs != 1 else ''} over {innings} innings")
        sentence = "; ".join(notes)
        return sentence[:1].upper() + sentence[1:] + "."

    def copy_live_comparison(self):
        text = self.format_live_comparison()
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()
        self.live_status.set("Game comparison copied to clipboard")

    @staticmethod
    def _set_text(widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")


def main():
    root = tk.Tk()
    logger = None
    try:
        logger, _log_path = configure_logging()
    except Exception:
        # A log-directory problem must not prevent the production tool opening.
        logger = None
    AUSLStatsApp(root, logger=logger)
    root.mainloop()


if __name__ == "__main__":
    main()
