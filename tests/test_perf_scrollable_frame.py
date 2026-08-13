"""PERF-001 — one shared, debounced scrollable-frame helper for every panel.

The five scrollable panels used to duplicate the same ``<Configure>`` pair.
The canvas half wrote ``itemconfigure(window, width=event.width)`` on every
resize step, which relayouts every widget inside the container — 886 of them
on Game Day. These tests pin the shared helper down: one definition site, a
debounced width write, and unchanged scrolling behaviour afterwards.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import ausl_stats_app


SOURCE = Path(ausl_stats_app.__file__).resolve().read_text(encoding="utf-8")

# Every scrollable panel, as (canvas attribute, canvas-window attribute).
# These are the five sites the tracker recorded at lines 2558, 2681, 2781,
# 2969, and 3488 of src/ausl_stats_app.py.
SCROLLABLE_PANELS = (
    ("fact_cards_canvas", "_fact_canvas_window"),
    ("what_changed_canvas", "_change_canvas_window"),
    ("rundown_canvas", "_rundown_canvas_window"),
    ("college_canvas", "_college_canvas_window"),
    ("comparison_canvas", "_comparison_canvas_window"),
)


def pump(root, predicate, *, timeout=10.0):
    """Drive the real Tk loop until ``predicate`` holds, as tools/*_gui_smoke."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for the debounced Tk callback")


@pytest.fixture(scope="module")
def tk_root():
    """One real, offline Tk root; skipped where no display is available.

    Module-scoped on purpose: each Tk initialisation is the slow and least
    reliable part of these tests, and every test tears its own canvas down.
    """

    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless CI has no display
        pytest.skip(f"Tk display unavailable: {exc}")
    root.geometry("420x220")
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


@pytest.fixture
def panel(tk_root):
    """One scrollable canvas/container pair built through the shared helper."""

    import tkinter as tk
    from tkinter import ttk

    canvas = tk.Canvas(tk_root, highlightthickness=0, width=400, height=200)
    canvas.pack(fill="both", expand=True)
    container = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=container, anchor="nw")
    for index in range(60):
        ttk.Label(container, text=f"row {index}", wraplength=300).pack(fill="x")
    binder = ausl_stats_app.DebouncedScrollableFrame(canvas, window, container)
    tk_root.update()
    try:
        yield canvas, container, window, binder
    finally:
        binder.cancel_pending()
        try:
            canvas.destroy()
        except tk.TclError:
            pass


def settle(root, binder):
    """Let the panel finish its initial layout, then reset the counters."""

    pump(
        root,
        lambda: binder.pending_width_id is None
        and binder.pending_scrollregion_id is None,
    )
    binder.width_writes = 0
    binder.applied_width = None


def test_one_shared_helper_is_the_only_configure_definition_site():
    """One definition site, not five: no panel binds <Configure> itself."""

    assert hasattr(ausl_stats_app, "DebouncedScrollableFrame")
    assert SOURCE.count('"<Configure>"') == 2, (
        "Exactly two <Configure> bindings may exist — the container and canvas "
        "binds inside DebouncedScrollableFrame. Every scrollable panel must "
        "route through the shared helper instead of duplicating the pair."
    )
    assert SOURCE.count(".itemconfigure(") == 1, (
        "The canvas-window width write must live in exactly one place."
    )
    assert SOURCE.count("_bind_scrollable_frame(") == len(SCROLLABLE_PANELS) + 1, (
        "Each of the five scrollable panels must call the shared helper once, "
        "alongside the single helper definition."
    )


def test_helper_debounce_interval_clears_one_game_day_relayout():
    """A single Game Day relayout measured ~156 ms; the timer must outlast it.

    At 120 ms the timer expired inside every drag step and the debounce bought
    nothing (294.4 ms/step against an undebounced 288.8). Anything at or below
    that floor silently reverts PERF-001 to a no-op.
    """

    assert ausl_stats_app.DebouncedScrollableFrame.WIDTH_DEBOUNCE_MS >= 200
    assert ausl_stats_app.DebouncedScrollableFrame.WIDTH_DEBOUNCE_MS == 250


def test_configure_burst_writes_the_width_once_after_the_debounce(tk_root, panel):
    """A rapid burst at differing widths costs one width write, not five."""

    canvas, _container, window, binder = panel
    settle(tk_root, binder)

    widths = (300, 340, 380, 420, 460)
    for width in widths:
        canvas.event_generate("<Configure>", width=width, height=200)
        assert binder.width_writes == 0, (
            "The <Configure> handler must not write itemconfigure(width=...) "
            "synchronously."
        )
        assert binder.pending_width_id is not None

    pump(tk_root, lambda: binder.pending_width_id is None)

    assert binder.width_writes == 1
    assert binder.applied_width == widths[-1]
    assert int(float(canvas.itemcget(window, "width"))) == widths[-1]


def test_each_event_cancels_and_reschedules_and_the_id_clears_on_fire(
    tk_root, panel, monkeypatch
):
    canvas, _container, _window, binder = panel
    settle(tk_root, binder)

    cancelled = []
    real_after_cancel = canvas.after_cancel

    def record_cancel(identifier):
        cancelled.append(identifier)
        return real_after_cancel(identifier)

    monkeypatch.setattr(canvas, "after_cancel", record_cancel)

    canvas.event_generate("<Configure>", width=300, height=200)
    first = binder.pending_width_id
    assert first is not None

    canvas.event_generate("<Configure>", width=360, height=200)
    second = binder.pending_width_id
    assert second is not None
    assert second != first, "Each new event must reschedule the debounce timer"
    assert cancelled == [first], "The superseded timer must be cancelled"

    pump(tk_root, lambda: binder.pending_width_id is None)

    assert binder.pending_width_id is None, (
        "The pending timer id must be cleared once the timer fires."
    )
    assert binder.width_writes == 1
    assert binder.applied_width == 360


def test_redundant_width_is_not_rewritten(tk_root, panel):
    canvas, _container, _window, binder = panel
    settle(tk_root, binder)

    canvas.event_generate("<Configure>", width=390, height=200)
    pump(tk_root, lambda: binder.pending_width_id is None)
    assert binder.width_writes == 1

    canvas.event_generate("<Configure>", width=390, height=200)
    pump(tk_root, lambda: binder.pending_width_id is None)
    assert binder.width_writes == 1, (
        "An unchanged width must not be written to the canvas window again."
    )


def test_scrollregion_settles_and_scrolling_still_works(tk_root, panel):
    canvas, _container, _window, binder = panel
    settle(tk_root, binder)

    canvas.event_generate("<Configure>", width=380, height=200)
    pump(
        tk_root,
        lambda: binder.pending_width_id is None
        and binder.pending_scrollregion_id is None,
    )

    region = str(canvas.cget("scrollregion")).strip()
    assert region, "The coalesced after_idle callback must set a scrollregion"
    assert [float(value) for value in region.split()][3] > 200, (
        "The scrollregion must cover the full container, not just the viewport"
    )

    canvas.yview_moveto(0.5)
    tk_root.update()
    assert abs(canvas.yview()[0] - 0.5) < 0.05


def test_scrollregion_updates_coalesce_into_one_idle_callback(tk_root, panel):
    """Container churn schedules one after_idle callback, not one per event."""

    import tkinter as tk
    from tkinter import ttk

    canvas, container, _window, binder = panel
    settle(tk_root, binder)
    binder.scrollregion_writes = 0

    for index in range(10):
        ttk.Label(container, text=f"extra {index}").pack(fill="x")
    container.event_generate("<Configure>", width=380, height=1200)
    first_pending = binder.pending_scrollregion_id
    assert first_pending is not None
    container.event_generate("<Configure>", width=380, height=1400)
    assert binder.pending_scrollregion_id == first_pending, (
        "A second scrollregion callback must not be scheduled while one is "
        "already pending."
    )

    pump(tk_root, lambda: binder.pending_scrollregion_id is None)
    assert binder.scrollregion_writes >= 1
    assert isinstance(canvas, tk.Canvas)


def test_teardown_during_shutdown_does_not_raise(tk_root, panel):
    """after_cancel/configure must survive the widget being destroyed."""

    canvas, _container, _window, binder = panel
    settle(tk_root, binder)

    canvas.event_generate("<Configure>", width=350, height=200)
    assert binder.pending_width_id is not None

    canvas.destroy()
    binder.cancel_pending()
    binder._apply_pending_width()
    binder._apply_scrollregion()

    assert binder.pending_width_id is None
    assert binder.pending_scrollregion_id is None
