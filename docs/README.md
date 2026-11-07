# Documentation

Start with the [repository README](../README.md) if you want to run the simulator. These notes contain the detailed design choices, experiments, and failure cases.

## Model and standards

- [Semantics](semantics.md): current policy and journal rules, with open questions.
- [GREEN alignment](green-alignment.md): the parts of the active drafts we reuse and the gap being investigated.
- [YANG experiment](yang-augmentation-experiment.md): the read-only augmentation and real schema/instance checks.

## State, time, and hardware evidence

- [Hardware transitions](hardware-transitions.md): dispatch, lost acknowledgements, and reconciliation.
- [Durable time](durable-time.md): time uncertainty and what cannot be established after reboot.
- [Hardware counters](hardware-counter-provenance.md): limitations of counters as evidence of physical transitions.
- [Vendor counter adapters](vendor-counter-adapters.md): offline diagnostics for specific Linux and NVMe sources.
- [Optical power-mode evidence](optical-power-mode-evidence-2026-11-07.md): Cisco readback and the limits of its evidence.
- [Restriction scope](restriction-scope-evidence.md): component-specific power, protocol and maintenance timing.
- [Optical control cadence](optical-control-cadence.md): reset-signal and laser-safety pulse timing.
- [Mechanical durability](mechanical-durability-and-green-capabilities.md): SFP-DD mating qualifications and their limits.
- [Pulsed-laser lifetime](pulsed-laser-lifetime-evidence.md): industrial pulse-life estimates and source conflicts.
- [Storage fault injection](storage-fault-injection.md): process-level I/O failure cases.

## Persistence and recovery

- [Policy migration](policy-migration.md)
- [Window ceiling](window-ceiling.md) and [operation budget](operation-budget.md)
- [Checkpoint preflight](checkpoint-preflight.md) and [archive](checkpoint-archive.md)
- [Lineage and witness](recovery-witness.md)

## Results and next work

- [Test report](test-report.md): commands and CI evidence for the code on `main`.
- [Roadmap](roadmap.md): next questions and prerequisites for device testing.

Several of the linked documents are research notebooks from earlier iterations. Their assumptions are local to the experiment described; the README, current code, and CI runs describe the tested repository state.
