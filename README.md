# GREEN Transition Guard - experimental v0.1.9

An **independent, unendorsed** reference simulation for evaluating power-state
transition frequency and dwell constraints relevant to the IETF GREEN work.
This project does not control hardware and does not claim IETF endorsement or
conformance. No real hardware safety limits have been established.

## Research question

Can different controllers make consistent decisions about a device's permitted
power-state transitions, while respecting the device's own durable history
through controller changes and restarts?

In this first prototype, the device is the source of truth: every simulated
accepted transition is recorded in a durable, per-device journal. Controllers
may issue commands, but cannot reset transition counts by restarting.

## Baseline semantics (experimental)

- Explicit allowed transitions, e.g. `on -> sleep` and `sleep -> on`.
- Per-current-state minimum dwell time.
- Minimum interval between accepted transitions.
- A maximum number of accepted transitions in a sliding time window.
- Window semantics: `(T-window, T]`, with the left edge **excluded**.
- A no-op request (target == current state) uses no transition quota.
- Time is a caller-supplied, trusted, integer millisecond timestamp. A
  backwards clock observation is rejected. Large forward jumps are **not**
  detectable without external clock guarantees.
- Event history and the last observed time persist across restarts.
- Retried request IDs are idempotent; a reused ID for another target is
  rejected. Explicit expected revisions reject stale commands.
- All cooperating writers to the same store are serialized by a POSIX lock.
- State corruption causes a fail-closed error; SHA-256 checksum is for
  accidental corruption detection, **not** adversarial tamper resistance.
- When multiple temporal limits block a transition, `retry_at_ms` is the
  earliest time given the recorded history and no additional transitions.

**Important:** The simulator records a transition as accepted. A real device
needs a separate persistent intent/actuation/feedback reconciliation protocol,
a trusted clock, authorization, and independent hardware safety protections.

## System requirements

- Linux (including Ubuntu WSL2) and Python 3.11+.
- No network, containers, special hardware, or third-party runtime modules.
- pytest for tests; Hypothesis reserved for later property-based experiments.

## Run without installing

```bash
PYTHONPATH=src python3 -m green_transition_guard.cli init \
  --store demo.guard.json --policy examples/demo_policy.json \
  --device-id switch-01 --state on --time-ms 0
PYTHONPATH=src python3 -m green_transition_guard.cli request \
  --store demo.guard.json --target sleep --request-id r-1 --time-ms 5000
PYTHONPATH=src python3 -m green_transition_guard.cli request \
  --store demo.guard.json --target on --request-id r-2 --time-ms 10000
PYTHONPATH=src python3 -m green_transition_guard.cli status --store demo.guard.json
```

Or install editable for the `green-guard` command:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

The `init` command refuses to overwrite an existing snapshot. To simulate a
controller restart, exit and launch another `request`; it reads the same
persistent device history.

## Project layout

- `src/green_transition_guard/`: constraint evaluator, persistence and CLI
- `examples/demo_policy.json`: entirely fictional limits
- `tests/`: deterministically reproducible tests
- `docs/semantics.md`: current definitions and unresolved standard choices
- `docs/ietf-127-meeting.md`: optional discussion outline, unsent

## Research status (2026-11-04)

- GREEN Framework -03 section 3.5.1 mentions frequency/operational constraints,
  and states that the related discovery model does not cover frequency or duty
  cycle limits.
- Power and Energy YANG -05 covers monitored and configured power state.
- Capability Discovery -03 describes supported state capabilities/transition
  characteristics, leaving additional restrictions outside its model.
- The prototype is a research artifact. Integration and standardization
  require discussions with GREEN and implementer feedback.

References:

- https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03
- https://datatracker.ietf.org/doc/html/draft-swepcarl-green-controller-yang-00

## Prior research experiments (v0.1.1)

- `docs/durable-time.md`: verified clock domains, bounded uncertainty,
  fail-closed cross-reboot behavior, and expiry proof conditions.
- `src/green_transition_guard/experimental_time.py`: pure reference
  experiment for conservative elapsed-time comparisons. It does not provide
  authenticated time, and the production v0.1 guard does not use it yet.
- `docs/hardware-transitions.md`: physical actuation phases, crash matrix,
  safety assumptions and conformance scenarios. No physical adapter exists.
