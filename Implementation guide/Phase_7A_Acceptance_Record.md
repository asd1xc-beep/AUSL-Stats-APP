# Phase 7A Acceptance Record

Acceptance date: 2026-07-29

Status: **PHASE 7A COMPLETE — PHASE 7B NOT STARTED**

## Baseline and branch

- Starting remote `main`:
  `08fd7f09f24a53f3270516c51e6667e9daa35538`.
- Branch: `agent/phase7a-producer-enrichment`.
- Clean baseline: **769 passed** with warnings treated as errors;
  `compileall`, `pip check`, and core distribution verification passed.
- Reviewed implementation commits:
  - `c23ab52` — typed enrichment modes, split policy, approval/load gates,
    serialized refresh transaction, producer UI, and regressions.
  - `8a34785` — explicit approved distribution profile, deterministic ZIP,
    verifier, build integration, and privacy regressions.
  - `85b0db9` — deterministic Windows/real-Tk Phase 7A smoke.
- The documentation acceptance commit and final branch tip are recorded in
  the PR and completion report because a commit cannot contain its own hash.

## Split reliability policy

- One GUI-free policy in `src/ausl_splits.py` is used by producer lookup and
  canonical facts.
- Normalized exact `regularSeason` aggregate identities are excluded without
  substring overmatching.
- Default hitter threshold: **12 plate appearances**.
- Default pitcher threshold: **9 outs**, using canonical baseball-innings
  conversion.
- Valid detailed rows below the threshold remain visible as
  `SMALL SAMPLE`, but are never air-ready.
- Missing, malformed, negative, fractional count, or nonfinite sample evidence
  fails closed.

## Typed enrichment modes

- `CORE_ONLY` loads no optional workbook.
- `PRODUCER_APPROVED` is the ordinary startup, Quick Refresh reload, Full
  Enrichment Refresh completion, Local/Offline Mode, session, and packaged-app
  path. It loads only rows that pass the complete producer gates.
- `DEVELOPER_REVIEW` retains raw/review access for development and can never
  make review data air-ready merely by setting a Boolean.
- The legacy `include_enrichment=True` loader argument maps explicitly to
  `DEVELOPER_REVIEW`; it is not a producer approval shortcut.

## Approval and trust gates

- Media-guide rows require exact entity/roster identity, exact TOC mapping,
  printed/PDF pages, guide date, source reference, parser/match evidence,
  internally consistent approval record, and no unresolved warning.
  `not_in_guide` remains absent.
- Official game notes require exact game/player/team/opponent identity,
  document URL/name, page, date, parser version, normalized content hash,
  reviewer, approval timestamp, and an evidence-bound approval record.
- Source health is independent from row approval. Green may be air-ready;
  yellow is stale; red or unknown is unavailable.
- The load boundary filters producer rows and the canonical fact adapter checks
  the producer markers again. Projected or review-only content is not promoted.

## Refresh and last-known-good behavior

- The top bar retains `Quick Refresh (Core)` and adds the deliberate,
  explained `Full Enrichment Refresh`.
- One process-local refresh lock serializes Quick and Full jobs before network
  or staging work. The existing commit lock then serializes the complete
  core-plus-successful-optional promotion.
- Cancellation is rechecked after a queued job acquires the lock. A cancelled
  job cannot start writing; a job already in commit may finish atomically.
- Core and every successful optional workbook are staged and promoted in the
  same rollback-capable transaction. A failed optional source retains its
  last-known-good workbook and records yellow/red source health.
- Quick Refresh does not fetch or rewrite optional sources; it preserves their
  health and reloads validated local producer-approved rows.
- Offline Mode blocks Full Refresh before confirmation, token creation, or
  worker startup. Late callbacks remain token-gated and harmless.

## Distribution boundary

- Default profile: `core`, unchanged and fail-closed.
- Explicit profile: `approved-enrichment`.
- The explicit profile contains core exports plus only filtered normalized
  producer workbooks and `approved_enrichment_manifest.json`.
- The approval manifest uses deterministic UTF-8/LF and records the approval
  schema, source snapshot/validation timestamp, hashes, byte counts, row
  counts, and provenance columns.
- The verifier re-runs row gates and rejects injected/unapproved rows,
  hash/count mismatches, raw/review/debug artifacts, private notes, lineups,
  sessions, packets, caches, PDFs, credentials, and environment files.
- ZIP member paths, timestamps, permissions, ordering, and bytes are
  deterministic and portable.
- Missing optional sources produce a verified `core_only` fallback inside the
  explicit profile rather than breaking the core application.

## Failing-first evidence

- Split and typed-mode tests first failed collection because
  `ausl_splits` and `ausl_enrichment` did not exist.
- Producer refresh tests then failed because no ordinary Full Enrichment
  action or shared button gate existed.
- Distribution tests first failed because the profile builder did not exist
  and the ZIP inherited source mtimes.
- Documentation tests first failed all six assertions before these acceptance
  records and status updates existed.

## Verification

- Phase 7A focused split/mode/refresh/distribution/ZIP tests:
  **76 passed in 6.01 s**.
- Complete offline suite with warnings as errors:
  **847 passed**.
- `compileall`: passed.
- `pip check`: no broken requirements.
- Checked-in core distribution verification: passed.
- Synthetic approved-enrichment directory and ZIP verification: passed,
  including injected-row and privacy-negative tests.
- Git whitespace, LFS payload, tracked-file secret, history secret, and
  private-data scans: passed.

## GUI smoke

- Platform: `Windows-10-10.0.19045-SP0`, Python 3.12.10.
- App type: Windows source app, real Tk loop, offline hand-auditable fixtures.
- Window: 1120×720.
- Six verified optional facts covered both selected-game teams.
- Full Refresh was started, cancelled while blocked, and followed immediately
  by a queued Core Refresh. The final installed database and fact collection
  used `phase7a-smoke-replacement`; no stale/duplicate dialog appeared.
- Local/Offline Mode retained local facts, all eight tabs opened, and
  **network calls: 0**.

## Remaining limitations and deferrals

- The public repository intentionally contains only the validated core
  snapshot. Producer-approved optional rows appear after a successful Full
  Enrichment Refresh or in an explicit approved-enrichment package.
- Downloaded official-note parser rows remain review-only until a producer
  completes the evidence-bound approval transaction; refresh never
  auto-approves them.
- Split thresholds are centralized and configurable in code but do not yet
  have producer UI settings.
- Automated tests and the acceptance smoke are network-independent; they do
  not claim that every live upstream document is currently available.
- College schema, collection, pilot, UI, scaling, and broadcast connections
  are deferred. **Phase 7B has not started.**
