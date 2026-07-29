# Phase 6 stabilization acceptance

Completion date: 2026-07-29

Status:
**PHASE 6 STABILIZATION COMPLETE — DISPLAY SCALING SIGN-OFF PENDING**

Branch: `agent/phase6-final-stabilization`

Starting commit:
`bca5be6286996da844e0f260ae1e06f1feaf054e`

Ending reviewed source commit:
`55a4af0` (`fix: stabilize Phase 6 search and comparison`)

The later documentation/acceptance commit changes no application behavior.
Its exact SHA is reported as the final branch head in the pull request and
completion report rather than self-referencing this file.

## Accepted scope

This narrow pass closes the four independent full-phase review findings:

1. restore the accidentally reverted Phase 6F tracker/guide status while
   preserving the approved Phase 7A–7E roadmap;
2. show each comparison fact's own canonical source, freshness, trust, and
   warning information;
3. assign Player Lookup expansion to the row that actually contains the list
   and player card;
4. support conservative partial first/last-name typos and ordinary straight or
   smart apostrophes without weakening explicit player selection.

Phase 7 was not started. No factual workbook, player/team value, new network
source, private producer file, graphics integration, or verification,
freshness, identity, approval, privacy, offline, session, refresh, atomic-write,
or last-known-good rule changed.

## Files changed

- `Implementation guide/AUSL_Broadcast_Stats_Implementation_Guide.md`
- `Implementation guide/AUSL_Broadcast_Stats_Improvement_Tracker.md`
- `Implementation guide/Phase_6_Stabilization_Acceptance_Record.md`
- `README.txt`
- `src/ausl_comparison.py`
- `src/ausl_search.py`
- `src/ausl_stats_app.py`
- `tests/test_phase6_stabilization_docs.py`
- `tests/test_phase6f_comparison.py`
- `tests/test_phase6f_search.py`
- `tests/test_phase6f_ui.py`
- `tools/phase6f_gui_smoke.py`

## Root causes and corrections

### Documentation status

PR #10 correctly installed the project owner's Phase 7 roadmap, but its
planning documents had been prepared before Phase 6F acceptance and therefore
reverted completed status to “not started.” The tracker and guide now record
Phase 6F's original commits, 750-test result, Windows smoke, exact completed
IDs, and remaining scaling/full-review limitations. The Phase 7 roadmap is
unchanged.

### Compare Players provenance

The comparison model already retained independent canonical `BroadcastFact`
objects, but the Tk renderer emitted only `[STATE]` plus `fact.air_copy`. A
generic `Source` line below the view described the statistical database and
could be mistaken for fact evidence.

`comparison_fact_display_text()` now renders, when present, the canonical
verification state, source name/reference/date/page/game, snapshot timestamp,
source-health state, and warning/confirmation reason. Missing fields say
unavailable; rendering does not mutate or promote the fact. Supporting sources
remain separate. The global database is now labeled `Statistics source` and
`Statistical snapshot`. The clipboard action is explicitly metrics-only and
does not silently add fact wording.

### Player Lookup resizing

`_build_lookup()` placed the feedback label on grid row 1 and the expanding
player list/card body on row 2, while assigning expansion weight to row 1.
Expansion weight now belongs only to row 2. The feedback row remains compact,
and the real-Tk smoke asserts both list/card viewports remain usable.

### Partial-name typos and apostrophes

Fuzzy ranking compared only the full normalized name and approved aliases, so
`Gacria` could not match the `Garcia` token even though `Rachel Gacria` could
match the full name. Token values now participate only in the final
conservative fuzzy stage; exact full/alias/token, prefix, and substring
precedence remains unchanged. Filters still apply before ranking, short
queries remain ineligible, candidates remain distinct/deterministic, and
possible typos never auto-select.

The query parser used `shlex` with both shell quote styles enabled, so an
ordinary unmatched apostrophe raised a malformed-quotation error. The lexer
now treats only double quotes as filter delimiters. Straight and smart
apostrophes are inert text, Windows path-like and command-like input remains
inert, and malformed double-quoted filters still fail safely.

## Failing-first evidence

Before implementation, the new focused command produced
**15 failed, 55 passed in 1.63 s**:

- seven parser/token-search failures;
- five per-fact/statistical-provenance failures;
- one Player Lookup grid-row failure;
- two stale-documentation failures.

The failures showed the prior malformed apostrophe behavior, empty partial-name
typo results, absent comparison formatting helpers, row 1 expanding instead of
row 2, and the reverted Phase 6F status. No existing assertion was weakened.

## Automated verification

Baseline from exact remote `main`:

