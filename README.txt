AUSL BROADCAST STATS LOOKUP

This is the standalone AUSL softball broadcast tool project. It is separated
from the NFL_STATS_DATABASE project, so changes here do not modify or replace
the NFL application.

CURRENT READINESS
Phases 1-7C are implemented. The project owner accepted the exact ten-player
Phase 7C college pilot on 2026-08-11 and authorized Phase 7D; this is recorded
as project-owner acceptance, not as a claim of personal AUSL producer review.
Phase 7D adds the ninth main tab, College Résumé, using only a hash-validated
approved local envelope and exact player IDs. The project owner reported on
2026-08-12 that the Phase 7D scaling test passed at 100%, 125%, and 150%.

The clean Phase 7A baseline passed 769 offline tests. The accepted Phase 7A
source passes 847 tests with warnings treated as errors. The deterministic
Windows source-app smoke passes at 1120x720 with real Tk and zero network
calls. It covers approved facts for both selected-game teams, Full Refresh
cancellation while blocked, an immediately queued replacement refresh,
coherent replacement database/facts, Local/Offline Mode, and all eight tabs.
Compileall, pip check, Git LFS validation, core and approved-enrichment
distribution verification, whitespace validation, packaging/privacy checks,
and tracked/history private-data and secret scans pass. The future-season
year-generalization patch remains applied once and its regressions pass.

Truck-hardware smoke testing, producer rehearsal, and Windows display scaling
at 100%, 125%, and 150% are recorded as completed based on the project owner's
report. No hardware model, Windows build, rehearsal date, or additional
observed behavior is asserted here because those details were not supplied.

The project owner reports that the developer-only optional enrichment refresh
was run and the resulting real fact cards were manually reviewed without
dubious facts or enrichment issues being observed. This is an owner-reported
content audit only; no unsupplied samples, dates, or test details are asserted.

Status: PHASE 7E DATA ACCEPTED — FINAL WINDOWS SIGN-OFF PENDING.
The 2026 coverage manifest accounts for all 118 exact roster IDs. On
2026-08-12, the project owner approved all 11 bounded batches after reporting
no mistakes, clear unavailable labels, and matching schools. The resulting
aggregate is 9 Verified and 109 Partial; review did not invent absent fields.
Historical gate: PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED.
Phase 7E data integration followed that authorization. The project owner then
double-checked and approved all eight exact college
connection wordings. Those immutable evidence versions now appear in College
Résumé and eligible selected-game fact workflows, including copy, pin,
rundown, used-on-air, session restore, What Changed, and the explicit
approved-enrichment package. Changed future evidence requires new review.
Phase 7 is not yet closed: the owner must still run the final Windows expanded-
content scaling check at 100%, 125%, and 150%.
The reported scaling result closes the Phase 7D start gate without asserting
unsupplied hardware, package, or interaction details. This remains an assisted
broadcast tool, not a candidate for unattended on-air use: cards that do not
pass exact identity, provenance, freshness, source-health, and approval gates
stay VERIFY, STALE, or UNAVAILABLE and cannot use ordinary air-line copy.
College values are visually and statistically separate from AUSL professional
totals. Missing or conflicting college fields remain unavailable, the one
documented Partial résumé remains Partial, and developer-review data cannot use
producer copy actions. Cancellation is cooperative while a single urllib request is inside its
bounded timeout, although cancelled/superseded jobs cannot overlap core
commits or replace a newer coherent snapshot.

FIRST-TIME SETUP
Double-click:
  Setup AUSL Environment.bat

This creates a local .venv folder for the AUSL app and installs the needed
libraries. Python 3.12 is required. Runtime, test, and build dependencies are
pinned and installed through constraints.txt so a build cannot silently take
newer package versions.

START
If you are using the portable ZIP version, unblock and unzip the folder, then
double-click:
  Start AUSL Broadcast Stats.bat

If you are using the PyInstaller ZIP version, unzip the folder and
double-click:
  AUSL Broadcast Stats.exe

