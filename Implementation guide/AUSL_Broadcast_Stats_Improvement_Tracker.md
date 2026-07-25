# AUSL Broadcast Stats — Improvement Tracker

Last updated: 2026-07-25
Project source reviewed: `AUSL_BROADCAST_STATS_project_backup_2026-07-18_223756.zip`  
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

### Milestone 4 — Resilient refresh and producer UX (Phase 5 slice)

Target outcome for the current phase: make background refresh/live work
deterministic and recoverable (bounded timeouts, retry/backoff, real
cancellation, per-source health, deterministic cleanup) before starting
Phase 6's producer-speed UX work.

Current implementation unit: `REFRESH-006` (mid-flight cancellation). With
this pass, all of `REFRESH-001` through `REFRESH-006` and `HEALTH-001`/
`HEALTH-002` are `[x]` COMPLETE — the Phase 5 refresh-resilience slice of
Milestone 4 is code-complete. Phase 6's producer-speed items (`UX-001`
through `UX-005`) remain `PLANNED`/`BACKLOG` and have not been started.

The master list below is the single source of task status. No item is
complete until its tests and stated acceptance behavior pass.

Status: **CODE-COMPLETE — PHASE 5 REFRESH RESILIENCE (MILESTONE 4 SLICE) — 2026-07-25 — NOT YET PRODUCER-SIGNED-OFF (Gate C pending a human rehearsal)**

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

- [ ] `SPLIT-001` — Exclude `regularSeason` aggregate rows from the best situational-split list. **P1 · PLANNED**

- [ ] `SPLIT-002` — Establish configurable sample thresholds and reliability labels. **P1 · PLANNED**
  - Initial review target: hitter at least 10–12 PA; pitcher at least 3 IP or a batters-faced threshold.
  - Always show sample size.

- [ ] `SPLIT-003` — Keep small samples available in detail without promoting them as top storylines. **P2 · PLANNED**

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

- [ ] `SEARCH-004` — Add optional quick filters. **P2 · BACKLOG**
  - Candidate syntax: `team:CHI`, `pos:P`, `status:inactive`, `#22`.

- [x] `STATE-001` — Rerender or clear the selected player card after data refresh. **P0 · COMPLETE**
  - Clipboard text and `current_broadcast_note` must use the same database version as the visible card.

- [ ] `UI-001` — Add visible scrollbars to long content panels. **P2 · PLANNED**

- [ ] `UI-002` — Verify minimum window size and Windows scaling at 100%, 125%, and 150%. **P1 · PLANNED**

- [ ] `UI-003` — Add keyboard navigation for search and primary game workflow. **P2 · BACKLOG**

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

- [x] `REFRESH-003` — Preserve last-known-good data after optional-source failure. **P0 · COMPLETE**
  - A failed optional source must not replace a valid workbook with an empty one.

- [x] `REFRESH-004` — Add a per-source health manifest. **P1 · COMPLETE**
  - Track attempt/success time, row count, content hash/ETag, status, error, fallback, and parser version.

- [x] `REFRESH-005` — Cache and incrementally process unchanged PDFs. **P1 · COMPLETE**
  - Official game-note PDFs are hashed after download; an unchanged hash reuses its cached parsed rows instead of a second `PdfReader` pass.

