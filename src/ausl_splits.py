"""Pure, fail-closed policy for optional AUSL split-stat samples."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

import pandas as pd


class SplitSampleState(str, Enum):
    ELIGIBLE = "eligible"
    SMALL_SAMPLE = "small_sample"


@dataclass(frozen=True)
class SplitSamplePolicy:
    hitter_min_plate_appearances: int = 12
    pitcher_min_outs: int = 9

    def __post_init__(self) -> None:
        if self.hitter_min_plate_appearances < 1 or self.pitcher_min_outs < 1:
            raise ValueError("Split sample thresholds must be positive integers")

    def with_thresholds(self, **changes: int) -> "SplitSamplePolicy":
        return replace(self, **changes)


DEFAULT_SPLIT_SAMPLE_POLICY = SplitSamplePolicy()


def _normalized_token(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().casefold())


def is_regular_season_aggregate(row: pd.Series | dict[str, Any]) -> bool:
    """Match only a normalized exact aggregate identity, never a substring."""

    return any(
        _normalized_token(row.get(field)) == "regularseason"
        for field in ("split_key", "split_label", "season_type")
    )


def _nonnegative_integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def innings_to_outs(value: Any) -> int | None:
    """Convert canonical baseball innings notation to outs without guessing."""

    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if "." not in text and number.is_integer():
        return int(number) * 3
    match = re.fullmatch(r"(\d+)(?:\.(\d))?", text)
    if not match:
        return None
    whole = int(match.group(1))
    partial = int(match.group(2) or "0")
    if partial not in {0, 1, 2}:
        return None
    return whole * 3 + partial


def _pitching_outs(row: pd.Series) -> int | None:
    for field in ("innings_outs", "outs", "outsPitched"):
        if field in row.index:
            value = _nonnegative_integer(row.get(field))
            if value is not None:
                return value
            if row.get(field) not in (None, ""):
                return None
    for field in ("inningsPitched", "innings_pitched", "ip"):
        if field in row.index:
            return innings_to_outs(row.get(field))
    return None


def apply_split_sample_policy(
    frame: pd.DataFrame,
    *,
    category: str,
    policy: SplitSamplePolicy = DEFAULT_SPLIT_SAMPLE_POLICY,
) -> pd.DataFrame:
    """Return deterministic detailed split rows annotated with trust metadata.

    Malformed sample evidence and regular-season aggregate rows are removed.
    Valid detailed rows below the configured sample remain visible, but carry
    ``SMALL SAMPLE`` and can never be treated as air-ready.
    """

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=list(getattr(frame, "columns", [])))
    category_key = str(category or "").strip().casefold()
    if category_key not in {"batting", "pitching", "fielding"}:
        raise ValueError(f"Unsupported split category: {category}")

    kept: list[dict[str, Any]] = []
    for _, source_row in frame.iterrows():
        if is_regular_season_aggregate(source_row):
            continue
        row = source_row.to_dict()
        if category_key == "batting":
            sample = _nonnegative_integer(source_row.get("plateAppearances"))
            if sample is None:
                continue
            eligible = sample >= policy.hitter_min_plate_appearances
            row["split_sample_plate_appearances"] = sample
        elif category_key == "pitching":
            sample = _pitching_outs(source_row)
            if sample is None:
                continue
            eligible = sample >= policy.pitcher_min_outs
            row["split_sample_outs"] = sample
        else:
            # Fielding rows are not promoted as air-ready facts in Phase 7A.
            # They still must have an exact detailed split identity.
            if not _normalized_token(source_row.get("split_key")):
                continue
            eligible = False
        state = (
            SplitSampleState.ELIGIBLE
            if eligible
            else SplitSampleState.SMALL_SAMPLE
        )
        row["split_sample_state"] = state.value
        row["split_sample_label"] = "" if eligible else "SMALL SAMPLE"
        row["split_air_ready"] = bool(eligible)
        kept.append(row)

    if not kept:
        return pd.DataFrame(columns=[*frame.columns, "split_sample_state", "split_sample_label", "split_air_ready"])
    result = pd.DataFrame(kept)
    sort_columns = [
        column
        for column in ("season", "player_id", "split_key", "split_label")
        if column in result.columns
    ]
    if sort_columns:
        result = result.sort_values(sort_columns, kind="stable")
    return result.reset_index(drop=True)
