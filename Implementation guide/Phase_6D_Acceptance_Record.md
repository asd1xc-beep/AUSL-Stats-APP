# Phase 6D acceptance — Session persistence and crash recovery

Completion date: 2026-07-28

Branch: `agent/phase6d-session-recovery`

Starting commit: `e9e65dc5dd6363749ff08d0a88483e3bd23c1dcd`
Functional commits: `0b2816f`, `f19ffda`

## Accepted behavior

Phase 6D implements only `UX-008`. Phase 6E What Changed and Phase 6F search
and comparison work have not started.

The producer session uses schema version 1 and JSON primitives only. It
retains:

- exact official game ID, season, away team, and home team;
- all exact-game Phase 6C rundown states;
- canonical pinned facts and used-on-air history, including stable fact IDs,
  evidence hashes, wording, provenance, warning/trust/reconciliation state,
  queue order, targets, and timezone-aware timestamps;
- Game Day subview and fact filters;
- one exact uniquely resolved player identity;
- normalized fact-card and rundown scroll positions;
- an informational record that Offline Mode had been enabled.

It does not restore or serialize clipboard/copy events, Tk widgets, callbacks,
threads, timers, locks, credentials, network responses, live state, or enabled
Offline Mode.

## Storage, atomicity, and privacy

The default Windows directory is:

```text
%LOCALAPPDATA%\AUSL Broadcast Stats
```

POSIX uses `XDG_STATE_HOME` or `~/.local/state`. The root is injectable for
tests and smoke harnesses.

`producer_session.json` is deterministic UTF-8/LF. One store lock and
monotonic generation serialize saves. Each save writes a same-directory owned
temporary file, flushes and fsyncs it, preserves the prior validated current
file as `producer_session.backup.json`, then uses atomic replacement. A failed
replacement leaves the current bytes identical. Success, failure, and
supersession clean only the store's own temp-name pattern.

Corrupt, invalid UTF-8/JSON, oversized, malformed, or future-schema state fails
closed. Original bytes are copied to an exclusive timestamped quarantine file.
A valid backup can be loaded; otherwise startup continues empty with a visible
warning. Start Fresh first creates an exclusive validated recovery archive and
does not clear runtime state if that archive fails.

Session names are ignored by Git and explicitly rejected by
`tools/verify_distribution.py`, including backup and Start Fresh archives.
Structured logs record only event/error type/generation, never producer fact
wording or private note content.

## Autosave and lifecycle

One 500 ms Tk `after` debounce covers exact-game changes, pin/use/order/remove,
break target, reconciliation/replace, Game Day views and filters, selected
player, and normalized scroll. A replacement change cancels the one owned
timer, and generation checks make late callbacks harmless. The main thread
captures and writes the small snapshot; session handling creates no worker or
network access.

Status text distinguishes `Saving session…`, `Session saved`, and persistent
`SESSION NOT SAVED`. Save failure contributes a readiness workflow warning
without changing source-health truth. Shutdown cancels the debounce and
synchronously flushes `closed_cleanly`. A persisted `active` state is
classified as crash recovery on the next launch.

## Restore and reconciliation

Restore requires one installed official schedule row whose game ID, season,
away code, and home code all match. It never falls back by date, opponent, or
label. A mismatch remains a blocking recovery issue, suppresses automatic
autosave of the default-game guess, and preserves the saved identity through a
clean close until the producer explicitly selects a game or starts fresh.

Rundown state is reconstructed as canonical typed facts and passed through
Phase 6C reconciliation after the current fact collection is built. Exact used
versions remain the versions actually aired. Player restore requires exactly
one roster identity. Scroll restoration runs only after Tk layout. Offline
Mode always starts disabled.

The Game Day recovery notice provides:

- **Review** — opens the recovered Rundown;
- **Dismiss** — hides the notice without clearing recovered state;
- **Start Fresh** — confirms, archives, clears working state, and immediately
  saves a new active session.

## Failing-first evidence

1. The initial schema/storage command failed with two collection errors:
   `ModuleNotFoundError: No module named 'ausl_session'`.
2. The UI/readiness slice failed 13 tests because no persistence controller,
   restore hooks, or readiness input existed.
3. The adversarial invariant/privacy slice failed five tests for rundown
   timestamp/membership validation, corrupt-current backup archive, and three
   producer-session distribution filenames.

Each slice passed after its corresponding narrow implementation. No assertion
was weakened to permit ambiguous identity or unsafe writes.

## Verification

- Clean baseline: **611 passed in 19.63 s**.
- Phase 6D/adjacent focused matrix: **149 passed in 4.26 s**.
- Complete offline suite with warnings as errors:
  **654 passed in 21.54 s**.
- `python -m compileall -q src tests tools`: passed.
- `python -m pip check`: no broken requirements.
- `python tools/verify_distribution.py data/exports`: passed against the
  checked-in real Git LFS workbooks.
- `git diff --check`: passed.
- Git LFS pointer/materialization validation: passed.
- Tracked filename/content and repository-history secret scans: passed.

## Windows GUI smoke

`tools/phase6d_gui_smoke.py` passed on
`Windows-10-10.0.19045-SP0`, Python 3.12.10, real Tk source execution at
1120×720, using the checked-in local snapshot and an isolated temporary
private state directory.

It exercised clean first launch, meaningful game/player/rundown/use/filter/
view/scroll state, active save, normal close, clean resume, exact restoration,
Offline Mode remaining off, no restored fact-copy event, all seven tabs,
deliberate unclean termination, recovered-session notice, Review, current fact
reconciliation, injected disk-full save failure, readiness warning, validated
archive, Start Fresh, and normal close. Network routes were replaced with
failing sentinels; calls observed: zero.

A separate Windows graphics-capture inspection was attempted. The Computer
Use helper returned `SetIsBorderRequired failed: No such interface supported
(0x80004002)` twice, so no screenshot coordinates were guessed. The real-Tk
smoke's widget mapping, text/state, and interaction assertions passed.

## Remaining limitations

- Persistence is intentionally local and single-user; there is no cloud/shared
  queue, multi-process merge, or cross-machine synchronization.
- One validated backup plus timestamped quarantine/Start Fresh archives are
  retained; there is no archive-management UI.
- Source-data atomic refresh and producer-session atomic save remain separate
  transactions by design.
- Phase 6E and 6F are deferred.
- The existing cooperative `urllib` cancellation limitation is unchanged and
  unrelated to session persistence.

Verdict: **PHASE 6D COMPLETE**.
