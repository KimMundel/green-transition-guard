# Semantics and unresolved normative decisions

This file records implementation choices, not an adopted IETF specification.

## MVP data model

`Policy = (S, E, dwell[S], interval, window, cap)` where:

- `S`: device-supported power states.
- `E`: allowed directed pairs of different states.
- `dwell[s]`: minimum residence time in the current state `s`.
- `interval`: minimum separation of any accepted transitions.
- `window`: positive sliding-window duration, in milliseconds.
- `cap`: number of accepted transitions allowed in a window; zero blocks all.

`DeviceHistory = (initial_state, initial_entry_time, accepted_events)`.

A transition requested at time `T` is admitted iff:

1. target is a supported state and the current->target edge is allowed;
2. `T >= entered_time + dwell[current]`;
3. `T >= previous_transition_time + interval` (if any);
4. `count(events with T - window < event.time <= T) < cap`.

An accepted change is appended durably and increments the revision. No-op
requests are accepted without incrementing the revision. All comparisons are
integer-exact. Multiple failures use deterministic reason precedence: dwell,
interval, rate. Rejected requests still update the last observed clock value.

## Consistency model

- One authoritative journal per device, protected by a POSIX advisory lock.
- Every accepted event has a monotonically increasing revision and a stable
  request ID. Across controller failovers, the device journal is unchanged.
- Replays of previously accepted requests, including no-ops, report the
  current state without actuating. A transition replay returns the original
  event identifier; callers distinguish `replay` from a newly performed
  transition. No-op request IDs are also persisted.
- Clock regression, lost or invalid storage, and unsupported schema reject
  processing (fail closed).
- The event log and policy-update log remain unbounded. Safe compaction is
  an open research question. v0.1.8 introduces simulated policy epochs with
  state identity preservation and historical event revision cutoffs; see
  `docs/policy-migration.md`. These semantics are exploratory rather than
  a standardized or authenticated policy rollout.

## Open research questions (must resolve before any standards proposal)

1. Which limits are vendor-provided hardware constraints versus operator policy?
2. Are cycle budgets per device, component, state, transition edge, or lifetime?
3. Do attempted, confirmed, interrupted, or rolled-back transitions count?
4. What clock source survives device reboot and how do we handle uncertainty?
5. How should emergency transitions and manual service overrides be modeled?
6. Which behavior is safe after storage loss or high-availability split brain?
7. How should a new controller learn a trustworthy history and policy version?
8. How do we align identifiers with IETF GREEN Energy Objects and YANG models?
9. How can limits be represented as YANG read-only capabilities, and how can
   rejection reasons be conveyed by NETCONF/RESTCONF in an interoperable way?
10. What hardware/vendor evidence is needed to justify any particular limits?

## Explicit non-goals

- No real device command execution or claim of hardware protection.
- No authenticated telemetry or secure transport.
- No standards-approved YANG model; the optional v0.1.4 read-only
  experimental augmentation remains uncompiled and simulation-only.
- No distributed replicated write authority.
- No automatic adaptation of vendor safety limits.
- No claim that the proposal is novel, accepted by GREEN, or on its charter.


## v0.1.2 physical-execution experiment (additional model)

The original v0.1 logical `TransitionGuard` semantics remain unchanged.
`HardwareTransitionExperiment` adds an isolated, independent persistent
actuator ledger and separate controller journal. This models two crash domains
without pretending to model production device timing or transport semantics.

- `prepare`: records one pending reservation. At most one operation for a
  protected Energy Object can be prepared/in flight.
- `dispatch`: rechecks temporal limits, commits `may-have-dispatched` before
  calling the simulated actuator, then may record `acknowledged`.
- `reconcile`: accepts only one independently recorded matching physical edge
  and matching counter, then advances the observed `oper` state. The
  verification observation time is used as a conservative latest-edge time.
- `timeout`: marks `unresolved`; a missing ACK never proves an absent edge.
- External/firmware transitions and counter disagreement lead to `unresolved`
  or `physical-divergence`, blocking automatic actions.
- The simulated actuator is idempotent by operation ID, while the controller
  refuses dispatch retries after the durable possible-dispatch marker.
- A `prepared` operation may be aborted only because the lab explicitly
  gates dispatch on an earlier durable phase change.

The current interval is a caller-injected single clock epoch. The cross-reboot
bound comparison from v0.1.1 has **not yet been integrated** with physical
state bookkeeping. Production clock trust and hardware authority remain open.

All numeric example thresholds are fictional. This is a requirements and
conformance research model, not a basis for real hardware control.
