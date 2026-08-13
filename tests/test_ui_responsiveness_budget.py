"""PERF-004 — a resize-budget guard that fails before responsiveness rots.

Same shape as the `SEASON-001` hardcoded-year guard in
test_hardcoded_season_years.py: a source-level scan that fails when a Phase 8
panel silently reintroduces the cost `PERF-001` removed.

The budgets here are structural, not wall-clock. Game Day resize measured
218-330 ms/step across runs of identical code during the review, so a timing
assertion in CI would be flaky and would eventually be deleted by whoever it
annoyed. One advisory wall-clock check lives at the bottom, skipped unless
explicitly opted into, and never runs in CI.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import ausl_stats_app


APP_SOURCE_PATH = Path(ausl_stats_app.__file__).resolve()
APP_SOURCE = APP_SOURCE_PATH.read_text(encoding="utf-8")

# Every scrollable panel, as (canvas attribute, canvas-window attribute).
SCROLLABLE_PANELS = (
    ("fact_cards_canvas", "_fact_canvas_window"),
    ("what_changed_canvas", "_change_canvas_window"),
    ("rundown_canvas", "_rundown_canvas_window"),
    ("college_canvas", "_college_canvas_window"),
    ("comparison_canvas", "_comparison_canvas_window"),
)

# Measured on 2026-08-13 against the checked-in snapshot with one official
# game selected: 886 widgets in the Game Day fact container and 971 on the
# tab. The ceilings add roughly 20% headroom so an ordinary Phase 8 panel
# does not trip the guard, while a rebuild that doubles the tree does.
FACT_CONTAINER_WIDGET_CEILING = 1060
GAME_DAY_TAB_WIDGET_CEILING = 1165

# itemconfigure(..., width=...) on a canvas window relayouts everything the
# window contains. It is the single most expensive thing a <Configure>
# handler can do, and it must only ever happen inside the shared helper.
_WIDTH_WRITE = re.compile(r"\.itemconfigure\(\s*[^)]*\bwidth\s*=")
_CONFIGURE_BIND = re.compile(r"\.bind\(\s*[\"']<Configure>[\"']")


def _helper_source() -> str:
    """The DebouncedScrollableFrame class body, as text."""

    start = APP_SOURCE.index("class DebouncedScrollableFrame:")
    rest = APP_SOURCE[start:]
    end = rest.index("\nclass ", 1)
    dataclass_marker = rest.find("\n@dataclass")
    if 0 <= dataclass_marker < end:
        end = dataclass_marker
    return rest[:end]


def test_the_shared_helper_owns_every_configure_binding():
    """No panel may bind <Configure> outside DebouncedScrollableFrame."""

    helper = _helper_source()
    total = len(_CONFIGURE_BIND.findall(APP_SOURCE))
    inside_helper = len(_CONFIGURE_BIND.findall(helper))

    assert inside_helper == 2, (
        "DebouncedScrollableFrame must bind <Configure> exactly twice: once "
        "on the container for the scrollregion, once on the canvas for the "
        "debounced width write."
    )
    assert total == inside_helper, (
        f"{total - inside_helper} <Configure> binding(s) live outside the "
        "shared helper. Route the panel through _bind_scrollable_frame "
        "instead of duplicating the pair -- that duplication is what "
        "PERF-001 removed."
    )


def test_no_undebounced_canvas_width_write_exists():
    helper = _helper_source()
    total = len(_WIDTH_WRITE.findall(APP_SOURCE))
    inside_helper = len(_WIDTH_WRITE.findall(helper))

    assert inside_helper == 1
    assert total == 1, (
        "itemconfigure(..., width=...) must only be reachable through the "
        "debounced helper. A synchronous width write in a <Configure> "
        "handler relayouts every widget in the container on every resize "
        "step."
    )


def test_every_scrollable_panel_registers_with_the_shared_helper():
    for canvas_attribute, window_attribute in SCROLLABLE_PANELS:
        assert f'"{canvas_attribute}",' in APP_SOURCE, (
            f"{canvas_attribute} must be registered by name so this guard can "
            "see it"
        )
        assert window_attribute in APP_SOURCE

    registrations = APP_SOURCE.count("self._bind_scrollable_frame(")
    assert registrations == len(SCROLLABLE_PANELS), (
        f"Expected {len(SCROLLABLE_PANELS)} scrollable panels to register "
        f"with the shared helper, found {registrations}. A new scrollable "
        "panel must call _bind_scrollable_frame and be added to "
        "SCROLLABLE_PANELS here."
    )


def test_the_debounce_still_outlasts_one_game_day_relayout():
    """A shorter interval silently reverts PERF-001 to a no-op.

    One Game Day relayout measured ~156 ms. At 120 ms the timer expired
    inside every drag step and the debounce bought nothing: 294.4 ms/step
    against an undebounced 288.8.
    """

    assert ausl_stats_app.DebouncedScrollableFrame.WIDTH_DEBOUNCE_MS >= 200


def test_the_helper_still_cancels_and_coalesces():
    """The three properties that make the helper cheap, pinned as source."""

    helper = _helper_source()

    assert "after_cancel" in helper, "the debounce must cancel its own timer"
    assert "after_idle" in helper, (
        "the scrollregion update must be coalesced into one idle callback"
    )
    assert "(tk.TclError, ValueError)" in helper, (
        "after_cancel and configure must be guarded so teardown during "
        "shutdown cannot raise"
    )
    assert "width == self.applied_width" in helper, (
        "a redundant width must not be rewritten"
    )


@pytest.fixture(scope="module")
def game_day_widget_counts():
    """Realise the real Game Day tab once and count its widget tree."""

    tk = pytest.importorskip("tkinter")
    pytest.importorskip("pandas")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless CI has no display
        pytest.skip(f"Tk display unavailable: {exc}")

    import ausl_data
    from ausl_facts import FactCollection
    from ausl_session import SessionStore
    import tempfile
    import time

    def count(widget):
        return 1 + sum(count(child) for child in widget.winfo_children())

    original_load_initial = ausl_stats_app.AUSLStatsApp._load_initial
    original_lineups = ausl_stats_app.AUSLStatsApp.load_locked_lineups
    ausl_stats_app.AUSLStatsApp._load_initial = lambda self: None
    ausl_stats_app.AUSLStatsApp.load_locked_lineups = (
        lambda self: ausl_data.empty_locked_lineup_store()
    )
    temporary = tempfile.TemporaryDirectory(prefix="ausl-perf004-")
    try:
        database = ausl_data.load_database(include_enrichment=True)
        app = ausl_stats_app.AUSLStatsApp(
            root, session_store=SessionStore(Path(temporary.name) / "session")
        )
        root.geometry("1120x720")
        root.update()
        app._finish_load(database)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            root.update()
            collection = app._fact_collection
            if (
                isinstance(collection, FactCollection)
                and collection.game_id == app.selected_game.game_id
            ):
                break
            time.sleep(0.01)
        else:
            pytest.skip("fact collection did not settle offline")
        root.update_idletasks()
        game_day_tab = app.main_tabs.nametowidget(app.main_tabs.tabs()[0])
        yield {
            "facts": len(app._fact_collection.facts),
            "container": count(app.fact_cards_container),
            "tab": count(game_day_tab),
        }
    finally:
        ausl_stats_app.AUSLStatsApp._load_initial = original_load_initial
        ausl_stats_app.AUSLStatsApp.load_locked_lineups = original_lineups
        try:
            root.destroy()
        except tk.TclError:
            pass
        temporary.cleanup()


def test_game_day_fact_container_stays_within_its_widget_budget(
    game_day_widget_counts,
):
    container = game_day_widget_counts["container"]

    assert container <= FACT_CONTAINER_WIDGET_CEILING, (
        f"The Game Day fact container holds {container} widgets against a "
        f"{FACT_CONTAINER_WIDGET_CEILING} ceiling (886 measured on "
        "2026-08-13). Every one of them relayouts on each resize step. "
        "Raise the ceiling only with a fresh measurement recorded alongside "
        "it."
    )


def test_game_day_tab_stays_within_its_widget_budget(game_day_widget_counts):
    tab = game_day_widget_counts["tab"]

    assert tab <= GAME_DAY_TAB_WIDGET_CEILING, (
        f"The Game Day tab holds {tab} widgets against a "
        f"{GAME_DAY_TAB_WIDGET_CEILING} ceiling (971 measured on "
        "2026-08-13)."
    )


@pytest.mark.skipif(
    os.environ.get("AUSL_ADVISORY_RESIZE_TIMING") != "1",
    reason=(
        "Advisory and local-only. Game Day resize measured 218-330 ms/step "
        "across runs of identical code, so this is not a CI signal. Run with "
        "AUSL_ADVISORY_RESIZE_TIMING=1 to see the number locally."
    ),
)
def test_advisory_local_resize_timing(game_day_widget_counts, capsys):
    """Advisory only. Never asserted, never run in CI."""

    with capsys.disabled():
        print(
            "\nAdvisory: Game Day carries "
            f"{game_day_widget_counts['container']} fact-container widgets and "
            f"{game_day_widget_counts['tab']} tab widgets across "
            f"{game_day_widget_counts['facts']} facts. Resize timing is "
            "measured out of band; see Phase_8_Perf_Acceptance_Record.md."
        )
