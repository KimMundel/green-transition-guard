# Pulsed-laser lifetime evidence and GREEN scope

Research note, 2026-11-07. Only offline, synthetic comparisons are implemented.

## A quantitative optical-emission example

The ePhotonics C1Y-808F-3000Q-VH(1-20) industrial 808 nm QCW diode stack
has supplier-published **mode-dependent expected pulse life**. Its product
page lists these figures at a stated 22 C case temperature:

| Pulse width | Frequency | Duty | Expected shots | Peak power (table) | Source check |
| --- | --- | --- | --- | --- | --- |
| 5 ms | 20 Hz | 10% | 30,000,000 | 3,000 W | Agreement |
| 20 ms | 5 Hz | 10% | 15,000,000 | 3,000 W | Agreement |
| 100 ms | 2 Hz | 20% | 15,000,000 | 1,500 W | **Conflict** |

The same page's "Key features" section reports **1,200 W** for the 100 ms
mode. The research adapter refuses to compare even synthetic counts with
that ambiguous mode. The vendor datasheet or clarification would be required.
The site describes *expected lifetime* with an optical-output-degradation
endpoint in its FAQ. This remains a published estimate under specified
conditions and supplies no maximum permitted laser switching rate.

Source: [ePhotonics product page](https://ephotonics.com/product/808nm-3000w-vertical-laser-diode-stack/),
"Specifications", "Key features", and "FAQs" (accessed 2026-11-07).

## Other cycle domains

- [IEC 62572-3:2016](https://webstore.iec.ch/en/publication/24202) defines
  *qualification methods* for telecommunications laser modules. A
  [public table preview](https://www.iteh.fr/catalog/standards/iec/effbdaa2-4ed5-4b0f-a3e4-6e74818792d2/iec-62572-3-2016)
  mentions **20,000 power cycles** in the initial qualification of cooled
  modules. A separate [IEC 62149-3:2023 preview](https://www.standards.iteh.ai/catalog/standards/iec/445cd287-d848-415d-b7fb-076fe66b9128/iec-62149-3-2023)
  names this as a *thermoelectric cooler* power-cycle test. These are
  qualification conditions. Consult licensed standards for authoritative
  test conditions and edition differences.
- [Thorlabs optical shutters](https://www.thorlabs.de/newgrouppage9.cfm?objectgroup_id=927&pn=SH05)
  report a typical **1,000,000 mechanical shutter actuations** and separate
  steady/burst pulse-frequency conditions. The laser can continue emitting
  while the shutter blocks its beam.
- [SFP-DD mating durability](mechanical-durability-and-green-capabilities.md)
  concerns physically inserting or removing modules, another distinct event.

## Software boundary

`conformance/pulsed-laser-lifetime.json` contains three transcribed product
modes. `experimental_pulsed_laser_lifetime.py` compares invented counts only
when product, component, event, pulse width, frequency, duty, case temperature
and synthetic history coverage match exactly. Contradictory source fields
suppress numeric comparisons. All assessments have
`green_power_state_capability=False` and `hardware_authorized=False`.

An industrial QCW pulse is a different event from Cisco IOS XR's optical
transceiver administrative sleep. None of these numbers establishes a
telecommunications optical-transceiver safe cycling limit. No YANG model or
physical actuator changes are proposed.

The unresolved primary question for GREEN implementers is whether a specific
transceiver model and firmware has a manufacturer-declared operational limit
on a named power-state transition, and how evidence for autonomous transitions,
restarts, counter resets and timestamps can be made trustworthy.
