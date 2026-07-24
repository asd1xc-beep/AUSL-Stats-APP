from __future__ import annotations

from pathlib import Path

import pandas as pd

import ausl_data
import ausl_stats_app


def approved_media_row(row):
    approved = {
        "warnings": "",
        "approval_state": "approved",
        "approval_method": "parser_exact_identity",
        "parser_version": "media-toc-v1",
        **row,
    }
    approved["approval_record_id"] = ausl_data.media_approval_record_id(approved)
    return approved


def test_cleaner_repairs_wrapped_words_and_years_without_changing_names():
    raw = (
        "Kelsey Stewart-Hunter missed the remain- \n"
        "der of the 20 25 season with Sierra Sacco-Ferrie."
    )

    cleaned = ausl_data._clean_media_guide_text(raw)

    assert "remainder" in cleaned
    assert "2025" in cleaned
    assert "remain- der" not in cleaned
    assert "Kelsey Stewart-Hunter" in cleaned
    assert "Sierra Sacco-Ferrie" in cleaned


def test_semantically_duplicate_notes_keep_the_more_specific_category():
    rows = [
        {
            "entity_type": "player",
            "entity_id": 77,
            "note_text": "Named an NFCA All-American in 2025.",
            "note_category": "bio",
            "source_pages": "49-50",
        },
        {
            "entity_type": "player",
            "entity_id": 77,
            "note_text": "Named an NFCA All American in 2025",
            "note_category": "college",
            "source_pages": "50",
        },
    ]

    deduplicated = ausl_data._deduplicate_media_note_rows(rows)

    assert len(deduplicated) == 1
    assert deduplicated[0]["note_category"] == "college"
    assert deduplicated[0]["source_pages"] == "50"


def test_media_audit_has_one_explicit_status_row_per_roster_player(load_fixture):
    fixture = load_fixture("media_guide_toc_identity.json")
    roster = pd.DataFrame(fixture["roster"])
    pages = [
        {**page, "text": ausl_data._clean_media_guide_text(page["raw_text"])}
        for page in fixture["pages"]
    ]
    players, _notes = ausl_data._media_guide_player_frames(
        roster,
        pages,
        imported_at="2026-07-22T12:00:00+00:00",
    )

    audit = ausl_data._media_guide_audit_frame(players)

    assert list(audit.columns) == [
        "player_id",
        "player_name",
        "match_status",
        "expected_printed_pages",
        "parsed_pdf_pages",
        "confidence",
        "note_count",
        "warnings",
        "guide_date",
    ]
    assert len(audit) == len(roster)
    assert audit["player_id"].is_unique
    assert audit["match_status"].value_counts().to_dict() == {
        "verified": 5,
        "not_in_guide": 1,
    }


def test_verified_media_copy_has_visible_verification_and_page_provenance():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(
            [
                approved_media_row({
                    "entity_type": "player",
                    "entity_id": 77,
                    "entity_name": "Fixture Player",
                    "note_text": "Verified fixture biography.",
                    "note_category": "college",
                    "source_name": "2026 AUSL Media Guide",
                    "source_pages": "49-50",
                    "expected_printed_pages": "47-48",
                    "parsed_pdf_pages": "49-50",
                    "guide_date": "2026-06-01",
                    "match_status": "verified",
                    "confidence_score": 0.98,
                    "needs_review": False,
                })
            ]
        ),
        "media_players": pd.DataFrame(),
    }

    lines = app._media_guide_player_lines(77)

    assert len(lines) == 1
    assert "[VERIFIED" in lines[0]
    assert "printed pages 47-48" in lines[0]
    assert "PDF pages 49-50" in lines[0]
    assert "guide date June 1, 2026" in lines[0]


def test_needs_review_media_is_browsable_but_never_air_ready():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(),
        "media_players": pd.DataFrame(
            [
                {
                    "player_id": 77,
                    "player_name": "Review Player",
                    "media_guide_bio": "Review-only fixture biography.",
                    "match_status": "needs_review",
                    "expected_printed_pages": "130",
                    "parsed_pdf_pages": "132",
                    "guide_date": "2026-06-01",
                    "warnings": "Expected player header was not extracted.",
                    "needs_review": True,
                }
            ]
        ),
    }

    assert app._media_guide_player_lines(77) == []
    review_lines = app._media_guide_player_lines(77, include_review=True)
    assert any("[VERIFY]" in line for line in review_lines)
    assert any("Expected player header was not extracted" in line for line in review_lines)
    assert any("printed pages 130" in line and "PDF pages 132" in line for line in review_lines)


def test_not_in_guide_is_visible_only_in_browsable_source_view():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(),
        "media_players": pd.DataFrame(
            [
                {
                    "player_id": 88,
                    "player_name": "New Player",
                    "match_status": "not_in_guide",
                    "guide_date": "2026-06-01",
                    "needs_review": True,
                }
            ]
        ),
    }

    assert app._media_guide_player_lines(88) == []
    lines = app._media_guide_player_lines(88, include_review=True)
    assert lines == [
        "- [NOT IN GUIDE] Not included in the June 1, 2026 media guide; no biography inferred."
    ]


def test_verified_team_media_has_visible_verification_and_guide_date():
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame(
            [
                approved_media_row({
                    "entity_type": "team",
                    "entity_id": "CHI",
                    "entity_name": "Chicago Bandits",
                    "note_text": "Verified fixture team context.",
                    "note_category": "team_context",
                    "source_name": "2026 AUSL Media Guide",
                    "expected_printed_pages": "19-22",
                    "parsed_pdf_pages": "21-24",
                    "guide_date": "2026-06-01",
                    "match_status": "verified",
                    "confidence_score": 0.9,
                    "needs_review": False,
                })
            ]
        ),
        "media_teams": pd.DataFrame(),
    }

    lines = app._media_guide_team_lines("Chicago Bandits")

    assert len(lines) == 1
    assert "[VERIFIED" in lines[0]
    assert "printed pages 19-22" in lines[0]
    assert "PDF pages 21-24" in lines[0]
    assert "guide date June 1, 2026" in lines[0]


def test_valid_enrichment_refresh_writes_and_returns_media_audit(
    monkeypatch, tmp_path
):
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
    monkeypatch.setattr(
        ausl_data,
        "fetch_split_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture skip")),
    )
    monkeypatch.setattr(
        ausl_data, "fetch_official_game_notes_frame", lambda *_args: pd.DataFrame()
    )
    media_frames = (
        pd.DataFrame([{"player_id": 2026}]),
        pd.DataFrame([{"team_code": "CHI"}]),
        pd.DataFrame([{"note_id": "fixture"}]),
        pd.DataFrame([{"chunk_id": "fixture"}]),
        pd.DataFrame([{"player_id": 2026, "match_status": "verified"}]),
    )
    monkeypatch.setattr(
        ausl_data, "fetch_media_guide_frames", lambda *_args: media_frames
    )
    monkeypatch.setattr(ausl_data, "ensure_manual_notes_file", lambda: tmp_path / "manual.csv")

    def fake_write(path, _sheets):
        written.append(Path(path).name)
        path.write_bytes(b"fixture output")

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", fake_write)

    outputs = ausl_data.update_all_data(include_enrichment=True)

    assert "ausl_media_guide_audit.xlsx" in written
    assert outputs["media_audit"] == tmp_path / "ausl_media_guide_audit.xlsx"
