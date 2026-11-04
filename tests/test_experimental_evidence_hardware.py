"""Combined physical-edge and bounded-time fault-injection oracle (simulation)."""

import json
import random

import pytest

from green_transition_guard import Policy, InvalidSnapshot
from green_transition_guard.experimental_evidence_hardware import EvidenceHardwareExperiment
from green_transition_guard.experimental_hardware import InjectedCrash, SimulatedActuator
from green_transition_guard.experimental_time import Bounds, TimeEvidence
from green_transition_guard.storage import wrap


def t(boot, low, high=None, abs_low=None, abs_high=None):
    return TimeEvidence(boot, Bounds(low, high if high is not None else low),
                        None if abs_low is None else Bounds(abs_low, abs_high if abs_high is not None else abs_low))


def p(*, max_transitions=2, window=100, dwell=0, interval=0):
    return Policy(states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
                  min_dwell_ms={"on": dwell, "sleep": dwell},
                  min_interval_ms=interval, window_ms=window, max_transitions=max_transitions)


def setup(tmp_path, policy=None, init=None):
    hw = SimulatedActuator.initialize(tmp_path / "hw.json", energy_object_id="eo-1", initial_state="on")
    guard = EvidenceHardwareExperiment.initialize(tmp_path / "evidence.json", actuator=hw, policy=policy or p(),
                                                  energy_object_id="eo-1", evidence=init or t("boot-a", 0))
    return guard, hw


def restart(guard, hw):
    return EvidenceHardwareExperiment.open(guard.store.path, actuator=hw)


def move(guard, op_id, target, now):
    assert guard.prepare(op_id=op_id, target=target, evidence=now).reason == "prepared"
    assert guard.dispatch(op_id=op_id, evidence=now).reason == "acknowledged"
    assert guard.reconcile(evidence=now).reason == "verified"


def test_basic_physical_confirmation_and_green_admin_oper_split(tmp_path):
    guard, hw = setup(tmp_path)
    a = guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5))
    assert a.allowed and a.oper == "on" and a.admin == "sleep"
    assert hw.snapshot()["counter"] == 0
    assert guard.dispatch(op_id="a", evidence=t("boot-a", 6)).reason == "acknowledged"
    assert guard.status()["oper"] == "on"
    assert guard.reconcile(evidence=t("boot-a", 10)).reason == "verified"
    assert guard.status()["oper"] == "sleep"
    assert hw.snapshot()["counter"] == 1
    assert guard.status()["events"][0]["verified"]["boottime"] == {"low_ms": 10, "high_ms": 10}


def test_same_boot_window_and_interval_boundaries(tmp_path):
    guard, hw = setup(tmp_path, p(max_transitions=1, window=100, interval=12, dwell=0))
    move(guard, "a", "sleep", t("boot-a", 10))
    assert restart(guard, hw).prepare(op_id="b", target="on", evidence=t("boot-a", 21)).reason == "min-interval-unproven"
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-a", 22)).reason == "rate-limit-unproven"
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-a", 109)).reason == "rate-limit-unproven"
    move(guard, "b", "on", t("boot-a", 110))
    assert guard.status()["counter"] == 2


def test_cross_boot_unknown_elapsed_preserves_quota(tmp_path):
    guard, hw = setup(tmp_path, p(max_transitions=1, window=100))
    move(guard, "a", "sleep", t("boot-a", 10))
    guard = restart(guard, hw)
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 10)).reason == "rate-limit-unproven"
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 200000)).reason == "rate-limit-unproven"
    assert guard.status()["counter"] == hw.snapshot()["counter"] == 1


