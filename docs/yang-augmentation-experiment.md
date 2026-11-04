# Experimental GREEN YANG augmentation (v0.1.4)

Status: **design and unit-test experiment; NOT YANG-compiled, standards-approved,
manufacturer-certified, or deployable**. Checked against the named nodes in
`draft-ietf-green-power-and-energy-yang-05` (published 2026-11-02, embedded
YANG revision `2026-11-01`) on 2026-11-04.

## Why this is a narrow addition

The existing `ietf-power-and-energy` operational list is:

`/energy-objects/energy-object` (read-only, keyed by `id`).

The same draft defines power-state `oper` in that operational list and
power-state `admin` in the separate `/energy-control` configuration tree.
The experiment **does not augment or alter** those leaves, power caps,
measurement accuracy, energy readings or Energy Object identifiers.

Its YANG file, `yang/green-transition-guard-experimental@2026-11-04.yang`,
augments only `/eo:energy-objects/eo:energy-object` with a read-only
`transition-safety` container. The namespace is under `urn:example:` to avoid
representing this as an IETF-registered model. No writable leaves or RPCs.

## Experimental data fields

- `operation-phase`: local guard journal phase, separate from GREEN oper.
- `quarantine-reason`: present only if automatic operations are quarantined.
- `simulated-ledger-status`: explicit *simulation* match, pending independent
  confirmation, or discrepancy. Does not authenticate hardware evidence.
- `clock-evidence-kind`: local clock epoch versus caller-*asserted* absolute
  bounds. Does not authenticate time.
- `confirmed-edge-count`: only transitions reconciled in the local guard log.
  In particular it excludes unreconciled physical edges and external events.
- `applied-limits`: exact policy currently used by the simulator: minimum
  interval, rolling-window duration, count cap and per-state dwell limits.
  They are **fictional experiment values**, not vendor capabilities.

The list `dwell-restriction/state` uses an `identityref` based on the existing
`eo:power-state` identity. A caller must map all toy states explicitly to
valid official or vendor-derived identities. The Python code validates map
shape and uniqueness, but **does not prove the identities exist**. That needs
an actual YANG instance validator with official modules.

All YANG `uint64` values are encoded as JSON strings (RFC 7951); overflow is
rejected rather than silently truncated.

## Relation to other active GREEN work

- `draft-claise-green-capability-discovery-03`: relevant for supported power
  states, per-state power, and entry/exit time characteristics. The proposed
  per-state *minimum residence* restriction is distinct from entry latency.
  A normative model for manufacturer limits likely belongs alongside
  discoverable capabilities; placement requires GREEN WG review.
- `draft-swepcarl-green-controller-yang-00`: preliminary controller model;
  our guard stays device-authoritative and does not duplicate controller data.
- `draft-ietf-green-framework-03`: leaves transition-frequency safety and
  duty-cycle limits uncovered (section 3.5.1).
- RFC 8341/NACM and RFC 6241 + RFC 8040 remain the mechanisms for access
  control and immediate NETCONF/RESTCONF errors. Our diagnostics do not
  define a proprietary error transport.

## Validation gate: intentionally fails closed until official sources exist

```bash
python scripts/validate_yang.py --modules /path/to/official-yang-modules
```

The directory must contain at minimum the exact published
`ietf-power-and-energy@2026-11-01.yang` and its imported modules including
`ietf-hardware` (RFC 8348) and `iana-power-and-energy` from the same current
GREEN draft (plus each transitive dependency). `pyang` must be available;
`yanglint` is run when installed. A missing compiler or dependency is
`UNVERIFIED`, not `PASS`.

The environment used to build v0.1.4 could not fetch the official source or
install `pyang` due to disabled outbound DNS. **Neither compilation against
real dependencies nor live NETCONF/RESTCONF/JSON instance validation has
been completed.** The test suite checks projection behavior and the offline
validation gate only.

## Production blockers

1. Real YANG compiler + upstream module integration and drift checks.
2. Trusted hardware counter provenance, reset semantics and extra external
   transitions; the simulated ledger is not attested.
3. Validated, bounded time sources after full device power loss.
4. Correct vendor-supplied safety limits, emergency policy and authorization.
5. GREEN WG decisions on native module vs capability augmentation, and
   error/reconciliation semantics.

Sources:

- https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03
- https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- https://datatracker.ietf.org/doc/html/draft-swepcarl-green-controller-yang-00
- https://www.rfc-editor.org/rfc/rfc7951
