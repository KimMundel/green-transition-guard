"""Read-only semantic projection onto the GREEN Power & Energy YANG -05 model.

This is a review aid. It does not emit a YANG instance document or access
NETCONF/RESTCONF. The identity map must be supplied by a model-aware caller;
fictional 'on'/'sleep' names cannot be assumed valid identityrefs.
"""

from dataclasses import dataclass
from collections.abc import Mapping

from .experimental_hardware import HardwareTransitionExperiment
from .experimental_evidence_hardware import EvidenceHardwareExperiment


# Paths from draft-ietf-green-power-and-energy-yang-05, revision 2026-11-01.
POWER_AND_ENERGY_DRAFT = "draft-ietf-green-power-and-energy-yang-05"
ADMIN_PATH = "/energy-control/energy-objects/energy-object/power-state/admin"
OPER_PATH = "/energy-objects/energy-object/power-state/oper"


@dataclass(frozen=True)
class PowerStateProjection:
    energy_object_id: str
    requested_state_identity: str
    observed_state_identity: str
    transition_diagnostic: str
    differs: bool


def project_power_state(experiment: HardwareTransitionExperiment | EvidenceHardwareExperiment,
                        identity_map: Mapping[str, str]) -> PowerStateProjection:
    """Map simulator intent and feedback to existing GREEN leaves conceptually.

    The configured admin leaf may be absent in a real deployment, and the
    GREEN -05 YANG admin/oper comparison cannot convey failure reason.
    Therefore transition_diagnostic is LAB-ONLY metadata.
    """
    s = experiment.status()
    if not isinstance(identity_map, Mapping):
        raise TypeError("identity_map must be a mapping")
    names = (s["admin"], s["oper"])
    if any(name not in identity_map or not isinstance(identity_map[name], str)
           or not identity_map[name] for name in names):
        raise ValueError("each simulated state needs an explicitly verified YANG identityref")
    pending = s["pending"]
    diagnostic = "quarantined" if s["quarantine"] else (pending["phase"] if pending else "idle")
    return PowerStateProjection(s["energy_object_id"], identity_map[s["admin"]],
                                identity_map[s["oper"]], diagnostic, s["admin"] != s["oper"])