`python -W error -m pytest -q`

- **750 passed in 17.84 s**

Initial implemented search/comparison/UI slice:

`python -W error -m pytest -q tests/test_phase6f_search.py tests/test_phase6f_comparison.py tests/test_phase6f_ui.py`

- **68 passed in 1.42 s**

Adjacent implementation matrix:

`python -W error -m pytest -q tests/test_phase6f_search.py tests/test_phase6f_comparison.py tests/test_phase6f_session.py tests/test_phase6f_ui.py tests/test_phase6e_session_schema.py tests/test_broadcast_facts.py tests/test_phase6b_fact_ui.py tests/test_official_note_selection.py tests/test_media_approval.py`

- **168 passed in 2.13 s**

Final Phase 6F/search/comparison/session/UI/docs:

`python -W error -m pytest -q tests/test_phase6f_search.py tests/test_phase6f_comparison.py tests/test_phase6f_session.py tests/test_phase6f_ui.py tests/test_phase6e_session_schema.py tests/test_phase6_stabilization_docs.py`

- **82 passed in 1.27 s**

Final Phase 6B fact/provenance/official-note/media/enrichment safety:

`python -W error -m pytest -q tests/test_broadcast_facts.py tests/test_phase6b_fact_ui.py tests/test_official_note_selection.py tests/test_media_approval.py tests/test_media_guide_identity.py tests/test_media_guide_quality.py tests/test_enrichment_safety.py`

- **106 passed in 1.76 s**

Final Phase 6D/6E session/change/refresh/offline interaction:

`python -W error -m pytest -q tests/test_phase6d_session_schema.py tests/test_phase6d_session_storage.py tests/test_phase6d_session_ui.py tests/test_phase6e_change_ui.py tests/test_phase6e_changes.py tests/test_phase6e_session_schema.py tests/test_phase6e_snapshot_integration.py tests/test_refresh_state.py tests/test_refresh_cancellation.py tests/test_app_refresh_cancellation.py tests/test_refresh_concurrency.py tests/test_refresh_staging.py tests/test_refresh_attempt_health.py tests/test_refresh_health.py tests/test_callbacks.py tests/test_offline_mode.py tests/test_phase6a_command_center.py`

- **163 passed in 8.10 s**

Build privacy and portable ZIP:

`python -W error -m pytest -q tests/test_build_privacy.py tests/test_portable_zip.py`

- **34 passed in 3.56 s**

Complete final offline suite:

`python -W error -m pytest -q`

- **769 passed in 22.73 s**

Release-integrity commands:

- `python -m compileall -q src tests tools` — passed.
- `python -m pip check` — no broken requirements.
- `python tools/verify_distribution.py data/exports` —
  `Clean distribution verified`.
- Git LFS materialization — all four tracked XLSX files have real ZIP/XLSX
  bytes and are listed as materialized LFS objects.
- `git diff --check` — passed.
- Tracked/history private-path and credential-pattern scans — zero matches.

All automated tests were network-independent.

## Windows GUI smoke

`python tools/phase6f_gui_smoke.py` passed using source/real-Tk execution on
`Windows-10-10.0.19045-SP0`, Python 3.12.10, at 1120×720 against the checked-in
local snapshot and an in-memory validated local replacement.

The smoke verified:

- correct row-2 expansion and usable Player Lookup list/card viewports;
- exact, typo, quoted-filter, invalid-filter, and explicit keyboard selection;
- two exact comparison identities and aligned neutral metrics;
- visible independent per-fact verification, source, snapshot, and health;
- separately labeled statistical snapshot and metrics-only copy;
- mouse-wheel scrolling;
- Local/Offline Mode with zero network calls;
- local database/index/comparison replacement;
- exact-game fact-context rebuilding;
- all eight tabs;
- schema-v3 save, normal close, and exact restart restoration.

## Remaining limitations

- `UI-002` remains open. The project owner will separately verify Windows
  display scaling at 100%, 125%, and 150%.
- Full Phase 6 acceptance is not recorded until that scaling sign-off and the
  final producer-workflow checklist are complete.
- Typo matching deliberately remains conservative and nonphonetic. Only
  explicit approved aliases are indexed.
- Comparison copy history remains in memory; session persistence continues to
  store only exact comparison identities and normalized scroll position.
- Cooperative cancellation cannot forcibly abort one `urllib` request already
  inside its bounded timeout; its late result remains harmless.
- Phase 7 has not started.

Verdict:
**PHASE 6 STABILIZATION COMPLETE — DISPLAY SCALING SIGN-OFF PENDING**
