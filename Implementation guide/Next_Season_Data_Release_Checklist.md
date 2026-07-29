# Next Season Data Release Checklist

Use this checklist as soon as the new season data begins to appear ahead of preseason. The goal is to catch schema or source changes early before they break imports or refreshes.

## 1. Confirm the season mapping
- [ ] Update the season map with the new season id and any new year-specific identifiers.
- [ ] Confirm the current season, previous season, and any fallback season values are still correct.
- [ ] Check whether the app expects a different season label or naming convention.

## 2. Check the source endpoints and files
- [ ] Verify the roster/stat source URL or endpoint still works.
- [ ] Verify the media-guide source URL or file pattern still works.
- [ ] Confirm the expected CSV/JSON/Excel/PDF filenames or download patterns have not changed.
- [ ] Note any new authentication, access, or rate-limit requirements.

## 3. Validate the incoming data schema
- [ ] Open a sample file and confirm column names are still present.
- [ ] Check for renamed columns, added columns, or removed columns.
- [ ] Confirm player/team identifiers still match the app’s expected keys.
- [ ] Check whether dates, game ids, season ids, or status fields have changed format.

## 4. Review roster and player identity fields
- [ ] Verify player names still match expected formatting.
- [ ] Confirm player ids or roster ids are still unique and stable.
- [ ] Check whether team abbreviations or names changed.
- [ ] Verify any roster-merge or deduplication logic still behaves correctly.

## 5. Review media-guide and enrichment inputs
- [ ] Confirm the media-guide note fields still exist.
- [ ] Check whether source labels or guide-year naming changed.
- [ ] Verify team or player context note fields still populate correctly.
- [ ] Review any enrichment fields that depend on external content.
- [ ] Revalidate exact TOC identity, printed/PDF page offset, guide date,
      parser version, warnings, and approval-record hashing for the new guide.
- [ ] Confirm official game-note rows still carry exact game/player/team/
      opponent identity, source document/page/date, parser version, normalized
      content hash, reviewer, and approval timestamp before producer promotion.
- [ ] Review the centralized split policy for the new competition format.
      Do not change the 12-PA/9-out defaults without producer acceptance and
      new regression evidence.

## 6. Validate the refresh and import pipeline
- [ ] Run a full refresh or import test with the latest sample data.
- [ ] Run Quick Refresh and confirm it does not fetch/rewrite optional sources
      while still reloading validated local PRODUCER_APPROVED rows.
- [ ] Cancel Full Enrichment Refresh while blocked, queue a replacement, and
      confirm one coherent final core/optional/manifest snapshot.
- [ ] Confirm the app still builds season and career stats correctly.
- [ ] Verify manual notes, snapshots, and lineage data are not overwritten incorrectly.
- [ ] Check export files or packaged outputs for missing or malformed data.
- [ ] Build and verify both `core` and explicit `approved-enrichment`
      distribution profiles. Confirm raw/review/debug/private files remain
      excluded and the approved manifest hashes/counts match.

## 7. Check UI and display behavior
- [ ] Verify labels, source names, and season text still render correctly.
- [ ] Confirm any producer-prep or note-display views still show the right content.
- [ ] Check for broken sorting, filtering, or empty-state displays.

## 8. Regression and smoke testing
- [ ] Re-run import-focused regression tests.
- [ ] Re-run any data quality or enrichment tests.
- [ ] Exercise CORE_ONLY, PRODUCER_APPROVED, and DEVELOPER_REVIEW load modes;
      confirm developer review rows cannot become air-ready.
- [ ] Compare a small sample of imported rows against the upstream source.
- [ ] Record any unexpected differences or missing values.

## 9. Document changes for the season
- [ ] Capture any schema changes in a short change log.
- [ ] Note which fields required code updates or data mapping changes.
- [ ] Keep a copy of the first successful import sample for comparison.
