from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ausl_readiness import aggregate_game_day_readiness


NOW = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)


def game(*, game_id="9001", status="Scheduled", starts_in_minutes=60):
    return {
        "game_id": game_id,
        "away_team": "Chicago Bandits",
        "home_team": "Carolina Blaze",
        "away_team_code": "CHI",
        "home_team_code": "CAR",
        "status": status,
        "date_time": NOW + timedelta(minutes=starts_in_minutes),
        "source_updated_at": "2026-07-20T17:45:00+00:00",
        "source_name": "Official AUSL Schedule",
    }


def lineup(
    *,
    game_id="9001",
    source="official",
    revision=3,
    stale=False,
    valid=True,
):
    provenance = {
        "verified": True,
        "source_name": "Official lineup card",
        "source_id": "game-9001-card",
        "verified_at": "2026-07-20T17:50:00+00:00",
        "verified_by": "Fixture Producer",
    }
    return {
        "game_id": game_id,
        "source": source,
        "revision": revision,
        "locked_at": "2026-07-20T17:50:00+00:00",
        "validation_state": "valid" if valid else "invalid",
        "stale": stale,
        "official_provenance": provenance if source == "official" else {},
        "lineups": {
            side: {
                "lineup": [
                    {
                        "player_id": f"{side}-{order}",
                        "player_name": f"{side.title()} Player {order}",
                        "batting_order": order,
                    }
                    for order in range(1, 10)
                ],
                "starting_pitcher": f"{side.title()} Pitcher",
                "warnings": [],
            }
            for side in ("away", "home")
        },
    }


def packet(*, game_id="9001", lineup_revision=3):
    return {
        "game_id": game_id,
        "generated_at": "2026-07-20T17:55:00+00:00",
        "lineup_revision": lineup_revision,
        "lineup_source": "official",
    }


def live(*, state="connected", game_id="9001"):
    return {
        "state": state,
        "game_id": game_id,
        "last_updated": "2026-07-20T17:59:30+00:00",
        "age_seconds": 30,
        "auto_refresh": True,
    }


def readiness(**overrides):
    values = {
        "selected_game": game(),
        "data_health_state": "green",
        "data_health_detail": "All core sources validated",
        "refresh_attempt": {"state": "succeeded"},
        "rosters_available": True,
        "lineup_lock": lineup(),
        "live_feed": live(),
        "verification_count": 0,
        "packet": packet(),
        "offline_mode": False,
        "now": NOW,
    }
    values.update(overrides)
    return aggregate_game_day_readiness(**values)


def by_key(result, key):
    return next(check for check in result.checks if check.key == key)


def test_no_game_selected_is_blocking_and_never_ready():
    result = readiness(selected_game=None, lineup_lock=None, packet=None, live_feed=None)

    assert result.overall_state == "not-ready"
    assert result.selected_game_id == ""
    assert by_key(result, "selected_game").state == "fail"
    assert by_key(result, "selected_game").blocking is True


def test_healthy_scheduled_game_with_no_lineup_is_not_ready():
    result = readiness(lineup_lock=None, packet=None)

    assert result.overall_state == "not-ready"
    assert by_key(result, "lineups").state == "fail"
    assert "not saved" in by_key(result, "lineups").detail.lower()


@pytest.mark.parametrize("source", ["projected", "manual", "imported"])
def test_nonofficial_saved_lineups_remain_warnings(source):
    result = readiness(lineup_lock=lineup(source=source), packet=packet())

    check = by_key(result, "lineup_provenance")
    assert result.overall_state == "needs-attention"
    assert check.state == "warning"
    assert source in check.detail.lower()
    assert "official" not in check.detail.lower() or "not official" in check.detail.lower()


def test_current_official_lineups_can_pass_only_with_complete_provenance():
    result = readiness()

    assert by_key(result, "lineups").state == "pass"
    assert by_key(result, "lineup_provenance").state == "pass"
    assert result.overall_state == "ready"

    incomplete = lineup()
    incomplete["official_provenance"] = {"verified": True}
    result = readiness(lineup_lock=incomplete)
    assert by_key(result, "lineup_provenance").state == "fail"
    assert result.overall_state == "not-ready"


def test_stale_and_wrong_game_lineups_fail_closed():
    stale = readiness(lineup_lock=lineup(stale=True))
    wrong = readiness(lineup_lock=lineup(game_id="9002"))

    assert by_key(stale, "lineups").state == "fail"
    assert by_key(wrong, "lineups").state == "fail"
    assert "9002" in by_key(wrong, "lineups").detail
    assert stale.overall_state == wrong.overall_state == "not-ready"