def test_cross_boot_bounded_trusted_clock_allows_when_proven(tmp_path):
    guard, _ = setup(tmp_path, p(max_transitions=1, window=100), init=t("boot-a", 0, abs_low=1000))
    move(guard, "a", "sleep", t("boot-a", 10, abs_low=1010, abs_high=1015))
    # 1110-1015=95: plausible physical edge still within the window.
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 5, abs_low=1110, abs_high=1120)).reason == "rate-limit-unproven"
    # 1115-1015=100: provably expired at the half-open boundary.
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 10, abs_low=1115, abs_high=1125)).reason == "prepared"


def test_missing_historical_absolute_cannot_be_repaired_after_reboot(tmp_path):
    guard, _ = setup(tmp_path, p(max_transitions=1, window=100))
    move(guard, "a", "sleep", t("boot-a", 5))
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 12, abs_low=100000)).reason == "rate-limit-unproven"
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 100012, abs_low=200000)).reason == "rate-limit-unproven"


def test_min_dwell_uses_lower_bound_and_fails_closed_on_cross_boot(tmp_path):
    guard, _ = setup(tmp_path, p(dwell=20))
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 19, 21)).reason == "min-dwell-unproven"
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 21)).reason == "prepared"


def test_min_dwell_cross_boot_without_absolute_is_unprovable(tmp_path):
    guard, _ = setup(tmp_path, p(dwell=1))
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-b", 999999)).reason == "min-dwell-unproven"


def test_min_dwell_cross_boot_with_trusted_absolute(tmp_path):
    guard, _ = setup(tmp_path, p(dwell=15), init=t("boot-a", 0, abs_low=100, abs_high=103))
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-b", 5, abs_low=117, abs_high=120)).reason == "min-dwell-unproven"
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-b", 6, abs_low=118, abs_high=121)).reason == "prepared"


def test_conflicting_independent_clock_evidence_quarantines(tmp_path):
    guard, hw = setup(tmp_path, init=t("boot-a", 100, abs_low=1000))
    bad = guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 200, abs_low=1001))
    assert bad.reason == "clock-inconsistent"
    assert guard.status()["quarantine"] == "clock-inconsistent"
    assert restart(guard, hw).prepare(op_id="b", target="sleep", evidence=t("boot-a", 300, abs_low=1100)).reason == "clock-inconsistent"
    assert hw.snapshot()["counter"] == 0


def test_crash_after_effect_then_cross_boot_reconcile_uses_new_evidence(tmp_path):
    guard, hw = setup(tmp_path, p(max_transitions=1, window=100))
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5)).reason == "prepared"
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 6), crash_at="after_effect")
    assert hw.snapshot()["counter"] == 1
    guard = restart(guard, hw)
    assert guard.reconcile(evidence=t("boot-b", 10)).reason == "verified"
    assert guard.prepare(op_id="b", target="on", evidence=t("boot-b", 110)).reason == "prepared"


def test_crash_after_mark_does_not_retry_or_release_reservation(tmp_path):
    guard, hw = setup(tmp_path)
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5)).reason == "prepared"
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 6), crash_at="after_mark")
    guard = restart(guard, hw)
    assert guard.dispatch(op_id="a", evidence=t("boot-b", 7)).reason == "dispatch-unavailable"
    assert guard.reconcile(evidence=t("boot-b", 8)).reason == "unresolved"
    assert guard.prepare(op_id="b", target="sleep", evidence=t("boot-b", 9)).reason == "busy"
    assert hw.snapshot()["counter"] == 0


def test_external_hardware_event_quarantines_before_dispatch(tmp_path):
    guard, hw = setup(tmp_path)
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 2)).reason == "prepared"
    hw.external_edge(event_id="firmware-1", target="sleep")
    assert guard.dispatch(op_id="a", evidence=t("boot-a", 3)).reason == "physical-divergence"
    assert guard.status()["quarantine"] == "physical-divergence"


def test_external_two_cycles_cannot_be_hidden_by_final_state(tmp_path):
    guard, hw = setup(tmp_path)
    hw.external_edge(event_id="firmware-sleep", target="sleep")
    hw.external_edge(event_id="firmware-on", target="on")
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 10)).reason == "physical-divergence"
    assert guard.status()["counter"] == 0
    assert hw.snapshot()["counter"] == 2


