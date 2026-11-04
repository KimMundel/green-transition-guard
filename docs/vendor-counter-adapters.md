# v0.1.6 — Counter source fidelity and offline adapters

**Date:** 2026-11-04. **Status:** research-only, no sampled hardware.

## Findings grounded in maintained implementations

1. Linux `igc` maps `tx_lpi_counter` to `stats.tlpic` and `rx_lpi_counter` to
   `stats.rlpic`. Its `igc_main.c` uses `stats.tlpic += rd32(IGC_TLPIC)` and
   similarly for `RLPIC`. Therefore an `ethtool -S` reading represents a
   driver-accumulated number. The code proves the existence and meaning of
   the exported fields; it does **not** establish persistence across module
   unloading, host reboot or full power loss. Tx and Rx are distinct; Rx
   reflects the receive side of an Ethernet link. Neither maps to all GREEN
   Power State changes of a chassis or Energy Object.
2. NVMe SMART Log Identifier 02h includes `power_cycles`,
   `thm_temp1_trans_count`, and `thm_temp2_trans_count`. The power-cycle count
   describes controller power cycling. A thermal transition count may include
   vendor-specific thermal management actions or lower-power *active* states,
   not a universal on/sleep/off edge. Thermal counts saturate at `FFFFFFFFh`.
   Zero is ambiguous: the transition never occurred **or** the feature is
   unimplemented. `nvme-cli` JSON examples use the exact keys parsed here;
   output naming can differ across tool versions.
3. Linux driver-defined ethtool statistics are implementation-specific.
   Stable output across interface down/up is an API requirement, but neither
   a complete physical event history nor a global lifetime guarantee.
4. EMAN RFC 7460 already defines `eoPowerStateEnterCount` (`Counter32`) and
   `eoPowerStateTotalTime` per supported power state. Its existing design is
   the reference for the semantics of state *entry* counts. The new research
   question is continuity, provenance and enforcement across discontinuities.
5. GREEN Power/Energy YANG -05 defines `energy-objects/energy-object/id`,
   `source-component-id` and `power-state/oper`, and uses `energy-control`
   for administrative state. It does not define the full counter provenance
   contract or authorize using an unrelated NVMe/EEE count as a transition
   limit input. We make no changes to these existing paths.

## Reference interfaces

- `experimental_vendor_counters.parse_igc_ethtool_stats`: exact
  `tx_lpi_counter` or `rx_lpi_counter` from copied `ethtool -S` text.
- `experimental_vendor_counters.parse_nvme_smart_json`: exact `power_cycles`,
  `thm_temp1_trans_count`, or `thm_temp2_trans_count` from copied SMART JSON.
- `assess_offline_pair`: delegates to the existing counter-provenance gate.
  A clean numeric difference is still **diagnostic only**. All source
  contracts deliberately declare unknown durability, autonomy, epoch
  authenticity, and coverage. None can become a provisional safety source.

The parser requires *asserted* identity, boot, driver instance, or controller
counter epoch supplied by a caller. These are labels, **not** authenticated
observations. Reusing an old driver-instance label across a module reload
would disguise a discontinuity; external collection must detect such events.
No explicit claim about the hardware's retention is inferred from a Linux
boot ID. NVMe SMART alone cannot prove controller identity or a counter epoch.

### Demonstration (synthetic fixtures, no device access)

```bash
PYTHONPATH=src python3 examples/run_vendor_counter_demo.py
PYTHONPATH=src python3 -m pytest -q
```

Both printout and tests use fabricated counts for controlled boundary testing.
They are **not** samples taken from Intel or NVMe equipment.

## Opt-in, passive measurement plan for a later owned-device session

For an authorized Linux NIC, capture metadata and two snapshots without
changing power states:

```bash
ethtool -i <interface>
ethtool --show-eee <interface>
ethtool -S <interface> > igc-before.txt
cat /proc/sys/kernel/random/boot_id
# After an ordinary observation interval:
ethtool -S <interface> > igc-after.txt
```

Confirm that the interface actually uses `igc`; record PCI device ID and
module/driver version out of band. A driver reload can occur within one boot.
The adapter needs a separately established driver-instance continuity claim.

For an authorized NVMe controller, read SMART (commands vary with `nvme-cli`
version; newer clients use `nvme log smart`):

```bash
nvme smart-log /dev/nvme0 --output-format=json > nvme-before.json
# Later, without inducing any power cycling:
nvme smart-log /dev/nvme0 --output-format=json > nvme-after.json
```

Be aware that a `/dev/nvme0` path and an SNMP/NETCONF Energy Object id are
independent namespaces. Component identity must be established securely.
Sanitize controller serial numbers, BMC addresses and unique infrastructure
identifiers before sharing data. No unsafe shutdown, power interruption or
high-rate cycling should be triggered for this project.

## Follow-on gates

1. Obtain a manufacturer or platform guarantee for precisely which policy
   edges an observed counter covers, including autonomous transitions.
2. Check what resets on driver unload, hardware reset, warm reboot and full
   power removal. Record discontinuities conservatively.
3. Establish stable component identity and authenticated event-time bounds;
   count deltas alone cannot prove exactly-once command completion.
4. Determine whether the source can *enforce* physical cycle limits locally.
   A controller polling counters cannot prevent unknown autonomous events.
5. Only after implementer review, consider a **small, optional read-only**
   GREEN extension describing evidence quality/continuity. It must reference
   the existing Energy Object and avoid redefining EMAN's entry counters.

## Sources (checked 2026-11-04)

- Linux `igc` ethtool string mapping:
  https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/igc/igc_ethtool.c
- Linux `igc` register accumulation (`IGC_TLPIC`, `IGC_RLPIC`):
  https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/igc/igc_main.c
- Linux driver-statistics documentation:
  https://docs.kernel.org/networking/statistics.html
- libnvme SMART log structure and definitions:
  https://github.com/linux-nvme/libnvme/blob/master/doc/rst/types.rst
- NVMe tool JSON example:
  https://github.com/influxdata/telegraf/issues/18180
- RFC 7460, Energy Object power-state table:
  https://www.rfc-editor.org/rfc/rfc7460.html
- Current GREEN Power/Energy YANG -05:
  https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
