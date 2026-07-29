from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import ausl_stats_app
from ausl_changes import ChangeComparisonContext, compare_snapshot_digests
from ausl_session import SessionChangeState
from ausl_session import SessionSnapshot
from test_phase6a_command_center import FakeVar, make_app, selected_game
from test_phase6e_changes import NOW, _digest, _roster


class FakeCanvas:
    def __init__(self):
        self.moves = []

    def yview_scroll(self, units, mode):
        self.moves.append((units, mode))


def change_app():
    app = make_app()
    app._change_state = SessionChangeState()
    app._change_build_generation = 1
    app._change_build_running = False
    app._change_build_pending = None
    app._change_build_lock = None
    app._change_status = "No comparison has run."
    app._change_last_error = ""
    app._session_ui_ready = False
    app._session_base_snapshot = SessionSnapshot.new(now=NOW)
    app._fact_collection = None
    app.what_changed_status_var = FakeVar("")
    app.what_changed_summary_var = FakeVar("")
    app.what_changed_filter_var = FakeVar("All Changes")
    app.what_changed_team_filter_var = FakeVar("Both teams")
    app.what_changed_category_filter_var = FakeVar("All categories")
    app.rendered_changes = 0
    app._render_change_cards = lambda: setattr(
        app, "rendered_changes", app.rendered_changes + 1
    )
    return app


def test_first_valid_result_establishes_baseline_without_change_flood():
    app = change_app()
    digest = _digest(roster=(_roster(),))

    accepted = app._finish_change_comparison(
        digest=digest,
        comparison=None,
        generation=1,
        database_identity=id(app.db),
        selected_game_id=app.selected_game.game_id,
        affected_source="local_reload",
    )

    assert accepted
    assert app._change_state.baseline == digest
    assert app._change_state.latest_comparison is None
    assert app._change_state.refresh_metadata.state == "baseline_created"
    assert "baseline" in app.what_changed_status_var.get().lower()


def test_successful_comparison_promotes_baseline_and_keeps_complete_report():
    app = change_app()
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))
    app._change_state = SessionChangeState(baseline=before)
    comparison = compare_snapshot_digests(
        before,
        after,
        context=ChangeComparisonContext(selected_game_id=app.selected_game.game_id),
        detected_at=NOW,
    )

    assert app._finish_change_comparison(
        digest=after,
        comparison=comparison,
        generation=1,
        database_identity=id(app.db),
        selected_game_id=app.selected_game.game_id,
        affected_source="official_core_sources",
    )

    assert app._change_state.baseline == after
    assert app._change_state.latest_comparison == comparison
    assert app._change_state.refresh_metadata.state == "success"
    assert app.rendered_changes == 1


def test_late_database_or_selected_game_result_is_discarded_without_promotion():
    app = change_app()
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))
    app._change_state = SessionChangeState(baseline=before)
    comparison = compare_snapshot_digests(before, after, detected_at=NOW)

    assert not app._finish_change_comparison(
        digest=after,
        comparison=comparison,
        generation=0,
        database_identity=id(app.db),
        selected_game_id=app.selected_game.game_id,
        affected_source="local_reload",
    )
    assert not app._finish_change_comparison(
        digest=after,
        comparison=comparison,
        generation=1,
        database_identity=id(app.db),
        selected_game_id="different-game",
        affected_source="local_reload",
    )
    assert app._change_state.baseline == before


def test_failed_and_cancelled_refresh_preserve_baseline_and_prior_report():
    app = change_app()
    before = _digest(roster=(_roster(),))
    after = _digest(roster=(_roster(status="inactive"),))
    comparison = compare_snapshot_digests(before, after, detected_at=NOW)
    app._change_state = SessionChangeState(
        baseline=after,
        latest_comparison=comparison,
    )

    app._record_change_refresh_outcome(
        "failed",
        error_summary="safe refresh fixture failure",
    )
    failed = app._change_state
    app._record_change_refresh_outcome("cancelled")

    assert failed.baseline == after
    assert failed.latest_comparison == comparison
    assert failed.refresh_metadata.state == "failed"
    assert app._change_state.baseline == after
    assert app._change_state.latest_comparison == comparison
    assert app._change_state.refresh_metadata.state == "cancelled"


def test_comparison_failure_preserves_prior_report_and_surfaces_unavailable():
    app = change_app()
    baseline = _digest(roster=(_roster(),))
    app._change_state = SessionChangeState(baseline=baseline)

    app._finish_change_comparison_error(
        RuntimeError("safe comparison fixture failure"),
        generation=1,
        database_identity=id(app.db),
        selected_game_id=app.selected_game.game_id,
        affected_source="local_reload",
    )

    assert app._change_state.baseline == baseline
    assert app._change_state.latest_comparison is None
    assert app._change_state.refresh_metadata.state == "comparison_failed"
    assert "unavailable" in app.what_changed_status_var.get().lower()


