# Hardware transition execution and reconciliation (2026-11-04)

**Status: research design, with no real actuator or hardware validation.**

## Standards context and overlap

- `draft-ietf-green-power-and-energy-yang-05` distinguishes administrative
  intended power state (`admin`) and reported operational state (`oper`). It
  exposes an intended-state configuration interface, with device-side handling.
- `draft-claise-green-capability-discovery-03` advertises supported power
  states and time-to-enter/exit values. Section 5 explicitly excludes allowed
  direct transition edges and additional transition restrictions. Section 6
  warns that supporting a power state does not imply it is currently eligible.
- `draft-ietf-green-framework-03` discusses operational cycle limits as part
  of power-state SLAs.
- Linux runtime PM has active, suspended, suspending and resuming meta-states,
  plus transient errors and device-driver callbacks. Successful callbacks
  are driver-level evidence and may not establish independently measured
  physical power.
- DMTF Redfish Reset actions have state-dependent outcomes and asynchronous
  task semantics. An accepted request may require later completion checks.
- RFC 6241 supplies `error-app-tag` and structured `error-info` for device-
  specific failure reasons; RFC 8040 transports relevant YANG errors via
  RESTCONF. Reuse these interfaces rather than inventing a parallel wire
  protocol in the first experimental YANG model.

Sources:
- https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05
- https://www.ietf.org/ietf-ftp/internet-drafts/draft-claise-green-capability-discovery-03.html
- https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03
- https://docs.kernel.org/power/runtime_pm.html
- https://redfish.dmtf.org/schemas/DSP0268_2026.1.html
- https://redfish.dmtf.org/schemas/DSP0266_1.23.1.html
- https://www.rfc-editor.org/rfc/rfc6241.html
- https://datatracker.ietf.org/doc/html/rfc8040

## Important distinction: energy economics vs. physical wear

Linux CPUIdle exposes **target residency** as an energy break-even threshold
and **exit latency** as a responsiveness constraint. These are established
concepts, and our proposed minimum-dwell policy must not misrepresent them as
manufacturer-rated hardware damage limits. Any physical wear/cycle budget
requires manufacturer evidence for the relevant component, state, edge, and
operating conditions. No such vendor-specific budget has been verified for
this prototype.

Reference: https://docs.kernel.org/admin-guide/pm/cpuidle.html

For existing GREEN admin/oper leaves, a successful administrative write may
only express requested intent. Asynchronous execution and later hardware
failures need durable operational state and event reporting. Immediate
NETCONF/RESTCONF errors address known pre-acceptance conditions; the model
must also expose late errors after an accepted configuration request.

## Required distinction: requests, attempts, outcomes

The v0.1 simulation treats a permitted logical request as an immediately
accepted state change. A physical operation has separate phases:

1. `REQUESTED`: controller submits intent with unique operation ID, target,
   expected device revision, and policy version.
2. `RESERVED`: the device-side authoritative guard checks the policy and
   **durably reserves budget** before any hardware side effect.
3. `DISPATCH_POSSIBLE`: record durable intent that a side effect may occur;
   finish storage commit **before** handing the command to firmware/driver.
4. `IN_PROGRESS`: actuator execution has begun or was acknowledged. The
   physical state might be transient. One operation must exclude competing
   requests for the same protected hardware scope.
5. `VERIFIED`: authoritative device feedback establishes the target stable
   operational state, with event time or conservative time interval.
6. `UNRESOLVED`: timeout, crash, lost acknowledgment, inconsistent readback,
   or insufficient proof. Retain the reservation and block automatic changes
   for the affected device scope pending reconciliation.

`REJECTED` is a pre-actuation policy decision with a machine-readable reason;
no command is sent. A separate `FAILED_NO_EFFECT` outcome may be possible only
when the actuator can **prove** that no physical transition took place. An
unverified failure must remain `UNRESOLVED`.

At the initial implementation stage, treat each reservation as consuming at
least one attempt quota. Vendor data may require separate limits for
transition *attempts*, *physical switching cycles*, and completed transitions.
No-op requests, repeated network messages, and retries with the same
operation ID must never trigger a second physical command.

## Crash matrix

| Failure boundary | Recovery action |
|---|---|
| Before durable reservation | No effect may have occurred if all actuator calls are properly gated |
| After reservation, before `DISPATCH_POSSIBLE` | Reservation persists; could cancel only with proof no dispatch was possible |
| After `DISPATCH_POSSIBLE`, before actual actuator call | Treat as ambiguous; may have executed when the process died |
| Hardware ACK, then crash | Unknown physical completion; query independent hardware state and counters |
| Command times out | Keep quota and a pending operation; avoid automatic re-dispatch |
| Observed target after restart | Potentially successful, but readback alone cannot prove **how many** intermediary transitions happened |
| Observed original state after restart | Do not infer zero physical cycles; device might have changed twice |
| Missing journal/clock evidence | Fail closed, with an explicit separately governed restoration process |