If you are working from this project/source folder, use:
  Launch AUSL Stats App.bat

SHARING / WINDOWS DEFENDER NOTE
There are three shareable packages. Pick by what the recipient can be asked
to do:

  dist\AUSL-Broadcast-Stats-Portable-Windows.zip     <- recommended for sharing
    Built by "Build Portable AUSL App.bat". Carries its own copy of CPython,
    so the recipient installs nothing and needs no network access. Nothing in
    it is compiled locally: every binary comes from the official python.org
    embeddable release and from the pinned dependency wheels, so there is no
    unsigned, newly built executable for Defender to score as unknown. That is
    the pattern that gets auto-quarantined, not the presence of an .exe.
    About 30 MB compressed, roughly 90 MB extracted.

  dist\AUSL-Broadcast-Stats-Windows.zip
    PyInstaller build. One self-contained .exe tree, but the bootloader is
    freshly compiled and unsigned, so it has no SmartScreen reputation and is
    the build most likely to be quarantined on download.

  dist\AUSL-Broadcast-Stats-Safer-No-EXE.zip
    Sources only. Smallest download, but the recipient must already have
    Python 3.12, run "Setup AUSL Environment.bat" once, and be online while
    pip installs.

The packaged .exe build disables UPX packing and uses an uncompressed ZIP to
reduce false-positive antivirus heuristics. The portable build uses deflate
instead, because an uncompressed 90 MB archive is impractical to send and a
plain deflate ZIP is still scannable by every mail and endpoint scanner.
Code signing is still the only way to remove unknown-publisher warnings
outright.

SENDING THE PORTABLE PACKAGE
It cannot go out as an email attachment. Gmail and most corporate mail
gateways reject archives containing python.exe regardless of the archive
extension, and the package is over the 25 MB attachment limit anyway. Upload
it to Drive/OneDrive/Dropbox and send the link, or attach it to a GitHub
release. Do not rename the extension or password-protect the ZIP to slip it
past a scanner: that trips spam heuristics and makes the download look worse,
not better.

Paste the contents of the .sha256.txt file into the email body so the
recipient can confirm the download with:
  Get-FileHash -Algorithm SHA256 "path\to\package.zip"

Tell the recipient to right-click the downloaded ZIP, choose Properties, tick
"Unblock", and only then extract it. That clears the mark-of-the-web from
every extracted file at once. Extracting first instead propagates the mark to
each file and produces a SmartScreen prompt on the launcher.

The bundled runtime is pinned by SHA-256 in tools\embedded_runtime_pins.json.
The first build of a given Python version stops and prints the hash it
downloaded; compare it against the checksum published on python.org, then
re-run with -AcceptRuntimeHash to record it and commit the result. Later
builds fail closed if the download ever changes.

All three build paths run tools\verify_distribution.py before and after
compression and write a portable SHA-256 file beside each ZIP. Verify a ZIP
with:
  Get-FileHash -Algorithm SHA256 "path\to\package.zip"
The result must match the first value in package.zip.sha256.txt.
ZIP members use portable POSIX-style paths so the same archive extracts into
the intended folder structure on Windows, macOS, and Linux.

If Defender is especially aggressive, use:
  Build Safer No-EXE AUSL App.bat

That creates only:
  dist\AUSL-Broadcast-Stats-Safer-No-EXE.zip

It does not run PyInstaller and does not create a bundled executable.

DATA
Click "Quick Refresh (Core)" in the app. The normal updater downloads official
AUSL roster/stat JSON for every configured season, plus standings and
schedule context, then builds the validated core workbooks under:
  data\exports

Quick Refresh does not fetch or rewrite split-stat, media-guide, or
official-game-note enrichment. It does reload validated local
PRODUCER_APPROVED rows after the core transaction.

Click "Full Enrichment Refresh" for a deliberate producer-facing update of
official splits, schedule-linked game-note PDFs, and the configured media
guide. Core and every successful optional source promote in one
rollback-capable transaction. A failed optional source retains its
last-known-good workbook and reports its own health/fallback state. Quick and
Full jobs share one serialized coordinator.

