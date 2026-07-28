from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import ausl_stats_app
from ausl_facts import (
    FactCollection,
    VerificationState,
    build_copy_event,
    copy_with_source_text,
)
from test_broadcast_facts import fact
from test_phase6a_command_center import FakeVar, make_app, selected_game


def prepare_app():
    app = make_app()
    app._fact_build_generation = 0
    app._fact_collection = None
    app._fact_build_pending = None
    app._fact_build_running = False
    app._fact_build_lock = None
    app._last_fact_copy_event = None
    app.current_broadcast_note = ""
    app.fact_status_filter_var = FakeVar("Air Ready")
    app.fact_team_filter_var = FakeVar("Both teams")
    app.fact_category_filter_var = FakeVar("All categories")
    app.fact_panel_status_var = FakeVar("")
    app._render_fact_cards = lambda: None
    return app


def collection(game_id="9001", facts=None):
    return FactCollection(
        game_id=game_id,
        snapshot_timestamp="2026-07-27T15:42:00+00:00",
        database_version="db-v1",
        facts=tuple(facts or ()),
        available=True,
        empty_reason="",
    )


def test_game_change_clears_visible_facts_and_copied_version_immediately(monkeypatch):
    app = prepare_app()
    app._fact_collection = collection(
        facts=[fact(selected_game_id="9001")]
    )
    app.current_broadcast_note = "old game fact"
    app._last_fact_copy_event = object()
    requested = []
    monkeypatch.setattr(
        app, "request_fact_rebuild", lambda: requested.append(app.selected_game.game_id)
    )
    app.away_var = FakeVar(app.selected_game.away_team)
    app.home_var = FakeVar(app.selected_game.home_team)
    app.game_choice_var = FakeVar()
    app.game_context_var = FakeVar()
    app.note_game_var = FakeVar()
    app.game_id_var = FakeVar()
    app.selected_player_id = None
    app.search = lambda: None
    app.render_producer_prep = lambda: None
    app.render_manual_notes = lambda: None
    app._reset_lineup_editor_for_game = lambda _game: None
    app._reset_live_for_game = lambda _game: None
    app.refresh_game_day_dashboard = lambda: None

    app.on_game_changed(selected_game("9002"))

    assert app._fact_collection is None
    assert app.current_broadcast_note == ""
    assert app._last_fact_copy_event is None
    assert requested == ["9002"]


def test_late_old_game_fact_result_is_discarded():
    app = prepare_app()
    app._fact_build_generation = 4
    app.selected_game = selected_game("9002")
    old = collection("9001", [fact(selected_game_id="9001")])

    accepted = app._finish_fact_rebuild(
        old,
        generation=3,
        game_id="9001",
        database_identity=id(app.db),
    )

    assert accepted is False
    assert app._fact_collection is None


def test_current_fact_result_updates_collection_and_verification_count():
    app = prepare_app()
    app._fact_build_generation = 4
    needs_review = replace(
        fact(selected_game_id="9001"),
        verification_state=VerificationState.VERIFY,
        readiness_blocking=True,
    )
    current = collection("9001", [needs_review])
    dashboard = []
    app.refresh_game_day_dashboard = lambda: dashboard.append(True)

    accepted = app._finish_fact_rebuild(
        current,
        generation=4,
        game_id="9001",
        database_identity=id(app.db),
    )

    assert accepted is True
    assert app._scoped_verification_count() == 1
    assert dashboard == [True]


def test_changed_evidence_invalidates_previously_copied_version():
    app = prepare_app()
    app._fact_build_generation = 4
    old = fact(selected_game_id="9001")
    app._last_fact_copy_event = build_copy_event(old)
    app.current_broadcast_note = old.air_copy
    changed = replace(
        old,
        air_copy="Ada Active has 32 hits and 18 RBI in the 2026 AUSL season.",
        evidence=(("hits", "32"), ("rbi", "18")),
    )
    app.refresh_game_day_dashboard = lambda: None

    app._finish_fact_rebuild(
        collection("9001", [changed]),
        generation=4,
        game_id="9001",
        database_identity=id(app.db),
    )

    assert changed.fact_id == old.fact_id
    assert changed.evidence_hash != old.evidence_hash
    assert app._last_fact_copy_event is None
    assert app.current_broadcast_note == ""