def test_disk_failure_before_dispatch_mark_prevents_hardware_call(tmp_path, monkeypatch):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with monkeypatch.context() as m:
        m.setattr(guard.store, "save", lambda _payload: (_ for _ in ()).throw(OSError("full disk")))
        with pytest.raises(OSError):
            guard.dispatch(op_id="a", evidence=t("boot-a", 2))
    assert hw.snapshot()["counter"] == 0
    assert restart(guard, hw).status()["pending"]["phase"] == "prepared"


def test_controller_commit_failure_after_physical_edge_reconciles(tmp_path, monkeypatch):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 2), crash_at="after_effect")
    with monkeypatch.context() as m:
        m.setattr(guard.store, "save", lambda _payload: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            guard.reconcile(evidence=t("boot-a", 3))
    assert restart(guard, hw).reconcile(evidence=t("boot-b", 12)).reason == "verified"
    assert hw.snapshot()["counter"] == 1


def test_revision_and_idempotency_after_reboot(tmp_path):
    guard, hw = setup(tmp_path)
    move(guard, "a", "sleep", t("boot-a", 5))
    assert restart(guard, hw).prepare(op_id="a", target="sleep", evidence=t("boot-b", 1)).reason == "replay"
    assert guard.prepare(op_id="a", target="on", evidence=t("boot-b", 2)).reason == "op-id-collision"
    assert guard.prepare(op_id="b", target="on", expected_revision=0, evidence=t("boot-b", 3)).reason == "stale-revision"
    assert guard.prepare(op_id="b", target="sleep", evidence=t("boot-b", 4)).reason == "no-change"
    assert hw.snapshot()["counter"] == 1


def test_zero_max_transitions_never_actuates(tmp_path):
    guard, hw = setup(tmp_path, p(max_transitions=0))
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5000)).reason == "rate-limit-unproven"
    assert hw.snapshot()["counter"] == 0


def test_corrupt_integrity_checked_before_recovery(tmp_path):
    guard, hw = setup(tmp_path)
    file = tmp_path / "evidence.json"
    raw = json.loads(file.read_text(encoding="utf8"))
    raw["payload"]["counter"] = 1
    file.write_text(json.dumps(wrap(raw["payload"])), encoding="utf8")
    with pytest.raises(InvalidSnapshot):
        restart(guard, hw)


def test_randomized_monotonic_dispatch_obeys_rate_and_counter(tmp_path):
    guard, hw = setup(tmp_path, p(max_transitions=3, window=50, dwell=3, interval=4))
    rng = random.Random(260413)
    at = 0
    for i in range(120):
        at += rng.randrange(1, 20)
        target = "sleep" if guard.status()["oper"] == "on" else "on"
        evidence = t("boot-a", at)
        result = guard.prepare(op_id=f"req-{i}", target=target, evidence=evidence)
        if result.reason == "prepared":
            if i % 5 == 0:
                with pytest.raises(InjectedCrash):
                    guard.dispatch(op_id=f"req-{i}", evidence=evidence, crash_at="after_effect")
            else:
                assert guard.dispatch(op_id=f"req-{i}", evidence=evidence).reason == "acknowledged"
            assert restart(guard, hw).reconcile(evidence=evidence).reason == "verified"
        else:
            assert result.reason in ("min-dwell-unproven", "min-interval-unproven", "rate-limit-unproven")
        history = guard.status()["events"]
        assert len([e for e in history if e["verified"]["boottime"]["low_ms"] > at-50]) <= 3
        assert guard.status()["counter"] == hw.snapshot()["counter"]


