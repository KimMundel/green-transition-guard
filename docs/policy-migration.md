# Simulated policy upgrade semantics (v0.1.8)

This implements **in-process, single-host policy updates for `TransitionGuard` only**.
It is not a signed policy distribution protocol, a physical-device upgrade
procedure, or an IETF-standardized contract. The hardware experiment remains
unchanged and does not support live policy updates.

## Backward compatibility and durable epochs

- Legacy schema-1 journals continue to read and accept requests unchanged.
- The first successful `update_policy` atomically converts that journal to
  schema 2, without clearing the events, no-op IDs, initial state or times.
- Schema 2 retains `initial_policy`, ordered `policy_updates`, and the most
  recent policy in `policy`. The update log is append-only at the API level.
- Each update records `seq` (policy revision), `id` (idempotency key),
  `at_ms`, `after_event_seq` (last accepted event at activation), and the
  full new policy. A cutoff separates an update from events accepted at the
  **same millisecond**. Events before the cutoff are validated under their
  original epoch. The current policy is used for all *future* requests.
- `status()` exposes `policy_revision` separately from accepted-transition
  `revision`. `policy_history()` returns a detached copy of the epoch log.
- State identifiers and their order must remain identical. Edges, dwell
  times, minimum interval, quota, and window length may change.

## Safety invariants

1. **No history reset:** New limits apply to the entire saved event history.
   A larger window can re-include older events, and a lower quota blocks
   until the active count falls below the new cap. A zero cap blocks changes.
2. **No retrospective edge rewrite:** An edge that was legal in its original
   policy epoch remains valid in the durable historical journal, even if a
   later policy removes that edge.
3. **No clock reset:** Updates must use a nondecreasing clock. Idempotent
   replays also persist the observed clock, without creating another epoch.
4. **No id reuse:** Update IDs are unique across transition, no-op and policy
   change operations. A matching replay returns the original policy revision.
5. **Revision compare-and-swap:** `update_policy` requires the caller's last
   seen policy revision. `request` optionally accepts
   `expected_policy_revision`; mismatches return `stale-policy-revision`.
   Requests omitting it remain backward-compatible and still use the current
   authoritative policy.
6. **Strict migration validation:** Reopening reconstructs the historical
   policy at each event, verifies update timestamps and event cutoffs, checks
   the final active policy, and rejects malformed history.

## Example

```python
from green_transition_guard import Policy, TransitionGuard

guard = TransitionGuard.open("device.guard.json")
current = guard.status()
next_policy = Policy.from_dict({
    **current["policy"],
    "max_transitions": 1,
})
revision = guard.update_policy(
    new_policy=next_policy,
    update_id="policy-rollout-2026-11-05-A",
    at_ms=123456,
    expected_policy_revision=current["policy_revision"],
)
```

CLI alternative (the caller creates and reviews `new-policy.json` first):

```bash
green-guard update-policy \
  --store device.guard.json \
  --policy new-policy.json \
  --update-id change-001 \
  --time-ms 123456 \
  --expected-policy-revision 0
```

All timestamp values must belong to the same trusted, nondecreasing domain as
existing events. Sample times above are illustrative only.

## Remaining risks

- Schema-2 journals are **not readable** by old v0.1.7 software. Upgrade
  readers before performing a policy update; do not downgrade journal files.
- The checksum detects accidental corruption; it does not authenticate
  policies or operators. A production system needs authorization, audit,
  authenticated clock evidence and rollback resistance.
- A persistence error after `os.replace` leaves durability ambiguous. After
  an error, reopen the journal and reconcile the update ID before any retry.
- This implementation does not prove power-loss durability or solve policy
  updates on physical in-flight actuation. The hardware experiment is
  deliberately unaffected.
- There is no cross-device synchronization or distributed consensus. The
  history, update log and deduplication keys remain unbounded.


## v0.1.10 window ceiling addendum

Policy updates on a schema-3 sealed journal are limited to `window_ms` at or
below the persisted `window_ceiling.max_window_ms`, even across restarts.
Schema-1/2 journals remain readable and can be sealed explicitly; old policy
epochs are retained and validated under their original rules. Schema 3 cannot
be read by v0.1.9 or earlier. See `docs/window-ceiling.md` for the immutable
seal operation and its limits. Physical operations remain unaffected.