AUSL Career totals in this version combine the available AUSL regular-season
files for every season in the configured season map. They are not full
softball career totals, college career totals, Team USA totals, or All-Star
Cup totals.

The app displays the latest local data timestamp in the header. Any exported
producer packet includes that timestamp plus a reminder to verify lineups,
availability, and milestones before air.

DATA AUTHORITY AND FRESHNESS
Official AUSL standings are the only source used for a team's on-screen W-L
record. Pitcher decisions remain separately labeled calculated player-stat
aggregates. If an official standings row is missing or ambiguous, the app says
"Record unavailable" instead of inventing a record. Missing or malformed
player values render as unavailable rather than factual zeroes.

Season pitching WHIP is derived from the official hits allowed, walks, and
baseball innings converted to outs: (H + BB) * 3 / outs. The imported WHIP is
retained as source_whip for audit only and is never used as a fallback. Missing,
malformed, negative, or zero-inning component data makes WHIP unavailable.

Packaged official-data workbooks are a dated offline-startup snapshot, not a
claim that the facts are current. Check the visible source/freshness/VERIFY
labels and refresh official data before production use.

Snapshot health and latest-attempt health are separate. update_manifest.json
describes the installed last-known-good snapshot. refresh_attempt.json records
the latest refresh outcome atomically without replacing a validated snapshot
after a failure. The UI distinguishes "stored snapshot valid" from "latest
refresh failed"; cancellation is not reported as a source failure, and a later
success clears the failed-attempt state.

GAME DAY COMMAND CENTER
The first tab is Game Day. It renders one pure readiness result for the exact
selected official game and shows:
  - teams, official records, game time, venue, status, ID, and schedule age;
  - installed snapshot health separately from the latest refresh attempt;
  - exact-game lineup save, validation, source, time, revision, and warnings;
  - game-aware live-feed state, timestamp, age, ID, and auto-refresh state;
  - the exact-game/team verification count, or Unavailable when optional
    review data is not loaded;
  - producer-packet game ID, generation time, lineup source, and revision;
  - one derived READY FOR AIR, NEEDS ATTENTION, or NOT READY state.

There is no manual force-green control. Unknown never counts as pass. Saved
projected, manual, and imported lineups remain warnings and are never described
as official. A stale or disconnected exact-game feed blocks readiness once the
authoritative game or live response says the game is live.

AIR-READY FACTS
Game Day now opens on an Air-Ready Facts view, with Phase 6A's complete
readiness detail retained in the adjacent Readiness Details view. Every card is
an immutable canonical Broadcast Fact with:
  - stable conceptual fact ID;
  - separate evidence hash that changes with wording, value, provenance,
    approval, or trust state;
  - exact player/team/game/season identity;
  - concise air copy and optional context;
  - source, page/game identity, snapshot freshness, parser, and approval
    provenance where applicable;
  - one derived VERIFIED, VERIFY, STALE, or UNAVAILABLE state.

The selected-game builder is local and deterministic. It wraps installed
official statistics, canonical roster status, exact-game lineup provenance,
approved official game notes and media-guide rows when explicitly loaded,
exactly scoped producer notes, and official team snapshots. It does not access
the network or generate prose with AI. One worker performs fact aggregation;
one pending replacement is coalesced, and late results are discarded unless
their generation, official game ID, and database identity still match.

Copy Air Line is enabled only for an air-ready VERIFIED fact and copies the
exact displayed string. Its in-memory copy event retains the fact ID, evidence
hash, full provenance, snapshot, copy time, and selected character-width
profile. Copy With Source remains available for research/handoff and prints
the trust state and warning explicitly. Copying never promotes verification,
and Phase 6B does not persist copy history.

Character guidance is centrally configured for 60-character one-line and
120-character extended profiles. It counts the exact Unicode string that Copy
Air Line uses, labels likely wrapping without truncating or rewriting facts,
and is guidance only—not validation against an XPression or other graphics
template.

