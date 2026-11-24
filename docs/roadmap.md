# Open work

The next useful result is a **manufacturer-specified operating limit that could populate a GREEN capability**. Publicly documented test counts and firmware timing are useful evidence, but they have different meanings from operational transition limits. See the [manufacturer evidence matrix](manufacturer-transition-evidence.md).

## Near term

1. **Collect manufacturer answers.** For a named part and revision, ask whether switching limits exist, which operation they apply to, whether hardware/firmware enforces them, and whether the vendor can publish the value. A confirmed absence of a needed restriction is also useful evidence.
2. **Keep three operations separate.** Laser `Tx_Disable`/enable, module low/high power transitions, and removal/restoration of module power can have different costs and restrictions. Prioritize optical emitters and thermal control (VCSEL, DFB, EML, TEC, laser drivers), and management paths such as CMIS and SFF-8472 when supported by the specific product.
3. **Monitor the GREEN mailing-list discussion.** On November 23, Benoit Claise asked whether vendors have data to populate power-transition limit fields. His position is to defer new YANG leaves until the source and interpretation of the values are clear. Record subsequent vendor/operator responses before revisiting standards work.
4. **Preserve the simulator's open questions.** Track actual physical edges separately from requests and acknowledgements; account for firmware-initiated changes, restart and counter discontinuities. No real-device enforcement is established.

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
with implementer review. PR #10 merged and passed Linux CI.

## Manufacturer evidence review (2026-11-23)

- Juniper MX204 documents a 60-second wait for physical PSU power operations; this is the clearest public fixed operating restriction found so far.
- Glenair documents 10 ms between successive `Tx_Disable` assertions; this is signal-event spacing, rather than generic state residence.
- Cisco MDS documents remotely managed transceiver power control and a public qualification claim without a numeric operational limit.
- Ferrotec has public thermoelectric-cycling results; Arista has automatic transceiver recovery behavior. Neither supplies a generic optical dwell limit.
- Tark publishes an OptoTEC power-cycling qualification protocol. Its detailed report is confidential and its figures are excluded from the public repository until written publication permission is granted.
- XGS-PON has configured state durations, but these are protocol parameters with 125-microsecond frame units.

**Open:** determine which, if any, of these constraints vendors are willing and able to publish as per-component capabilities. Avoid presenting qualification conditions as device-protection thresholds.

## Current direction after IETF 127 (2026-11-23)

The November 18 GREEN discussion raised doubts about whether a generic power-transition limit can be populated with real vendor values. Participants expressed different views about how reliably devices protect themselves from excessive switching. There is no established requirement here for a new generic YANG restriction leaf. See the [IETF 127 GREEN agenda](https://datatracker.ietf.org/doc/agenda-127-green/) and [session recording](https://recordings.conf.meetecho.com:8080/#q=GREEN&selected=IETF127-GREEN-20261118-2200).

**Project decision:** pause proposals for `min-residency-time`, transition quotas, or other new GREEN capability leaves. The existing simulator and read-only augmentation remain experimental. A qualified test count, an unpublished vendor value, or the absence of a declared limit must never be interpreted as a device-enforceable operating restriction. Keep hardware capabilities, operator policy, and observed transition history separate.

Benoit posted ["Limits on Power State Transitions?"](https://mailarchive.ietf.org/arch/browse/green/) to the GREEN list on November 23. He asked whether equipment vendors **have data suitable for populating transition-limit capabilities** and said he prefers to defer a YANG leaf until the source data can be mapped reliably. He also noted that some vendors may possess values without agreeing to document them. The meeting participants' views on internal device protection and the need for a model were mixed; no WG consensus is claimed here.

**Next checkpoint:** collect replies to that mailing-list question and any publishable, part-specific vendor limits. Benoit invited independent findings from this project, so keep a concise public evidence table ready for the discussion. Any future capability proposal would require known units, event semantics, a source of authority and a reason an external controller needs the value. No new YANG restriction fields are planned at present.

## Already implemented on `main`

- Persistent simulated transition journal; dwell, interval, and rolling-quota checks.
- Request replay handling, policy epochs, one-way window/budget seals, and bounded-identity experiments.
- Simulated dispatch uncertainty, cross-reboot time tests, and storage fault injection.
- Read-only checkpoint/archive/lineage diagnostics and an HMAC witness integration example.
- Experimental read-only YANG augmentation; pinned `-05` schema and 14 instances, plus separate published `-06` schema and 17 instances passed GitHub CI in PR #11.

Tests and limitations: [test report](test-report.md).

## Blocking work before any real-device control

- Manufacturer-provided limits and a verified component identity.
- Reliable clock evidence across resets and power loss.
- A trustworthy way to distinguish physical changes from commands and acknowledgements, including manual/firmware transitions.
- Authorization, authenticated state, and recovery from a lost or rolled-back journal.
- Storage bounds and power-loss testing on actual hardware.

History compaction, restored operation, and independent witness infrastructure remain out of scope until those requirements are grounded. The full journal is retained.
