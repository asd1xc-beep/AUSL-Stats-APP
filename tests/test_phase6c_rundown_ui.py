from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import ausl_stats_app
from ausl_facts import FactCollection, VerificationState
from ausl_rundown import ReconciliationState, RundownSession
from test_broadcast_facts import fact
from test_phase6a_command_center import FakeVar, make_app, selected_game


NOW = datetime(2026, 7, 28, 2, 0, tzinfo=timezone.utc)


def ui_fact(*, game_id="9001", subject_id="11", **overrides):
    values = {
        "selected_game_id": game_id,
        "subject_id": subject_id,
        "source_record_identity": f"player:{subject_id}:season:2026:hits",
        "concept_key": f"season-context-{subject_id}",
    }
    values.update(overrides)
    return fact(**values)


def collection(game_id="9001", facts=()):
    return FactCollection(
        game_id=game_id,
        snapshot_timestamp="2026-07-28T01:45:00+00:00",
        database_version=f"db-{game_id}",
        facts=tuple(facts),
        available=True,
        empty_reason="",
    )


def prepare_rundown_app(facts=()):
    app = make_app()
    app._fact_build_generation = 0
    app._fact_collection = collection(facts=facts)
    app._fact_build_pending = None
    app._fact_build_running = False
    app._fact_build_lock = None
    app._last_fact_copy_event = None
    app.current_broadcast_note = ""
    app._rundown_session = RundownSession()
    app.fact_status_filter_var = FakeVar("Air Ready")
    app.fact_team_filter_var = FakeVar("Both teams")
    app.fact_category_filter_var = FakeVar("All categories")
    app.fact_show_used_var = FakeVar(False)
    app.fact_panel_status_var = FakeVar("")
    app.rundown_status_var = FakeVar("")
    app.rundown_budget_var = FakeVar("")
    app.rundown_session_var = FakeVar("")
    app.rundown_break_target_var = FakeVar("30")
    app.rendered_facts = 0
    app.rendered_rundown = 0
    app.rendered_dashboard = 0

    def render_facts():
        app.rendered_facts += 1

    def render_rundown():
        app.rendered_rundown += 1

    def render_dashboard():
        app.rendered_dashboard += 1

    app._render_fact_cards = render_facts
    app._render_rundown = render_rundown
    app.refresh_game_day_dashboard = render_dashboard
    return app


def test_pin_button_uses_canonical_fact_and_updates_views_immediately():
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])

    assert app.pin_fact_to_rundown(canonical.fact_id, now=NOW)

    state = app._current_rundown_state(create=False)
    assert state.active_entries[0].fact_snapshot is canonical
    assert "Pinned" in app.rundown_status_var.get()
    assert app.rendered_rundown == 1
    assert app.rendered_facts == 1


def test_review_pin_retains_warning_and_unavailable_pin_is_blocked():
    review = ui_fact(
        subject_id="22",
        verification_state=VerificationState.VERIFY,
        producer_confirmation_required=True,
        warning_reason="Review required.",
        readiness_blocking=True,
    )
    unavailable = ui_fact(
        subject_id="33",
        verification_state=VerificationState.UNAVAILABLE,
        source_health="red",
        warning_reason="Unavailable.",
    )
    app = prepare_rundown_app([review, unavailable])

    assert app.pin_fact_to_rundown(review.fact_id, now=NOW)
    assert app._current_rundown_state().active_entries[0].needs_verification
    assert not app.pin_fact_to_rundown(unavailable.fact_id, now=NOW)
    assert "cannot be pinned" in app.rundown_status_var.get().lower()


def test_used_card_is_suppressed_by_default_show_used_and_undo_restore_it():
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])

    assert app.mark_fact_used_from_card(canonical.fact_id, now=NOW)
    assert app._filtered_fact_cards() == []
    app.fact_show_used_var.set(True)
    assert app._filtered_fact_cards() == [canonical]
    assert app.undo_rundown_used(canonical.fact_id, now=NOW)
    app.fact_show_used_var.set(False)
    assert app._filtered_fact_cards() == [canonical]


def test_mark_pinned_used_removes_active_entry_and_undo_restores_queue():
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])
    app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    entry = app._current_rundown_state().active_entries[0]

    assert app.mark_rundown_entry_used(entry.entry_id, now=NOW)
    state = app._current_rundown_state()
    assert state.active_entries == ()
    assert state.used_history[0].fact_snapshot is canonical
    assert app.undo_rundown_used(canonical.fact_id, now=NOW)
    assert app._current_rundown_state().active_entries[0].fact_snapshot is canonical