- [x] `REFRESH-006` — Add bounded timeouts, retry/backoff, cancellation, and deterministic cleanup. **P1 · COMPLETE**
  - Bounded timeouts and deterministic single-flight cleanup were already in place (`SAFE-002`/`LIVE-001`). Bounded retry/backoff on transient network failures was added in the 2026-07-24 pass. This pass closes the remaining gap: real mid-flight cancellation. A `CancelToken`/`RefreshCancelled` pair in `ausl_data.py` is threaded through `_fetch_with_retry`, `_get_json`, `_get_text`, `_download_file`, `fetch_standings_frame`, `fetch_schedule_frame`, `update_all_data`, and `fetch_live_game`; cancellation is checked before every attempt and during the retry backoff wait (`Event.wait` instead of `time.sleep`), so a cancelled job stops retrying immediately instead of working through its full timeout/retry budget, and `update_all_data` re-checks cancellation once more immediately before staging/promotion so a cancelled Quick Refresh can never write or promote a partial result. In `ausl_stats_app.py`, `cancel_data_update()`/`cancel_live_refresh()` (wired to new Cancel buttons, a game change, and app shutdown) give each job a token/token-identity check so a late success/error/cancelled callback from an abandoned background thread is a safe no-op rather than a promotion or a crash. Python/`urllib` offer no safe way to force-abort a call already inside `urlopen`; this is a cooperative design (documented in `CancelToken`'s docstring) rather than a raw socket-level abort — see the change-log entry below for what that means in practice.

- [x] `HEALTH-001` — Add visible per-source freshness and green/yellow/red health. **P1 · COMPLETE**
  - The color/marker/text health strip already existed in the UI, but the data layer could only ever emit green or red — yellow was unreachable. The manifest builder now carries forward the previous successful timestamp for each optional/enrichment source and reports yellow ("usable last-known-good, aging") while that data is within a 24-hour freshness target, and red once it ages out or nothing has ever been promoted. This carry-forward is scoped to the three optional/enrichment sources; a core-source failure still fails the whole refresh closed before any manifest is written (`REFRESH-003`), so yellow is not reachable there by design.

- [x] `HEALTH-002` — Display live feed `lastUpdated`, connection state, and staleness. **P0 · COMPLETE**

### L. Producer-speed improvements

- [ ] `UX-001` — Add a compact selected-game dashboard. **P2 · PLANNED**
  - Teams/records, game time/venue/status, data health, lineup state/age, live state, and verification count.

- [ ] `UX-002` — Add air-ready fact cards with concise copy, context, source, freshness, and verification state. **P2 · PLANNED**

- [ ] `UX-003` — Add a local pinned-facts/rundown queue with plain-text export. **P2 · BACKLOG**

- [ ] `UX-004` — Add a post-refresh `What changed?` panel. **P2 · BACKLOG**
  - Roster/status, records, lineups, starters, injuries, milestones, and invalidated facts.

- [ ] `UX-005` — Preserve source/freshness metadata when copying or pinning a fact. **P1 · PLANNED**

### M. College Résumé tab

The college layer must remain visually and statistically separate from AUSL professional totals.

- [ ] `COLLEGE-001` — Write the normalized college-data specification before importing data. **P1 · BACKLOG**
  - Support multiple schools, seasons, transfers, shortened seasons, extra eligibility, and two-way players.

- [ ] `COLLEGE-002` — Add a separate `College Résumé` tab or player-card section. **P2 · BACKLOG**
  - Proposed sections: Snapshot, Career Totals, Season-by-Season, Honors/Records, and Broadcast Connections.

- [ ] `COLLEGE-003` — Build a verified core résumé from official AUSL player profiles. **P2 · BACKLOG**
  - School(s), seasons, career batting/pitching totals, final season, championships/WCWS, awards, and records.

- [ ] `COLLEGE-004` — Add source hierarchy and field-level provenance. **P1 · BACKLOG**
  - Preferred order: official AUSL profile, NCAA statistics, official school athletics site, manually verified entry.

- [ ] `COLLEGE-005` — Add `Verified`, `Partial`, and `Needs review` completeness states. **P1 · BACKLOG**
  - Missing information remains unavailable and is never converted to zero.

- [ ] `COLLEGE-006` — Pilot the résumé with ten varied players before full-roster import. **P2 · BACKLOG**
  - Include rookies, veterans, transfers, pitchers, and two-way players.

- [ ] `COLLEGE-007` — Add college-based broadcast connections and storylines after producer review. **P2 · BACKLOG**
  - Former teammates, conference rivals, champions, homecomings, coaches, and role changes.

- [ ] `COLLEGE-008` — Consider complete season-by-season college statistics only after the pilot proves useful. **P3 · BACKLOG**

College display rule example:

```text
2026 AUSL: .286 AVG, 4 HR, 13 RBI
COLLEGE CAREER — Oklahoma: .376 AVG, 54 HR, 301 H
```

College and AUSL numbers must never be combined into one unlabeled career total.

### N. Longer-term ideas

- [ ] `FUTURE-001` — Live milestone watch that updates pregame thresholds from the live box score. **P3 · BACKLOG**

- [ ] `FUTURE-002` — Verification desk for stale, ambiguous, conflicting, or needs-review facts. **P2 · BACKLOG**

- [ ] `FUTURE-003` — Standings, seeding, clinching, or elimination scenarios from versioned official rules. **P3 · BACKLOG**

- [ ] `FUTURE-004` — Export/import a game package containing selected game, lineups, pinned facts, and scoped notes. **P3 · BACKLOG**

- [ ] `FUTURE-005` — Review-only feed for official AUSL/team announcements and transactions. **P3 · BACKLOG**

- [ ] `FUTURE-006` — Shared multi-user workflow only after ownership, authentication, conflict handling, and offline behavior are designed. **P3 · BACKLOG**

## Acceptance records

Fill in one record when a milestone or major item is completed.

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

- Completion date: 2026-07-25 (`REFRESH-006` only; Milestone 4 covers only `REFRESH-004` through `REFRESH-006`, `HEALTH-001`/`HEALTH-002`, and Phase 6's producer-speed items, so this record reflects the Phase 5 refresh-resilience slice of Milestone 4, not the still-`PLANNED`/`BACKLOG` Phase 6 UX items.)
- Source version/commit: `b30e97472662e2edc751aa8e82a29a5187fd13fc` on branch `claude/refresh-006-mid-flight-cancel-125ykx`, following the 2026-07-24 `REFRESH-004`/`REFRESH-005`/`HEALTH-001` pass.
- Automated test command and result: focused suites `python -m pytest -q tests/test_refresh_cancellation.py tests/test_app_refresh_cancellation.py` — 28 passed (13 `ausl_data` cancellation-primitive/`update_all_data`/`fetch_live_game` tests, 15 app-layer `cancel_data_update`/`cancel_live_refresh` tests). Full offline suite `python -m pytest -q` (and again with `-W error`) — 415 passed, plus the same 3 pre-existing failures and 14 pre-existing errors caused by Git LFS pointer files (not real `.xlsx` bytes) in this sandbox clone, confirmed unrelated to this change and unchanged before/after (see the change-log entry below). `python -m compileall -q src tests tools` passed. `pip check` reported no broken requirements in this sandbox's environment (see the change-log entry for the camelot-py/pypdf note).
- Refresh failure/staleness checks: covered by the existing `REFRESH-002`/`REFRESH-003`/`HEALTH-001` tests (unchanged by this pass) plus the new cancellation tests, which specifically assert that a cancelled `update_all_data` call writes nothing to the export directory (checkpoints before the roster/stats loop, mid-loop, and immediately before staging) and that a cancelled/superseded live or Quick Refresh callback never promotes into `app.db`/`app.live_game`.
- Rehearsal result: a real Tkinter smoke ran under Xvfb on this Linux sandbox (not a Windows machine) — see the change-log entry for exactly what it exercised. No producer rehearsal has occurred; this is code-complete verification only.
- Known limitations remaining: cancellation is cooperative, not a raw socket abort — an already-in-flight single `urlopen` call cannot be forcibly killed by Python/`urllib`, so if a job is cancelled while genuinely blocked on the network (not merely between retries), the app's UI and in-flight state free up immediately, but the abandoned OS-level request may continue running in its daemon thread until it naturally completes or times out before being discarded; this is documented on `CancelToken`. `REFRESH-004`/`REFRESH-005`/`HEALTH-001` limitations from 2026-07-24 are unchanged. Phase 6 producer-speed items (`UX-001` through `UX-005`) remain `PLANNED`/`BACKLOG` and are not part of this record. No producer acceptance rehearsal has occurred; Gate C is not met.
- Verified by: Codex failing-first offline tests (`ausl_data`-layer and app-layer), full regression/compile/dependency gates, and a no-network Linux/Xvfb Tkinter smoke; not yet producer-signed-off.

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
- 2026-07-24 — Add read-time budgeting to fact cards and the pinned rundown: estimate seconds-to-read from word count (~140 wpm) and show a running total against a settable break-length target, so a producer can tell at a glance whether a fact fits the current window. Extends `UX-002`/`UX-003`.
- 2026-07-24 — Let a producer mark a suggested fact "used on air" with a timestamp. A used fact drops out of default Top Storylines/suggestion surfaces for the remainder of the selected game but stays visible and selectable in the detailed view. Extends `UX-003`.
- 2026-07-24 — Add session/crash recovery for producer working state (selected game, pinned/used-fact queue, scroll position) separate from lineup-lock and manual-note storage, which are already atomic-written. This protects in-progress broadcast prep from an unexpected restart; it is distinct from Phase 5's data-refresh resilience, which protects source data, not UI session state.
- 2026-07-24 — Add a single "Ready for Air" readiness indicator that rolls up data health, lineup-lock state, and outstanding verification count into one glanceable state, plus a short pregame checklist (rosters confirmed, lineups locked, packet generated, live feed connected). Extends `6A`/dashboard work.
- 2026-07-24 — Add fuzzy/typo-tolerant matching (edit-distance or phonetic) to player-name search so a misspelled or mistyped name under time pressure still returns the right player. A tolerance improvement to `SEARCH-004`, not a new search mode.
- 2026-07-24 — Add a quiet character-count preview on copy actions against one or two common graphics-template widths, so a producer can see before handoff whether air-ready text fits a lower-third/CG line limit. Extends `UX-002`. Does not imply or require an actual CG/graphics-system integration.
- 2026-07-24 — Add an explicit Local/Offline Mode toggle that guarantees no refresh attempt or network-related UI notification will fire while enabled, for use during specific live windows (e.g., final two minutes before first pitch, an active half-inning). Complements Phase 5's failure-safe refresh with an explicit producer-controlled guarantee rather than relying on failure behavior alone.
- 2026-07-24 — Add a side-by-side compare view: two selected players' stat lines, verified notes, and milestones shown in parallel columns, for probable-starter or hitter-vs-pitcher "tale of the tape" segments. A new screen, not a variant of the existing player card.

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
