from __future__ import annotations

from datetime import datetime, timezone

import pytest

import ausl_stats_app


def game(game_id):
    return ausl_stats_app.SelectedGame(
        game_id=game_id,
        season=2026,
        date_time=datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc),
        away_team="Oklahoma City Spark",
        home_team="Carolina Blaze",
        away_team_code="OKC",
        home_team_code="CAR",
        time_zone="UTC",
        venue="Fixture Stadium",
        status="Scheduled",
        source_updated_at="2026-07-19T12:00:00+00:00",
        source_name="Official AUSL Schedule",
    )


def test_repeat_matchup_packet_names_include_distinct_official_game_ids():
    generated_at = datetime(2026, 7, 19, 22, 30, 45, 123456, tzinfo=timezone.utc)

    first = ausl_stats_app.producer_packet_filename(game("985"), generated_at)
    second = ausl_stats_app.producer_packet_filename(game("987"), generated_at)

    assert "game_985" in first
    assert "game_987" in second
    assert first != second


def test_same_game_packet_names_include_precise_generation_time_and_revision():
    first_time = datetime(2026, 7, 19, 22, 30, 45, 123456, tzinfo=timezone.utc)
    second_time = datetime(2026, 7, 19, 22, 30, 45, 123457, tzinfo=timezone.utc)

    first = ausl_stats_app.producer_packet_filename(game("985"), first_time, revision=2)
    second = ausl_stats_app.producer_packet_filename(game("985"), second_time, revision=2)

    assert "20260719T223045123456Z" in first
    assert "_r2_" in first
    assert first != second


def test_packet_filename_refuses_missing_or_uncertain_game_identity():
    with pytest.raises(ValueError, match="official game"):
        ausl_stats_app.producer_packet_filename(
            None,
            datetime(2026, 7, 19, 22, 30, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="official game"):
        ausl_stats_app.producer_packet_filename(
            game("unknown"),
            datetime(2026, 7, 19, 22, 30, tzinfo=timezone.utc),
        )


def test_app_packet_path_uses_current_game_lock_revision(tmp_path, monkeypatch):
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.selected_game = game("985")
    app.locked_lineups = {
        "schema_version": 2,
        "games": {"985": {"game_id": "985", "revision": 4, "lineups": {}}},
        "legacy_unassigned": [],
    }
    monkeypatch.setattr(ausl_stats_app, "export_dir", lambda: tmp_path)
    generated_at = datetime(2026, 7, 19, 22, 30, 45, 123456, tzinfo=timezone.utc)

    path = app._producer_packet_path(generated_at)

    assert path.parent == tmp_path / "game_packets"
    assert path.name == "20260719T223045123456Z_game_985_r4_producer_packet.txt"


def test_existing_packet_is_never_silently_overwritten(tmp_path):
    path = tmp_path / "packet.txt"
    path.write_bytes(b"original packet")

    with pytest.raises(FileExistsError):
        ausl_stats_app.write_producer_packet_exclusive(path, "replacement packet")

    assert path.read_bytes() == b"original packet"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("projected", "SAVED PROJECTED LINEUP — NOT OFFICIAL"),
        ("manual", "MANUAL LINEUP — VERIFY AGAINST OFFICIAL CARD"),
        ("imported", "IMPORTED LINEUP — VERIFY SOURCE"),
    ],
)
def test_packet_lineup_heading_is_derived_from_stored_source(source, expected):
    lock = {"source": source}

    assert ausl_stats_app.packet_lineup_heading(lock) == expected


def test_official_heading_requires_complete_authoritative_provenance():
    incomplete = {"source": "official", "official_provenance": {"verified": True}}
    complete = {
        "source": "official",
        "official_provenance": {
            "verified": True,
            "source_name": "Official lineup card",
            "source_id": "game-985-card",
            "verified_at": "2026-07-20T18:30:00+00:00",
            "verified_by": "Fixture Producer",
        },
    }

    assert "DO NOT USE ON AIR" in ausl_stats_app.packet_lineup_heading(incomplete)
    assert ausl_stats_app.packet_lineup_heading(complete) == "OFFICIAL STARTING LINEUP"


def test_packet_lineup_renderer_includes_flex_once_without_fabricating_it():
    lineup = [
        {
            "batting_order": order,
            "player_name": f"Hitter {order}",
            "jersey_number": str(order),
            "position": "OF",
            "roster_status": "Active",
        }
        for order in range(1, 10)
    ]
    flex = {
        "player_name": "Flex Player",
        "jersey_number": "22",
        "position": "FLEX",
        "roster_status": "Active",
    }

    with_flex = ausl_stats_app.format_stored_packet_lineup(
        {"lineup": lineup, "flex": flex}
    )
    without_flex = ausl_stats_app.format_stored_packet_lineup(
        {"lineup": lineup, "flex": None}
    )

    assert len(with_flex) == 10
    assert sum("Flex Player" in line for line in with_flex) == 1
    assert with_flex[-1].startswith("FLEX.")
    assert len(without_flex) == 9
    assert all("FLEX." not in line for line in without_flex)
