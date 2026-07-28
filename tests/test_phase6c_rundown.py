from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ausl_facts import FactCategory, VerificationState
from ausl_rundown import (
    BREAK_TARGET_PRESETS,
    DEFAULT_READING_WPM,
    GameRundownState,
    ReconciliationState,
    RundownExportContext,
    RundownMutationError,
    RundownSession,
    budget_for_state,
    count_read_words,
    estimate_read_time_seconds,
    render_rundown_export,
    rundown_export_filename,
    validate_break_target,
    write_rundown_export_exclusive,
)
from test_broadcast_facts import fact


NOW = datetime(2026, 7, 28, 1, 2, 3, 456789, tzinfo=timezone.utc)


def versioned_fact(*, game_id="1042", subject_id="11", copy=None, **overrides):
    values = {
        "selected_game_id": game_id,
        "subject_id": subject_id,
        "source_record_identity": f"player:{subject_id}:season:2026:hits",
        "concept_key": "season-hits-rbi",
    }
    if copy is not None:
        values["air_copy"] = copy
    values.update(overrides)
    return fact(**values)


def review_fact(*, game_id="1042", subject_id="22"):
    return versioned_fact(
        game_id=game_id,
        subject_id=subject_id,
        verification_state=VerificationState.VERIFY,
        source_health="green",
        producer_confirmation_required=True,
        warning_reason="Producer review required.",
        readiness_blocking=True,
    )


@pytest.mark.parametrize(
    ("text", "expected_words"),
    [
        ("", 0),
        ("Ada", 1),
        ("Ada has 31 hits in 11-7 games.", 7),
        ("A.J. Andrews is a two-time All-Star.", 6),
        ("Jocelyn Alo’s résumé — verified.", 4),
        ("79.4 mph; No. 22.", 4),
    ],
)
def test_read_word_count_is_deterministic_for_broadcast_copy(text, expected_words):
    assert count_read_words(text) == expected_words


def test_read_time_uses_central_default_and_minimum_one_second():
    assert DEFAULT_READING_WPM == 140
    assert estimate_read_time_seconds("") == 0
    assert estimate_read_time_seconds("Ada") == 1
    assert estimate_read_time_seconds("one two three", words_per_minute=60) == 3
    assert estimate_read_time_seconds("!!!") == 1


@pytest.mark.parametrize("target", [15, 30, 45, 60, 90])
def test_break_target_presets_are_valid(target):
    assert target in BREAK_TARGET_PRESETS
    assert validate_break_target(str(target)) == target


@pytest.mark.parametrize("target", ["", "nope", 0, -1, 3601, True, 1.5])
def test_invalid_break_targets_fail_closed(target):
    with pytest.raises(RundownMutationError):
        validate_break_target(target)


def test_pin_uses_canonical_fact_and_blocks_same_game_duplicate():
    session = RundownSession()
    canonical = versioned_fact()

    state = session.pin_fact("1042", canonical, now=NOW)

    assert state.active_entries[0].fact_snapshot is canonical
    assert state.active_entries[0].fact_id == canonical.fact_id
    assert state.active_entries[0].evidence_hash == canonical.evidence_hash
    with pytest.raises(RundownMutationError, match="already pinned"):
        session.pin_fact("1042", canonical, now=NOW)


def test_exact_game_isolation_including_repeat_opponents():
    session = RundownSession()
    first = versioned_fact(game_id="1042")
    second = versioned_fact(game_id="1043")

    session.pin_fact("1042", first, now=NOW)
    session.pin_fact("1043", second, now=NOW)

    assert [entry.fact_snapshot for entry in session.get_state("1042").active_entries] == [first]
    assert [entry.fact_snapshot for entry in session.get_state("1043").active_entries] == [second]
    assert session.get_state("9999", create=False) is None


@pytest.mark.parametrize("game_id", ["", "custom", None])
def test_invalid_or_missing_game_identity_blocks_pin_and_use(game_id):
    session = RundownSession()
    with pytest.raises(RundownMutationError):
        session.pin_fact(game_id, versioned_fact(), now=NOW)
    with pytest.raises(RundownMutationError):
        session.mark_fact_used(game_id, versioned_fact(), now=NOW)


def test_wrong_game_fact_cannot_enter_state():
    session = RundownSession()
    with pytest.raises(RundownMutationError, match="does not match"):
        session.pin_fact("1043", versioned_fact(game_id="1042"), now=NOW)


def test_unavailable_fact_is_not_pinnable():
    session = RundownSession()
    unavailable = versioned_fact(
        verification_state=VerificationState.UNAVAILABLE,
        source_health="red",
        warning_reason="Source unavailable.",
    )
    with pytest.raises(RundownMutationError, match="[Uu]navailable"):
        session.pin_fact("1042", unavailable, now=NOW)


