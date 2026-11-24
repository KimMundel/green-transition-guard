# GREEN Transition Guard

Some components need time between power-state changes; others may tolerate ordinary cycling without measurable wear. The [IETF GREEN use cases](https://datatracker.ietf.org/doc/html/draft-ietf-green-use-cases-02#section-2.1.4) mention possible damage to lasers and connectors. See the [manufacturer evidence](docs/manufacturer-transition-evidence.md) for the documented examples and their limits.

This repository explores a narrow question: **how can a controller respect a device's limits on power-state changes, including after a restart or controller handover?**

The code is a Python simulator. It keeps a per-device journal and checks transitions against a policy. There is also a separate fault-injection lab for uncertain physical operations, plus an experimental read-only YANG augmentation. Everything runs with fictional limits and simulated equipment.

## Try it

Requires Linux (WSL2 is fine) and Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# Run these in a fresh directory, or remove demo.guard.json first.
green-guard init --store demo.guard.json \
  --policy examples/demo_policy.json --device-id switch-01 \
  --state on --time-ms 0
green-guard request --store demo.guard.json \
  --target sleep --request-id r-1 --time-ms 5000
green-guard request --store demo.guard.json \
  --target on --request-id r-2 --time-ms 10000
green-guard status --store demo.guard.json

python -m pytest -q
```

The example policy allows three transitions in a 60-second rolling window. It also sets per-state minimum dwell times and a minimum interval between changes. The numbers are test data. `init` refuses to overwrite an existing journal.

## What it currently does

- Checks directed state transitions, minimum dwell time, minimum interval, and a sliding-window transition count. The window is `(now - window, now]`.
- Stores accepted transitions, no-ops, policy changes, and request IDs so a restarted process sees the previous history.
- Rejects stale revisions, invalid history, and backwards timestamps. Requests are idempotent by ID.
- Provides separate experiments for dispatch/reconciliation, uncertain clocks, history archives, and recovery diagnostics.
- Maps simulated operational data into an experimental YANG augmentation of the GREEN Power and Energy model. It adds read-only diagnostics; it does not change the existing `admin` or `oper` leaves.

The normal guard accepts a caller-supplied millisecond timestamp and records *accepted requests*. The physical-operation lab has a separate model for what may actually have happened to a device. Keeping those apart matters when an acknowledgement is lost.

## What has been checked

At the current verified `main` commit (`21366c8`, PR #11), [GitHub Tests](https://github.com/KimMundel/green-transition-guard/actions/runs/43723062105) passed **886 tests each on Python 3.11 and Python 3.13**. The separate [GREEN YANG checks](https://github.com/KimMundel/green-transition-guard/actions/runs/43722499805) passed with the pinned `-05` schema (14 RFC 7951 cases) and a separate published `-06` schema check (17 cases).

See [test evidence](docs/test-report.md) for the commands, versions, and CI links. These checks establish software behavior on the tested inputs. They say nothing about a particular device's safe cycling limits.

## Current limits

- No equipment is controlled. No NETCONF/RESTCONF server is provided.
- Some manufacturer restrictions and cycling-test results are documented, but none provides a verified, remotely discoverable optical cycling limit for the specific GREEN operation being simulated. Authenticated physical transition counters and trustworthy cross-reboot time remain unproven.
- Local checksums detect corruption; they do not protect against an attacker replacing the journal. HMAC witness experiments require trust managed outside the device.
- Recovery tools inspect full journals. They cannot restore or compact them safely; neither operation is enabled.

The immediate research task is to find a manufacturer-supported operating restriction that a device could actually advertise, and clarify the event and counter semantics with GREEN implementers. Qualification numbers must not be copied into YANG as operating limits. The experimental YANG model may change after that discussion.

## Where to look

- [Documentation index](docs/README.md) - technical notes grouped by topic
- [Semantics](docs/semantics.md) - exact window, replay, and rejection rules
- [GREEN alignment](docs/green-alignment.md) - overlap with current drafts and RFCs
- [Manufacturer evidence matrix](docs/manufacturer-transition-evidence.md) - published values and their fit for a transition capability
- [YANG experiment](docs/yang-augmentation-experiment.md) - schema and instance evidence
- [Tests and evidence](docs/test-report.md) - reproducible checks and limitations
- [Open work](docs/roadmap.md) - research questions and engineering dependencies

The project is an independent experiment. It has no IETF status or hardware-safety claim. Issues and PRs with documented hardware constraints, counter semantics, or counterexamples to the model are particularly useful.
