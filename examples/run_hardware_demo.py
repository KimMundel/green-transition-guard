"""Demonstrate three crash/physical-verification outcomes with temporary files."""
import json
import tempfile
from pathlib import Path

from green_transition_guard import Policy
from green_transition_guard.experimental_hardware import (
    HardwareTransitionExperiment, InjectedCrash, SimulatedActuator,
)


def policy():
    return Policy(states=("on", "sleep", "off"),
                  edges=(("on", "sleep"), ("sleep", "on"),
                         ("on", "off"), ("off", "on")),
                  min_dwell_ms={"on": 0, "sleep": 0, "off": 0},
                  min_interval_ms=0, window_ms=60000, max_transitions=3)


def scenario(label, fault, extra_edges=False):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)
        hw = SimulatedActuator.initialize(path / "hw.json", energy_object_id="card-01", initial_state="on")
        g = HardwareTransitionExperiment.initialize(path / "ctrl.json", actuator=hw,
                                                    policy=policy(), energy_object_id="card-01", entered_at_ms=0)
        g.prepare(op_id="example-op", target="sleep", at_ms=100)
        try:
            g.dispatch(op_id="example-op", at_ms=101, crash_at=fault)
        except InjectedCrash:
            pass
        if extra_edges:
            hw.external_edge(event_id="firmware-off", target="off")
            hw.external_edge(event_id="firmware-on", target="on")
        g = HardwareTransitionExperiment.open(path / "ctrl.json", actuator=hw)
        result = g.reconcile(at_ms=102)
        return {"case": label, "result": result.reason,
                "oper": g.status()["oper"], "pending": g.status()["pending"] is not None,
                "physical_edges": hw.snapshot()["counter"]}


if __name__ == "__main__":
    cases = [scenario("crash after dispatch mark", "after_mark"),
             scenario("crash after physical effect", "after_effect"),
             scenario("unobserved extra physical cycles", "after_mark", extra_edges=True)]
    print(json.dumps(cases, indent=2))
