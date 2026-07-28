# AUSL Broadcast Stats — Codex Implementation Guide

Version: 1.0  
Prepared from: `AUSL_BROADCAST_STATS_project_backup_2026-07-18_223756.zip`  
Primary files: `src/ausl_stats_app.py`, `src/ausl_data.py`

## 1. Purpose

This guide turns the source audit into an implementation sequence for Codex. The goal is not a broad rewrite. The goal is to make the current Windows/Tkinter application dependable enough for live television: fast to navigate, explicit when data is stale or uncertain, and resistant to producing plausible-but-wrong information for air.

The producer's two primary jobs should remain central:

1. Recover an accurate player, team, matchup, or game fact in seconds.
2. Surface trustworthy storylines that a producer can verify and use on air.

The core operating rule is:

> Wrong-on-air is worse than unavailable. If the application is uncertain, it must say so.

## 2. Copy-paste starter prompt for Codex

Use this at the start of an implementation session:

```text
Work from the current AUSL Broadcast Stats source package. Read this implementation guide completely before editing.

Implement the phases in order. Do not perform a sweeping rewrite, rename unrelated APIs, or replace the existing Tkinter application. Preserve existing user data and working features. Begin by adding a small pytest baseline and fixtures for every behavior you are about to change. Make changes in reviewable units, run the relevant tests after each unit, and report the exact tests and manual checks performed.

Treat official standings and game identifiers as authoritative. Never silently turn missing or uncertain data into zero, "active," a player match, or an on-air fact. Add visible provenance, freshness, and verification labels where appropriate. An unavailable fact is acceptable; a confidently displayed wrong fact is not.

Do not bundle a producer's manual notes or lineup locks into a distributable build by default. Do not run destructive migrations without making a recoverable backup. Do not make tests depend on the live internet.

At the end of each phase:
- run the phase tests and full regression suite;
- perform the listed manual smoke checks;
- summarize changed files and behavior;
- list any remaining risks or assumptions;
- stop if the acceptance criteria are not met.
```

## 3. Non-negotiable engineering rules

- Keep the existing user experience recognizable. Improve it incrementally.
- Put data decisions in testable helper functions rather than inside Tkinter callbacks.
- Keep all Tkinter widget mutation on the main thread. Worker threads may fetch and parse data, then return immutable results through a queue or `after()` callback.
- Use exact official game IDs wherever state belongs to a game.
- Prefer official team-level data for team-level facts. Player-stat sums are calculated aggregates, not official records.
- Preserve the last-known-good dataset if a refresh source fails validation.
- Treat missing roster status as `Status unknown`, never `Active`.
- Require exact identity matches for player-specific notes and media-guide material.
- Attach source, effective date, and freshness to facts intended for air.
- Store user-authored files atomically and back them up before schema migration.
- Keep live-network checks optional; default automated tests must be deterministic and offline.

## 4. Target data authority model

Codex should establish these source-of-truth rules before changing presentation logic.

| Fact | Authoritative source | Permitted fallback | Display rule |
|---|---|---|---|
| Team W-L, runs for/against, differential, streak, GB | Official standings/schedule | Last-known-good official snapshot | Show freshness; never derive W-L from pitcher decisions |
| Game identity, date, teams, venue, status | Official schedule/game metadata | User-created game only when explicitly labeled | Key state by `game_id` |
| Player roster/team/status | Current roster source | Last-known-good roster | Missing status becomes `Status unknown` |
| Player statistics | Official stats feed/export | Last-known-good stats | Distinguish missing from zero |
| Live game facts | Live box score | None | Show last update and stale state |
| Media-guide biography | Exact TOC player/page mapping | None | Unmatched player is explicitly not included |
| Official game note | Official PDF plus parsed source location | None | Show verification/source metadata |
| Producer note | Manual-note store | None | Scope explicitly to player/team/game |
| Projected lineup | Validated lineup lock or active-roster projection | None | Clearly distinguish locked from projected |

## 5. Recommended implementation sequence

### Phase 0 — Baseline, fixtures, and safety rails

Objective: make later correctness work measurable without changing user-visible behavior.

#### Work

1. Add `pytest` and a `tests/` directory.
2. Create small, hand-auditable fixtures rather than copying the entire production dataset:
   - roster with active, inactive, reserve-pool, and unknown-status players;
   - batting and pitching rows, including nulls and baseball innings notation;
   - standings and schedule rows with official game IDs;
   - manual notes with player, team-wide, and game scopes;
   - lineup text with valid and invalid examples;
   - media-guide TOC text and page text;
   - official game-note snippets;
   - a representative live-box-score response.
3. Add characterization tests for existing loaders and pure formatting helpers.
4. Move no UI behavior merely for test convenience. Extract only the smallest pure helper needed.
5. Add a temporary audit command or test that enumerates every rostered player and every copy type without invoking the clipboard.
6. Pin runtime and build dependencies. Replace unconditional "upgrade to latest" behavior in build scripts with reproducible installation from pinned requirements or a lock file.
7. Add structured application logging to a user-writable log directory. Log source refresh start/end, row counts, exceptions, fallback use, and validation failures; do not log note contents unnecessarily.

#### Initial test files

Suggested organization:

