# Phase 6E acceptance — Post-refresh What Changed

Completion date: 2026-07-28

Branch: `agent/phase6e-what-changed`

Starting commit: `b00027b7eb85bdc474bff1bc76bd347cc03af70f`

Final implementation commit: `f3c7076`

Reviewed implementation commits:

- `4fc2736` — deterministic snapshot/change model and failing-first tests;
- `aafd8f4` — explicit producer-session schema-v2 migration;
- `c8d05f3` — material source adapters and conservative severity policies;
- `e989434` — Game Day workflow, bounded worker, acknowledgements, and readiness;
- `f3c7076` — checked-in snapshot integration and persistence bounds.

## Accepted scope

Phase 6E implements only `UX-004`. Phase 6F fuzzy search and player
comparison have not started. No factual workbook/player/team data, new network
source, generative wording, automatic pin replacement, or Phase 6F interface
was added.

## Canonical digest and event design

`src/ausl_changes.py` is GUI-free and network-free. It defines:

- a versioned `BroadcastSnapshotDigest`;
- normalized roster, official team, exact-game schedule/final-score, lineup,
  source-health, and canonical-fact records;
- an immutable typed `ChangeEvent`;
- separate blocking, attention, and informational severity;
- a complete `ChangeComparison` with before/after snapshot identity;
- a pure comparison context for exact selected-game, pinned-version, and
  used-version impact.

Snapshot identity is a deterministic SHA-256 over normalized material content
and authoritative source/content identity. Input ordering, UI state,
comparison time, and wall-clock-only import timestamp changes do not alter the
identity. Routine batting/pitching rows are deliberately absent; a statistical
change enters the report only when it changes a canonical `BroadcastFact`
evidence version.

Every event ID is deterministic for the same before/after snapshots, type,
scope, and canonical subject identity. Detection time is display metadata and
does not affect event identity. Exact player/team/game/season/fact IDs are
retained where applicable. Similar wording is never used to link facts.
Milestone watch-to-reached transitions collapse only when canonical subject,
season, game, and `concept_key` identity match.

Manual producer-note headline/copy is redacted from the digest. Only the
canonical identity/evidence hash, generic producer-note label, trust state,
and concise source identity needed for comparison remain.

## Detection and severity policy

Accepted material categories are:

- roster add/remove, team assignment, status, jersey, and position;
- official W-L, rank, games back, and streak;
- exact-game schedule time, venue, status, and final score;
- exact-game locked-lineup membership/source/revision;
- source-health regression and recovery;
- canonical fact add/remove/evidence/wording/provenance/trust changes;
- verification upgrade/downgrade;
- milestone watch-to-reached transitions;
- pinned-current-version and used-on-air-history impact.

Source-health red/unknown regression, selected-game confirmed/official lineup
invalidation, and pinned or selected-game air-ready fact invalidation are
blocking. Relevant pinned/used/current-game changes are otherwise attention.
Ordinary official record/context changes are informational. The policy is pure
and independently tested.

Acknowledgement changes only persisted event identity. It never edits a fact,
verification, source health, lineup, readiness input, used history, or pinned
entry. Acknowledging a blocking event therefore does not make readiness green.
Pinned wording is never silently rewritten; the existing explicit confirmed
`Replace With Latest` operation remains the only replacement path.

## Baseline lifecycle and refresh safety

The first validated installed snapshot establishes a baseline and intentionally
produces no all-added report. A later successful core refresh or validated
local reload builds a complete new digest and comparison, then promotes the
new baseline only after diff success.

Failed or cancelled refreshes do not create factual change events and do not
alter the baseline/latest complete report. Comparison failure also preserves
both and displays an unavailable/error state. Refresh outcome metadata is
persisted separately.

One local worker processes digest/diff work with at most one coalesced
replacement. Generation, database-object identity, and exact selected-game
identity are checked before main-thread promotion. A selected-game change
queues the latest replacement when an old comparison is running or awaiting
callback. Late callbacks cannot promote state. Shutdown invalidates pending
work. Fact/digest generation performs no network access and remains available
in Local/Offline Mode.

## Private session schema migration

`src/ausl_session.py` now uses schema version 2. Version 1 is explicitly
migrated with safe defaults while preserving:

- exact selected-game identity;
- every canonical pinned/used rundown entry and order;
- break target, reconciliation, and timestamps;
- existing fact filters, selected player, view, and scroll state.

Schema v2 atomically stores the Phase 6E baseline, latest complete comparison,
acknowledgement IDs, five compact history summaries, refresh/comparison
metadata, change filters, and normalized scroll position. Acknowledgements are
bounded at 1,000 and a comparison at 300 events. Oversized state retains the
existing 5 MiB fail-closed session limit.

Corrupt/incompatible Phase 6E state is discarded with a visible recovery
warning instead of making an otherwise valid Phase 6D session or rundown
unrecoverable. Future top-level session schema remains fail-closed.

