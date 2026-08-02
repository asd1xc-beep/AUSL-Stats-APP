# Phase 7B Acceptance Record

Acceptance date: 2026-08-01

## Baseline and branch

- Starting remote `main`: `d67124b706d77f6ab677b5257a253088e20f5e78`.
- Branch: `agent/phase7b-college-foundation`.
- Clean baseline: **847 passed** with warnings treated as errors.
- Reviewed implementation commits:
  - `6e80507` — normalized model, provenance/conflict/completeness logic,
    deterministic serialization, validator, and focused tests.
  - `d11ce58` — specification, tracker/guide status, and acceptance contract.
  - `8851456` and `b86d676` — explicit Phase 7C boundary and roadmap-test
    alignment.
- The final evidence-record commit and branch tip are recorded in the PR and
  completion report because a commit cannot contain its own hash.

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

- Phase 7B plus Phase 7A safety/distribution matrix: **116 passed in 5.95 s**.
- Complete clean offline suite with warnings as errors after rebasing onto the
  merged responsiveness fix: **899 passed in 41.73 s**. The original accepted
  Phase 7A baseline was 847; the publish-time `main` baseline was 853.
- Packaging/privacy/portable ZIP matrix: **41 passed in 5.34 s**.
- Synthetic approved-enrichment directory and ZIP verification:
  **6 passed in 3.17 s**.
- `compileall`: passed. `pip check`: no broken requirements.
- Checked-in core distribution: `Clean distribution verified: data\\exports`.
- Git LFS lists all four factual XLSX exports and direct header inspection
  confirmed real ZIP/XLSX bytes rather than pointer text.
- Git whitespace, tracked-file secret, history secret, and private-path scans:
  passed.
- Git object IDs for every checked-in factual XLSX exactly match starting
  `main`; `git diff` reports no `data/exports` change in this branch.
- No UI or startup code changed, so a new scaling/Tk smoke was neither required
  nor performed.

## Boundary and limitations

No production college data was imported. No ten-player pilot, College Résumé UI,
college fact, copy/pin/rundown/packet/comparison integration, startup loader,
network collector, refresh source, or distribution member was added. Phase 7C
must build the reviewed synthetic-to-real importer and ten-player pilot before
any UI work.

**PHASE 7B COMPLETE — PHASE 7C TEN-PLAYER PILOT NOT STARTED**
