# Research backlog (draft, dependency-first)

## P0 — experimental baseline (complete in v0.1.0)

- [x] Explicit transition graph and per-state dwell constraints
- [x] Global minimum interval and sliding-window transition cap
- [x] Boundary semantics, stable machine-readable reasons and retry times
- [x] Durable device-side simulated history and fail-closed corruption handling
- [x] Replay of accepted transitions and no-ops; request revision guards
- [x] Single-host POSIX process locking
- [x] Deterministic randomized tests, independent reference oracle,
      restart tests, and concurrent writer regression

## P1 — correctness under adverse conditions

- [x] Inject in-process errors across initialization/replacement I/O boundaries (v0.1.7); real power-loss tests remain open
- [x] Research crash/actuation state model and failure matrix (docs only)
- [x] Implement **simulated** persistent physical-transition state machine with fault injection (v0.1.2); real adapter pending
- [x] Research clock evidence contract and uncertainty tests (experimental)
- [x] Integrate bounded time evidence with simulated physical-edge reconciliation (v0.1.3)
- [ ] Implement authenticated clock source and reliable real cross-reboot evidence
- [x] Implement history-preserving simulated policy epochs and migration (v0.1.8); authenticated physical rollouts remain open
- [ ] Bound state size using provably safe history compaction
- [ ] Analyze how missed external transitions affect quota guarantees
- [ ] Extend property-based tests with Hypothesis and independent oracle
- [ ] Formalize the state machine in Z3 or TLA+ (choose after semantics settle)

## P2 — standards integration

- [x] Document conceptual mapping to GREEN Energy Objects and admin/oper paths; production identityrefs still need validation
- [x] Compare Capability Discovery -03, Power/Energy -05, Framework -03, and Controller -00 in `docs/green-alignment.md`
- [x] Scope a minimal, read-only augmentation without duplicating existing GREEN leaves
- [x] Author an optional read-only experimental YANG augmentation and a
      fail-closed compilation gate (v0.1.4); **actual compilation pending**
- [ ] Compile experimental YANG with pinned official imports using pyang/yanglint
- [ ] Define rejection reason taxonomy and NETCONF/RESTCONF behavior
- [ ] Obtain feedback from implementers / GREEN WG without assuming adoption
- [ ] Investigate vendor-provided hardware limits and authenticity

## P3 — hardware integration (conditional)

- [ ] Find a willing vendor/device with documented limits
- [ ] Build real actuator with durable requested/applied/failed transitions
- [ ] Integrate fault simulation, real clock conditions and event reconciliation
- [ ] Publish test results and interoperability evidence

## Go/no-go

Stop or re-scope if equivalent standards work already covers these semantics,
no implementers need the feature, or the design cannot make safe claims with
realistic clock and failure assumptions.


## Priorities after v0.1.3

1. Source authenticated clock evidence with a justified drift/uncertainty bound
   and obtain vendor physical-edge counter semantics; current providers are
   simulated inputs only.
2. Extend storage power-loss fault simulation beyond current injected errors,
   including rename/fsync reorderings and a real durable physical ledger.
3. Validate independent hardware counter provenance, monotonicity, retention,
   autonomous/external edges, and secure component identity with implementers.
4. Obtain official GREEN imported YANG source and compile the smallest useful
   augmentation with pyang/yanglint; current documentation is only a scope memo.
5. Refresh the GREEN standards matrix whenever a relevant draft revision
   changes (the controller model remains preliminary).


## v0.1.4 delta

- Added source-only `yang/green-transition-guard-experimental@2026-11-04.yang`.
- Added RFC 7951-shaped, explicitly unvalidated read-only projection.
- Added fail-closed `scripts/validate_yang.py` for official module compilation.
- Priority: obtain exact published module and imports, run the gate and correct
  any actual compiler findings. Do not treat structural unit tests as YANG
  schema validation.

## v0.1.5 counter provenance research

- [x] Find standardized per-state entry counters: RFC 7460 and RFC 7326.
- [x] Compare NVMe SMART, Intel EEE LPI, Redfish logs, Linux PM, and RFC 8343
      discontinuity semantics; record primary-source links and limitations.
- [x] Add research-only source contract / observation-pair checks and tests.
- [ ] Obtain real device capability disclosures and validate any stated
      durability/atomicity before connecting to actuator/reconciliation logic.
