# GREEN standards traceability — checked 2026-11-04

**Status:** research-only mapping against published Internet-Drafts. They are
works in progress, not finalized standards. Our own hardware simulator is
neither a GREEN implementation nor an IETF-approved module.

## Canonical overlap and boundaries

| Specification | Current reference | What we reuse | What remains experimental here |
|---|---|---|---|
| GREEN framework | `draft-ietf-green-framework-03`, 2026-11-02 | Terminology, Energy Objects, requirements context for transition constraints | Rate/dwell/cycle-safety enforcement and fail-closed recovery |
| GREEN Power & Energy YANG | `draft-ietf-green-power-and-energy-yang-05`, 2026-11-02; YANG module revision 2026-11-01 | Read/write **admin** intent on an Energy Object and read-only **oper** state, separate monitoring and control trees | Diagnostic phases, pending durable operations, rejection reason details |
| Power State Capability Discovery | `draft-claise-green-capability-discovery-03`, 2026-10-27 | Static power-state support per RFC 8348 hardware component via RFC 9196 capability augmentation; entry/exit times to/from `power-state-on` | Allowed direct edges, transition-frequency constraints, duty/cycle counters. The draft explicitly leaves those out |
| Controller YANG | `draft-swepcarl-green-controller-yang-00`, 2026-10-16 | Controller collection and audit/provenance context | Device-side physical enforcement; controller work is incomplete and evolving |
| GREEN terminology | `draft-ietf-green-terminology-03`, 2026-10-30 | GREEN vocabulary and Power State terms | Device-specific guard policy |
| GREEN use cases | `draft-ietf-green-use-cases-02`, 2026-08-07 | Motivation and operational scenarios | Exact hardware safety semantics and conformance cases |

WG draft list: https://datatracker.ietf.org/wg/green/documents/

### Exact paths from the Power & Energy YANG -05 draft

- Requested state (configuration intent):
  `/energy-control/energy-objects/energy-object/power-state/admin`
- Reported observed state (operational):
  `/energy-objects/energy-object/power-state/oper`
- Both trees correlate entries by an Energy Object `id`; the control `id`
  is a leafref with `require-instance false`.
- The `admin` and `oper` values are YANG `identityref` values. Our toy strings
  (`on`, `sleep`) are internal simulation names. **Never send them as YANG
  instances without an explicit validated identity mapping.**
- `admin != oper` indicates outstanding intent in the draft's model. The
  draft describes that difference as a transition in progress; it has no
  separate indication for permanent failure or uncertain completion.
  Additional diagnostics need a reviewed augmentation or management errors.
- A successful configuration write does **not** prove a physical hardware
  transition happened. This simulator only advances `oper` after independent
  simulated hardware evidence is reconciled.

`src/green_transition_guard/green_projection.py` is a semantic adapter for
review; it deliberately emits no YANG/NETCONF/RESTCONF instance and invents
no wire-level nodes.

### Capability Discovery -03 separation

The discovery draft augments **RFC 9196** system capabilities, associated
with **RFC 8348** hardware components, to report supported Power States and
per-state entry/exit times relative to `power-state-on`.

It explicitly leaves direct low-power-to-low-power transitions and additional
transition restrictions outside scope. A future guard extension should reuse
these supported identities, and avoid re-introducing `max-exit-time`,
`typical-exit-time`, `max-entry-time`, and `typical-entry-time`.

Our experimental minimum dwell is a time *restriction*, and is distinct from
entry/exit latency, CPU idle target residency, and hardware wear guarantees.

## Mature IETF protocols and security machinery to reuse

- **RFC 7950** — YANG 1.1 syntax and identityrefs.
- **RFC 8342** — NMDA datastores. The GREEN Power & Energy draft deliberately
  uses separate administrative/operational leaves rather than the single-leaf
  NMDA arrangement discussed in its introduction.
- **RFC 8348** — Hardware Management YANG component inventory.
- **RFC 9196 / 9195** — System capabilities and instance data, used by the
  discovery draft.
- **RFC 6241 / RFC 8040** — NETCONF/RESTCONF structured error handling; use
  `error-app-tag`/`error-info` for immediate rejection instead of creating
  a proprietary failure protocol. Asynchronous failure still needs a way to
  be observed after an accepted configuration write.
- **RFC 8341** — NACM access control for sensitive writable state.
- **RFC 7326 / 7460 / 7461** — Earlier EMAN work; preserve compatibility
  context without copying MIB fields into our own schema.

