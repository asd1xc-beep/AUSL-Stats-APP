from __future__ import annotations

import copy

import pandas as pd
import pytest

import ausl_data
import ausl_stats_app


def approved_player_row():
    row = {
        "entity_type": "player",
        "entity_id": 77,
        "entity_name": "Fixture Player",
        "note_category": "bio",
        "note_text": "Approved fixture biography.",
        "source_name": "2026 AUSL Media Guide",
        "source_pages": "49-50",
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


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("needs_review", True),
        ("match_status", "needs_review"),
        ("warnings", "Expected identity header is unresolved."),
        ("expected_printed_pages", ""),
        ("parsed_pdf_pages", ""),
        ("guide_date", ""),
        ("entity_name", ""),
        ("approval_state", "review_required"),
        ("approval_record_id", "tampered-record"),
        ("confidence_score", 0.45),
    ],
)
def test_every_media_approval_disagreement_fails_closed(field, unsafe_value):
    row = approved_player_row()
    row[field] = unsafe_value

    approved = ausl_stats_app._air_ready_media_rows(
        pd.DataFrame([row]), expected_entity_type="player", expected_entity_id=77
    )

    assert approved.empty


def test_flipping_only_needs_review_cannot_promote_a_review_row():
    row = approved_player_row()
    row.update(
        {
            "needs_review": False,
            "match_status": "needs_review",
            "approval_state": "review_required",
            "warnings": "Manual identity review remains open.",
            "approval_record_id": "",
        }
    )

    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame([row]),
        "media_players": pd.DataFrame(),
    }

    assert app._media_guide_player_lines(77) == []


def test_approved_media_renders_the_identity_and_pages_bound_to_approval():
    row = approved_player_row()
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.db = {
        "clean_media_notes": pd.DataFrame([row]),
        "media_players": pd.DataFrame(),
    }

    lines = app._media_guide_player_lines(77)

    assert len(lines) == 1
    assert "[VERIFIED | bio]" in lines[0]
    assert "Fixture Player" in lines[0]
    assert "printed pages 47-48" in lines[0]
    assert "PDF pages 49-50" in lines[0]


def test_approval_record_is_invalidated_when_identity_or_page_evidence_changes():
    original = approved_player_row()
    edited = copy.deepcopy(original)
    edited["entity_name"] = "Different Player"
    edited["parsed_pdf_pages"] = "99"

    assert ausl_data.media_approval_record_id(edited) != original["approval_record_id"]


def test_manual_approval_transaction_requires_resolved_identity_and_provenance():
    row = approved_player_row()
    row.update(
        {
            "needs_review": True,
            "match_status": "needs_review",
            "approval_state": "review_required",
            "approval_method": "",
            "approval_record_id": "",
            "warnings": "Expected player header remains unresolved.",
        }
    )

    with pytest.raises(ValueError, match="verified before approval"):
        ausl_data.approve_media_row(
            row,
            reviewer="Fixture Producer",
            approved_at="2026-07-23T01:00:00+00:00",
        )


def test_complete_manual_approval_transaction_binds_reviewer_time_and_evidence():
    row = approved_player_row()
    row.update(
        {
            "approval_state": "review_required",
            "approval_method": "",
            "approval_record_id": "",
        }
    )

    approved = ausl_data.approve_media_row(
        row,
        reviewer="Fixture Producer",
        approved_at="2026-07-23T01:00:00+00:00",
    )

    assert approved["approved_by"] == "Fixture Producer"
    assert approved["approved_at"] == "2026-07-23T01:00:00+00:00"
    frame = ausl_stats_app._air_ready_media_rows(
        pd.DataFrame([approved]),
        expected_entity_type="player",
        expected_entity_id=77,
    )
    assert len(frame) == 1
