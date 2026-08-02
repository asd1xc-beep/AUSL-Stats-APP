# AUSL Broadcast Stats — Improvement Tracker

Last updated: 2026-07-29

Project source reviewed: accepted Phase 6 GitHub `main` at
`08fd7f09f24a53f3270516c51e6667e9daa35538`, then the reviewed Phase 7A
commits on `agent/phase7a-producer-enrichment`.

Detailed plan: `AUSL_Broadcast_Stats_Implementation_Guide.md`

## Project goal

Build a fast, trustworthy in-truck application that helps an AUSL television producer find players and facts in seconds, discover useful storylines, and understand when information is stale or needs verification.

Primary rule:

> Wrong-on-air is worse than unavailable. If the application is uncertain, it must say so.

## Status legend

- `[ ]` Not complete
- `[x]` Complete and verified
- **NEXT** — included in the next implementation pass
- **IN PROGRESS** — implementation or verification is actively underway
- **PLANNED** — accepted work, ordered behind the current pass
- **BACKLOG** — valuable idea that has not been scheduled
- **BLOCKED** — cannot proceed until the stated dependency is resolved
- **DEFERRED** — deliberately postponed; retain the item and reason

Priority legend:

- **P0** — crash, incorrect on-air information, or serious state/data corruption risk
- **P1** — major reliability or live-production workflow problem
- **P2** — meaningful usability or producer-value improvement
- **P3** — longer-term enhancement

## Current milestone

### Milestone 7A — Producer-facing approved enrichment

Phase 6F completed on 2026-07-29. The stabilization changes merged in PR #11
at `08fd7f09f24a53f3270516c51e6667e9daa35538`. Windows scaling at 100%,
125%, and 150%, truck-hardware smoke, and producer rehearsal are recorded as
**project-owner reported** complete; no unsupplied hardware or behavior detail
is inferred. The full Phase 6 acceptance is closed.

Phase 7A completed centralized split reliability, typed enrichment load
modes, producer-facing Full Enrichment Refresh, strict media/note approval
gates, last-known-good source handling, and the explicit approved-enrichment
distribution profile. Phase 7B now completes the normalized, provenance-first
college data foundation. Phase 7C's ten-player pilot is **NOT STARTED**.

The master list below is the single source of task status. No item is
complete until its tests and stated acceptance behavior pass.

Status: **PHASE 7B COMPLETE — PHASE 7C TEN-PLAYER PILOT NOT STARTED**

## Approved next roadmap

Producer feedback elevated the College Résumé from backlog to the next major
product milestone. Approved enrichment becomes producer-visible first so the
same source, identity, freshness, approval, and last-known-good boundaries can
be reused by the college layer.

| Order | Implementation unit | Outcome | Start gate |
|---|---|---|---|
| 1 | Phase 6 stabilization | Close the four independent-review findings without starting Phase 7 | Complete |
| 2 | Phase 6 acceptance | Owner scaling sign-off and final full-phase acceptance record | Complete |
| 3 | Phase 7A | Promote only approved optional enrichment to producer-facing use | Complete |
| 4 | Phase 7B | Define the normalized, provenance-first college data foundation | Phase 7A trust boundaries stable |
| 5 | Phase 7C | Build and validate a varied ten-player college résumé pilot | Phase 7B specification accepted |
| 6 | Phase 7D | Add the separate College Résumé tab | Pilot data and producer review accepted |
| 7 | Phase 7E | Scale to the roster and add college-based broadcast connections | College tab pilot accepted |

The college milestone takes precedence over `NOTE-004`, live milestone watch,
scenario calculations, news intake, and multi-user work unless a new producer
requirement or a P0/P1 reliability issue changes the order.

## Master improvement list

### A. Test, build, and maintenance foundation

- [x] `BASE-001` — Add an offline automated test harness. **P0 · COMPLETE**
  - Cover formatters, note scope, lineup validation, team snapshots, media parsing, game-note classification, copy generation, status filtering, refresh staging, and live parsing.
  - Tests must not access the live internet by default.

- [x] `BASE-002` — Create small, hand-auditable fixture datasets. **P1 · COMPLETE**
  - Include active, inactive, reserve, and unknown-status players; batting and pitching nulls; repeat-opponent games; scoped notes; valid/invalid lineups; media TOC text; official notes; and a live-box response.

- [x] `QA-001` — Complete the Milestone 1 automated regression and six-tab Windows smoke test. **P0 · COMPLETE**
  - Record the test command/result, Windows environment, producer-visible behavior, and remaining limitations in the Milestone 1 acceptance record.

- [x] `BUILD-001` — Pin runtime and build dependencies. **P1 · COMPLETE**
  - Builds must not silently install whichever dependency version is newest that day.

- [x] `BUILD-002` — Add a clean distribution-package option. **P0 · COMPLETE**
  - Exclude manual notes, lineup locks, logs, producer-generated/private exports, debug-only raw exports, and caches. Permit only an explicit allowlist of validated official snapshots with their source manifest and visible freshness metadata.
  - ZIP members must use portable POSIX `/` paths and pass CRC plus cross-platform extraction tests.

- [x] `DOC-001` — Align producer instructions and missing-time formatting with the implemented official-game workflow. **P1 · COMPLETE**
  - README instructions must use the official game selector and `Validate & Save Lineups`; missing time/time-zone sentinels must render as unavailable rather than mojibake.

- [x] `OPS-001` — Add structured application logging. **P1 · COMPLETE**
  - Record refresh source, timestamps, row counts, validation results, fallback use, and useful exceptions.
  - Avoid unnecessarily logging private producer-note contents.

### B. Crash prevention and UI thread safety

- [x] `SAFE-001` — Fix delayed exception callbacks in `_load_initial`, `update_data`, and `refresh_live`. **P0 · COMPLETE**
  - Bind exception values safely or use a thread-safe result queue.
  - Original errors must reach the user instead of producing a second callback error.

- [x] `SAFE-002` — Add one in-flight guard per refresh source. **P1 · COMPLETE**
  - Disable the relevant action while running and restore it on success, failure, or cancellation.

- [x] `SAFE-003` — Keep all Tkinter widget mutations on the main thread. **P0 · COMPLETE**
  - Background workers may fetch and parse only; results return through one main-thread handler.

- [x] `LIVE-001` — Guarantee only one pending live auto-refresh timer. **P1 · COMPLETE**
  - Store the timer ID, cancel before rescheduling, and make repeated enable/disable actions safe.

### C. Manual notes

- [x] `NOTE-001` — Add explicit manual-note scope. **P0 · COMPLETE**
  - Supported scopes: player, team, game, and optional global.
  - A player view may show that exact player's notes plus explicitly team-wide/game-wide notes, never another player's note.

- [x] `NOTE-002` — Replace ambiguous typed player matching with an exact searchable picker. **P0 · COMPLETE**
  - If a name matches more than one player, block the save and require an explicit selection.

- [x] `NOTE-003` — Migrate existing note files safely. **P1 · COMPLETE**
  - Back up before migration, preserve every existing row, and use atomic writes.

- [ ] `NOTE-004` — Add edit, delete, and source/date display for manual notes. **P2 · PLANNED**

### D. Official team facts

- [x] `TEAM-001` — Create one authoritative `official_team_snapshot` helper. **P0 · COMPLETE**
  - Supply official W-L, runs for/against, differential, streak, games back, source, and freshness.

- [x] `TEAM-002` — Route team totals, producer prep, and generated packets through the same snapshot. **P0 · COMPLETE**
  - The same team cannot show contradictory records in different sections.

- [x] `TEAM-003` — Remove pitcher-decision totals as a fallback team record. **P0 · COMPLETE**
  - If official standings are unavailable, display `Record unavailable`.
  - Player-stat aggregates may remain only when clearly labeled `Calculated`.

### E. Roster status and copy safety

- [x] `COPY-001` — Make `gfx_text` and every copy type safe for missing team/status values. **P0 · COMPLETE**
  - Reserve-pool players display `RESERVE POOL` or `RAP`, never `nan`.
  - Run every roster player through every copy type without an exception.

- [x] `COPY-002` — Separate player ID, season stat, career stat, and announcer-note copy. **P1 · COMPLETE**
  - Career text must say `AUSL CAREER` and include the applicable season span.

- [x] `COPY-003` — Add an on-air copy warning/confirmation for inactive, reserve, unknown, stale, or unverified information. **P0 · COMPLETE**

- [x] `ROSTER-001` — Make missing roster status `Status unknown`, not `Active`. **P0 · COMPLETE**

- [x] `ROSTER-002` — Filter projections and watch lists to active players by default. **P0 · COMPLETE**
  - Applies to projected lineups, projected pitchers, and players to watch.
  - Nonactive players belong in a separate `Availability impact` section.

### F. Statistical correctness and split reliability

- [x] `STAT-001` — Create one canonical baseball-innings parser. **P0 · COMPLETE**
  - Verify `0.1`, `0.2`, `1.2`, `31.2`, null, and malformed values.

- [x] `STAT-002` — Derive and validate pitching metrics using outs. **P0 · COMPLETE — REVERIFIED 2026-07-19**
  - WHIP must use true innings, not decimal interpretation of baseball notation.
  - Retain source values for comparison and audit.

- [x] `STAT-003` — Separate rate and decimal formatting. **P0 · COMPLETE**
  - AVG/OBP/SLG/OPS: `.392`.
  - ERA/WHIP: `0.88`, `1.00`.
  - Missing is `—`/`N/A`, never a fabricated zero.

- [x] `SPLIT-001` — Exclude `regularSeason` aggregate rows from the best situational-split list. **P1 · COMPLETE — PHASE 7A**

- [x] `SPLIT-002` — Establish configurable sample thresholds and reliability labels. **P1 · COMPLETE — PHASE 7A**
  - Default policy: hitter at least 12 PA; pitcher at least 9 canonical outs.
  - Always show sample size.

- [x] `SPLIT-003` — Keep small samples available in detail without promoting them as top storylines. **P2 · COMPLETE — PHASE 7A**

### G. Exact game identity and lineup workflow

- [x] `GAME-001` — Add an official selected-game model and schedule-driven game selector. **P0 · COMPLETE**
  - Include game ID, season, time, teams, venue, status, and source update time.

- [x] `GAME-002` — Add one `on_game_changed` state transaction. **P0 · COMPLETE**
  - Update teams, search scope, selected player, lineup editor, prep, notes, live game ID, and packet context together.
  - Invalidate in-flight live requests/timers and apply a strict prior-game time cutoff to historical matchup context.

- [x] `LINEUP-001` — Key lineup locks by official game ID. **P0 · COMPLETE**
  - Repeat series between the same teams must never share a lineup accidentally.

- [x] `LINEUP-002` — Migrate old matchup-only lineup locks without guessing their game. **P1 · COMPLETE**
  - Preserve ambiguous locks as `legacy_unassigned` until the user attaches them.

- [x] `LINEUP-003` — Add structured lineup validation. **P0 · COMPLETE**
  - Block duplicate batting order, duplicate player, unresolved player, wrong team, missing starter, bad position syntax, and malformed DP/FLEX.
  - Preserve a separate FLEX through save/load/save and require a real `P`, `RHP`, or `LHP` starter unless a complete reviewed two-way exception is recorded.

- [x] `LINEUP-004` — Add explicit warnings and confirmation for nonactive players and stale/projected lineups. **P0 · COMPLETE**

- [x] `LINEUP-005` — Store lineup source, lock time, and revision. **P1 · COMPLETE**
  - Save/delete transactions replace in-memory state only after the atomic disk write succeeds.

- [x] `PACKET-001` — Include game ID and timestamp/revision in generated packet filenames. **P1 · COMPLETE**
  - Packet lineup and starter headings must derive from validated stored provenance; projected/manual/imported input cannot be mislabeled official.

### H. Search and interface state

- [x] `SEARCH-001` — Make `All Players` genuinely show all players regardless of game scope. **P1 · COMPLETE**

- [x] `SEARCH-002` — Stop team views from silently mutating the game-scope preference. **P1 · COMPLETE**

- [x] `SEARCH-003` — Search numbers with or without `#` and include roster status. **P2 · COMPLETE**
  - Examples: `22`, `#22`, `inactive`, and `reserve`.

- [x] `SEARCH-004` — Add optional quick filters. **P2 · COMPLETE**
  - Supports deterministic AND-combined team, position, roster-status,
    jersey-number, and quoted name filters without executing input.

- [x] `STATE-001` — Rerender or clear the selected player card after data refresh. **P0 · COMPLETE**
  - Clipboard text and `current_broadcast_note` must use the same database version as the visible card.

- [x] `UI-001` — Add visible scrollbars to long content panels. **P2 · COMPLETE — PHASE 6 ACCEPTED**
  - Player Lookup and Compare Players have visible vertical scrolling, and the
    comparison surface supports the mouse wheel. Broader cross-tab manual
    confirmation remains part of the full Phase 6 acceptance review.

- [x] `UI-002` — Verify minimum window size and Windows scaling at 100%, 125%, and 150%. **P1 · COMPLETE — OWNER REPORTED**
  - The automated 1120×720 Windows smoke passes. The project owner reports
    that 100%, 125%, and 150% scaling passed; no additional display or hardware
    detail is inferred.

- [x] `UI-003` — Add keyboard navigation for search and primary game workflow. **P2 · COMPLETE**
  - Ctrl+F, Escape, arrows, Enter, Ctrl+1, and Ctrl+2 preserve explicit player
    selection and do not intercept multiline note editing.

### I. Media-guide accuracy

- [x] `MEDIA-001` — Replace page-wide name-mention matching with exact table-of-contents mapping. **P0 · COMPLETE**
  - Map normalized exact player identity to printed page/page range and verify the PDF offset.

- [x] `MEDIA-002` — Merge every page in a player's TOC range. **P1 · COMPLETE**

- [x] `MEDIA-003` — Mark absent players `Not included in guide`; never infer a biography from a teammate mention. **P0 · COMPLETE**

