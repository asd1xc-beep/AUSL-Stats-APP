from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import ausl_data
from ausl_enrichment import (
    EnrichmentMode,
    approve_official_note_row,
    approved_enrichment_frames,
    official_note_approval_record_id,
)
from ausl_facts import VerificationState, build_selected_game_facts


def _health(status="green"):
    return {
        "source_health": {
            "official_game_notes": {"status": status},
            "media_guide": {"status": status},
            "split_stats": {"status": status},
        }
    }


def _roster():
    return pd.DataFrame(
        [
            {
                "player_id": 101,
                "player_name": "Ada Active",
                "team_code": "CHI",
                "team": "Chicago Bandits",
                "roster_status": "Active",
            }
        ]
    )


def _approved_note():
    row = {
        "game_id": 9001,
        "source_game_id": 9001,
        "game_date": "2026-07-20",
        "source_date": "2026-07-20",
        "team_codes": "CHI,CAR",
        "subject_player_id": "101",
        "subject_player_name": "Ada Active",
        "subject_team_code": "CHI",
        "opposing_team_code": "CAR",
        "note_text": "Ada Active has reached 50 career AUSL hits.",
        "note_category": "milestone_reached",
        "source_url": "https://theausl.com/notes/9001.pdf",
        "source_pdf": "9001.pdf",
        "source_page": 4,
        "parser_version": "official-game-notes-v1",
        "normalized_hash": ausl_data._normalized_game_note_hash(
            "Ada Active has reached 50 career AUSL hits."
        ),
        "verification_state": "VERIFIED",
        "needs_review": False,
        "approval_state": "approved",
        "approval_method": "manual_review",
        "approved_by": "Fixture Producer",
        "approved_at": "2026-07-20T18:00:00+00:00",
    }
    row["approval_record_id"] = official_note_approval_record_id(row)
    return row


def _approved_media():
    row = {
        "entity_type": "player",
        "entity_id": 101,
        "player_id": 101,
        "entity_name": "Ada Active",
        "player_name": "Ada Active",
        "team_code": "CHI",
        "note_category": "bio",
        "note_text": "Approved fixture biography.",
        "media_guide_bio": "Approved fixture biography.",
        "source_name": "2026 AUSL Media Guide",
        "source_url": "https://theausl.com/media-guide.pdf",
        "expected_printed_pages": "47-48",
        "parsed_pdf_pages": "49-50",
        "guide_date": "2026-06-01",
        "match_status": "verified",
        "confidence_score": 0.98,
        "needs_review": False,
        "warnings": "",
        "approval_state": "approved",
        "approval_method": "parser_exact_identity",
        "parser_version": "media-toc-v1",
    }
    row["approval_record_id"] = ausl_data.media_approval_record_id(row)
    return row


def _raw_frames():
    note = _approved_note()
    unsafe_note = copy.deepcopy(note)
    unsafe_note["source_page"] = ""
    media = _approved_media()
    unsafe_media = copy.deepcopy(media)
    unsafe_media["warnings"] = "Teammate identity is ambiguous."
    return {
        "official_game_notes": pd.DataFrame([note, unsafe_note]),
        "media_players": pd.DataFrame([media, unsafe_media]),
        "media_notes": pd.DataFrame([media, unsafe_media]),
        "media_teams": pd.DataFrame(),
        "media_audit": pd.DataFrame(),
        "clean_media_notes": pd.DataFrame([media, unsafe_media]),
        "batting_splits": pd.DataFrame(
            [
                {
                    "player_id": 101,
                    "season": 2026,
                    "split_key": "last7Days",
                    "split_label": "Last 7 Days",
                    "plateAppearances": 12,
                },
                {
                    "player_id": 101,
                    "season": 2026,
                    "split_key": "regularSeason",
                    "split_label": "Regular Season",
                    "plateAppearances": 80,
                },
            ]
        ),
        "pitching_splits": pd.DataFrame(),
        "fielding_splits": pd.DataFrame(),
        "storyline_sources": pd.DataFrame(),
        "raw_media_chunks": pd.DataFrame([{"raw_text": "private review material"}]),
    }


def test_modes_are_typed_and_distinct():
    assert EnrichmentMode.CORE_ONLY is not EnrichmentMode.PRODUCER_APPROVED
    assert EnrichmentMode.PRODUCER_APPROVED is not EnrichmentMode.DEVELOPER_REVIEW


def test_producer_approved_filters_every_row_at_the_load_boundary():
    approved = approved_enrichment_frames(
        _raw_frames(), roster=_roster(), manifest=_health("green")
    )

    assert len(approved["official_game_notes"]) == 1
    assert len(approved["media_players"]) == 1
    assert len(approved["clean_media_notes"]) == 1
    assert len(approved["batting_splits"]) == 1
    assert approved["raw_media_chunks"].empty
    assert approved["official_game_notes"].iloc[0]["producer_air_ready"]
    assert approved["media_players"].iloc[0]["producer_air_ready"]


