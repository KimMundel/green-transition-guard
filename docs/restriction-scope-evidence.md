# Restriction scope: three different kinds of evidence

Research snapshot: 2026-11-07. This note accompanies the local
`conformance/restriction-evidence.json` corpus. Source claims were transcribed
for comparison; the program cannot authenticate a document or a device.

The hardware question remains narrow: **which documented restriction could a
GREEN controller discover or enforce without guessing the component, event,
or source of authority?**

| Source | What the source establishes | What it does not establish |
| --- | --- | --- |
| [Juniper MX204 power instructions](https://www.juniper.net/documentation/us/en/hardware/mx204/topics/topic-map/mx204-connecting-to-power.html) | Wait at least 60 seconds after turning a PSU **off** before turning it back **on**, and after turning it **on** before turning it **off**. These are two physical-PSU maintenance instructions. | A remotely managed laser-cycle limit, a validated power-state counter, or a limit for other PSU models. |
| [Cisco IOS XR 26.3.x optics controller guide](https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5500/interfaces/26xx/configuration/guide/b-interfaces-hardware-component-cg-ncs5500-26xx/configuring-controllers.html) | Selected NCS 5500 platforms with release 26.3.1 expose admin sleep and `Power Mode: High/Low` optics readback. | A maximum switching rate, minimum dwell, lifetime laser endurance, or evidence of every intervening physical transition. |
| [ITU-T G.9807.1 (2023), Amendment 1 (2025)](https://www.itu.int/epublications/publication/itu-t-g-9807-1-2023-amd-1-2025-05), §C.16.1.2 | `Iaware` is an OLT-controlled **minimum** aware-state interval. `Ilowpower` is an OLT-controlled **maximum** low-power interval. Both are measured in 125 μs frames. | A fixed numerical timer without its negotiated/configured value, or a generic wear limit for pluggable optical modules. |

The Juniper example is the first *fixed numerical, manufacturer-documented*
restriction in this corpus. Its scope is a PSU undergoing a physical power
procedure. In a simulation of that exact operation, the two 60-second rules
have the same mathematical shape as two state-specific minimum dwell times.
That mathematical match is only a research observation. The current guard has
no way to identify or control the physical MX204 PSU.

The XGS-PON parameters are useful for a separate reason: they demonstrate that
minimum and maximum residence times can both matter. The current guard only
models a **minimum** residence time. It uses whole milliseconds, while eight
125 μs frames equal one millisecond. Converting by rounding would silently
alter the standard's exact value. The research code rejects such conversions.
Neither parameter is a manufacturer-defined cycle-endurance guarantee.

## Reproducible scope check

`experimental_restriction_evidence.py` reads a small local JSON corpus and
compares it against an explicitly declared platform, component, operation,
state and purpose. It reports one of the following:

- An exact *simulation* mapping for a fixed, compatible minimum residence time.
- An applicable source with an unknown parameter value or a bound the guard
  cannot represent.
- A component, operation or purpose mismatch.
- A readback with no numerical restriction.

Every result has `hardware_authorized=False`. A reported simulation value is
never a device-control permission. The manifest is curated research input; it
is neither a signed capability declaration nor a live discovery interface.

To run its tests:

```sh
python -m pytest -q tests/test_experimental_restriction_evidence.py
```

## Evidence still needed

A vendor-specific, remotely controllable optical module would be a stronger
next example. We need its exact PID/revision, firmware, rated physical edges,
minimum durations or lifetime budget, counter coverage (including autonomous
activity), and a credible source for power-loss continuity. Until then, a
power-mode readback and an operator-issued `shutdown` remain distinct from a
verified transition history.

No hardware experiments or network commands were run for this note.
