"""Conformance-like tests for the intentionally limited simulator semantics."""
import json
import random

import pytest

from green_transition_guard import InvalidSnapshot, Policy, Reason, TransitionGuard


def policy(*, max_transitions=3, min_interval_ms=0, dwell=0, window_ms=100) -> Policy:
    return Policy(
        states=("on", "sleep", "off"),
        edges=(("on", "sleep"), ("sleep", "on"), ("on", "off"), ("off", "on")),
        min_dwell_ms={"on": dwell, "sleep": dwell, "off": dwell},
        min_interval_ms=min_interval_ms,
        window_ms=window_ms,
        max_transitions=max_transitions,
    )


def init(tmp_path, p=None):
    return TransitionGuard.initialize(
        tmp_path / "device.guard.json", device_id="dev-1", policy=p or policy(),
        initial_state="on", entered_at_ms=0,
    )


def move(g, target, t, key=None, rev=None):
    return g.request(target=target, request_id=key or f"id-{target}-{t}",
                     at_ms=t, expected_revision=rev)


def test_accepted_path_and_revision(tmp_path):
    g = init(tmp_path)
    a = move(g, "sleep", 1)
    b = move(g, "on", 2)
    assert a.allowed and a.reason == Reason.ACCEPTED
    assert b.allowed and b.event_id == "dev-1:2"
    assert g.status()["revision"] == 2
    assert [e["to"] for e in g.history()] == ["sleep", "on"]


def test_dwell_exact_boundary(tmp_path):
    g = init(tmp_path, policy(dwell=5000))
    before = move(g, "sleep", 4999)
    assert before.reason == Reason.MIN_DWELL
    assert before.retry_at_ms == 5000
    assert move(g, "sleep", 5000).allowed
    assert move(g, "on", 9999).reason == Reason.MIN_DWELL
    assert move(g, "on", 10000).allowed


def test_interval_exact_boundary(tmp_path):
    g = init(tmp_path, policy(min_interval_ms=15))
    assert move(g, "sleep", 3).allowed
    d = move(g, "on", 17)
    assert d.reason == Reason.MIN_INTERVAL and d.retry_at_ms == 18
    assert move(g, "on", 18).allowed


def test_rate_limit_window_left_excluded(tmp_path):
    g = init(tmp_path, policy(max_transitions=2, window_ms=100))
    assert move(g, "sleep", 10).allowed
    assert move(g, "on", 20).allowed
    d = move(g, "sleep", 109)
    assert d.reason == Reason.RATE_LIMIT and d.retry_at_ms == 110
    assert move(g, "sleep", 110).allowed  # 10 is outside (10,110]
    assert len(g.history()) == 3


def test_noop_consumes_no_quota(tmp_path):
    g = init(tmp_path, policy(max_transitions=1))
    assert move(g, "on", 1).reason == Reason.NO_CHANGE
    assert move(g, "sleep", 2).allowed
    assert move(g, "sleep", 3).reason == Reason.NO_CHANGE
    assert move(g, "on", 4).reason == Reason.RATE_LIMIT
    assert g.status()["revision"] == 1


def test_max_zero_blocks_all_changes(tmp_path):
    g = init(tmp_path, policy(max_transitions=0))
    d = move(g, "sleep", 10)
    assert d.reason == Reason.RATE_LIMIT and d.retry_at_ms is None


def test_controller_restart_keeps_quota(tmp_path):
    p = tmp_path / "device.guard.json"
    g = init(tmp_path, policy(max_transitions=1))
    assert move(g, "sleep", 10).allowed
    del g
    other_controller = TransitionGuard.open(p)
    denied = move(other_controller, "on", 20)
    assert denied.reason == Reason.RATE_LIMIT
    assert move(other_controller, "on", 110).allowed


def test_two_controller_objects_see_latest_state(tmp_path):
    g = init(tmp_path)
    other = TransitionGuard.open(tmp_path / "device.guard.json")
    assert move(g, "sleep", 1, rev=0).allowed
    assert move(other, "on", 2, rev=0).reason == Reason.STALE_REVISION
    assert move(other, "on", 3, rev=1).allowed


def test_request_id_replay_even_after_later_change(tmp_path):
    g = init(tmp_path)
    first = move(g, "sleep", 1, key="command-1")
    assert move(g, "on", 2, key="command-2").allowed
    same = move(g, "sleep", 3, key="command-1", rev=0)
    assert same.allowed and same.reason == Reason.REPLAY
    assert same.event_id == first.event_id
    assert same.current_state == "on"
    assert g.status()["revision"] == 2


def test_request_id_collision_fails(tmp_path):
    g = init(tmp_path)
    assert move(g, "sleep", 1, key="once").allowed
    assert move(g, "off", 2, key="once").reason == Reason.REQUEST_ID_COLLISION
    assert g.status()["revision"] == 1


def test_clock_regression_fail_closed(tmp_path):
    g = init(tmp_path)
    assert move(g, "on", 100).reason == Reason.NO_CHANGE
    assert move(g, "sleep", 99).reason == Reason.CLOCK_REGRESSION
    assert g.status()["last_checked_ms"] == 100


def test_rejected_request_advances_clock_persistently(tmp_path):
    g = init(tmp_path, policy(dwell=5000))
    assert move(g, "sleep", 4000).reason == Reason.MIN_DWELL
    h = TransitionGuard.open(tmp_path / "device.guard.json")
    assert move(h, "sleep", 3999).reason == Reason.CLOCK_REGRESSION


def test_unsupported_edge_and_unknown_state(tmp_path):
    g = init(tmp_path)
    assert move(g, "off", 1).allowed
    assert move(g, "sleep", 2).reason == Reason.UNSUPPORTED_TRANSITION
    assert move(g, "dormant", 3).reason == Reason.UNKNOWN_STATE
    assert g.status()["state"] == "off"