def test_ordering_boundaries_repeated_moves_and_remove_keep_dense_positions():
    session = RundownSession()
    facts = [
        versioned_fact(subject_id=str(subject), concept_key=f"concept-{subject}")
        for subject in (11, 22, 33)
    ]
    for item in facts:
        session.pin_fact("1042", item, now=NOW)
    entries = session.get_state("1042").active_entries

    unchanged = session.move_entry("1042", entries[0].entry_id, -1, now=NOW)
    assert unchanged.active_entries == entries
    session.move_entry("1042", entries[2].entry_id, -1, now=NOW)
    session.move_entry("1042", entries[2].entry_id, -1, now=NOW)
    state = session.remove_entry("1042", entries[1].entry_id, now=NOW)

    assert [entry.fact_id for entry in state.active_entries] == [
        facts[2].fact_id,
        facts[0].fact_id,
    ]
    assert [entry.position for entry in state.active_entries] == [1, 2]


def test_mark_pinned_used_removes_time_and_undo_restores_original_position():
    session = RundownSession()
    first = versioned_fact(subject_id="11", concept_key="one", copy="one two three")
    second = versioned_fact(subject_id="22", concept_key="two", copy="four five")
    session.pin_fact("1042", first, now=NOW)
    session.pin_fact("1042", second, now=NOW)
    entry = session.get_state("1042").active_entries[0]

    used_state = session.mark_entry_used("1042", entry.entry_id, now=NOW)

    assert [item.fact_id for item in used_state.active_entries] == [second.fact_id]
    assert used_state.used_history[0].fact_snapshot is first
    assert used_state.used_history[0].evidence_hash == first.evidence_hash
    assert used_state.used_history[0].used_at.tzinfo is not None
    assert used_state.used_history[0].from_queue is True
    restored = session.undo_used("1042", first.fact_id, now=NOW)
    assert [item.fact_id for item in restored.active_entries] == [
        first.fact_id,
        second.fact_id,
    ]
    assert restored.used_history == ()
    assert session.undo_used("1042", first.fact_id, now=NOW) is restored


def test_mark_unpinned_used_suppresses_stable_fact_id_only_for_exact_game():
    session = RundownSession()
    current = versioned_fact(game_id="1042")

    state = session.mark_fact_used("1042", current, now=NOW)

    assert state.active_entries == ()
    assert state.used_history[0].from_queue is False
    assert session.is_fact_used("1042", current.fact_id)
    changed = replace(current, air_copy="Ada Active now has 32 hits.")
    assert changed.fact_id == current.fact_id
    assert changed.evidence_hash != current.evidence_hash
    assert session.is_fact_used("1042", changed.fact_id)
    assert not session.is_fact_used("1043", changed.fact_id)
    assert session.mark_fact_used("1042", changed, now=NOW) is state
    assert session.undo_used("1042", current.fact_id, now=NOW).used_history == ()


def test_distinct_watch_and_reached_concepts_are_not_suppressed_together():
    session = RundownSession()
    watch = versioned_fact(
        category=FactCategory.MILESTONE_WATCH,
        concept_key="25-hits-watch",
    )
    reached = versioned_fact(
        category=FactCategory.MILESTONE_REACHED,
        concept_key="25-hits-reached",
    )
    session.mark_fact_used("1042", watch, now=NOW)
    assert watch.fact_id != reached.fact_id
    assert not session.is_fact_used("1042", reached.fact_id)


def test_read_time_budget_sums_displayed_active_items_and_excludes_review_used_changed():
    session = RundownSession()
    ready = versioned_fact(subject_id="11", concept_key="ready", copy="one two three")
    review = review_fact(subject_id="22")
    changed = versioned_fact(subject_id="33", concept_key="changed", copy="one two")
    for item in (ready, review, changed):
        session.pin_fact("1042", item, now=NOW)
    changed_latest = replace(changed, air_copy="one two three four")
    session.reconcile("1042", [ready, review, changed_latest], now=NOW)
    session.set_break_target("1042", 1, now=NOW)

    state = session.get_state("1042")
    budget = budget_for_state(state)

    assert budget.active_seconds == sum(
        entry.read_time_seconds for entry in state.active_air_ready_entries
    )
    assert budget.active_seconds == 2
    assert budget.target_seconds == 1
    assert budget.difference_seconds == 1
    assert budget.status == "over"
    assert len(state.review_entries) == 2


def test_break_budget_under_exact_over_and_target_is_game_local():
    session = RundownSession()
    item = versioned_fact(copy="one two three")
    session.pin_fact("1042", item, now=NOW)
    session.set_break_target("1042", 3, now=NOW)
    assert budget_for_state(session.get_state("1042")).status == "under"
    session.set_break_target("1042", 2, now=NOW)
    assert budget_for_state(session.get_state("1042")).status == "exact"
    session.set_break_target("1042", 1, now=NOW)
    assert budget_for_state(session.get_state("1042")).status == "over"
    assert session.ensure_state("1043", now=NOW).break_target_seconds == 30


