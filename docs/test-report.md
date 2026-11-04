# Reproducible local validation — 2026-11-04

Environment: Linux container, Python 3.13.5, pytest 9.0.2.
Command:

```bash
PYTHONPATH=src python3 -m pytest -q
```

Observed result: **24 passed**.

Coverage includes policy validation, no-op/replay semantics, clock rollback,
stale revision, simulated controller failover, concurrent controller writers,
durable event history, corruption rejection, minimum dwell/interval boundaries,
sliding-window expiry boundary, randomized invariant and independent oracle.

A Python wheel was also built from this source with `pip wheel --no-deps
--no-build-isolation`.

## Demonstration result

Three transitions at t=5000, 10000 and 15000 ms were accepted under a
3-transitions/60000-ms limit. A fourth request at t=20000 was rejected with
`rate-limit` and `retry_at_ms=65000`. Reopening the journal through a new
controller at t=30000 produced the same rejection. At exactly t=65000 a
transition was allowed (oldest event expired from the open-left window).

This validates only the software model and its configured fictional limits.

## v0.1.1 research addendum (2026-11-04)

- Added `experimental_time.py` as a separate, non-integrated research helper.
- Added 10 time-evidence tests: cross-boot uncertainty, exact expiry boundary,
  suspend-aware elapsed time, upper/lower uncertainty, contradictory clock
  sources, invalid evidence, and 2,000 deterministic generated oracle cases.
- Existing 24 tests remain unchanged, no integration with the v0.1 guard.
- The helper trusts its injected evidence; authenticating an actual RTC/time
  service remains unimplemented. Hardware actuation remains unimplemented.


## v0.1.2 conformance and standards-alignment addendum

Command: `PYTHONPATH=src python3 -m pytest -q`.

Tests: **59 passed** (existing 34, physical-actuation lab 23, standards
projection 2). The initial version's core engine remains unchanged.

New checks cover all four simulated dispatch crash points, no duplicate
command execution across controller restarts, deadline/interval boundaries,
physical-edge counter mismatches, external firmware transitions, operation ID
collisions, stale revisions, deliberately injected disk errors, random
transition sequences, and separation of requested intent from observed state.

`PYTHONPATH=src python3 examples/run_hardware_demo.py` produced:

| Scenario | Result | Simulated hardware edges | Guard observed state |
|---|---|---:|---|
| Crash after dispatch marker (no effect) | `unresolved` | 0 | `on` |
| Crash after physical effect (ACK lost) | `verified` | 1 | `sleep` |
| Autonomous OFF→ON changes while pending | `unresolved` | 2 | `on` |

YANG overlap was reviewed against `draft-ietf-green-power-and-energy-yang-05`
(2 Nov 2026), `draft-claise-green-capability-discovery-03` (27 Oct 2026),
`draft-ietf-green-framework-03` (2 Nov 2026), and the preliminary Controller
YANG -00. See `docs/green-alignment.md`. No YANG schema validation or real
NETCONF/RESTCONF test has been performed. Production time and hardware
security assumptions are still unresolved.


## v0.1.3 integrated evidence + physical faults (2026-11-04)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**87 tests passed**, including all 59 v0.1.2 regressions, 26 new bounded-time
physical-operation tests and 2 projection tests. No physical devices or
network services were exercised.

Added cases include same-boot timing uncertainties, exact rolling-window
expiry, cross-reboot unknown and proven elapsed time, contradictory clock
quarantine, independent hardware counter divergence, crash after physical
change, crash after durable dispatch mark, timeout/abort distinction,
fsync-failure injections at journal and simulated actuator boundaries,
randomized time/rate accounting and GREEN admin/oper projection.

Command: `PYTHONPATH=src python3 examples/run_evidence_hardware_demo.py`.

Expected demonstration:

| Scenario | Result |
|---|---|
| Physical edge occurred, controller crashed, later verified after reboot | verified |
| Only 20 seconds of proven uptime since reboot verification | rate-limit-unproven |
| 60 seconds proven since verification | prepared |
| Trusted cross-reboot time 1 ms below window boundary | rate-limit-unproven |
| Trusted cross-reboot time exactly at boundary | prepared |

Dependency check: pyang was unavailable; installation and official YANG source
fetch failed because the container lacks outbound DNS connectivity. No .yang
module compilation or actual NETCONF/RESTCONF interoperability is claimed.


## v0.1.4 experimental YANG projection (2026-11-04)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**103 tests passed** (all 87 previous tests and 16 new projection and
validation-gate tests). New cases exercise idle read-only projection,
nonmutation, pending/acknowledged distinction, dispatch crash, external
physical edges, asserted time evidence, invalid identity maps, uint64
overflow, and fail-closed YANG compiler dependency checks.

`PYTHONPATH=src python3 examples/run_yang_projection_demo.py` emits an
illustrative JSON instance with existing Energy Object id and optional
experimental operational subtree. No on-wire YANG schema has been compiled
and no real hardware/NETCONF/RESTCONF endpoint has been tested.

## v0.1.5 hardware counter provenance checks

- Added a research-only pairwise counter assessment and 29 focused cases.
- Existing actuator/time/YANG simulation and tests unchanged.
- Synthetic assertions only; no NIC, NVMe, BMC or manufacturer telemetry was
  sampled or validated.
- This experiment never authorizes a transition; source declarations require
  external verification.


## v0.1.6 source-specific counter provenance (2026-11-04)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**171 tests passed** (133 retained and 38 new cases). The new cases cover
actual `igc` statistic names, Tx/Rx separation, driver-epoch and host-boot
discontinuities, duplicate and malformed readings, NVMe SMART metric scope,
ambiguous zero, saturating thermal counters, cross-source rejection, and an
explicit regression ensuring diagnostic metrics are never interpreted as
complete physical state-edge counters.

`PYTHONPATH=src python3 examples/run_vendor_counter_demo.py` prints
`diagnostic-source-only` for both fictional Intel and NVMe fixtures. No
networking/storage hardware was read, manipulated or tested. The existing
experimental YANG module was not changed or compiled.
