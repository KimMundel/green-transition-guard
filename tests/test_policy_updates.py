"""Policy epoch migration and retention of the entire quota-relevant journal.

Simulation only. The API is not an authenticated or physical safety control.
"""

import json
import multiprocessing
import sys

import pytest

from green_transition_guard import GuardError, InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.storage import wrap


PATH = "guard.json"


def policy(*, edges=None, dwell=0, interval=0, window=100, limit=3) -> Policy:
    return Policy(
        states=("on", "sleep", "off"),
        edges=edges or (("on", "sleep"), ("sleep", "on"), ("on", "off"), ("off", "on")),
        min_dwell_ms={"on": dwell, "sleep": dwell, "off": dwell},
        min_interval_ms=interval,
        window_ms=window,
        max_transitions=limit,
    )


def init(tmp_path, p=None):
    return TransitionGuard.initialize(tmp_path / PATH, device_id="unit", policy=p or policy(),
                                      initial_state="on", entered_at_ms=0)


def request(g, state, time, key):
    return g.request(target=state, at_ms=time, request_id=key)


def update(g, new_policy, time, key="update-1", revision=0):
    return g.update_policy(new_policy=new_policy, update_id=key, at_ms=time,
                           expected_policy_revision=revision)


def rewrite(path, change):
    envelope = json.loads(path.read_text())
    payload = envelope["payload"]
    change(payload)
    path.write_text(json.dumps(wrap(payload)))


def test_legacy_journal_opens_and_remains_schema_one(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 1, "first").reason == Reason.ACCEPTED
    reopened = TransitionGuard.open(tmp_path / PATH)
    assert reopened.status()["policy_revision"] == 0
    assert reopened.policy_history() == {"initial_policy": policy().to_dict(), "updates": []}
    assert json.loads((tmp_path / PATH).read_text())["payload"]["schema"] == 1


def test_schema_migration_preserves_history_noops_and_ids(tmp_path):
    g = init(tmp_path)
    assert request(g, "on", 0, "original-noop").reason == Reason.NO_CHANGE
    assert request(g, "sleep", 5, "original-transition").reason == Reason.ACCEPTED
    tightened = policy(window=100, limit=1)
    assert update(g, tightened, 6) == 1
    h = TransitionGuard.open(tmp_path / PATH)
    assert h.status()["revision"] == 1
    assert h.status()["policy_revision"] == 1
    assert h.status()["noops"] == 1
    assert h.policy_history()["initial_policy"] == policy().to_dict()
    assert h.policy_history()["updates"][0]["after_event_seq"] == 1
    assert request(h, "on", 7, "blocked").reason == Reason.RATE_LIMIT
    assert request(h, "sleep", 8, "original-transition").reason == Reason.REPLAY
    assert request(h, "on", 9, "original-noop").reason == Reason.REPLAY
    assert request(h, "on", 105, "allowed").reason == Reason.ACCEPTED
    assert len(h.history()) == 2


def test_removed_edge_still_valid_in_historical_epoch(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 1, "first").allowed
    assert request(g, "on", 2, "second").allowed
    no_sleep = policy(edges=(("on", "off"), ("off", "on")))
    assert update(g, no_sleep, 3) == 1
    h = TransitionGuard.open(tmp_path / PATH)
    assert request(h, "sleep", 4, "forbidden").reason == Reason.UNSUPPORTED_TRANSITION
    assert request(h, "off", 4, "allowed").reason == Reason.ACCEPTED


def test_tightening_window_recounts_earlier_events(tmp_path):
    g = init(tmp_path, policy(window=10, limit=2))
    assert request(g, "sleep", 1, "a").allowed
    assert request(g, "on", 12, "b").allowed
    # Both historical events become active in the larger 100ms window.
    assert update(g, policy(window=100, limit=2), 13) == 1
    assert request(g, "sleep", 14, "deny").reason == Reason.RATE_LIMIT
    assert request(g, "sleep", 101, "allow-at-boundary").reason == Reason.ACCEPTED


def test_min_dwell_and_interval_reference_events_before_change(tmp_path):
    g = init(tmp_path, policy(limit=5))
    assert request(g, "sleep", 10, "a").allowed
    assert update(g, policy(limit=5, dwell=40, interval=30), 11) == 1
    d = request(g, "on", 20, "wait")
    assert d.reason == Reason.MIN_DWELL
    assert d.retry_at_ms == 50
    assert request(g, "on", 50, "go").reason == Reason.ACCEPTED


def test_zero_cap_blocks_future_events_without_erasing_history(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 1, "a").allowed
    assert update(g, policy(limit=0), 2) == 1
    d = request(g, "on", 100000, "blocked")
    assert d.reason == Reason.RATE_LIMIT and d.retry_at_ms is None
    assert g.status()["revision"] == 1
    assert request(g, "sleep", 100001, "noop").reason == Reason.NO_CHANGE