```text
tests/
  conftest.py
  fixtures/
  test_formatting.py
  test_manual_notes.py
  test_lineups.py
  test_team_snapshots.py
  test_media_guide.py
  test_game_notes.py
  test_copy_text.py
  test_status_filtering.py
  test_refresh_staging.py
  test_live_parser.py
```

#### Acceptance criteria

- The source compiles and the current app starts.
- Tests run offline with one documented command.
- Fixture failures produce useful, local diagnostics.
- No distributable build contains local manual notes, lineup locks, logs, or cached credentials by default.
- A clean build can be reproduced without silently taking new dependency versions.

---

### Phase 1 — On-air correctness blockers

Objective: eliminate known crashes and misleading facts before adding features.

#### 1A. Fix delayed exception callbacks

Locations in `ausl_stats_app.py`:

- `_load_initial`
- `update_data`
- `refresh_live`

The exception object captured by `except Exception as exc` is cleared when the `except` block exits. A later Tk callback that closes over `exc` can therefore fail instead of reporting the original error.

Replace closures such as `lambda: ... exc ...` with either:

```python
root.after(0, lambda exc=exc: handle_error(exc))
```

or, preferably, pass a serializable result object through a thread-safe queue to one main-thread result handler.

Also:

- disable the relevant update button while work is in flight;
- restore it on success, error, and cancellation;
- guarantee a terminal status message;
- prevent concurrent refreshes of the same source.

#### 1B. Correct manual-note scoping

Locations:

- `save_manual_note`
- `_manual_note_lines`

Current fallback behavior can show one player's note on a teammate's card. Migrate the note schema to include explicit fields:

```text
note_id
scope              # player | team | game | global
player_id          # required only for player scope
team_code          # required for team scope; optional context elsewhere
game_id            # required for game scope
text
created_at
updated_at
author              # optional
source              # manual
```

Retrieval rules:

- player card: that exact `player_id`, plus explicitly team-wide notes for the player's team, plus applicable game notes;
- team view: explicitly team-scoped notes only, unless the interface intentionally expands player notes;
- never fall back from a missing player match to every note for that team.

The editor must use a searchable exact player picker and team dropdown. If typed input matches multiple players, block the save and require a selection. Back up the existing CSV before migration and write changes atomically. Add edit and delete actions after correctness is established.

#### 1C. Centralize official team snapshots

Locations:

- `render_team_totals`
- `_team_metrics`
- `_packet_team_snapshot`
- `_standings_row`

Create one pure helper, for example:

```python
official_team_snapshot(team_code, season, database) -> TeamSnapshot
```

It should return official W-L, runs for, runs against, differential, streak, games back, source timestamp, and availability flags. All team panels and generated packets must consume the same object.

Never calculate team W-L by summing pitcher wins and losses. If official team data is absent, display `Record unavailable` and retain separately labeled calculated player aggregates where useful.

Regression values observed during the audit prove why this is urgent: reconstructed records disagreed with official standings for Chicago, Carolina, Oklahoma City, Portland, and Utah. The same packet could show two different records for one team.

#### 1D. Make roster and copy output status-safe

Locations:

- `ausl_data.py`: `roster_frame`
- `ausl_stats_app.py`: `gfx_text`, `copy_gfx`

Requirements:

- missing status becomes `Status unknown`;
- missing team is formatted safely and never receives `.upper()` directly;
- reserve-pool players display `RESERVE POOL` or `RAP`, not `nan`;
- inactive, reserve, and unknown-status players receive a visible warning before on-air copy is placed on the clipboard;
- a user may explicitly confirm an override, but the application must not silently treat the player as active.

Clarify copy semantics:

- `Player ID`: name, team/status, position, number if known;
- `Season stat`: current season, explicitly labeled;
- `Career stat`: explicitly labeled `AUSL CAREER 2025–26` or the actual season span;
- `Announcer note`: sourced narrative with verification metadata.

#### 1E. Correct baseball innings and numeric formatting

Locations:

- `pitching_line`
- `decimal`
- `_innings_to_outs`
- `ausl_data.py`: `_ip_to_outs`, `career_pitching`

Create one canonical innings parser. In baseball notation, `31.2` means 31 innings and two outs, not 31.2 decimal innings. Derive WHIP using outs:

```text
innings = outs / 3
WHIP = (H + BB) / innings
```

For season and split pitching, treat `hitsAllowed`, `baseOnBalls`, and canonical
innings outs as the source inputs. Preserve the imported metric as
`source_whip`, publish only the derived `whip`, and fail closed when any input is
missing, malformed, negative, or represents zero outs. Never use `source_whip`
as a fallback for an on-air value. Apply the same policy in workbook exports,
loader normalization, UI lines, and clipboard copy routes.

Keep separate formatters:

- rate formatter for AVG/OBP/SLG/OPS: `.392`;
- decimal formatter for ERA/WHIP: `0.88`, `1.00`.

Do not convert a null or malformed value to `0`. Return an unavailable sentinel and render `—` or `N/A`.

#### 1F. Exclude unavailable players from recommendations

Locations:

- `_projected_lineup`
- `_projected_pitchers`
- `_players_to_watch`

Default recommendations must contain active-roster players only. Put inactive/reserve/unknown players in a separate `Availability impact` section with their status and source freshness. Manual inclusion requires an explicit override.

