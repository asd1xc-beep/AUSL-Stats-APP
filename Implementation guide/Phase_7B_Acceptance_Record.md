# Phase 7B Acceptance Record

Acceptance date: 2026-08-01

## Baseline and branch

- Starting remote `main`: `d67124b706d77f6ab677b5257a253088e20f5e78`.
- Branch: `agent/phase7b-college-foundation`.
- Clean baseline: **847 passed** with warnings treated as errors.
- Implementation commits: recorded in the final branch/PR handoff because a
  commit cannot contain its own final hash.

## Schema and trust decisions

- `src/ausl_college.py` is GUI-free, network-free, and absent from producer
  startup, refresh, facts, and distributions.
- Stable AUSL player ID is mandatory; names and aliases cannot establish
  identity. Multiple programs, transfers, unusual seasons, and separate
  batting/pitching roles are normalized.
- Integers and exact decimals preserve zero versus missing. Innings use outs.
- Every selected value has candidate-specific provenance. Conflicts and
  rejected alternatives remain present; manual resolution needs complete
  reviewer evidence.
- `CORE_RESUME_V1` returns deterministic `Verified`, `Partial`, or
  `Needs Review` results with blocking reasons and missing-field paths.
- Versioned deterministic UTF-8/LF JSON rejects unknown/future/malformed and
  bounded hostile inputs. The validator operates only on an explicit file.

## Failing-first evidence

- Four model test modules initially failed collection because `ausl_college`
  did not exist.
- Six career/identity/metric tests then failed before complete-scope derivation,
  verified-source gates, source-athlete conflict reporting, and supported-metric
  reporting were implemented.
- Documentation tests failed because the specification and acceptance record
  did not exist.

## Verification

- Phase 7B focused tests: final exact result recorded after acceptance run.
- Full offline suite, compileall, pip check, core and synthetic approved-
  enrichment verification: final exact results recorded after acceptance run.
- Factual XLSX hashes are compared with starting `main`; no factual export is
  part of the Phase 7B commit.

## Boundary and limitations

No production college data was imported. No ten-player pilot, College Résumé UI,
college fact, copy/pin/rundown/packet/comparison integration, startup loader,
network collector, refresh source, or distribution member was added. Phase 7C
must build the reviewed synthetic-to-real importer and ten-player pilot before
any UI work.

**PHASE 7B COMPLETE — PHASE 7C TEN-PLAYER PILOT NOT STARTED**
