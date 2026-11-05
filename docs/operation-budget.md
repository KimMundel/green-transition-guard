# Durable accepted-identity budget (experimental v0.1.13)

## Scope and ordering

`TransitionGuard.seal_operation_budget` explicitly migrates an **already
window-sealed schema-3** simulation journal to **schema 4**. The guard retains
all prior state, accepted transitions, no-ops, policy updates and the
window-ceiling record. The operation-budget seal itself also receives a unique
idempotency key.

The installation records a one-way `max_total_ids` limit with a monotonic
clock reading and event, no-op and policy-revision cutoffs. Installation is
atomic through the existing single-host snapshot store. Recovery after an
ambiguous write requires reopening and replaying the **same** installation ID.

The limit counts all **accepted persistent operation identities**:

- accepted state transitions;
- accepted no-op requests;
- committed policy updates;
- the pre-existing window-ceiling seal (1);
- the operation-budget seal (1).

Unsuccessful or rejected requests consume no identity slot. A rejected
request may still advance the stored `last_checked_ms` clock. All identifiers
already in the journal remain available for exact replay or collision checks.

## Saturation behavior

When `total_identities == max_total_ids`, any previously unseen request that
would create a new accepted transition or no-op is rejected with
`reason: "journal-capacity"`; no event, no-op or revision is appended.
A previously unseen policy update raises `GuardError` with an exhausted-budget
message. The guard checks exact historical ID replay and collisions first,
so previous operations remain replayable even at capacity. A new unsupported
or malformed transition retains its normal rejection reason.

There is deliberately **no automatic pruning, cap enlargement or unsealing**.
Set the cap conservatively. A filled budget renders a simulated device unable
to accept new transitions until a future, separately proven migration exists.
The API provides a fail-closed availability tradeoff.

## Usage

The simulated journal must already have a sealed maximum policy window:

```bash
green-guard seal-window --store device.guard.json \
  --max-window-ms 60000 --install-id window-seal-001 \
  --time-ms 10000 --expected-policy-revision 0

green-guard seal-budget --store device.guard.json \
  --max-identities 1000 --install-id budget-seal-001 \
  --time-ms 10001 --expected-policy-revision 0
```

The `status` output includes `total_identities` and `operation_budget_max`.
Legacy schemas have a `null` budget field; they remain readable and function
as before. Schema 4 is **unreadable to v0.1.12 and earlier**. Do not open or
downgrade a sealed journal with older versions.

`checkpoint-plan` and complete-history `checkpoint-export` include the budget
seal in exact replay indexing. The archive can be verified independently and
still contains the complete raw history. The live journal alone remains
operationally authoritative.

## Explicit limits and unsolved prerequisites

- This caps **operation identity count**, not JSON bytes, disk usage, or memory.
  Policy configurations, identifiers, clocks and complete history still grow
  within the remaining budget; no measured storage bound is established.
- Existing unsealed journals remain unbounded until explicitly migrated.
- File checksums and schema validation are unauthenticated. File restoration,
  hostile tampering or downgrade attempts can bypass the software-only seal.
- Clock evidence, real power loss, hardware actuation, independent tamper-proof
  generations, and transport edge cases have not been validated.
- `journal_compaction_enabled` remains `false`. A quota-expired event still
  cannot be discarded: exact replay IDs, historical policy validation and
  crash-consistent checkpoint activation must survive removal.

Tests: `tests/test_operation_budget.py`, including concurrency, saturation,
replay preservation, schema migration, corruption, and I/O fault injection.