#### 1G. Limit the first milestone distribution to tested core snapshots

First-milestone distributable builds contain only `ausl_rosters.xlsx`, `ausl_season_stats.xlsx`, `ausl_career_stats.xlsx`, `ausl_team_context.xlsx`, `update_manifest.json`, and a generated `distribution_manifest.json`. The default updater and loader must also remain core-only: media-guide, official-game-note, split-stat, and storyline enrichment may exist in the source package for isolated development, but normal refresh/startup must neither activate nor rewrite it until its later validation gates pass.

The generated distribution manifest must record source snapshot freshness and, for each core workbook, its SHA-256 digest, byte count, and validation state. This milestone restriction does not claim that the later enrichment-validation phases are complete.

#### Phase 1 acceptance criteria

- Every packet view displays the exact same official W-L for a team.
- No player sees another player's private/manual note.
- A team-wide note appears for every appropriate team player.
- All roster players can generate each copy type without an exception.
- Reserve, inactive, and unknown-status output is unmistakably labeled.
- Innings tests pass for `0.1`, `0.2`, `1.2`, `31.2`, null, and malformed input.
- Missing values do not render as factual zeroes.
- A failed initial load, data update, or live refresh produces the original useful error and leaves the UI usable.
- Projected lineups, pitchers, and watch lists exclude nonactive players by default.
- The first-milestone `data/exports` payload contains exactly the tested core snapshot allowlist and generated distribution manifest; later enrichment exports are absent.

---

### Phase 2 — Exact game identity, lineup validation, and synchronized UI state

Objective: make the application game-centric and prevent stale information from crossing matchups.

#### 2A. Introduce a selected-game model

The Game Setup area should select an official scheduled game, not merely two team abbreviations. A selected game should include:

```text
game_id
season
date_time
away_team
home_team
venue
status
source_updated_at
```

Allow a clearly labeled custom game only when an official game is unavailable.

Add a single handler such as `on_game_changed(selected_game)` that updates, in one transaction:

- team variables and matchup header;
- player search scope and result list;
- selected player/card, clearing it when no longer applicable;
- lineup editor and lock status;
- producer-prep panel;
- manual game notes;
- live game ID and live panel;
- packet filename/context.

Do not let individual widget callbacks independently mutate partial game state.

#### 2B. Key lineup locks by `game_id`

Locations:

- `lineup_key`
- `current_locked_lineups`
- `load_projected_lineups_into_editor`
- `lock_lineups_from_editor`

The current key based only on `AWAY_at_HOME` collides when teams meet again. Persist locks by exact game ID and include:

```text
game_id
date_time
away_team
home_team
venue
locked_at
source             # manual | imported | projected
revision
lineups
```

Back up and migrate old matchup-only locks. Because an old key may correspond to several games, do not guess. Mark it `legacy_unassigned` and ask the user to attach it to a game.

#### 2C. Validate before locking

Locations:

- `parse_lineup_text`
- `lock_lineups_from_editor`

Return a structured validation result with `errors`, `warnings`, and normalized lineup data.

Blocking errors:

- batting orders are not exactly 1 through 9;
- duplicate batting order;
- duplicate player;
- unresolved or ambiguous player;
- player is assigned to the wrong team;
- missing required starter;
- invalid defensive-position syntax;
- malformed DP/FLEX relationship.

Warnings requiring confirmation:

- inactive, reserve, or unknown-status player;
- player missing a jersey number or position;
- lineup is old relative to game time;
- projected rather than officially confirmed source.

Implementation decision (2026-07-19): treat a lineup source timestamp more
than six hours before scheduled first pitch as stale. If timestamp awareness or
offsets cannot be compared safely, warn and require confirmation instead of
assuming the lineup is fresh. Confirmation does not promote a projected source
to official; persist the original source and the warning-confirmation time.

DP/FLEX must be modeled separately from the nine batting positions. Do not count an additional FLEX entry as a tenth hitter.

Show validation inline next to the affected line. Do not display `Locked` when blocking errors exist.

#### 2D. Repair search and selection state

Locations:

- `show_all`
- `show_team`
- `search`
- `_finish_load`

Requirements:

- `All Players` truly searches all players even when game scope is enabled;
- selecting one team does not silently disable a separate game-scope preference;
- jersey search accepts both `22` and `#22`;
- search includes roster status, including `reserve` and `inactive`;
- data refresh rerenders the selected player card from the new database or clears it if the player no longer exists;
- `current_broadcast_note` and all clipboard output are regenerated after refresh;
- changing a game clears or reloads lineup and player state atomically.

#### Phase 2 acceptance criteria

- Two games with identical home/away orientation have isolated lineup locks.
- Changing the selected game cannot save the old editor contents under the new game without an explicit import/confirmation.
- Duplicate, unresolved, inactive, wrong-team, and malformed DP/FLEX fixtures behave as specified.
- Search scope and labels always agree with the visible results.
- Refreshing data cannot leave a stale player card or stale clipboard note visible.
- Generated packet filenames include game ID and a timestamp or revision, preventing silent overwrite.

---

### Phase 3 — Trustworthy media-guide extraction

Objective: remove false biography matches and extract complete, source-verifiable player material.

Locations in `ausl_data.py`:

- `_clean_media_guide_text`
- `fetch_media_guide_frames`

