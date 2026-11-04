"""RFC 7951-shaped research projection for an unvalidated YANG augmentation.

This module does not implement a standards-approved management interface.
The two journals are both SIMULATED and time evidence is caller asserted.
Real YANG identityrefs must be checked against the official module tree.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .experimental_evidence_hardware import EvidenceHardwareExperiment, _validate


YANG_MODULE = "green-transition-guard-experimental"
YANG_REVISION = "2026-11-04"
BASE_MODULE = "ietf-power-and-energy"
BASE_REVISION = "2026-11-01"
MAX_U64 = (1 << 64) - 1
IDENTITY_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.-]*$")


def _u64(value: int) -> str:
    if type(value) is not int or not 0 <= value <= MAX_U64:
        raise ValueError("value cannot be encoded as YANG uint64")
    return str(value)


def _simulated_ledger_status(controller: dict[str, Any], actuator: dict[str, Any]) -> str:
    if (controller["energy_object_id"] != actuator["energy_object_id"]):
        return "divergent-simulation"
    if (controller["counter"] == actuator["counter"] and
            controller["state"] == actuator["state"]):
        return "matched-simulation"
    pending = controller["pending"]
    if pending is None or pending["phase"] == "prepared":
        return "divergent-simulation"
    counter = controller["counter"] + 1
    if (actuator["counter"] != counter or len(actuator["events"]) != counter or
            actuator["state"] != pending["target"]):
        return "divergent-simulation"
    edge = actuator["events"][-1]
    if (edge["counter"] == counter and edge["kind"] == "managed" and
            edge["id"] == pending["op_id"] and edge["from"] == pending["from"] and
            edge["to"] == pending["target"]):
        return "pending-confirmation-simulation"
    return "divergent-simulation"


def project_experimental_ietf_json(experiment: EvidenceHardwareExperiment,
                                   identity_map: Mapping[str, str]) -> dict[str, Any]:
    """Emit a proposed operational instance for offline discussion.

    This is deliberately read-only: it does not write the existing GREEN
    admin/oper leaves, issue commands or alter the simulator's state.
    uint64 values use RFC 7951's string JSON encoding.
    """
    if not isinstance(experiment, EvidenceHardwareExperiment):
        raise TypeError("EvidenceHardwareExperiment expected")
    with experiment.store.lock():
        controller = experiment.store.read()
        policy = _validate(controller)
        actuator = experiment.actuator.snapshot()
        if not isinstance(identity_map, Mapping):
            raise TypeError("identity_map must be a mapping")
        # All declared states need explicit mappings, including inactive
        # states that appear in dwell restrictions. Reject ambiguous aliases.
        if (set(identity_map) != set(policy.states) or
                any(type(v) is not str or IDENTITY_REF.fullmatch(v) is None
                    for v in identity_map.values()) or
                len(set(identity_map.values())) != len(identity_map)):
            raise ValueError("explicit distinct module-qualified identityrefs required")
        # Pending and current states are guaranteed by the validated
        # policy journal; fail closed if an unexpected state appears.
        if controller["state"] not in identity_map or (
            controller["pending"] is not None and
            controller["pending"]["target"] not in identity_map
        ):
            raise ValueError("missing mapped operational state")

        phase = controller["pending"]["phase"] if controller["pending"] else "idle"
        safe = {
            "operation-phase": phase,
            "simulated-ledger-status": _simulated_ledger_status(controller, actuator),
            "clock-evidence-kind": (
                "asserted-absolute-bounds" if controller["last_evidence"]["trusted_absolute"]
                is not None else "local-epoch-bounds"
            ),
            "confirmed-edge-count": _u64(controller["counter"]),
            "applied-limits": {
                "minimum-interval-ms": _u64(policy.min_interval_ms),
                "window-ms": _u64(policy.window_ms),
                "maximum-transitions": _u64(policy.max_transitions),
                "dwell-restriction": [
                    {"state": identity_map[state],
                     "minimum-dwell-ms": _u64(policy.min_dwell_ms[state])}
                    for state in policy.states
                ],
            },
        }
        if controller["quarantine"] is not None:
            safe["quarantine-reason"] = controller["quarantine"]
        return {
            "ietf-power-and-energy:energy-objects": {
                "energy-object": [
                    {
                        "id": controller["energy_object_id"],
                        "green-transition-guard-experimental:transition-safety": safe,
                    }
                ]
            }
        }