PINNED RUNDOWN AND ON-AIR WORKFLOW
The Game Day Rundown view keeps a separate in-memory queue for each exact
official game ID. Air-ready cards can be pinned directly; warning-bearing
research cards use Pin for Review and remain visibly separate. Unavailable
facts cannot be pinned. The queue stores the canonical Broadcast Fact,
evidence hash, provenance, verification state, pin time, and deterministic
position rather than reparsing displayed text.

Each exact air-copy string receives a deterministic read-time estimate at a
central 140-words-per-minute rate, with a one-second minimum for nonempty
copy. The producer may choose 15/30/45/60/90-second presets or enter a
validated custom target. The displayed total is the sum of active air-ready
item estimates. Review, changed, invalidated, and used facts are excluded
from the remaining air-ready total. Being over target is a workflow warning,
not a factual readiness failure.

Mark Used on Air records a timezone-aware snapshot and evidence hash whether
the fact was pinned or used directly from a card. The stable fact ID is then
suppressed from default suggestions for that exact game, even after an
ordinary rerender. Show Used reveals it; Undo Used restores suggestion
eligibility and returns a previously pinned item to a deterministic queue
position. Another official game has independent pin/use state.

A refresh never silently rewrites a pin. Same fact/evidence remains current;
changed evidence or downgraded verification moves the retained snapshot into
review; a missing fact is retained as invalidated. Review / Replace Latest
requires an explicit confirmation and preserves queue position. This safety
reconciliation is not the broader Phase 6E What Changed interface.

Copy Rundown produces a source-labeled text version on the clipboard. Export
Text creates an exclusive, collision-resistant producer-private file under:
  data\exports\game_packets\rundowns
That directory is ignored by Git and rejected by the public distribution
verifier. Rundown state is now part of the private Phase 6D producer session
described below. Canonical pinned and used snapshots, exact evidence hashes,
order, break target, and reconciliation state survive a clean restart or
crash.

SESSION AUTOSAVE AND RECOVERY
Phase 6D saves producer working state under the current user's private
application-data directory, outside the repository and install folder:
  %LOCALAPPDATA%\AUSL Broadcast Stats\producer_session.json

The versioned schema-v3 JSON contains primitives only. It can retain the exact selected
official game identity, canonical per-game rundown and used history, Game Day
view and filters, unique selected player identity, exact left/right comparison
player IDs, and normalized fact/rundown/change/comparison scroll positions. It
deliberately does not persist clipboard contents or comparison copy records,
workers, timers, locks, credentials, network responses, or an enabled
Local/Offline Mode.

Meaningful changes use one 500 ms debounced Tk timer. Saves are serialized,
written to a same-directory temporary file, flushed, and atomically replaced.
A previous validated snapshot is retained as a backup. A failed write leaves
the installed session byte-identical and displays a persistent SESSION NOT
SAVED warning; it does not alter data-health truth. Normal shutdown flushes a
closed-cleanly lifecycle marker. A saved active marker produces a crash
recovery notice on the next launch.

Restore never guesses. The saved game ID, season, away team, and home team
must all match one current official schedule row. A mismatch remains a
blocking recovery issue and preserves the saved identity until the producer
selects a game or starts fresh. Facts are restored as canonical snapshots and
then passed through the existing refresh reconciliation rules. Offline Mode
always starts off.

Corrupt, oversized, malformed, or newer-schema files fail closed and are
copied byte-for-byte to a timestamped quarantine file. A valid backup may be
used; otherwise the app continues with an empty session and a visible warning.
The recovery notice offers Review, Dismiss, and Start Fresh. Start Fresh first
creates an exclusive recovery archive and refuses to clear runtime state if
that archive cannot be written. Producer session filenames are ignored by Git
and explicitly rejected by distribution privacy verification.

POST-REFRESH WHAT CHANGED
The Game Day "What Changed?" view compares only two validated installed
snapshot digests. The first valid snapshot establishes a baseline without
reporting every row as newly added. A later successful local load or core
refresh can report material roster/status/team assignment, official
record/rank/games-back/streak, exact-game schedule/final-score, lineup,
source-health, canonical fact, verification, and milestone-transition changes.
Routine stat-row churn appears only when it changes a canonical broadcast fact.

