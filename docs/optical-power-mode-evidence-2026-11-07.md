# Optical power-mode evidence (2026-11-07)

Status: source-based research and synthetic offline parsing. No real device was
sampled or controlled. The dates and platform names below matter; the examples
should not be generalized to other hardware, firmware, or power domains.

## Primary finding: a remotely controllable optical low-power mode

Cisco IOS XR 26.3.1 documents **admin sleep mode for optical transceivers** on
selected NCS 540 and NCS 5500 platforms. `shutdown` on an optics controller
places a supported module in low-power mode, while management access remains
available. The read-only `show controllers optics <location>` output includes
`Power Mode: High/Low` and `Laser State: On/Off`, alongside controller and
transport administrative status. This is a concrete platform for examining
intent, reported state, and potentially incomplete transition history.

| Primary source | Explicitly documented scope | Research implication |
| --- | --- | --- |
| [Cisco NCS 540, Configuring Controllers](https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5xx/interfaces/26xx/b-interfaces-hardware-component-cg-26xx-ncs540/config-controllers.html) (updated 2026-09-08) | 26.3.1; N540-24Z8Q2C-SYS and N540(X)-ACC-SYS; SFP/SFP+/SFP28/QSFP/QSFP+/QSFP-DD families | Reported power state and laser status are exposed, and administrative sleep is supported. |
| [Cisco NCS 5500, Configuring Controllers](https://www.cisco.com/c/en/us/td/docs/iosxr/ncs5500/interfaces/26xx/configuration/guide/b-interfaces-hardware-component-cg-ncs5500-26xx/configuring-controllers.html) (updated 2026-09-08) | 26.3.1; guide specifically names NCS-57C3-MOD-SYS | Same readback distinction, subject to the specified platform and optics compatibility. |

These documents **do not establish a cycling-rate limit, endurance rating,
complete physical-edge counter, cross-reboot timing guarantee, or local
hardware enforcement** for the optical module. `show controllers optics`
can report the same final `High` state before and after an undetected
`High -> Low -> High` excursion. A configured shutdown, observed laser state,
and a safely completed physical transition have different evidence requirements.

The sample status displays include device-specific identity fields (`PID`,
serial number). A captured serial is only a device assertion; separate
verification is necessary to bind it securely to a GREEN Energy Object.

## Adjacent restrictions: keep the hardware and operation scope intact

| Documented fact | Actual scope | Consequence for GREEN |
| --- | --- | --- |
| [Juniper MX204 power instructions](https://www.juniper.net/documentation/us/en/hardware/mx204/topics/topic-map/mx204-connecting-to-power.html): wait **at least 60 s after PSU on before off, and after PSU off before on** | Router power supply, physical power procedures | A genuine, *directional dwell* example for a PSU. It does not rate Cisco or Juniper optical laser cycling. |
| [Juniper 800G optics installation](https://www.juniper.net/documentation/us/en/hardware/800g-optics-cables-guide/optics/topics/topic-map/800g-optics-initial-install-config.html): wait **at least 10 s after removal before hot-swapping a transceiver** | Physical module removal/insertion | Service procedure, outside the scope of a software-issued laser `shutdown`. |
| [Juniper Junos interface `disable`](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/disable-edit-interfaces.html): laser-off behavior depends on PIC/optic | Interface admin state versus laser state | An interface-down result must not automatically be treated as proof of a laser power transition. |
| [ITU-T G.9807.1 (2023) Amendment 1 (2025)](https://www.itu.int/epublications/publication/itu-t-g-9807-1-2023-amd-1-2025-05): `Iaware` minimum ONU aware-state interval, `Ilowpower` maximum low-power interval | XGS-PON ONU protocol/power-management state machine; 125 microsecond frame units | Strong timing/state-machine precedent, with a different rationale and different state semantics from laser wear. |

A human maintenance delay can sometimes be represented mathematically by a
minimum dwell constraint, but its component and operation scope must travel
with it. There is still no primary-source optical wear or cycling quota
suitable for authorizing a GREEN laser transition in this project.

## Small offline experiment

`experimental_optics_observation.py` parses a **single saved** Cisco-style
optics readback. It compares pairs of synthetic snapshots and enforces:

- Exact field names, one command location, and bounded input; missing or
  duplicate fields fail parsing.
- Independent device, component, port, PID and serial assertions. A changed
  identity or stale sample quarantines the pair.
- Matching `High/On/Up/In Service` or `Low/Off/Administratively Down/Out Of
  Service` for a consistent reported status. Mismatches stay ambiguous.
- Exact platform/release claims for the documented 26.3.1 examples; other
  claims remain unverified.
- Every comparison remains diagnostic-only: `quarantine=True`,
  `safe_to_dispatch=False`, and `proven_physical_edges=None`.

Run tests from the repository root:

```bash
python -m pytest -q tests/test_experimental_optics_observation.py
```

The parser runs without Cisco network access. Do not put live IP addresses,
serial numbers, credentials, or unredacted operational logs into public issues.
The parser has no ability to issue optical shutdown/start commands.

## Next research question for an implementer

For a specific remotely managed optical module, ask the manufacturer to
provide the *part number, hardware revision and firmware* plus:

1. A manufacturer-rated minimum time in each power state, maximum switching
   frequency, or lifetime cycle limit, including units and applicable edges.
2. Whether administrative sleep affects laser, DSP, power rail, or only the
   interface, and which internal actions consume the rated cycle budget.
3. Whether a hardware/firmware count includes autonomous transitions, resets,
   errors and power loss, and how counter continuity can be authenticated.
4. Whether the device enforces restrictions locally when a controller is
   disconnected or another controller takes over.
5. A passive read-only access method and an authorized test environment.

Until this evidence is available, the GREEN YANG experiment should keep
operational reports separated from certified restrictions. Real-device
actuation remains blocked.

The separate [optical control cadence note](optical-control-cadence.md) records
a manufacturer-recommended 10 ms `Tx_Disable` assertion spacing for Glenair
050-315 and Cisco NCS 2000 automatic laser-safety pulse timing. Their scopes
do not supply a switching limit for this IOS XR optics sleep feature.