- `tests/test_experimental_time.py`: independent boundary/reboot tests.

The production simulation still requires caller-provided trusted integer
milliseconds. Do not use the experimental module as a clock service.

## Evidence and next research steps

See `docs/test-report.md`, `docs/proof-sketch.md`, and `docs/roadmap.md`.
The current sliding-window algorithm is conventional; the potential
standardization contribution concerns interoperable constraints, durability,
failure semantics, and conformance. Novelty remains unestablished.

If WSL2 cannot start, first enable CPU virtualization in UEFI/BIOS and
Windows Virtual Machine Platform. No WSL installation is needed to inspect
this archive; simulation execution requires Linux (or WSL2).


## Experimental physical-actuation fault lab (v0.1.2, retained)

This version adds a **separate simulation-only actuator** with a durable
physical-edge ledger and independent controller journal:

- `src/green_transition_guard/experimental_hardware.py`: prepare,
  dispatch-possible, acknowledgment, uncertain timeout, and reconciliation.
- A crash **after the persisted may-have-dispatched marker** cannot cause an
  automatic resend. Reconciliation requires independent evidence of exactly
  one hardware event with the matching operation ID, counter, origin and target.
- Unknown actuation or unexpected firmware/manual edges blocks new automated
  requests; even a return to the original stable state does not erase cycles.
- `src/green_transition_guard/green_projection.py` maps requested/observed
  meanings to the **existing** GREEN -05 `admin`/`oper` paths. It does not
  produce a YANG document or pretend that lab state names are YANG identities.
- `docs/green-alignment.md`: pinned draft versions, existing YANG nodes,
  relevant RFCs, overlaps and possible future augmentation placement.
- `tests/test_experimental_hardware.py`: deterministic crash, restart,
  mismatch, quota, counter and storage-failure cases.

Reproduce the fault scenarios without GitHub, WSL2 or installed packages:

```bash
PYTHONPATH=src python3 examples/run_hardware_demo.py
PYTHONPATH=src python3 -m pytest -q
```

**Scope limitation:** This laboratory trusts its own simulated actuator journal
and caller-supplied nondecreasing millisecond clock. Independent real hardware
feedback, clock authenticity, distributed fencing, storage tamper-resistance,
manufacturer cycle limits and NETCONF/RESTCONF interfaces remain unimplemented.
A successful test of this simulator cannot establish hardware safety.


## Combined bounded time + physical-edge experiment (v0.1.3)

The opt-in `experimental_evidence_hardware.py` integrates the independent
simulated hardware journal with bounded clock evidence:

- Every verified physical edge has persisted time evidence. Bounded clock
  comparisons prove sufficient dwell/interval time or expiration of a rolling
  quota; unknown elapsed time remains conservative.
- Reboot without a trusted absolute clock cannot expire historical events by
  guesswork. If a physical event is verified **after** reboot, the guard can
  conservatively begin its retention interval at that verification and make
  progress once sufficient new uptime is proven.
- Crashes after a possible dispatch preserve a pending operation until the
  independent simulated hardware counter proves an edge. Counter divergence
  and contradictory clocks quarantine further automation.
- GREEN's existing `admin` (intent) and `oper` (observed) model remains
  unchanged. The new phase/reason fields exist **only in the laboratory**.

Demonstration:

```bash
PYTHONPATH=src python3 examples/run_evidence_hardware_demo.py
PYTHONPATH=src python3 -m pytest -q
```

See `docs/time-hardware-integration.md`, `docs/hardware-counter-provenance.md`
and `docs/yang-augmentation-proposal.md`. This is **not a device controller**, a
validated YANG implementation, or a hardware safety guarantee. No real
authenticated clock or physical counter is provided.


## Proposed GREEN read-only YANG augmentation (v0.1.4)

The new `yang/green-transition-guard-experimental@2026-11-04.yang` sketches a
**nonstandard, uncompiled** `transition-safety` subtree under the existing
`ietf-power-and-energy` operational Energy Object. It avoids replacing
`admin`/`oper` or the Capability Discovery model. The simulator's current
rate/dwell constraints are exposed as illustrative operational limits.
`experimental_yang_projection.py` emits a proposed RFC 7951-shaped example
with explicit power-state identity mappings and string-encoded uint64 values.
It never writes device configuration or exercises hardware.