Location in `ausl_stats_app.py`:

- `_media_guide_player_lines`
- `_media_guide_team_lines`

#### Replace mention-based matching with TOC mapping

The present parser searches every PDF page for a player's name and favors a high-scoring/later mention. That can attach a page about one player to another player merely mentioned in the biography. The audit found 24 nonempty biographies mapped to the wrong player and 10 empty player entries.

Implement this pipeline:

1. Parse the media guide table of contents.
2. Normalize each exact TOC player name and its printed page or page range.
3. Calculate and verify the PDF-page offset. Do not hard-code the observed `+2` offset without a validation check.
4. Map roster players only by normalized exact identity, with a small explicit alias table for known name changes.
5. Merge every page in the player's TOC range.
6. Validate that the expected player's name/header occurs in the mapped range.
7. Record match status, confidence, expected pages, parsed PDF pages, guide date, and extraction warnings.
8. If the player is absent from the TOC, store `not_in_guide`; never guess from a mention elsewhere.

Repair wrapped hyphenation before collapsing whitespace so strings such as `remain- der` are reconstructed. Normalize broken year tokens without changing legitimate hyphenated names.

Deduplicate semantically identical notes across `bio`, `2025_AUSL`, `college`, and other categories. Retain the most specific category and its source location.

Create a media audit table/export containing:

```text
player_id
player_name
match_status
expected_printed_pages
parsed_pdf_pages
confidence
note_count
warnings
guide_date
```

Only `verified` notes may enter air-ready copy automatically. `needs_review` can be browsed but must carry a visible warning. `not_in_guide` should display `Not included in the June 1 media guide` (with the actual guide date if it changes).

#### Required regression fixtures

- Sydney Romero must not receive Elise Sokolsky's biography.
- Morgan Zerkle must not receive Sydney Romero's page.
- Rachel Garcia must not receive Mariah Mazon's page.
- A newcomer absent from the TOC receives no inferred biography.
- A two-page player receives both pages in the correct order.
- Duplicate category material is shown once.

#### Phase 3 acceptance criteria

- Every TOC-listed roster player maps to the expected page range in the audit report.
- No absent player receives a guessed page.
- No wrong-player biography is eligible for air-ready copy.
- Multi-page sections are complete and source-labeled.
- Parser validation failures preserve the prior verified media dataset instead of replacing it with empty output.

---

### Phase 4 — Useful official notes and nonduplicative producer prep

Objective: turn a large PDF-derived note store into a small, relevant, balanced, and verifiable game rundown.

Locations in `ausl_data.py`:

- `_game_note_category`
- `_split_game_note_items`
- `fetch_official_game_notes_frame`

Locations in `ausl_stats_app.py`:

- `_official_game_note_lines`
- `_producer_prep_lines`
- `generate_pregame_report`

#### 4A. Replace keyword-only categories

Current generic keywords overclassify notes: any use of `career` can become a milestone, `series` can turn a college-history sentence into a matchup note, and retrospective starting-pitcher text can become a probable starter.

Use explicit categories with conservative rules:

| Category | Qualification |
|---|---|
| `availability` | injury, illness, inactive status, transaction, roster change |
| `milestone_watch` | explicit needs/within-X/approaching/record threshold |
| `milestone_reached` | explicit first, reached, broke, tied, set record |
| `probable_starter` | explicitly scheduled, announced, or probable for the selected game |
| `matchup_history` | both opponents, head-to-head, rematch, or exact game-series context |
| `recent_trend` | explicit streak, last-N sample, or since-date window |
| `season_context` | current-season summary |
| `career_summary` | general career material that is not a milestone |
| `background` | noncompetitive biography/context |

Store subject player/team, opposing team where applicable, effective/source date, source game/PDF/page, parser version, normalized hash, and verification state.

Deduplicate repeated notes across PDFs with a normalized content hash. Prefer the newest verified instance while retaining source history for audit.

#### 4B. Select notes for the exact game

Build selection as structured data, not preformatted strings. Selection priorities:

1. confirmed availability/transaction information;
2. exact-game probable starters;
3. milestones reached or genuinely within range;
4. exact-opponent history;
5. recent, adequately sampled trends;
6. season/career context.

Balance the two teams and limit repeated categories. Do not allow all five default notes to come from one team unless the interface explicitly says the other side has no verified candidates.

Every note intended for air should expose:

- subject and team;
- `[VERIFIED]`, `[VERIFY]`, or `[STALE]` state;
- source date;
- source game/PDF/page;
- relevant sample size or time window.

#### 4C. Refactor producer prep into sections

`_producer_prep_lines` should return a sectioned model rather than a flat list of strings, for example:

```python
ProducerPrep(
    game_context=...,
    availability=...,
    top_storylines=...,
    offense=...,
    pitching=...,
    matchup_history=...,
    milestones=...,
    verification_queue=...,
)
```

Render the UI and packet from this same model. The packet's `TOP STORYLINES` section must select actual storyline objects, not the first four bullet strings from the complete prep output. Each fact should appear once unless a deliberate summary links to its detailed section.

#### Phase 4 acceptance criteria