Each immutable event retains before/after snapshot identity, exact player/team/
game/season/fact identity where applicable, concise before/after summaries,
severity, selected-game/pinned/used/readiness impact, source context, and a
stable event ID. Milestones are linked only by canonical identity, never by
similar prose. Manual producer-note wording is not copied into the digest.

The view provides All Changes, Needs Attention, Selected Game, Pinned, and
Used filters plus team/category filters. Acknowledgement is persisted as event
identity only and never changes a fact, source-health state, rundown entry, or
readiness gate. Pinned wording is never silently replaced; Review Pinned and
the existing confirmed Replace With Latest path remain explicit.

Digest creation and comparison are local/network-free and run in one bounded
worker with one coalesced replacement. Late generation, database, or selected-
game results cannot promote a baseline. Failed/cancelled refreshes and failed
comparisons retain the prior baseline/report. The schema-v3 private producer
session atomically stores the baseline, latest complete result,
acknowledgements, five compact history summaries, refresh outcome metadata,
and normalized change-panel filters/scroll position.

PLAYER DISCOVERY AND COMPARISON
Player Lookup uses one reusable local roster index per installed database. It
supports exact names, explicitly approved aliases, team, position, roster
status, jersey number, free text, and AND-combined filters such as:
  team:CHI pos:P status:active #22
  team:"Chicago Bandits" name:"Rachel Garcia"

Ranking is deterministic: exact full name, approved alias, exact name token,
prefix, substring, then conservative typo candidates. A possible typo is
visibly labeled and never auto-selects a player. Typo matching includes
individual first/last name tokens, so conservative partial-name errors such as
`Gacria` can surface Rachel Garcia without opening her automatically. Ordinary
straight and smart apostrophes in names remain inert text; double-quoted filter
values retain strict malformed-quote validation. Explicit team filters
override the selected-game scope for that query only; the saved scope
preference is not mutated. Unknown or malformed filters show a safe
explanation.

The Compare Players tab accepts two different exact roster identities. It
aligns current-season and AUSL-career batting, pitching, and fielding values
through one metric registry and the existing canonical WHIP/innings rules.
Missing values stay Unavailable; two-way players keep both roles; inactive,
reserve, unknown-status, or teamless players retain warnings. The view makes no
winner or "better player" judgment. Exact-game canonical facts are kept
independent by player, with their original trust state. Each visible fact now
shows its own verification state, source reference/date/page/game, snapshot,
source health, and review warning. The shared statistical database line is
separately labeled `Statistics source` / `Statistical snapshot`.

Copy Metrics + Stat Source remains deliberately metrics-only. It includes both
identities, selected-game context, statistical source, snapshot freshness, and
an explicit verify-before-air status without implicitly adding fact wording.
Its in-memory copy record is not persisted. Ctrl+F focuses Player Lookup, arrow
keys move the result highlight, Enter explicitly opens that identity, Escape
clears the search, and Ctrl+1/Ctrl+2 assign the highlighted or selected player
to the comparison sides. These shortcuts do not intercept multiline note
editing. Visible scrollbars and mouse-wheel support cover the lookup list and
comparison view.

LOCAL/OFFLINE MODE
The visible Local/Offline Mode control appears beside the refresh controls and
in the Game Day tab. While enabled it blocks core, full-enrichment, and manual
live refreshes, cancels
their existing tokens, stops and prevents live timers, and ignores abandoned
network callbacks. Local search, notes, lineups, packet generation, and copy
actions remain available against the installed last-known-good snapshot.

Offline Mode defaults off on every fresh launch. Turning it off does not start
a refresh or live request; the producer chooses when network activity resumes.

