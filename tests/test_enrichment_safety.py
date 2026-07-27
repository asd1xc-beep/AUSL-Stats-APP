from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import ausl_data
import ausl_stats_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAFETY_ROWS = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "enrichment_safety_rows.json").read_text(
        encoding="utf-8"
    )
)
for group_name, entity_name in (
    ("media_player", "Fixture Player"),
    ("media_team", "Chicago Bandits"),
):
    for fixture_row in SAFETY_ROWS[group_name]:
        if fixture_row.get("needs_review") is False:
            fixture_row.update(
                {
                    "entity_name": entity_name,
                    "expected_printed_pages": fixture_row["source_pages"],
                    "parsed_pdf_pages": fixture_row["source_pages"],
                    "guide_date": "2026-06-01",
                    "match_status": "verified",
                    "warnings": "",
                    "approval_state": "approved",
                    "approval_method": "parser_exact_identity",
                    "parser_version": "media-toc-v1",
                }
            )
            fixture_row["approval_record_id"] = (
                ausl_data.media_approval_record_id(fixture_row)
            )


def test_core_refresh_neither_fetches_nor_writes_optional_enrichment(monkeypatch, tmp_path):
    calls = []
    written = []

    monkeypatch.setattr(ausl_data, "export_dir", lambda: tmp_path)
    monkeypatch.setattr(ausl_data, "_get_json", lambda _path: {})
    monkeypatch.setattr(
        ausl_data,
        "roster_frame",
        lambda _payload, year: pd.DataFrame(
            [{"season": year, "player_id": year, "player_name": f"Player {year}"}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "stat_frames",
        lambda _payload, year: tuple(
            pd.DataFrame([{"player_id": year}]) for _ in range(3)
        ),
    )
    monkeypatch.setattr(ausl_data, "career_batting", lambda _frames: pd.DataFrame())
    monkeypatch.setattr(ausl_data, "career_pitching", lambda _frames: pd.DataFrame())
    monkeypatch.setattr(ausl_data, "career_fielding", lambda _frames: pd.DataFrame())
    monkeypatch.setattr(
        ausl_data,
        "fetch_standings_frame",
        lambda: pd.DataFrame(
            [{"team_code": "CHI", "seasonId": 369, "standingsTypeLk": "SEASON"}]
        ),
    )
    monkeypatch.setattr(
        ausl_data,
        "fetch_schedule_frame",
        lambda: pd.DataFrame(
            [
                {
                    "game_id": 9001,
                    "game_date": "2026-07-20T19:00:00-04:00",
                    "away_team_code": "CHI",
                    "home_team_code": "CAR",
                    "status": "scheduled",
                }
            ]
        ),
    )
    monkeypatch.setattr(ausl_data, "ensure_manual_notes_file", lambda: tmp_path / "manual.csv")

    def optional_call(name):
        def called(*_args, **_kwargs):
            calls.append(name)
            raise RuntimeError(f"{name} must not run during a core refresh")

        return called

    monkeypatch.setattr(ausl_data, "fetch_split_payload", optional_call("splits"))
    monkeypatch.setattr(
        ausl_data, "fetch_official_game_notes_frame", optional_call("game_notes")
    )
    monkeypatch.setattr(
        ausl_data, "fetch_media_guide_frames", optional_call("media_guide")
    )

    def fake_write(path, _sheets):
        written.append(path.name)
        path.write_bytes(b"fixture workbook")

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", fake_write)

    outputs = ausl_data.update_all_data()

    assert calls == []
    assert set(written) == {
        "ausl_rosters.xlsx",
        "ausl_season_stats.xlsx",
        "ausl_career_stats.xlsx",
        "ausl_team_context.xlsx",
    }
    assert set(outputs) == {
        "rosters",
        "season",
        "career",
        "team_context",
        "manifest",
        "refresh_attempt",
    }
    manifest = json.loads((tmp_path / "update_manifest.json").read_text(encoding="utf-8"))
    assert manifest["enrichment_enabled"] is False
    assert manifest["enrichment_sources"] == []
    assert manifest["normalizations"]["season_pitching_whip"] == {
        "method": "(hitsAllowed + baseOnBalls) * 3 / innings_outs",
        "source_field_retained_as": "source_whip",
        "applied_at": "2026-07-19",
        "failure_policy": "unavailable",
    }


def test_default_loader_does_not_activate_unapproved_optional_workbook(
    monkeypatch, tmp_path
):
    for filename in (
        "ausl_rosters.xlsx",
        "ausl_season_stats.xlsx",
        "ausl_career_stats.xlsx",
        "ausl_team_context.xlsx",
        "clean_media_guide_notes.xlsx",
        "official_game_notes.xlsx",
        "ausl_pitching_splits.xlsx",
    ):
        (tmp_path / filename).write_bytes(b"fixture")
    (tmp_path / "update_manifest.json").write_text(
        json.dumps({"updated_at": "fixture", "enrichment_enabled": False}),
        encoding="utf-8",
    )
    read_calls = []

    def fake_read_excel(path, sheet_name):
        read_calls.append((Path(path).name, sheet_name))
        if sheet_name.startswith("roster_"):
            return pd.DataFrame([{"player_id": 1}])
        return pd.DataFrame()

    monkeypatch.setattr(ausl_data, "export_dir", lambda: tmp_path)
    monkeypatch.setattr(pd, "read_excel", fake_read_excel)
    monkeypatch.setattr(ausl_data, "load_manual_notes", lambda: pd.DataFrame())

    database = ausl_data.load_database()

    assert database["enrichment_enabled"] is False
    assert database["clean_media_notes"].empty
    assert database["official_game_notes"].empty
    assert database["pitching_splits"].empty
    assert not any(name == "clean_media_guide_notes.xlsx" for name, _ in read_calls)
    assert not any(name == "official_game_notes.xlsx" for name, _ in read_calls)
    assert not any(name == "ausl_pitching_splits.xlsx" for name, _ in read_calls)


def test_needs_review_rows_never_reach_media_or_game_note_output():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(
            SAFETY_ROWS["media_player"] + SAFETY_ROWS["media_team"]
        ),
        "media_players": pd.DataFrame(),
        "media_teams": pd.DataFrame(),
        "official_game_notes": pd.DataFrame(SAFETY_ROWS["official_game_notes"]),
    }
    app.selected_game = ausl_stats_app.SelectedGame(
        game_id="999",
        season=2026,
        date_time=datetime(2026, 7, 19, 19, 0, tzinfo=timezone.utc),
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        away_team_code="CHI",
        home_team_code="CAR",
        time_zone="UTC",
        venue="Fixture Stadium",
        status="Scheduled",
        source_updated_at="2026-07-19T12:00:00+00:00",
        source_name="Official AUSL Schedule",
    )

    player_lines = app._media_guide_player_lines(77)
    team_lines = app._media_guide_team_lines("Chicago Bandits")
    game_lines = app._official_game_note_lines("Chicago Bandits", "Carolina Blaze")

    assert len(player_lines) == 1
    assert "Verified short player note" in player_lines[0]
    assert len(team_lines) == 1
    assert "Verified short team note" in team_lines[0]
    assert len(game_lines) == 2
    assert "Verified exact-game note" in game_lines[0]
    assert "No verified official-note candidate" in game_lines[1]
    combined = "\n".join(player_lines + team_lines + game_lines)
    assert "Unverified" not in combined


def test_rows_without_review_state_fail_closed():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(
            [
                {
                    "entity_type": "player",
                    "entity_id": 77,
                    "note_text": "Approval state omitted.",
                }
            ]
        ),
        "media_players": pd.DataFrame(),
    }

    assert app._media_guide_player_lines(77) == []