- [x] `MEDIA-004` — Repair wrapped hyphenation and deduplicate repeated biography categories. **P1 · COMPLETE**

- [x] `MEDIA-005` — Store match confidence, expected/parsed pages, guide date, source, and warnings. **P1 · COMPLETE**

- [x] `MEDIA-006` — Add a media-guide audit table/export. **P1 · COMPLETE**

- [x] `MEDIA-007` — Gate unverified or mismatched media notes from air-ready copy. **P0 · COMPLETE**
  - Air-ready rows require one canonical, evidence-bound approval record; changing an independent Boolean cannot promote a row.

Required identity regressions:

- [x] Sydney Romero does not receive Elise Sokolsky's biography.
- [x] Morgan Zerkle does not receive Sydney Romero's page.
- [x] Rachel Garcia does not receive Mariah Mazon's page.
- [x] A player absent from the TOC receives no guessed biography.
- [x] A two-page player receives both pages in order.

### J. Official game notes and storyline quality

- [x] `GNOTE-001` — Replace broad keyword-only categories with conservative classification. **P0 · COMPLETE**
  - Distinguish availability, milestone watch/reached, probable starter, matchup history, recent trend, season context, career summary, and background.

- [x] `GNOTE-002` — Store subject identity, teams, effective/source date, PDF/game/page, verification state, and parser version. **P1 · COMPLETE**

- [x] `GNOTE-003` — Deduplicate repeated notes across PDFs with a normalized content hash. **P1 · COMPLETE**

- [x] `GNOTE-004` — Select notes for the exact game and balance both teams. **P0 · COMPLETE**

- [x] `GNOTE-005` — Prioritize confirmed injuries/transactions and exact-game starters over generic history. **P0 · COMPLETE**

- [x] `GNOTE-006` — Display `[VERIFIED]`, `[VERIFY]`, or `[STALE]` with source location/date. **P0 · COMPLETE**

- [x] `PREP-001` — Refactor producer prep into structured sections. **P1 · COMPLETE**
  - Game context, availability, top storylines, offense, pitching, matchup history, milestones, and verification queue.

- [x] `PREP-002` — Stop the packet's `TOP STORYLINES` section from repeating the first official-note bullets. **P0 · COMPLETE**

### K. Refresh speed, resilience, and data health

- [x] `REFRESH-001` — Split `Quick Refresh` from `Full Enrichment Refresh`. **P1 · COMPLETE**
  - Quick: roster, stats, standings, schedule, live metadata.
  - Full: media guide and historical/official-note PDFs.

- [x] `REFRESH-002` — Stage, validate, and atomically promote each source. **P0 · COMPLETE**
  - Validate schema, row count, unique keys, season, and value ranges.
  - A process-local commit lock now serializes the complete core
    workbook-and-manifest stage/promotion transaction. A cancelled worker
    rechecks its token immediately after acquiring the lock; a worker already
    inside may finish coherently, and a newer replacement commits afterward.

- [x] `REFRESH-003` — Preserve last-known-good data after optional-source failure. **P0 · COMPLETE**
  - A failed optional source must not replace a valid workbook with an empty one.
  - Failed core refreshes also retain every validated core byte and the
    snapshot manifest; their latest-attempt outcome is written separately and
    atomically to nonprivate `refresh_attempt.json`.

- [x] `REFRESH-004` — Add a per-source health manifest. **P1 · COMPLETE**
  - Track attempt/success time, row count, content hash/ETag, status, error, fallback, and parser version.

- [x] `REFRESH-005` — Cache and incrementally process unchanged PDFs. **P1 · COMPLETE**
  - Every deliberate full enrichment refresh revalidates official game-note
    PDFs at the same URL. Unchanged bytes reuse cached parsed rows without a
    second `PdfReader` pass; revised bytes parse from a temporary candidate and
    replace the PDF/cache only after validation. Download/parse failures retain
    the last-known-good PDF/cache. The media-guide path follows the same
    candidate-before-promotion rule.