def test_game_change_reads_only_that_games_session_queue():
    first = ui_fact(game_id="9001")
    second = ui_fact(game_id="9002")
    app = prepare_rundown_app([first])
    app.pin_fact_to_rundown(first.fact_id, now=NOW)
    app.selected_game = selected_game("9002")
    app._fact_collection = collection("9002", [second])

    assert app._current_rundown_state(create=False) is None
    app.pin_fact_to_rundown(second.fact_id, now=NOW)
    assert [item.fact_id for item in app._current_rundown_state().active_entries] == [
        second.fact_id
    ]
    app.selected_game = selected_game("9001")
    assert [item.fact_id for item in app._current_rundown_state().active_entries] == [
        first.fact_id
    ]


def test_finish_fact_rebuild_reconciles_only_accepted_exact_game_result():
    original = ui_fact()
    app = prepare_rundown_app([original])
    app.pin_fact_to_rundown(original.fact_id, now=NOW)
    changed = replace(original, air_copy="Updated current source wording.")
    app._fact_build_generation = 4

    accepted = app._finish_fact_rebuild(
        collection("9001", [changed]),
        generation=4,
        game_id="9001",
        database_identity=id(app.db),
    )

    assert accepted
    entry = app._current_rundown_state().active_entries[0]
    assert entry.fact_snapshot is original
    assert entry.latest_fact is changed
    assert entry.reconciliation_state is ReconciliationState.SOURCE_CHANGED

    app.selected_game = selected_game("9002")
    rejected = app._finish_fact_rebuild(
        collection("9001", [original]),
        generation=4,
        game_id="9001",
        database_identity=id(app.db),
    )
    assert rejected is False
    assert entry == app._rundown_session.get_state("9001").active_entries[0]


def test_custom_break_target_updates_budget_without_readiness_failure():
    canonical = ui_fact(air_copy="one two three")
    app = prepare_rundown_app([canonical])
    app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    dashboard_before_target = app.rendered_dashboard
    app.rundown_break_target_var.set("1")

    assert app.apply_rundown_break_target(now=NOW)

    state = app._current_rundown_state()
    assert state.break_target_seconds == 1
    assert state.remaining_read_seconds == 2
    assert "over" in app.rundown_budget_var.get()
    assert app.rendered_dashboard == dashboard_before_target + 1


def test_pinned_review_issues_are_unioned_not_double_counted_in_readiness():
    review = ui_fact(
        subject_id="22",
        verification_state=VerificationState.VERIFY,
        producer_confirmation_required=True,
        warning_reason="Review.",
        readiness_blocking=True,
    )
    app = prepare_rundown_app([review])
    app.pin_fact_to_rundown(review.fact_id, now=NOW)

    assert app._scoped_verification_count() == 1


def test_copy_rundown_uses_selected_game_context_and_exact_session_state():
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])
    app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    clipboard = []
    app.root.clipboard_clear = lambda: clipboard.clear()
    app.root.clipboard_append = lambda text: clipboard.append(text)
    app.root.update = lambda: None

    assert app.copy_rundown(now=NOW)

    assert "OFFICIAL GAME ID: 9001" in clipboard[0]
    assert canonical.air_copy in clipboard[0]
    assert "Copied rundown" in app.rundown_status_var.get()


def test_export_rundown_writes_only_under_private_game_packet_area(
    monkeypatch, tmp_path
):
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])
    app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    monkeypatch.setattr(ausl_stats_app, "export_dir", lambda: tmp_path)

    assert app.export_rundown(now=NOW)

    exports = list((tmp_path / "game_packets" / "rundowns").glob("*_rundown.txt"))
    assert len(exports) == 1
    assert "OFFICIAL GAME ID: 9001" in exports[0].read_text(encoding="utf-8")


def test_rundown_logs_identity_metadata_without_private_fact_wording():
    canonical = ui_fact(air_copy="Private producer-facing wording.")
    app = prepare_rundown_app([canonical])
    events = []
    app._log_event = lambda event, **fields: events.append((event, fields))

    app.pin_fact_to_rundown(canonical.fact_id, now=NOW)

    assert events[0][0] == "rundown_fact_pinned"
    assert events[0][1]["fact_id"] == canonical.fact_id
    assert canonical.air_copy not in repr(events)


def test_offline_mode_does_not_block_local_rundown_mutations():
    canonical = ui_fact()
    app = prepare_rundown_app([canonical])
    app._offline_mode = True

    assert app.pin_fact_to_rundown(canonical.fact_id, now=NOW)
    assert app.mark_fact_used_from_card(canonical.fact_id, now=NOW)
    assert app._current_rundown_state().used_history
