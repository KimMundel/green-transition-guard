# Tests and evidence

This page records verified results through **`main` at `21366c8` (PR #11)**. Earlier test counts live in Git history. Current tests are reproducible with:

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
| Linux / Python 3.11 | **886 passed** | [Tests on main](https://github.com/KimMundel/green-transition-guard/actions/runs/43723062105) |
| Linux / Python 3.13 | **886 passed** | [Tests on main](https://github.com/KimMundel/green-transition-guard/actions/runs/43723062105) |
| Published GREEN YANG -05 | Compiler checks; 5 valid and 9 invalid RFC 7951 cases accepted/rejected as expected | [Official YANG on PR #11](https://github.com/KimMundel/green-transition-guard/actions/runs/43722499805) |
| Published GREEN YANG -06 | Separate compiler check; **17** RFC 7951 cases validated | [Official YANG on PR #11](https://github.com/KimMundel/green-transition-guard/actions/runs/43722499805) |

The YANG workflow validates the pinned `-05` draft and experimental augmentation, then compiles `-06` separately. The `-05` corpus is pinned by hashes; the `-06` run records its source fingerprints without an independent fixed release digest. The run retains source bytes, compiler output and the instance results as short-lived artifacts. See [GREEN -06 validation](yang-06-validation.md) and the scripts for reproducibility.

## Covered behavior

The Python tests exercise dwell/interval/window boundaries, request-ID replay, policy changes, journal restarts, concurrent writers, and corruption detection. Separate test suites cover simulated dispatch/acknowledgement failure, time uncertainty, storage I/O faults, archive verification, lineage comparisons, HMAC receipt handling and offline optical evidence-scope analyzers. The YANG workflow adds parser/compiler and instance checks against actual published module dependencies.

Some demos can be run independently:

```bash
PYTHONPATH=src python3 examples/run_hardware_demo.py
PYTHONPATH=src python3 examples/run_evidence_hardware_demo.py
PYTHONPATH=src python3 examples/run_yang_projection_demo.py
```

## What this evidence does not establish

These are process-level simulations and synthetic instances. They do not establish safe values for any commercial component, timing across a real power outage, authenticated physical transition counts, crash durability on a particular device, or compatibility with a live NETCONF/RESTCONF implementation. The HMAC example verifies supplied inputs; it does not provide an independently trusted witness service.

The software deliberately refuses journal compaction or restoration. A passing test suite is a useful regression signal for the simulator; it cannot authorize hardware control.