- A generic `career` sentence is not labeled a milestone.
- `Women's College World Series` alone does not create an AUSL matchup-history note.
- A retrospective `starting pitchers` sentence is not a probable starter.
- Confirmed injury/transaction notes appear before lower-value context.
- Default results include both teams when verified material exists for both.
- Duplicate PDFs do not yield duplicate on-screen notes.
- `TOP STORYLINES` is not a copy of the first official-note bullets.
- Every air-ready note has source and freshness metadata.

---

### Phase 5 — Refresh architecture, resilience, and data health

Objective: keep the app responsive and useful when a source is slow, malformed, or unavailable.

Locations:

- `ausl_data.py`: `update_all_data`, `_write_excel_atomic`, `load_database`, source fetchers
- `ausl_stats_app.py`: `update_data`, `refresh_live`, `_schedule_live`, `_auto_refresh`, `_finish_live`, `_finish_load`

#### 5A. Split refresh modes

Keep the producer-facing action core-only:

- **Quick Refresh (Core)** — roster, player statistics, standings, schedule, and live metadata.
- **Experimental enrichment refresh** — media guide, split statistics, and historical/official game-note PDFs. This remains an explicit developer-only option until source identity, provenance, freshness, and review gates pass; it must not be exposed as the normal producer refresh.

The default database loader must ignore optional enrichment workbooks. Any
experimental row with a missing or affirmative `needs_review` state must be
excluded from air-ready media, split, official-note, prep, and copy output.

The audit's full isolated refresh took roughly three minutes even with most historical PDFs cached. A producer needs a predictable fast path before and during a show.

#### 5B. Stage, validate, then promote

For each source:

1. fetch into a versioned temporary location;
2. parse without touching the active cache;
3. validate schema, row count, unique keys, season, and expected value ranges;
4. write atomically;
5. promote only after validation;
6. otherwise retain last-known-good data and record the error.

An optional-source failure must not overwrite a valid workbook with an empty one.

Maintain a manifest with:

```text
source_name
source_url_or_id
season
last_attempt_at
last_success_at
row_count
content_hash_or_etag
status
error_summary
used_fallback
parser_version
```

Cache PDFs by content hash/ETag and process only new or changed files.

#### 5C. Show source health

Add a compact data-health strip or dialog with green/yellow/red state:

- green: current and validated;
- yellow: usable last-known-good data outside freshness target;
- red: unavailable, invalid, or too stale for air.

Show per-source age, not only a single application timestamp. Live data should display `lastUpdated`, connection state, and a stale indicator.

#### 5D. Make background work deterministic

- use a single refresh coordinator;
- allow only one in-flight job per source;
- keep one live-auto-refresh timer ID and cancel it before rescheduling;
- use bounded timeouts, retry/backoff, and cancellation;
- update Tkinter only on the main thread;
- make success/error/cancel cleanup idempotent;
- preserve the currently viewed data while a refresh runs;
- rerender all dependent UI state after successful promotion.

#### 5E. Protect local producer data

- use atomic writes for notes and lineups;
- keep rolling, recoverable backups before migrations;
- keep clean-package mode excluding manual notes, lineup locks, logs, producer-generated or private local exports, debug-only raw exports, caches, and any enrichment that has not passed its validation gate. The Phase 1 fixed allowlist remains the default for offline startup; any later expansion requires passed validation gates, the source manifest, the generated distribution manifest, and visible freshness metadata;
- use game ID plus timestamp/revision in packet filenames;
- include data/source timestamps inside the packet itself.

#### Phase 5 acceptance criteria

- Quick Refresh has a predictable short path and neither fetches nor writes the optional enrichment set.
- Default startup ignores optional enrichment workbooks, and unapproved rows cannot reach air-ready output even in explicit development mode.
- Failure of any one optional source retains its last-known-good data.
- A malformed or empty response cannot be promoted as valid.
- Repeated manual and automatic refreshes cannot create duplicate timers or overlapping same-source jobs.
- The UI remains interactive during refresh.
- A user can see which source is stale or failed and what fallback is in use.
- After refresh, selected game, search results, player card, producer prep, and copy text all use one database version.

---

### Phase 6 — Producer-speed improvements

Objective: reduce clicks and cognitive load in a live truck after correctness is established.

#### 6A. Game dashboard

Make the selected game the application's home context. A compact top bar should show:

- away/home teams and official records;
- game time, venue, and status;
- data-health summary;
- lineup lock state and age;
- live connection/last update;
- outstanding verification count.

Implementation status (2026-07-27): complete as the first-tab `Game Day`
command center, together with the pure `GameDayReadiness` policy and explicit
Local/Offline Mode. The later broadcast-fact boundary is documented in
`Phase_6_Broadcast_Fact_Interface.md`. Phase 6B now implements that boundary;
Phase 6C now implements the session-only rundown and used-on-air workflow;
session recovery, change comparison, and faster search remain deferred to
6D–6F.

#### 6B. Air-ready fact cards

Every displayed/copied fact uses one immutable canonical representation with a
stable conceptual `fact_id` and a separate `evidence_hash`. The evidence hash
changes when wording, supporting values, source evidence, approval, or trust
state changes; the stable ID remains usable by later rundown/change workflows.

For every selected-game fact, display:

- deterministic concise air copy;
- expanded context;
- exact source, page/game, approval, parser, and snapshot provenance where
  applicable;
