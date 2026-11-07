# Open work

The next useful result is a concrete hardware example. The current simulator can exercise a proposed rule, but there is no evidence yet that its particular policy fields are the ones real devices need to expose.

## Near term

1. **Find a documented restriction.** A device or component with minimum residence time, minimum interval, maximum cycles in a window, or another cycling limit. Record the exact unit, scope, firmware/hardware source, and whether the value is fixed or configurable.
2. **Ask implementers about placement.** Should the restriction be discoverable as a capability, appear in operational state, live in an operator policy, or stay in a technology-specific model? Start with the [GREEN working-group drafts](green-alignment.md).
3. **Settle counting rules.** A request, accepted command, observed physical change, failed attempt, and autonomous transition are different events. A useful model has to state which ones count and what happens when evidence is missing.
4. **Check the YANG experiment against feedback.** Keep the existing `admin`/`oper` meanings. Add fields only when an implementer can explain their use.

## Optical evidence review (2026-11-07)

The offline research now covers Cisco IOS XR optical sleep/readback, Juniper
MX204 PSU power-procedure timing, XGS-PON state-machine intervals, Glenair
`Tx_Disable` signal timing, Cisco ALS recovery pulses, SFP-DD mechanical
mating qualification, and ePhotonics industrial pulsed-laser lifetime estimates.
Each has different event, component and authority semantics.

Five experimental analyzers and four small source-index corpora use synthetic
observations and always withhold hardware authorization. The GREEN YANG
schema remains unchanged.

**Open question:** obtain a revision-specific manufacturer operational limit
for remotely controlled telecom laser transitions, with independently defensible
event coverage and counter continuity. Only then consider capability semantics
with implementer review. GitHub CI is still required for this research batch.

## Already implemented on `main`

- Persistent simulated transition journal; dwell, interval, and rolling-quota checks.
- Request replay handling, policy epochs, one-way window/budget seals, and bounded-identity experiments.
- Simulated dispatch uncertainty, cross-reboot time tests, and storage fault injection.
- Read-only checkpoint/archive/lineage diagnostics and an HMAC witness integration example.
- Experimental read-only YANG augmentation; official -05 schema compilation and 14 synthetic instance checks in CI.

Tests and limitations: [test report](test-report.md).

## Blocking work before any real-device control

- Manufacturer-provided limits and a verified component identity.
- Reliable clock evidence across resets and power loss.
- A trustworthy way to distinguish physical changes from commands and acknowledgements, including manual/firmware transitions.
- Authorization, authenticated state, and recovery from a lost or rolled-back journal.
- Storage bounds and power-loss testing on actual hardware.

History compaction, restored operation, and independent witness infrastructure remain out of scope until those requirements are grounded. The full journal is retained.
