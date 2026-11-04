# Safety property sketch — simulation model only

## Bounded transition rate

For a fixed policy with cap `N` and window `W > 0`, define
`A(T) = {e | T-W < e.time <= T}` for accepted transition events.
Claim: `|A(T)| <= N` at every processed request time `T`, assuming a
nondecreasing trusted clock and an initially empty event journal.

Base case: the initial journal is empty.

Inductive step:
- A rejected or no-op request appends no transition event.
- For an accepted transition, the implementation first requires
  `|A(T)| < N`, then appends one event at time `T`. Thus the new count is
  at most `N`.
- If time advances without adding events, older events can expire and none
  can become newly active in the sliding window.

The event history is serialized under a file lock and recorded before the
simulated decision returns, so a controller restart sees the same count.

This is a short argument about the **model and implementation rule**, not an
external formal proof or a physical safety certification. It relies on:
- persistent state storage and single-host lock integrity;
- trusted, nondecreasing time;
- exclusive authority for accepted transitions (no out-of-band actuation);
- fixed policy; and
- the simulator's definition of accepted events.

## Remaining proof obligations

1. Persistent crash consistency (fault-injection at every filesystem write).
2. Correct event accounting across real hardware failures and restarts.
3. Model alignment with eventual IETF YANG message semantics.
4. Refinement proof between a hardware adapter and the simulator model.
5. Failure behavior under storage exhaustion, corruption, or split brain.


## v0.1.2 simulated hardware evidence invariant (informal)

Under the simulator assumptions of a single durable actuator authority,
serialized writes and a complete hardware edge ledger, the controller can
move its reported `oper` state only when:

1. It has a durable `may-have-dispatched` operation ID and an expected origin.
2. The actuator ledger reports exactly one additional physical edge since
   the last verified counter, with the same operation ID, origin and target.
3. The current actuator state equals the requested destination.

Otherwise the pending operation is retained and competing automation blocked.
The separate ledger means crashes after physical movement can be reconciled
without re-sending the original command. Neither the actuator ledger nor the
checksum is authenticated; this is an executable invariant test, not a
mathematical refinement proof or a hardware safety guarantee.


## v0.1.3 bounded-time physical-edge argument (informal, conditional)

The combined simulator holds a per-device journal protected by a serialized
single-host lock and a separate simulated physical-edge ledger. All policy
decisions count each previously verified event as active unless a lower bound
on elapsed time proves its expiration. No cross-boot expiry follows from an
arbitrary new boot uptime. Reconciliation records a verification observation
which is later than (or coincides with) the simulated physical edge.

For a real edge at time `E` and its verification at `V >= E`, conservative
elapsed lower bounds at a later request `T` satisfy
`elapsed_min(V,T) <= actual_elapsed(E,T)` when the clock bounds are honest.
Therefore a physical edge can only expire from the quota after it really has
expired. The same bound applies to min-dwell and min-interval restrictions.

A physical edge is **only** followed by another automated dispatch if the
preceding edge is fully verified and an independent counter proves exactly
one physical event; otherwise the pending operation blocks further dispatch.
Any external/missing cycle must be reflected in the independent counter or
exclusive actuator authority; a counter that silently misses edges destroys
the premise. Wall-clock values, JSON hashes, and controller command logs are
insufficient to certify this premise.

The tests exercise examples and faults, not a formal refinement proof.
Unresolved proof obligations: trustworthy clock provider, persistent
monotonic counter provenance, crash/power-loss durability, actuator fencing,
firmware autonomous edges, policy mutation and lifecycle counter resets.