Store a fencing token and operation ID **at the device/firmware enforcement
boundary** if the actuator supports them. A controller-only lock cannot stop
in-flight commands that were already accepted by hardware. A distributed
control plane must have one effective device-side writer or a real consensus
and fencing mechanism; POSIX file locks on separate machines do not provide
that guarantee.

## Physical timestamp questions

Do hardware limits apply at:

- command acceptance,
- physical switching start,
- first intermediate state,
- stable destination confirmation, or
- all attempts and intermediate cycles?

A controller's request timestamp can precede actual hardware movement by an
unbounded delay. Rate and dwell guarantees must use conservatively bounded
physical event times. Where no reliable event telemetry exists, retain wider
uncertainty and block if safety cannot be established.

A state transition can create *multiple* physical cycles: for example,
`ON -> OFF -> ON` consumes two edges even when the final state equals ON.
Unknown autonomous power-management, manual switching, firmware resets, and
hardware fault responses can invalidate a controller-maintained cycle count.
The device must either count them itself or explicitly declare that its cycle
statistics cover only managed transitions.

## Safety envelope and research boundaries

- Hard manufacturer safety requirements and operator optimization policy
  should have distinct ownership. Never infer real numeric limits from the
  fictional examples in this repository.
- Model transition edges and counters per relevant hardware component or
  Power/Energy Object. Shared power domains can introduce dependencies.
- Maintain independent safety constraints for a power-off decision and any
  safety-critical wake or service-restoration action. The latter may need
  an audited override under vendor-specific rules.
- Preserve an auditable indication of `accepted`, `delayed`, `rejected`,
  `unknown-result`, and `verified` outcomes in controller and device views.
- Any proposal should align with existing GREEN `admin`/`oper` fields.
  Consider a **read-only capability augmentation**, a diagnostic status
  subtree, and optional `error-app-tag` values once semantics are agreed.
- The current prototype enforces neither firmware nor switch datapaths.

## First hardware-independent conformance scenarios

- Confirm that a simulated command ACK does not mark hardware completion.
- Inject a crash at each persistence and actuator-call boundary.
- Drop a response after the actuator executes; reject duplicate execution.
- Force a timeout and concurrent command; hold the device in `UNRESOLVED`.
- Simulate the final state returning to the initial state after two physical
  edges; test that edge counts reflect both changes.
- Simulate controller replacement during an in-flight operation.
- Simulate an autonomous firmware transition outside controller management.
- Test emergency wake precedence under an explicit separately justified
  policy and ensure an audit trail is produced.

## Go/no-go for a real adapter

Before control of any physical device, require:
1. Vendor-validated constraints and applicability per component.
2. Hardware-side exclusive command authority or a documented safe handoff.
3. Reliable physical feedback or event counters and repeatability evidence.
4. Durable storage and clock contract surviving the relevant failure cases.
5. Independent laboratory fault testing and recovery procedures.

Until then, any proposed algorithm remains an **advisory, simulation-only
experiment** and cannot certify hardware protection.


## v0.1.2 implemented fault-injection lab

The `experimental_hardware.py` module implements the phases above using two
independent `SnapshotStore` instances. The hardware model has one durable
monotonically increasing **simulated** physical-edge counter. A transaction
across both stores is intentionally absent, exposing realistic crash gaps.

| Injected boundary | Persisted controller phase | Simulated edge | Safe observed result |
|---|---|---|---|
| Before dispatch marker | `prepared` | None | Abort is possible in this lab |
| After dispatch marker | `may-have-dispatched` | None | Unresolved; automatic re-dispatch blocked |
| After hardware effect, ACK lost | `may-have-dispatched` | One | Verified from independent matching ledger |
| After ACK, before confirmation | `acknowledged` | One | `oper` advances only after reconciliation |
| Extra external OFF→ON cycles | Pending | Two | Unresolved even if final state returns to start |
| Controller persistence failure before marker | `prepared` | None | Hardware call never occurs |
| Controller persistence failure during reconciliation | `may-have-dispatched` | One | Recovery can verify later without a second command |

A real asynchronous physical actuator needs stronger fencing and event
coverage. The lab permits immediate simulated effects and uses the timestamp
of verification as a conservative event time, while real hardware may include
unbounded queues, other controllers, and spontaneous firmware changes. None
of those risks is solved by an application-level file lock.