- [ ] Lab-measure counter behavior through safe resets, power-domain changes,
      autonomous transitions, counter replacement, and log overflow.
- [ ] Align with GREEN WG on how much of the RFC 7460 counter history they
      expect to carry forward and whether quality metadata belongs in YANG.

## v0.1.6 counter source fidelity

- [x] Verify actual `igc` Linux ethtool metric names and software-accumulation
  behavior from maintained driver source.
- [x] Verify NVMe SMART power-cycle and thermal-action count scope, saturation
  and ambiguous zero from libnvme documentation.
- [x] Build strict, passive, offline parsers; keep all observed counts
  diagnostic-only regardless of count delta.
- [x] Fix generic diagnostic-source comparison when GREEN `oper` changes.
- [ ] Collect authorized real hardware snapshots and obtain reset/identity
  guarantees; synthetic fixtures do not establish production eligibility.
- [ ] Validate experimental YANG with official imports; read-only provenance
  leaf proposal remains deferred until implementer feedback.


## v0.1.7 persistence boundary tests

- [x] Simulate `mkstemp`, `fdopen`, partial writes, flush, file fsync,
      before/after rename, directory open/fsync, and exclusive-create failures.
- [x] Verify old/new snapshot integrity, temporary-file cleanup, no automatic
      resend after ambiguous dispatch, eventual reconciliation and quota replay.
- [x] Close the temporary descriptor when `fdopen` fails; regression added.
- [ ] Validate real system crashes, storage ordering and flush durability on
      a specific filesystem and hardware platform.
- [ ] Add fault-injection at process termination, transport duplication, and
      external physical-edge source failures.


## v0.1.8 policy epoch work

- [x] Keep schema-1 journals readable, migrate atomically to schema 2 on first
  explicit policy update; record every policy epoch with an event revision cutoff.
- [x] Revalidate historical edges under the active policy at the time; apply
  new quota/window/dwell/interval to retained history going forward.
- [x] Add policy revision compare-and-swap, idempotent update IDs, request
  preconditions, exact timestamp/cutoff validation and recovery tests.
- [ ] Design authorized policy rollout and anti-rollback for a real device;
  guarantee safety with pending physical operations before any hardware use.
- [ ] Bound journal and epoch size without losing quota or replay guarantees.

## v0.1.9 compaction prerequisites

- [x] Formalize quota-expired prefix under a *hypothetically enforced* maximum
  future window and monotonic time; verify boundary equality and migrations.
- [x] Add a fail-closed, read-only retention inspector and independent
  randomized quota oracle; the journal remains completely unchanged.
- [x] Persist and enforce future policy-window ceiling (optional schema-3 seal, v0.1.10); rollback and compaction remain open.
- [ ] Specify replay/ID tombstones and historical policy-chain checkpoints.
- [ ] Bound accepted event volume and handle saturation fail closed.
- [ ] Prove crash-consistent checkpoint installation, archive integrity,
  and recovery without silently resetting quotas.


## v0.1.10 enforced retention-bound prerequisite

- [x] Persist a one-way future policy-window ceiling in schema 3 while
      preserving legacy event/no-op history and policy epochs.
- [x] Reject new policy windows above the seal; validate sealing cutoffs,
      replay/collision keys, corruption and restart behavior.
- [x] Distinguish enforced versus hypothetical retention projections.
- [ ] Establish authenticated, rollback-resistant storage and clock evidence.
- [ ] Preserve replay IDs, historical state/epoch proofs and interval anchors
      across any planned journal compaction.
- [ ] Prove bounded operation volume and crash-safe checkpoint installation.


## v0.1.11 replay and checkpoint preflight

- [x] Add exact, detached replay identity probes for transition, no-op,
      policy-update and one-time seal IDs across schema 1/2/3.
- [x] Add a read-only, snapshot-bound checkpoint manifest with complete-history
      source hash, prefix/suffix commitments, policy chain digest, replay-index
      digest, state/time/interval anchors and sealed quota prefix count.
- [x] Exercise identity collisions, digest stability/staleness, migration,
      sealed/unsealed boundaries, fail-closed reads and CLI with regressions.
- [ ] Specify durable replay tombstones/archives and exact old-ID behavior after
      pruning; an index digest alone cannot answer replay queries.
- [ ] Design transactional checkpoint installation and authoritative archive
      verification before deleting any history.
- [ ] Bound journal/ID volume with fail-closed saturation and add real crash,
      rollback and hardware validation.
