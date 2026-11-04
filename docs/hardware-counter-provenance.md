# Independent hardware transition counters: feasibility and trust

**Status:** requirements analysis; no physical hardware or vendor capability
was tested. A simulated durable event journal is an oracle, not attestation.

## Required device-side properties

A counter usable for per-component transition safety would require:

1. A stable identity matching a GREEN Energy Object and a specific physical
   component (RFC 8348 identity may be correlated through discovery).
2. A monotonically increasing or explicitly epoch-tagged count of **every**
   relevant physical state edge, including autonomous firmware transitions.
3. Durability across reboots, failed commands, controller restarts and power
   loss, or an independently enforceable maximum loss bound.
4. Atomic association between the physical edge and counter increment.
5. Clear wrap, replacement and counter-reset semantics; ambiguous changes
   must quarantine automated control.
6. A trustworthy access path so the controller cannot forge or rewrite the
   value; authenticated and authorized management access is required.
7. The observed current physical state and operation identity, or an
   equivalent verifiable sequence of event records, to disambiguate multiple
   edges that finish in the original state.

A counter increase of 2 with final state unchanged indicates at least two
physical edges **only if** the counter itself has those semantics. A
configuration commit, HTTP success response, or state snapshot alone does
not furnish that information.

## Source classes and what they prove

| Source class | Potential value | Limitation |
|---|---|---|
| Vendor protected, persistent physical-edge counter | Strongest candidate | Vendor must specify counting semantics, authenticity, scope and lifecycle |
| Vendor event log with durable operation IDs | May prove exactly one acknowledged physical event | Requires completeness and retention guarantees |
| BMC/management processor in independent power domain | Can continue accounting while a controlled component is off | May still miss firmware-local transitions or lose state |
| Controller-side journal | Tracks commands and expected results | Cannot prove firmware/manual transitions were absent |
| Polling `oper` or equivalent observed state | Shows state at polling time | Misses off-on cycles between observations |
| Generic OS runtime power-management counters | Useful diagnostics | Counter semantics may be software references, rather than physical edges |

## Decision for the reference implementation

- Require an independent simulated physical counter and full edge journal.
- Reject or quarantine any unexpected counter increment, unknown origin,
  counter reset, unrecognized Energy Object or unexplained final state.
- Retain uncertain pending commands; do not retransmit merely because the
  counter currently appears unchanged.
- Keep policy dwell/interval/window constraints distinct from capability
  discovery's entry/exit latencies.

## Real-hardware acceptance gate

No physical safety claim until one target device supplies a documented
counter or equivalent event-trace contract and trusted clock bounds. Demonstrate
power failure, firmware-local transitions, counter wrap/replacement, split
controller authority, and power-domain behavior in a physical test plan.

This analysis should be cross-checked with the GREEN working group and actual
hardware implementers before proposing a protocol field for the counter.

## v0.1.5 primary-source correction

RFC 7460 **already standardizes** per-Power-State `eoPowerStateEnterCount`
and `eoPowerStateTotalTime` (both scoped to device uptime), along with
`eoPowerStateEnterReason`. See
`docs/hardware-counter-evidence-2026-11-04.md` for source-by-source analysis.
This supersedes any implication that standardized per-state entry counters
are a new invention. The open problem is persistence, provenance, complete
coverage, correct time/epoch interpretation and fail-closed enforcement.

The optional `experimental_counter_provenance.py` models purely asserted
source properties and safe pairwise counter checks. It is **not** an actual
vendor adapter and never authorizes physical transitions. The existing
simulated physical ledger remains the only simulated source of events in
`experimental_evidence_hardware.py`.

**NVMe-specific caution:** SMART also defines two thermal-management
transition counters. Their count may mean a lower-power active state **or**
a vendor-specific thermal management action, and their 32-bit fields stop
at their maximum. `experimental_counter_provenance.py` now rejects known
counter saturation and requires declared protection against undetected wraps.
