# Bounded time + durable physical evidence (experimental v0.1.3)

**Research-only simulation.** This model cannot protect a physical device until
trusted time, counter provenance, fault-tolerant storage, and actuator authority
are furnished by the vendor/device. It has no authenticated remote interface.

## What changed

`experimental_evidence_hardware.py` runs an optional combined experiment;
`experimental_hardware.py` (v0.1.2 integer-time experiment) remains intact.
Both use the independent simulated actuator journal, but the combined guard
persists `TimeEvidence` for initial state, last checked time, last verified
physical state, every confirmed hardware edge, and operation preparation and
dispatch.

Each time observation consists of a collision-free boot identity,
suspend-aware boot-relative interval and an optional *validated* absolute-time
interval. The caller is responsible for authenticity and bounding errors.
Ordinary wall-clock samples do not satisfy the external contract.

## Time evaluation

For an event `E` and prospective operation at `N`, the guard uses the
minimum **provable** elapsed time based on comparable time domains. Relevant
restrictions are:

- minimum dwell in currently observed GREEN `oper` state;
- minimum interval since most recent verified physical edge;
- count of all verified edges that *cannot be proven expired* within the
  half-open window `(N-W,N]`.

A zero policy limit is exempt from an elapsed-time proof, since it places no
restriction. A zero transition budget always denies physical changes.

A controller can never satisfy time limits solely by issuing a new command,
changing its clock, or restarting. Contradictory time sources quarantine the
guard. The journal retains all events across restarts.

`retry_at_ms` is deliberately absent from this experimental mode; time may be
uncertain across reboot, and any absolute retry promise would be misleading.

## Verification time and the physical event

A physical transition can occur between dispatch and verification. The
simulator persists the **verification timestamp** as a conservative latest
possible physical event time (the physical event was no later than the
verification). This delays expiry relative to earlier real events; it never
makes a policy window expire early under the complete-counter assumption.

If the transition occurs in boot A and the first independent observation is
in boot B, its quota can be released after a full window of proven uptime
starting with its boot-B verification, even with no trusted absolute time.
This yields a safe *liveness path* without guessing the offline duration.

This approximation needs proof that the physical edge occurred before the
reported verification, and that all relevant intervening edges are visible.
Future actuators that allow subsequent background transitions require extra
reconciliation logic.

## Crash protocol

1. `prepare` records a pending operation after conservative policy checks.
2. `dispatch` rechecks policy and the hardware counter, then persists the
   `may-have-dispatched` marker **before** calling the actuator.
3. `acknowledged` is an API bookkeeping phase. It never changes GREEN `oper`.
4. `reconcile` requires an independent ledger event matching operation ID,
   original state, target, exactly one counter increment and Energy Object ID.
   It records a bounded verification-time event and advances `oper`.
5. An unknown outcome remains `unresolved`; competing automated operations
   are rejected. There is no automatic resend after possible dispatch.
6. A `prepared` operation can be aborted before any dispatch possibility;
   a `may-have-dispatched` operation cannot.

The controller and actuator ledgers are separate and have no distributed
transaction. Tests inject crashes and storage failures around the boundary.

## Limitations / non-claims

- `TimeEvidence` is supplied by the caller; nothing proves clock authenticity.
- The 'hardware' is a separate JSON journal, not a secure firmware counter.
- SHA-256 detects accidental modification only. Rollback or deliberate data
  modification is outside the guarantee.
- POSIX `flock` serializes cooperating processes on a single host; it is not
  a distributed lock, fencing service, or HA cluster primitive.
- The independent actuator counter must span reboots and count autonomous
  firmware changes to validate the real-device invariant.
- Simulation-only transitions are fictional. No manufacturer cycle or wear
  limit, no physical safety claim, and no IETF endorsement follow from tests.

## GREEN alignment

The experimental `admin` projection denotes requested intent while `oper`
denotes **verified observed power state**, following
`draft-ietf-green-power-and-energy-yang-05` (2026-11-02). `pending`,
`quarantine` and clock uncertainty are local diagnostics; there is no
normative GREEN YANG node for them in this prototype.

Refer to `green-alignment.md`, `yang-augmentation-proposal.md`, and
`hardware-counter-provenance.md` for the possible interoperable interface.
