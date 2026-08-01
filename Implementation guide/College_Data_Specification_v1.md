# College Data Specification v1

## Purpose and non-goals

This document defines the Phase 7B normalized, provenance-first foundation for
future college résumés. The governing rule is that wrong-on-air is worse than
unavailable. This version does not collect production college data, add a
College Résumé UI, create Broadcast Facts, or change refresh and distribution
behavior.

The declared completeness profile is `CORE_RESUME_V1`. It is a contract, not a
claim that every athlete has every possible college field.

## Entity relationship overview

One résumé is anchored by a stable AUSL `player_id`. It contains reviewed
identity mappings, programs, ordered program stints, independent statistical
records, achievements, and explicit section states. A separate source catalog
contains evidence records. Every displayable scalar refers to its own source;
document-level trust is never inherited by unrelated fields.

```text
CollegeEnvelope
  +-- SourceProvenance[]
  +-- CollegeResume[] -- stable AUSL player_id
        +-- IdentityMapping[]
        +-- Program[] -- ProgramStint[]
        +-- StatRecord[] -- CandidateValue[]
        +-- Achievement[]
        +-- section_statuses
```

## Identity, programs, and transfers

Display-name similarity is never identity proof. Each reviewed mapping retains
the AUSL ID, source athlete ID, explicit aliases, source ID, reviewer, approval
time, and evidence reference. Similar names remain separate records.

Programs use stable IDs, official display names, source-specific identifiers,
and explicitly sourced historical names. Stints retain transfer order and may
have unknown start or end seasons. Unknown dates require an uncertainty note;
the model never guesses. Redshirt, shortened, extra-eligibility, standard, and
unknown season kinds are explicit. Overlap is retained for review rather than
automatically discarded.

## Roles and statistical records

Hitter, pitcher, and two-way roles are supported. Batting and pitching are
independent records, including for a two-way player or a player whose role
changes by stint.

Record types are season batting, season pitching, source-reported career
batting, source-reported career pitching, safely derived career batting, and
safely derived career pitching. A source-reported total is never replaced by a
derived career total.

Counting metrics are exact integers. Rates use finite `Decimal` values and are
serialized as exact decimal strings. Pitching workload uses canonical outs;
`.1` means one out and `.2` means two outs, never decimal tenths.
`NaN`, infinity, binary floats, and malformed innings are rejected.

Missing is never zero. The value states `present`, `missing`, `unavailable`,
`not_applicable`, and `unresolved_conflict` preserve the distinction between
missing data, explicit sourced zero, and a value that cannot safely be chosen.

Career derivation requires a declared complete season scope, verified source
IDs, compatible player/role/record definitions, present component values, and
no conflicting candidates. Rates are not combined without canonical
denominators. Unsafe aggregation returns unavailable.

## Achievements

Normalized achievement types cover honors, records, conference and national
awards, WCWS appearances/results, championships, and other postseason results.
Each record distinguishes team from individual scope, retains program and
season/date where known, and may preserve source wording alongside a normalized
label.

## Source hierarchy and field-level provenance

The preference order is official AUSL profile, NCAA statistics, official school
athletics material, then explicitly manually verified evidence. Preference
breaks ties only for equivalent candidates with identical identity, scope,
season, record type, metric definition, and unit. It never overwrites a
material conflict.

Each source records organization, title, canonical URL or local document ID,
locator, source season/effective date, UTC retrieval time, parser/manual-entry
version, optional normalized hash, verification state, reviewer, approval time,
and review note. A manual source is verified only with reviewer, approval time,
reason, and an evidence reference.

## Candidate values and conflict resolution

All candidates and candidate-specific provenance remain in the model. The pure
resolver returns a structured state, selected candidate when safe, rejected
candidate IDs, deterministic reason, and optional manual resolution evidence.
Equivalent compatible candidates resolve by source preference and stable ID.
Different dimensions are `incompatible`, not competing values. Different
values in the same dimensions are `conflicting` and have no selected value.
Manual resolution requires a selected candidate, reviewer, UTC time, reason,
and verified evidence source; rejected evidence remains auditable.

## Completeness rubric

`CORE_RESUME_V1` accounts for identity, programs, statistics, and achievements.

- `Verified`: exact reviewed identity; verified core identity/program fields;
  every applicable section accounted for; displayable values have field-level
  provenance; no blocking conflict.
- `Partial`: safe identity and at least one useful verified section, with
  nonblocking unavailable sections listed as machine-readable missing fields.
- `Needs Review`: ambiguous identity, conflicting source athlete IDs,
  unresolved material conflict, missing selected-value provenance, invalid
  approval, incompatible definitions, or malformed/unsupported schema data.

Completeness output includes blocking reasons and missing-field paths. The
résumé label does not replace candidate or provenance verification states.

## Deterministic storage and validation

The wire format is UTF-8 JSON with schema name `ausl-college-resume`, version
`1`, UTC generation timestamp, `CORE_RESUME_V1`, sorted source and résumé
records, and validation metadata. Serialization uses stable keys, compact
separators, LF termination, exact decimal text, and rejects nonfinite values.
Load/serialize/load round trips preserve supported records.

Unknown, missing, unversioned, malformed, oversized, excessively nested, or
future-version input fails closed with actionable diagnostics. Version 1 is a
no-op current-version boundary; no fictional legacy production migration is
claimed. Validation reports errors, warnings, counts, duplicate IDs,
unresolved identities, missing provenance, conflicts, malformed values,
unsupported metrics, completeness totals, and records safe for pilot review.

The developer-only command is:

```powershell
python tools/validate_college_data.py <explicit-json-path>
```

It is offline, never approves data, and is not called at producer startup.

## Phase 7C importer contract

The Phase 7C importer must produce this exact versioned envelope from explicitly
selected official evidence. It must anchor to an existing AUSL `player_id`,
create candidate-specific provenance, preserve raw conflicts, use canonical
outs and exact decimals, declare expected seasons/sections, run validation, and
write only to a developer-review destination. It must not load into the app,
promote approval, or package data until a separate later-phase review accepts
the pilot.

College totals and AUSL totals are separate statistical scopes. Importers,
formatters, and future UI code must label them independently and may never add,
merge, or substitute one for the other.