def test_combined_delay_reports_latest_retry(tmp_path):
    g = init(tmp_path, policy(max_transitions=1, dwell=30, min_interval_ms=25, window_ms=100))
    assert move(g, "sleep", 30).allowed
    d = move(g, "on", 40)
    assert d.reason == Reason.MIN_DWELL
    assert d.retry_at_ms == 130  # max(dwell 60, interval 55, window 130)


def test_snapshot_corruption_fails_closed(tmp_path):
    g = init(tmp_path)
    path = tmp_path / "device.guard.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["state"] = "sleep"  # checksum deliberately wrong
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)
    with pytest.raises(InvalidSnapshot):
        move(g, "sleep", 1)


def test_unknown_schema_fails_closed(tmp_path):
    init(tmp_path)
    path = tmp_path / "device.guard.json"
    from green_transition_guard.storage import wrap
    envelope = json.loads(path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    payload["schema"] = 99
    path.write_text(json.dumps(wrap(payload)), encoding="utf-8")
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


def test_existing_snapshot_cannot_be_reset_by_initialize(tmp_path):
    g = init(tmp_path)
    assert move(g, "sleep", 1).allowed
    with pytest.raises(FileExistsError):
        init(tmp_path)
    assert g.status()["revision"] == 1


def test_policy_rejects_bad_configuration():
    with pytest.raises(ValueError):
        policy(window_ms=0)
    with pytest.raises(ValueError):
        policy(max_transitions=-1)
    with pytest.raises(ValueError):
        Policy(states=("on",), edges=(), min_dwell_ms={},
               min_interval_ms=0, window_ms=1, max_transitions=1)


def test_deterministic_randomized_window_invariant(tmp_path):
    """Acceptance is bounded for all sampled times even across controller restarts."""
    g = init(tmp_path, policy(max_transitions=3, window_ms=70, min_interval_ms=3))
    rng = random.Random(20261104)
    t = 0
    for i in range(300):
        t += rng.randint(0, 12)
        target = "on" if g.status()["state"] == "sleep" else "sleep"
        decision = move(g, target, t, key=f"random-{i}")
        events = list(g.history())
        if decision.reason == Reason.ACCEPTED:
            assert events[-1]["at_ms"] == t
        active = [e for e in events if t - 70 < e["at_ms"] <= t]
        assert len(active) <= 3
        if i % 41 == 0:
            g = TransitionGuard.open(tmp_path / "device.guard.json")


def test_noop_replay_cannot_actuate_after_state_change(tmp_path):
    g = init(tmp_path)
    assert move(g, "on", 1, key="noop-1").reason == Reason.NO_CHANGE
    assert move(g, "sleep", 2, key="move-2").allowed
    replay = move(g, "on", 3, key="noop-1")
    assert replay.reason == Reason.REPLAY and replay.current_state == "sleep"
    assert g.status()["revision"] == 1
    assert g.status()["noops"] == 1


def test_noop_request_id_collision(tmp_path):
    g = init(tmp_path)
    assert move(g, "on", 1, key="noop-1").allowed
    assert move(g, "sleep", 2, key="noop-1").reason == Reason.REQUEST_ID_COLLISION


def test_corrupted_noop_log_fails_closed(tmp_path):
    init(tmp_path)
    path = tmp_path / "device.guard.json"
    from green_transition_guard.storage import wrap
    envelope = json.loads(path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    payload["noops"] = [{"request_id": "id", "target": "sleep", "at_ms": 0, "revision": 0}]
    path.write_text(json.dumps(wrap(payload)), encoding="utf-8")
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


def test_against_independent_exhaustive_style_reference(tmp_path):
    """Cross-check the guard against a small independently written oracle."""
    p = policy(max_transitions=2, window_ms=47, min_interval_ms=4, dwell=7)
    g = init(tmp_path, p)
    rng = random.Random(83)
    state, entered, last_transition, history = "on", 0, None, []
    clock = 0
    for i in range(500):
        clock += rng.randrange(0, 20)
        target = rng.choice(p.states)
        if target == state:
            expected = Reason.NO_CHANGE
        elif (state, target) not in p.edges:
            expected = Reason.UNSUPPORTED_TRANSITION
        elif clock - entered < p.min_dwell_ms[state]:
            expected = Reason.MIN_DWELL
        elif last_transition is not None and clock - last_transition < p.min_interval_ms:
            expected = Reason.MIN_INTERVAL
        elif sum(clock - p.window_ms < timestamp <= clock for timestamp in history) >= p.max_transitions:
            expected = Reason.RATE_LIMIT
        else:
            expected = Reason.ACCEPTED
            state, entered, last_transition = target, clock, clock
            history.append(clock)
        decision = g.request(target=target, at_ms=clock, request_id=f"oracle-{i}")
        assert decision.reason == expected, (i, clock, target, expected, decision)
        assert decision.current_state == state
    assert len(g.history()) == len(history)


def _concurrent_attempt(path, req_id, queue):
    from green_transition_guard import TransitionGuard
    guard = TransitionGuard.open(path)
    decision = guard.request(target="sleep", request_id=req_id, at_ms=10, expected_revision=0)
    queue.put(decision.reason.value)


def test_concurrent_controllers_one_revision_wins(tmp_path):
    import multiprocessing
    p = policy()
    init(tmp_path, p)
    path = str(tmp_path / "device.guard.json")
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [ctx.Process(target=_concurrent_attempt, args=(path, f"c{i}", queue)) for i in range(2)]
    for process in processes:
        process.start()
    reasons = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert sorted(reasons) == sorted([Reason.ACCEPTED.value, Reason.STALE_REVISION.value])
    assert TransitionGuard.open(path).status()["revision"] == 1
