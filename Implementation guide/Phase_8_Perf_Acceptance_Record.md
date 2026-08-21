# Phase 8 — UI responsiveness and data-path separation

Technical completion date: 2026-08-13.

Scope: `PERF-001`, `PERF-003`, `PERF-004` from tracker section
`P. UI responsiveness and data-path separation`. `PERF-002` (incremental
fact-card rendering) was deliberately excluded — it touches pinned, used, and
copy state and needs its own pass with its own review. `PERF-005` was not
started.

## Starting point

- Starting commit: `d55ee43` (`main`, merge of PR #19, Phase 7E).
- Branch: `agent/phase8-perf-responsiveness`.
- Interpreter: the pinned virtual environment at **Python 3.12.10**. The
  machine's default `python` on PATH is **3.14.6**, so every command in this
  record was run as `.venv\Scripts\python.exe`. This divergence is the
  subject of the still-open `PERF-005`.
- Tk 8.6.15, Windows 10 (10.0.19045).

### Baseline

The working tree was **not** clean at `d55ee43`. The four tracked LFS
workbooks, `update_manifest.json`, and `refresh_attempt.json` were all
modified, and eleven untracked enrichment workbooks sat in `data/exports`.
This is exactly the `PERF-003` defect, and it was severe enough to fail the
suite:

- `python -W error -m pytest -q` → **1 failed, 1062 passed**. The single
  failure was
  `test_build_privacy.py::test_checked_in_core_snapshot_passes_distribution_verification`,
  rejecting the eleven untracked workbooks.
- `python tools/verify_distribution.py data/exports` → **exit 1**, eleven
  violations.

`data/exports` was backed up, the tracked files were restored with
`git checkout --`, and the eleven untracked workbooks were moved to what
would become `data/runtime/exports`. That produced the clean baseline the
prompt expected:

- `python -m compileall -q src tests tools` → pass.
- `python -m pip check` → no broken requirements.
- `python -W error -m pytest -q` → **1063 passed in 82.25 s**.
- `python tools/verify_distribution.py data/exports` → **clean**.

## Per-unit commits

| Unit | Commit | Subject |
|---|---|---|
| Tracker section `P` | `231c924` | Add tracker section P for UI responsiveness and data-path separation |
| `PERF-001` | `ce06f85` | Extract one shared, debounced scrollable-frame helper |
| `PERF-003` | `1d79cbc` | Separate the runtime refresh target from the canonical snapshot |
| `PERF-004` | `d76da5a` | Add a resize-budget regression guard |

The tracker and this record are committed after `d76da5a`. The final branch
tip is reported in the pull request rather than referenced from inside a
committed file.

## Test counts

| Point | Result |
|---|---|
| Baseline at `d55ee43` (cleaned) | 1063 passed |
| After `PERF-001` | 1071 passed |
| After `PERF-003` | 1086 passed |
| After `PERF-004` | **1093 passed, 1 skipped in 100.72 s** |

The skip is the advisory wall-clock check in
`tests/test_ui_responsiveness_budget.py`, which asserts nothing and only runs
when `AUSL_ADVISORY_RESIZE_TIMING=1` is set.

All runs used `-W error`.

## `PERF-001` — shared debounced scrollable-frame helper

Five panels duplicated the same `<Configure>` pair. `DebouncedScrollableFrame`
replaces all five; each panel registers through `_bind_scrollable_frame`.

### The measurement did not reproduce at 120 ms

The tracker proposed a 120 ms debounce on the strength of a prototype that
measured 217.7 → 121.6 ms/step. **That result did not reproduce.** The
measurement harness drove the real app — nine tabs realised, one official
game selected, 60 facts, 886 fact-container widgets, 971 Game Day tab
widgets — and resized the window in fourteen steps, three to five runs per
configuration, reporting the median of the run means. Two drag models were
used and agreed: a forced-settle model (`update()` plus `update_idletasks()`
per step) and a 60 Hz live-drag model (geometry steps issued on a real-time
cadence, `update()` only).

An early version of the harness measured ~1 ms/step and was wrong: the app
pins `root.minsize(1120, 720)` (`src/ausl_stats_app.py:1556`), so a drag that
shrank the window was clamped and never resized at all. Growing the window
fixed it.

| Configuration | Forced-settle ms/step | 60 Hz drag ms/step |
|---|---|---|
| Base `d55ee43`, undebounced | 288.8 | 290.5 |
| Branch, **120 ms** debounce | 294.4 | 295.8 |
| Branch, **250 ms** debounce | 159.3 | 163.1 |
| Branch, 400 ms debounce | 160.5 | 166.1 |
| Branch, debounce raised so it cannot fire mid-drag | 157.0 | — |
| Canvas `<Configure>` unbound entirely (the ceiling) | 156.2 | — |

The mechanism is sound — deferring the width write reaches the unbound
ceiling — but a single Game Day relayout costs **~156 ms** on this machine,
so a 120 ms timer expires inside every drag step and the write happens
anyway. The debounce interval has to outlast one relayout or it is a no-op.

The container `<Configure>` counts confirm the chain: across the same drag
the container reconfigured **46** times with the 120 ms interval and **once**
when the width write was deferred or removed.

**Shipped: 250 ms**, on the project owner's decision after this evidence was
presented. Final measurement of the shipped configuration, five runs:
**159.8 ms/step** forced-settle and **159.0 ms/step** live-drag against the
288.8 / 290.5 base — a **44.7%** improvement, matching the 44.1% the
prototype predicted, and landing on the 156.2 ms ceiling.

Run-to-run spread, stated honestly: the review recorded 218–330 ms/step for
identical code, and this pass saw 287.6–329.4 ms/step on the base and
291.1–302.6 ms/step at 120 ms. Only within-run A/B deltas are treated as
reliable. Absolute figures are not comparable across machines or runs, which
is why `PERF-004` asserts structure rather than time.

### Behaviour verification

- Scrollregion after the debounce settles: `0 0 1225 9735` (non-empty and
  covering the full container).
- `yview_moveto(0.5)` resolves to exactly **0.5**.
- `tools/phase6f_gui_smoke.py` → `session_restored_exactly: true`,
  `comparison_scroll: true`, `tabs_opened: 9`, `network_calls: 0`.
  Session scroll restore is scheduled from `src/ausl_stats_app.py:1925` and
  depends on the scrollregion; it is unchanged.
- `tools/phase7e_gui_smoke.py` → `status: passed`, 118 college résumés,
  8 connections.
- Mousewheel behaviour is untouched, including the `add="+"`
  `<MouseWheel>` / `<Button-4>` / `<Button-5>` binds on the college and
  comparison panels.
- `_on_close` now cancels both pending timers explicitly, alongside the
  existing session-autosave cancellation.

`wraplength` was not touched; the review had already measured and rejected
it (121.2 ms against 121.6 ms).

## `PERF-003` — runtime refresh target separated from the canonical snapshot

`ausl_data.py` now distinguishes four roles:

| Function | Role |
|---|---|
| `canonical_export_dir()` | the tracked `data/exports` snapshot |
| `runtime_export_dir()` | untracked `data/runtime/exports`, never created just by reading |
| `refresh_output_dir()` | where a refresh writes |
| `active_export_dir()` | where the loader reads |

`export_dir()` keeps its previous meaning — the configured snapshot
directory — so producer-local state (manual notes, locked lineups, game
packets) and the distribution resolve exactly as before.

Deliberate decisions:

- **A partial runtime directory is ignored, not merged.** Mixing a fresh
  runtime roster with a stale canonical workbook would produce a snapshot no
  `update_manifest.json` describes. `active_export_dir()` prefers the runtime
  directory only when all four core workbooks and `update_manifest.json` are
  present and non-empty.
- **An explicitly redirected `export_dir` stays authoritative** for both read
  and write. The portable build, the GUI smokes, and a dozen existing tests
  redirect it on purpose; the runtime split applies only to a default
  installation.
- **Refresh attempts** are written beside the runtime output and read from
  the runtime copy when it exists, falling back to the canonical copy so a
  fresh install still reads the attempt that shipped with it.
- **College artifacts stay canonical-only.** `ausl_college_store.default()`
  lists `data/exports` as a fallback approved directory
  (`src/ausl_college_store.py:77` and `:82`), but refresh never writes
  approved college envelopes or connection artifacts — an approval tool does,
  as a deliberate developer-gated step, and the results are packaged for
  distribution. Routing them through an untracked runtime directory would
  create a second approval surface. Approval semantics are unchanged either
  way.

Staging, atomic promotion, and last-known-good restore are untouched; only
the directory they operate in changed.

`tests/test_production_snapshot_regression.py` now pins itself to
`canonical_export_dir`. It is the checked-in snapshot's guard and must read
the tracked workbooks whether or not the machine running it has a local
refresh installed. Without this pin it failed locally against the newer
runtime snapshot while still passing in CI — precisely the divergence this
unit exists to remove.

### Promotion

`tools/promote_runtime_snapshot.py` replaces the side effect. It verifies a
staged copy with the same `scan_distribution` CI runs, regenerates
`distribution_manifest.json`, refuses Git LFS pointer text and incomplete or
empty snapshots, and is a dry run unless `--confirm` is passed. It also
refuses to run on anything but Python 3.12. No UI was added, as scoped.

The dry run was exercised against the real local runtime snapshot; it
reported all six core exports as `CHANGED` and wrote nothing. **Promotion
was deliberately not executed**, because this work must leave the tracked
workbooks byte-identical.

### Local migration

The eleven untracked enrichment workbooks found in `data/exports` at the
start were refresh output. They were moved to `data/runtime/exports`, and the
matching core workbooks from the same refresh (recovered from the pre-restore
backup) were placed alongside them, so the runtime directory holds one
complete, self-consistent snapshot rather than a partial one. The loader
prefers it; the canonical snapshot is untouched.

## `PERF-004` — resize-budget regression guard

`tests/test_ui_responsiveness_budget.py`. Structural budgets only. The guard
fails when:

- a `<Configure>` binding exists outside `DebouncedScrollableFrame`;
- `itemconfigure(..., width=...)` is reachable anywhere but the debounced
  helper;
- a scrollable panel does not register through `_bind_scrollable_frame`;
- the debounce interval drops below one Game Day relayout, which would revert
  `PERF-001` to a no-op without changing any structure;
- the helper stops cancelling its timer, coalescing the scrollregion into
  `after_idle`, guarding teardown, or skipping a redundant width write;
- the Game Day fact container exceeds **1060** widgets or the tab exceeds
  **1165**.

The ceilings come from measurements taken on 2026-08-13 against the
checked-in snapshot with one official game selected — **886** in the fact
container and **971** on the tab — plus roughly 20% headroom, so an ordinary
new Phase 8 panel does not trip the guard while a rebuild that doubles the
tree does. The numbers and their date are recorded next to the constants.

No wall-clock assertion is in the CI path. One advisory check exists, asserts
nothing, and is skipped unless `AUSL_ADVISORY_RESIZE_TIMING=1` is set.

**Guard verified by reintroduction.** A raw duplicated `<Configure>` pair was
temporarily restored in `_build_rundown_panel`. Three guard tests failed with
actionable messages:

- `test_the_shared_helper_owns_every_configure_binding` —
  "2 `<Configure>` binding(s) live outside the shared helper"
- `test_no_undebounced_canvas_width_write_exists`
- `test_every_scrollable_panel_registers_with_the_shared_helper` —
  "Expected 5 scrollable panels ... found 4"

The pair was then reverted and all fifteen `PERF-001` / `PERF-004` tests
passed.

## Integrity control

The control the acceptance records have tracked since Phase 7C, run after
every unit:

```
git diff --stat -- data/exports        # empty
git lfs ls-files | findstr exports     # unchanged
python tools/verify_distribution.py data/exports   # clean
```

Final state:

- `git diff --stat -- data/exports` → **empty**.
- Git LFS object IDs for the four workbooks, unchanged from `d55ee43`:

  | Workbook | SHA-256 | Bytes |
  |---|---|---|
  | `ausl_rosters.xlsx` | `fa7e390b645bccea2497eca95eebb914e9cff6e5da214e1604f9b3235eb07840` | 33548 |
  | `ausl_season_stats.xlsx` | `f4aa966c94802944ceba3bfbeeddc54e135b1d13518867945e7e7419f54d8caa` | 98380 |
  | `ausl_career_stats.xlsx` | `c2cfb23f4247baf3baefd40f2dd9cfe34a5ca7c532da9f77238a0bc4a2dc3773` | 37535 |
  | `ausl_team_context.xlsx` | `45e60f70ee341a4fe805ad463a1ff6db52fa456004aeec4097788e6b2b5189eb` | 16585 |

- `python tools/verify_distribution.py data/exports` → **clean**.
- `data/exports` remains tracked in Git LFS and was never added to
  `.gitignore`. `data/runtime/` was added, alongside the existing
  `data/exports/game_packets/` and `data/manual/` entries.

## Constraints held

- No change to verification, freshness, identity, approval, privacy,
  offline, session, refresh, atomic-write, or last-known-good rules.
- No new network source. No factual value changed.
- No college data, connection, or approval artifact changed.
- Core packages remain college-free.

## Remaining limitations

1. **`PERF-002` is untouched.** `_render_fact_cards()` still destroys and
   rebuilds every card, costing 824–1303 ms per call across seven call sites.
   It remains the longest single UI freeze in the application and the one a
   producer changing a filter mid-broadcast is most likely to feel. The
   `PERF-001` gain does not reduce it.
2. **`PERF-005` is untouched.** The default `python` on PATH is still 3.14.6
   against a pinned 3.12.10, and `.github/workflows/ci.yml` is still titled
   `Phase 5 CI`. `tools/promote_runtime_snapshot.py` asserts its own
   interpreter version, but no other tool script does.
3. **The 250 ms interval is calibrated to one machine.** It was chosen to
   outlast a ~156 ms Game Day relayout measured here. On slower truck
   hardware a single relayout could exceed 250 ms, and the debounce would
   again fire mid-drag and stop helping. The `PERF-004` guard catches the
   interval being lowered, but it cannot detect hardware that is slower than
   the interval. Re-measuring on the truck machine is worthwhile before the
   producer demo.
4. **Resize timing is not covered in CI**, by design. The 218–330 ms
   run-to-run spread makes any wall-clock assertion flaky. The structural
   guard is the CI signal; timing must be re-measured by hand.
5. **The real-Tk tests skip on headless CI.** `tests/test_perf_scrollable_frame.py`
   and the widget-count budgets in `tests/test_ui_responsiveness_budget.py`
   need a display, so they skip on the `ubuntu-latest` CI leg and run on the
   `windows-latest` leg. The source-level guards run everywhere. One
   transient Tcl initialisation failure was observed during development; the
   Tk root fixture is module-scoped to keep initialisations to a minimum.
6. **The local runtime snapshot has not been promoted.** `data/runtime/exports`
   holds a newer refresh (`updated_at` 2026-08-12) than the canonical
   snapshot (2026-07-23). The application now prefers it locally. Promoting
   it into the tracked snapshot is a separate, deliberate decision, made with
   `tools/promote_runtime_snapshot.py --confirm` and committed on its own.
7. **No producer or truck-hardware verification.** Everything in this record
   is offline, on one Windows 10 development machine. Windows display
   scaling at 100%, 125%, and 150% was not re-checked for this pass.
