# Potential GREEN WG discussion — UNSENT

The GREEN WG announcement invited presentation requests for IETF 127 by
2026-11-08. Its meeting is planned for 2026-11-18. Verify the current agenda
and chair instructions before requesting a slot.

## Proposed five-minute presentation

Title: "Experimental semantics for power-state transition safety limits"

1. Framework -03 section 3.5.1 explicitly identifies limits on transition
   frequency and duty cycle as outside current capability discovery.
2. Proposal: device-authoritative, discoverable constraints (min dwell,
   min interval, bounded transitions in a time window) and explainable
   acceptance or rejection.
3. Open-source reference simulator with deterministic temporal boundary tests,
   crash-persistent history, and controller restart/failover examples.
4. Open questions: what counts as a transition? how are clocks handled after
   reboot? should restrictions be in capability discovery, control YANG, or
   a separate augment? what vendor limits and use cases exist?
5. Request for feedback: existing overlapping work, implementation interest,
   desired model placement and semantics.

## Status caveat

A simulator cannot demonstrate physical hardware safety or guaranteed energy
savings. The proposal is independent and has not been accepted by the WG.


## Prototype evidence update: v0.1.4

A minimal read-only experimental YANG augmentation and a JSON projection
are available for discussion, with 103 local software tests passing. The
YANG module has **not** been compiled against official imports, so present
it as a proposed interface rather than a validated module. No meeting
request was sent by this release.
