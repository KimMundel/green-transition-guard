# Candidate GREEN YANG extension — interface review memo

**Original proposal memo (2026-11-04).** In v0.1.4 an optional, **uncompiled**
experimental `.yang` module is now emitted under `yang/`. The current
environment lacks `pyang` / `yanglint` and cannot fetch authoritative modules,
so the experiment is a scope discussion artifact only. See
`docs/yang-augmentation-experiment.md` for the implemented shape. It is not
an IETF-approved or deployable YANG schema.

## Reuse before extending

- Power state intent: `ietf-power-and-energy` (Power & Energy YANG -05),
  `/energy-control/energy-objects/energy-object/power-state/admin`.
- Actual state: same module, read-only
  `/energy-objects/energy-object/power-state/oper`.
- Power state identities: `identityref` based on `power-state`; use published
  identities and explicitly validate any vendor-defined derived identities.
- Device power state capabilities, per-state consumption, entry/exit timing:
  Capability Discovery -03 using RFC 9196 + RFC 8348 augmentation.
- Controller views and telemetry collection: preliminary Controller YANG -00.
- Before an administrative request is accepted, use existing NETCONF/
  RESTCONF error structures (RFC 6241 / RFC 8040) and access controls (RFC
  8341), including meaningful application-tag if agreed upon.

## Candidate #1: read-only operational diagnostics

*Potential augment target:* `ietf-power-and-energy` operational list
`/energy-objects/energy-object`, associated by the **existing** Energy Object
`id` rather than a second independent key.

Candidate optional diagnostics (exact node names unsettled):

| Information | Motivation | Caveat |
|---|---|---|
| pending/unresolved/quarantined operation phase | Distinguish normal admin/oper lag from a fault | Keep `oper` device-reported, not optimistic |
| transition counter status and epoch | Diagnose external cycles and resets | Must disclose unknown/untrusted provenance |
| time-evidence adequacy | Explain a held safety restriction | Never expose a spurious absolute retry |
| last safe rejection category | Machine-readable reason when error occurred asynchronously | Avoid duplicating NETCONF/RESTCONF synchronous errors |

*Scope restriction:* no new configuration knobs and no duplication of the
existing `admin`, `oper`, energy metrics, power caps or capability-discovery
latency leaves. Read-only fields would be protected through relevant NACM
policies and data minimization.

## Candidate #2: transition restrictions/capabilities

The original proposed standardized contribution remains frequency/dwell/
cycle limits. A device-advertised read-only capability augmentation under
Capability Discovery -03 may be more appropriate than an additional GREEN
control configuration subtree. Decision requires WG feedback on:

- Manufacturer-enforced vs administrator-configured limits.
- Per-component, per-power-state and per-transition-edge scope.
- Window-length/time units and reboot time-base semantics.
- Physical-edge vs command/attempt counting.
- Persistent counter availability, reset/epoch semantics.
- Vendor-specific extensions and legacy device behavior.

**Do not conflate:** minimum dwell time, actual entry/exit latency, CPU idle
residency hints, and verified hardware cycle lifetime guarantees.

## Proposed validation gate for a future .yang module

1. Acquire *official* source of Power & Energy -05 and Capability Discovery
   -03 modules and their actual imported dependencies; pin revision and SHA.
2. Import the exact published module names/prefixes and target schema nodes.
3. Compile with `pyang` and independently check with `yanglint` when available.
4. Produce a minimal valid instance document and validate `config false`
   placement, `leafref`/`identityref` usage and NMDA behavior.
5. Compare with current Controller YANG work and obtain GREEN implementer
   review. Keep experimental diagnostics optional and additive.

## Sources

- https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03
- https://datatracker.ietf.org/doc/html/draft-swepcarl-green-controller-yang-00
- https://www.rfc-editor.org/rfc/rfc7950.html
- https://www.rfc-editor.org/rfc/rfc6241.html
- https://www.rfc-editor.org/rfc/rfc8040.html