- [x] `REFRESH-006` — Add bounded timeouts, retry/backoff, cancellation, and deterministic cleanup. **P1 · COMPLETE**
  - Bounded timeouts and deterministic single-flight cleanup were already in place (`SAFE-002`/`LIVE-001`). Bounded retry/backoff on transient network failures was added in the 2026-07-24 pass. This pass closes the remaining gap: real mid-flight cancellation. A `CancelToken`/`RefreshCancelled` pair in `ausl_data.py` is threaded through `_fetch_with_retry`, `_get_json`, `_get_text`, `_download_file`, `fetch_standings_frame`, `fetch_schedule_frame`, `update_all_data`, and `fetch_live_game`; cancellation is checked before every attempt and during the retry backoff wait (`Event.wait` instead of `time.sleep`), so a cancelled job stops retrying immediately instead of working through its full timeout/retry budget, and `update_all_data` re-checks cancellation once more immediately before staging/promotion so a cancelled Quick Refresh can never write or promote a partial result. In `ausl_stats_app.py`, `cancel_data_update()`/`cancel_live_refresh()` (wired to new Cancel buttons, a game change, and app shutdown) give each job a token/token-identity check so a late success/error/cancelled callback from an abandoned background thread is a safe no-op rather than a promotion or a crash. Python/`urllib` offer no safe way to force-abort a call already inside `urlopen`; this is a cooperative design (documented in `CancelToken`'s docstring) rather than a raw socket-level abort — see the change-log entry below for what that means in practice.
  - The 2026-07-27 stabilization closes the cancellation/promote race left by
    immediately re-enabling Quick Refresh: deterministic two-worker tests now
    prove no overlapping stage/promotion, harmless late callbacks, coherent
    disk/in-memory data, newer-refresh-wins ordering, and cleanup on every exit.

- [x] `HEALTH-001` — Add visible per-source freshness and green/yellow/red health. **P1 · COMPLETE**
  - The snapshot manifest describes the installed last-known-good data;
    `refresh_attempt.json` separately persists latest attempt
    success/failure/cancellation, timestamp, safe error summary, and affected
    source. The UI can now say "Stored snapshot valid; latest refresh failed,"
    cancellation is not a source failure, restart preserves the state, and a
    later success clears it. The checked-in offline manifest contains usable
    source health instead of UNKNOWN.

- [x] `HEALTH-002` — Display live feed `lastUpdated`, connection state, and staleness. **P0 · COMPLETE**
- [x] `REFRESH-007` — Add an explicit Local/Offline Mode toggle. **P2 · COMPLETE**
  - While enabled, guarantees no refresh attempt or network-related UI notification fires, for use during producer-designated live windows (e.g., final two minutes before first pitch, an active half-inning). Complements Phase 5's failure-safe refresh with an explicit guarantee rather than relying on failure behavior alone.
  - The shared producer-facing network guard blocks core and manual live
    refreshes before a token, timer, or worker is created. Enabling the mode
    cancels existing core/live tokens, cancels the owned live timer, prevents
    rescheduling, invalidates late callbacks, and leaves local workflows
    enabled. Disabling it never starts a request.

### L. Producer-speed improvements

- [x] `UX-001` — Add a compact selected-game dashboard. **P2 · COMPLETE**
  - Teams/records, game time/venue/status, data health, lineup state/age, live state, and verification count.
  - Implemented as the first `Game Day` tab. It additionally shows exact
    schedule/lineup/live/packet game IDs, snapshot versus latest-attempt
    health, packet lineup revision/source, and an honest `Unavailable` scoped
    verification count when optional review data is not loaded.

- [x] `UX-002` — Add air-ready fact cards with concise copy, context, source, freshness, and verification state. **P2 · COMPLETE**
  - Game Day opens on a scrollable card view backed by one immutable
    `BroadcastFact`. Stable fact identity is separate from evidence/version
    identity; exact-game adapters wrap trusted core stats, canonical roster
    status, exact-game lineup provenance, approved optional official/media
    rows, scoped producer notes, and official team snapshots. VERIFIED,
    VERIFY, STALE, and UNAVAILABLE are derived from evidence and health.

- [x] `UX-003` — Add a local pinned-facts/rundown queue with plain-text export. **P2 · COMPLETE**
  - One session-only state is keyed by exact official game ID. Canonical fact
    snapshots retain stable/version identity, provenance, warning state,
    order, and reconciliation status. Active air-ready, review, and used
    sections are separate. Clipboard copy and exclusive text export preserve
    source/freshness and write only under the private game-packet area.

- [x] `UX-004` — Add a post-refresh `What changed?` panel. **P2 · COMPLETE**
  - Roster/status/team assignment, official record/rank/games-back/streak,
    exact-game schedule/final score, locked-lineup state, source health,
    canonical fact/evidence/verification, milestones, pinned impact, used
    history impact, and invalidation are compared only between validated
    normalized snapshots.
  - The first valid snapshot establishes a quiet baseline. Successful
    comparisons promote atomically with the result; failed/cancelled refreshes
    and failed comparisons retain the prior baseline/report. Stable event IDs,
    exact scope, pure severity, filters, review actions, and acknowledgements
    never mutate facts or silently replace pins.

- [x] `UX-005` — Preserve source/freshness metadata when copying or pinning a fact. **P1 · COMPLETE**
  - Phase 6B copy events retain exact fact ID, evidence hash, full provenance,
    snapshot timestamp, copy timestamp, and selected width profile. Copy With
    Source renders source/status/freshness explicitly. No pin queue exists yet;
    Phase 6C can consume the canonical fact without reparsing display text.
- [x] `UX-006` — Add read-time budgeting to fact cards and the pinned rundown. **P2 · COMPLETE**
  - Estimate seconds-to-read from word count (~140 wpm); show a running total against a settable break-length target on the pinned queue.
  - Exact air copy is counted deterministically at a centralized 140 WPM with
    a one-second minimum for nonempty text. Presets and validated custom
    targets are exact-game local; active totals equal the displayed per-item
    sums, while review/changed/invalidated/used items are excluded.

- [x] `UX-007` — Let a producer mark a suggested fact "used on air" with a timestamp. **P2 · COMPLETE**
  - A used fact is excluded from default Top Storylines/suggestion surfaces for the remainder of the selected game; it remains visible and selectable in the detailed view.
  - Pinned and unpinned facts retain the exact evidence hash and timezone-aware
    used timestamp. Stable-ID suppression is exact-game scoped; Show Used and
    Undo Used provide history and deterministic recovery without promoting
    verification.

- [x] `UX-008` — Add session/crash recovery for producer working state. **P1 · COMPLETE**
  - Autosave and restore selected game, pinned/used-fact queue, and scroll position. Distinct from lineup-lock and manual-note storage, which are already atomic-written; this protects in-progress prep, not source data.
  - Schema v2 (with explicit v1 migration) persists canonical primitives under
    application-data directory. One 500 ms debounced timer covers exact game,
    rundown/use/order/target/reconciliation, Game Day view/filters, unique
    player selection, normalized fact/rundown/change scroll, Phase 6E baseline,
    latest complete comparison, acknowledgement IDs, bounded history
    summaries, and refresh metadata. Atomic saves retain
    one validated backup; corrupt/future/oversized state is quarantined and
    fails closed. Exact game/team/season identity is never guessed. Clean
    resume, crash recovery, save failure, and Start Fresh are visibly
    distinct; Offline Mode, clipboard state, workers, timers, locks,
    credentials, and network state are not restored.

- [x] `UX-009` — Add a "Ready for Air" readiness indicator and pregame checklist. **P2 · COMPLETE**
  - Roll up data health, lineup-lock state, and verification count into one status; checklist covers rosters confirmed, lineups locked, packet generated, live feed connected. Extends `UX-001`.
  - `GameDayReadiness` is derived by one pure aggregator; Tkinter renders it
    without independently storing or editing readiness. Blocking failures
    always produce `NOT READY`; warning/unavailable state produces
    `NEEDS ATTENTION`; only all applicable passes produce `READY FOR AIR`.
    There is no force-green control.

- [x] `SEARCH-005` — Add fuzzy/typo-tolerant name matching to search. **P2 · COMPLETE**
  - Conservative length-aware Damerau-Levenshtein matching covers full names
    and individual name tokens. Partial first/last-name typos remain labeled
    `POSSIBLE TYPO`, never auto-select, preserve distinct candidates, and stay
    disabled for short queries. Straight and smart apostrophes are inert name
    characters; double-quoted filters retain strict malformed-quote checks.

- [x] `UX-010` — Add a character-count preview on copy actions against common graphics-template widths. **P2 · COMPLETE**
  - Central profiles provide 60-character one-line and 120-character extended
    guidance. Counts use the exact Unicode air-copy string, never truncate or
    rewrite it, and are explicitly labeled guidance rather than graphics-system
    validation.

- [x] `UX-011` — Add a side-by-side player/matchup compare view. **P3 · COMPLETE**
  - Two exact player identities retain aligned neutral statistics and
    independent exact-game canonical facts. Each fact now displays its own
    verification state, source reference/date/page/game, snapshot, health,
    and review warning. The shared statistical snapshot is labeled separately,
    and metrics-only copy does not silently add fact wording.

### M. Producer-facing approved enrichment

Only enrichment that passes the existing canonical identity, approval,
freshness, and source-health gates may leave developer mode. Raw parser output,
debug exports, ambiguous identities, and unapproved rows remain excluded.

- [x] `ENRICH-001` — Add a producer-facing `Full Enrichment Refresh` workflow. **P1 · COMPLETE — PHASE 7A**
  - Require deliberate opt-in, per-source progress and health, cancellation,
    Local/Offline Mode enforcement, and last-known-good retention.
  - A failed or cancelled source must not replace its prior validated snapshot.

- [x] `ENRICH-002` — Promote approved media-guide facts to ordinary producer mode. **P0 · COMPLETE — PHASE 7A**
  - Reuse the canonical approval transaction, exact player/team identity,
    printed/PDF provenance, guide date, reviewer, approval timestamp, and
    unresolved-warning gates.

- [x] `ENRICH-003` — Promote approved official game-note facts to ordinary producer mode. **P0 · COMPLETE — PHASE 7A**
  - Require exact official game ID, subject/team identity, source document,
    page/location, publication/effective date, parser version, freshness, and
    approval state. Ambiguous or wrong-game rows remain unavailable.

- [x] `ENRICH-004` — Define and verify an enrichment-capable distribution profile. **P1 · COMPLETE — PHASE 7A**
  - Package only validated approved outputs and their manifests.
  - Continue excluding raw/debug artifacts, unapproved review queues, caches,
    manual notes, lineup locks, private session state, and producer exports.

### N. College Résumé tab

The college layer must remain visually and statistically separate from AUSL professional totals.

- [x] `COLLEGE-001` — Write the normalized college-data specification before importing data. **P1 · COMPLETE — PHASE 7B**
  - Support multiple schools, seasons, transfers, shortened seasons, extra eligibility, and two-way players.

- [ ] `COLLEGE-002` — Add a separate `College Résumé` tab. **P2 · PLANNED — PHASE 7D**
  - Sections: Snapshot, Schools/Transfer Timeline, College Career Totals,
    Season-by-Season Summary, Honors/Records, WCWS/Championships, Broadcast
    Connections, and Sources/Completeness.

- [ ] `COLLEGE-003` — Build a verified core résumé from official sources. **P2 · PLANNED — PHASE 7C**
  - School(s), seasons, career batting/pitching totals, final season, championships/WCWS, awards, and records.

- [x] `COLLEGE-004` — Add source hierarchy and field-level provenance. **P1 · COMPLETE — PHASE 7B**
  - Preferred order: official AUSL profile, NCAA statistics, official school athletics site, manually verified entry.
  - Every displayed value must retain its own source, effective season/date,
    retrieval time, and verification state; one good source must not silently
    validate unrelated fields.

- [x] `COLLEGE-005` — Add `Verified`, `Partial`, and `Needs review` completeness states. **P1 · COMPLETE — PHASE 7B**
  - Missing information remains unavailable and is never converted to zero.

- [ ] `COLLEGE-006` — Pilot the résumé with ten varied players before full-roster import. **P2 · PLANNED — PHASE 7C**
  - Include rookies, veterans, transfers, hitters, pitchers, two-way players,
    award/WCWS résumés, and at least one deliberately incomplete record.
  - The pilot target is a verified useful résumé, not forced completeness for
    every season and field.

- [ ] `COLLEGE-007` — Add college-based broadcast connections and storylines after producer review. **P2 · PLANNED — PHASE 7E**
  - Former teammates, conference rivals, champions, homecomings, coaches, and role changes.

- [ ] `COLLEGE-008` — Consider complete season-by-season college statistics only after the pilot proves useful. **P3 · DEFERRED — PRODUCER DECISION AFTER PHASE 7D**

College display rule example:

```text
2026 AUSL: .286 AVG, 4 HR, 13 RBI
COLLEGE CAREER — Oklahoma: .376 AVG, 54 HR, 301 H
```

College and AUSL numbers must never be combined into one unlabeled career total.

### O. Longer-term ideas

- [ ] `FUTURE-001` — Live milestone watch that updates pregame thresholds from the live box score. **P3 · BACKLOG**

- [ ] `FUTURE-002` — Verification desk for stale, ambiguous, conflicting, or needs-review facts. **P2 · BACKLOG**

- [ ] `FUTURE-003` — Standings, seeding, clinching, or elimination scenarios from versioned official rules. **P3 · BACKLOG**

- [ ] `FUTURE-004` — Export/import a game package containing selected game, lineups, pinned facts, and scoped notes. **P3 · BACKLOG**

- [ ] `FUTURE-005` — Review-only feed for official AUSL/team announcements and transactions. **P3 · BACKLOG**

- [ ] `FUTURE-006` — Shared multi-user workflow only after ownership, authentication, conflict handling, and offline behavior are designed. **P3 · BACKLOG**

## Acceptance records

Fill in one record when a milestone or major item is completed.

### Phase 7B — College data foundation

- Completion date: 2026-08-01.
- Starting commit and branch: remote `main`
  `d67124b706d77f6ab677b5257a253088e20f5e78`;
  `agent/phase7b-college-foundation`.
- Completed tracker scope: `COLLEGE-001`, `COLLEGE-004`, and `COLLEGE-005`.
- Added a GUI-free normalized model, field-level evidence candidates, retained
  conflict resolution, explainable completeness, deterministic versioned JSON,
  bounded validation, and an offline explicit-file developer validator.
- Verification: **116** focused/safety tests and **899** complete offline tests
  passed with warnings as errors; compile, dependency, distribution, privacy,
  LFS/XLSX, whitespace, secret, and unchanged-export checks passed.
- No production college data, UI, startup/refresh integration, or distribution
  member was added. `COLLEGE-003` and `COLLEGE-006` remain uncompleted.
- Detailed evidence: `Implementation guide/Phase_7B_Acceptance_Record.md`.

**PHASE 7B COMPLETE — PHASE 7C TEN-PLAYER PILOT NOT STARTED**

### Phase 7A — Producer-facing approved enrichment

- Completion date: 2026-07-29.
- Starting commit and branch: remote `main`
  `08fd7f09f24a53f3270516c51e6667e9daa35538`;
  `agent/phase7a-producer-enrichment`.
- Reviewed implementation commits: `c23ab52`, `8a34785`, and `85b0db9`.
- Completed tracker scope: `SPLIT-001`, `SPLIT-002`, `SPLIT-003`,
  `ENRICH-001`, `ENRICH-002`, `ENRICH-003`, and `ENRICH-004`.
- Typed load boundary: ordinary producer paths use `PRODUCER_APPROVED`;
  `CORE_ONLY` excludes optional sources; `DEVELOPER_REVIEW` cannot promote
  review rows.
- Split boundary: exact aggregate exclusion, 12-PA/9-out defaults, and
  visible non-air-ready `SMALL SAMPLE` detail.
- Refresh boundary: deliberate Full Enrichment action, Quick/Full
  serialization, complete transactional staging, cancellation guards,
  per-source health, and last-known-good fallback.
- Distribution boundary: unchanged default `core` profile plus explicit,
  deterministic, row-revalidated `approved-enrichment`.
- Focused tests passed **76 tests in 6.01 s**; the complete offline suite
  passed **847 tests** with warnings as errors. Compilation, dependency,
  distribution, LFS, whitespace, privacy, and tracked/history secret checks
  passed.
- Windows source/real-Tk smoke passed at 1120×720 on
  `Windows-10-10.0.19045-SP0`, Python 3.12.10, with approved facts for both
  teams, cancel/queue replacement, coherent final facts/database, all eight
  tabs, Local/Offline Mode, no stale dialogs, and zero network calls.
- Detailed evidence:
  `Implementation guide/Phase_7A_Acceptance_Record.md`.
- Phase 7B is **NOT STARTED**.

### Phase 6 full acceptance — COMPLETE

- [x] Phase 6F focused tests and full offline regression pass.
- [x] Collision-safe fuzzy search and quick-filter identity tests pass.
- [x] Side-by-side comparison preserves independent source, freshness, and
  verification labels for both players.
- [x] Keyboard and scroll reachability pass at the normal automated minimum
  1120×720 window.
- [x] Windows 100%, 125%, and 150% scaling pass, project-owner reported.
- [x] Privacy and distribution verification exclude all producer-private,
  raw/debug, and unapproved enrichment artifacts.
- [x] Offline startup, Local/Offline Mode, refresh cancellation,
  last-known-good recovery, session restore, and What Changed remain stable.
- [x] Producer workflow smoke covers game selection, player search, fact copy,
  pin/rundown, used-on-air, comparison, packet export, and recovery.
- [x] Completion report records commands, counts, hardware/environment,
  screenshots or observations, known limitations, and the accepted commit.
- [x] Truck-hardware smoke and producer rehearsal are project-owner reported
  complete. No unsupplied hardware, date, scaling behavior, or rehearsal
  details are recorded.
- Detailed evidence:
  `Implementation guide/Phase_6_Full_Acceptance_Record.md`.

### Phase 6F — Faster discovery and player comparison

- Completion date: 2026-07-29.
- Starting commit and branch: remote `main`
  `d7f255b273acfc52f24aea98c544bbb945391f2b`;
  `agent/phase6f-search-compare`.
- Reviewed implementation commits: `14356a1` added the immutable local search
  index and conservative ranked query model; `20745a0` added the canonical
  neutral comparison model; `846cbfc` integrated Player Lookup, Compare
  Players, keyboard workflow, schema-v3 recovery, and the real-Tk smoke.
  `c5e10d1` recorded the detailed acceptance evidence.
- Completed tracker scope at that delivery: `SEARCH-004`, `SEARCH-005`,
  `UI-003`, `UX-011`, and the Player Lookup/Compare Players portion of
  `UI-001`. `UI-001` and `UI-002` were subsequently accepted in the full
  Phase 6 record.
- Search behavior: exact full name, exact approved alias, exact name token,
  prefix, substring, then conservative possible-typo matching. Filters apply
  before ranking. Selected-game relevance and active status are tie-breakers
  only. Fuzzy results never auto-select; explicit exact identities remain
  separate.
- Comparison behavior: one aligned registry covers current-season and AUSL
  career batting, pitching, and fielding without a winner judgment. Missing
  values stay unavailable, exact-player/exact-game facts remain independent,
  and wrong-game fact collections fail closed. The 2026-07-29 stabilization
  adds the missing per-fact source/trust display without changing canonical
  verification.
- Automated acceptance: Phase 6F focused/adjacent tests passed **83 tests in
  1.16 s**; the Phase 6A–6F matrix passed **432 tests in 7.22 s**; the complete
  offline suite passed **750 tests in 24.17 s** with warnings as errors.
  Compilation, dependency integrity, distribution verification, Git LFS,
  whitespace, privacy, and tracked/history secret checks passed.
- Windows GUI smoke: source/real-Tk execution passed on
  `Windows-10-10.0.19045-SP0`, Python 3.12.10, at 1120×720 with zero network
  calls. It exercised exact/typo/filter lookup, explicit keyboard selection,
  two-player comparison, wheel scrolling, source-labeled copy, local database
  replacement, exact-game rebuilding, Local/Offline Mode, all eight tabs,
  clean save, and exact restart restore.
- Remaining Phase 6F design limitations: alias matching uses only explicit
  approved aliases; typo tolerance remains conservative, and comparison copy
  history remains memory-only. The cross-phase review and project-owner
  scaling sign-off were subsequently accepted; Phase 7A is now complete.
- Detailed evidence source:
  `Implementation guide/Phase_6F_Acceptance_Record.md`.

### Phase 6D — Session persistence and crash recovery

- Completion date: 2026-07-28.
- Starting commit and baseline: latest remote `main`
  `e9e65dc5dd6363749ff08d0a88483e3bd23c1dcd`, the merged Phase 6C PR;
  **611 passed in 19.63 s** from a clean Git LFS worktree with warnings
  treated as errors.
- Branch and reviewed functional commits:
  `agent/phase6d-session-recovery`; `0b2816f` adds the v1 schema, canonical
  rundown reconstruction, atomic store, backup/quarantine, and its
  failing-first tests; `f19ffda` integrates autosave/restore/recovery UI,
  readiness/privacy behavior, isolated prior-phase smokes, and the Phase 6D
  real-Tk acceptance harness. The documentation commit and final branch head
  are reported in the Phase 6D PR and completion report.
- Schema and storage: `src/ausl_session.py` owns the primitive-only schema and
  one validation/migration entrypoint. It reconstructs `BroadcastFact`,
  provenance, pinned entries, used history, and exact-game state through
  canonical typed models and rechecks fact/evidence identity. It rejects
  missing required fields, future schemas, malformed timestamps/types,
  duplicate/cross-game state, unsafe limits, and invalid queue/timestamp
  invariants. Storage is under `%LOCALAPPDATA%\AUSL Broadcast Stats` on
  Windows, with injected XDG/home fallbacks for tests.
- Atomicity and recovery: one store lock and monotonic generation prevent an
  older same-process save from replacing a newer one. JSON is deterministic
  UTF-8/LF. A same-directory temp is flushed/fsynced and atomically replaced;
  the previous validated current file becomes the backup. Failures preserve
  the current bytes and clean only owned temp files. Corrupt/incompatible
  bytes are preserved in exclusive timestamped quarantine copies; valid
  backup fallback is explicit. Start Fresh archives validated current or
  backup bytes exclusively before any runtime clear.
- Autosave and lifecycle: one 500 ms Tk debounce covers official game,
  pinned/used/order/target/reconcile changes, filters/views, selected player,
  and normalized scroll. Status visibly distinguishes Saving, Saved, and
  persistent SESSION NOT SAVED. Shutdown cancels the debounce and synchronously
  flushes `closed_cleanly`; a persisted `active` lifecycle opens as crash
  recovery. No worker or network request is created by session handling.
- Restore safety: saved game ID, season, away code, and home code must match
  one current schedule row. Mismatch remains a blocking readiness/recovery
  issue, is not autosaved as an automatic default guess, and preserves the
  unresolved saved identity through close. Unique player identity is required.
  Facts/rundown/used versions restore canonically and the existing Phase 6C
  reconciliation handles current/changed/downgraded/missing evidence.
  Offline Mode always starts off. Clipboard/copy events, workers, timers,
  locks, credentials, and network state are not serialized.
- UI and privacy: Game Day shows a recovery notice with Review, Dismiss, and
  Start Fresh. Save failure contributes a workflow warning without changing
  source health; unresolved saved-game identity blocks readiness. Session
  filenames are Git-ignored and explicitly rejected by distribution
  verification. Smoke harnesses from Phases 5–6C now inject temporary session
  locations so fixtures cannot contaminate a real producer session.
- Failing-first evidence: the initial schema/storage files produced two
  collection errors because `ausl_session` did not exist. The UI/readiness
  slice then produced 13 expected failures before autosave/restore methods and
  readiness input existed. A later adversarial slice produced five failures
  for internal timestamp/membership validation, corrupt-current backup
  archive, and three distribution privacy filenames. Each slice passed after
  the corresponding narrow implementation.
- Automated acceptance:
  - Phase 6D schema/storage/UI plus readiness/Phase 6A/6C/privacy matrix —
    **149 passed in 4.26 s**;
  - complete offline warnings-as-errors suite — **654 passed in 21.54 s**;
  - `compileall`, `pip check`, checked-in core distribution verification,
    Git LFS pointer/materialization checks, whitespace validation, and
    tracked-file/history secret scans passed.
- Windows GUI smoke: deterministic source/real-Tk execution on
  `Windows-10-10.0.19045-SP0`, Python 3.12.10, at `1120x720`, using the
  checked-in local snapshot and isolated private state. It created an exact
  game/player/rundown/used state, saved active, closed cleanly, resumed,
  verified Offline Mode and copy events were not restored, deliberately
  terminated uncleanly, reopened with the recovery notice, reviewed the
  recovered rundown, injected a visible disk-full save failure, archived and
  started fresh, opened all seven tabs, made zero network calls, and closed
  normally. A separate Windows graphics-capture inspection was attempted but
  the helper returned `SetIsBorderRequired failed: No such interface
  supported (0x80004002)` twice; no coordinates were guessed. Real Tk widget
  mapping/state assertions and the full scripted interaction passed.
- Known limitations and deferred work: this is local single-user persistence,
  not shared/cloud synchronization. One validated backup and timestamped
  quarantine/start-fresh archives are retained; no cleanup UI is added.
  Source workbook refresh remains a separate atomic system. Phase 6E What
  Changed and Phase 6F fuzzy search/comparison have not started. The existing
  cooperative `urllib` cancellation limitation remains unrelated and
  unchanged.

### Phase 6C — Pinned rundown and on-air workflow

- Completion date: 2026-07-28.
- Starting commit and baseline: latest remote `main`
  `354995423d43c8f69fbc308d4dae7de5c5401944`. GitHub PR #5 had been
  merged into the already-merged Phase 6A branch rather than main, so the new
  `agent/phase6c-rundown-workflow` branch was created from that exact main
  commit and explicitly merged the completed Phase 6B line (including the
  reviewed fact-card wheel fix) at
  `71738c231761d26b763d31f80e64ffbbe85cec26`. The resulting clean offline
  baseline passed **559 tests in 17.67 s** with warnings treated as errors.
- Branch and final functional commits: `agent/phase6c-rundown-workflow`;
  `d67155d` adds the exact-game session rundown model and pure acceptance
  coverage; `8048f79` integrates pin/use/timing/reconciliation/export behavior
  into Game Day, adds privacy coverage, and adds the deterministic real-Tk
  smoke. The documentation acceptance commit is reported in the Phase 6C PR.
- Rundown model and game isolation: `src/ausl_rundown.py` owns frozen,
  serialization-ready `PinnedFactEntry`, `UsedFactRecord`, and
  `GameRundownState` values behind one isolated `RundownSession`. States are
  keyed only by exact numeric official game ID; repeat-opponent games remain
  separate. Pins retain the canonical immutable Broadcast Fact object, stable
  fact ID, evidence hash, provenance, trust state, timezone-aware pin time,
  dense position, and reconciliation state. Duplicate active pins and
  wrong/missing game identity fail closed.
- Ordering and lifecycle: reliable Move Up/Move Down buttons preserve every
  entry and dense positions; boundary moves are no-ops. Remove affects only
  session memory. Game switches restore that exact game's current-session
  queue. All mutations are synchronous local operations on the Tk main thread,
  create no timer/worker/network request, and remain usable in Local/Offline
  Mode. Closing intentionally discards the session because Phase 6D has not
  started.
- Read-time formula and break targets: exact Air Copy is tokenized with one
  Unicode-aware deterministic helper. Numbers/records, initials,
  abbreviations, hyphenated words, apostrophes, accents, and Unicode
  punctuation have explicit fixtures. Per-item seconds are
  `max(1, ceil(words / WPM * 60))` for nonempty copy, using the centralized
  default **140 WPM**; empty copy is zero. The active total is the sum of the
  displayed eligible per-item estimates. 15/30/45/60/90-second presets and
  validated 1–3600-second custom targets are exact-game local. Under/exact/over
  labels are workflow guidance and do not alter factual readiness.
- Used-on-air policy: Mark Used works from an active queue entry or an
  unpinned canonical card, records a timezone-aware timestamp and the exact
  aired evidence version, removes pinned items from active timing, and
  suppresses the stable fact ID from default suggestions for only that exact
  game. Show Used reveals current cards; history retains provenance and
  wording. Undo restores suggestion eligibility and returns a formerly pinned
  item to its deterministic prior position. A same-ID evidence update remains
  suppressed while a distinct watch-versus-reached fact ID remains eligible.
- Refresh reconciliation: an accepted exact-game fact rebuild reconciles only
  that game's existing pins. Same ID/hash remains current. Same ID/new hash
  retains the pinned snapshot and becomes `SOURCE CHANGED`; a trust downgrade
  becomes `VERIFICATION DOWNGRADED`; a missing fact becomes `INVALIDATED`.
  These entries leave air-ready timing/copy until reviewed. Deliberate
  Review / Replace Latest requires confirmation, preserves queue position,
  and then adopts the latest canonical evidence. Used history always retains
  the version actually aired. Generation/game/database guards continue to
  discard stale callbacks before reconciliation.
- Export and privacy: Copy Rundown and plain-text export include teams, exact
  game ID, schedule/venue when available, UTC export time, revision, target,
  active estimate, snapshot, verify reminder, separated active/review/used
  sections, exact wording, status, source/freshness, read estimates, and used
  timestamps. Filenames include UTC microseconds, exact game ID, and revision;
  exclusive creation never overwrites. Files go only under
  `data/exports/game_packets/rundowns`, which is covered by the existing Git
  ignore rule and distribution-forbidden game-packet policy. Tests exercise
  the nested rundown path specifically. Logs contain identity/hash/count
  metadata, never fact or producer-note contents.
- Failing-first evidence: the first 38 model tests failed at collection because
  `ausl_rundown` did not exist. After implementation, two fixture assertions
  were corrected without weakening behavior (case-sensitive exception text
  and three deliberately distinct export sentences), then all 38 passed.
  Ten UI tests next failed because no pin/use/rundown callbacks existed; all
  passed after canonical integration. The first real-Tk smoke exposed that a
  hidden Notebook subview reports a one-pixel canvas until selected; selecting
  the actual Rundown view before geometry/wheel assertions produced the real
  viewport and a passing wheel movement.
- Automated acceptance:
  - Phase 6C model/UI plus Phase 6B/6A and build privacy focused suite —
    **155 passed in 3.73 s**;
  - required Phase 6C/6B/6A, readiness/offline, exact-game, notes/media,
    enrichment, team/copy, refresh/callback, packet/privacy/portable, and
    future-season matrix — **339 passed in 7.35 s**;
  - complete offline warnings-as-errors suite — **611 passed in 19.82 s**;
  - `compileall`, `pip check`, checked-in distribution verification, Git LFS
    workbook validation, `git diff --check`, the actual nested export
    `git check-ignore`, and tracked filename/content/history secret scans all
    passed.
- Windows GUI smoke: deterministic source/real-Tk harness on
  `Windows-10-10.0.19045-SP0`, Python 3.12.10, exactly `1120x720`, using the
  checked-in local core snapshot and an isolated temporary private export
  directory with no network access. It selected an official game; pinned
  verified facts from both teams and a Needs Verification fact; reordered;
  set/validated a 30-second target and exact per-item sum; marked one pinned
  and one unpinned fact used; proved default suppression, Show Used, and Undo;
  switched repeat-opponent games and restored the first queue; injected a
  same-ID evidence change and retained/invalidated old wording; exported and
  inspected separated sections; enabled Offline Mode; moved the real rundown
  viewport by mouse-wheel event; opened all seven existing top-level tabs; and
  closed normally.
- Owner-reported content audit: the project owner reports running the
  developer-only optional enrichment refresh and manually reviewing the real
  resulting fact cards without observing dubious facts or enrichment issues.
  No specific samples or additional test details are inferred or asserted.
- Known limitations and deferred work: all rundown state is deliberately
  memory-only and is lost on close. No autosave, crash recovery, restart
  restoration, persisted scroll position, full Phase 6E change panel,
  historical version browser, fuzzy search, comparison, cloud/shared queue,
  graphics integration, generative rewriting, automatic shortening, or
  automatic ordering was added. Normal producer startup still loads core data
  only; optional enrichment remains developer-only and approval-gated. Phase
  6D through 6F have not started.

### Phase 6B — Air-ready fact cards

- Completion date: 2026-07-27.
- Starting commit and branch basis:
  `e87b4d7efabb9795bcbd5521aadedb742b5eb921`, the completed Phase 6A
  acceptance head on `agent/phase6a-command-center`. That head is directly
  based on latest remote `main`
  `19f2702266883e76bcd439c25044e01b98017daa`; Phase 6A remained open as
  draft PR #4, so Phase 6B was intentionally developed as a stacked branch
  rather than omitting its required dependency.
- Branch and final functional commit: `agent/phase6b-air-ready-facts`;
  `e64d53d` after canonical model `b2a8f30`, Game Day cards/synchronization
  `d7994ad`, canonical roster-state reuse `eda0bfd`, copy/width guidance
  `5febe19`, minimum-size GUI correction/smoke `919254e`, detailed smoke
  platform `f65823e`, and reviewed stale-starter gate `e64d53d`. The
  documentation-only acceptance commit is reported in the Phase 6B PR.
- Fact identity/version design: one frozen `BroadcastFact` owns category,
  exact player/team/game/season identity, stable source-record/concept key,
  headline, exact air copy, context, provenance, and trust state. `fact_id`
  hashes stable conceptual identity; `evidence_hash` separately hashes
  wording, supporting values, source evidence/history, approval, and trust.
  Numeric/evidence changes retain the conceptual ID when appropriate while
  invalidating the copied version. Later phases can pin this canonical value
  without parsing visible text.
- Supported adapters/categories: roster availability/injury/transaction
  warnings; official or projected selected-game starters; milestone watches;
  current-season form/context; official-note milestone reached, recent trend,
  season context, matchup/career/background categories when approved rows are
  explicitly loaded; approved media-guide background; exactly scoped
  air-safe producer notes; and official team-record context through the
  existing canonical team snapshot helper. No new data source or generative
  wording was added.
- Verification/air-ready policy: `air_ready` is derived and cannot be supplied
  or edited independently. VERIFIED requires exact subject/team/game/season
  identity, complete provenance, green source health, valid snapshot, no
  warning, no producer-confirmation requirement, and source-specific approval.
  Yellow becomes STALE; red/unknown is UNAVAILABLE; a failed latest refresh
  downgrades affected stored-snapshot facts to VERIFY while retaining the
  installed snapshot timestamp. Probable/projected starters never become
  confirmed starters, nonactive/unknown roster status stays review-blocking,
  wrong-game notes are excluded, `not_in_guide` produces no biography, and
  missing/malformed numeric values never become zero or `nan`.
- Selection/deduplication/readiness: facts are exact-game and selected-team
  scoped, deterministically ordered by safety/category with team balancing,
  and deduplicated while retaining the strongest authoritative evidence plus
  useful source history. Only unresolved safety-blocking facts contribute to
  the Phase 6A verification count; optional background review does not block
  readiness. Missing/in-flight fact state remains unavailable rather than
  zero.
- Copy/provenance behavior: Copy Air Line is disabled unless the visible fact
  is air-ready and records an in-memory canonical event with fact ID, evidence
  hash, full provenance, snapshot, copy time, exact string, and selected width
  profile. Copy With Source includes status, source, date, freshness, IDs, and
  warnings for research/handoff. Copy never changes verification; game or
  database changes clear stale copy state, and an evidence-hash change
  invalidates a previously copied version. No copy history is persisted.
- Character profiles: centralized 60-character `one_line` and 120-character
  `extended` guidance. Python Unicode string length is applied to the exact
  copied air line; punctuation, curly apostrophes, em/en dashes, jersey
  numbers, and accented names are covered. The UI reports fits/near
  limit/likely wraps and never truncates or rewrites factual copy.
- Worker/main-thread behavior: local fact aggregation uses one daemon worker
  with one coalesced latest pending request. All Tk mutations remain on the
  established main-thread queue. A late result must still match build
  generation, exact official game ID, and database object identity. Game
  changes clear old cards immediately; database replacement, lineup change,
  and manual-note change rebuild facts. Local/Offline Mode continues to permit
  local fact generation and performs no network request.
- Failing-first evidence: the initial Phase 6B tests failed during collection
  twice because `ausl_facts` did not exist. After the model was implemented,
  46 behavioral tests passed and one hand-counted Unicode expectation exposed
  an incorrect test expectation (the exact string contains 28 code points,
  not 27); correcting that test produced 47 passing model tests. Subsequent
  UI integration first failed one Phase 6A close test because its minimal app
  fixture lacked the new worker-generation field; the lifecycle guard fixed
  it without weakening shutdown. The first real-Tk smoke then exposed a
  22-pixel fact viewport at minimum size; the internal Game Day Facts/Readiness
  views increased the asserted scrollable viewport to 254 pixels. Final diff
  review added one failing regression proving that a fully approved official
  starter with yellow roster health was mislabeled projected; the corrected
  adapter retains CONFIRMED STARTER identity but makes it STALE and non-air-ready.
- Automated acceptance:
  - required Phase 6B plus readiness, selected-game, official-note, media,
    enrichment, team/stat formatting, roster/copy, callback/refresh,
    privacy/build, and future-season matrix — **357 passed in 3.41 s**;
  - complete offline warnings-as-errors suite — **557 passed in 11.93 s**;
  - final `compileall`, `pip check`, checked-in distribution verification,
    Git LFS validation, whitespace validation, and tracked/history secret scans
    are recorded in the Phase 6B PR completion report.
- Windows GUI smoke: deterministic real-Tk source harness on
  `Windows-10-10.0.19045-SP0`, Python 3.12.10, exactly `1120x720`. It began
  with no selected game; loaded checked-in local data without refresh; selected
  an official game; found verified facts for both teams; switched Air Ready
  and Needs Verification; copied an exact verified line and the sourced form;
  rejected ordinary copy for a review fact without changing the clipboard;
  matched character count to clipboard text; changed between repeat-opponent
  Games 916/917 and proved all old fact IDs disappeared; replaced a local
  database value/snapshot and proved evidence changed and copied state cleared;
  enabled Local/Offline Mode and rebuilt local facts; opened all seven existing
  tabs; asserted a 254-pixel scrollable fact viewport; and closed normally.
  Final Game 917 held 58 facts: 56 air-ready and two blocking review items.
  No network refresh, factual workbook, lineup, private note, or packet was
  written.
- Computer Use inspection: the skill found and activated exactly one
  `AUSL Phase 6B Smoke` window. Tk exposed no useful accessibility text;
  Windows Graphics Capture returned
  `SetIsBorderRequired ... No such interface supported (0x80004002)`. The
  harness completed and closed normally before the recovery capture, so no
  coordinates were guessed and visual acceptance rests on the deterministic
  real-Tk widget/clipboard/geometry assertions.
- Known limitations: normal producer startup intentionally loads only core
  data, so approved optional official-note/media facts appear only when an
  explicit enrichment database is supplied and all existing gates pass.
  Character thresholds are guidance, not an XPression/template contract.
  Copy events are memory-only. No Linux/Xvfb GUI smoke was performed locally.
  Historical integration note: Phase 6A subsequently merged to main, but
  Phase 6B PR #5 merged into the already-merged Phase 6A branch. Phase 6C
  therefore integrated that completed branch explicitly from a new main-based
  worktree.
- Intentionally deferred: Phase 6C pinned rundown, drag/order, read-time, and
  used-on-air workflow; Phase 6D session/crash recovery; Phase 6E What
  Changed; Phase 6F fuzzy search/quick filters/player comparison; College
  Résumé; graphics integration; persistence; and generative rewriting.

### Phase 6A — Game-day command center, readiness, and Local/Offline Mode

- Completion date: 2026-07-27.
- Starting commit: remote `main`
  `19f2702266883e76bcd439c25044e01b98017daa`, which includes the merged
  Phase 5 stabilization pass.
- Branch and final functional commits: `agent/phase6a-command-center`;
  readiness policy `0eeefa36b579fbf1a89a8222e3ad3585fffb23c2`;
  command center/Offline Mode
  `0c994a1a94be5539e226cb641c984b3a4fe58356`. The documentation commit
  containing this acceptance record is reported in the Phase 6A PR.
- Automated acceptance:
  - focused Phase 6A plus selected-game, lineup, refresh, health, staging,
    cancellation, live, packet, callback, privacy, portable-build, and
    future-season command — **207 passed in 3.03 s**;
  - full offline warnings-as-errors command
    `.venv\Scripts\python.exe -W error -m pytest -q` —
    **491 passed in 12.19 s**;
  - `compileall`, `pip check`, checked-in distribution verification, Git LFS
    verification, whitespace validation, and tracked/history secret scans
    passed in the final acceptance run.
- Windows GUI smoke: deterministic source-app/real-Tk smoke passed on
  `Windows-10-10.0.19045-SP0` at exactly `1120x720`. It began with no selected
  game, selected exact Game 914, saved a projected lineup without promoting it
  to ready, generated a revision-matched packet, enabled Offline Mode, proved
  core/live refresh and timer routes made zero requests, changed to Game 915
  and cleared old lineup/packet/live state, disabled Offline Mode without a
  request, closed, and relaunched in a separate process. Relaunch defaulted
  Offline Mode off and recovered only the exact-game local lineup/packet
  artifacts in the isolated smoke directory. No production data or private
  producer files were written.
- Computer Use inspection: the skill found and activated the exact smoke
  window. Windows Graphics Capture failed twice with
  `SetIsBorderRequired ... No such interface supported (0x80004002)`, so no
  coordinate guesses were made; layout acceptance comes from the asserted
  real-Tk minimum-size harness.
- Producer-visible changes: first-tab `Game Day` command center; one prominent
  `READY FOR AIR`/`NEEDS ATTENTION`/`NOT READY` result; plain-language ordered
  checklist; exact schedule/lineup/live/packet identity and freshness; snapshot
  versus latest-attempt health; honest scoped verification state; and a
  persistent visible Local/Offline Mode control beside refresh and inside the
  dashboard.
- Readiness policy: any blocking failure wins; warnings cannot be
  acknowledged into verified state; unknown never passes; official lineup
  provenance requires the existing complete canonical evidence; projected,
  manual, and imported lineups remain warnings; a feed or schedule reporting a
  live game makes stale/disconnected exact-game live data blocking; pregame
  disconnection is a warning; packets must match exact game and current lineup
  revision; there is no stored or editable force-green Boolean.
- Known limitations: the normal core-only loader intentionally does not load
  optional verification rows, so its scoped verification count displays
  `Unavailable` rather than a misleading zero and prevents a green state until
  reliable reviewed context is available. `urllib` cancellation remains
  cooperative during one bounded in-flight call. Existing packet and lineup
  files are used for restart display; broader session/crash recovery is
  deferred.
- Intentionally deferred: Phase 6B fact cards; Phase 6C pinned rundown,
  read-time, and used-on-air flow; Phase 6D session recovery; Phase 6E change
  comparison; Phase 6F fuzzy search and player comparison. No Phase 6B–6F
  storage or UI was implemented.

### Milestone 1 — Broadcast-safety foundation

- Completion date: 2026-07-19
- Source version/commit: local Git baseline commit `b008c971d192233484429cbe67f7ccf374e477b9` on branch `main`; deterministic release-source fingerprint `SHA-256 86e5a5f00445199b421fb12743bbb449f12626e49bc056a635753de8f848ee09` over the 58-file reviewed staged release-source manifest / 2,729,520 bytes; the same manifest hashes identically in the deployed live folder. Algorithm: SHA-256 of sorted UTF-8 relative path, NUL, file SHA-256, and newline records; excludes the tracker itself, generated `.spec`, `.venv`, `_backups`, `build`, `dist`, Git/test caches, `pytest-*`, `.pytest-*`, `data/manual`, `data/exports/game_packets`, and Python bytecode. Additional unchanged archival/source assets that exist only in the live folder are outside this manifest.
- Automated test command and result: final staged `.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp\full-final` — 253 passed in 34.74 s; deployed-source read-only rerun with isolated staged temp data — 253 passed in 33.65 s; prebuild full suite — 253 passed in 33.69 s; independent `.venv\Scripts\python.exe -m pytest -q` — 253 passed in 35.32 s. `.venv\Scripts\python.exe -m compileall -q src tests tools` passed; `.venv\Scripts\python.exe -m pip check` reported no broken requirements. Focused career/production suite: 39 passed; build/privacy suite: 24 passed.
- Windows smoke-test environment: Windows 11 64-bit, build `10.0.26200.0`; Python 3.12.13; Tcl/Tk 8.6; PyInstaller 6.21.0. Tested the final packaged EXE offline before a final clean rebuild.
- Producer-visible changes: explicit player/team/game/global note scope and exact player picker; authoritative standings reused across team totals/prep/packets with source and timestamp; active-only recommendations and an availability-impact path; unmistakable reserve/inactive/unknown warnings with copy confirmation; distinct copy types; canonical innings/rate formatting; visible July 9 freshness/VERIFY labeling; structured non-private logging; and clean core-only EXE/no-EXE distributions with SHA-256 sidecars/manifests.
- Known limitations remaining: Phase 2 must add exact selected-game synchronization and structured lineup validation; media-guide, official-game-note, split, and storyline enrichment may remain in the source tree for isolated development but is disabled in normal refresh/startup and absent from the distributable until later identity/verification gates pass; live refresh was not invoked and still requires the network; per-source health/cancellation/timer ownership remain planned; the unsigned EXE may trigger Windows reputation warnings; first launch creates an empty manual-note template beside an unpacked executable, so a per-user storage migration remains an inbox idea. No producer acceptance rehearsal has occurred yet.
- Verified by: Codex automated tests and six-tab Windows smoke test, plus an independent read-only acceptance audit; not yet producer-signed-off.

### Milestone 2 — Exact game and lineup workflow

- Completion date: 2026-07-19
- Source version/commit: branch `phase-2-exact-game-lineups`; source head `e8e490b` (`fix: synchronize selected player after refresh`) after reviewable game, lineup, packet, search, and refresh commits.
- Automated test command and result: dedicated Phase 2 acceptance command `.venv\Scripts\python.exe -m pytest -q tests\test_selected_game.py tests\test_lineup_storage.py tests\test_lineup_validation.py tests\test_packet_identity.py tests\test_search_state.py tests\test_refresh_state.py --basetemp=work\pytest-phase2-final-focused` — 45 passed in 0.55 s; full offline regression `.venv\Scripts\python.exe -m pytest -q --basetemp=work\pytest-phase2-final-full` — 310 passed in 12.92 s. `.venv\Scripts\python.exe -m compileall -q src tests tools` passed; `.venv\Scripts\python.exe -m pip check` reported no broken requirements. The final refresh unit also passed 79 focused/adjacent tests in 0.74 s after four failing-first tests.
- Windows smoke-test environment: Windows 11 64-bit source application using the local Python 3.12 virtual environment and offline checked-in data. All writes were redirected to ignored `work` fixtures; no live network request or producer-data write was made.
- Producer-visible changes: official schedule-driven game selection with exact game ID/time/source/freshness; atomic game changes across search, player, lineup, prep, notes, live ID, and packet context; exact-game lineup locks with recoverable fail-closed legacy migration; structured lineup errors and confirmation warnings; explicit projected/not-official labels; exact-game collision-resistant packet names; honest search scope; and refresh-time selected-player/card/note synchronization.
- Known limitations remaining: legacy matchup locks are preserved as `legacy_unassigned` but have no dedicated attachment UI; the six-hour lineup-staleness threshold remains an implementation assumption pending producer feedback; the checked-in official source snapshot is dated July 9; live network refresh was not invoked; experimental media/official-note/split enrichment remains disabled pending Phase 3 verification; no producer acceptance rehearsal has occurred. Ignored manual-smoke output remains under `work` and is excluded from distributable builds.
- Verified by: Codex automated acceptance/regression tests and offline Windows source-app smokes covering repeat-matchup selection and state clearing, exact-game lock isolation, rejected projected-lineup confirmation, packet identity, search scope/status/jersey behavior, and rerendering the same selected player and broadcast note from a refreshed database version. Not yet producer-signed-off.

### Milestone 3 — Verified media and official storylines

- Completion date: 2026-07-22
- Source version/commit: branch `codex/phase-4-official-storylines`; Phase 4 source head `c5877d8` after official-note foundation `91ccc88`, exact-game selection `2d6b3bb`, structured producer-prep work `bbe60e1`, and final stale/classification safety review.
- Automated test command and result: `.venv\Scripts\python.exe -m pytest -q tests\test_official_game_notes_phase4.py tests\test_official_note_selection.py tests\test_producer_prep_phase4.py --basetemp=work\pytest-phase4-final-focused-reviewed` — 13 passed in 0.22 s; full offline regression `.venv\Scripts\python.exe -m pytest -q --basetemp=work\pytest-phase4-final-reviewed` — 338 passed in 53.21 s. `.venv\Scripts\python.exe -m compileall -q src tests tools` passed and `.venv\Scripts\python.exe -m pip check` reported no broken requirements.
- Media identity audit result: Phase 3's local 280-page audit remains 118 unique roster rows: 96 `verified`, 8 `needs_review`, and 14 `not_in_guide`, with validated PDF offset `+2` and no inferred biography for absent players.
- Official-note classification audit result: the hand-auditable offline corpus passed all 13 category cases, including retrospective announced/starting-pitcher and non-record tie safeguards in addition to the three required false-positive regressions; exact Game 9001 selection excluded the later repeat-opponent Game 9002, deduplicated repeated PDF content, placed confirmed availability before lower context, and included verified CHI and CAR material. Explicit `[STALE]` material remained review-only.
- Windows smoke-test result: a real Tkinter window opened all six tabs with offline fixtures and selected official Game 9001. Producer Prep rendered all 11 named sections once, showed verified source/date/game/page labels, isolated incomplete provenance under `[VERIFY]`, excluded the repeat-opponent note, and kept the availability fact single-instance in both screen prep and the shared packet-intro model. Startup loading was disabled for the smoke; no network, manual note, lineup lock, export, or packet write occurred.
- Producer-visible changes: conservative nine-category official-note labels; exact subject/team/opponent and source metadata; normalized-hash deduplication with source history; authoritative exact-game selection; both-team balancing; availability/starter priority; explicit `[VERIFIED]`, `[VERIFY]`, and `[STALE]` states; structured Producer Prep sections; and nonduplicative packet storylines rendered from the same model.
- Known limitations remaining: automated PDF extraction deliberately remains `VERIFY`/`needs_review` until reviewed, so no unreviewed item can enter air-ready copy. Official-note enrichment remains disabled in normal startup and distributions until Phase 5 staging/source-health gates; no live official-note workbook was promoted during this phase. Where the source row exposes no separate PDF publication date, effective/source date uses the authoritative schedule game date. `STALE` must currently be explicit rather than inferred from an unapproved age threshold. The checked-in core snapshot remains July 9; eight media-guide players remain review-only and fourteen remain correctly absent. No live network refresh or producer acceptance rehearsal occurred.
- Verified by: Codex failing-first offline tests, full regression/compile/dependency gates, and the no-write Windows/Tkinter source smoke; not yet producer-signed-off.

#### Phase 4 acceptance — Useful official notes and nonduplicative producer prep

- Completion date: 2026-07-22
- Source version/commit: source commits `91ccc88`, `2d6b3bb`, `bbe60e1`, and `c5877d8` on `codex/phase-4-official-storylines`.
- Acceptance behavior: generic career copy is `career_summary`; WCWS-only history is `background`; retrospective starting-pitcher copy is not `probable_starter`; verified availability precedes lower context; both teams are represented when both have verified candidates; repeat PDFs collapse before display; top storylines are structured objects rather than copied prep bullets; and every air-ready official note carries verification, date, PDF, exact game, and page.
- Validation evidence: 13 focused Phase 4 tests passed, the 338-test offline suite passed, compilation/dependencies passed, and the targeted six-tab Tkinter smoke passed without a network call or write.
- Limitations: review-only notes are visible only in the explicit verification queue and cannot enter air-ready official-note lines or top storylines. Actual source promotion and health/staleness policy automation remain Phase 5 work.

#### Phase 3 acceptance — Trustworthy media-guide extraction

- Completion date: 2026-07-22
- Source version/commit: branch `codex/phase-3-trustworthy-media`; source head `e135100` after exact identity, page-range, audit/deduplication, and provenance-label commits.
- Automated test command and result: `.venv\Scripts\python.exe -m pytest -q tests\test_media_guide_identity.py tests\test_media_guide_quality.py tests\test_enrichment_safety.py tests\test_build_privacy.py --basetemp=work\pytest-phase3-final-focused-2` — 43 passed in 0.93 s; clean detached full regression — 325 passed in 44.17 s. `.venv\Scripts\python.exe -m compileall -q src tests tools` passed and `.venv\Scripts\python.exe -m pip check` reported no broken requirements.
- Media identity audit result: read-only parse of the local 280-page guide produced 118 unique roster audit rows and calculated/validated PDF offset `+2`: 96 `verified`, 8 `needs_review`, and 14 `not_in_guide`, all dated 2026-06-01. Sydney Romero, Morgan Zerkle, and Rachel Garcia retained their exact printed/PDF ranges; multi-page ranges were merged in order. Final extraction produced 575 deduplicated media notes, including 537 explicitly air-ready rows; broken `remain- der` text was absent.
- Windows smoke-test result: offline Tkinter harness showed Reese Atwood as `NOT IN GUIDE` with no inferred biography, Jocelyn Erickson as browse-only `VERIFY` with the missing-header warning, and Rachel Garcia as `VERIFIED` with printed pages 204-206, PDF pages 206-208, and June 1 guide date. The smoke app closed normally without a network call or note, lineup, packet, or export write.
- Producer-visible changes: player and team media lines now display verification state, guide date, and printed/PDF provenance; review-only rows are visible in Sources/Notes but excluded from automatic storylines and packets; absent players state that no biography was inferred. A nine-column audit workbook is available only during explicit developer enrichment and remains excluded from default startup/distributions.
- Known limitations remaining: eight TOC-listed players remain `needs_review` because their expected name/header was not text-extracted from the mapped PDF range; fourteen current players joined after the June 1 guide and correctly have no guide biography. The audit workbook and all media enrichment remain developer-only until later refresh/health gates. Official-note classification, exact-game storyline selection, and producer-prep restructuring are Phase 4 and are not claimed here. No producer sign-off has occurred.
- Verified by: Codex offline tests, full clean-snapshot regression, full local-PDF identity audit, and Windows source-view smoke; not yet producer-signed-off.

### Milestone 4 — Resilient refresh and producer UX

- Completion date: 2026-07-27 for the Phase 5 stabilization slice. Phase 6
  producer-speed UX remains outside this record and has not started.
- Source version/commits: functional stabilization commits
  `4967f5b31280ed67241a2e20385cbd0d4ae5ae4e` and
  `b22ea3a067f8584cd174684e611e98e9fcae275f` on
  `agent/phase5-stabilization`, based on remote `main`
  `0a52db18cb98e0603e0cc6fd7222a23719e4d5ba`.
- Automated result: `.venv\Scripts\python.exe -W error -m pytest -q` —
  **458 passed in 12.19 s**. `python -m compileall -q src tests tools` passed;
  `python -m pip check` reported no broken requirements;
  `python tools\verify_distribution.py data\exports` reported
  `Clean distribution verified`. The checked-in Git LFS workbooks are real
  XLSX bytes.
- Failing-first evidence: the future-season file produced 7 intended
  failures before 12/12 passed; the same-URL PDF, serialized commit,
  latest-attempt health, portable-manifest, and checked-in-distribution
  regressions all failed against the prior implementation before passing.
- Rehearsal result: truck-hardware smoke testing and producer rehearsal are
  recorded as completed based on the project owner's report. Hardware,
  scaling, date, and detailed behavior were not supplied and are not invented
  here. Codex's focused GUI cancellation/queue smoke result is recorded in the
  2026-07-27 change-log entry.
- Known limitations remaining: cancellation is cooperative rather than a raw
  socket abort, so one request already inside `urlopen` may live until its
  bounded timeout; official source facts remain producer-verified before air;
  optional enrichment remains developer-only/approval-gated; the checked-in
  snapshot is dated 2026-07-23; Phase 6 items remain
  `PLANNED`/`BACKLOG`.
- Verified by: Codex failing-first offline tests, full
  regression/compile/dependency/distribution gates, focused GUI smoke, and the
  project owner's report for truck-hardware smoke/rehearsal completion.

## Producer-meeting questions to preserve

- Which information do you most often need to recover quickly during a game?
- Which parts of pregame preparation take the most time today?
- What information must always be independently verified before air?
- Do you prefer concise suggested storylines or a deeper searchable reference?
- Which college facts are most useful: career numbers, final season, awards, WCWS history, teammates/rivals, or school records?
- How should inactive, injured, unconfirmed, or stale information be presented?
- What would make you trust—or stop trusting—an automated storyline suggestion?
- Who else would use the app or its exports during a broadcast?

## Ideas inbox

Add unreviewed ideas here first. Promote them to the master list only after assigning a stable ID, priority, and completion condition.

- 2026-07-19 — Move producer-authored notes and lineup locks from the portable install tree to a per-user application-data directory. Require an explicit, backed-up migration/import path so existing files remain recoverable; clean builds already omit these files, but first launch currently creates an empty note template beside an unpacked executable.
- 2026-07-22 — **PROMOTED to `GAME-002`**: historical prep uses a strict selected-game time cutoff and does not describe current standings as the record entering a past game.
- 2026-07-22 — **PROMOTED to `PACKET-001`**: lineup and starter packet headings derive from stored provenance; `official` is reserved for validated authoritative input.
- 2026-07-22 — **PROMOTED to `LINEUP-005`**: lineup save/delete transactions are atomic in memory and on disk, with persistent UI failure status.
- 2026-07-22 — **PROMOTED to `BUILD-002`**: portable ZIPs use POSIX member paths and pass cross-platform extraction tests.
- 2026-07-22 — **PROMOTED to `DOC-001`**: first-pitch missing-value mojibake and README workflow drift are repaired.
- 2026-07-24 — **PROMOTED to `UX-006`**: read-time budgeting on fact cards and pinned rundown against a break-length target.
- 2026-07-24 — **PROMOTED to `UX-007`**: mark facts "used on air" with a timestamp to suppress repeat suggestions within a game.
- 2026-07-24 — **PROMOTED to `UX-008`**: session/crash recovery for producer working state, separate from lineup/note storage.
- 2026-07-24 — **PROMOTED to `UX-009`**: "Ready for Air" readiness indicator and pregame checklist.
- 2026-07-24 — **PROMOTED to `SEARCH-005`**: fuzzy/typo-tolerant name matching.
- 2026-07-24 — **PROMOTED to `UX-010`**: character-count preview on copy actions for graphics-template widths.
- 2026-07-24 — **PROMOTED to `REFRESH-007`**: explicit Local/Offline Mode toggle for producer-designated live windows.
- 2026-07-24 — **PROMOTED to `UX-011`**: side-by-side player/matchup compare view.

## Update instructions for Codex

When working on this tracker:

1. Preserve the existing item IDs.
2. At the start of a pass, change chosen items to **NEXT** or **IN PROGRESS**.
3. Do not check an item merely because code was written. Check it only after its stated tests and acceptance behavior pass.
4. When checking an item, add a dated change-log entry with evidence such as tests, source version, and important limitations.
5. If an item is postponed, retain it and mark **DEFERRED** with a reason.
6. Put new ideas in the Ideas inbox before prioritizing them.
7. Update the `Last updated` date whenever the file changes.
8. Keep the detailed implementation guide aligned if a decision materially changes the technical plan.

## Change log

### 2026-07-29

- Restored the Phase 6F acceptance status accidentally reverted by the
  project-owner roadmap replacement. `SEARCH-004`, `SEARCH-005`, `UI-003`, and
  `UX-011` are complete; Player Lookup and Compare Players satisfy their
  scoped `UI-001` scrolling behavior; `UI-002` remains open for the owner's
  100%/125%/150% Windows scaling sign-off.
- Started the independent-review stabilization from remote `main`
  `bca5be6286996da844e0f260ae1e06f1feaf054e` on
  `agent/phase6-final-stabilization`. Functional commit `55a4af0` adds
  independent per-fact comparison provenance, separates the statistical
  snapshot label, expands the correct Player Lookup row, adds conservative
  token-level typo matching, and treats ordinary straight/smart apostrophes
  as name characters while preserving strict double-quoted filters.
- Failing-first evidence for this pass was **15 failed, 55 passed**: seven
  search/parser failures, five comparison-provenance failures, one layout
  failure, and two stale-documentation failures. The first implemented
  search/comparison/UI slice then passed **68 tests**, and the adjacent
  Phase 6F/fact/session/media matrix passed **168 tests**. Final cross-phase,
  packaging/privacy, and GUI results are recorded in the separate
  stabilization acceptance record.
- Updated the current milestone to Phase 6F plus the full Phase 6 acceptance
  review; no Phase 6F item is marked complete by this planning update.
- Promoted approved optional enrichment and the College Résumé from backlog to
  the ordered Phase 7 roadmap based on direct producer feedback.
- Added `ENRICH-001` through `ENRICH-004`, made `SPLIT-001` through
  `SPLIT-003` Phase 7A prerequisites, and assigned `COLLEGE-001` through
  `COLLEGE-008` to Phases 7B–7E.
- Deferred exhaustive season-by-season college statistics until the ten-player
  pilot and producer review prove that the additional breadth is worth its
  verification and maintenance cost.

### 2026-07-23

- Refreshed the five checked-in core exports from official AUSL sources with optional enrichment disabled. The final promoted manifest is `2026-07-23T18:08:06.854069+00:00`; the checksum-verified prior snapshot is recoverable under `_backups\2026-07-23_pre_core_refresh`. A failing-first regression also closed a refresh-provenance gap so every new manifest retains the formula, source audit field, adoption date, and fail-closed policy for normalized season pitching WHIP.
- Workbook validation passed with 63/118 roster rows for 2025/2026, 18 unique official standings rows, and 76 unique official game IDs with parseable dates and valid opponents. The schedule contains 75 completed games and one postponed game; no game IDs were added or removed. Every season pitching row retained `source_whip`, published formula-derived WHIP only when its source inputs were valid, and failed closed otherwise.
- The official 2026 regular-season records are now CHI 16-9, UTA 16-9, PDX 14-11, OKC 13-12, CAR 9-16, and TEX 7-18. The current-roster identity delta is Jala Wright (`player_id` 1308) added as `Reserve Pool` with no team assignment and Emiley Kennedy (`player_id` 1097) removed; the application does not infer a team or active status for either case.
- The expected failing baseline produced 12 snapshot-version errors against the retired July 9 timestamp, and a separate failing-first manifest regression exposed the missing WHIP-normalization provenance. After updating the narrow checked-in snapshot regression and refresh manifest, the final focused refresh/standings/status/WHIP suite passed 53 tests; the full offline suite passed 392 tests in 9.91 s and again with warnings as errors in 9.73 s. Compilation passed and `pip check` found no broken requirements.
- The Windows/Tk smoke opened all six tabs, loaded 118 players, displayed July 23 freshness plus `VERIFY BEFORE AIR`, retained exact official Game 987, showed Carolina 9-16 in Team Totals and OKC 13-12 / CAR 9-16 in Producer Prep, kept lineup and manual-note stores empty, left live data unloaded, and rendered Jala Wright as `Reserve Pool`, `TEAM UNKNOWN`, with a visible availability warning. A final relaunch loaded the promoted 6:08 PM UTC snapshot. No manual note, lineup lock, producer packet, optional enrichment, or live-game request was written or sent.
- Limitations: this is a dated official-source snapshot, not a guarantee that facts remain current; run a guarded core refresh and repeat verification shortly before the demo if the source is healthy. Eight media identities remain review-only, target-truck scaling and producer rehearsal remain pending, and this refresh does not advance Gate C or claim unattended live-broadcast readiness.

### 2026-07-22

- Recompleted the independent Phase 4 stability remediation in source commits `c6f9051`, `5a8e003`, `9ca88da`, `67dbc6b`, `6fbbd97`, and `6b6fa08`. Failing-first evidence was 5 exact-game/history failures, 15 lineup/packet failures, 13 media-approval failures, 3 refresh rollback failures, 7 live-health failures, and a missing portable-ZIP writer plus two first-pitch regressions. Focused reviewed gates passed 43 game/live tests, 55 lineup/packet tests, 58 media tests, 41 refresh tests, 39 live-health/callback tests, and 60 packaging/formatting tests, all with warnings as errors where applicable. The full offline suite passed 390 tests in 49.10 s and again with warnings as errors in 47.05 s; compilation passed and `pip check` found no broken requirements.
- The no-network Windows/Tk smoke opened all six tabs from the checked-in snapshot, selected official Game 987, confirmed the Live Game ID was read-only, blocked detached Game 988 before fetch, rendered a valid DP/FLEX as nine hitters plus one FLEX, kept an adversarial review-only media row out of air-ready output, and displayed authoritative green/current live freshness. No real lineup, note, packet, or live request was written or sent.
- The real safer no-EXE build passed the distribution privacy verifier before and after compression. Its 16 ZIP members contain zero backslashes, CRC and extraction passed, and SHA-256 is `58d5b542567d870f310ad8601e37bc52db5c1a500369df2497ed68174b60b860`.
- Remaining limitations: the checked-in core snapshot is still dated July 9 and was not refreshed from the live internet; eight media-guide identities remain review-only and require a complete approval transaction; `REFRESH-004` through `REFRESH-006`, `HEALTH-001`, target-truck scaling checks, and producer rehearsal/sign-off remain planned. This pass supports a controlled offline producer demo, not unattended live-broadcast use.
- Completed `PREP-001`, `PREP-002`, Phase 4, and Milestone 3 in source commits `bbe60e1` and final safety review `c5877d8`. Three failing-first prep tests established the sectioned `ProducerPrep`/`ProducerStoryline` model, a shared screen/packet-intro renderer, and single-instance top-storyline facts; the final review added explicit stale-state gating and two conservative-classification regressions. The reviewed Phase 4 suite passed 13 tests in 0.22 s, the full offline regression passed 338 tests in 53.21 s, compilation passed, and `pip check` found no broken requirements. The offline Windows/Tkinter smoke opened all six tabs and verified exact Game 9001, all 11 section headings, repeat-opponent exclusion, CHI/CAR balance, source/verification labels, the separate review queue, and nonduplicative screen/packet storylines without any network request or write. Official-note promotion remains gated behind Phase 5 source-health work, and extracted notes remain review-only by default.
- Completed `GNOTE-004`, `GNOTE-005`, and `GNOTE-006` in source commit `2d6b3bb`. Four failing-first selection tests plus adjacent game/enrichment regressions established authoritative selected-game-ID filtering, both-team balance, safety-first category priority, repeated-PDF screen deduplication, and complete verification/source labels. The focused/adjacent suite passed 41 tests in 0.67 s. Rows with missing provenance are downgraded to `[VERIFY]` and excluded from air-ready official-note lines; they remain available only through the separate review queue. When one side has no verified exact-game candidate, the air-ready output says so explicitly instead of filling all default facts from the other team without warning.
- Completed `GNOTE-001`, `GNOTE-002`, and `GNOTE-003` in source commit `91ccc88`. Five failing-first Phase 4 tests established conservative nine-category classification, exact header player/team propagation, fail-closed extraction metadata, normalized content hashes, subject-safe repeated-PDF deduplication, and retained source history. The focused classification/parser/safety suite passed 29 tests in 0.35 s. Extracted PDF notes remain `VERIFY`/`needs_review` until explicitly verified; source/effective date currently uses the authoritative schedule game date because no separate PDF publication date is exposed by the source row.
- Completed `MEDIA-001`, `MEDIA-002`, `MEDIA-003`, and `MEDIA-005` in source commit `a07ed55`. Five failing-first identity tests established exact TOC mapping, evidence-derived offset validation, complete ordered page ranges, explicit absence, and fail-closed parser failure. The focused parser/enrichment/callback suite passed 38 tests, the non-production suite passed 304 tests, compilation passed, and the clean detached full regression passed 316 tests in 41.37 s. A read-only parse of the local 280-page guide mapped all 118 current roster players with calculated offset `+2`: 96 `verified`, 8 `needs_review` because an expected extracted header was absent, and 14 `not_in_guide`; guide date `2026-06-01` was recorded. Sydney Romero, Morgan Zerkle, and Rachel Garcia mapped to printed/PDF ranges `141-142`/`143-144`, `47-48`/`49-50`, and `204-206`/`206-208`. Parser validation failure now leaves the five prior media workbooks byte-identical instead of replacing them with empty output. The July 20 core working exports were not modified, staged, or committed. `MEDIA-004` and `MEDIA-006` remain in progress; no Phase 4 work has started.
- Completed `MEDIA-004`, `MEDIA-006`, and Phase 3 in source commits `f956d99` and `e135100`. Eight failing-first quality/export/display tests plus one team-provenance test established wrapped-hyphen/year repair, category deduplication, the exact nine-column audit export, distribution exclusion, verified provenance labels, browse-only review warnings, and explicit guide absence. Final Phase 3 tests passed 43 in 0.93 s and the full clean regression passed 325 in 44.17 s; compilation and dependency checks passed. The final read-only PDF audit retained 118 unique rows and the safe 96 verified / 8 review / 14 absent split, reduced output to 575 deduplicated notes, and removed broken `remain- der` text. The offline Windows smoke displayed all three verification states correctly. No production export, manual note, lineup, packet, or live source was written; the user's July 20 core exports remain uncommitted and untouched. Phase 4 has not started.

### 2026-07-19

- Created the master improvement tracker from the source audit and implementation guide.
- Added the proposed separate College Résumé feature and its staged data strategy.
- Marked the broadcast-safety foundation as the next implementation milestone.
- Completed and verified `BASE-001`, `BASE-002`, and `QA-001`: the offline suite contains 253 tests with hand-auditable fixtures and passed prebuild, independent, and final runs (33.69 s, 35.32 s, and 34.74 s); the packaged Windows app passed all six tab checks without a network call or producer-data write.
- Completed and verified `BUILD-001`, `BUILD-002`, and `OPS-001`: exact dependency pins and structured privacy-safe JSONL logging are covered by tests; both noninteractive build scripts passed; all four directory/ZIP targets passed `tools\verify_distribution.py`; both ZIPs passed CRC and sidecar checks. Final hashes: Windows ZIP `5ec5e31961bff2d5d084aeb75f04f2ce96b198c675232ad90d067c850d5d3879`; safer no-EXE ZIP `41db51a943d7faa6e668fe3a9b84e1dac032acc7857dc394c2de2fdfbf6fe6e7`.
- Completed and verified `SAFE-001` and `SAFE-002`: callback failures preserve their original exceptions, initial/update/live sources each reject overlapping work, and action state is restored on success/failure; dedicated callback and operation-state regressions pass.
- Completed and verified `NOTE-001`, `NOTE-002`, and `NOTE-003`: scope isolation, exact/ambiguous identity handling, full-list rendering, recoverable pre-migration backups, and atomic writes pass offline tests. Manual smoke showed an empty clean-build note store; no note was saved.
- Completed and verified `TEAM-001`, `TEAM-002`, and `TEAM-003`: official rows must be unique and pass record/run/domain/freshness/provenance checks; Chicago rendered `11-7` in Team Totals and producer prep, while pitcher decisions remain separately labeled calculated aggregates.
- Completed and verified `COPY-001`, `COPY-002`, `COPY-003`, `ROSTER-001`, and `ROSTER-002`: every roster player/copy type passes; active copy actions work; a Reserve Pool card showed no `nan`, visible availability warning, and a cancelable confirmation; automatic lineups/pitchers/watch lists are active-only.
- Completed and verified `STAT-001`, `STAT-002`, and `STAT-003`: canonical outs parsing, fail-closed missing/malformed/fractional-count handling, and route-specific formatting pass; the regenerated career workbook retains every prior factual value and adds 12 pitching audit columns for 47 players. The source snapshot remains `2026-07-09T14:56:07.992182+00:00`.
- Recorded matching staged/deployed release-source fingerprint `86e5a5f00445199b421fb12743bbb449f12626e49bc056a635753de8f848ee09`. Important limitation: later game identity, lineup, enrichment identity, and refresh-health phases remain planned; this entry does not claim they are complete.
- Deployed 43 changed/new files and the two verified release formats to the live source folder only after creating `_backups\2026-07-19_pre_phase1`. All 43 deployed hashes matched staging; the deployed suite passed 253 tests in 33.65 s; the existing manual-note file remained byte-identical at SHA-256 `2ce8ebdd09b9a5333849f314b7965041785f45da0b08753e452d48bb670671e2`.
- Initialized a local Git repository on `main` and recorded the verified Phase 0–1 package as baseline commit `b008c971d192233484429cbe67f7ccf374e477b9`. The exact staged baseline passed all 253 offline tests in 81.95 s. Git LFS manages 66 PDF/XLSX source artifacts; private notes, lineup/game packets, backups, environments, logs, build products, and distributions remain untracked by explicit ignore rules.
- Reopened `STAT-002` and started `REFRESH-001` / `MEDIA-007` after an independent audit found that season WHIP still used an imported value and that the normal updater/loader could activate unapproved enrichment. No item is complete until the new formula, copy-route, core-refresh, and negative verification-gate regressions pass.
- Completed and reverified `STAT-002`, `MEDIA-007`, and `REFRESH-001` in source commit `b312869`: 2025/2026 season pitching and AUSL career pitching workbooks retain imported `source_whip` while publishing only `(hitsAllowed + baseOnBalls) * 3 / innings_outs`; missing or invalid inputs fail closed. The normal `Quick Refresh (Core)` and default loader neither fetch nor activate optional enrichment, and rows without an explicit passed `needs_review` state cannot reach media, split, or official-game-note output. Failing-first evidence was 12 failures; focused acceptance passed 8 WHIP tests, 188 adjacent regressions, and 12 callback/enrichment tests; the full offline suite passed 265 tests in 12.23 s, `compileall` passed, and `pip check` found no broken requirements. The Windows source-app smoke opened all six tabs, loaded 118 players without a network call, displayed the July 9 freshness warning, and displayed/copied Rachel Garcia's formula-derived `2.15 WHIP`. Recoverable pre-normalization workbooks are under `_backups\2026-07-19_pre_whip_normalization`. Important limitations: the official snapshot remains dated July 9; no live refresh was invoked; experimental enrichment remains developer-only and its deeper identity/classification work is still planned.
- Fast-forwarded the audit-corrected work to `main`, tagged commit `77118e8` as `phase-1-audit-corrected-2026-07-19`, created branch `phase-2-exact-game-lineups`, and started `GAME-001` / `GAME-002`. No lineup migration or validation item is claimed by this entry.
- Completed `GAME-001` and retained `GAME-002` in progress pending exact lineup-store isolation. Failing-first selected-game evidence was 5 failures; the focused model/transaction suite passed 8 tests, including all 76 checked-in authoritative schedule IDs, and the full offline suite passed 273 tests in 13.32 s using `work\pytest-phase2-game-unit-final` because the legacy `.pytest-tmp` directory is inaccessible to the current Windows identity. Manual source-app smoke selected official Game 985, changed to repeat-opponent Game 987, and verified exact ID/time/source/freshness, cleared player and lineup state, Live Game 987 without a fetch, and Producer Prep Game ID 987. No lineup, note, packet, or live data was saved or requested. `LINEUP-001` / `LINEUP-002` now proceed before `GAME-002` can be claimed complete.
- Completed `LINEUP-001` and `LINEUP-002` in source commit `b19f1a0`. Failing-first evidence was 5 failures. The final exact-game/lineup suite passed 17 tests, source compilation passed, and the full offline suite passed 282 tests in 13.20 s using `work\pytest-phase2-lineup-full-reviewed-2`. Legacy matchup-keyed JSON is copied byte-for-byte before atomic migration, retained only under `legacy_unassigned`, and never guessed onto an official game; unreadable stores remain unchanged and block later saves. Manual source-app smoke used an isolated `work` file: Game 985 saved as schema 2/revision 1, switching to the identical OKC-at-CAR Game 987 cleared the editor, and loading Game 987 showed projections rather than Game 985's lock. The real `data/manual/locked_lineups.json` did not exist and was not created or changed. Limitation: there is not yet a dedicated legacy-attachment UI; the visible warning directs the user to re-enter or explicitly import against an official game, while the unassigned payload and backup remain recoverable.
- Completed `LINEUP-003`, `LINEUP-004`, and `LINEUP-005` in source commit `edf4bf2`. Failing-first evidence was 11 missing-validator failures followed by 2 lock-transaction failures. The focused validation, exact-game, lineup-storage, and production-snapshot suite passed 43 tests, source compilation passed, and the full offline suite passed 296 tests in 13.41 s using `work\pytest-phase2-validation-full`. Fixtures cover exact 1–9 order, duplicate order/player, unresolved and ambiguous identity, wrong team, missing starter, invalid position, DP/FLEX separation, inactive/unknown status, missing jersey/position, stale age, and projected source. Manual source-app smoke loaded projections for official Game 985, displayed both projected/not-official warnings, required confirmation, and left no isolated or real lineup-lock file after confirmation was declined. Confirmed warnings are persisted with their timestamp; saved projections remain labeled `NOT OFFICIAL`. Assumption documented in the guide: more than six hours before scheduled first pitch is stale, and incomparable timestamps require confirmation.
- Completed `PACKET-001` in source commit `5b7c362`. Failing-first evidence was 4 identity/path failures plus 1 exclusive-write failure. The exact-game, lineup, and packet-focused suite passed 36 tests, source compilation passed, and the full offline suite passed 301 tests in 13.46 s using `work\pytest-phase2-packet-full`. Packet creation now requires an official selected game, filenames contain a UTC microsecond timestamp, exact game ID, and lineup revision when present, and exclusive creation prevents silent overwrite. Manual source-app smoke generated isolated `20260719T223111615212Z_game_985_producer_packet.txt`; its header contained the matching generated timestamp, Official Game ID 985, schedule source/freshness, and `PROJECTED LINEUPS ONLY — NOT OFFICIAL`. No real lineup lock was created; the smoke packet remained only under ignored `work` test output.
- Completed `SEARCH-001`, `SEARCH-002`, and `SEARCH-003` in source commit `2b97692`. Failing-first evidence was 5 search/scope failures plus 1 stale team-view-on-game-change failure. The focused search, selected-game, and packet suite passed 18 tests, source compilation passed, and the full offline suite passed 306 tests in 13.40 s using `work\pytest-phase2-search-full`. Manual source-app smoke showed an explicit all-player label while the game-scope preference remained checked, returned the same four players for `#22` and `22`, returned reserve-pool players for `reserve`, and showed only the Oklahoma City roster after `Show Away Roster` without mutating the checked preference. Temporary team views now reset during an official game change so labels and visible results cannot describe the previous game.
- Completed `STATE-001`, `GAME-002`, and Milestone 2 at source commit `e8e490b`. Four failing-first refresh tests established that a retained player selection must be rerendered from the replacement database and that missing or duplicate identity must clear the player and clipboard note. The final refresh/adjacent suite passed 79 tests in 0.74 s; the dedicated Phase 2 acceptance suite passed 45 tests in 0.55 s; the full offline regression passed 310 tests in 12.92 s; compilation passed; and `pip check` found no broken requirements. In the offline Windows smoke, Reese Atwood's selected card changed to the fixture marker `[REFRESHED]` after Quick Refresh and the broadcast note was regenerated from the same replacement database. Combined Phase 2 smokes also verified repeat-matchup game isolation, validation/confirmation, exact packet identity, and explicit search scope. No live source, manual note, real lineup lock, or producer packet was written. Remaining limitations are recorded in the Milestone 2 acceptance record; Phase 3 has not started.

### 2026-07-24

- Closed three of the four remaining Phase 5 gaps identified by an independent review of `REFRESH-004`, `REFRESH-005`, `REFRESH-006`, and `HEALTH-001`, plus 11 new tests in `tests/test_refresh_health.py`.
  - `REFRESH-004`/content hash: `content_hash_or_etag` in the source-health manifest was populated but always `None`. It is now a real sha256 fingerprint of each promoted source's content (frame CSV fingerprint for tabular sources; downloaded-bytes hash for PDFs).
  - `REFRESH-005`: `fetch_official_game_notes_frame` now keeps a `.notes_parse_cache.json` sidecar keyed by PDF content hash. An unchanged PDF reuses its cached parsed rows instead of a second `PdfReader` pass; a changed or newly-downloaded PDF is reparsed and the cache entry is replaced.
  - `REFRESH-006`: added bounded retry/backoff (`_fetch_with_retry`, 3 attempts, exponential backoff) to `_get_json`, `_get_text`, and `_download_file` for transient errors (`URLError`, timeouts, `ConnectionError`, HTTP 429/5xx); non-transient HTTP errors (404, etc.) still fail on the first attempt. Left `[ ]` / **IN PROGRESS** because true mid-flight request cancellation is still not implemented.
  - `HEALTH-001`: the UI-side green/yellow/red health strip already existed, but the manifest builder could only ever emit green or red. Added `_previous_source_health` (reads the prior manifest) and `_enrichment_source_health_entry` (carries forward the last successful timestamp for the three optional/enrichment sources and reports yellow while that data is within a 24-hour freshness target, red once it ages out). Deliberately did not extend this to the four core sources: a core-source failure fails the whole refresh closed before any manifest write (`REFRESH-003`), and an existing test (`test_standings_failure_preserves_entire_last_known_good_core_snapshot`) asserts the manifest is byte-identical after a core failure — changing that would contradict a locked acceptance test, so core failures remain hard red/abort by design, not yellow.
  - Test evidence: new focused suite `python3 -m pytest -q tests/test_refresh_health.py` — 11 passed. Full offline suite `python3 -m pytest -q` — 387 passed (376 prior + 11 new), plus the same 3 pre-existing failures and 14 pre-existing errors caused by Git LFS pointer files (not real `.xlsx` bytes) in this sandbox clone, unrelated to this change and unchanged before/after. `python3 -m compileall -q src tests` passed. `pip check` reported the same pre-existing, unrelated `camelot-py`/`pypdf` pin conflict as before this change.
  - Not done in this pass: no Windows/Tkinter smoke test, no git commit, and no deployment to a live folder — this was sandbox-only verification against the offline suite. `REFRESH-006`'s cancellation requirement remains open. The Milestone 4 acceptance record is intentionally left blank pending a real rehearsal and sign-off.

### 2026-07-25

- Closed the remaining `REFRESH-006` gap: true mid-flight cancellation of a running refresh/live job.
  - Mechanism: a `CancelToken`/`RefreshCancelled` pair (`src/ausl_data.py`) — a `threading.Event`-backed, idempotent cancellation signal. `cancel_token` is now an optional kwarg on `_fetch_with_retry`, `_get_json`, `_get_text`, `_download_file`, `fetch_standings_frame`, `fetch_schedule_frame`, `update_all_data`, and `fetch_live_game`. Cancellation is checked before every attempt and, during the retry backoff wait, `Event.wait(delay)` replaces `time.sleep(delay)` so a cancel during backoff returns immediately instead of sleeping out the remaining budget. `update_all_data` re-checks cancellation once more immediately before staging/promoting any file, so a cancelled Quick Refresh can never write or promote a partial result (existing `REFRESH-002` atomic staging is otherwise untouched — once staging starts, it still runs to completion rather than being interrupted mid-write).
  - App layer (`src/ausl_stats_app.py`): `update_data()`/`refresh_live()` now create a `CancelToken` per job. New `cancel_data_update()`/`cancel_live_refresh()` methods cancel the token and free the in-flight flag/button state immediately, without waiting for the abandoned background thread's network call to finish or time out. New "Cancel Refresh" and "Cancel" buttons call these; a game change (`_invalidate_live_context`, already used for `SAFE-002`/`LIVE-001` staleness) and app shutdown (`root.protocol("WM_DELETE_WINDOW", ...)`) also cancel any in-flight job. Each job's success/error/cancelled callback checks token identity (`_data_update_token_is_current`, the pre-existing `_live_request_is_current`) before acting, so a late callback from an abandoned/superseded job is a silent no-op — no crash, no stale-data promotion, no dialog. Repeated cancel calls are no-ops (idempotent).
  - Honest limitation: Python/`urllib` provide no safe way to forcibly abort a single call already blocked inside `urlopen` without touching raw sockets, which this narrowly-scoped change does not attempt (would have meant replacing `urlopen` with a hand-rolled `http.client` connection-capture shim across every call site — out of scope for "narrowest change"). Cancellation is therefore cooperative: it stops further retries/backoff immediately and guarantees the app-visible state (UI, in-flight flag, `app.db`/`app.live_game`) is never left waiting on or contaminated by an abandoned call, but a single already-in-flight attempt may keep running in its daemon thread in the background until it naturally completes or times out, at which point its result is discarded via the token check. This is documented on `CancelToken` itself and in the Milestone 4 acceptance record below.
  - Test evidence (failing-first): `tests/test_refresh_cancellation.py` (13 tests, `ausl_data` layer — cancel before start, cancel while blocked in a real background thread with the retry loop provably not sleeping out its backoff, a success racing cancellation still returning its result so the *caller* decides whether to discard it, `update_all_data` writing nothing when cancelled before start/mid-loop/immediately before staging, and `fetch_live_game` stopping before its second call) and `tests/test_app_refresh_cancellation.py` (15 tests, app layer — cancel with nothing in flight is a no-op, cancel frees UI state immediately, repeated cancel calls, a stale success/error/cancelled callback after cancel is discarded without promoting or opening a dialog, and a game change cancels an in-flight live refresh's token). Focused command: `python -m pytest -q tests/test_refresh_cancellation.py tests/test_app_refresh_cancellation.py` — 28 passed. Existing test doubles for `_get_json`/`_get_text`/`fetch_standings_frame`/`fetch_schedule_frame`/`update_all_data`/`fetch_live_game` across `tests/test_callbacks.py` and elsewhere were updated to accept the new optional `cancel_token` kwarg; no other test file needed changes.
  - Full-suite evidence: `python -m pytest -q` (and again with `-W error`) — 415 passed (387 prior + 28 new), plus the same 3 pre-existing failures and 14 pre-existing errors caused by Git LFS pointer files (`data/exports/*.xlsx` are LFS pointer text, not real spreadsheet bytes, in this sandbox clone) — confirmed present before this change too and unrelated to it. `python -m compileall -q src tests tools` passed. `python -m pip check` reported **no broken requirements** in this sandbox's environment (Python 3.12 venv built from `constraints.txt`); `camelot-py` does not appear in any `requirements*.txt`/`constraints.txt` in this repository, so the camelot-py/pypdf pin conflict noted on 2026-07-24 did not reproduce here — reported as-observed rather than assumed still present; it may be specific to a different (e.g. fuller dev/Windows) environment than this sandbox's clean venv.
  - Smoke test: **not a Windows smoke** — this sandbox is Linux. A real Tkinter smoke ran under `xvfb-run` (Xvfb was available in this sandbox), driving the actual `AUSLStatsApp` class, its real `threading.Thread` worker, the real Tk event loop, and the real `cancel_data_update()`/Cancel-Refresh-button code path, with `update_all_data` stubbed to block until released (simulating a stalled network call; no real network request was made). It confirmed: the UI stays responsive (the Tk event loop keeps pumping) while the job is blocked; cancelling frees the in-flight flag and re-enables the button immediately, before the blocked call returns; `app.db`/freshness text are untouched by the cancel; repeated cancel calls are harmless; and the abandoned thread's late `RefreshCancelled`, once released, is a silent no-op that does not promote or crash. Confirmed reliable across 5 repeated runs. This is real-GUI verification on this platform, not a substitute for the Windows/Tkinter rehearsal the project's smoke tests otherwise run on.
  - Commit: `b30e97472662e2edc751aa8e82a29a5187fd13fc` on branch `claude/refresh-006-mid-flight-cancel-125ykx`. **Push to `origin` failed**: `git push -u origin claude/refresh-006-mid-flight-cancel-125ykx` returned a persistent `403` from this session's local git proxy (`http://127.0.0.1:41729/...`) on four attempts with exponential backoff; the commit exists locally but has not reached the remote as of this entry. This needs a human/session-owner to grant push access or push the branch manually.
  - Scope: only `REFRESH-006` was touched. `SPLIT-001/002/003`, `NOTE-004`, `UI-001/002/003`, `UX-001/002/003`, `SEARCH-004`, and Phase 6/7 items were not started and remain exactly `PLANNED`/`BACKLOG` as before. No redesign was performed; the existing one-job-per-source model, `_fetch_with_retry`'s bounded timeout/retry shape, and REFRESH-002's atomic staging/promotion are unchanged in structure.

### 2026-07-27

- Completed the focused Phase 5 stabilization pass from remote `main`
  `0a52db18cb98e0603e0cc6fd7222a23719e4d5ba` on
  `agent/phase5-stabilization`.
  - Applied the attached future-season patch once; failing-first coverage
    produced 7 expected failures before all 12 year regressions passed. Removed
    the obsolete root patch artifacts after verifying their source changes.
  - Closed the P0 cancelled-refresh race with one serialized core commit
    section and a cancellation check immediately after lock acquisition.
    Deterministic two-worker tests force both orderings and verify that the
    newer refresh owns the final workbooks, manifest, and loaded database.
  - Revalidated game-note PDFs on every deliberate full refresh. Same bytes
    reuse parsed rows; revised bytes parse as a temporary candidate; download,
    invalid-PDF, and parse failure retain the last-known-good PDF/cache. The
    media-guide path now uses the same promote-after-parse rule.
  - Separated snapshot health from `refresh_attempt.json`, with atomic,
    stale-worker-safe persistence for success/failure/cancellation. The
    checked-in snapshot now has usable source health.
  - Repaired deterministic distribution metadata, verified real Git LFS XLSX
    bytes, removed the historical root `portable_source_manifest.json`, and
    generate portable-source manifests only inside release output.
  - Added Python 3.12 Windows/Linux GitHub Actions validation with Git LFS
    checkout, pinned dependency install, `pip check`, `compileall`, the
    warnings-as-errors offline suite, and checked-in distribution verification.
  - Functional commits:
    `4967f5b31280ed67241a2e20385cbd0d4ae5ae4e` and
    `b22ea3a067f8584cd174684e611e98e9fcae275f`.
- Failing-first evidence also exposed one GUI-only stale progress callback:
  the cancelled worker could overwrite the queued replacement's waiting
  message. Two regressions failed before progress callbacks were token-gated.
- Final automated result:
  `.venv\Scripts\python.exe -W error -m pytest -q` —
  **458 passed in 12.19 s**; targeted refresh/PDF/health/build/year suites
  passed; `compileall`, `pip check`, distribution verification, and
  `git diff --check` passed.
- Windows GUI smoke: the self-driving no-network real Tk loop passed on
  `Windows-10-10.0.19045-SP0`. It started a blocked refresh, remained
  responsive, cancelled it, immediately started a replacement, displayed the
  queued/waiting state, resolved both workers, showed no dialog, restored
  button state, loaded the replacement, and matched the in-memory manifest
  timestamp to disk. Computer Use located the window, but Windows Graphics
  Capture failed with `SetIsBorderRequired ... No such interface supported`;
  the repeatable Tk harness was used rather than guessing coordinates.
- Truck-hardware smoke testing and producer rehearsal are recorded as completed
  based on the project owner's report. No unsupplied hardware, scaling, date,
  or behavioral details are asserted.
- Remaining limitations: cancellation does not forcibly abort one `urlopen`
  already inside its bounded timeout; optional enrichment remains
  developer-only and approval-gated; checked-in facts are dated 2026-07-23 and
  require verification before air. Phase 6 has not started.
