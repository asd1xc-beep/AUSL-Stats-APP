# Phase 6 broadcast-fact interface

Phase 6A established this boundary. Phase 6B implements it in
`src/ausl_facts.py` and renders the resulting immutable values in Game Day.
Phase 6C consumes the same immutable values in `src/ausl_rundown.py` for a
pinned rundown, read-time estimate, and used-on-air state. Phase 6D persists
and recovers those exact canonical snapshots through `src/ausl_session.py`;
it does not reconstruct a fact from visible text or weaken reconciliation.

## Required fact input

A broadcast fact is supplied to presentation, copying, and readiness code as
one frozen `BroadcastFact` value. Its contract includes:

```text
fact_id                 stable conceptual/source-record identity
evidence_hash           version of wording, values, provenance, and trust
category                typed supported fact category
selected_game_id        exact official game ID, when game-scoped
subject_type            player | team | game | global
subject_id              exact player/team/game identifier
season/team/opponent    explicit selected-game display context
headline/air_copy       deterministic producer-facing display strings
supporting_context      optional supporting explanation
provenance[]            source/ref/date/page/game/snapshot/parser/approval
verification_state      VERIFIED | VERIFY | STALE | UNAVAILABLE
source_health           green | yellow | red | unknown
warning_reason          concise invalidation/review reason
air_ready               derived property; never independently editable
readiness_blocking      safety relevance, separate from optional context
```

An unavailable, stale, mismatched, or unreviewed fact must remain in that state.
Acknowledgement, pinning, copying, or marking a later item used on air cannot
promote it to verified.

`fact_id` does not depend solely on the rendered sentence. The same conceptual
fact can retain its ID when a numeric value changes, while its `evidence_hash`
changes. Different player/team/game/season/category/source-record identities
cannot collide. Later phases must pin the canonical value and hashes rather
than reparsing visible text.

## Readiness contribution

Phase 6B translates applicable blocking facts into the existing selected-game
verification count. It does not mutate `GameDayReadiness` or store an
independent Ready-for-Air Boolean. A fact may contribute:

- `pass` only with exact identity and authoritative current verification;
- `warning` for usable but stale or explicitly review-required context;
- `fail` for a safety-critical identity/source conflict;
- `unavailable` when the required state cannot be resolved;
- `not-applicable` when the fact is unrelated to the selected game.

Fact checks must be scoped to the exact selected game and its teams/players.
They must be regenerated after a game or database change. Phase 6A's pure
aggregator remains the single owner of overall `READY FOR AIR`,
`NEEDS ATTENTION`, and `NOT READY`.

## Rundown consumption and private session storage

Phase 6C pins the complete canonical fact value, stable fact ID, evidence hash,
provenance, and trust state; it never reconstructs a fact from a label. The
in-memory exact-game state additionally owns dense order, break target, pin
timestamp, reconciliation state, used timestamp/history, and an explicit
schema version for later serialization. Stable fact ID suppresses ordinary
rerenders within the same game while the used evidence hash preserves the
version actually aired.

Phase 6D serializes the complete canonical pinned and used snapshots, stable
fact IDs, evidence hashes, provenance, trust/reconciliation state, exact-game
order, target, and timestamps into versioned primitive-only JSON. Loading
reconstructs the typed models and recalculates fact/version identity; a stored
hash or game mismatch fails closed. Restored pins then pass through Phase 6C's
existing current/changed/downgraded/missing-evidence reconciliation.

The private per-user session also retains exact selected-game identity, safe
Game Day filters/views, one uniquely resolved player identity, and normalized
fact/rundown scroll. It does not persist clipboard/copy events, workers,
timers, locks, credentials, network state, or enabled Offline Mode. Session
files and recovery archives are outside the repository, Git-ignored by name,
and distribution-forbidden. The explicit producer-requested plain-text
rundown export remains separately under the private game-packet directory.