def test_multiple_policy_epochs_at_identical_event_revision(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 10, "a").allowed
    assert update(g, policy(limit=1), 11, "p1", 0) == 1
    assert update(g, policy(limit=0), 11, "p2", 1) == 2
    assert update(g, policy(limit=3), 11, "p3", 2) == 3
    h = TransitionGuard.open(tmp_path / PATH)
    assert h.status()["policy_revision"] == 3
    assert request(h, "on", 11, "b").reason == Reason.ACCEPTED


def test_multiple_epochs_before_and_after_events_allow_old_edges(tmp_path):
    g = init(tmp_path)
    assert update(g, policy(edges=(("on", "off"), ("off", "on"))), 0, "p1", 0) == 1
    assert request(g, "off", 0, "a").allowed
    assert update(g, policy(), 1, "p2", 1) == 2
    assert request(g, "on", 1, "b").allowed
    assert request(g, "sleep", 1, "c").allowed
    assert update(g, policy(edges=(("on", "off"), ("off", "on"))), 2, "p3", 2) == 3
    assert TransitionGuard.open(tmp_path / PATH).status()["revision"] == 3


def test_policy_update_replay_is_idempotent_even_after_more_requests(tmp_path):
    g = init(tmp_path)
    p2 = policy(limit=2)
    assert update(g, p2, 1, "p1", 0) == 1
    assert request(g, "sleep", 2, "a").allowed
    assert update(g, p2, 3, "p1", 0) == 1
    assert g.status()["policy_revision"] == 1
    with pytest.raises(GuardError, match="collision"):
        update(g, policy(limit=1), 4, "p1", 1)
    with pytest.raises(GuardError, match="stale policy"):
        update(g, p2, 4, "new", 0)
    assert g.status()["last_checked_ms"] == 3  # replay does not persist time


def test_replay_clock_regression_rejected(tmp_path):
    g = init(tmp_path)
    assert update(g, policy(limit=2), 10, "p1", 0) == 1
    with pytest.raises(GuardError, match="clock regression"):
        update(g, policy(limit=2), 9, "p1", 0)


def test_same_state_set_required(tmp_path):
    g = init(tmp_path)
    p = Policy(states=("on", "sleep"), edges=(("on", "sleep"),),
               min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
               window_ms=100, max_transitions=2)
    with pytest.raises(GuardError, match="state identifiers"):
        update(g, p, 5)
    assert g.status()["policy_revision"] == 0


def test_state_reorder_rejected(tmp_path):
    g = init(tmp_path)
    p = Policy(states=("sleep", "on", "off"), edges=(("sleep", "on"),),
               min_dwell_ms={"on": 0, "sleep": 0, "off": 0}, min_interval_ms=0,
               window_ms=100, max_transitions=2)
    with pytest.raises(GuardError, match="state identifiers"):
        update(g, p, 5)


def test_ids_shared_across_request_and_policy_namespace(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 1, "event-id").allowed
    with pytest.raises(GuardError, match="collision"):
        update(g, policy(limit=2), 2, "event-id")
    assert request(g, "sleep", 2, "noop-id").reason == Reason.NO_CHANGE
    with pytest.raises(GuardError, match="collision"):
        update(g, policy(limit=2), 3, "noop-id")
    assert update(g, policy(limit=2), 3, "update-id") == 1
    assert request(g, "on", 4, "update-id").reason == Reason.REQUEST_ID_COLLISION


