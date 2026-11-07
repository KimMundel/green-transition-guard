# Mechanical durability and GREEN transition capabilities

Research note, 2026-11-07. The attached data are manually transcribed from an
industry specification. They are **not** manufacturer-specific test results and
are not device telemetry.

## A documented cycling figure, with a different event

The [SFP-DD MSA Hardware Specification, rev. 4.2](https://sfp-dd.com/wp-content/uploads/2020/08/SFP-DDrev4.2.pdf),
Appendix A.1, Table 13 (printed page 60), gives these *rated durability cycles*:

| Physical item | Rated cycles | Event being qualified |
| --- | ---: | --- |
| SFP-DD module | 50 | Mechanical insertion and removal |
| Connector/cage | 100 | Mechanical insertion and removal |

These are connector-system mechanical qualification requirements, evaluated using
EIA-364-1000 testing. Table 14 permits replacing the module after it reaches
its rated durability if the connector needs to meet a higher rating.

The numbers are design/test references. They do **not** mean that every module
fails on cycle 51, or that a deployed device should refuse a maintenance
operation at cycle 50. Neither number specifies how many times a laser may be
powered off and on. No automatic connection between mechanical wear and a
controller's power-state commands is justified.

## What the experiment checks

`conformance/mechanical-wear-qualification.json` pins the specification
revision and table location for each independently scoped item.
`experimental_wear_qualification.py` validates the references and compares
*synthetic* cycle counts at their exact form-factor, component, event and
caller-asserted instance identity. The result is descriptive only:

- A complete *synthetic* history can be compared to its qualification rating.
- A partial history, different component, replaced module or different event
  produces an incomparable result with no numeric threshold.
- `hardware_authorized` and `green_power_state_capability` remain false,
  including when the synthetic count is below the rated figure.

No physical module is sampled, and no live operation or server is exposed.
These checks do not estimate remaining service life.

## Where the information belongs

The current [GREEN Power and Energy YANG -05](https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05)
separates requested `admin` power state from reported `oper` power state.
[Capability Discovery -03](https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03)
models supported power states and entry/exit durations per physical component
using RFC 9196 and RFC 8348. Its Section 5 explicitly leaves allowed direct
transitions and other transition constraints outside the model.

A mechanical mating qualification rating would fit a hardware-asset,
maintenance or component-qualification discussion, if anyone needed to
advertise it. It is **not** a power-state transition capability. Existing
transceiver inventory representations, including Broadband Forum's
[`bbf-hardware-transceivers.yang`](https://github.com/BroadbandForum/yang/blob/master/standard/equipment/bbf-hardware-transceivers.yang),
should be examined before adding form-factor identity fields.

A future *verified* optical on/off or state-entry restriction could warrant
an optional capability linked to that same physical component. It would need,
at minimum:

1. The specific protected component and permitted transition/event scope.
2. The counted unit (requests, commanded changes, observed state entries,
   physical edges, failed attempts, or lifetime power cycles).
3. Rule semantics: interval, residence, rolling quota or lifetime budget;
   numerical value and units; fixed versus configured versus unknown.
4. Boundaries after component replacement, resets, autonomous transitions,
   and counter/discontinuity gaps.
5. Whether the device enforces the restriction locally, plus the source and
   authority for that claim.

Those are *discussion fields*, not a proposed normative YANG augmentation. The
YANG module in this repository is unchanged. Actual field placement, including
possible use of a technology-specific model, requires implementer input.

## Open evidence request

For a particular transceiver or line card that supports remote optical
shutdown/sleep, ask the supplier for a published and revisioned answer to:

- Is there a guaranteed minimum time between **physical laser off/on events**,
  or a rated count of those events over a window or a lifetime?
- Are firmware-initiated changes and faults included in the count?
- Does firmware enforce the bound independently of a controller?
- Can the device report a counter that survives the relevant power loss and
  has an explicit discontinuity epoch?
- Which exact module hardware and firmware revisions does the statement cover?

The Cisco IOS XR optics sleep example remains an **unanswered case**. The
SFP-DD mechanical table cannot fill that gap.
