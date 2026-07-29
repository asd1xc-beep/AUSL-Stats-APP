"""Typed optional-enrichment modes and producer approval boundaries."""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Any, Mapping

import pandas as pd

from ausl_splits import apply_split_sample_policy


class EnrichmentMode(str, Enum):
    CORE_ONLY = "core_only"
    PRODUCER_APPROVED = "producer_approved"
    DEVELOPER_REVIEW = "developer_review"


PRODUCER_ENRICHMENT_KEYS = (
    "batting_splits",
    "pitching_splits",
    "fielding_splits",
    "storyline_sources",
    "media_players",
    "media_teams",
    "media_notes",
    "media_audit",
    "clean_media_notes",
    "official_game_notes",
)
DEVELOPER_ONLY_KEYS = ("raw_media_chunks",)

_NOTE_APPROVAL_FIELDS = (
    "source_game_id",
    "subject_player_id",
    "subject_player_name",
    "subject_team_code",
    "opposing_team_code",
    "note_text",
    "note_category",
    "source_date",
    "source_url",
    "source_pdf",
    "source_page",
    "parser_version",
    "normalized_hash",
    "verification_state",
    "needs_review",
    "approval_state",
    "approval_method",
    "approved_by",
    "approved_at",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    return _text(value).casefold() in {"false", "0", "no"}


def _identifier(value: Any) -> str:
    return _text(value)


def official_note_approval_record_id(row: Mapping[str, Any] | pd.Series) -> str:
    payload = {
        field: _text(row.get(field))
        for field in _NOTE_APPROVAL_FIELDS
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approve_official_note_row(
    row: Mapping[str, Any] | pd.Series,
    *,
    reviewer: str,
    approved_at: str,
) -> dict[str, Any]:
    """Create one review transaction; callers still must resolve roster identity."""

    reviewer_text = _text(reviewer)
    approved_at_text = _text(approved_at)
    if not reviewer_text or not approved_at_text:
        raise ValueError("Official-note approval requires reviewer and timestamp")
    candidate = dict(row)
    required = (
        "game_id",
        "source_game_id",
        "subject_player_id",
        "subject_player_name",
        "subject_team_code",
        "opposing_team_code",
        "note_text",
        "source_date",
        "source_url",
        "source_pdf",
        "source_page",
        "parser_version",
        "normalized_hash",
    )
    if any(not _text(candidate.get(field)) for field in required):
        raise ValueError("Official-note identity and provenance must be complete")
    if _identifier(candidate.get("game_id")) != _identifier(
        candidate.get("source_game_id")
    ):
        raise ValueError("Official-note source game identity does not match")
    team = _text(candidate.get("subject_team_code")).upper()
    opposing = _text(candidate.get("opposing_team_code")).upper()
    if not team or not opposing or team == opposing:
        raise ValueError("Official-note team/opponent identity is invalid")
    candidate.update(
        {
            "verification_state": "VERIFIED",
            "needs_review": False,
            "approval_state": "approved",
            "approval_method": "manual_review",
            "approved_by": reviewer_text,
            "approved_at": approved_at_text,
        }
    )
    candidate["approval_record_id"] = official_note_approval_record_id(
        candidate
    )
    return candidate


def _source_health(manifest: Mapping[str, Any], source: str) -> str:
    entries = manifest.get("source_health") if isinstance(manifest, Mapping) else None
    entry = entries.get(source) if isinstance(entries, Mapping) else None
    status = _text(entry.get("status") if isinstance(entry, Mapping) else "").casefold()
    return status if status in {"green", "yellow", "red"} else "unknown"


def _roster_identity(roster: pd.DataFrame) -> dict[str, tuple[str, str]]:
    if (
        not isinstance(roster, pd.DataFrame)
        or roster.empty
        or not {"player_id", "player_name", "team_code"}.issubset(roster.columns)
    ):
        return {}
    identities: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for _, row in roster.iterrows():
        player_id = _identifier(row.get("player_id"))
        name = _text(row.get("player_name"))
        team = _text(row.get("team_code")).upper()
        if not player_id or not name or not team:
            continue
        value = (name.casefold(), team)
        if player_id in identities and identities[player_id] != value:
            ambiguous.add(player_id)
        identities[player_id] = value
    return {
        player_id: value
        for player_id, value in identities.items()
        if player_id not in ambiguous
    }


def _approved_official_notes(
    frame: pd.DataFrame,
    *,
    roster: pd.DataFrame,
    manifest: Mapping[str, Any],
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=list(getattr(frame, "columns", [])))
    identities = _roster_identity(roster)
    health = _source_health(manifest, "official_game_notes")
    approved: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        player_id = _identifier(row.get("subject_player_id"))
        identity = identities.get(player_id)
        team = _text(row.get("subject_team_code")).upper()
        opposing = _text(row.get("opposing_team_code")).upper()
        source_game_id = _identifier(row.get("source_game_id"))
        row_game_id = _identifier(row.get("game_id"))
        required = (
            source_game_id,
            row_game_id,
            player_id,
            _text(row.get("subject_player_name")),
            team,
            opposing,
            _text(row.get("source_date")),
            _text(row.get("source_url")),
            _text(row.get("source_pdf")),
            _identifier(row.get("source_page")),
            _text(row.get("parser_version")),
            _text(row.get("normalized_hash")),
            _text(row.get("approval_record_id")),
            _text(row.get("approved_by")),
            _text(row.get("approved_at")),
        )
        if not all(required):
            continue
        if source_game_id != row_game_id or team == opposing:
            continue
        if identity is None:
            continue
        expected_name, expected_team = identity
        if (
            _text(row.get("subject_player_name")).casefold() != expected_name
            or team != expected_team
        ):
            continue
        team_codes = {
            token.strip().upper()
            for token in _text(row.get("team_codes")).split(",")
            if token.strip()
        }
        if team_codes != {team, opposing}:
            continue
        if (
            _text(row.get("verification_state")).upper() != "VERIFIED"
            or not _false(row.get("needs_review"))
            or _text(row.get("approval_state")).casefold() != "approved"
            or _text(row.get("approval_method")).casefold() not in {
                "manual_review",
                "producer_review",
            }
        ):
            continue
        from ausl_data import _normalized_game_note_hash

        if _text(row.get("normalized_hash")) != _normalized_game_note_hash(
            row.get("note_text")
        ):
            continue
        record_id = _text(row.get("approval_record_id"))
        if record_id != official_note_approval_record_id(row):
            continue
        candidate = row.to_dict()
        candidate["producer_approved"] = True
        candidate["producer_air_ready"] = health == "green"
        candidate["producer_trust_state"] = (
            "VERIFIED"
            if health == "green"
            else "STALE"
            if health == "yellow"
            else "UNAVAILABLE"
        )
        approved.append(candidate)
    return pd.DataFrame(approved).reset_index(drop=True)


def _approved_media(
    frame: pd.DataFrame,
    *,
    roster: pd.DataFrame,
    manifest: Mapping[str, Any],
    expected_entity_type: str | None = None,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=list(getattr(frame, "columns", [])))
    # Lazy import avoids an ausl_data -> ausl_enrichment import cycle.
    from ausl_data import media_approval_record_id

    identities = _roster_identity(roster)
    known_teams = {team for _name, team in identities.values()}
    health = _source_health(manifest, "media_guide")
    approved: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        entity_type = _text(row.get("entity_type")).casefold()
        if expected_entity_type and entity_type != expected_entity_type:
            continue
        entity_id = _identifier(row.get("entity_id"))
        entity_name = _text(row.get("entity_name"))
        required = (
            entity_type,
            entity_id,
            entity_name,
            _text(row.get("source_name")),
            _text(row.get("source_url")),
            _text(row.get("expected_printed_pages")),
            _text(row.get("parsed_pdf_pages")),
            _text(row.get("guide_date")),
            _text(row.get("parser_version")),
            _text(row.get("approval_record_id")),
        )
        if not all(required) or entity_type not in {"player", "team"}:
            continue
        if entity_type == "player":
            identity = identities.get(entity_id)
            if identity is None or entity_name.casefold() != identity[0]:
                continue
            row_team = _text(row.get("team_code")).upper()
            if row_team and row_team != identity[1]:
                continue
        else:
            if entity_id.upper() not in known_teams:
                continue
            row_team = _text(row.get("team_code")).upper()
            if row_team and row_team != entity_id.upper():
                continue
        if (
            _text(row.get("match_status")).casefold() != "verified"
            or not _false(row.get("needs_review"))
            or _text(row.get("warnings"))
            or _text(row.get("approval_state")).casefold() != "approved"
            or _text(row.get("approval_method")).casefold()
            not in {"parser_exact_identity", "manual_review"}
        ):
            continue
        record_id = _text(row.get("approval_record_id"))
        if record_id != media_approval_record_id(row):
            continue
        candidate = row.to_dict()
        candidate["producer_approved"] = True
        candidate["producer_air_ready"] = health == "green"
        candidate["producer_trust_state"] = (
            "VERIFIED"
            if health == "green"
            else "STALE"
            if health == "yellow"
            else "UNAVAILABLE"
        )
        approved.append(candidate)
    return pd.DataFrame(approved).reset_index(drop=True)


def approved_enrichment_frames(
    frames: Mapping[str, pd.DataFrame],
    *,
    roster: pd.DataFrame,
    manifest: Mapping[str, Any],
) -> dict[str, pd.DataFrame]:
    """Filter raw review workbooks into the only producer-loadable views."""

    result = {
        key: pd.DataFrame()
        for key in (*PRODUCER_ENRICHMENT_KEYS, *DEVELOPER_ONLY_KEYS)
    }
    result["official_game_notes"] = _approved_official_notes(
        frames.get("official_game_notes", pd.DataFrame()),
        roster=roster,
        manifest=manifest,
    )
    for key, expected_type in (
        ("media_players", "player"),
        ("media_teams", "team"),
        ("media_notes", None),
        ("clean_media_notes", None),
    ):
        result[key] = _approved_media(
            frames.get(key, pd.DataFrame()),
            roster=roster,
            manifest=manifest,
            expected_entity_type=expected_type,
        )
    for key, category in (
        ("batting_splits", "batting"),
        ("pitching_splits", "pitching"),
        ("fielding_splits", "fielding"),
    ):
        filtered = apply_split_sample_policy(
            frames.get(key, pd.DataFrame()), category=category
        )
        if not filtered.empty:
            health = _source_health(manifest, "split_stats")
            filtered["producer_approved"] = True
            filtered["producer_air_ready"] = (
                filtered["split_air_ready"].astype(bool) & (health == "green")
            )
            filtered["producer_trust_state"] = (
                "VERIFIED"
                if health == "green"
                else "STALE"
                if health == "yellow"
                else "UNAVAILABLE"
            )
        result[key] = filtered
    # Source registry/audit are metadata, not facts. They are retained only
    # when explicitly safe and never become air copy on their own.
    result["storyline_sources"] = frames.get(
        "storyline_sources", pd.DataFrame()
    ).copy()
    result["media_audit"] = pd.DataFrame()
    result["raw_media_chunks"] = pd.DataFrame()
    return result
