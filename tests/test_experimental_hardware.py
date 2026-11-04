"""Crash and actuator-ledger tests; simulated devices only."""
import json

import pytest

from green_transition_guard import Policy, InvalidSnapshot
from green_transition_guard.experimental_hardware import (
    ActuatorMismatch, HardwareTransitionExperiment, InjectedCrash, SimulatedActuator,
)
from green_transition_guard.storage import wrap


def policy(*, max_transitions=3, window_ms=100, dwell=0, interval=0):
    return Policy(states=("on", "sleep", "off"),
                  edges=(("on", "sleep"), ("sleep", "on"), ("on", "off"), ("off", "on")),
                  min_dwell_ms={"on": dwell, "sleep": dwell, "off": dwell},
                  min_interval_ms=interval, window_ms=window_ms, max_transitions=max_transitions)


def setup(tmp_path, p=None):
    hw = SimulatedActuator.initialize(tmp_path / "hardware.json", energy_object_id="eo-linecard-3", initial_state="on")
    guard = HardwareTransitionExperiment.initialize(tmp_path / "guard.json", actuator=hw, policy=p or policy(),
                                                    energy_object_id="eo-linecard-3", entered_at_ms=0)
    return guard, hw


def restart(g, hw):
    return HardwareTransitionExperiment.open(g.store.path, actuator=hw)


def round_trip(g, op_id, target, t):
    assert g.prepare(op_id=op_id, target=target, at_ms=t).reason == "prepared"
    assert g.dispatch(op_id=op_id, at_ms=t).reason == "acknowledged"
    assert g.reconcile(at_ms=t).reason == "verified"


def test_admin_oper_split_and_explicit_physical_verification(tmp_path):
    g, hw = setup(tmp_path)
    d = g.prepare(op_id="req-1", target="sleep", at_ms=5)
    assert (d.admin, d.oper, d.phase) == ("sleep", "on", "prepared")
    assert hw.snapshot()["state"] == "on"
    d = g.dispatch(op_id="req-1", at_ms=5)
    assert (d.admin, d.oper, d.reason) == ("sleep", "on", "acknowledged")
    assert hw.snapshot()["state"] == "sleep"
    d = g.reconcile(at_ms=7)
    assert (d.admin, d.oper, d.reason) == ("sleep", "sleep", "verified")
    assert g.status()["events"][0]["at_ms"] == 7  # conservative confirmation timestamp


def test_crash_before_dispatch_mark_is_abortable(tmp_path):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    with pytest.raises(InjectedCrash):
        g.dispatch(op_id="r", at_ms=6, crash_at="before_mark")
    recovered = restart(g, hw)
    assert recovered.status()["pending"]["phase"] == "prepared"
    assert hw.snapshot()["counter"] == 0
    assert recovered.abort_prepared(op_id="r").reason == "aborted-before-dispatch"
    assert recovered.status()["oper"] == "on"


def test_crash_after_dispatch_mark_remains_unresolved(tmp_path):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    with pytest.raises(InjectedCrash):
        g.dispatch(op_id="r", at_ms=6, crash_at="after_mark")
    recovered = restart(g, hw)
    assert hw.snapshot()["counter"] == 0
    assert recovered.dispatch(op_id="r", at_ms=7).reason == "dispatch-unavailable"
    assert recovered.reconcile(at_ms=8).reason == "unresolved"
    assert recovered.prepare(op_id="other", target="sleep", at_ms=9).reason == "busy"
    assert recovered.abort_prepared(op_id="r").reason == "abort-unavailable"


@pytest.mark.parametrize("point,phase", [
    ("after_effect", "may-have-dispatched"), ("after_ack", "acknowledged")
])
def test_recover_physical_change_without_retransmit(tmp_path, point, phase):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    with pytest.raises(InjectedCrash):
        g.dispatch(op_id="r", at_ms=6, crash_at=point)
    assert hw.snapshot()["counter"] == 1
    g2 = restart(g, hw)
    assert g2.status()["pending"]["phase"] == phase
    assert g2.status()["oper"] == "on"
    assert g2.dispatch(op_id="r", at_ms=7).reason == "dispatch-unavailable"
    assert g2.reconcile(at_ms=9).reason == "verified"
    assert g2.status()["oper"] == "sleep"
    assert hw.snapshot()["counter"] == 1


def test_lost_acknowledgement_can_be_reconciled_after_timeout(tmp_path):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=10)
    g.dispatch(op_id="r", at_ms=11, crash_at=None)
    assert g.timeout(op_id="r").reason == "unresolved"
    assert g.prepare(op_id="r2", target="sleep", at_ms=12).reason == "busy"
    assert restart(g, hw).reconcile(at_ms=13).reason == "verified"