def test_ack_one_and_all_filtered_persist_identity_without_changing_fact_state():
    app = change_app()
    before = _digest(roster=(_roster(), _roster("p-2", name="Bea Batter")))
    after = _digest(
        roster=(
            _roster(status="inactive"),
            _roster("p-2", name="Bea Batter", status="inactive"),
        )
    )
    comparison = compare_snapshot_digests(before, after, detected_at=NOW)
    app._change_state = SessionChangeState(
        baseline=after,
        latest_comparison=comparison,
    )
    facts_before = app._fact_collection
    database_before = app.db

    assert app.acknowledge_change(comparison.events[0].event_id)
    app.acknowledge_all_filtered_changes()

    assert set(app._change_state.acknowledged_event_ids) == {
        event.event_id for event in comparison.events
    }
    assert app._fact_collection is facts_before
    assert app.db is database_before


def test_filtering_supports_attention_selected_game_team_category_pinned_and_used():
    app = change_app()
    selected = app.selected_game.game_id
    before = _digest(
        roster=(_roster(),),
        facts=(),
    )
    # A selected-game fact and one roster change provide distinct filter cases.
    from test_phase6e_changes import _fact

    old_fact = _fact(game_id=selected)
    new_fact = _fact(game_id=selected, evidence_hash="changed")
    before = _digest(roster=(_roster(),), facts=(old_fact,))
    after = _digest(roster=(_roster(status="inactive"),), facts=(new_fact,))
    comparison = compare_snapshot_digests(
        before,
        after,
        context=ChangeComparisonContext(
            selected_game_id=selected,
            pinned_fact_versions=((old_fact.fact_id, old_fact.evidence_hash),),
        ),
        detected_at=NOW,
    )
    app._change_state = SessionChangeState(
        baseline=after,
        latest_comparison=comparison,
    )

    app.what_changed_filter_var.set("Selected Game")
    assert all(item.selected_game_impact for item in app._filtered_change_events())
    app.what_changed_filter_var.set("Pinned")
    assert all(item.pinned_impact for item in app._filtered_change_events())
    app.what_changed_filter_var.set("Needs Attention")
    assert all(
        item.severity.value in {"blocking", "attention"}
        for item in app._filtered_change_events()
    )
    app.what_changed_filter_var.set("All Changes")
    app.what_changed_team_filter_var.set("BOS")
    assert all(item.team_code == "BOS" for item in app._filtered_change_events())
    app.what_changed_category_filter_var.set("Roster")
    assert all(item.category == "roster" for item in app._filtered_change_events())


def test_blocking_selected_game_change_affects_readiness_even_after_ack():
    from test_phase6e_changes import _fact

    app = change_app()
    game_id = app.selected_game.game_id
    old_fact = _fact(game_id=game_id)
    new_fact = _fact(
        game_id=game_id,
        evidence_hash="downgraded",
        air_ready=False,
        verification="VERIFY",
    )
    before = _digest(facts=(old_fact,))
    after = _digest(facts=(new_fact,))
    comparison = compare_snapshot_digests(
        before,
        after,
        context=ChangeComparisonContext(selected_game_id=game_id),
        detected_at=NOW,
    )
    app._change_state = SessionChangeState(
        baseline=after,
        latest_comparison=comparison,
    )

    issue_before = app._change_readiness_issue()
    app.acknowledge_change(comparison.events[0].event_id)
    issue_after = app._change_readiness_issue()

    assert issue_before["state"] == "fail"
    assert issue_before["blocking"] is True
    assert issue_after == issue_before


def test_change_panel_mousewheel_scrolls_and_is_safe_without_canvas():
    app = change_app()
    app.what_changed_canvas = FakeCanvas()

    assert app._on_change_cards_mousewheel(
        SimpleNamespace(delta=120, num=None)
    ) == "break"
    assert app.what_changed_canvas.moves == [(-1, "units")]

    app.what_changed_canvas = None
    assert app._on_change_cards_mousewheel(
        SimpleNamespace(delta=-120, num=None)
    ) is None


def test_restart_state_restoration_updates_change_filters_without_network():
    app = change_app()
    app.what_changed_filter_var = FakeVar("All Changes")
    app.what_changed_team_filter_var = FakeVar("Both teams")
    app.what_changed_category_filter_var = FakeVar("All categories")
    snapshot = replace(
        app._session_base_snapshot,
        change_state=SessionChangeState(),
        ui_state=replace(
            app._session_base_snapshot.ui_state,
            what_changed_filter="Needs Attention",
            what_changed_team_filter="BOS",
            what_changed_category_filter="Roster",
        ),
    )

    app._restore_change_session_state(snapshot)

    assert app.what_changed_filter_var.get() == "Needs Attention"
    assert app.what_changed_team_filter_var.get() == "BOS"
    assert app.what_changed_category_filter_var.get() == "Roster"
