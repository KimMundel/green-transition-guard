"""Conservative quota-retention proofs. No durable journal is ever pruned."""
import json
import random
import sys

import pytest

from green_transition_guard import GuardError, InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.experimental_retention import build_quota_retention_view


def policy(*, window=100, limit=100):
    return Policy(
        states=("on", "sleep"),
        edges=(("on", "sleep"), ("sleep", "on")),
        min_dwell_ms={"on": 0, "sleep": 0},
        min_interval_ms=0,
        window_ms=window,
        max_transitions=limit,
    )


def setup(tmp_path, *, window=100):
    return TransitionGuard.initialize(
        tmp_path / "guard.json", device_id="dev", policy=policy(window=window),
        initial_state="on", entered_at_ms=0,
    )


def event(g, at_ms, key):
    target = "sleep" if g.status()["state"] == "on" else "on"
    assert g.request(target=target, at_ms=at_ms, request_id=key).reason == Reason.ACCEPTED


def test_empty_journal_has_empty_view(tmp_path):
    g = setup(tmp_path)
    v = g.quota_retention_view(max_future_window_ms=100)
    assert v.expired_for_quota == v.retained_for_quota == 0
    assert v.last_transition_ms is None
    assert v.active_count(at_ms=500, window_ms=100) == 0
    assert v.release_at(at_ms=500, window_ms=100, max_transitions=1) is None
    assert v.to_dict()["journal_compaction_enabled"] is False


@pytest.mark.parametrize("boundary,expected", [(99, 1), (100, 2), (101, 2), (150, 2)])
def test_exact_left_boundary_is_excluded(tmp_path, boundary, expected):
    g = setup(tmp_path)
    event(g, 1, "a")
    event(g, 100, "b")
    g.request(target="on", at_ms=boundary + 100, request_id="advance-clock")
    v = g.quota_retention_view(max_future_window_ms=100)
    assert v.expired_for_quota == expected
    assert v.last_transition_ms == 100
    assert v.active_count(at_ms=boundary + 100, window_ms=100) == 2 - expected
    assert v.active_count(at_ms=boundary + 200, window_ms=100) == 0
    # The fully expired last edge remains available as an interval anchor.
    assert g.status()["revision"] == 2


def test_partial_expiration_and_release(tmp_path):
    g = setup(tmp_path, window=20)
    for at, key in [(1, "a"), (10, "b"), (20, "c"), (40, "d")]:
        event(g, at, key)
    assert g.request(target="on", at_ms=40, request_id="noop").reason == Reason.NO_CHANGE
    v = g.quota_retention_view(max_future_window_ms=30)
    assert v.expired_for_quota == 2  # 1 and 10 are <= 40 - 30
    assert v.retained_for_quota == 2
    assert v.active_count(at_ms=40, window_ms=30) == 2
    assert v.active_count(at_ms=50, window_ms=30) == 1  # 20 exactly expired
    assert v.release_at(at_ms=40, window_ms=30, max_transitions=2) == 50
    assert v.release_at(at_ms=40, window_ms=30, max_transitions=3) is None
    assert v.release_at(at_ms=40, window_ms=30, max_transitions=0) is None


def test_repeated_timestamp_keeps_stable_quota_count(tmp_path):
    g = setup(tmp_path, window=1)
    for i in range(5):
        event(g, 0, f"k-{i}")
    assert g.request(target="sleep", at_ms=0, request_id="clock").reason == Reason.NO_CHANGE
    v = g.quota_retention_view(max_future_window_ms=1)
    assert v.active_count(at_ms=0, window_ms=1) == 5
    assert v.active_count(at_ms=1, window_ms=1) == 0
    assert v.release_at(at_ms=0, window_ms=1, max_transitions=3) == 1


def test_policy_change_recounts_all_history_and_view_does_not_mutate(tmp_path):
    g = setup(tmp_path, window=10)
    event(g, 1, "early")
    event(g, 20, "late")
    before = (tmp_path / "guard.json").read_bytes()
    view = g.quota_retention_view(max_future_window_ms=50)
    assert (tmp_path / "guard.json").read_bytes() == before
    assert view.active_count(at_ms=20, window_ms=50) == 2
    assert g.update_policy(
        new_policy=policy(window=50, limit=2), update_id="p-1",
        at_ms=21, expected_policy_revision=0,
    ) == 1
    assert g.request(target="sleep", request_id="denied", at_ms=22).reason == Reason.RATE_LIMIT
    reopened = TransitionGuard.open(tmp_path / "guard.json")
    assert reopened.quota_retention_view(max_future_window_ms=50).active_count(at_ms=22, window_ms=50) == 2
    assert len(reopened.history()) == 2  # exact history and IDs remain intact
    assert reopened.request(target="sleep", request_id="early", at_ms=23).reason == Reason.REPLAY


def test_expanding_policy_beyond_proposed_ceiling_is_rejected_by_view(tmp_path):
    g = setup(tmp_path, window=10)
    g.update_policy(new_policy=policy(window=100), update_id="p", at_ms=1,
                    expected_policy_revision=0)
    with pytest.raises(GuardError, match="ceiling"):
        g.quota_retention_view(max_future_window_ms=20)
    assert g.quota_retention_view(max_future_window_ms=100).retained_for_quota == 0