## Tentative YANG placement options (NO YANG module committed yet)

1. **Read-only capability augmentation** on the discovered hardware
   component: static, manufacturer-backed transition restrictions. Requires
   agreeing on ownership, units, per-edge/per-state scope, and verification.
2. **Read-only operational diagnostics** on the existing monitored GREEN
   Energy Object: pending/unresolved/verified state, conservative cycle
   accounting, and clock quality if useful. Avoid duplicating `oper`.
3. Use existing **NETCONF/RESTCONF error structures** for pre-acceptance
   failures; define interop behavior for late failures separately.

A YANG module must be checked against the actual published source with pyang
or yanglint before calling it valid. These tools are absent from this current
container environment; a speculative unvalidated schema would risk drift.

## Open interoperability decisions

- Which GREEN identityref identifies each relevant physical power state?
- Is the safety cap vendor firmware policy, administrator configuration, or
  device-advertised capability? Some sources may conflict.
- What is an accountable **physical edge**? An attempted API call, a power
  rail change, a verified stable state, or a vendor lifetime counter?
- How should physical transitions occurring outside the controller appear?
- Can trusted time bounds and a durable hardware counter be supplied by real
  platforms, especially across full power loss?
- How can the controller learn `UNRESOLVED` without conflating it with the
  base draft's ordinary admin/oper transition-in-progress interpretation?
- Does the Controller YANG design team add a related model before our draft?

## Primary sources

- https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03
- https://datatracker.ietf.org/doc/html/draft-swepcarl-green-controller-yang-00
- https://datatracker.ietf.org/doc/html/draft-ietf-green-terminology-03
- https://datatracker.ietf.org/doc/html/draft-ietf-green-use-cases-02
- https://www.rfc-editor.org/rfc/rfc6241.html
- https://www.rfc-editor.org/rfc/rfc8040.html
- https://www.rfc-editor.org/rfc/rfc8341.html


## v0.1.3 alignment delta (2026-11-04)

The new bounded-time physical-edge simulator adds **no on-wire GREEN nodes**.
`project_power_state` now accepts both hardware-lab experiments and uses the
same existing `admin`/`oper` paths with explicit identityref mappings. It
keeps error reasons, pending operations, counter provenance, and clock
uncertainty in local diagnostics. These are candidates for optional operational
augmentation following actual YANG validation and working-group review.

See `docs/yang-augmentation-proposal.md` for the narrow diagnostics proposal;
`docs/hardware-counter-provenance.md` for missing real-device guarantees.
No YANG compiler or official source download was available in this sandbox,
so **YANG validation remains pending**. The referenced published IETF drafts
were reviewed for their named nodes and boundaries.


## v0.1.4: optional experimental operational augmentation

The uncompiled `yang/green-transition-guard-experimental@2026-11-04.yang`
augments `/eo:energy-objects/eo:energy-object`. Its configuration is
read-only, its namespace explicitly experimental, and its data clearly
labeled as simulator-derived. Existing GREEN Power State admin/oper leaves,
Capability Discovery values and Controller YANG data remain unchanged.
Details and missing validation gates: `docs/yang-augmentation-experiment.md`.

## v0.1.5: legacy EMAN count semantics reviewed

RFC 7460 `eoPowerStateEnterCount` (Counter32) already counts visits to each
Power State since device reset, paired with `eoPowerStateTotalTime` and the
reason field `eoPowerStateEnterReason`. RFC 7326 also covers per-state
statistics. GREEN YANG -05's cumulative **energy** values are distinct
from **transition-entry** counts. Source durability and completeness across
power loss have no universal guarantee. Reuse the legacy semantic precedent;
research epoch/discontinuity and provenance instead of inventing another
unqualified event counter. See `docs/hardware-counter-evidence-2026-11-04.md`.
No GREEN/YANG wire schema changes in v0.1.5.

## v0.1.6 vendor counter interface review

`docs/vendor-counter-adapters.md` records direct Linux igc and NVMe SMART
references. Their source-specific metrics cannot be identified with a GREEN
`power-state/oper` change or RFC 7460 `eoPowerStateEnterCount` without an
explicit, validated mapping to the same Energy Object and set of states.
The augmentation remains unchanged: synthetic confirmed-edge-count describes
our internal lab journal alone, with no claim of hardware attestation.