def test_missing_fact_collection_is_unavailable_not_zero():
    app = prepare_app()
    app._fact_collection = None
    assert app._scoped_verification_count() is None


def test_only_blocking_selected_game_review_items_affect_readiness_count():
    app = prepare_app()
    optional = replace(
        fact(selected_game_id="9001"),
        verification_state=VerificationState.VERIFY,
        readiness_blocking=False,
        concept_key="optional",
        source_record_identity="optional",
    )
    blocking = replace(
        fact(selected_game_id="9001"),
        verification_state=VerificationState.VERIFY,
        readiness_blocking=True,
        concept_key="blocking",
        source_record_identity="blocking",
    )
    app._fact_collection = collection("9001", [optional, blocking])
    assert app._scoped_verification_count() == 1


def test_copy_air_line_syncs_visible_version_and_event():
    app = prepare_app()
    item = fact(selected_game_id="9001")
    app._fact_collection = collection("9001", [item])
    copied = []
    app.root.clipboard_clear = lambda: copied.clear()
    app.root.clipboard_append = copied.append
    app.root.update = lambda: None

    assert app.copy_fact_air_line(item.fact_id) is True
    assert copied == [item.air_copy]
    assert app.current_broadcast_note == item.air_copy
    assert app._last_fact_copy_event.fact_id == item.fact_id
    assert app._last_fact_copy_event.evidence_hash == item.evidence_hash


def test_copy_air_line_records_the_visible_width_profile():
    app = prepare_app()
    app.fact_template_profile_var = FakeVar("120 — extended")
    item = fact(selected_game_id="9001")
    app._fact_collection = collection("9001", [item])
    app.root.clipboard_clear = lambda: None
    app.root.clipboard_append = lambda _text: None
    app.root.update = lambda: None

    assert app.copy_fact_air_line(item.fact_id) is True
    assert app._last_fact_copy_event.template_profile == "extended"


def test_stale_fact_cannot_silently_use_copy_air_line():
    app = prepare_app()
    item = replace(
        fact(selected_game_id="9001"),
        verification_state=VerificationState.STALE,
    )
    app._fact_collection = collection("9001", [item])
    copied = []
    app.root.clipboard_clear = lambda: copied.clear()
    app.root.clipboard_append = copied.append
    app.root.update = lambda: None

    assert app.copy_fact_air_line(item.fact_id) is False
    assert copied == []
    assert item.verification_state is VerificationState.STALE
    assert "not copied" in app.fact_panel_status_var.get().casefold()


def test_copy_with_source_keeps_warning_and_does_not_promote_review_fact():
    app = prepare_app()
    item = replace(
        fact(selected_game_id="9001"),
        verification_state=VerificationState.VERIFY,
        warning_reason="Reviewer confirmation required.",
    )
    app._fact_collection = collection("9001", [item])
    copied = []
    app.root.clipboard_clear = lambda: copied.clear()
    app.root.clipboard_append = copied.append
    app.root.update = lambda: None

    assert app.copy_fact_with_source(item.fact_id) is True
    assert copied == [copy_with_source_text(item)]
    assert "Status: VERIFY" in copied[0]
    assert item.verification_state is VerificationState.VERIFY
    assert app.current_broadcast_note == ""
    assert app._last_fact_copy_event is None


def test_database_replacement_invalidates_fact_collection_and_rebuilds(monkeypatch):
    app = prepare_app()
    app._fact_collection = collection("9001", [fact(selected_game_id="9001")])
    app._last_fact_copy_event = object()
    app.current_broadcast_note = "old evidence"
    app.data_freshness_var = FakeVar()
    app._apply_data_health_display = lambda *_args: None
    app._refresh_manual_note_players = lambda: None
    app.refresh_game_choices = lambda: None
    app._sync_selected_player_after_load = lambda *_args: None
    app.show_all = lambda: None
    app.render_team_totals = lambda: None
    app.render_producer_prep = lambda: None
    app.render_manual_notes = lambda: None
    app.refresh_game_day_dashboard = lambda: None
    requested = []
    monkeypatch.setattr(app, "request_fact_rebuild", lambda: requested.append(True))
    replacement = dict(app.db)

    app._finish_load(replacement)

    assert app._fact_collection is None
    assert app._last_fact_copy_event is None
    assert app.current_broadcast_note == ""
    assert requested == [True]


