"""The bridge must preserve GREEN -05 intended vs observed state semantics."""
import pytest

from green_transition_guard import Policy
from green_transition_guard.experimental_hardware import HardwareTransitionExperiment, SimulatedActuator
from green_transition_guard.green_projection import (ADMIN_PATH, OPER_PATH, POWER_AND_ENERGY_DRAFT,
                                                    project_power_state)


def test_paths_reference_existing_green_draft_leaves():
    assert POWER_AND_ENERGY_DRAFT == "draft-ietf-green-power-and-energy-yang-05"
    assert ADMIN_PATH == "/energy-control/energy-objects/energy-object/power-state/admin"
    assert OPER_PATH == "/energy-objects/energy-object/power-state/oper"


def test_projection_requires_explicit_identity_mapping_and_preserves_divergence(tmp_path):
    actuator = SimulatedActuator.initialize(tmp_path / "device.json", energy_object_id="line-card", initial_state="on")
    guard = HardwareTransitionExperiment.initialize(
        tmp_path / "controller.json", actuator=actuator,
        policy=Policy(states=("on", "sleep"), edges=(("on", "sleep"),),
                      min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
                      window_ms=100, max_transitions=1),
        energy_object_id="line-card", entered_at_ms=0)
    with pytest.raises(ValueError):
        project_power_state(guard, {})
    # These are deliberately illustrative placeholders, not registered IETF identity names.
    names = {"on": "example:ON", "sleep": "example:SLEEP"}
    idle = project_power_state(guard, names)
    assert idle.requested_state_identity == idle.observed_state_identity == "example:ON"
    assert idle.transition_diagnostic == "idle"
    guard.prepare(op_id="req", target="sleep", at_ms=1)
    prepared = project_power_state(guard, names)
    assert prepared.differs and prepared.transition_diagnostic == "prepared"
    guard.dispatch(op_id="req", at_ms=1)
    acknowledged = project_power_state(guard, names)
    assert acknowledged.differs and acknowledged.observed_state_identity == "example:ON"
    guard.reconcile(at_ms=3)
    verified = project_power_state(guard, names)
    assert not verified.differs and verified.requested_state_identity == "example:SLEEP"