STORYLINE / ENRICHMENT DATA
Full Enrichment Refresh can import official AUSL split stats, the media guide
for the latest configured season, official game notes, and a source registry.
These are saved locally under:
  data\exports\ausl_batting_splits.xlsx
  data\exports\ausl_pitching_splits.xlsx
  data\exports\ausl_fielding_splits.xlsx
  data\exports\ausl_team_context.xlsx
  data\exports\ausl_storyline_sources.xlsx
  data\exports\ausl_media_guide_players.xlsx
  data\exports\ausl_media_guide_teams.xlsx
  data\exports\ausl_media_guide_notes.xlsx
  data\exports\clean_media_guide_notes.xlsx
  data\exports\ausl_media_guide_raw_chunks.xlsx
  data\exports\official_game_notes.xlsx

The cached media guide PDF is saved to:
  data\sources\<configured-season>-AUSL-Media-Guide.pdf

The loader has three explicit modes. CORE_ONLY ignores optional workbooks.
PRODUCER_APPROVED is used by ordinary startup, Quick/Full completion,
Local/Offline Mode, sessions, and packaged apps; it loads only rows that pass
complete identity, provenance, approval, freshness, and source-health gates.
DEVELOPER_REVIEW exposes raw/review material for development but cannot
promote it to air-ready output by flipping a Boolean. The legacy
include_enrichment=True flag maps only to DEVELOPER_REVIEW.

Split rows use one centralized policy: exact normalized regularSeason
aggregates are excluded; hitters require 12 plate appearances and pitchers
require 9 canonical outs for air-ready eligibility. Smaller valid detailed
samples remain visible with a SMALL SAMPLE warning and are never promoted.
Raw page chunks remain developer-only and are excluded from every
distribution profile.

Official game notes PDFs listed on the AUSL schedule are cached under:
  data\sources\game_notes

Registered enrichment sources include the configured season's AUSL Media
Guide, AUSL news, MLB AUSL news, draft/Golden Ticket pages, college/award
sources, and manual producer notes. Treat those as context layers unless
verified against official game notes.

LIVE GAME
Choose an official game from Game Setup. Its authoritative game ID is copied
into the Live Game tab as a read-only value. The app blocks a detached or typed
different ID, rejects a late response after the selected game changes, and can
refresh the selected game every 30 seconds. The live panel displays the feed's
own lastUpdated value plus CONNECTED/CURRENT, STALE, or unavailable state.

PRE-GAME REPORT
Choose an official scheduled game in Game Setup and click "Generate Producer
Packet."
The text report includes stat-based projected lineups and starting pitchers,
team totals, milestone notes, players to watch, suggested graphics, and
jersey/roster references. Projections are not official and must be checked when
the teams release their game lineups. Automatic lineup, pitcher, player-to-watch,
and milestone recommendations contain active-roster players only. Nonactive,
reserve-pool, and unknown-status players are listed separately under
Availability Impact with status and freshness context.

PRODUCER PREP
The Producer Prep tab builds a quick matchup summary, players to watch,
milestone-watch notes, and a copyable graphics queue for the selected teams.

LINEUP LOCK
Use the Lineup Lock tab to load a projection or paste a lineup for the selected
official game. Enter starting pitchers, then click "Validate & Save Lineups."
The app validates exact team/player identity, positions, 1-through-9 order,
starter eligibility, and DP/FLEX before saving. Producer packets derive their
headings from the saved source: projected, manual, and imported input remains
explicitly nonofficial. Saved lineups are stored locally in:
  data\manual\locked_lineups.json

MANUAL NOTES
Use the Manual Notes tab to save pronunciation notes, producer reminders,
injury context, story ideas, or do-not-use notes. They are saved locally to:
  data\manual\player_notes.csv

Choose an explicit player, team, game, or global scope. Player selection uses
the exact AUSL player ID; ambiguous typed names and game IDs absent from the
official local schedule are blocked. A player card can receive only its exact
player note plus explicitly scoped team/game notes; global notes require an
intentional opt-in.

Writes are atomic. Before a legacy CSV is migrated, its exact original bytes
are copied beside it as:
  player_notes.csv.backup-<UTC timestamp>
