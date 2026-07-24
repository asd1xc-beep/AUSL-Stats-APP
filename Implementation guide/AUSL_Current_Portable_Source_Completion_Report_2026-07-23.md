# AUSL Broadcast Stats — Current Portable Source Completion Report

Date: 2026-07-23  
Branch: `codex/phase-4-official-storylines`  
Base Git commit: `a6d0324`  
Package state: includes the reviewed July 23 working-tree refresh and provenance changes

## Outcome

The portable source package contains the current Tkinter application, complete
offline test suite and fixtures, packaging/verification tools, pinned
requirements, Windows setup/build/launch scripts, project documentation, and
the validated core AUSL data snapshot.

The official core refresh completed with optional enrichment disabled. Its
manifest timestamp is `2026-07-23T18:08:06.854069+00:00`, and it retains the
season-pitching WHIP policy:

```text
(hitsAllowed + baseOnBalls) * 3 / innings_outs
```

The imported value remains available as `source_whip` for audit only. Missing,
malformed, negative, or zero-inning inputs make the published value
unavailable rather than falling back to an imported value or factual zero.

## Snapshot validation

- 2025 roster: 63 unique player IDs.
- 2026 roster: 118 unique player IDs.
- Official standings: 18 unique authoritative keys.
- Official schedule: 76 unique game IDs with parseable dates and valid
  opponents.
- Schedule states: 75 completed and one postponed.
- No official game IDs were added or removed relative to the recoverable prior
  snapshot.
- Jala Wright (`player_id` 1308) is retained exactly as `Reserve Pool` with no
  inferred team.
- Emiley Kennedy (`player_id` 1097) is absent from the current official roster;
  the application does not infer a replacement identity or active status.

## Test evidence

- Refresh safeguards before promotion: 11 passed.
- Final snapshot/refresh/standings/status/WHIP suite: 53 passed.
- Complete offline regression: 392 passed in 9.91 seconds.
- Complete regression with warnings treated as errors: 392 passed in 9.73
  seconds.
- `compileall`: passed.
- `pip check`: no broken requirements.
- Automated tests remain offline and do not depend on live internet access.

## Windows/Tkinter smoke evidence

The source application opened all six tabs and loaded the final 118-player
snapshot. It displayed July 23 freshness plus `VERIFY BEFORE AIR`, retained
exact official Game 987, showed Carolina 9-16 in Team Totals and Oklahoma City
13-12 / Carolina 9-16 in Producer Prep, kept lineup and manual-note stores
empty, and left live data unloaded.

Jala Wright's card rendered `Reserve Pool`, `TEAM UNKNOWN`, and a visible
availability warning. No manual note, lineup lock, producer packet, optional
enrichment, or live-game request was written or sent.

## Portable-source safety

The package includes only the validated core export allowlist:

```text
data/exports/ausl_rosters.xlsx
data/exports/ausl_season_stats.xlsx
data/exports/ausl_career_stats.xlsx
data/exports/ausl_team_context.xlsx
data/exports/update_manifest.json
data/exports/distribution_manifest.json
```

It excludes environments, build products, prior distributions, backups,
caches, bytecode, logs, `data/manual`, producer packets, personal notes,
lineup locks, source PDFs, credentials, and unverified enrichment workbooks.

## Remaining limitations

- This is a dated official-source snapshot, not a guarantee that facts remain
  current. Run the guarded core refresh and repeat verification shortly before
  the producer demonstration when the official source is healthy.
- Eight media-guide identities remain review-only.
- Target-truck scaling and producer rehearsal/sign-off remain pending.
- This package supports a controlled producer demonstration; it does not claim
  unattended live-broadcast readiness or Gate C completion.
