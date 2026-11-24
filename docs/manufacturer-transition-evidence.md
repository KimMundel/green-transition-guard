# Manufacturer evidence for transition restrictions

Research snapshot: 2026-11-23. This table answers a practical question raised
in the GREEN capability-discovery discussion: **which published values could
actually populate a power-state transition restriction?**

These sources cover different components and events. A qualification-test count
is a test result. A procedural wait time is an instruction for that operation.
An automated fault-recovery timer is firmware behavior. None is automatically
a generic lifetime or dwell limit for all Energy Objects.

| Source and component | Public value and event | Kind of evidence | Fit for a generic `min-residency-time` leaf? |
| --- | --- | --- | --- |
| [Juniper MX204 PSU](https://www.juniper.net/documentation/us/en/hardware/mx204/topics/topic-map/mx204-connecting-to-power.html) | Wait at least **60 s** after PSU power-off before turning it on, and after power-on before turning it off; physical power procedures. | Manufacturer operating/maintenance instruction. | **Conditional only:** mathematically a minimum residence in each PSU power condition. The documentation does not advertise a remotely discoverable limit for a GREEN-controlled Energy Object. |
| [Glenair 050-315 Rev N, p. 7](https://www.glenair.com/optoelectronic/pcb-mount-transceivers-transmitters-and-receivers/pdf/050-315.pdf) | Host **should** allow **10 ms** between successive **assertions** of `Tx_Disable` (pin 10), including fault-reset use. | Manufacturer signal-timing recommendation. | **No:** assertion-to-assertion spacing differs from minimum residence in an optical power state. |
| [Cisco MDS 9000 SFP power control](https://blogs.cisco.com/our-corporate-purpose/improving-data-center-sustainability-with-cisco-mds-9000-transceiver-power-control-capability) | Supports remote transceiver power-off for administratively shut ports. Public qualification claim reports no effect on failure rates under its tested cycling conditions; **no public numeric cycle limit**. | Manufacturer feature and qualification claim. | **No numeric value:** the public article gives neither an enforced dwell time nor a permitted transition count. |
| [Tark OptoTEC OTX/HTX](https://tark-solutions.com/thermal-technical-library/backgrounders/optotec-otx-htx-series-test-protocol) | Public protocol includes **power-cycling qualification** of thermoelectric coolers used in optoelectronics; public page gives no numeric cycle limit. | Manufacturer test protocol. | **No:** test conditions cannot be treated as operating limits. The detailed reliability report is confidential; its figures are withheld from this repository pending written permission. |
| [Ferrotec SuperTEC](https://thermal.ferrotec.com/technology/thermoelectric-reference-guide/thermalRef10/) | Cycled between **30 and 100 C** every **5 min**; all tested modules survived **at least 25,000 cycles** without failure; calculated group MTBF **68,000 cycles**. | Thermal-cycling reliability experiment on TECs. | **No:** survival and MTBF under a thermal test are neither a minimum dwell nor a guaranteed life for telecom optics. |
| [Ferrotec ValueTEC](https://thermal.ferrotec.com/technology/thermoelectric-reference-guide/thermalRef10/) | **7.5 s powered / 7.5 s off** at relatively constant temperature; about **6 million cycles** run, calculated MTBF about **30 million cycles** for these conditions. | Electrical ON/OFF cycling experiment on TECs. | **No:** test cadence and statistical MTBF are not product operating restrictions. |
| [Arista EOS, 7800R](https://www.arista.com/en/um-eos/eos-ethernet-ports) | After a power-controller fault, automatic recovery begins after **5 s**; a group of transceivers is power-cycled, with **one automatic recovery attempt**. | Firmware fault-recovery behavior. | **No:** the 5 s delay and retry cap concern fault handling. They do show why autonomous power events matter to any transition counter. |
| [ITU-T G.9807.1 (2023), Amd. 1 (2025), C.16.1.2](https://www.itu.int/epublications/publication/itu-t-g-9807-1-2023-amd-1-2025-05) | OLT-defined `Iaware` is a **minimum** Aware-state duration; `Ilowpower` is a **maximum** LowPower-state duration; units are **125 us frames**. No fixed value can be inferred without the configured parameter. | Technology-specific protocol timing parameters. | **Partial semantic match** for `Iaware` if its actual configured value and state scope are known. It is a protocol parameter, and exact sub-millisecond units need care. `Ilowpower` is a maximum, so it needs different semantics. |

## Answer to the GREEN capability question

There are useful manufacturer numbers, but **none of the published optical
examples gives a revision-specific, lifetime-derived minimum residence time
for a remotely controlled telecom transceiver**. The Juniper PSU instructions
are the clearest fixed operating restriction in this set, with a narrower
physical-maintenance scope. Cisco's published reliability claim is a useful
counterexample to assuming that ordinary, qualified power cycling necessarily
causes measurable wear.

An optional GREEN capability should distinguish:

- **Hardware restriction:** an authoritative bound applicable to a specified
  component, state or event, with units and conditions.
- **Configured protocol timer:** a parameter whose actual effective value
  must be retrieved for that device and configuration.
- **Qualification evidence:** a tested cycle count, a survival result or an
  MTBF under specified conditions; it does not set an operational limit.
- **Operational observations:** commands, notifications and physical events;
  these require separate counter-coverage and continuity semantics.

Even if a numeric bound is documented, a controller still needs evidence of
which physical changes occurred, including firmware-initiated changes, and
what happened across a reboot. The project has only simulated these cases.

## Publication boundary

This document uses publicly available manufacturer and standards material.
Vendor correspondence and non-public reliability reports are excluded.
Confidential test figures must remain out of source control and public
working-group discussions until the owner grants publication permission.

No limit in this table authorizes controlling real equipment. See also
[restriction scope](restriction-scope-evidence.md),
[optical control timing](optical-control-cadence.md), and the
[experimental guard semantics](semantics.md).
