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


## v0.1.7 storage fault-injection tests (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**220 tests passed**, comprising all 171 v0.1.6 regressions and 49 new
local I/O-failure tests. Scenarios cover exclusive initial creation,
truncated snapshots, temporary-file descriptor allocation/cleanup, flush,
file fsync, atomic replacement, directory open/fsync, uncertain dispatch
markers, actuator ledger writes, delayed reconciliation, and logical quota
replay. These are deterministic process-level injections, not real power-loss
tests. In-process file visibility after `os.replace` does not establish
on-media durability after an I/O error. No real hardware was used.


## v0.1.8 policy upgrade tests (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**252 tests passed** (220 baseline + 32 new). Added legacy schema
compatibility, history-preserving migration, historical edge validation,
quota/window re-evaluation, dwell/interval changes, replays, concurrent
updates, stale policy revision preconditions, first-update disk errors,
post-replace uncertainty, CLI behavior and malformed epoch ledger rejection.

These are deterministic single-host simulated tests. No external device,
actual power-loss testing, trust anchor or authenticated policy rollout was
used or validated.

## v0.1.9 quota-retention preflight (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**275 tests passed** (252 baseline + 23 new test cases). The new cases exercise
read-only quota-prefix analysis, exact left-boundary expiration, repeated
timestamps, release-time parity, corrupt storage, policy epoch upgrades,
replay consistency, CLI inspection, and a deterministic independent oracle
with 240 random histories and 4,800 timestamp/window probes.

No durable history compaction is performed. The proposed maximum future window
is hypothetical and cannot be used to justify deletion until a versioned,
durable enforcement contract and replay/history checkpoint design are added.


## v0.1.10 persisted future-window ceiling (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**315 tests passed** (275 baseline + 40 new). New tests exercise schema-1/2
upgrades to schema 3, later policy ceiling enforcement, older epoch validity,
request-ID uniqueness, exact idempotent installation replay, policy revision
preconditions, corruption despite recomputed checksums, simultaneous timestamps,
legacy replay, read-only retention signal, CLI, and before/after replacement
exceptions. Existing randomized quota-retention oracle tests still pass.

The tests use an in-process POSIX simulation. The seal has no hardware,
trusted clock, authenticated rollback protection, or real power-loss validation.


## v0.1.11 exact replay and checkpoint preflight (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**333 tests passed** (315 baseline + 18 new), including schema 1/2/3 replay
identities, cross-kind collisions, legacy no-op/transition replays, policy
changes, one-way window seal, exact quota left boundary, detached views,
snapshot digests, stale manifests, corrupt checksummed journals, read-only CLI,
and a randomized replay comparison against real simulated guard decisions.

The checkpoint preflight is read-only. SHA-256 is an unkeyed content commitment,
not an authenticated rollback-resistant proof. No actual history deletion,
archival, real power-loss testing, or physical hardware experiment was done.


## v0.1.12 create-only replay archive tests (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**372 tests passed** (333 baseline + 39 new). Covers schema 1/2/3 archive
exports, independent regeneration of replay/epoch manifest, request-ID
privacy in CLI summaries, replay and collision checks, immutable-by-API
no-clobber behavior, symlink and invalid-path rejection, concurrent exports,
source staleness, offline inspection, recomputed-checksum tampering, temporary
FD cleanup, injected file-sync and partial-write failures, post-link/dir-sync
uncertainty, and CLI nonzero exit on stale archives.

Tests are POSIX in-process simulations. They establish neither physical
filesystem power-loss guarantees nor trusted archive provenance or rollback
protection; the guard continues to use only the full live journal.

## v0.1.13 accepted-identity budget tests (2026-11-05)

Command: `PYTHONPATH=src python3 -m pytest -q`.

**405 tests passed** (372 baseline + 33 new). Exercises explicit schema-3 to
schema-4 conversion, exact budget counts including both seals, full-journal
replay after saturation, request/policy rejection at capacity, stale revisions,
ID collisions, legacy preservation, before/after-replacement failure recovery,
checksummed corruptions, independent archive verification, CLI semantics, and
simultaneous process writers contending for the last available identity slot.

This bounds the number of accepted identities in **opt-in** schema-4 simulations
only; source history is preserved. The tests provide no power-loss durability,
authenticated rollback guarantee, physical safety certification or byte-size
upper bound.