def test_failed_commit_before_replace_preserves_legacy_journal(tmp_path, monkeypatch):
    g = init(tmp_path)
    old = (tmp_path / PATH).read_bytes()

    def fail(_):
        raise OSError("disk full")

    monkeypatch.setattr(g.store, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        update(g, policy(limit=1), 7)
    assert (tmp_path / PATH).read_bytes() == old
    assert TransitionGuard.open(tmp_path / PATH).status()["policy_revision"] == 0


def test_save_after_replace_raises_but_update_remains_valid(tmp_path, monkeypatch):
    g = init(tmp_path)
    save = g.store.save

    def after_replace(payload):
        save(payload)
        raise OSError("uncertain durability after rename")

    monkeypatch.setattr(g.store, "save", after_replace)
    with pytest.raises(OSError, match="uncertain durability"):
        update(g, policy(limit=1), 7)
    g2 = TransitionGuard.open(tmp_path / PATH)
    assert g2.status()["policy_revision"] == 1
    assert update(g2, policy(limit=1), 8) == 1


@pytest.mark.parametrize("corruption", [
    lambda p: p.update(policy=p["initial_policy"]),
    lambda p: p["policy_updates"][0].update(seq=True),
    lambda p: p["policy_updates"][0].update(id=""),
    lambda p: p["policy_updates"][0].update(after_event_seq=9),
    lambda p: p["policy_updates"][0].update(at_ms=0),
    lambda p: p["policy_updates"][0].update(policy={"no": "policy"}),
    lambda p: p["policy_updates"].append(dict(p["policy_updates"][0])),
    lambda p: p.pop("initial_policy"),
    lambda p: p.update(schema=99),
])
def test_policy_epoch_tamper_rejected_even_with_valid_checksum(tmp_path, corruption):
    g = init(tmp_path)
    assert request(g, "sleep", 5, "first").allowed
    assert update(g, policy(limit=1), 6) == 1
    rewrite(tmp_path / PATH, corruption)
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(tmp_path / PATH)


def test_time_cutoff_vs_event_times_rejects_corruption(tmp_path):
    g = init(tmp_path)
    assert request(g, "sleep", 10, "a").allowed
    assert update(g, policy(limit=1), 20) == 1
    assert request(g, "on", 120, "b").allowed
    # Update recorded after event 1; changing cutoff to 0 contradicts 20ms timestamp.
    rewrite(tmp_path / PATH, lambda p: p["policy_updates"][0].update(after_event_seq=0))
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(tmp_path / PATH)


def test_policy_history_returns_detached_nested_objects(tmp_path):
    g = init(tmp_path)
    assert update(g, policy(limit=1), 10) == 1
    info = g.policy_history()
    info["updates"][0]["policy"]["max_transitions"] = 999
    info["initial_policy"]["states"].clear()
    assert TransitionGuard.open(tmp_path / PATH).status()["policy"]["max_transitions"] == 1


def test_clock_regression_update_does_not_modify_snapshot(tmp_path):
    g = init(tmp_path)
    assert request(g, "on", 100, "noop").allowed
    before = (tmp_path / PATH).read_bytes()
    with pytest.raises(GuardError, match="clock regression"):
        update(g, policy(limit=1), 99)
    assert (tmp_path / PATH).read_bytes() == before


def concurrent_update(path, uid, results):
    g = TransitionGuard.open(path)
    try:
        results.put((uid, update(g, policy(limit=1), 10, uid, 0)))
    except GuardError:
        results.put((uid, "stale"))


def test_concurrent_policy_updates_enforce_revision(tmp_path):
    g = init(tmp_path)
    path = str(g.store.path)
    ctx = multiprocessing.get_context("spawn")
    results = ctx.Queue()
    processes = [ctx.Process(target=concurrent_update, args=(path, f"u-{i}", results)) for i in range(2)]
    for proc in processes:
        proc.start()
    seen = [results.get(timeout=20) for _ in processes]
    for proc in processes:
        proc.join(timeout=20)
        assert proc.exitcode == 0
    assert sorted(v for _, v in seen if isinstance(v, str)) == ["stale"]
    assert sorted(v for _, v in seen if isinstance(v, int)) == [1]
    assert TransitionGuard.open(path).status()["policy_revision"] == 1


def test_cli_update_policy_and_status(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main

    g = init(tmp_path)
    path = tmp_path / "next-policy.json"
    path.write_text(json.dumps(policy(limit=1).to_dict()))
    monkeypatch.setattr(sys, "argv", ["green-guard", "update-policy", "--store", str(g.store.path),
                                   "--policy", str(path), "--update-id", "cli-1", "--time-ms", "5",
                                   "--expected-policy-revision", "0"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["policy_revision"] == 1
    assert output["status"]["policy"]["max_transitions"] == 1


def test_cli_rejects_stale_policy_revision(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main

    g = init(tmp_path)
    update(g, policy(limit=1), 5)
    path = tmp_path / "next-policy.json"
    path.write_text(json.dumps(policy(limit=2).to_dict()))
    monkeypatch.setattr(sys, "argv", ["green-guard", "update-policy", "--store", str(g.store.path),
                                   "--policy", str(path), "--update-id", "cli-2", "--time-ms", "6",
                                   "--expected-policy-revision", "0"])
    assert main() == 2
    assert "stale policy revision" in capsys.readouterr().err


def test_request_policy_revision_precondition_after_migration(tmp_path):
    g = init(tmp_path)
    assert update(g, policy(limit=2), 1) == 1
    # Existing consumers are still checked against the new active policy.
    stale = g.request(target="sleep", at_ms=2, request_id="stale", expected_policy_revision=0)
    assert stale.reason == Reason.STALE_POLICY_REVISION
    assert g.status()["revision"] == 0
    assert g.request(target="sleep", at_ms=3, request_id="current", expected_policy_revision=1).reason == Reason.ACCEPTED
    # Idempotent replay of a completed request precedes revision CAS checks.
    assert g.request(target="sleep", at_ms=4, request_id="current", expected_policy_revision=0).reason == Reason.REPLAY


def test_legacy_request_policy_revision_zero(tmp_path):
    g = init(tmp_path)
    assert g.request(target="sleep", at_ms=1, request_id="a", expected_policy_revision=0).allowed
    assert g.request(target="on", at_ms=2, request_id="b", expected_policy_revision=1).reason == Reason.STALE_POLICY_REVISION
