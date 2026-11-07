# Optical control timing: repeated events are different from state dwell

Research note, 2026-11-07. The two primary sources below give actual optical
control timing information. Neither gives a laser wear-out budget, and neither
is evidence that this simulator may operate a real device.

| Source and scope | Documented timing | What it means for this experiment |
| --- | --- | --- |
| [Glenair 050-315 product brief, Rev N, p. 7](https://www.glenair.com/optoelectronic/pcb-mount-transceivers-transmitters-and-receivers/pdf/050-315.pdf), 850 nm PCB transceiver, `Tx_Disable` (pin 10) | Host systems **should** leave 10 ms between successive *assertions* of `Tx_Disable`. The control disables optical output and can reset a latched laser fault. | A manufacturer **recommendation** about one signal event. It is not a rated minimum laser-off time, a maximum number of power cycles, or a GREEN device-wide interval. |
| [Cisco NCS 2000 SVO 12.3.x, Provision Optical Safety, Table 4](https://www.cisco.com/c/en/us/td/docs/optical/ncs2000/123/b-svo-config-guide-r12-3/provision-psm-cards.html) | Automatic laser shutdown uses recovery probe pulses. The documented recovery-pulse interval range is **60-300 seconds**. | This is device-managed **optical safety** behavior. The available range does not disclose the active interval, justify a wear limit, or establish that controller-initiated power-mode changes are subject to it. |

The Glenair signal is local to a particular transceiver. Cisco's optical
safety pulses belong to a different class of event and another equipment
family. The documented 10 ms and 60-300 s values cannot be applied to the
Cisco IOS XR 26.3.1 `controller optics shutdown` feature described in the
[power-mode note](optical-power-mode-evidence-2026-11-07.md).

## Gap in current guard policy semantics

The guard's `min_interval_ms` separates **any two accepted state changes**.
It cannot express the interval between two occurrences of *one* event when
other events occur in between. Example using the Glenair signal:

```text
at 0 ms:  Tx_Disable asserted
at 1 ms:  Tx_Disable deasserted
at 9 ms:  Tx_Disable asserted again
```

The two assertions are 9 ms apart: a synthetic violation of the recommendation.
Change the last timestamp to 10 ms and the assertion-to-assertion spacing
satisfies the timing recommendation. Requiring 10 ms between **every**
assertion/deassertion would impose an additional, undocumented condition.

The Cisco ALS interval is a period between automatic recovery pulses. It is
neither a fixed policy value for every installation nor a bound on state dwell.
Before modeling ALS, an implementation must discover the effective setting,
whose physical pulse events are counted, and whether safety firmware may
restart autonomously during a controller outage.

## Offline regression fixture

`conformance/optical-cadence-evidence.json` is a manually curated source
index. The `experimental_optical_cadence.py` lab checks exact platform,
component, operation, event and purpose, then evaluates synthetic timestamp
traces. It distinguishes a *recommended minimum* from a *documented parameter
range*. A passing synthetic trace returns a descriptive diagnostic;
`hardware_authorized` is always false.

```sh
PYTHONPATH=src python -m pytest -q tests/test_experimental_optical_cadence.py
```

The module never opens a network connection or changes an optical control.
Source URLs are references, not attestations. There is no measurement of
physical transitions, no verified timestamp base, and no proof that all
autonomous events were observed.

## What to ask an optical implementer

For one part number and firmware revision:

1. Is the recommended assertion interval a functional reset requirement,
   a laser reliability limit, or both? What happens if it is violated?
2. Is a laser emission change, DSP power-mode change, or host control-line
   assertion the event that a physical cycle limit would count?
3. Does automatic laser safety probing consume the same quota as
   administrator-triggered sleep/wake, and does a hardware guard enforce it?
4. Can event counters and time evidence cover automatic, firmware and
   host-initiated switching across power loss and controller replacement?

Until those questions are answered, the YANG augmentation remains
read-only and physical actuation stays out of scope.
