"""Lineage must reject individually valid, retroactive same-clock operations."""
from copy import deepcopy

import pytest

from green_transition_guard import Policy, TransitionGuard
from green_transition_guard.engine import _validate_payload
from green_transition_guard.experimental_recovery import compare_recovery_lineage


def guard(tmp_path):
    policy = Policy(
        states=("awake", "sleep"), edges=(("awake", "sleep"), ("sleep", "awake")),
        min_dwell_ms={"awake": 0, "sleep": 0}, min_interval_ms=0,
        window_ms=20, max_transitions=100,
    )
    return TransitionGuard.initialize(tmp_path / "journal.json", device_id="device-A",
                                      policy=policy, initial_state="awake", entered_at_ms=0)


def after_two_transitions(tmp_path):
    g = guard(tmp_path)
    assert g.request(target="sleep", request_id="event-1", at_ms=1).allowed
    assert g.request(target="awake", request_id="event-2", at_ms=2).allowed
    return g, g.store.read()


def assert_valid_but_not_ancestor(old, new):
    _validate_payload(old)
    _validate_payload(new)
    assert compare_recovery_lineage(old, new).relation == "diverged"


def test_noop_cannot_be_inserted_before_already_observed_event(tmp_path):
    _, old = after_two_transitions(tmp_path)
    new = deepcopy(old)
    # at_ms is tied to the older clock, but revision 1 predates event 2.
    new["noops"].append({"request_id": "retro", "target": "sleep", "at_ms": 2, "revision": 1})
    assert_valid_but_not_ancestor(old, new)


def test_policy_update_cannot_be_inserted_before_observed_event(tmp_path):
    _, old = after_two_transitions(tmp_path)
    new = deepcopy(old)
    new["schema"] = 2
    new["initial_policy"] = deepcopy(old["policy"])
    new["policy_updates"] = [{"seq": 1, "id": "retro-policy", "at_ms": 2,
                              "after_event_seq": 1, "policy": deepcopy(old["policy"])}]
    assert_valid_but_not_ancestor(old, new)


def test_window_seal_cannot_be_inserted_before_observed_event(tmp_path):
    _, old = after_two_transitions(tmp_path)
    new = deepcopy(old)
    new.update(schema=3, initial_policy=deepcopy(old["policy"]), policy_updates=[],
               window_ceiling={"id": "window", "at_ms": 2, "max_window_ms": 30,
                               "after_event_seq": 1, "after_policy_revision": 0})
    assert_valid_but_not_ancestor(old, new)


def test_operation_budget_cannot_be_inserted_before_observed_noop(tmp_path):
    g = guard(tmp_path)
    g.seal_window_ceiling(max_future_window_ms=30, install_id="window", at_ms=0,
                          expected_policy_revision=0)
    assert g.request(target="awake", request_id="old-noop", at_ms=2).allowed
    assert g.request(target="sleep", request_id="event-1", at_ms=2).allowed
    old = g.store.read()
    new = deepcopy(old)
    new.update(schema=4, operation_budget={
        "id": "budget", "at_ms": 2, "max_total_ids": 100,
        "after_event_seq": 1, "after_noop_count": 0, "after_policy_revision": 0,
    })
    assert_valid_but_not_ancestor(old, new)


@pytest.mark.parametrize("field", ["time", "revision"])
def test_append_noop_order_must_remain_monotonic(tmp_path, field):
    g = guard(tmp_path)
    old = g.store.read()
    if field == "time":
        new = deepcopy(old)
        new["last_checked_ms"] = 2
        new["noops"] = [
            {"request_id": "late", "target": "awake", "at_ms": 2, "revision": 0},
            {"request_id": "early", "target": "awake", "at_ms": 1, "revision": 0},
        ]
    else:
        assert g.request(target="sleep", request_id="event-1", at_ms=1).allowed
        assert g.request(target="awake", request_id="event-2", at_ms=2).allowed
        new = g.store.read()
        new["noops"] = [
            {"request_id": "later-rev", "target": "awake", "at_ms": 2, "revision": 2},
            {"request_id": "earlier-rev", "target": "sleep", "at_ms": 2, "revision": 1},
        ]
    assert_valid_but_not_ancestor(old, new)


def test_genuine_same_millisecond_operations_remain_ancestors(tmp_path):
    g, old = after_two_transitions(tmp_path)
    assert g.request(target="awake", request_id="noop-1", at_ms=2).allowed
    assert g.request(target="awake", request_id="noop-2", at_ms=2).allowed
    assert compare_recovery_lineage(old, g.store.read()).relation == "archive_ancestor"
    g.update_policy(new_policy=Policy.from_dict(old["policy"]), update_id="update", at_ms=2,
                    expected_policy_revision=0)
    assert compare_recovery_lineage(old, g.store.read()).relation == "archive_ancestor"
    g.seal_window_ceiling(max_future_window_ms=30, install_id="window", at_ms=2,
                          expected_policy_revision=1)
    assert compare_recovery_lineage(old, g.store.read()).relation == "archive_ancestor"
    g.seal_operation_budget(max_total_ids=100, install_id="budget", at_ms=2,
                            expected_policy_revision=1)
    assert compare_recovery_lineage(old, g.store.read()).relation == "archive_ancestor"


def test_result_hashes_are_detached_from_caller_mutations(tmp_path):
    g = guard(tmp_path)
    old, new = g.store.read(), g.store.read()
    view = compare_recovery_lineage(old, new)
    before = view.to_dict()
    old["device_id"] = "tampered-after-comparison"
    new["last_checked_ms"] = 123
    assert view.to_dict() == before
