from __future__ import annotations

import pandas as pd
import pytest

import ausl_data


def fixture_frames(load_fixture):
    fixture = load_fixture("media_guide_toc_identity.json")
    roster = pd.DataFrame(fixture["roster"])
    pages = [
        {
            **page,
            "text": ausl_data._clean_media_guide_text(page["raw_text"]),
        }
        for page in fixture["pages"]
    ]
    return fixture, roster, pages


def row_for(frame, player_name):
    rows = frame[frame["player_name"].eq(player_name)]
    assert len(rows) == 1
    return rows.iloc[0]


def test_toc_mapping_uses_verified_offset_and_exact_page_ranges(load_fixture):
    fixture, roster, pages = fixture_frames(load_fixture)

    players, notes = ausl_data._media_guide_player_frames(
        roster,
        pages,
        imported_at="2026-07-22T12:00:00+00:00",
    )

    assert len(players) == len(roster)
    assert set(players["match_status"]) == {"verified", "not_in_guide"}
    for name, printed_pages, pdf_pages in (
        ("Morgan Zerkle", "47-48", "49-50"),
        ("Sydney Romero", "141-142", "143-144"),
        ("Rachel Garcia", "204-206", "206-208"),
        ("Mariah Mazon", "241-242", "243-244"),
        ("Elise Sokolsky", "251", "253"),
    ):
        row = row_for(players, name)
        assert row["expected_printed_pages"] == printed_pages
        assert row["parsed_pdf_pages"] == pdf_pages
        assert row["pdf_page_offset"] == fixture["expected_pdf_offset"]
        assert row["guide_date"] == fixture["guide_date"]
        assert row["match_status"] == "verified"
        assert row["needs_review"] is False or row["needs_review"] == False
        assert row["confidence_score"] >= 0.9

    assert not notes.empty
    assert set(notes["match_status"]) == {"verified"}
    assert set(notes["guide_date"]) == {fixture["guide_date"]}
    assert set(notes["approval_state"]) == {"approved"}
    assert set(notes["approval_method"]) == {"parser_exact_identity"}
    assert all(
        row["approval_record_id"] == ausl_data.media_approval_record_id(row)
        for _, row in notes.iterrows()
    )


def test_mentions_on_later_players_pages_never_override_toc_identity(load_fixture):
    _fixture, roster, pages = fixture_frames(load_fixture)

    players, _notes = ausl_data._media_guide_player_frames(
        roster,
        pages,
        imported_at="2026-07-22T12:00:00+00:00",
    )

    sydney = row_for(players, "Sydney Romero")
    assert "Sydney biography first page marker" in sydney["media_guide_bio"]
    assert "Elise biography marker" not in sydney["media_guide_bio"]

    morgan = row_for(players, "Morgan Zerkle")
    assert "Morgan biography first page marker" in morgan["media_guide_bio"]
    assert "Elise biography marker" not in morgan["media_guide_bio"]

    rachel = row_for(players, "Rachel Garcia")
    assert "Rachel biography first page marker" in rachel["media_guide_bio"]
    assert "Mariah biography marker" not in rachel["media_guide_bio"]


def test_multi_page_player_merges_every_page_in_printed_order(load_fixture):
    _fixture, roster, pages = fixture_frames(load_fixture)

    players, _notes = ausl_data._media_guide_player_frames(
        roster,
        pages,
        imported_at="2026-07-22T12:00:00+00:00",
    )

    morgan = row_for(players, "Morgan Zerkle")
    bio = morgan["media_guide_bio"]
    assert "first page marker" in bio
    assert "second page marker" in bio
    assert bio.index("first page marker") < bio.index("second page marker")


def test_player_absent_from_toc_is_explicit_and_has_no_inferred_biography(load_fixture):
    fixture, roster, pages = fixture_frames(load_fixture)
    pages.append(
        {
            "page": 260,
            "raw_text": "A teammate mentions Reese Newcomer in an unrelated biography.",
            "text": "A teammate mentions Reese Newcomer in an unrelated biography.",
        }
    )

    players, notes = ausl_data._media_guide_player_frames(
        roster,
        pages,
        imported_at="2026-07-22T12:00:00+00:00",
    )

    newcomer = row_for(players, "Reese Newcomer")
    assert newcomer["match_status"] == "not_in_guide"
    assert newcomer["guide_date"] == fixture["guide_date"]
    assert newcomer["media_guide_bio"] == ""
    assert newcomer["expected_printed_pages"] == ""
    assert newcomer["parsed_pdf_pages"] == ""
    assert newcomer["needs_review"] is True or newcomer["needs_review"] == True
    assert not notes[notes["entity_id"].eq(1006)].shape[0]


def test_unverifiable_page_offset_fails_closed(load_fixture):
    _fixture, roster, pages = fixture_frames(load_fixture)
    for page in pages:
        if page["page"] != 3:
            page["raw_text"] = "Unrelated page without the expected player header."
            page["text"] = page["raw_text"]

    with pytest.raises(ausl_data.MediaGuideValidationError, match="offset"):
        ausl_data._media_guide_player_frames(
            roster,
            pages,
            imported_at="2026-07-22T12:00:00+00:00",
        )


def test_failed_media_validation_preserves_last_known_good_workbooks(
    monkeypatch, tmp_path
):
    media_files = {
        "ausl_media_guide_audit.xlsx",
        "ausl_media_guide_players.xlsx",
        "ausl_media_guide_teams.xlsx",
        "ausl_media_guide_notes.xlsx",
        "clean_media_guide_notes.xlsx",
        "ausl_media_guide_raw_chunks.xlsx",
    }
    prior_bytes = b"verified media fixture"
    for filename in media_files:
        (tmp_path / filename).write_bytes(prior_bytes)

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
    monkeypatch.setattr(
        ausl_data,
        "fetch_media_guide_frames",
        lambda *_args: (_ for _ in ()).throw(
            ausl_data.MediaGuideValidationError("fixture offset failure")
        ),
    )
    monkeypatch.setattr(ausl_data, "ensure_manual_notes_file", lambda: tmp_path / "manual.csv")

    def fake_write(path, _sheets):
        path.write_bytes(b"new output")

    monkeypatch.setattr(ausl_data, "_write_excel_atomic", fake_write)

    outputs = ausl_data.update_all_data(include_enrichment=True)

    for filename in media_files:
        assert (tmp_path / filename).read_bytes() == prior_bytes
    assert not {
        "media_players",
        "media_teams",
        "media_notes",
        "clean_media_notes",
        "raw_media_chunks",
        "media_audit",
    }.intersection(outputs)
