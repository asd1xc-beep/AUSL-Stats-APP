# Phase 6F acceptance — Faster Discovery and Player Comparison

Completion date: 2026-07-29

Branch: `agent/phase6f-search-compare`

Starting commit: `d7f255b273acfc52f24aea98c544bbb945391f2b`

Reviewed implementation commits:

- `14356a1` — deterministic indexed player discovery and failing-first tests;
- `20745a0` — canonical neutral comparison model and failing-first tests;
- `846cbfc` — keyboard-first lookup/comparison UI, schema-v3 recovery, and
  Windows smoke harness.

## Accepted scope

Phase 6F completes `SEARCH-004`, `SEARCH-005`, `UX-011`, and `UI-003`, plus
the Player Lookup/Compare Players portion of `UI-001`. `UI-002` remains open.
The full Phase 6 cross-phase review is pending. Phase 7 has not started.

No factual workbook/player/team values, new network source, Phase 7 feature,
phonetic guess, generative wording, winner judgment, or automatic fuzzy
selection was added.

## Canonical search design

`src/ausl_search.py` is GUI-free and network-free. It builds one immutable
local roster index for each installed database and retains exact player ID,
name, explicitly approved aliases, team, jersey, normalized position, and
canonical roster status.

The parser accepts free name text and safely quoted/AND-combined filters:

- `team:CHI` or `team:"Chicago Bandits"`;
- `pos:P`;
- `status:active`, `status:inactive`, `status:reserve`, or `status:unknown`;
- `number:22`, `#22`, or plain `22`;
- `name:"Rachel Garcia"`.

Unknown keys/values, conflicts, malformed quotes, and nonsensical combinations
produce visible validation issues. Input remains inert text.

Filters apply before text ranking. Ranking is exact full name, exact approved
alias, exact name token, prefix, substring, then conservative length-aware
bounded Damerau-Levenshtein. Selected-game relevance and active context are
tie-breakers only and never suppress an exact inactive player. Final ordering
is deterministic by canonical identity. Results are capped at 50 with a
visible total/truncation state.

Explicit team filters temporarily override selected-game scope without
mutating the saved preference. An exact player outside the selected game is
explained rather than silently omitted. A possible typo is labeled and never
selected automatically.

## Comparison design

`src/ausl_comparison.py` owns one typed, aligned, neutral model. Its stable
metric registry covers:

- current-season batting, pitching, and fielding;
- AUSL-career batting, pitching, and fielding.

It reuses the canonical pitching WHIP and innings conversions. Formatters
render invalid/missing values as unavailable, never zero or `nan`. Two-way
players retain both roles. Inactive, reserve, unknown-status, and teamless
identities retain warnings.

Each side keeps its exact player/team identity, metric provenance, and
independently filtered canonical exact-game facts. Wrong-game fact collections
are rejected. The model has no winner, score, recommendation, or
better-player field.

The Compare Players tab renders one scrollable aligned view with source,
snapshot, selected-game context, verified/review fact labels, Swap/Clear, and
Copy Comparison + Sources. Copy includes both identities, source, freshness,
game context, and verify-before-air status. Its canonical copy record is
in-memory only.

## Keyboard, refresh, and recovery behavior

Player Lookup distinguishes list highlight from explicit selection.

- Ctrl+F opens/focuses Player Lookup.
- Up/Down moves the highlight.
- Enter or double-click explicitly opens the highlighted identity.
- Escape clears the active lookup.
- Ctrl+1 / Ctrl+2 assign the highlighted or selected player to comparison
  left/right.

Multiline Text editors retain their shortcuts. Player Lookup and Compare
Players both have visible vertical scrollbars; the comparison surface supports
Windows/macOS wheel deltas and X11 button events.

Each installed database rebuilds the index once and invalidates comparison
copy state. A database replacement rebuilds comparison values. A removed
player leaves the saved exact ID visibly unavailable; no replacement is
guessed. Exact-game changes discard old fact context and rebuild against the
new canonical collection. Local/Offline Mode retains all local search and
comparison behavior.

Producer-session schema version 3 explicitly migrates versions 1 and 2. It
stores only exact left/right player IDs and normalized comparison scroll.
Rows, workers, widget state, and copy records are not serialized. Corrupt
comparison state is dropped with a warning without losing valid game, rundown,
used-history, or What Changed state.

## Failing-first evidence

1. The initial search slice failed at collection with
   `ModuleNotFoundError: No module named 'ausl_search'`.
2. The initial comparison slice failed at collection with
   `ModuleNotFoundError: No module named 'ausl_comparison'`.
3. The initial session slice failed at collection because
   `SessionComparisonState` did not exist.
4. The first parser implementation then exposed two narrow failures: Windows
   path-like text was interpreted as an unknown filter, and the test's
   deterministic last-name order expectation was incorrect. The parser now
   treats drive-like text as inert; the test asserts the documented canonical
   ordering.
5. The first GUI smoke exposed two harness assumptions rather than product
   safety failures: background Tk focus required an explicit smoke-only
   `focus_force`, and nondeterministic set selection could choose a roster
   position outside the supported filter vocabulary. The harness now chooses
   deterministic active identities with supported positions.

No exact-identity, privacy, trust, atomic-write, last-known-good, or
verification assertion was weakened.

## Verification

- Clean Phase 6E baseline: **695 passed in 23.39 s**.
- Phase 6F search/comparison/session/UI plus adjacent schema/search tests:
  **83 passed in 1.16 s**.
- Phase 6A–6F search, readiness, fact, rundown, session, changes, refresh,
  callback, offline, official-note, media, team, formatting, and copy matrix:
  **432 passed in 7.22 s**.
- Complete offline suite with warnings as errors:
  **750 passed in 24.17 s**.
- `python -m compileall -q src tests tools`: passed.
- `python -m pip check`: no broken requirements.
- `python tools/verify_distribution.py data/exports`: passed.
- Git LFS materialization, whitespace validation, tracked-content privacy scan,
  and tracked/history secret scans: passed.

All automated tests were network-independent.

## Windows GUI smoke

`tools/phase6f_gui_smoke.py` passed on
`Windows-10-10.0.19045-SP0`, Python 3.12.10, real Tk source execution at
1120×720, using the checked-in local snapshot and an in-memory validated local
replacement.

It exercised exact search, conservative typo labeling, structured filters,
invalid filters, keyboard highlight/selection, two exact comparison sides,
aligned metrics, no-winner policy, scrollbar/wheel movement, copy with both
sources/identities, Local/Offline Mode, local database/index/comparison
replacement, exact-game fact-context rebuild, all eight tabs, schema-v3 save,
normal close, and exact restart restoration. Observed network calls: zero.

## Remaining limitations

- The requested full Phase 6 cross-phase review is still pending.
- `UI-002` is still open. The automated smoke covers the minimum 1120×720
  window, but no claim is made for 100%, 125%, and 150% Windows display scaling.
- Alias matching is deliberately limited to explicit approved roster aliases.
  The app does not infer nicknames or import aliases from narrative media text.
- Typo tolerance is conservative edit distance, not phonetic matching. Low
  recall is preferred to a false identity.
- Comparison displays only metrics in the stable registry and canonical facts
  already available for the exact selected game. Unsupported/missing material
  remains unavailable.
- Comparison copy history remains in memory and is not restored after restart.
- Phase 7 has not started.

Verdict:
**PHASE 6F COMPLETE — FULL PHASE 6 REVIEW PENDING**.