def test_counter_increase_without_state_change_detects_two_physical_edges(tmp_path):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    with pytest.raises(InjectedCrash):
        g.dispatch(op_id="r", at_ms=5, crash_at="after_mark")
    hw.external_edge(event_id="firmware-off", target="off")
    hw.external_edge(event_id="firmware-on", target="on")
    assert hw.snapshot()["state"] == "on"
    assert hw.snapshot()["counter"] == 2
    assert restart(g, hw).reconcile(at_ms=15).reason == "unresolved"
    assert g.status()["oper"] == "on"
    assert g.prepare(op_id="r2", target="sleep", at_ms=16).reason == "busy"


def test_external_transition_before_new_request_quarantines(tmp_path):
    g, hw = setup(tmp_path)
    hw.external_edge(event_id="firmware-1", target="sleep")
    assert g.prepare(op_id="r1", target="sleep", at_ms=10).reason == "physical-divergence"
    assert g.status()["quarantine"] == "physical-divergence"
    hw.external_edge(event_id="firmware-2", target="on")
    assert g.prepare(op_id="r2", target="sleep", at_ms=20).reason == "physical-divergence"


def test_external_transition_between_reservation_and_actuation(tmp_path):
    g, hw = setup(tmp_path)
    assert g.prepare(op_id="r", target="sleep", at_ms=10).reason == "prepared"
    hw.external_edge(event_id="firmware-1", target="off")
    assert g.dispatch(op_id="r", at_ms=11).reason == "hardware-mismatch"
    assert g.status()["pending"]["phase"] == "unresolved"
    assert hw.snapshot()["counter"] == 1
    assert g.reconcile(at_ms=12).reason == "unresolved"


def test_simulated_actuator_idempotence_but_controller_retries_never_reinvoke(tmp_path):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=3)
    g.dispatch(op_id="r", at_ms=3)
    assert hw.apply(op_id="r", target="sleep", expected_state="on", expected_counter=0)["counter"] == 1
    with pytest.raises(ActuatorMismatch):
        hw.apply(op_id="r", target="off", expected_state="on", expected_counter=0)
    assert hw.snapshot()["counter"] == 1
    assert g.dispatch(op_id="r", at_ms=4).reason == "dispatch-unavailable"
    assert g.reconcile(at_ms=5).reason == "verified"


def test_second_controller_does_not_override_pending_operation(tmp_path):
    g, hw = setup(tmp_path)
    assert g.prepare(op_id="one", target="sleep", at_ms=2, expected_revision=0).allowed
    other = restart(g, hw)
    assert other.prepare(op_id="two", target="off", at_ms=3).reason == "busy"
    g.dispatch(op_id="one", at_ms=4)
    assert other.reconcile(at_ms=5).allowed
    assert g.prepare(op_id="three", target="on", at_ms=6, expected_revision=0).reason == "stale-revision"


def test_verified_transition_dwell_and_interval_begin_at_confirmation(tmp_path):
    g, hw = setup(tmp_path, policy(dwell=10, interval=12))
    assert g.prepare(op_id="one", target="sleep", at_ms=9).reason == "min-dwell"
    g.prepare(op_id="one", target="sleep", at_ms=10)
    g.dispatch(op_id="one", at_ms=10)
    g.reconcile(at_ms=30)
    d = g.prepare(op_id="two", target="on", at_ms=39)
    assert d.reason == "min-dwell" and d.retry_at_ms == 42
    assert g.prepare(op_id="two", target="on", at_ms=42).allowed


def test_rate_quota_survives_restarts_and_exact_boundary(tmp_path):
    g, hw = setup(tmp_path, policy(max_transitions=1, window_ms=100))
    round_trip(g, "one", "sleep", 10)
    g = restart(g, hw)
    denied = g.prepare(op_id="two", target="on", at_ms=109)
    assert denied.reason == "rate-limit" and denied.retry_at_ms == 110
    assert g.prepare(op_id="two", target="on", at_ms=110).reason == "prepared"
    g.dispatch(op_id="two", at_ms=110)
    assert restart(g, hw).reconcile(at_ms=111).reason == "verified"


def test_noop_has_no_hardware_effect_and_replay_safe(tmp_path):
    g, hw = setup(tmp_path)
    assert g.prepare(op_id="noop", target="on", at_ms=1).reason == "no-change"
    round_trip(g, "move", "sleep", 2)
    assert g.prepare(op_id="noop", target="on", at_ms=3).reason == "replay"
    assert g.prepare(op_id="noop", target="off", at_ms=4).reason == "op-id-collision"
    assert hw.snapshot()["counter"] == 1


def test_pending_replay_collision_and_abort(tmp_path):
    g, hw = setup(tmp_path)
    assert g.prepare(op_id="r", target="sleep", at_ms=1).reason == "prepared"
    assert g.prepare(op_id="r", target="sleep", at_ms=2).reason == "pending-replay"
    assert g.prepare(op_id="r", target="off", at_ms=3).reason == "op-id-collision"
    assert g.abort_prepared(op_id="r").reason == "aborted-before-dispatch"
    assert g.prepare(op_id="r", target="sleep", at_ms=4).reason == "prepared"


