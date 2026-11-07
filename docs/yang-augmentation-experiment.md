# Experimental GREEN YANG augmentation

The module at [`yang/green-transition-guard-experimental@2026-11-04.yang`](../yang/green-transition-guard-experimental@2026-11-04.yang) adds a read-only `transition-safety` container to the operational Energy Object in `draft-ietf-green-power-and-energy-yang-05`. It uses an example namespace and is separate from the GREEN drafts.

The existing Power and Energy model has two relevant paths:

- `/energy-control/energy-objects/energy-object/power-state/admin`: requested power state.
- `/energy-objects/energy-object/power-state/oper`: observed power state.

The extension leaves both alone. It describes the simulator's own state: operation phase, quarantine reason, simulated ledger status, clock evidence, confirmed edge count and applied limits (dwell, interval and rolling quota).

These fields describe what the local experiment believes. They are not manufacturer capabilities. `confirmed-edge-count` depends on the simulated ledger, and the example limits were chosen for tests.

State identities need an explicit mapping from toy names such as `sleep` to the YANG identities in the actual module. The projector checks mapping shape and uniqueness, and the pinned RFC 7951 fixtures exercise real schema acceptance. All `uint64` values are serialized as JSON strings, as required by RFC 7951.

## Validation

On GitHub PR #8, the [Official GREEN YANG workflow](https://github.com/KimMundel/green-transition-guard/actions/runs/42316078149) passed against the published -05 sources:

- `pyang 2.7.1` and `yanglint 2.1.30` compiled the augmentation with its imported modules.
- `yanglint` accepted five valid and rejected nine deliberately invalid RFC 7951 instances for the intended schema reasons.
- The scripts pin the official source, extension and corpus hashes. GitHub Actions archives the source bytes and tool output for review.

To validate against a local set of official modules:

```bash
python scripts/validate_yang.py --modules /path/to/official-yang-modules
```

The directory must contain the official Power and Energy YANG -05 modules and required imports. The command fails closed if required compilers or modules are missing. For the exact automated version and corpus, inspect `.github/workflows/official-yang-smoke.yml`, `scripts/official_yang_smoke.py`, and `scripts/official_yang_instance_smoke.py`.

## Remaining questions

There is no physical device or live NETCONF/RESTCONF endpoint behind these instances. An implementation would still need verified limits, authoritative power-state feedback, trustworthy clock/counter semantics and authorization. The right standards placement also needs working-group feedback; the current augmentation is a way to test terminology and shapes.

Related reading: [GREEN alignment](green-alignment.md), [RFC 7951](https://www.rfc-editor.org/rfc/rfc7951), [Framework -03](https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03).
