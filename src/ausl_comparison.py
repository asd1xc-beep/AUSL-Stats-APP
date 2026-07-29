"""Canonical, neutral side-by-side player comparison for Phase 6F."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

import pandas as pd

from ausl_data import canonical_pitching_whip, innings_to_outs, normalize_roster_status, outs_to_innings
from ausl_facts import BroadcastFact, FactCollection


class ComparisonBuildError(ValueError):
    """Raised when exact comparison identity cannot be established."""


class MetricSection(str, Enum):
    SEASON_BATTING = "season_batting"
    SEASON_PITCHING = "season_pitching"
    SEASON_FIELDING = "season_fielding"
    CAREER_BATTING = "career_batting"
    CAREER_PITCHING = "career_pitching"
    CAREER_FIELDING = "career_fielding"


@dataclass(frozen=True)
class ComparisonMetric:
    metric_key: str
    label: str
    section: MetricSection
    table_template: str
    source_field: str
    format_kind: str
    order: int


def _metric_specs():
    batting = (
        ("g", "G", "gamesPlayed", "whole"),
        ("pa", "PA", "plateAppearances", "whole"),
        ("h", "H", "hits", "whole"),
        ("hr", "HR", "homeRuns", "whole"),
        ("rbi", "RBI", "runsBattedIn", "whole"),
        ("avg", "AVG", "battingAverage", "rate"),
        ("obp", "OBP", "onBasePercentage", "rate"),
        ("slg", "SLG", "sluggingPercentage", "rate"),
        ("ops", "OPS", "opsPercentage", "rate"),
    )
    pitching = (
        ("app", "APP", "appearances", "whole"),
        ("gs", "GS", "gamesStarted", "whole"),
        ("w", "W", "wins", "whole"),
        ("l", "L", "losses", "whole"),
        ("ip", "IP", "inningsPitched", "innings"),
        ("era", "ERA", "earnedRunAverage", "decimal"),
        ("so", "SO", "strikeOuts", "whole"),
        ("bb", "BB", "baseOnBalls", "whole"),
        ("whip", "WHIP", "__canonical_whip__", "decimal"),
        ("sv", "SV", "saves", "whole"),
    )
    fielding = (
        ("g", "G", "gamesPlayed", "whole"),
        ("po", "PO", "putOuts", "whole"),
        ("a", "A", "assists", "whole"),
        ("e", "E", "errors", "whole"),
        ("fld", "FLD%", "fieldingPercent", "rate"),
    )
    groups = (
        (MetricSection.SEASON_BATTING, "batting_{season}", batting),
        (MetricSection.SEASON_PITCHING, "pitching_{season}", pitching),
        (MetricSection.SEASON_FIELDING, "fielding_{season}", fielding),
        (MetricSection.CAREER_BATTING, "career_batting", batting),
        (MetricSection.CAREER_PITCHING, "career_pitching", pitching),
        (MetricSection.CAREER_FIELDING, "career_fielding", fielding),
    )
    order = 0
    for section, table, specs in groups:
        for suffix, label, source, formatter in specs:
            yield ComparisonMetric(
                metric_key=f"{section.value}.{suffix}",
                label=label,
                section=section,
                table_template=table,
                source_field=source,
                format_kind=formatter,
                order=order,
            )
            order += 1


COMPARISON_METRICS = tuple(_metric_specs())


@dataclass(frozen=True)
class ComparisonMetricValue:
    metric_key: str
    display_value: str
    available: bool
    source_name: str
    snapshot_timestamp: str


@dataclass(frozen=True)
class ComparisonMetricRow:
    metric: ComparisonMetric
    left: ComparisonMetricValue
    right: ComparisonMetricValue


@dataclass(frozen=True)
class ComparisonSection:
    section: MetricSection
    label: str
    rows: tuple[ComparisonMetricRow, ...]


@dataclass(frozen=True)
class ComparisonPlayer:
    player_id: str
    player_name: str
    team_code: str
    team_name: str
    jersey_number: str
    position: str
    roster_status: str
    warnings: tuple[str, ...]
    verified_facts: tuple[BroadcastFact, ...] = ()
    review_facts: tuple[BroadcastFact, ...] = ()


@dataclass(frozen=True)
class PlayerComparison:
    left: ComparisonPlayer
    right: ComparisonPlayer
    season: int
    selected_game_id: str | None
    database_identity: str
    source_name: str
    snapshot_timestamp: str
    sections: tuple[ComparisonSection, ...]
    fact_context_warning: str = ""
    summary: str = "Neutral aligned comparison; no performance judgment is applied."

    @property
    def rows(self) -> tuple[ComparisonMetricRow, ...]:
        return tuple(row for section in self.sections for row in section.rows)


@dataclass(frozen=True)
class ComparisonCopyRecord:
    left_player_id: str
    right_player_id: str
    database_identity: str
    selected_game_id: str | None
    copied_at: datetime
    text: str

    @classmethod
    def create(
        cls,
        comparison: PlayerComparison,
        *,
        text: str,
        copied_at: datetime | None = None,
    ) -> "ComparisonCopyRecord":
        timestamp = copied_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("Comparison copy timestamp must be timezone-aware")
        return cls(
            left_player_id=comparison.left.player_id,
            right_player_id=comparison.right.player_id,
            database_identity=comparison.database_identity,
            selected_game_id=comparison.selected_game_id,
            copied_at=timestamp.astimezone(timezone.utc),
            text=str(text),
        )


_SECTION_LABELS = {
    MetricSection.SEASON_BATTING: "Season Batting",
    MetricSection.SEASON_PITCHING: "Season Pitching",
    MetricSection.SEASON_FIELDING: "Season Fielding",
    MetricSection.CAREER_BATTING: "AUSL Career Batting",
    MetricSection.CAREER_PITCHING: "AUSL Career Pitching",
    MetricSection.CAREER_FIELDING: "AUSL Career Fielding",
}


def build_player_comparison(
    database: Mapping[str, Any],
    left_player_id: str,
    right_player_id: str,
    *,
    season: int,
    selected_game_id: str | None = None,
    facts: FactCollection | None = None,
) -> PlayerComparison:
    left_id = _identifier(left_player_id)
    right_id = _identifier(right_player_id)
    if not left_id or not right_id or left_id == right_id:
        raise ComparisonBuildError("Choose two different exact player identities")
    roster = database.get("roster", pd.DataFrame())
    left_row = _exact_row(roster, left_id, "roster")
    right_row = _exact_row(roster, right_id, "roster")
    source_name, snapshot_timestamp, database_identity = _database_provenance(database)
    fact_warning = ""
    fact_items: tuple[BroadcastFact, ...] = ()
    if facts is not None:
        if selected_game_id is not None and _identifier(facts.game_id) != _identifier(
            selected_game_id
        ):
            fact_warning = (
                "Canonical fact context is unavailable for this exact selected game."
            )
        elif facts.available:
            fact_items = tuple(
                fact
                for fact in facts.facts
                if fact.selected_game_id in (None, _identifier(selected_game_id))
            )
        else:
            fact_warning = facts.empty_reason or "Canonical fact context is unavailable."
    left = _comparison_player(left_row, left_id, fact_items)
    right = _comparison_player(right_row, right_id, fact_items)

    rows: list[ComparisonMetricRow] = []
    for metric in COMPARISON_METRICS:
        table_name = metric.table_template.format(season=season)
        table = database.get(table_name, pd.DataFrame())
        left_stat = _optional_exact_row(table, left_id)
        right_stat = _optional_exact_row(table, right_id)
        rows.append(
            ComparisonMetricRow(
                metric=metric,
                left=_metric_value(
                    metric, left_stat, source_name, snapshot_timestamp
                ),
                right=_metric_value(
                    metric, right_stat, source_name, snapshot_timestamp
                ),
            )
        )
    sections = tuple(
        ComparisonSection(
            section=section,
            label=_SECTION_LABELS[section],
            rows=tuple(row for row in rows if row.metric.section is section),
        )
        for section in MetricSection
    )
    return PlayerComparison(
        left=left,
        right=right,
        season=int(season),
        selected_game_id=_identifier(selected_game_id) or None,
        database_identity=database_identity,
        source_name=source_name,
        snapshot_timestamp=snapshot_timestamp,
        sections=sections,
        fact_context_warning=fact_warning,
    )


def comparison_with_sources_text(comparison: PlayerComparison) -> str:
    lines = [
        f"{comparison.left.player_name} vs. {comparison.right.player_name}",
        f"{comparison.season} AUSL season and AUSL career comparison",
        "",
    ]
    for section in comparison.sections:
        available_rows = [
            row for row in section.rows if row.left.available or row.right.available
        ]
        if not available_rows:
            continue
        lines.append(section.label.upper())
        for row in available_rows:
            left = row.left.display_value if row.left.available else "Unavailable"
            right = row.right.display_value if row.right.available else "Unavailable"
            lines.append(f"{row.metric.label}: {left} | {right}")
        lines.append("")
    lines.extend(
        [
            f"Left: {comparison.left.player_name} · {comparison.left.team_code} · "
            f"{comparison.left.roster_status}",
            f"Right: {comparison.right.player_name} · {comparison.right.team_code} · "
            f"{comparison.right.roster_status}",
            (
                f"Selected game context: Game {comparison.selected_game_id}"
                if comparison.selected_game_id
                else "Selected game context: Unavailable"
            ),
            f"Source: {comparison.source_name}",
            f"Data snapshot: {comparison.snapshot_timestamp or 'Unavailable'}",
            "Status: Verify roster availability and source freshness before air.",
        ]
    )
    if comparison.fact_context_warning:
        lines.append(f"Fact context: {comparison.fact_context_warning}")
    return "\n".join(lines)


def _comparison_player(
    roster_row: pd.Series,
    player_id: str,
    facts: tuple[BroadcastFact, ...],
) -> ComparisonPlayer:
    name = _text(roster_row.get("player_name")) or "Player name unavailable"
    team_code = _text(roster_row.get("team_code")).upper()
    team_name = _text(roster_row.get("team"))
    status = normalize_roster_status(roster_row.get("roster_status"))
    warnings = []
    if status.casefold() != "active":
        warnings.append(f"Roster status: {status} — verify availability before air.")
    if not team_code or not team_name:
        warnings.append("Current team identity is unavailable; verify before air.")
    player_facts = tuple(
        fact
        for fact in facts
        if fact.subject_id == player_id
        and fact.subject_type.value == "player"
    )
    verified = tuple(fact for fact in player_facts if fact.air_ready)
    review = tuple(fact for fact in player_facts if not fact.air_ready)
    return ComparisonPlayer(
        player_id=player_id,
        player_name=name,
        team_code=team_code or "UNASSIGNED",
        team_name=team_name or "Team unavailable",
        jersey_number=_jersey(roster_row.get("jersey_number")),
        position=_text(roster_row.get("position")) or "Position unavailable",
        roster_status=status,
        warnings=tuple(warnings),
        verified_facts=verified,
        review_facts=review,
    )


def _metric_value(
    metric: ComparisonMetric,
    row: pd.Series | None,
    source_name: str,
    snapshot_timestamp: str,
) -> ComparisonMetricValue:
    raw = None
    if row is not None:
        raw = (
            canonical_pitching_whip(row)
            if metric.source_field == "__canonical_whip__"
            else row.get(metric.source_field)
        )
    display = _format_value(raw, metric.format_kind)
    return ComparisonMetricValue(
        metric_key=metric.metric_key,
        display_value=display,
        available=display != "—",
        source_name=source_name,
        snapshot_timestamp=snapshot_timestamp,
    )


def _format_value(value, kind: str) -> str:
    if kind == "innings":
        outs = innings_to_outs(value)
        return outs_to_innings(outs) or "—"
    if value is None or isinstance(value, bool):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if not math.isfinite(number):
        return "—"
    if kind == "whole":
        return str(int(number)) if number.is_integer() else "—"
    if kind == "rate":
        rendered = f"{number:.3f}"
        return rendered[1:] if rendered.startswith("0.") else rendered
    if kind == "decimal":
        return f"{number:.2f}"
    return "—"


def _database_provenance(database: Mapping[str, Any]) -> tuple[str, str, str]:
    manifest = database.get("manifest")
    manifest = manifest if isinstance(manifest, Mapping) else {}
    source = _text(manifest.get("source")) or "Official AUSL local snapshot"
    timestamp = _text(manifest.get("updated_at"))
    explicit = _text(
        manifest.get("snapshot_id")
        or manifest.get("snapshot_identity")
        or manifest.get("database_version")
    )
    identity = explicit or hashlib.sha256(
        json.dumps(
            {"source": source, "updated_at": timestamp},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return source, timestamp, identity


def _exact_row(frame, player_id: str, label: str) -> pd.Series:
    row = _optional_exact_row(frame, player_id, allow_duplicate=False)
    if row is None:
        raise ComparisonBuildError(
            f"Player {player_id} must resolve to exactly one {label} identity"
        )
    return row


def _optional_exact_row(
    frame, player_id: str, *, allow_duplicate: bool = True
) -> pd.Series | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "player_id" not in frame:
        return None
    matches = frame[frame["player_id"].map(_identifier).eq(player_id)]
    if len(matches) == 1:
        return matches.iloc[0]
    if len(matches) > 1 and not allow_duplicate:
        raise ComparisonBuildError(
            f"Player {player_id} must resolve to exactly one roster identity"
        )
    return None


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).strip().split())


def _identifier(value) -> str:
    text = _text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _jersey(value) -> str:
    text = _identifier(value)
    return text if text.isdigit() else ""
