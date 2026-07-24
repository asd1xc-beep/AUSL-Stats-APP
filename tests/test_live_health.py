from __future__ import annotations

from datetime import datetime, timezone

import pytest

import ausl_stats_app


@pytest.mark.parametrize(
    ("last_updated", "expected_state"),
    [
        ("2026-07-20T23:11:30+00:00", "GREEN"),
        ("2026-07-20T23:05:00+00:00", "YELLOW"),
        ("", "RED"),
        ("not-a-time", "RED"),
        ("2026-07-21T01:00:00+00:00", "RED"),
    ],
)
def test_live_health_uses_authoritative_feed_time_and_fails_closed(
    last_updated, expected_state
):
    now = datetime(2026, 7, 20, 23, 12, tzinfo=timezone.utc)

    health = ausl_stats_app.live_feed_health(
        {"lastUpdated": last_updated}, now=now
    )

    assert health.state == expected_state
    if expected_state == "GREEN":
        assert health.connection_state == "CONNECTED"
        assert health.stale is False
    elif expected_state == "YELLOW":
        assert health.connection_state == "CONNECTED"
        assert health.stale is True
    else:
        assert health.stale is None


def test_live_comparison_displays_same_authoritative_freshness_state(load_fixture):
    fixture = load_fixture("live_box_response.json")
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.live_game = fixture["game"]
    app.live_box = fixture["box"]
    app.live_health = ausl_stats_app.live_feed_health(
        fixture["game"],
        now=datetime(2026, 7, 20, 23, 12, 30, tzinfo=timezone.utc),
    )

    rendered = app.format_live_comparison()

    assert "[GREEN | CONNECTED | CURRENT]" in rendered
    assert "2026-07-20T23:12:00+00:00" in rendered


def test_missing_feed_timestamp_is_never_labeled_current(load_fixture):
    fixture = load_fixture("live_box_response.json")
    game = {key: value for key, value in fixture["game"].items() if key != "lastUpdated"}
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.live_game = game
    app.live_box = fixture["box"]

    rendered = app.format_live_comparison()

    assert "[RED | CONNECTED | UPDATE TIME UNAVAILABLE]" in rendered
    assert "CURRENT" not in rendered
