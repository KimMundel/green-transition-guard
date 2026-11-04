# Hardware transition counters: primary-source investigation

Date: 2026-11-04 | Scope: independent experimental GREEN Transition Guard

## Executive finding

There is **existing standardized state-entry accounting** in IETF EMAN RFC 7460. Its `eoPowerStateEnterCount` (Counter32) counts entries into a particular power state **since the last device reset** (referenced to `sysUpTime`). `eoPowerStateTotalTime` similarly measures time spent in each power state since reset. The same RFC defines `eoPowerAdminState`, `eoPowerOperState`, and `eoPowerStateEnterReason`. RFC 7326 already calls for per-state entry counts and durations.

Therefore, recording state entries is an existing standards concept. The remaining research problem is how to make safety decisions under **counter discontinuities, missing firmware transitions, uncertain timing, controller failover and power loss**, and how to express the necessary evidence without duplicating GREEN's own model.

The GREEN Framework -03 section 3.5.1 and appendix A.2 still identify operational cycle/frequency safety limits; GREEN Power & Energy YANG -05 exposes `admin` and `oper` and cumulative energy counters. It does not publish an equivalent durable state-entry ledger. Its device-level energy *counter* reset semantics must not be confused with physical *transition* counters.

## Actual source families and applicability

| Source | Specified semantics | Reset / completeness concern | GREEN safety conclusion |
|---|---|---|---|
| IETF EMAN RFC 7460 `eoPowerStateEnterCount` | Per-Energy-Object/per-state entry count (Counter32), since device reset | Reset at `sysUpTime` discontinuity; physical hardware origin is not guaranteed | Best interoperable semantic starting point, **insufficient across reboot alone** |
| NVMe SMART health `Power Cycles` | Controller/subsystem lifetime power-cycle statistic, retained across power cycles | Device-specific meaning; may exclude sleep/low-power edges; per-namespace interpretation varies by specification | Useful example of durability; **wrong granularity for generic GREEN states** |
| NVMe SMART `Thermal Management Temperature 1/2 Transition Count` | Number of thermal-management threshold responses; may include lower-power active states **or other vendor actions** | Hardware counts are potentially persistent as part of SMART; 32-bit counters saturate rather than wrap; exact GREEN state mapping is absent | Strong example of narrowly defined hardware transitions, **not a generic ON/SLEEP edge count** |
| Intel `igc` NIC EEE LPI registers (`IGC_TLPIC`, `IGC_RLPIC`) | Tx/Rx entry events into Ethernet Low Power Idle | Register/driver accounting, reset behavior; Rx measures peer activity; does not count all network device states | Candidate **LPI-specific** lab input only; hardware registers documented, no full-power-loss guarantee confirmed |
| Redfish event logs (`LogService`, `LogEntry`) | Management event records, possibly power-state and system-boot events | Can wrap, discard on full, or be cleared; log creation does not prove every physical edge was captured | Conditional reconciliation aid; an unverified event log cannot discharge a safety quota |
| Linux runtime PM | `runtime_status`, accumulated active/suspended times | Software management state and host-lifetime accounting; not a hardware lifetime edge counter | Diagnostics and timing hints, no guaranteed power-edge count |
| RFC 8343 `discontinuity-time` | Established management model for identifying counter reset epochs | Interface statistics semantics differ from energy state entry semantics | Reuse its **discontinuity design pattern**, avoid copying unrelated counters |

## A critical distinction: source evidence and counter completeness

Counter increase `N -> N+2` proves two relevant physical edges **only if** the counter's scope actually covers both edges, counts unmanaged firmware/manual activity, has no gaps, and is bound to the same component and counter epoch. An API acknowledgment proves only an accepted management operation. A state snapshot cannot expose an off-on excursion that completed between polls.

A per-state *entry* counter and a physical *edge* counter need different units and interpretations. Counting entries into sleep is appropriate for the on-to-sleep edge; returning to on normally changes a different per-state counter. Deriving a single global edge count requires a complete family of per-state counts, known starting conditions and a compatible power-state mapping. Autonomous transitions must be included.

Some hardware increments counters only while powered. A management processor in a separate power domain can observe extra events, but its persistent storage and event coverage remain vendor-specific. Cryptographically authenticated transport only authenticates what the endpoint **reports**; it does not prove the firmware captured every physical edge.

## Minimum counter provenance contract (proposed, experimental)

For each source and controlled Energy Object, define and verify:

1. `source-component-id`: stable binding to the physical component via existing GREEN `source-component-id` and RFC 8348 inventory; validate replacements.
2. `counter-scope`: exact counted event(s), per-state entry versus all edges, power domain, and direction; **no automatic unit conversion**.
3. `counter-epoch`: source-specific reset/discontinuity marker; a boot ID alone cannot prove a counter persisted across that reboot.
4. `durability`: vendor-specified counter retention after host reboot, component power-off, and full site power removal.
5. `autonomous-coverage`: firmware, hardware-local, thermal, watchdog, manual and externally triggered edges.
6. `atomicity`: an event is counted with the physical occurrence, including power loss at the boundary.
7. `integrity`: anti-rollback and authorization properties; distinguish transport authenticity from counter completeness.
8. `gap reporting`: wrap, overwrite, clear, unreadable, replacement, out-of-order snapshot and sample-loss semantics.
9. `time provenance`: trusted bounds for when edges occurred, or a conservative observation-time upper bound.
10. `command association`: evidence linking a counted edge to an operation, if claiming completion of a particular command.

