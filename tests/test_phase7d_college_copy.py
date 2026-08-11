from __future__ import annotations

from pathlib import Path

import ausl_stats_app
from ausl_college_approval import load_checked_in_approval
from ausl_college_view import build_college_resume_view
from ausl_enrichment import EnrichmentMode


ROOT = Path(__file__).resolve().parents[1]


class ClipboardRoot:
    def __init__(self, text=""):
        self.text = text

    def clipboard_clear(self):
        self.text = ""

    def clipboard_append(self, text):
        self.text += text

    def update(self):
        return None


class Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def _app(mode=EnrichmentMode.PRODUCER_APPROVED):
    artifact = load_checked_in_approval(ROOT / "data" / "college_approved")
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.root = ClipboardRoot("previous clipboard")
    app.college_status_var = Var()
    app._current_college_view = build_college_resume_view(
        artifact, player_id="950", mode=mode
    )
    app._last_fact_copy_event = object()
    app.current_broadcast_note = "professional note"
    app._last_college_copy = None
    return app


def test_approved_field_copies_exact_visible_scoped_text():
    app = _app()
    field = app._current_college_view.stat_fields[0]
    assert app.copy_college_field(field.field_id)
    assert app.root.text == field.copy_text
    assert "COLLEGE CAREER" in app.root.text
    assert "CLEMSON" in app.root.text


def test_source_copy_contains_exact_provenance_and_review_date():
    app = _app()
    field = app._current_college_view.stat_fields[0]
    assert app.copy_college_field(field.field_id, with_source=True)
    assert app.root.text == field.copy_with_source
    assert "Source:" in app.root.text
    assert "reviewed 2026-08-11" in app.root.text


def test_developer_review_copy_is_blocked_and_clipboard_is_unchanged():
    app = _app(EnrichmentMode.DEVELOPER_REVIEW)
    field = app._current_college_view.stat_fields[0]
    before = app.root.text
    assert not app.copy_college_field(field.field_id)
    assert app.root.text == before
    assert "blocked" in app.college_status_var.value.casefold()


def test_college_copy_does_not_mutate_professional_copy_state():
    app = _app()
    professional_event = app._last_fact_copy_event
    app.copy_college_field(app._current_college_view.stat_fields[0].field_id)
    assert app._last_fact_copy_event is professional_event
    assert app.current_broadcast_note == "professional note"
    assert app._last_college_copy["field_id"]


def test_unknown_field_and_unavailable_summary_preserve_clipboard():
    app = _app()
    before = app.root.text
    assert not app.copy_college_field("not-a-field")
    assert app.root.text == before
    app._current_college_view = None
    assert not app.copy_college_summary()
    assert app.root.text == before