def test_clock_regression_and_corrupted_journal_fail_closed(tmp_path):
    g, hw = setup(tmp_path)
    assert g.prepare(op_id="noop", target="on", at_ms=9).allowed
    assert g.prepare(op_id="r", target="sleep", at_ms=8).reason == "clock-regression"
    path = tmp_path / "guard.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["payload"]["oper"] = "off"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(InvalidSnapshot):
        restart(g, hw)


def test_corrupted_hardware_journal_fails_closed(tmp_path):
    g, hw = setup(tmp_path)
    path = hw.store.path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["payload"]["counter"] = 2
    path.write_text(json.dumps(wrap(data["payload"])), encoding="utf-8")
    with pytest.raises(InvalidSnapshot):
        g.prepare(op_id="r", target="sleep", at_ms=10)


def test_new_instance_requires_fresh_hardware_journal(tmp_path):
    g, hw = setup(tmp_path)
    hw.external_edge(event_id="firmware", target="off")
    with pytest.raises(ValueError):
        HardwareTransitionExperiment.initialize(tmp_path / "other.json", actuator=hw, policy=policy(),
                                                 energy_object_id="eo-linecard-3", entered_at_ms=0)


def test_wrong_energy_object_prevents_reconciliation(tmp_path):
    g, hw = setup(tmp_path)
    other_hw = SimulatedActuator.initialize(tmp_path / "other-hardware.json", energy_object_id="different", initial_state="on")
    assert HardwareTransitionExperiment.open(g.store.path, actuator=other_hw).prepare(
        op_id="r", target="sleep", at_ms=1).reason == "physical-divergence"
    assert g.status()["quarantine"] == "physical-divergence"


def test_write_failure_before_dispatch_marker_never_calls_actuator(tmp_path, monkeypatch):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    def disk_full(_payload):
        raise OSError("simulated disk full")
    with monkeypatch.context() as m:
        m.setattr(g.store, "save", disk_full)
        with pytest.raises(OSError):
            g.dispatch(op_id="r", at_ms=6)
    assert hw.snapshot()["counter"] == 0
    assert restart(g, hw).status()["pending"]["phase"] == "prepared"


def test_controller_commit_failure_during_reconciliation_recovers(tmp_path, monkeypatch):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=2)
    with pytest.raises(InjectedCrash):
        g.dispatch(op_id="r", at_ms=2, crash_at="after_effect")
    with monkeypatch.context() as m:
        m.setattr(g.store, "save", lambda _p: (_ for _ in ()).throw(OSError("disk failure")))
        with pytest.raises(OSError):
            g.reconcile(at_ms=3)
    recovered = restart(g, hw)
    assert recovered.status()["oper"] == "on"
    assert recovered.reconcile(at_ms=4).reason == "verified"
    assert hw.snapshot()["counter"] == 1


def test_actuator_storage_failure_remains_dispatch_possible(tmp_path, monkeypatch):
    g, hw = setup(tmp_path)
    g.prepare(op_id="r", target="sleep", at_ms=5)
    with monkeypatch.context() as m:
        m.setattr(hw.store, "save", lambda _p: (_ for _ in ()).throw(OSError("hardware disk full")))
        with pytest.raises(OSError):
            g.dispatch(op_id="r", at_ms=5)
    assert hw.snapshot()["counter"] == 0
    assert restart(g, hw).status()["pending"]["phase"] == "may-have-dispatched"
    assert restart(g, hw).reconcile(at_ms=6).reason == "unresolved"


def test_randomized_confirmation_quota_with_recovery(tmp_path):
    import random
    g, hw = setup(tmp_path, policy(max_transitions=3, window_ms=55, interval=4, dwell=4))
    rng = random.Random(20261104)
    t = 0
    for n in range(110):
        t += rng.randint(2, 17)
        current = g.status()["oper"]
        target = "on" if current == "sleep" else "sleep"
        op_id = f"r-{n}"
        result = g.prepare(op_id=op_id, target=target, at_ms=t)
        if result.reason == "prepared":
            fault = "after_effect" if n % 4 == 0 else None
            if fault:
                with pytest.raises(InjectedCrash):
                    g.dispatch(op_id=op_id, at_ms=t, crash_at=fault)
            else:
                assert g.dispatch(op_id=op_id, at_ms=t).reason == "acknowledged"
            if n % 3 == 0:
                g = restart(g, hw)
            assert g.reconcile(at_ms=t).reason == "verified"
        elif result.reason not in ("min-dwell", "min-interval", "rate-limit"):
            pytest.fail(f"unexpected rejection: {result.reason}")
        events = g.status()["events"]
        active = [e for e in events if t - 55 < e["at_ms"] <= t]
        assert len(active) <= 3
        assert g.status()["counter"] == hw.snapshot()["counter"]
