"""GREEN -05 semantic mapping of physical + bounded-time experiment."""

import pytest

from green_transition_guard import Policy
from green_transition_guard.experimental_evidence_hardware import EvidenceHardwareExperiment
from green_transition_guard.experimental_hardware import SimulatedActuator
from green_transition_guard.experimental_time import Bounds, TimeEvidence
from green_transition_guard.green_projection import ADMIN_PATH, OPER_PATH, project_power_state


def t(ms):
    return TimeEvidence("boot-a", Bounds(ms, ms))


def test_projection_matches_existing_green_admin_oper_semantics(tmp_path):
    assert ADMIN_PATH == "/energy-control/energy-objects/energy-object/power-state/admin"
    assert OPER_PATH == "/energy-objects/energy-object/power-state/oper"
    policy = Policy(states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
                    min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
                    window_ms=60, max_transitions=1)
    actuator = SimulatedActuator.initialize(tmp_path / "hw.json", energy_object_id="unit-1", initial_state="on")
    g = EvidenceHardwareExperiment.initialize(tmp_path / "guard.json", actuator=actuator,
                                              policy=policy, energy_object_id="unit-1", evidence=t(0))
    identity_map = {"on": "ietf-power-and-energy:power-state-on",
                    "sleep": "ietf-power-and-energy:power-state-sleep"}
    s = project_power_state(g, identity_map)
    assert (s.requested_state_identity, s.observed_state_identity, s.transition_diagnostic) == (
        identity_map["on"], identity_map["on"], "idle")
    g.prepare(op_id="a", target="sleep", evidence=t(2))
    s = project_power_state(g, identity_map)
    assert s.differs and s.requested_state_identity == identity_map["sleep"]
    assert s.observed_state_identity == identity_map["on"] and s.transition_diagnostic == "prepared"
    g.dispatch(op_id="a", evidence=t(3))
    s = project_power_state(g, identity_map)
    assert s.observed_state_identity == identity_map["on"]
    g.reconcile(evidence=t(4))
    s = project_power_state(g, identity_map)
    assert not s.differs and s.observed_state_identity == identity_map["sleep"]


def test_projection_rejects_implicit_identityrefs(tmp_path):
    policy = Policy(states=("on", "sleep"), edges=(("on", "sleep"),),
                    min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
                    window_ms=10, max_transitions=1)
    a = SimulatedActuator.initialize(tmp_path / "hw.json", energy_object_id="e", initial_state="on")
    g = EvidenceHardwareExperiment.initialize(tmp_path / "journal.json", actuator=a, policy=policy,
                                              energy_object_id="e", evidence=t(0))
    with pytest.raises(ValueError):
        project_power_state(g, {})