@pytest.mark.parametrize(
    ("health", "expected_check", "expected_overall"),
    [
        ("green", "pass", "ready"),
        ("yellow", "warning", "needs-attention"),
        ("red", "fail", "not-ready"),
        ("unknown", "unavailable", "not-ready"),
    ],
)
def test_data_health_states_never_treat_unknown_as_pass(
    health, expected_check, expected_overall
):
    result = readiness(data_health_state=health)

    assert by_key(result, "core_data").state == expected_check
    assert result.overall_state == expected_overall


def test_latest_refresh_failure_warns_while_valid_snapshot_remains_usable():
    result = readiness(
        refresh_attempt={
            "state": "failed",
            "affected_source": "official_core_sources",
            "error_summary": "standings timeout",
        }
    )

    assert by_key(result, "core_data").state == "pass"
    assert by_key(result, "latest_refresh").state == "warning"
    assert "stored snapshot" in by_key(result, "latest_refresh").detail.lower()
    assert result.overall_state == "needs-attention"


def test_pregame_disconnected_feed_warns_but_live_game_feed_failure_blocks():
    pregame = readiness(live_feed=live(state="disconnected"))
    live_game = readiness(
        selected_game=game(status="Live", starts_in_minutes=-20),
        live_feed=live(state="stale"),
    )

    assert by_key(pregame, "live_feed").state == "warning"
    assert pregame.overall_state == "needs-attention"
    assert by_key(live_game, "live_feed").state == "fail"
    assert by_key(live_game, "live_feed").blocking is True
    assert live_game.overall_state == "not-ready"


def test_exact_feed_live_status_outranks_lagging_scheduled_status():
    feed = live(state="stale")
    feed["game_status"] = "Live"

    result = readiness(
        selected_game=game(status="Scheduled"),
        live_feed=feed,
    )

    assert by_key(result, "live_feed").state == "fail"
    assert result.overall_state == "not-ready"


def test_verification_queue_clear_nonclear_and_unavailable_are_honest():
    clear = readiness(verification_count=0)
    nonclear = readiness(verification_count=2)
    unavailable = readiness(verification_count=None)

    assert by_key(clear, "verification_queue").state == "pass"
    assert by_key(nonclear, "verification_queue").state == "warning"
    assert by_key(unavailable, "verification_queue").state == "unavailable"
    assert "unavailable" in by_key(unavailable, "verification_queue").detail.lower()


def test_missing_or_outdated_packet_warns_and_exact_revision_passes():
    missing = readiness(packet=None)
    wrong_game = readiness(packet=packet(game_id="9002"))
    old_revision = readiness(packet=packet(lineup_revision=2))
    current = readiness()

    assert by_key(missing, "producer_packet").state == "warning"
    assert by_key(wrong_game, "producer_packet").state == "warning"
    assert by_key(old_revision, "producer_packet").state == "warning"
    assert by_key(current, "producer_packet").state == "pass"


def test_offline_mode_is_visible_warning_and_does_not_force_green():
    result = readiness(offline_mode=True, live_feed={**live(), "state": "disabled"})

    assert by_key(result, "network_permission").state == "warning"
    assert "local/offline" in by_key(result, "network_permission").detail.lower()
    assert result.overall_state == "needs-attention"


def test_multiple_warnings_are_counted_and_blocking_failure_always_wins():
    warnings = readiness(
        lineup_lock=lineup(source="projected"),
        packet=None,
        live_feed=live(state="disconnected"),
        offline_mode=True,
        verification_count=3,
    )
    blocked = readiness(
        data_health_state="red",
        lineup_lock=lineup(source="projected"),
        packet=None,
        offline_mode=True,
    )

    assert warnings.warning_count >= 5
    assert warnings.overall_state == "needs-attention"
    assert blocked.blocking_issue_count >= 1
    assert blocked.overall_state == "not-ready"


def test_check_order_and_generated_time_are_stable():
    result = readiness()

    assert [check.key for check in result.checks] == [
        "selected_game",
        "core_data",
        "latest_refresh",
        "rosters",
        "lineups",
        "lineup_provenance",
        "verification_queue",
        "producer_packet",
        "live_feed",
        "network_permission",
    ]
    assert result.generated_at == NOW


def test_session_save_warning_and_unresolved_restore_are_honest():
    warning = readiness(
        session_issue={
            "state": "warning",
            "detail": "Producer session is not saved: disk full.",
            "blocking": False,
        }
    )
    assert by_key(warning, "producer_session").state == "warning"
    assert warning.overall_state == "needs-attention"

    blocked = readiness(
        session_issue={
            "state": "fail",
            "detail": "Saved Game 1042 does not match the installed schedule.",
            "blocking": True,
        }
    )
    assert by_key(blocked, "producer_session").state == "fail"
    assert blocked.overall_state == "not-ready"
