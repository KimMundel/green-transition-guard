# Tests and evidence

This page records results for the **GitHub `main` branch after PR #8**. Older per-release test counts live in Git history. Current tests are reproducible with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

The runtime targets Linux or WSL2 because journal locking uses `fcntl`.

## Automated runs

| Check | Observed result | GitHub run |
| --- | --- | --- |
| Linux / Python 3.11 | 534 passed | [Tests #19](https://github.com/KimMundel/green-transition-guard/actions/runs/42316078109) |
| Linux / Python 3.13 | 534 passed | [Tests #19](https://github.com/KimMundel/green-transition-guard/actions/runs/42316078109) |
| GREEN YANG -05 compilation | `pyang 2.7.1` and `yanglint 2.1.30` passed | [Official GREEN YANG #4](https://github.com/KimMundel/green-transition-guard/actions/runs/42316078149) |
| RFC 7951 JSON instances | 5 valid accepted, 9 invalid rejected for expected errors | [Official GREEN YANG #4](https://github.com/KimMundel/green-transition-guard/actions/runs/42316078149) |

The YANG CI job records the published draft source bytes, module fingerprints, compiler versions and stderr. It uses `draft-ietf-green-power-and-energy-yang-05` and the experimental augmentation in `yang/`. The test corpus is under `conformance/yang-instances/`, with a manifest of SHA-256 hashes. The workflow evidence artifacts have limited retention; the run and validation scripts remain available in the repository.

## Covered behavior

The Python tests exercise dwell/interval/window boundaries, request-ID replay, policy changes, journal restarts, concurrent writers, and corruption detection. Separate test suites cover simulated dispatch/acknowledgement failure, time uncertainty, storage I/O faults, archive verification, lineage comparisons and HMAC receipt handling. The YANG workflow adds parser/compiler and instance checks against actual published module dependencies.

Some demos can be run independently:

```bash
PYTHONPATH=src python3 examples/run_hardware_demo.py
PYTHONPATH=src python3 examples/run_evidence_hardware_demo.py
PYTHONPATH=src python3 examples/run_yang_projection_demo.py
```

## What this evidence does not establish

These are process-level simulations and synthetic instances. They do not establish safe values for any commercial component, timing across a real power outage, authenticated physical transition counts, crash durability on a particular device, or compatibility with a live NETCONF/RESTCONF implementation. The HMAC example verifies supplied inputs; it does not provide an independently trusted witness service.

The software deliberately refuses journal compaction or restoration. A passing test suite is a useful regression signal for the simulator; it cannot authorize hardware control.