- VERIFIED, VERIFY, STALE, or UNAVAILABLE state derived from evidence;
- one-click qualified air copy and explicit copy-with-source;
- 60- and 120-character guidance without truncation.

Implementation status (2026-07-27): complete. The Game Day tab opens on a
scrollable Air-Ready Facts view and retains Phase 6A readiness in an adjacent
Readiness Details view. Fact generation is local/network-free and coalesced
behind one worker plus one latest pending request. Late results require the
same build generation, exact official game ID, and database identity.
Ordinary air-line copy is unavailable unless every identity, source-health,
freshness, and approval gate passes. Copy history is in memory only.

#### 6C. Pinned rundown, read-time, and used-on-air workflow

Create a small ordered copy/rundown queue for the selected game. Keep it local
and exportable to plain text. Pin canonical facts without reparsing visible
text, retain their evidence hashes and provenance, add read-time budgeting,
and support a used-on-air timestamp. Do not imply direct integration with a
broadcast graphics system unless one is explicitly implemented.

Implementation status (2026-07-28): complete. `src/ausl_rundown.py` owns one
session-only state per exact official game ID, with canonical fact snapshots,
dense ordering, timezone-aware pin/use timestamps, a configurable 140-WPM
estimate, game-local break targets, stable-ID repeat suppression, Undo Used,
and safe refresh reconciliation. The Game Day Rundown view separates active
air-ready pins, Needs Verification pins, and used history. It offers reliable
move buttons, safe copy actions, deliberate latest-version replacement,
clipboard rundown copy, and exclusive producer-private text export.

Changed, downgraded, or missing current evidence never silently rewrites or
deletes a pinned snapshot and is excluded from air-ready timing. Read-time
overage is a workflow warning only. Export files live under the already
ignored/distribution-forbidden game-packet area. No rundown mutation accesses
the network, and Local/Offline Mode permits the complete local workflow.
Phase 6C writes no session state to disk; Phase 6D remains responsible for
atomic persistence, autosave, crash recovery, and restart restoration.

#### 6D. Session persistence and crash recovery

Persist and recover selected game, pinned/used facts, and safe view state
without weakening existing atomic-write or privacy rules.

Implementation status: not started.

#### 6E. “What changed?” panel

After refresh, summarize material changes since the previous validated version:

- roster/status changes;
- official record changes;
- newly locked lineups;
- probable-starter changes;
- new injuries/transactions;
- milestones newly reached or now within range;
- corrected or invalidated notes.

This is often more valuable before air than rereading every panel.

Implementation status: not started.

#### 6F. Faster search and player comparison

Search should support player name/aliases, team, number, position, roster
status, typo tolerance, and lightweight quick filters. Add side-by-side player
comparison only after collision-safe identity behavior is tested.

Implementation status: not started.

#### Cross-cutting readability and accessibility

- add visible scrollbars to long panels;
- preserve scroll position when safe;
- support Windows display scaling at 100%, 125%, and 150%;
- use status text/icons in addition to color;
- keep important copy selectable;
- ensure tab order and keyboard activation work;
- avoid modal confirmations for ordinary browsing, reserving them for risky on-air overrides.

#### Phase 6 acceptance criteria

- A producer can select a game, find a player, verify a fact, and copy it without changing tabs more than necessary.
- Every pinned item retains source/freshness metadata.
- Search and primary actions are keyboard-operable.
- Long content remains reachable at minimum supported window size and common Windows scaling levels.
- “What changed?” reports only differences between validated dataset versions.

---

### Phase 7 — Higher-value future features

Begin only after Phases 0–6 pass. These are worthwhile, but none should delay reliability work.

#### Live milestone watch

Combine pregame thresholds with live box-score events. Example: `Player needs 2 hits for 100 career` becomes `1 away` after a hit. Preserve the pregame source and label the live calculation time.

#### Verification desk

Collect all `needs_review`, stale, ambiguous, or conflicting items in one queue. Permit a producer to approve, correct, suppress, or annotate a fact, with an audit timestamp.

#### Scenario and standings context

If the AUSL format makes it useful, calculate clinching/elimination or seeding scenarios from official rules and standings. This requires a versioned rules source and extensive tests; never infer rules from standings alone.

#### Shared show workflow

Support export/import of a game package containing selected game, locked lineups, pinned facts, and producer notes. Use conflict-aware revisions and exclude unrelated personal data. Consider multi-user/cloud synchronization only with clear ownership, authentication, and offline behavior.

#### News and transaction intake

Add a review-only feed for official AUSL/team announcements. Never insert third-party or social text directly into air-ready copy. Require source link, publication time, subject identity, and producer verification.

## 6. Function-by-function work map

