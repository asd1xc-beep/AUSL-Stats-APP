"""Pure Phase 6A game-day readiness policy.

The Tkinter dashboard renders these results; it must not independently decide
whether a game is ready.  Inputs are deliberately small mappings/dataclasses so
later fact cards can contribute checks without depending on GUI widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


CHECK_STATES = frozenset(
    {"pass", "warning", "fail", "unavailable", "not-applicable"}
)
OVERALL_STATES = frozenset({"ready", "needs-attention", "not-ready"})


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    label: str
    state: str
    detail: str
    blocking: bool
    timestamp: str | None = None
    source_id: str | None = None

    def __post_init__(self):
        if self.state not in CHECK_STATES:
            raise ValueError(f"Unsupported readiness check state: {self.state}")
        if not self.key.strip() or not self.label.strip() or not self.detail.strip():
            raise ValueError("Readiness checks require a key, label, and detail")


@dataclass(frozen=True)
class GameDayReadiness:
    overall_state: str
    selected_game_id: str
    checks: tuple[ReadinessCheck, ...]
    blocking_issue_count: int
    warning_count: int
    generated_at: datetime

    def __post_init__(self):
        if self.overall_state not in OVERALL_STATES:
            raise ValueError(f"Unsupported overall readiness state: {self.overall_state}")
        if self.generated_at.tzinfo is None:
            raise ValueError("Readiness generation time must be timezone-aware")


def _field(value: Any, key: str, default=None):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _iso_timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    rendered = _text(value)
    return rendered or None


def _official_lineup_provenance_valid(lineup_lock: Any) -> bool:
    if _text(_field(lineup_lock, "source")).casefold() != "official":
        return False
    provenance = _field(lineup_lock, "official_provenance", {})
    if not isinstance(provenance, Mapping) or provenance.get("verified") is not True:
        return False
    return all(
        _text(provenance.get(key))
        for key in ("source_name", "source_id", "verified_at", "verified_by")
    )


def _lineup_structure_valid(lineup_lock: Any) -> tuple[bool, str]:
    if not isinstance(lineup_lock, Mapping):
        return False, "Lineups are not saved for this official game."
    if _text(lineup_lock.get("validation_state")).casefold() == "invalid":
        return False, "Saved lineup validation is invalid."
    lineups = lineup_lock.get("lineups")
    if not isinstance(lineups, Mapping):
        return False, "Saved lineup data is unavailable."
    for side in ("away", "home"):
        team = lineups.get(side)
        if not isinstance(team, Mapping):
            return False, f"{side.title()} lineup is unavailable."
        entries = team.get("lineup")
        if not isinstance(entries, list) or len(entries) != 9:
            return False, f"{side.title()} batting order is not a validated 1-through-9 lineup."
        orders = {
            _text(_field(item, "batting_order"))
            for item in entries
            if isinstance(item, Mapping)
        }
        identities = {
            _text(_field(item, "player_id"))
            for item in entries
            if isinstance(item, Mapping)
        }
        if orders != {str(item) for item in range(1, 10)} or len(identities) != 9 or "" in identities:
            return False, f"{side.title()} lineup identities or batting order are unresolved."
        if not _text(team.get("starting_pitcher")):
            return False, f"{side.title()} starting pitcher is unavailable."
    stale = bool(lineup_lock.get("stale"))
    warnings: list[str] = []
    for side in ("away", "home"):
        team_warnings = lineups.get(side, {}).get("warnings", [])
        if isinstance(team_warnings, list):
            warnings.extend(_text(item) for item in team_warnings)
    if stale or any("stale" in item.casefold() for item in warnings):
        return False, "Saved lineup is stale; revalidate it against the current game card."
    return True, "Both lineups have validated player identity, order, and starters."


def _game_is_live(selected_game: Any) -> bool:
    status = _text(_field(selected_game, "status")).casefold().replace("_", " ")
    return status in {
        "live",
        "in progress",
        "in-progress",
        "active",
        "started",
    }


def _game_is_complete(selected_game: Any) -> bool:
    status = _text(_field(selected_game, "status")).casefold()
    return status in {"final", "complete", "completed", "cancelled", "canceled"}


def aggregate_game_day_readiness(
    *,
    selected_game: Any,
    data_health_state: str,
    data_health_detail: str,
    refresh_attempt: Mapping[str, Any] | None,
    rosters_available: bool | None,
    lineup_lock: Mapping[str, Any] | None,
    live_feed: Mapping[str, Any] | None,
    verification_count: int | None,
    packet: Mapping[str, Any] | None,
    offline_mode: bool,
    now: datetime | None = None,
    session_issue: Mapping[str, Any] | None = None,
    change_issue: Mapping[str, Any] | None = None,
) -> GameDayReadiness:
    """Aggregate one exact game's current operational readiness.

    Unknown input never becomes a pass.  A blocking check only blocks when its
    state is ``fail`` or ``unavailable``; warnings remain visible and produce
    ``needs-attention``.
    """

    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("Readiness generation time must be timezone-aware")

    checks: list[ReadinessCheck] = []
    game_id = _text(_field(selected_game, "game_id"))
    if not selected_game or not game_id:
        checks.append(
            ReadinessCheck(
                "selected_game",
                "Official game selected",
                "fail",
                "No exact official game is selected. Open Game Setup and select one.",
                True,
            )
        )
    else:
        away = _text(_field(selected_game, "away_team")) or "Away team unavailable"
        home = _text(_field(selected_game, "home_team")) or "Home team unavailable"
        checks.append(
            ReadinessCheck(
                "selected_game",
                "Official game selected",
                "pass",
                f"Official Game {game_id}: {away} at {home}.",
                True,
                _iso_timestamp(_field(selected_game, "source_updated_at")),
                _text(_field(selected_game, "source_name")) or None,
            )
        )

    health = _text(data_health_state).casefold()
    health_detail = _text(data_health_detail) or "Source-health detail unavailable."
    if health == "green":
        core_state, core_detail = "pass", f"Installed snapshot is valid: {health_detail}"
    elif health == "yellow":
        core_state, core_detail = "warning", f"Installed snapshot is usable with warnings: {health_detail}"
    elif health == "red":
        core_state, core_detail = "fail", f"Core data is not safe for air: {health_detail}"
    else:
        core_state, core_detail = "unavailable", "Core data health is unknown; it cannot be treated as valid."
    checks.append(
        ReadinessCheck(
            "core_data",
            "Core data healthy",
            core_state,
            core_detail,
            True,
        )
    )

    attempt_state = _text(_field(refresh_attempt, "state")).casefold()
    attempt_timestamp = _iso_timestamp(
        _field(refresh_attempt, "completed_at") or _field(refresh_attempt, "started_at")
    )
    if attempt_state == "succeeded":
        attempt_check = ReadinessCheck(
            "latest_refresh",
            "Latest refresh attempt",
            "pass",
            "Latest refresh succeeded and the installed snapshot remains active.",
            False,
            attempt_timestamp,
            _text(_field(refresh_attempt, "affected_source")) or None,
        )
    elif attempt_state == "failed":
        source = _text(_field(refresh_attempt, "affected_source")) or "refresh source"
        error = _text(_field(refresh_attempt, "error_summary")) or "error detail unavailable"
        attempt_check = ReadinessCheck(
            "latest_refresh",
            "Latest refresh attempt",
            "warning",
            f"Stored snapshot remains valid; latest refresh failed for {source}: {error}",
            False,
            attempt_timestamp,
            source,
        )
    elif attempt_state == "cancelled":
        attempt_check = ReadinessCheck(
            "latest_refresh",
            "Latest refresh attempt",
            "warning",
            "Latest refresh was cancelled; the installed snapshot was not changed.",
            False,
            attempt_timestamp,
            _text(_field(refresh_attempt, "affected_source")) or None,
        )
    elif attempt_state == "in_progress":
        attempt_check = ReadinessCheck(
            "latest_refresh",
            "Latest refresh attempt",
            "warning",
            "Refresh is in progress; the installed snapshot remains active.",
            False,
            attempt_timestamp,
            _text(_field(refresh_attempt, "affected_source")) or None,
        )
    else:
        attempt_check = ReadinessCheck(
            "latest_refresh",
            "Latest refresh attempt",
            "unavailable",
            "Latest refresh-attempt outcome is unavailable.",
            False,
        )
    checks.append(attempt_check)

    if rosters_available is True:
        roster_check = ReadinessCheck(
            "rosters",
            "Rosters confirmed",
            "pass",
            "Both selected-game teams resolve to the installed official roster snapshot.",
            True,
        )
    elif rosters_available is False:
        roster_check = ReadinessCheck(
            "rosters",
            "Rosters confirmed",
            "fail",
            "One or both selected-game team rosters are unavailable.",
            True,
        )
    else:
        roster_check = ReadinessCheck(
            "rosters",
            "Rosters confirmed",
            "unavailable",
            "Roster confirmation is unavailable for this game.",
            True,
        )
    checks.append(roster_check)

    lock_game_id = _text(_field(lineup_lock, "game_id"))
    if not game_id:
        lineup_state, lineup_detail = "unavailable", "Lineup readiness requires an exact official game."
    elif not lineup_lock:
        lineup_state, lineup_detail = "fail", f"Lineups are not saved for official Game {game_id}."
    elif lock_game_id != game_id:
        lineup_state, lineup_detail = (
            "fail",
            f"Saved lineup belongs to Game {lock_game_id or 'unknown'}, not selected Game {game_id}.",
        )
    else:
        valid, lineup_detail = _lineup_structure_valid(lineup_lock)
        lineup_state = "pass" if valid else "fail"
    checks.append(
        ReadinessCheck(
            "lineups",
            "Lineups validated and saved",
            lineup_state,
            lineup_detail,
            True,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
            lock_game_id or None,
        )
    )

    source = _text(_field(lineup_lock, "source")).casefold()
    if lineup_state != "pass":
        provenance_check = ReadinessCheck(
            "lineup_provenance",
            "Lineup provenance reviewed",
            "unavailable",
            "Lineup provenance cannot pass until the selected-game lineup is valid.",
            False,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
            source or None,
        )
    elif source == "official" and _official_lineup_provenance_valid(lineup_lock):
        provenance_check = ReadinessCheck(
            "lineup_provenance",
            "Lineup provenance reviewed",
            "pass",
            "Official lineup provenance is complete and verified.",
            True,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
            source,
        )
    elif source == "official":
        provenance_check = ReadinessCheck(
            "lineup_provenance",
            "Lineup provenance reviewed",
            "fail",
            "Official source was claimed without complete authoritative provenance; do not use on air.",
            True,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
            source,
        )
    elif source in {"projected", "manual", "imported"}:
        label = {
            "projected": "Saved projected lineup is not official.",
            "manual": "Saved manual lineup is not official; verify against the official card.",
            "imported": "Saved imported lineup is not official; verify its source.",
        }[source]
        provenance_check = ReadinessCheck(
            "lineup_provenance",
            "Lineup provenance reviewed",
            "warning",
            label,
            False,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
            source,
        )
    else:
        provenance_check = ReadinessCheck(
            "lineup_provenance",
            "Lineup provenance reviewed",
            "unavailable",
            "Lineup source is unavailable; do not describe it as official.",
            True,
            _iso_timestamp(_field(lineup_lock, "locked_at")),
        )
    checks.append(provenance_check)

    if verification_count is None:
        verification_check = ReadinessCheck(
            "verification_queue",
            "Verification queue clear",
            "unavailable",
            "Scoped verification count is unavailable; no zero is inferred.",
            False,
            source_id=game_id or None,
        )
    elif verification_count < 0:
        raise ValueError("Verification count cannot be negative")
    elif verification_count == 0:
        verification_check = ReadinessCheck(
            "verification_queue",
            "Verification queue clear",
            "pass",
            "No unresolved items were found in the selected game/team/player context.",
            False,
            source_id=game_id or None,
        )
    else:
        verification_check = ReadinessCheck(
            "verification_queue",
            "Verification queue clear",
            "warning",
            f"{verification_count} unresolved item(s) remain in the selected-game context.",
            False,
            source_id=game_id or None,
        )
    checks.append(verification_check)

    packet_game_id = _text(_field(packet, "game_id"))
    packet_revision = _field(packet, "lineup_revision")
    lineup_revision = _field(lineup_lock, "revision")
    if not packet:
        packet_state, packet_detail = "warning", "Producer packet has not been generated for this game."
    elif packet_game_id != game_id:
        packet_state, packet_detail = (
            "warning",
            f"Latest packet belongs to Game {packet_game_id or 'unknown'}, not selected Game {game_id or 'unknown'}.",
        )
    elif lineup_revision is not None and packet_revision != lineup_revision:
        packet_state, packet_detail = (
            "warning",
            f"Packet lineup revision {packet_revision if packet_revision is not None else 'none'} "
            f"does not match current revision {lineup_revision}.",
        )
    else:
        packet_state, packet_detail = "pass", f"Producer packet is current for official Game {game_id}."
    checks.append(
        ReadinessCheck(
            "producer_packet",
            "Producer packet current",
            packet_state,
            packet_detail,
            False,
            _iso_timestamp(_field(packet, "generated_at")),
            packet_game_id or None,
        )
    )

    live_state = _text(_field(live_feed, "state")).casefold()
    live_game_id = _text(_field(live_feed, "game_id"))
    live_timestamp = _iso_timestamp(_field(live_feed, "last_updated"))
    live_status_context = {"status": _field(live_feed, "game_status")}
    game_is_live = _game_is_live(selected_game) or _game_is_live(
        live_status_context
    )
    game_is_complete = _game_is_complete(selected_game) or _game_is_complete(
        live_status_context
    )
    if not game_id:
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "not-applicable",
            "Live-feed readiness requires an exact official game.",
            False,
        )
    elif game_is_complete:
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "not-applicable",
            "Selected game is complete; a live connection is not required.",
            False,
            live_timestamp,
            live_game_id or None,
        )
    elif live_game_id and live_game_id != game_id:
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "fail",
            f"Live feed is for Game {live_game_id}, not selected Game {game_id}.",
            True,
            live_timestamp,
            live_game_id,
        )
    elif live_state in {"connected", "current", "green"}:
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "pass",
            f"Exact-game live feed is connected and current for Game {game_id}.",
            game_is_live,
            live_timestamp,
            game_id,
        )
    elif game_is_live:
        detail = {
            "stale": "Exact-game live feed is stale during a live game.",
            "disconnected": "Live feed is disconnected during a live game.",
            "disabled": "Live feed is disabled during a live game.",
            "unavailable": "Live-feed state is unavailable during a live game.",
        }.get(live_state, "A current exact-game live feed is unavailable during a live game.")
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "fail",
            detail,
            True,
            live_timestamp,
            live_game_id or game_id,
        )
    else:
        detail = (
            "Pregame live feed is not connected yet; this does not block scheduled-game preparation."
            if live_state in {"disconnected", "unavailable", "disabled", ""}
            else "Pregame live feed is stale; refresh it when live coverage begins."
        )
        live_check = ReadinessCheck(
            "live_feed",
            "Live feed ready when applicable",
            "warning",
            detail,
            False,
            live_timestamp,
            live_game_id or game_id,
        )
    checks.append(live_check)

    checks.append(
        ReadinessCheck(
            "network_permission",
            "Network requests permitted",
            "warning" if offline_mode else "pass",
            (
                "LOCAL/OFFLINE MODE is enabled; network requests and live timers are blocked."
                if offline_mode
                else "Network requests are permitted; refreshes still start only by producer action."
            ),
            False,
        )
    )

    if session_issue:
        issue_state = _text(session_issue.get("state")).casefold()
        if issue_state not in {"warning", "fail", "unavailable"}:
            issue_state = "unavailable"
        checks.append(
            ReadinessCheck(
                "producer_session",
                "Producer session recovery",
                issue_state,
                _text(session_issue.get("detail"))
                or "Producer-session persistence state is unavailable.",
                bool(session_issue.get("blocking")),
            )
        )

    if change_issue:
        issue_state = _text(change_issue.get("state")).casefold()
        if issue_state not in {"warning", "fail", "unavailable"}:
            issue_state = "unavailable"
        checks.append(
            ReadinessCheck(
                "material_changes",
                "Material changes reviewed",
                issue_state,
                _text(change_issue.get("detail"))
                or "Material-change review state is unavailable.",
                bool(change_issue.get("blocking")),
            )
        )

    blocking_issue_count = sum(
        check.blocking and check.state in {"fail", "unavailable"}
        for check in checks
    )
    warning_count = sum(
        check.state in {"warning", "fail", "unavailable"} for check in checks
    )
    if blocking_issue_count:
        overall = "not-ready"
    elif warning_count:
        overall = "needs-attention"
    else:
        overall = "ready"
    return GameDayReadiness(
        overall_state=overall,
        selected_game_id=game_id,
        checks=tuple(checks),
        blocking_issue_count=blocking_issue_count,
        warning_count=warning_count,
        generated_at=generated_at,
    )


__all__ = [
    "GameDayReadiness",
    "ReadinessCheck",
    "aggregate_game_day_readiness",
]