def test_offline_mode_still_allows_local_fact_rebuild(monkeypatch):
    app = prepare_app()
    app._offline_mode = True
    requested = []
    monkeypatch.setattr(
        app, "_queue_fact_build", lambda task: requested.append(task)
    )

    app.request_fact_rebuild()

    assert len(requested) == 1
    assert requested[0]["game_id"] == "9001"


def test_repeated_requests_keep_one_active_worker_and_one_latest_pending(monkeypatch):
    app = prepare_app()
    started = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(ausl_stats_app.threading, "Thread", FakeThread)
    app._ensure_main_thread_dispatch = lambda: None

    app.request_fact_rebuild()
    first_generation = app._fact_build_pending["generation"]
    app.request_fact_rebuild()

    assert len(started) == 1
    assert app._fact_build_running is True
    assert app._fact_build_pending["generation"] > first_generation


def test_fact_filters_keep_both_team_and_review_views_local():
    app = prepare_app()
    air_ready = fact(selected_game_id="9001", team_code="CHI")
    review = replace(
        fact(
            selected_game_id="9001",
            subject_id="22",
            team_code="CAR",
            concept_key="car-review",
            source_record_identity="car-review",
        ),
        verification_state=VerificationState.VERIFY,
    )
    app._fact_collection = collection("9001", [air_ready, review])

    assert app._filtered_fact_cards() == [air_ready]
    app.fact_status_filter_var.set("Needs Verification")
    assert app._filtered_fact_cards() == [review]
    app.fact_status_filter_var.set("All facts")
    app.fact_team_filter_var.set("CAR")
    assert app._filtered_fact_cards() == [review]


def test_fact_panel_contract_is_scrollable():
    assert ausl_stats_app.AUSLStatsApp.FACT_PANEL_SCROLLABLE is True


def test_fact_panel_mousewheel_scrolls_in_platform_directions():
    app = prepare_app()

    class FakeCanvas:
        def __init__(self):
            self.calls = []

        def yview_scroll(self, amount, units):
            self.calls.append((amount, units))

    app.fact_cards_canvas = FakeCanvas()

    assert app._on_fact_cards_mousewheel(SimpleNamespace(delta=120, num=None)) == "break"
    assert app._on_fact_cards_mousewheel(SimpleNamespace(delta=-240, num=None)) == "break"
    assert app._on_fact_cards_mousewheel(SimpleNamespace(delta=1, num=None)) == "break"
    assert app._on_fact_cards_mousewheel(SimpleNamespace(delta=0, num=4)) == "break"
    assert app._on_fact_cards_mousewheel(SimpleNamespace(delta=0, num=5)) == "break"
    assert app.fact_cards_canvas.calls == [
        (-1, "units"),
        (2, "units"),
        (-1, "units"),
        (-1, "units"),
        (1, "units"),
    ]


def test_fact_panel_mousewheel_binding_reaches_card_descendants_idempotently():
    app = prepare_app()

    class FakeWidget:
        def __init__(self, *children):
            self.children = list(children)
            self.bindings = {}

        def bind(self, sequence, callback):
            self.bindings[sequence] = callback

        def winfo_children(self):
            return self.children

    button = FakeWidget()
    label = FakeWidget()
    card = FakeWidget(label, button)
    container = FakeWidget(card)

    app._bind_fact_cards_mousewheel(container)
    app._bind_fact_cards_mousewheel(container)

    for widget in (container, card, label, button):
        assert set(widget.bindings) == {"<MouseWheel>", "<Button-4>", "<Button-5>"}
