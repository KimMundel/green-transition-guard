"""Read-only example of a proposed RFC7951-shaped GREEN augmentation."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from green_transition_guard.model import Policy
from green_transition_guard.experimental_time import Bounds, TimeEvidence
from green_transition_guard.experimental_hardware import SimulatedActuator
from green_transition_guard.experimental_evidence_hardware import EvidenceHardwareExperiment
from green_transition_guard.experimental_yang_projection import project_experimental_ietf_json


with TemporaryDirectory() as base:
    directory = Path(base)
    actuator = SimulatedActuator.initialize(directory / "actuator.json",
                                            energy_object_id="demo-device-1", initial_state="on")
    policy = Policy(states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
                    min_dwell_ms={"on": 1000, "sleep": 1000}, min_interval_ms=1000,
                    window_ms=60000, max_transitions=3)
    guard = EvidenceHardwareExperiment.initialize(
        directory / "controller.json", actuator=actuator, policy=policy,
        energy_object_id="demo-device-1", evidence=TimeEvidence("boot-1", Bounds(0, 0)),
    )
    mapping = {"on": "ietf-power-and-energy:power-state-on",
               "sleep": "ietf-power-and-energy:power-state-sleep"}
    print(json.dumps(project_experimental_ietf_json(guard, mapping), indent=2))
    print("NOTE: unvalidated experimental JSON shape; no real hardware evidence")