Ambiguous legacy rows are retained as legacy_unassigned and are not guessed
onto a player or team. To recover, close the app, preserve the newer CSV, and
copy the selected backup back to player_notes.csv.

TEAM TOTALS
The Team Totals tab provides MLB-style sortable Batting, Pitching, and Fielding
tables. Each table includes player rows and a highlighted TEAM TOTALS row. The
record is the official standings record with source/freshness metadata;
calculated pitcher decisions are clearly labeled and are never promoted to the
team record.

COPY OUTPUTS
Player Lookup has four explicit copy actions:
  Player ID       name, team, roster status, position, and known number
  Season Stat     current AUSL season only, explicitly labeled
  Career Stat     AUSL CAREER totals across the configured season range,
                  explicitly labeled
  Announcer Note  narrative plus verification and freshness metadata

Inactive, reserve-pool, and unknown-status output retains a visible VERIFY
warning and requires confirmation before the clipboard is changed. Unknown
team, position, number, or stat values remain visibly unavailable; they do not
render as nan or a confident zero.

PRIVACY / CLEAN DISTRIBUTION
The default `core` distribution profile contains only this tested snapshot
allowlist:
  data\exports\ausl_rosters.xlsx
  data\exports\ausl_season_stats.xlsx
  data\exports\ausl_career_stats.xlsx
  data\exports\ausl_team_context.xlsx
  data\exports\update_manifest.json
  data\exports\refresh_attempt.json
  data\exports\distribution_manifest.json

The generated distribution manifest records source snapshot freshness plus the
SHA-256 digest, byte count, and validation state for each core workbook and
the nonprivate latest-attempt record. portable_source_manifest.json is not an
authoritative live-repository file; it is generated only inside portable
source release output.
The explicit `approved-enrichment` profile adds only filtered normalized
producer-approved workbooks and approved_enrichment_manifest.json. That
manifest binds the approval schema, snapshot/validation timestamp, hashes,
byte counts, row counts, and provenance columns. Verification re-runs the row
gates. Missing optional sources produce a verified core_only fallback.

Build either profile from PowerShell:
  .\Build Shareable AUSL App.ps1 -DistributionProfile core
  .\Build Shareable AUSL App.ps1 -DistributionProfile approved-enrichment

Both profiles exclude raw/review/debug material, PDFs, manual notes, lineup
locks, producer game packets, private sessions, logs, credentials,
environment files, caches, and temporary output. Never add data\manual or
data\exports\game_packets to a package intended for distribution.

DIAGNOSTIC LOGS
GUI and standalone database refreshes write rotating JSON-lines diagnostics to:
  %LOCALAPPDATA%\AUSL Broadcast Stats\logs\ausl_broadcast_stats.jsonl
Logs contain source names, timestamps, row counts, validation/fallback status,
and useful error summaries. Producer-note text, lineup content, clipboard text,
and credential-like fields are deliberately excluded.

OFFLINE TESTING
After first-time setup, run from the project folder:
  .venv\Scripts\python.exe -W error -m pytest -q

Also verify the checked-in distributable snapshot:
  .venv\Scripts\python.exe tools\verify_distribution.py data\exports

Verify an explicitly staged approved profile with:
  .venv\Scripts\python.exe tools\verify_distribution.py --profile approved-enrichment path\to\data\exports

The pytest suite blocks live network access and uses small checked-in fixtures.
GitHub Actions runs the same offline suite on Python 3.12 for Windows and
Linux, checks Git LFS workbook content, runs pip check and compileall, and
verifies the checked-in distribution. Run syntax checks locally with:
  .venv\Scripts\python.exe -m compileall -q src tests tools

Broadcast reminder: imported and live feed values should be verified against
the official game book before being aired.

SSL / UPDATE NOTE
The packaged app includes a current trusted certificate bundle for official
AUSL data downloads. If a shared copy reports that an SSL certificate has
expired, rebuild the ZIP with "Build Shareable AUSL App.bat" and replace the
older copy on that computer.