@pytest.mark.parametrize(
    "field",
    [
        "source_game_id",
        "subject_player_id",
        "subject_team_code",
        "opposing_team_code",
        "source_date",
        "source_url",
        "source_pdf",
        "source_page",
        "parser_version",
        "normalized_hash",
        "approval_record_id",
        "approved_by",
        "approved_at",
    ],
)
def test_official_note_missing_any_required_gate_is_excluded(field):
    frames = _raw_frames()
    note = _approved_note()
    note[field] = ""
    frames["official_game_notes"] = pd.DataFrame([note])

    approved = approved_enrichment_frames(
        frames, roster=_roster(), manifest=_health("green")
    )

    assert approved["official_game_notes"].empty


@pytest.mark.parametrize(
    "field",
    [
        "entity_id",
        "entity_name",
        "source_name",
        "source_url",
        "expected_printed_pages",
        "parsed_pdf_pages",
        "guide_date",
        "parser_version",
        "approval_record_id",
    ],
)
def test_media_missing_any_required_gate_is_excluded(field):
    frames = _raw_frames()
    media = _approved_media()
    media[field] = ""
    frames["media_players"] = pd.DataFrame([media])

    approved = approved_enrichment_frames(
        frames, roster=_roster(), manifest=_health("green")
    )

    assert approved["media_players"].empty


def test_boolean_flip_cannot_promote_note_or_media():
    frames = _raw_frames()
    note = _approved_note()
    note.update(
        {
            "needs_review": False,
            "approval_state": "review_required",
            "approval_record_id": "",
        }
    )
    media = _approved_media()
    media.update(
        {
            "needs_review": False,
            "match_status": "needs_review",
            "approval_record_id": "",
        }
    )
    frames["official_game_notes"] = pd.DataFrame([note])
    frames["media_players"] = pd.DataFrame([media])

    approved = approved_enrichment_frames(
        frames, roster=_roster(), manifest=_health("green")
    )

    assert approved["official_game_notes"].empty
    assert approved["media_players"].empty


def test_official_note_approval_transaction_binds_reviewer_and_evidence():
    draft = _approved_note()
    draft.update(
        {
            "verification_state": "VERIFY",
            "needs_review": True,
            "approval_state": "review_required",
            "approval_method": "",
            "approved_by": "",
            "approved_at": "",
            "approval_record_id": "",
        }
    )

    approved = approve_official_note_row(
        draft,
        reviewer="Fixture Producer",
        approved_at="2026-07-20T18:00:00+00:00",
    )

    assert approved["verification_state"] == "VERIFIED"
    assert approved["approved_by"] == "Fixture Producer"
    assert approved["approval_record_id"] == official_note_approval_record_id(
        approved
    )
    tampered = dict(approved, note_text="Changed after approval")
    assert tampered["approval_record_id"] != official_note_approval_record_id(
        tampered
    )


def test_wrong_player_team_or_opponent_identity_fails_closed():
    for field, value in (
        ("subject_player_id", "999"),
        ("subject_team_code", "CAR"),
        ("opposing_team_code", "BOS"),
    ):
        frames = _raw_frames()
        note = _approved_note()
        note[field] = value
        frames["official_game_notes"] = pd.DataFrame([note])
        approved = approved_enrichment_frames(
            frames, roster=_roster(), manifest=_health("green")
        )
        assert approved["official_game_notes"].empty, field


@pytest.mark.parametrize(
    ("status", "expected_air_ready"),
    [("green", True), ("yellow", False), ("red", False), ("unknown", False)],
)
def test_health_never_promotes_unknown_or_aging_enrichment(status, expected_air_ready):
    approved = approved_enrichment_frames(
        _raw_frames(), roster=_roster(), manifest=_health(status)
    )

    assert not approved["official_game_notes"].empty
    assert set(approved["official_game_notes"]["producer_air_ready"]) == {
        expected_air_ready
    }
    assert set(approved["media_players"]["producer_air_ready"]) == {
        expected_air_ready
    }


def _write_loader_fixture(root: Path):
    for name in (
        "ausl_rosters.xlsx",
        "ausl_season_stats.xlsx",
        "ausl_career_stats.xlsx",
        "ausl_team_context.xlsx",
        "official_game_notes.xlsx",
    ):
        (root / name).write_bytes(b"fixture")
    (root / "update_manifest.json").write_text(
        json.dumps(_health("green")), encoding="utf-8"
    )