def test_no_policy_window_is_persistently_enforced(tmp_path):
    g = setup(tmp_path, window=10)
    view = g.quota_retention_view(max_future_window_ms=10)
    assert view.to_dict()["journal_compaction_enabled"] is False
    assert g.update_policy(new_policy=policy(window=200), update_id="p", at_ms=1,
                           expected_policy_revision=0) == 1
    with pytest.raises(ValueError, match="ceiling"):
        view.active_count(at_ms=1, window_ms=200)
    assert g.status()["policy"]["window_ms"] == 200


def test_read_only_analysis_cannot_save(tmp_path, monkeypatch):
    g = setup(tmp_path)
    def unsafe_save(_):
        pytest.fail("quota analysis must never write a snapshot")
    monkeypatch.setattr(g.store, "save", unsafe_save)
    assert g.quota_retention_view(max_future_window_ms=100).total_events == 0


def test_corrupt_journal_causes_fail_closed_analysis(tmp_path):
    g = setup(tmp_path)
    path = tmp_path / "guard.json"
    value = json.loads(path.read_text())
    value["payload"]["revision"] = 100
    path.write_text(json.dumps(value))
    with pytest.raises(InvalidSnapshot):
        g.quota_retention_view(max_future_window_ms=100)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10", None])
def test_invalid_ceiling_rejected(tmp_path, bad):
    g = setup(tmp_path)
    with pytest.raises(ValueError):
        g.quota_retention_view(max_future_window_ms=bad)


def test_cannot_query_past_or_over_ceiling(tmp_path):
    g = setup(tmp_path, window=20)
    event(g, 10, "event")
    v = g.quota_retention_view(max_future_window_ms=20)
    with pytest.raises(ValueError, match="clock"):
        v.active_count(at_ms=9, window_ms=20)
    with pytest.raises(ValueError, match="ceiling"):
        v.active_count(at_ms=10, window_ms=21)
    with pytest.raises(ValueError):
        v.active_count(at_ms=10, window_ms=0)


def test_direct_builder_invalid_unsorted_and_future_events():
    make = lambda seq, now=10: build_quota_retention_view(
        [{"at_ms": t} for t in seq], as_of_ms=now, max_future_window_ms=10,
    )
    with pytest.raises(ValueError, match="monotonic"):
        make([5, 4])
    with pytest.raises(ValueError, match="later"):
        make([11])
    with pytest.raises(ValueError):
        make([False])


def test_cli_retention_plan(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g = setup(tmp_path, window=5)
    event(g, 10, "k")
    monkeypatch.setattr(sys, "argv", [
        "green-guard", "retention-plan", "--store", str(tmp_path / "guard.json"),
        "--max-window-ms", "5",
    ])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["journal_compaction_enabled"] is False
    assert output["total_events"] == 1
    assert output["retained_for_quota"] == 1


def test_randomized_independent_quota_oracle():
    """Exhaustive boundary probes in each of 240 deterministic random histories."""
    rng = random.Random(20261105)
    for _ in range(240):
        times = sorted(rng.randint(0, 500) for _ in range(rng.randint(0, 60)))
        now = (times[-1] if times else 0) + rng.randint(0, 400)
        cap = rng.randint(1, 600)
        v = build_quota_retention_view(
            [{"at_ms": t} for t in times], as_of_ms=now, max_future_window_ms=cap,
        )
        assert v.expired_for_quota + v.retained_for_quota == len(times)
        assert v.last_transition_ms == (times[-1] if times else None)
        for j in range(20):
            at = now + rng.randint(0, 700)
            window = rng.randint(1, cap)
            active = [t for t in times if t > at - window]
            assert v.active_count(at_ms=at, window_ms=window) == len(active)
            limit = rng.randint(0, 65)
            expected_release = None
            if limit and len(active) >= limit:
                expected_release = active[len(active) - limit] + window
            assert v.release_at(at_ms=at, window_ms=window, max_transitions=limit) == expected_release


def test_randomized_policy_migration_matches_full_journal(tmp_path):
    rng = random.Random(100505)
    g = setup(tmp_path, window=9)
    at = 0
    for i in range(24):
        at += rng.randint(0, 10)
        event(g, at, f"e-{i}")
        if i % 5 == 3:
            window = rng.randint(9, 80)
            g.update_policy(new_policy=policy(window=window), update_id=f"p-{i}",
                            at_ms=at, expected_policy_revision=g.status()["policy_revision"])
    for cap in [80, 100, 250]:
        view = g.quota_retention_view(max_future_window_ms=cap)
        full_times = [e["at_ms"] for e in g.history()]
        for future in [at, at + 1, at + 20, at + 100]:
            for window in [1, 10, 50, cap]:
                assert view.active_count(at_ms=future, window_ms=window) == sum(
                    t > future - window for t in full_times
                )
