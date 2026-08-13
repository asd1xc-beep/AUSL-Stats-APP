from __future__ import annotations

import shutil
from pathlib import Path

import ausl_stats_app
from ausl_college_batch_approval import load_aggregate_approval
from ausl_college_connection_approval import load_checked_in_connection_approval
from ausl_college_store import CollegeDataMode, CollegeStore
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


def _approved():
    return load_aggregate_approval(ROOT / "data" / "college_approved_phase7e")


def _connections():
    return load_checked_in_connection_approval(
        ROOT / "data" / "college_connections_approved"
    )


def test_default_producer_store_loads_full_roster_and_approved_connections():
    loaded = CollegeStore.default().load(CollegeDataMode.PRODUCER_APPROVED)

    assert loaded.available and loaded.copy_allowed
    assert len(loaded.envelope.resumes) == 118
    assert loaded.connection_approval is not None
    assert len(loaded.connection_approval.connections.candidates) == 8


def test_invalid_connection_replacement_retains_complete_last_known_good(tmp_path):
    resumes = tmp_path / "resumes"
    connections = tmp_path / "connections"
    shutil.copytree(ROOT / "data" / "college_approved_phase7e", resumes)
    shutil.copytree(ROOT / "data" / "college_connections_approved", connections)
    store = CollegeStore(
        approved_directories=(resumes,),
        approved_connection_directories=(connections,),
        developer_pilot_path=ROOT / "data" / "college_pilot" / "pilot_envelope.json",
    )
    first = store.load(CollegeDataMode.PRODUCER_APPROVED)
    (connections / "college_connection_approval_manifest.json").write_text(
        "{}\n", encoding="utf-8"
    )
    second = store.load(CollegeDataMode.PRODUCER_APPROVED)

    assert first.available and second.available
    assert second.envelope is first.envelope
    assert second.connection_approval is first.connection_approval
    assert "last-known-good" in second.warning


def test_selected_player_view_contains_only_exact_approved_connections():
    view = build_college_resume_view(
        _approved(),
        player_id="1075",
        mode=EnrichmentMode.PRODUCER_APPROVED,
        connection_approval=_connections(),
    )

    assert view.available
    assert len(view.connection_fields) == 2
    assert all("Tiare Jennings" in item.copy_text for item in view.connection_fields)
    assert all(item.copy_eligible for item in view.connection_fields)
    championship = next(
        item for item in view.connection_fields if "championship" in item.copy_text
    )
    assert "Oklahoma" in championship.school_season
    assert "2024" in championship.school_season
    assert len(championship.source_details) == 2


def test_player_without_connection_keeps_normal_reviewed_resume():
    view = build_college_resume_view(
        _approved(),
        player_id="10",
        mode=EnrichmentMode.PRODUCER_APPROVED,
        connection_approval=_connections(),
    )

    assert view.available
    assert view.player_name == "Aleshia Ocasio"
    assert view.connection_fields == ()


def test_connection_copy_and_source_copy_use_exact_visible_approved_version():
    view = build_college_resume_view(
        _approved(),
        player_id="1075",
        mode=EnrichmentMode.PRODUCER_APPROVED,
        connection_approval=_connections(),
    )
    field = view.connection_fields[0]
    app = ausl_stats_app.AUSLStatsApp.__new__(ausl_stats_app.AUSLStatsApp)
    app.root = ClipboardRoot("previous")
    app.college_status_var = Var()
    app._current_college_view = view
    app._last_college_copy = None

    assert app.copy_college_connection(field.connection_id)
    assert app.root.text == field.copy_text
    assert app._last_college_copy["evidence_hash"] == field.evidence_hash

    assert app.copy_college_connection(field.connection_id, with_source=True)
    assert app.root.text == field.copy_with_source
    assert "Status: APPROVED" in app.root.text
    assert "Evidence:" in app.root.text


def test_developer_mode_cannot_copy_approved_connection_shortcut():
    view = build_college_resume_view(
        _approved().envelope,
        player_id="1075",
        mode=EnrichmentMode.DEVELOPER_REVIEW,
        connection_approval=_connections(),
    )
    assert all(not item.copy_eligible for item in view.connection_fields)


def test_college_ui_replaces_phase7d_placeholder_with_connection_controls():
    source = (ROOT / "src" / "ausl_stats_app.py").read_text(encoding="utf-8")
    assert "Copy College Connection" in source
    assert "copy_college_connection" in source
    assert "Phase 7D does not generate college storylines" not in source