def test_loader_modes_do_not_use_a_boolean_to_promote_enrichment(monkeypatch, tmp_path):
    _write_loader_fixture(tmp_path)
    calls = []

    def fake_read(path, sheet_name):
        calls.append((Path(path).name, sheet_name))
        if sheet_name.startswith("roster_"):
            return _roster()
        if sheet_name == "official_game_notes":
            return pd.DataFrame([_approved_note()])
        return pd.DataFrame()

    monkeypatch.setattr(ausl_data, "export_dir", lambda: tmp_path)
    monkeypatch.setattr(pd, "read_excel", fake_read)
    monkeypatch.setattr(ausl_data, "load_manual_notes", lambda: pd.DataFrame())

    core = ausl_data.load_database(enrichment_mode=EnrichmentMode.CORE_ONLY)
    assert core["official_game_notes"].empty
    assert core["enrichment_mode"] == EnrichmentMode.CORE_ONLY.value

    producer = ausl_data.load_database(
        enrichment_mode=EnrichmentMode.PRODUCER_APPROVED
    )
    assert len(producer["official_game_notes"]) == 1
    assert producer["enrichment_mode"] == EnrichmentMode.PRODUCER_APPROVED.value

    review = ausl_data.load_database(enrichment_mode=EnrichmentMode.DEVELOPER_REVIEW)
    assert len(review["official_game_notes"]) == 1
    assert review["enrichment_mode"] == EnrichmentMode.DEVELOPER_REVIEW.value


def test_legacy_true_flag_is_explicitly_developer_review_only(monkeypatch, tmp_path):
    _write_loader_fixture(tmp_path)

    def fake_read(_path, sheet_name):
        if sheet_name.startswith("roster_"):
            return _roster()
        if sheet_name == "official_game_notes":
            return pd.DataFrame([_approved_note()])
        return pd.DataFrame()

    monkeypatch.setattr(ausl_data, "export_dir", lambda: tmp_path)
    monkeypatch.setattr(pd, "read_excel", fake_read)
    monkeypatch.setattr(ausl_data, "load_manual_notes", lambda: pd.DataFrame())

    database = ausl_data.load_database(include_enrichment=True)

    assert database["enrichment_mode"] == EnrichmentMode.DEVELOPER_REVIEW.value


def _fact_database(note_frame, *, mode):
    snapshot = "2026-07-29T12:00:00+00:00"
    return {
        "roster": _roster(),
        "batting_2026": pd.DataFrame(),
        "pitching_2026": pd.DataFrame(),
        "career_batting": pd.DataFrame(),
        "career_pitching": pd.DataFrame(),
        "batting_splits": pd.DataFrame(),
        "pitching_splits": pd.DataFrame(),
        "fielding_splits": pd.DataFrame(),
        "official_game_notes": note_frame,
        "media_players": pd.DataFrame(),
        "manual_notes": pd.DataFrame(),
        "standings": pd.DataFrame(),
        "enrichment_enabled": True,
        "enrichment_mode": mode.value,
        "manifest": {
            "updated_at": snapshot,
            "source_health": {
                "official_rosters": {"status": "green"},
                "official_stats": {"status": "green"},
                "official_schedule": {"status": "green"},
                "official_standings": {"status": "green"},
                "official_game_notes": {"status": "green"},
                "media_guide": {"status": "green"},
                "split_stats": {"status": "green"},
            },
        },
        "refresh_attempt": {"state": "succeeded"},
    }


def _fact_game():
    return SimpleNamespace(
        game_id="9001",
        season=2026,
        away_team_code="CHI",
        away_team="Chicago Bandits",
        home_team_code="CAR",
        home_team="Carolina Blaze",
    )


def test_fact_adapter_requires_load_boundary_approval_marker_in_producer_mode():
    raw = pd.DataFrame([_approved_note()])
    unfiltered = build_selected_game_facts(
        _fact_database(raw, mode=EnrichmentMode.PRODUCER_APPROVED),
        _fact_game(),
    )
    unfiltered_note = next(
        fact
        for fact in unfiltered.facts
        if fact.source_record_identity.startswith("official-note:")
    )
    assert unfiltered_note.verification_state is VerificationState.VERIFY

    approved = approved_enrichment_frames(
        {"official_game_notes": raw},
        roster=_roster(),
        manifest=_health("green"),
    )["official_game_notes"]
    filtered = build_selected_game_facts(
        _fact_database(approved, mode=EnrichmentMode.PRODUCER_APPROVED),
        _fact_game(),
    )
    filtered_note = next(
        fact
        for fact in filtered.facts
        if fact.source_record_identity.startswith("official-note:")
    )
    assert filtered_note.verification_state is VerificationState.VERIFIED
    assert filtered_note.air_ready is True


def test_developer_review_mode_cannot_make_review_data_air_ready():
    collection = build_selected_game_facts(
        _fact_database(
            pd.DataFrame([_approved_note()]),
            mode=EnrichmentMode.DEVELOPER_REVIEW,
        ),
        _fact_game(),
    )
    note = next(
        fact
        for fact in collection.facts
        if fact.source_record_identity.startswith("official-note:")
    )
    assert note.verification_state is VerificationState.VERIFY
    assert note.air_ready is False