Without the complete relevant contract, remain in diagnostic-only mode and keep pending/unproven transitions quarantined. Any externally asserted contract must be validated against vendor documentation and experiments before hardware safety claims.

## Conservative sampling and recovery rules

- Identity mismatch, reset-epoch change, counter decrease, known log gap, out-of-order sample: **quarantine**.
- Observed `oper` changed while a complete edge counter remained unchanged: **quarantine**; at least one assumption is false.
- Counter rises by two and `oper` returns to its original state: **two edges are possible**, despite unchanged final state. Keep quarantined until reconciled.
- Counter rises during pending actuation with no operation ID or exclusive authority: **unattributed edges**; neither success nor exactly-once dispatch may be assumed.
- For known-but-undated edges in interval `(last_sample, new_sample]`, use the latest credible observation time when conservatively evaluating dwell and rolling windows; for multiple edges, maintain worst-case placement. This may delay transitions. It cannot retroactively prevent unobserved autonomous transitions; enforcing hardware must impose its own physical limits.
- If the counter has a bounded width, a decrease can mean wrap, reset or replacement. An unchanged saturated counter can silently hide further events. Require explicit trustworthy rollover evidence and a maximum possible edge-rate bound before inferring modulo deltas. The first experiment quarantines all decreases and values at a known counter maximum; only a verified no-undetected-wrap contract may qualify as a conditional candidate.
- Even a perfectly persistent count without individual event times cannot reconstruct whether a rolling-window rate cap was exceeded during an outage. Either hardware enforces the cap locally or the guard must preserve a conservative uncertainty interval until history expires.

## Proposed field experiment: choose two devices, different purposes

**A — Intel EEE-capable NIC with Linux `igc`:** examine `ethtool -S <iface>` for Tx/Rx LPI entry statistics and `ethtool --show-eee <iface>` for enabled capability. Test same-boot counts and link-local autonomous transitions in a controlled lab. Record driver/firmware versions. Stop short of claiming durability: power-cycle and reset tests are required and a NIC does not imply a complete device-level transition count. No arbitrary high-rate LPI-cycling stress should be performed without a hardware safety assessment.

**B — NVMe drive with SMART health:** use `nvme smart-log <device>` to observe Power Cycles, Unsafe Shutdowns and (where implemented) Thermal Management Temperature transition counts, with documented device identity and safe read-only operations. This tests lifetime-counter persistence and component binding, **not** generic per-state transition coverage. Avoid deliberate unsafe power interruption of a live drive.

**C — optional Redfish-equipped server:** inspect read-only `/redfish/v1/Systems/*`, `/redfish/v1/Managers/*/LogServices/*`, and log retention metadata. Determine whether events are complete, can be cleared, or wrap. Avoid `Reset` and `ClearLog` operations during passive reconnaissance.

Every test must be opt-in, on owned/authorized equipment, with a clear rollback and protection of workloads.

## What to request from a manufacturer

A short interface specification answering: Which exact power-state transitions increment a counter? Does it cover autonomous/firmware transitions? Is it durable across *all* power domains? Can it be cleared or overflow? What indicates its epoch? Is the read atomic? Can another actor change state independently? Does the platform enforce a cycle/dwell cap locally? Are the limits supported by a hardware lifetime specification?

## Alignment with GREEN

- `ietf-power-and-energy` -05: preserve Energy Object `id`, `source-component-id`, and existing `power-state/oper`, `power-state/admin`; the experimental augmentation remains read-only.
- Capability Discovery -03: existing supported-state identities and entry/exit times are independent of transition-cycle counts. No duplicate capability leaves.
- GREEN Framework -03: operational safety constraints remain a research topic. Use exact language from 3.5.1, 3.5.3 and appendix A.2 in future submissions.
- RFC 7460 / RFC 7326: **explicitly cite legacy state-entry statistics**. The incremental contribution is a safe-usage contract, discontinuity/epoch semantics, and controller/device interoperability.
- RFC 8343: reuse the counter-discontinuity concept rather than inventing a new reset notion with conflicting semantics.

No YANG wire model changed in this research iteration. The existing optional v0.1.4 augmentation still only reports simulated ledger status and must never be presented as hardware attestation.

## Primary references

- RFC 7460, §§5.3, 7: https://www.rfc-editor.org/rfc/rfc7460.html
- RFC 7326, power-state statistics: https://www.rfc-editor.org/rfc/rfc7326.html
- RFC 8343, `discontinuity-time`: https://www.rfc-editor.org/rfc/rfc8343.html
- RFC 8348, hardware component model: https://www.rfc-editor.org/rfc/rfc8348.html
- GREEN Framework -03: https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- GREEN Power & Energy YANG -05: https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- Power State Capability Discovery -03: https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03
- NVMe base 1.4c: https://www.nvmexpress.org/wp-content/uploads/NVM-Express-1_4c-2021.06.28-Ratified.pdf
- Linux `igc` Tx/Rx LPI register definitions: https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/igc/igc_regs.h
- Intel `igc` LPI statistics discussion: https://lists.openwall.net/netdev/2020/09/28/300
- Redfish LogService, retention and clearing: https://redfish.dmtf.org/schemas/DSP2046_2020.1.html
- Vendor example with wrapping log: https://pubs.lenovo.com/xcc3-restapi/service_bmc_event_logs_get
- Linux runtime PM: https://docs.kernel.org/power/runtime_pm.html