| File | Function/area | Planned change |
|---|---|---|
| `src/ausl_stats_app.py` | `_load_initial`, `update_data`, `refresh_live` | Safe exception/result handoff; in-flight guards |
| `src/ausl_stats_app.py` | `_finish_load` | Rerender every dependent state from one database version |
| `src/ausl_stats_app.py` | `show_all`, `show_team`, `search` | Explicit filters; status and jersey search; no hidden scope mutation |
| `src/ausl_stats_app.py` | `lineup_key`, `current_locked_lineups` | Key and retrieve by official game ID |
| `src/ausl_stats_app.py` | `parse_lineup_text`, `lock_lineups_from_editor` | Structured validation, errors/warnings, DP/FLEX rules |
| `src/ausl_stats_app.py` | `load_projected_lineups_into_editor` | Game/status-aware projection with source label |
| `src/ausl_stats_app.py` | `save_manual_note`, `_manual_note_lines` | Explicit note scopes and exact identities |
| `src/ausl_stats_app.py` | `render_team_totals`, `_team_metrics`, `_packet_team_snapshot`, `_standings_row` | Consume one official team snapshot |
| `src/ausl_stats_app.py` | `_projected_lineup`, `_projected_pitchers`, `_players_to_watch` | Active-only defaults, availability section, sample reliability |
| `src/ausl_stats_app.py` | `pitching_line`, `decimal`, `_innings_to_outs` | Canonical innings and distinct numeric formatters |
| `src/ausl_stats_app.py` | `_best_split_rows`, `_best_split_lines` | Exclude regular-season aggregate; reliable samples |
| `src/ausl_stats_app.py` | `_media_guide_player_lines`, `_media_guide_team_lines` | Verification/source gating |
| `src/ausl_stats_app.py` | `_official_game_note_lines`, `_producer_prep_lines` | Structured, balanced, exact-game selection |
| `src/ausl_stats_app.py` | `generate_pregame_report` | Render section model once; source timestamps; unique filename |
| `src/ausl_stats_app.py` | `gfx_text`, `copy_gfx` | Null-safe copy, clear season/career labels, status gate |
| `src/ausl_stats_app.py` | `_schedule_live`, `_auto_refresh`, `_finish_live` | One timer, stale state, deterministic cleanup |
| `src/ausl_data.py` | `roster_frame` | Unknown-by-default status and normalized identifiers |
| `src/ausl_data.py` | `_clean_media_guide_text`, `fetch_media_guide_frames` | TOC/page-range extraction and audit metadata |
| `src/ausl_data.py` | `_game_note_category`, `_split_game_note_items`, `fetch_official_game_notes_frame` | Conservative categories, subjects, dates, hashes |
| `src/ausl_data.py` | `update_all_data`, `_write_excel_atomic`, `load_database` | Per-source staging, validation, manifest, fallback |
| `src/ausl_data.py` | `_ip_to_outs`, `career_pitching` | Shared innings math and derived-metric validation |

## 7. Split-stat reliability policy

The current improvement to show sample sizes is valuable, but six plate appearances or one inning is still too small to promote as a top storyline. Also, the aggregate `regularSeason` row should not compete with situational splits.

Implement a configurable policy:

- exclude `regularSeason` from the best situational-split list;
- default hitter qualifying threshold: at least 10–12 PA, subject to product review;
- default pitcher threshold: at least 3 IP or a minimum batters-faced threshold;
- always display the sample;
- show a `small sample` badge below the threshold;
- use shrinkage/reliability weighting if ranking rates, or avoid numeric rank claims entirely;
- keep all splits discoverable in the detailed view even when not promoted.

Tests must prove that a 6-PA batting split and 1-IP pitching split are not promoted as a top fact, and that the full-season aggregate is not labeled a situational advantage.

## 8. Test and verification matrix

### Unit tests

- innings parsing and ERA/WHIP derivation;
- rate versus decimal formatting;
- missing-value rendering;
- manual-note scope and identity resolution;
- lineup key, parser, validator, DP/FLEX, and migration;
- official team snapshot authority;
- roster-status normalization and recommendation filters;
- media TOC/range parsing, identity validation, and deduplication;
- game-note classification, subject extraction, hashing, freshness, balance, and priority;
- split qualification and sample labels;
- copy text for every status and copy type.

### Integration tests

- `load_database` with a complete fixture and each optional source missing;
- refresh staging with mocked network success, timeout, malformed response, empty response, and partial failure;
- preservation of last-known-good datasets;
- generated-packet snapshot from a fixed selected game;
- live-response parser and stale-live detection;
- database refresh followed by selected-card and producer-prep rerender;
- manual-note and lineup atomic-write/migration recovery.

### Regression sweeps

- every player × every copy type: no exception, correct status and season label;
- every scheduled matchup/game: exact game context and unique lineup state;
- all six team totals: packet/UI W-L equals official standings;
- repeated manual/automatic refresh: one timer, no duplicate job;
- injected failure for each optional source: app remains usable and retains prior data;
- packet sections: no accidental duplicate storyline blocks.

### Manual Windows smoke test

1. Start from a clean install and from an existing-data upgrade.
2. Open all six main tabs.
3. Select two different games between repeat opponents.
4. Search by name, team, position, `22`, `#22`, `inactive`, and `reserve`.
5. Open active, inactive, reserve, and unknown-status player cards.
6. Exercise every copy action.
7. Enter valid and invalid lineups, including DP/FLEX.
8. Run Quick Refresh, cancel/retry it, and simulate one failed source.
9. Run Full Enrichment Refresh and confirm progress/source health.
10. Enable/disable live auto-refresh repeatedly and confirm only one timer runs.
11. Generate two packets and verify unique filenames and consistent records.
12. Test minimum supported window size and Windows scaling at 100%, 125%, and 150%.

## 9. Suggested implementation boundaries

Keep business logic outside the Tkinter class where possible. Small dataclasses or typed dictionaries are enough; a framework change is unnecessary.