```bash
PYTHONPATH=src python3 examples/run_yang_projection_demo.py
PYTHONPATH=src python3 -m pytest -q
# Only when official dependencies and pyang are available:
python scripts/validate_yang.py --modules /path/to/official-yang-modules
```

The **YANG compilation gate remains unverified** because this environment
cannot fetch official GREEN modules or install pyang. See
`docs/yang-augmentation-experiment.md` for exact dependency requirements,
limits of the projection and standards references. The file is an experiment
for technical review and must not be deployed as a certified safety control.

## Hardware counter provenance research (v0.1.5)

A source review identified existing EMAN RFC 7460 per-state entry and
residency counters, along with NVMe SMART (including thermal-management events), Intel Ethernet LPI, Redfish event
logs and Linux runtime PM evidence. See
`docs/hardware-counter-evidence-2026-11-04.md`.

`src/green_transition_guard/experimental_counter_provenance.py` adds a
**research-only** contract/sampling assessment. All contract flags are caller
assertions; no vendor counter was read and no real device is certified.
Counter reset, source mismatch, changed state without count, event gaps and
unattributed edges are quarantined. The baseline guard and YANG model are
unchanged. Full hardware integration requires verified device contracts.

## v0.1.6 offline vendor counter adapters

New research-only, passive parsers recognize the **documented** Linux `igc`
`tx_lpi_counter`/`rx_lpi_counter` and NVMe SMART power-cycle/thermal counts.
Their contracts are deliberately **diagnostic-only** and cannot release
transition quotas. Reboot, driver reload, component binding and full policy
coverage remain externally unverified. The generic provenance checker now
interprets a changed GREEN `oper` with an unchanged diagnostic-only count
as inconclusive, avoiding a false physical-state contradiction.

- `docs/vendor-counter-adapters.md`: primary-source review, capture procedure,
  exact scope, reset and discontinuity caveats.
- `examples/fixtures/`: fabricated text/JSON inputs, explicitly synthetic.
- `examples/run_vendor_counter_demo.py`: passive fixture demonstration.
- `tests/test_experimental_vendor_counters.py`: failure and regression tests.

YANG source is unchanged in this iteration; no vendor telemetry is added to
the GREEN wire model until provenance and formal YANG compilation are verified.


## v0.1.7 — storage failure boundary tests

- Improved `SnapshotStore.save()` cleanup when conversion of a freshly
  allocated temporary file descriptor to a text stream fails.
- Added 49 deterministic fault-injection cases covering initial snapshot
  creation, replacement writes, controller dispatch markers, actuator-ledger
  persistence, reconciliation and the logical quota guard.
- An exception after atomic replacement has **ambiguous physical durability**.
  The experimental physical guard never retries a possibly dispatched command
  automatically. See `docs/storage-fault-injection.md`.
- These tests simulate in-process errors on a POSIX filesystem; no power-loss
  or genuine hardware testing has been performed.


## v0.1.8 — policy epochs and history-preserving migration

The simulated `TransitionGuard.update_policy()` can now activate a revised
policy while preserving the entire transition/no-op journal. Historical edges
are validated against the policy active at their acceptance. The new policy's
window and quota are checked against **all historical transitions**, preventing
migration from resetting quotas. A separate `policy_revision` and optional
request precondition defend against stale configuration assumptions.

Legacy schema-1 journals remain readable. The first policy update converts
one to schema 2; older readers cannot open it afterward. See
[`docs/policy-migration.md`](docs/policy-migration.md) for the CLI, exact
migration constraints, fail-closed behavior, and production limitations.
This is an unauthenticated simulation API; live hardware updates are out of
scope.

## v0.1.9 — read-only retention analysis

`green-guard retention-plan --store device.guard.json --max-window-ms 60000`
reports how many historical accepted transitions would be quota-irrelevant
**if** future policy windows were durably capped at the supplied bound.
Exact left-boundary, timestamp, replay and policy migration behavior is tested
against the full journal; `journal_compaction_enabled` is always `false`.
The current guard permits unrestricted policy-window upgrades, so **no events
or IDs may be deleted using this report**. See
[`docs/quota-retention-proof.md`](docs/quota-retention-proof.md) for the proof,
unresolved replay/history obligations and scope of the experimental API.
