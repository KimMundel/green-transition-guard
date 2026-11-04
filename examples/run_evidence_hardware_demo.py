"""No-network demonstration of the combined time + physical simulator."""

from pathlib import Path
from tempfile import TemporaryDirectory

from green_transition_guard import Policy
from green_transition_guard.experimental_evidence_hardware import EvidenceHardwareExperiment
from green_transition_guard.experimental_hardware import SimulatedActuator, InjectedCrash
from green_transition_guard.experimental_time import Bounds, TimeEvidence


def ev(boot: str, up: int, utc: int | None = None) -> TimeEvidence:
    return TimeEvidence(boot, Bounds(up, up), None if utc is None else Bounds(utc, utc))


def policy() -> Policy:
    return Policy(states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
                  min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
                  window_ms=60_000, max_transitions=1)


def create(directory: Path, initial: TimeEvidence):
    actuator = SimulatedActuator.initialize(directory / "hardware.json", energy_object_id="lab-linecard", initial_state="on")
    guard = EvidenceHardwareExperiment.initialize(directory / "guard.json", actuator=actuator,
                                                  policy=policy(), energy_object_id="lab-linecard", evidence=initial)
    return guard, actuator


def main() -> None:
    with TemporaryDirectory() as root:
        guard, hardware = create(Path(root), ev("boot-a", 0))
        first = ev("boot-a", 5_000)
        guard.prepare(op_id="a", target="sleep", evidence=first)
        try:
            guard.dispatch(op_id="a", evidence=first, crash_at="after_effect")
        except InjectedCrash:
            pass
        guard = EvidenceHardwareExperiment.open(guard.store.path, actuator=hardware)
        print("restart, physical edge verified:", guard.reconcile(evidence=ev("boot-b", 10)).reason)
        print("20 seconds since reboot verification:", guard.prepare(op_id="b", target="on",
                                                             evidence=ev("boot-b", 20_010)).reason)
        print("60 seconds since reboot verification:", guard.prepare(op_id="b", target="on",
                                                             evidence=ev("boot-b", 60_010)).reason)

    with TemporaryDirectory() as root:
        guard, hardware = create(Path(root), ev("boot-a", 0, 1_000_000))
        first = ev("boot-a", 5_000, 1_005_000)
        guard.prepare(op_id="a", target="sleep", evidence=first)
        guard.dispatch(op_id="a", evidence=first)
        guard.reconcile(evidence=first)
        guard = EvidenceHardwareExperiment.open(guard.store.path, actuator=hardware)
        print("bounded cross-reboot <60 seconds:", guard.prepare(op_id="b", target="on",
            evidence=ev("boot-b", 1, 1_064_999)).reason)
        print("bounded cross-reboot >=60 seconds:", guard.prepare(op_id="b", target="on",
            evidence=ev("boot-b", 2, 1_065_000)).reason)


if __name__ == "__main__":
    main()