def test_abort_before_mark_is_safe_but_after_mark_is_unavailable(tmp_path):
    guard, hw = setup(tmp_path)
    assert guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1)).reason == "prepared"
    assert guard.abort_prepared(op_id="a").reason == "aborted-before-dispatch"
    assert guard.abort_prepared(op_id="a").reason == "abort-unavailable"
    assert hw.snapshot()["counter"] == 0
    guard.prepare(op_id="b", target="sleep", evidence=t("boot-a", 2))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="b", evidence=t("boot-a", 3), crash_at="after_mark")
    assert restart(guard, hw).abort_prepared(op_id="b").reason == "abort-unavailable"
    assert guard.timeout(op_id="b").reason == "unresolved"
    assert guard.status()["pending"]["phase"] == "unresolved"


def test_storage_fails_after_dispatch_rename_has_no_physical_edge(tmp_path, monkeypatch):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with monkeypatch.context() as m:
        # Simulates directory fsync failure after atomic replace.
        m.setattr(guard.store, "_sync_directory", lambda: (_ for _ in ()).throw(OSError("fsync error")))
        with pytest.raises(OSError):
            guard.dispatch(op_id="a", evidence=t("boot-a", 2))
    assert hw.snapshot()["counter"] == 0
    assert restart(guard, hw).status()["pending"]["phase"] == "may-have-dispatched"
    assert guard.reconcile(evidence=t("boot-a", 3)).reason == "unresolved"


def test_storage_fails_after_hardware_rename_reconcile_without_resend(tmp_path, monkeypatch):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with monkeypatch.context() as m:
        m.setattr(hw.store, "_sync_directory", lambda: (_ for _ in ()).throw(OSError("fsync error")))
        with pytest.raises(OSError):
            guard.dispatch(op_id="a", evidence=t("boot-a", 2))
    # The counter is visible in this deterministic test; real durability at
    # fsync failure is unproven and must be reconciled from trusted hardware.
    assert hw.snapshot()["counter"] == 1
    assert restart(guard, hw).reconcile(evidence=t("boot-a", 3)).reason == "verified"
    assert hw.snapshot()["counter"] == 1


def test_after_ack_crash_and_timeout_still_reconcile(tmp_path):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 2), crash_at="after_ack")
    guard = restart(guard, hw)
    assert guard.timeout(op_id="a").reason == "unresolved"
    assert guard.reconcile(evidence=t("boot-a", 3)).reason == "verified"
    assert hw.snapshot()["counter"] == 1


def test_crash_before_mark_prepared_can_be_aborted(tmp_path):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 1))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 2), crash_at="before_mark")
    assert restart(guard, hw).abort_prepared(op_id="a").reason == "aborted-before-dispatch"
    assert hw.snapshot()["counter"] == 0


def test_new_evidence_must_satisfy_pending_preparation_chronology(tmp_path):
    guard, hw = setup(tmp_path)
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5))
    path = tmp_path / "evidence.json"
    raw = json.loads(path.read_text(encoding="utf8"))
    raw["payload"]["last_evidence"] = {
        "boot_id": "boot-a", "boottime": {"low_ms": 2, "high_ms": 2},
        "trusted_absolute": None,
    }
    path.write_text(json.dumps(wrap(raw["payload"])), encoding="utf8")
    with pytest.raises(InvalidSnapshot):
        restart(guard, hw)


def test_clock_mismatch_after_physical_effect_quarantines_safely(tmp_path):
    guard, hw = setup(tmp_path, init=t("boot-a", 0, abs_low=1000))
    guard.prepare(op_id="a", target="sleep", evidence=t("boot-a", 5, abs_low=1005))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="a", evidence=t("boot-a", 6, abs_low=1006), crash_at="after_effect")
    result = restart(guard, hw).reconcile(evidence=t("boot-a", 8, abs_low=9999))
    assert result.reason == "clock-inconsistent"
    assert guard.status()["oper"] == "on"
    assert guard.status()["quarantine"] == "clock-inconsistent"
    assert hw.snapshot()["state"] == "sleep"
