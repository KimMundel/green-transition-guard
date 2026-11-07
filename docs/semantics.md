# Guard semantics

These rules describe the Python simulator. They have no standing as an IETF specification.

## Policy

A policy contains:

- A set of states and directed, allowed transitions.
- A minimum time to remain in each current state (`min_dwell_ms`).
- A minimum interval between accepted transitions (`min_interval_ms`).
- A rolling window (`window_ms`) and maximum accepted transitions in that window (`max_transitions`).

For a request at time `T`, changing from `s` to `t` requires:

1. `t` is known and `(s, t)` is an allowed edge.
2. `T >= entered_ms + min_dwell_ms[s]`.
3. `T >= last_transition_ms + min_interval_ms`, if there is a previous transition.
4. Fewer than `max_transitions` events have times in `(T - window_ms, T]`.

The left boundary is open. For example, an event at `T - window_ms` has already expired. A zero transition cap blocks all state changes. All comparisons use integer milliseconds.

When several time limits block a change, the reason order is dwell, interval, then rate limit. The reported `retry_at_ms` reflects the current recorded history and assumes no further transitions occur before retry. The caller supplies the clock; the simulator cannot authenticate it.

## Journal and replay

The journal records accepted state changes, accepted no-ops and policy updates. A state-changing operation gets an event ID and increments the event revision. A no-op keeps the revision unchanged and uses no transition quota, while its request ID is retained for replay detection.

Repeated use of an accepted request ID for the same target produces a replay result. Reusing the ID with a different target is a collision. Explicit expected event and policy revisions can reject stale requests. Rejected requests still persist the latest valid time observation, so restarting a process cannot silently move its clock backwards.

Cooperating processes serialize access through a POSIX file lock. Journal writes are replaced atomically and checksummed. A lost, truncated, or corrupt journal is rejected. The checksum provides accidental-corruption detection only.

## Changing policy

Policy updates preserve prior events and apply the new policy to subsequent decisions. Historical transitions remain associated with their earlier policy epochs. A later policy's rolling quota still counts relevant older events. New state identifiers or a different state order are rejected.

Optional one-way seals can cap future policy-window sizes and the count of accepted identities. The complete journal stays in place. The count budget is not a byte-size limit.

See [policy migration](policy-migration.md), [window ceiling](window-ceiling.md) and [operation budget](operation-budget.md) for migration details.

## Requested and physical state

The basic guard records *accepted simulated commands*. The separate physical-operation lab records whether an effect was dispatched, acknowledged, or reconciled with simulated evidence. An acknowledgement can be lost after a physical change, so issuing the command twice is unsafe without independent proof.

After an ambiguous dispatch, the lab withholds another operation until it can reconcile the result. Clock uncertainty, extra autonomous edges and conflicting evidence can also quarantine further work. The simulator's ledger is deliberately a controlled test fixture; it is not an authenticated hardware counter.

See [hardware transitions](hardware-transitions.md) and [durable time](durable-time.md).

## Unresolved choices

A device model would have to specify whether limits count requests, commands, physical edges, failed attempts or lifetime cycles. It would also need rules for emergency overrides, counter resets, policy authorization, multi-controller ownership and time across power loss. Those questions remain open pending implementer input.
