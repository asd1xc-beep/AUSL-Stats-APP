# Phase 6 broadcast-fact interface

Phase 6A does not create fact cards, a rundown, read-time estimates, used-on-air
state, or session persistence. It establishes only the boundary that later
Phase 6B–6D work must use.

## Required fact input

A future broadcast fact should be supplied to presentation and readiness code
as an immutable value with these fields:

```text
fact_id                 stable identity for this source fact
selected_game_id        exact official game ID, when game-scoped
subject_type            player | team | game | global
subject_id              exact player/team/game identifier
concise_copy            short producer-facing air copy
expanded_context        optional supporting explanation
source_name             human-readable authoritative source
source_id_or_url        stable source identifier or URL
source_timestamp        effective/publication time
retrieved_at            local retrieval time
verification_state      verified | needs-review | stale | unavailable
verification_detail     concise reason for the state
review_record_id        canonical approval record, when required
```

An unavailable, stale, mismatched, or unreviewed fact must remain in that state.
Acknowledgement, pinning, copying, or marking a later item used on air cannot
promote it to verified.

## Readiness contribution

Phase 6B may translate applicable facts into `ReadinessCheck` values, but it
must not mutate `GameDayReadiness` or store an independent Ready-for-Air
Boolean. A fact may contribute:

- `pass` only with exact identity and authoritative current verification;
- `warning` for usable but stale or explicitly review-required context;
- `fail` for a safety-critical identity/source conflict;
- `unavailable` when the required state cannot be resolved;
- `not-applicable` when the fact is unrelated to the selected game.

Fact checks must be scoped to the exact selected game and its teams/players.
They must be regenerated after a game or database change. Phase 6A's pure
aggregator remains the single owner of overall `READY FOR AIR`,
`NEEDS ATTENTION`, and `NOT READY`.

## Deferred storage

Pinned order, read-time budget, used-on-air timestamp, acknowledgement state,
and crash/session recovery belong to Phase 6C/6D. No Phase 6A file schema
silently reserves or persists those fields.