## Game Day workflow

The new scrollable `What Changed?` subview provides:

- blocking/attention/informational counts;
- All Changes, Needs Attention, Selected Game, Pinned, and Used views;
- exact team and category filters;
- severity, category, headline, before, after, impact, source, and detection
  context on each card;
- Acknowledge/Unacknowledge and Acknowledge Visible;
- Review Current Fact, Review Pinned, confirmed Replace With Latest, and Source
  Details where applicable;
- honest first-baseline, no-change, no-filter-match, failed-refresh,
  cancelled-refresh, and comparison-unavailable states;
- mouse-wheel and scrollbar navigation with persisted scroll position.

Only blocking material changes relevant to the current selected game, a
pinned rundown, or global source health feed the existing readiness policy.
Switching games filters by exact current game ID; a stale historical
`selected_game_impact` flag cannot leak an old repeat-matchup game into the
new game view.

## Failing-first evidence

1. The first 17 model tests failed at collection with
   `ModuleNotFoundError: No module named 'ausl_changes'`.
2. The first schema-migration slice failed at collection because
   `ComparisonHistorySummary` and the schema-v2 change state did not exist.
3. The first application slice failed all nine tests because comparison
   completion/error, refresh-outcome, filtering, acknowledgement, restore, and
   mouse-wheel methods did not exist.
4. The checked-in local snapshot adapter initially failed on the 18 valid
   reserve-pool players whose team is intentionally unassigned. The adapter
   now preserves them as explicit `UNASSIGNED` identities instead of dropping
   or guessing a team.
5. The first GUI smoke harness reached its final save step but called the
   existing save helper without the required lifecycle argument. The corrected
   harness passed; no product assertion failed in that first run.

No validation, privacy, identity, atomic-write, or last-known-good assertion
was weakened to make these tests pass.

## Verification

- Clean Phase 6D baseline: **654 passed in 20.02 s**.
- Phase 6E focused suite: **41 passed in 2.46 s**.
- Phase 6A–6D dashboard/fact/rundown/session adjacency:
  **203 passed in 6.10 s**.
- Refresh, cancellation, health, staging, source-selection, media,
  roster/team, copy, build/privacy, portable ZIP, and future-season matrix:
  **230 passed in 12.64 s**.
- Complete offline suite with warnings as errors:
  **695 passed in 30.71 s** (final documented tree).
- `python -m compileall -q src tests tools`: passed.
- `python -m pip check`: no broken requirements.
- `python tools/verify_distribution.py data/exports`: passed.
- Git LFS: four tracked workbooks are materialized; XLSX header is
  `50 4B 03 04`, not an LFS pointer.
- `git diff --check`: passed.
- Tracked-filename privacy scan: passed.
- Tracked-content high-confidence secret scan: passed.
- Repository-history high-confidence secret scan: passed.

All automated tests were network-independent.

## Windows GUI smoke

The final source smoke passed on Windows with Python 3.12 and real Tkinter at
1280×820. It used the checked-in local core snapshot, an isolated temporary
private-session directory, and an in-memory changed-snapshot fixture; it made
no live refresh and changed no checked-in factual data.

It exercised:

1. first validated baseline creation without an all-added report;
2. exact official game and current local fact collection;
3. one pinned and one used fact;
4. roster, exact-game schedule, source-health, and fact-version changes;
5. four rendered events: one blocking and three attention;
6. pinned impact and readiness impact;
7. Needs Attention, Pinned, and Selected Game filters;
8. acknowledgement persistence;
9. exact repeat-opponent/other-game switching with old-game exclusion;
10. Local/Offline Mode;
11. every existing Game Day and main application tab;
12. clean atomic session save/close;
13. restart recovery of baseline, complete report, and acknowledgement.

Recovered smoke baseline:
`2420d98b996ee13c0e84c0e087aed673f81008539d85e062b92200ed3d78c8c1`.

## Remaining limitations

- Only the latest comparison has full card detail. Five earlier comparisons
  retain compact count/timestamp summaries but do not have a history browser.
- Change detection is intentionally conservative. Unsupported or ambiguous
  source schema makes comparison unavailable instead of inferring a change.
- The checked-in all-game canonical-fact digest takes approximately eight
  seconds on the smoke computer. It runs off the Tk main thread and coalesces,
  but slower hardware may take longer.
- A comparison above the 300-event safety bound fails without baseline
  promotion; the producer must resolve the abnormal snapshot rather than
  receiving a truncated report.
- The private session remains local/single-user and subject to the existing
  5 MiB fail-closed bound. A save that exceeds it is visibly rejected and the
  prior on-disk session remains last-known-good.
- Acknowledgement records review only; it intentionally does not clear the
  underlying factual/readiness issue.
- Phase 6F fuzzy search and player comparison are not implemented.

Verdict: **PHASE 6E COMPLETE**.