def test_reconcile_same_changed_missing_and_downgraded_without_rewriting_snapshot():
    session = RundownSession()
    same = versioned_fact(subject_id="11", concept_key="same")
    changed = versioned_fact(subject_id="22", concept_key="changed")
    missing = versioned_fact(subject_id="33", concept_key="missing")
    downgraded = versioned_fact(subject_id="44", concept_key="downgraded")
    for item in (same, changed, missing, downgraded):
        session.pin_fact("1042", item, now=NOW)
    latest_changed = replace(changed, air_copy="Updated wording from the source.")
    latest_downgraded = replace(
        downgraded,
        verification_state=VerificationState.VERIFY,
        producer_confirmation_required=True,
        warning_reason="Verification was downgraded.",
    )

    state = session.reconcile(
        "1042",
        [same, latest_changed, latest_downgraded],
        now=NOW,
    )
    by_fact = {entry.fact_id: entry for entry in state.active_entries}

    assert by_fact[same.fact_id].reconciliation_state is ReconciliationState.CURRENT
    assert by_fact[changed.fact_id].reconciliation_state is ReconciliationState.SOURCE_CHANGED
    assert by_fact[changed.fact_id].fact_snapshot is changed
    assert by_fact[changed.fact_id].latest_fact is latest_changed
    assert by_fact[missing.fact_id].reconciliation_state is ReconciliationState.INVALIDATED
    assert (
        by_fact[downgraded.fact_id].reconciliation_state
        is ReconciliationState.VERIFICATION_DOWNGRADED
    )
    assert by_fact[downgraded.fact_id].fact_snapshot is downgraded


def test_replace_latest_requires_confirmation_and_preserves_entry_identity_order():
    session = RundownSession()
    original = versioned_fact()
    session.pin_fact("1042", original, now=NOW)
    latest = replace(original, air_copy="Latest approved wording.")
    session.reconcile("1042", [latest], now=NOW)
    before = session.get_state("1042").active_entries[0]

    with pytest.raises(RundownMutationError, match="confirmation"):
        session.replace_with_latest("1042", before.entry_id, confirmed=False, now=NOW)
    state = session.replace_with_latest(
        "1042", before.entry_id, confirmed=True, now=NOW
    )
    after = state.active_entries[0]
    assert after.entry_id == before.entry_id
    assert after.position == before.position
    assert after.fact_snapshot is latest
    assert after.reconciliation_state is ReconciliationState.CURRENT


def test_used_record_retains_version_after_reconciliation():
    session = RundownSession()
    original = versioned_fact()
    session.mark_fact_used("1042", original, now=NOW)
    latest = replace(original, air_copy="Changed after use.")

    state = session.reconcile("1042", [latest], now=NOW)

    assert state.used_history[0].fact_snapshot is original
    assert state.used_history[0].evidence_hash == original.evidence_hash
    assert session.used_version_changed("1042", latest)


def export_context():
    return RundownExportContext(
        game_id="1042",
        away_team="Chicago Bandits",
        home_team="Carolina Blaze",
        scheduled_time="July 28, 2026 7:00 PM ET",
        venue="Rosemont Stadium",
        snapshot_timestamp="2026-07-28T00:45:00+00:00",
    )


def test_plain_text_export_keeps_active_review_and_used_sections_separate():
    session = RundownSession()
    active = versioned_fact(
        subject_id="11", concept_key="active", copy="Active air-ready wording."
    )
    review = replace(
        review_fact(subject_id="22"), air_copy="Review-only wording."
    )
    used = versioned_fact(
        subject_id="33", concept_key="used", copy="Previously used wording."
    )
    session.pin_fact("1042", active, now=NOW)
    session.pin_fact("1042", review, now=NOW)
    session.mark_fact_used("1042", used, now=NOW)
    state = session.get_state("1042")

    text = render_rundown_export(state, export_context(), exported_at=NOW)

    assert "OFFICIAL GAME ID: 1042" in text
    assert "Chicago Bandits at Carolina Blaze" in text
    assert "VERIFY BEFORE AIR" in text
    assert "ACTIVE AIR-READY RUNDOWN" in text
    assert active.air_copy in text
    assert "NEEDS VERIFICATION" in text
    assert review.air_copy in text
    assert "USED-ON-AIR HISTORY" in text
    assert used.air_copy in text
    assert f"Estimated active read time: {state.remaining_read_seconds} sec" in text
    assert text.index(active.air_copy) < text.index(review.air_copy) < text.index(used.air_copy)


def test_export_filename_has_utc_game_revision_and_exclusive_write(tmp_path):
    state = GameRundownState.new("1042", now=NOW)
    filename = rundown_export_filename(state, exported_at=NOW)

    assert filename == "20260728T010203456789Z_game_1042_r0_rundown.txt"
    path = write_rundown_export_exclusive(
        tmp_path,
        state,
        export_context(),
        exported_at=NOW,
    )
    original = path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_rundown_export_exclusive(
            tmp_path,
            state,
            export_context(),
            exported_at=NOW,
        )
    assert path.read_text(encoding="utf-8") == original


def test_model_is_explicitly_session_only_and_serialization_ready():
    state = GameRundownState.new("1042", now=NOW)
    payload = state.to_dict()
    assert state.session_only is True
    assert payload["schema_version"] == 1
    assert payload["game_id"] == "1042"
    assert payload["created_at"].endswith("+00:00")
