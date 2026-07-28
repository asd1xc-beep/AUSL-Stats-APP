AUSL BROADCAST STATS LOOKUP

This is the standalone AUSL softball broadcast tool project. It is separated
from the NFL_STATS_DATABASE project, so changes here do not modify or replace
the NFL application.

CURRENT READINESS
Phases 1-5, Phase 6A, and Phase 6B are complete. Phase 6B's reviewed
functional commits are b2a8f30 (canonical fact model and source adapters),
d7994ad (Game Day cards and synchronization), eda0bfd (canonical roster-status
reuse), 5febe19 (copy provenance and 60/120-character guidance), and 919254e
(minimum-size fact-card layout and deterministic GUI smoke). Phase 6B started
from the completed Phase 6A head e87b4d7; at that time Phase 6A remained open
as draft PR #4 and remote main remained 19f2702, so Phase 6B is a stacked
branch rather than a claim that unmerged work is on main.

The complete offline suite passes 557 tests with warnings treated as errors;
the 357-test Phase 6B/adjacent safety matrix also passes. The deterministic
Windows source-app smoke passes at 1120x720 with a usable scrollable fact
viewport. Compileall, pip check, and checked-in distribution verification pass.
The future-season year-generalization patch remains applied once and its
dedicated regressions pass.

Truck-hardware smoke testing and producer rehearsal are recorded as completed
based on the project owner's report. No hardware model, display scaling,
rehearsal date, or additional observed behavior is asserted here because those
details were not supplied.

Phase 6C through 6F have not started. Phase 6B does not add a pinned rundown,
read-time budgeting, used-on-air state, restart persistence, crash recovery,
change comparison, fuzzy search, or player comparison. This remains an
assisted broadcast tool, not a candidate for unattended on-air use: cards that
do not pass exact identity, provenance, freshness, source-health, and approval
gates stay VERIFY, STALE, or UNAVAILABLE and cannot use ordinary air-line
copy. Cancellation is cooperative while a single urllib request is inside its
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
If you are using the shared ZIP version, unzip the folder and double-click:
  AUSL Broadcast Stats.exe

If you are working from this project/source folder, use:
  Launch AUSL Stats App.bat

SHARING / WINDOWS DEFENDER NOTE
The build script creates two shareable ZIP files:

  dist\AUSL-Broadcast-Stats-Windows.zip
    Standard packaged Windows app. This includes an unsigned .exe, so some
    computers may warn that the publisher is unknown.

  dist\AUSL-Broadcast-Stats-Safer-No-EXE.zip
    Lower-risk package without a bundled .exe. On another computer, unzip it,
    run "Setup AUSL Environment.bat" once, then run "Launch AUSL Stats App.bat."
    This version is less convenient but is usually less likely to be
    auto-quarantined because it avoids the unsigned bundled executable pattern.

The packaged .exe build disables UPX packing and uses an uncompressed ZIP to
reduce false-positive antivirus heuristics. Code signing is still the best
long-term way to reduce unknown-publisher warnings.

Both build paths run tools\verify_distribution.py before and after compression
and write a portable SHA-256 file beside each ZIP. Verify a ZIP with:
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

The normal refresh does not fetch, write, or activate split-stat, media-guide,
official-game-note, or storyline enrichment. A developer-only
include_enrichment=True option exists for isolated validation work; it is not a
producer-facing refresh mode and its rows still require explicit review approval
before any air-ready output may use them.

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

LOCAL/OFFLINE MODE
The visible Local/Offline Mode control appears beside Quick Refresh and in the
Game Day tab. While enabled it blocks core and manual live refreshes, cancels
their existing tokens, stops and prevents live timers, and ignores abandoned
network callbacks. Local search, notes, lineups, packet generation, and copy
actions remain available against the installed last-known-good snapshot.

Offline Mode defaults off on every fresh launch. Turning it off does not start
a refresh or live request; the producer chooses when network activity resumes.

STORYLINE / ENRICHMENT DATA
Optional development refreshes can import official AUSL split stats, the media
guide for the latest configured season, official game notes, and a storyline
source registry for isolated review. These are saved under:
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

The default loader ignores these optional workbooks. Even in explicit
development mode, a row is excluded from air-ready media, split, and game-note
output unless it has an explicit passed review state. Raw page chunks are kept
only for local debugging/search and are excluded from distributable builds.

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
First-milestone distributable builds include only this tested core snapshot
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
Distributable builds exclude media-guide, official-game-note, split-stat, and
storyline enrichment until those later validation gates pass. They also exclude
manual notes, lineup locks, producer game packets, logs, credentials, caches,
and debug-only raw exports. Never add data\manual or
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
