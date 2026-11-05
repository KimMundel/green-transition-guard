# Exact replay and checkpoint preflight (experimental v0.1.11)

## Contract

`TransitionGuard.checkpoint_preflight()` obtains the existing POSIX journal
lock, loads and validates the **complete** stored payload, and returns a
detached, read-only preview. No files are written and no historical events,
no-ops, policy epochs or IDs are removed. `green-guard checkpoint-plan --store
<file>` prints its manifest without exposing raw request IDs.

The preview is anchored to `sha256(canonical_bytes(payload))`, matching the
snapshot envelope's accidental-corruption checksum. It contains the complete
revision/policy revision, current state and entered-at time, last accepted
transition timestamp (required for arbitrary future minimum-interval values),
the sealed window ceiling when present, a policy-chain digest, event prefix and
suffix digests and an exact replay index commitment. This report becomes stale
as soon as any journal update occurs, including a no-op or a clock observation.

### Replay identity oracle

A detached `ReplayIndex` maps every accepted transition, accepted no-op, policy
update and one-time window seal ID to its original operation type and exact
parameters. Its query methods report `unknown`, `replay`, or `collision`:

- A transition ID replays only with its original target; the recorded event ID
  is returned. A no-op ID replays only with its original target.
- A policy update ID replays only with its full canonical policy unchanged.
- A window seal ID replays only with its original ceiling unchanged.
- Reusing an ID across operation types always yields a collision.

The oracle covers **identity semantics only**. The actual guard must also
validate its authoritative clock and other request preconditions. The in-memory
index is built from all historical IDs and never substitutes for the original
journal on a subsequent operation. The digest is **not an exact-membership data
structure**: the digest alone cannot answer queries about previously seen IDs.

### Quota prefix

If schema 3 contains a sealed maximum future window `W` and the last observed
clock is `T`, the preview counts the prefix of events where `at_ms <= T - W`.
That prefix is quota-expired under the sealed future policy-window contract.
The event at equality is excluded from the live window `(T-W, T]`. An unsealed
schema 1 or 2 journal reports a zero candidate prefix regardless of its age.

The prefix count **does not authorize deletion**. Old event identities, interval
anchors, policy-epoch proof and durable rollback prevention are independent
requirements. All `journal_compaction_enabled` fields remain `false`.

## Unresolved work before durable compaction

1. Preserve exact historical identities with a verifiable durable ledger or
   conservatively reject ambiguous old IDs. A single 256-bit digest is
   insufficient to perform exact deduplication after deleting the source.
2. Define an authenticated archive/checkpoint root and a monotonic generation
   that survives rollbacks, torn writes and restore of an older schema.
3. Preserve a verifiable state/event/policy epoch chain across a removed prefix;
   retain last-transition and state-entry time plus unexpired event suffix.
4. Bound operation volume or fail closed on saturation, including no-op and
   policy-update IDs, which may grow without accepted transitions.
5. Install any checkpoint and replay ledger crash-consistently; reconcile the
   commit state after ambiguous `fsync`/rename failures before any operation.
6. Obtain trusted clock, hardware and external transition evidence.

## Example

```bash
green-guard checkpoint-plan --store device.guard.json
```

The CLI prints digest/count metadata. The state and device ID are already part
of the simulator's `status()` output; request IDs themselves stay in memory.
The digest is unkeyed and has no confidentiality or authenticity guarantee.

Tests: `tests/test_checkpoint_preflight.py`. No real device was accessed.


## v0.1.12 archive extension

The preflight manifest can now be preserved together with a complete journal
copy in a create-only, checksum-wrapped sibling archive. Verification reconstructs
the exact ReplayIndex from the archived history and checks the manifest and
current-generation digest. Standalone inspection can validate a historical
archive when the live journal is missing, without proving that it is the newest
generation. This retains unbounded source history; pruning remains unavailable.
See `docs/checkpoint-archive.md` for commands and recovery limitations.

## v0.1.13 budget identity compatibility

The exact in-memory replay index now also covers schema-4 operation-budget
installation IDs. The preflight manifest includes `operation_budget_max` (or
`null` on earlier schemas), and the index can probe budget replay/collision
semantics. No historical IDs are discarded.