Recommended pure models/helpers:

```text
SelectedGame
TeamSnapshot
DataSourceHealth
LineupEntry
LineupValidationResult
ScopedNote
MediaGuideMatch
OfficialNote
StorylineCandidate
ProducerPrep
RefreshResult
```

Recommended services:

```text
GameContextService
LineupStore
ManualNoteStore
TeamSnapshotService
MediaGuideParser
OfficialNoteClassifier
StorylineSelector
RefreshCoordinator
```

These can initially remain in the existing two modules or a small number of focused new modules. Do not create a large architecture hierarchy merely to rename functions.

## 10. Release gates

### Independent Phase 4 stability-audit remediation (2026-07-22)

Phase 4 acceptance is reopened for a narrow corrective pass after adversarial
review of the portable source. This does not authorize a redesign or a phase
skip. Add offline failing-first regressions before each correction.

- Bind every live request to the selected official game ID and a monotonically
  increasing game/request generation. A game change invalidates callbacks and
  cancels owned timers; a returned feed ID must match both request and current
  selection.
- For historical exact-game prep, prior matchups must be completed, strictly
  earlier than the selected game's parsed time, and a different game ID.
  Equal-time, future, selected-game, and unparseable candidates fail closed.
  Current standings must be labeled current rather than as the record entering
  a historical game unless a true as-of snapshot exists.
- Preserve DP/FLEX as a separate stored role through editor reload, validation,
  re-save, lineup copy, and producer packets. Starting pitchers must retain and
  pass their roster position (`P`, `RHP`, or `LHP`); any future two-way
  exception requires an explicit reviewed record and cannot be inferred.
- Derive lineup/starter headings from stored provenance. Projected, manual, and
  imported input remain explicitly nonofficial; only validated authoritative
  provenance may render as official.
- Commit lineup save/delete changes to memory only after an atomic disk write
  succeeds. A write failure leaves the previous in-memory and on-disk state
  unchanged and displays a persistent error.
- Air-ready media requires one canonical approval transaction: verified match
  state, exact subject/team identity, printed and PDF provenance, guide date,
  no unresolved identity warning, reviewer, and approval timestamp. Independent
  Boolean flags cannot promote a row and display labels come from canonical
  state.
- Complete the already-planned main-thread result handoff, live timer ownership,
  last-known-good source promotion protections, and live freshness state before
  claiming demo stability.
- Portable ZIP writers must emit POSIX `/` member paths. Repair missing-time
  mojibake and update README instructions to the official selected-game flow.

Acceptance result (2026-07-22): this corrective pass passed 390 offline tests
and the same 390 tests with warnings promoted to errors, compilation,
dependency integrity, a no-network six-tab Windows/Tk smoke, and a real
privacy-verified source build with POSIX ZIP members, CRC, extraction, and
checksum verification. At the time of that acceptance, the checked-in core
snapshot remained dated July 9. A later validated core-only refresh on
2026-07-23 superseded it without activating or rewriting optional enrichment;
eight media identities remain review-only; broader source-health UI,
retry/cancellation policy, target-truck scaling, and producer rehearsal remain
required before Gate C. This result restores Phase 4 rehearsal readiness but
does not claim unattended live-broadcast readiness.

### Gate A — Safe for internal testing

- Phase 1 complete.
- No known crash from copy, load, or refresh error paths.
- Official records are consistent.
- Manual notes cannot leak between players.
- Nonactive statuses are visible.

### Gate B — Safe for rehearsal use

- Phases 2–4 complete.
- Game/lineup state is exact-game scoped.
- Media-guide identity audit passes.
- Official notes are source-labeled, balanced, and conservatively classified.
- Packet content is nonduplicative and internally consistent.

### Gate C — Candidate for live broadcast use

- Phase 5 complete.
- Refresh failure preserves last-known-good data.
- Data-health and staleness are visible.
- Windows smoke test passes on the target truck hardware.
- A producer has completed at least one rehearsal using real workflow and signed off on warnings, copy labels, and navigation.

### Gate D — Feature expansion

- Phase 6 complete and stable through rehearsal/live use.
- Only then begin Phase 7 capabilities.

## 11. Definition of done for every change

A task is done only when:

- the behavior is implemented in the narrowest appropriate layer;
- deterministic tests cover success, missing-data, ambiguous-data, and failure paths;
- existing user files are preserved or recoverably migrated;
- source authority, freshness, and uncertainty are visible where relevant;
- background work cannot mutate Tkinter widgets directly;
- the full offline test suite passes;
- the relevant Windows manual smoke check passes;
- the implementation notes identify any remaining assumption that a producer must validate.

## 12. First Codex work order

The safest first implementation session is intentionally limited:

1. Add the test skeleton and compact fixtures.
2. Fix delayed exception callbacks and in-flight button state.
3. Add canonical innings conversion and formatting tests.
4. Make reserve/unknown team copy null-safe and clearly labeled.
5. Add exact manual-note scope retrieval tests, then correct the fallback.
6. Add `official_team_snapshot` and route all record displays through it.
7. Run the full suite and a six-tab Windows smoke test.

Do not start media-guide parsing, game-note classification, or a UI redesign in that first work order. The initial milestone should leave the current application visibly familiar but materially safer for a broadcast producer.
