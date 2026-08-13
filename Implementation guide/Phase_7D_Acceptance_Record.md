# Phase 7D Acceptance Record

Status: **PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED**

## Baseline, branch, and owner review

- Starting remote `main`: `5996ef1f1a959f0c3c28f93d1fb1360f4c40111b`
  (merged Phase 7C PR #15).
- Clean starting suite: **933 passed** with warnings treated as errors. This is
  one more than the older Phase 7C acceptance record because the merged
  Windows session-quarantine collision regression is included.
- Branch: `agent/phase7d-college-resume-ui`.
- Implementation commits:
  - `7f07bde` — tamper-evident project-owner review transaction;
  - `0c6a4c0` — approved loader and pure presentation models;
  - `b8858fb` — ninth-tab producer workflow, copy, session, and Tk smoke;
  - `60bee5b` — approved-college distribution and privacy verification.
- Project-owner report recorded for 2026-08-11: all ten exact pilot players
  and displayed pilot facts were reviewed, looked correct, and Phase 7D was
  authorized. The neutral reviewer role is `project_owner`; this record does
  not claim a personal AUSL producer review or publish a personal name.
- The project-owner reported on 2026-08-12 that the Phase 7D Windows scaling test
  passed at 100%, 125%, and 150%. This closes the owner-only scaling gate. No
  hardware, package variant, interaction detail, or personal AUSL producer
  review beyond the supplied report is inferred here.

## Approval transaction and checked-in artifacts

The immutable Phase 7C pilot remains at
`data/college_pilot/pilot_envelope.json`. Its SHA-256 is
`d8c111e7762bf96e81ccd6844230123e31cfbab780f92d40d5aa695ccfdb3442`.
The Phase 7D transaction binds that exact hash, schema name/version,
`CORE_RESUME_V1`, the ten canonical AUSL IDs, every résumé and candidate ID,
review role/date/decision/scope, and deliberately incomplete fields.

Producer-visible artifacts:

- `college_resume_envelope.json` — SHA-256
  `36da267aed5bf12e40e5e923100ecbaf4811a896a523a6f476f80d4612b78b4a`;
- `college_approval_manifest.json` — SHA-256
  `c3adebfc0b7e7060280eb4c666498c8028c82809d2711eb5a71812a2a0d959fc`;
- `college_approval_summary.txt` — SHA-256
  `f5837dc45644e094975541f465c0afe1a28e0b04f8cae21c29d299057d02e5e7`.

The derived result is nine `Verified` résumés and one `Partial` résumé.
Ailana Agbayani's achievements and incomplete pitching scope remain
unavailable/Partial; no missing value was converted to zero.

## Loading, presentation, and copy policy

- `CORE_ONLY` loads no college data and presents a calm unavailable state.
- `PRODUCER_APPROVED` requires the matching envelope and approval manifest,
  exact hashes/IDs/candidates, Phase 7B validation, and owner-review fields.
- `DEVELOPER_REVIEW` is visibly `NOT AIR READY` and cannot copy producer text.
- Invalid producer data fails closed; it never falls back to the pilot. An
  already validated in-memory college snapshot remains last-known-good after
  a failed replacement.
- Pure view models resolve selected candidates before Tk renders them.
  Batting and pitching, season and career, source-reported and derived values,
  and program scopes remain separate. Canonical outs format softball innings;
  missing renders unavailable rather than zero.
- Copy eligibility is field-specific. Every copied statistic says `COLLEGE
  CAREER` or the exact college season and includes its school/program. Source
  copy includes exact official provenance and the 2026-08-11 review date.
  Blocked copy leaves the clipboard unchanged. College copies do not mutate
  professional fact-copy or `current_broadcast_note` state.

## Producer UI and workflow

The app now has nine main tabs, with a separate `College Résumé` tab. It uses
the canonical `selected_player_id` and adds an exact Player Lookup handoff plus
a route back. Supported sections are Snapshot, ordered school/transfer
timeline, college career and season records, honors/records/WCWS/championship
context, restrained no-reviewed-connections state, and sources/completeness.
Empty sections collapse. Mouse-wheel and keyboard scrolling are bound to the
scrollable content at the 1120×720 minimum.

Initial load and Quick/Full Refresh workers revalidate local approved college
artifacts after professional data work finishes. Neither refresh fetches,
imports, approves, or rewrites college sources. Local/Offline Mode retains the
installed approved college snapshot. Session schema v3 already supports the
generic active-tab label and exact selected player ID, so no schema bump was
needed; rendered/copy/evidence objects are not persisted.

## Distribution and isolation boundary

The default `core` profile remains unchanged and contains no college data.
Only `approved-enrichment` may add the validated envelope and matching
manifest, both recorded in its deterministic manifest. Verification repeats
the Phase 7B and approval-transaction checks, hashes, exact ten-ID/candidate
coverage, and rejects developer-review/staging artifacts. College data remains
absent from Game Day facts, rundowns, used-on-air history, Producer Prep,
packets, Compare Players, What Changed, live data, and professional graphics.

## Failing-first evidence

The initial Phase 7D focused run failed during collection because
`ausl_college_approval`, `ausl_college_store`, and `ausl_college_view` did not
exist. Subsequent red/green work added exact regressions for input/hash/player
tampering, mode boundaries, last-known-good behavior, copy preservation,
explicit scope labels, nine-tab navigation, session isolation, distribution
tampering, and deterministic ZIPs. A legacy callback fixture then exposed a
missing-store compatibility path; the worker now reloads college data only
when a store is configured, while real application instances always configure
one.

## Verification

- Phase 7D focused contract: **38 passed in 3.85 s**.
- Phase 7B/7C college regressions: **79 passed in 4.70 s**.
- Phase 7A enrichment/distribution regressions: **79 passed in 4.90 s**.
- Session/search/copy/refresh/privacy regressions: **276 passed in 18.97 s**.
- Complete clean offline suite with warnings as errors: **971 passed in
  40.57 s**.
- Offline real-Tk smoke: passed on Windows at 1120×720 with Python 3.12.10 and
  Tk 8.6.15. It covered all nine tabs, Player Lookup handoff, hitter, pitcher,
  two-way, transfer, Partial, nonpilot unavailable, approved/source copy,
  blocked-copy clipboard preservation, mouse/keyboard scroll, local Quick
  Refresh, Local/Offline Mode, rapid selection, and session restore. All
  external network routes were blocked.
- `compileall` passed and `pip check` reported no broken requirements.
- Core distribution verification passed. Two independently staged and
  verified approved-enrichment distributions produced byte-identical ZIPs,
  SHA-256
  `57cf838cb618317a4902462aaf1effa6c216fa7143499d04cbd4042168494c72`.
- Git LFS lists four real XLSX payloads. Their hashes are unchanged from the
  starting commit: roster `fa7e390b...7840`, season `f4aa966c...8caa`, career
  `c2cfb23f...3773`, and team context `45e60f70...9eb` (full values retained
  in the completion report).
- Git whitespace validation and tracked/history high-confidence secret and
  private-path scans passed with zero matches.

## Remaining limitations and Phase 7E boundary

- The reviewed producer surface intentionally contains ten players only.
- No college Broadcast Connections are generated in Phase 7D.
- Windows display scaling at 100%, 125%, and 150% was reported passed by the
  project owner on 2026-08-12; it remains an owner-reported manual result, not
  an automated assertion.
- `COLLEGE-007` remains incomplete. `COLLEGE-008` remains deferred pending
  later producer evaluation.
- The scaling acceptance gate is closed and Phase 7E is authorized.

**PHASE 7D ACCEPTED — PHASE 7E AUTHORIZED**
