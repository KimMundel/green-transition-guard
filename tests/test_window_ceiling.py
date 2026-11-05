"""Software-only seal for future policy windows; no physical or power-loss claim."""

import json
import sys

import pytest

from green_transition_guard import GuardError, InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.storage import wrap


def policy(*, window=10, limit=3):
    return Policy(
        states=("awake", "sleep"),
        edges=(("awake", "sleep"), ("sleep", "awake")),
        min_dwell_ms={"awake": 0, "sleep": 0},
        min_interval_ms=0, window_ms=window, max_transitions=limit,
    )


def init(tmp_path, *, window=10):
    path = tmp_path / "guard.json"
    guard = TransitionGuard.initialize(path, device_id="device", policy=policy(window=window),
                                       initial_state="awake", entered_at_ms=0)
    return guard, path


def seal(g, *, limit=50, key="seal-1", time=10, revision=0):
    return g.seal_window_ceiling(max_future_window_ms=limit, install_id=key, at_ms=time,
                                 expected_policy_revision=revision)


def migrate(g, *, window, key, time, revision):
    return g.update_policy(new_policy=policy(window=window), update_id=key,
                           at_ms=time, expected_policy_revision=revision)


def rewrite(path, mutation):
    envelope = json.loads(path.read_text())
    mutation(envelope["payload"])
    path.write_text(json.dumps(wrap(envelope["payload"])))


def test_schema1_seal_preserves_events_noops_and_idempotency(tmp_path):
    g, path = init(tmp_path)
    assert g.status()["window_ceiling_ms"] is None
    assert g.request(target="awake", request_id="noop", at_ms=1).reason == Reason.NO_CHANGE
    assert g.request(target="sleep", request_id="edge", at_ms=2).allowed
    before = json.loads(path.read_text())["payload"]
    assert seal(g, time=3) == 50
    after = json.loads(path.read_text())["payload"]
    assert after["schema"] == 3
    assert after["events"] == before["events"]
    assert after["noops"] == before["noops"]
    assert after["initial_policy"] == before["policy"]
    assert after["policy_updates"] == []
    g2 = TransitionGuard.open(path)
    assert g2.status()["window_ceiling_ms"] == 50
    assert g2.status()["policy_revision"] == 0
    assert g2.request(target="sleep", request_id="edge", at_ms=4).reason == Reason.REPLAY
    assert g2.request(target="awake", request_id="noop", at_ms=5).reason == Reason.REPLAY
    assert g2.request(target="awake", request_id="seal-1", at_ms=6).reason == Reason.REQUEST_ID_COLLISION
    assert migrate(g2, window=50, key="update1", time=7, revision=0) == 1
    assert g2.status()["policy_revision"] == 1
    assert g2.status()["window_ceiling_ms"] == 50
    assert g2.policy_history()["updates"][0]["policy"]["window_ms"] == 50


def test_bound_denies_future_upgrade_without_mutating_history(tmp_path):
    g, path = init(tmp_path)
    assert seal(g, time=0) == 50
    old = path.read_bytes()
    with pytest.raises(GuardError, match="exceeds sealed ceiling"):
        migrate(g, window=51, key="too-large", time=1, revision=0)
    assert path.read_bytes() == old
    assert migrate(g, window=50, key="at-limit", time=1, revision=0) == 1
    assert migrate(g, window=1, key="smaller", time=2, revision=1) == 2
    with pytest.raises(GuardError, match="exceeds sealed ceiling"):
        migrate(g, window=5000, key="too-large-2", time=3, revision=2)
    assert TransitionGuard.open(path).status()["policy"]["window_ms"] == 1


def test_schema2_history_with_older_larger_window_is_valid(tmp_path):
    g, path = init(tmp_path, window=200)
    assert g.request(target="sleep", request_id="a", at_ms=1).allowed
    assert migrate(g, window=10, key="p1", time=2, revision=0) == 1
    assert seal(g, limit=30, key="sealed", time=3, revision=1) == 30
    g = TransitionGuard.open(path)
    assert g.policy_history()["initial_policy"]["window_ms"] == 200
    assert g.status()["window_ceiling_ms"] == 30
    assert g.request(target="awake", request_id="b", at_ms=4).allowed
    assert migrate(g, window=20, key="p2", time=5, revision=1) == 2
    with pytest.raises(GuardError, match="exceeds sealed ceiling"):
        migrate(g, window=200, key="p3", time=6, revision=2)
    assert TransitionGuard.open(path).status()["revision"] == 2


def test_replay_of_old_update_can_exceed_later_installed_cap(tmp_path):
    g, path = init(tmp_path, window=300)
    assert migrate(g, window=200, key="legacy-update", time=1, revision=0) == 1
    assert migrate(g, window=20, key="current", time=2, revision=1) == 2
    assert seal(g, limit=30, key="install", time=3, revision=2) == 30
    assert migrate(g, window=200, key="legacy-update", time=4, revision=0) == 1
    assert TransitionGuard.open(path).status()["policy"]["window_ms"] == 20
    assert TransitionGuard.open(path).status()["last_checked_ms"] == 4


def test_policy_revision_stale_seal_rejected(tmp_path):
    g, path = init(tmp_path)
    migrate(g, window=20, key="p1", time=1, revision=0)
    original = path.read_bytes()
    with pytest.raises(GuardError, match="stale policy revision"):
        seal(g, revision=0, time=2)
    assert path.read_bytes() == original
    assert seal(g, revision=1, time=2) == 50


def test_ceiling_lower_than_active_policy_is_rejected(tmp_path):
    g, path = init(tmp_path, window=51)
    original = path.read_bytes()
    with pytest.raises(GuardError, match="below active"):
        seal(g, limit=50)
    assert path.read_bytes() == original
    assert g.status()["window_ceiling_ms"] is None


@pytest.mark.parametrize("invalid", [0, -1, 1.2, True, "50", None])
def test_invalid_window_bounds_rejected(tmp_path, invalid):
    g, path = init(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        seal(g, limit=invalid)
    assert path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["", "x" * 257, None, 123])
def test_invalid_install_id_rejected(tmp_path, invalid):
    g, path = init(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        seal(g, key=invalid)
    assert path.read_bytes() == original


def test_seal_replay_exact_and_reject_mutation_or_replacement(tmp_path):
    g, path = init(tmp_path)
    assert seal(g, time=2) == 50
    assert seal(g, time=3, revision=22) == 50  # same operation, earlier revision precondition
    assert g.status()["last_checked_ms"] == 3
    with pytest.raises(GuardError, match="ID collision"):
        seal(g, time=4, limit=100)
    with pytest.raises(GuardError, match="already sealed"):
        seal(g, time=4, key="other")
    with pytest.raises(GuardError, match="clock regression"):
        seal(g, time=2)
    assert g.status()["window_ceiling_ms"] == 50
    assert json.loads(path.read_text())["payload"]["window_ceiling"]["id"] == "seal-1"


def test_replay_preserves_seal_after_later_policy_and_events(tmp_path):
    g, path = init(tmp_path)
    seal(g, time=1)
    migrate(g, window=49, key="p", time=2, revision=0)
    assert g.request(target="sleep", request_id="e", at_ms=3).allowed
    assert seal(g, time=4, revision=0) == 50
    g = TransitionGuard.open(path)
    assert g.status()["policy_revision"] == 1
    assert g.status()["revision"] == 1


def test_clock_regression_and_collisions(tmp_path):
    g, path = init(tmp_path)
    g.request(target="sleep", request_id="transition", at_ms=1)
    g.request(target="sleep", request_id="noop", at_ms=2)
    migrate(g, window=20, key="policy", time=3, revision=0)
    for key in ("transition", "noop", "policy"):
        with pytest.raises(GuardError, match="collision"):
            seal(g, key=key, time=4, revision=1)
    assert seal(g, time=4, revision=1) == 50
    with pytest.raises(GuardError, match="collision"):
        migrate(g, window=20, key="seal-1", time=5, revision=1)
    with pytest.raises(GuardError, match="clock regression"):
        migrate(g, window=20, key="p2", time=3, revision=1)
    assert g.request(target="awake", request_id="seal-1", at_ms=5).reason == Reason.REQUEST_ID_COLLISION
    assert TransitionGuard.open(path).status()["policy_revision"] == 1


def test_retention_report_distinguishes_sealed_and_hypothetical(tmp_path):
    g, path = init(tmp_path)
    g.request(target="sleep", request_id="edge", at_ms=1)
    unsealed = g.quota_retention_view(max_future_window_ms=50).to_dict()
    assert unsealed["enforced_ceiling_ms"] is None
    assert unsealed["retention_bound_enforced"] is False
    seal(g, time=100, limit=50)
    sealed = g.quota_retention_view(max_future_window_ms=50).to_dict()
    assert sealed["enforced_ceiling_ms"] == 50
    assert sealed["retention_bound_enforced"] is True
    assert sealed["journal_compaction_enabled"] is False
    assert sealed["expired_for_quota"] == 1
    # A narrower hypothetical bound remains an unproven compaction premise.
    narrower = g.quota_retention_view(max_future_window_ms=10).to_dict()
    assert narrower["retention_bound_enforced"] is False
    assert g.quota_retention_view(max_future_window_ms=100).to_dict()["retention_bound_enforced"] is True
    assert g.status()["revision"] == 1


def test_retention_ceiling_applies_to_later_policy_migration(tmp_path):
    g, path = init(tmp_path)
    assert g.request(target="sleep", request_id="first", at_ms=1).allowed
    seal(g, time=3, limit=30)
    g.update_policy(new_policy=policy(window=30, limit=1), update_id="limited",
                    at_ms=4, expected_policy_revision=0)
    assert g.request(target="awake", request_id="blocked", at_ms=5).reason == Reason.RATE_LIMIT
    assert g.request(target="awake", request_id="allowed", at_ms=31).reason == Reason.ACCEPTED
    assert TransitionGuard.open(path).status()["window_ceiling_ms"] == 30


def test_mixed_same_timestamp_epochs_and_seal_are_valid(tmp_path):
    g, path = init(tmp_path)
    g.request(target="sleep", request_id="event-1", at_ms=0)
    migrate(g, window=100, key="before", time=0, revision=0)
    migrate(g, window=20, key="current", time=0, revision=1)
    seal(g, time=0, limit=20, revision=2)
    g.request(target="awake", request_id="event-2", at_ms=0)
    migrate(g, window=19, key="after", time=0, revision=2)
    assert TransitionGuard.open(path).status()["policy_revision"] == 3


def test_seal_failure_before_replace_keeps_legacy(tmp_path, monkeypatch):
    g, path = init(tmp_path)
    before = path.read_bytes()
    def failed_save(_):
        raise OSError("disk full")
    monkeypatch.setattr(g.store, "save", failed_save)
    with pytest.raises(OSError, match="disk full"):
        seal(g)
    assert path.read_bytes() == before
    assert TransitionGuard.open(path).status()["window_ceiling_ms"] is None


def test_seal_after_replace_error_can_reconcile_with_same_id(tmp_path, monkeypatch):
    g, path = init(tmp_path)
    original_save = g.store.save
    def uncertain_save(payload):
        original_save(payload)
        raise OSError("uncertain durability")
    monkeypatch.setattr(g.store, "save", uncertain_save)
    with pytest.raises(OSError, match="uncertain"):
        seal(g, time=10)
    reopened = TransitionGuard.open(path)
    assert reopened.status()["window_ceiling_ms"] == 50
    assert seal(reopened, time=11) == 50
    assert reopened.status()["last_checked_ms"] == 11


def test_corruption_rejects_any_policy_after_seal_over_cap(tmp_path):
    g, path = init(tmp_path)
    seal(g, time=1)
    migrate(g, window=40, key="safe", time=2, revision=0)
    rewrite(path, lambda p: p["policy_updates"][0]["policy"].update(window_ms=60))
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


@pytest.mark.parametrize("mutation", [
    lambda p: p["window_ceiling"].update(max_window_ms=0),
    lambda p: p["window_ceiling"].update(max_window_ms=True),
    lambda p: p["window_ceiling"].update(max_window_ms=2),
    lambda p: p["window_ceiling"].update(id=""),
    lambda p: p["window_ceiling"].update(id="edge"),
    lambda p: p["window_ceiling"].update(at_ms=200),
    lambda p: p["window_ceiling"].update(after_event_seq=99),
    lambda p: p["window_ceiling"].update(after_policy_revision=99),
    lambda p: p["window_ceiling"].update(extra=True),
    lambda p: p.pop("window_ceiling"),
    lambda p: p["window_ceiling"].update(after_policy_revision=0),
    lambda p: p["window_ceiling"].update(after_event_seq=0),
])
def test_modified_ceiling_record_fails_closed(tmp_path, mutation):
    g, path = init(tmp_path, window=200)
    g.request(target="sleep", request_id="edge", at_ms=10)
    migrate(g, window=20, key="p", time=11, revision=0)
    seal(g, time=12, limit=50, revision=1)
    g.request(target="awake", request_id="later", at_ms=20)
    migrate(g, window=30, key="later-policy", time=21, revision=1)
    rewrite(path, mutation)
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


def test_corrupt_late_epoch_with_inconsistent_event_cutoff_fails_closed(tmp_path):
    g, path = init(tmp_path)
    g.request(target="sleep", request_id="edge", at_ms=1)
    seal(g, time=2)
    g.request(target="awake", request_id="later", at_ms=3)
    migrate(g, window=20, key="p", time=4, revision=0)
    # Pretend sealing occurred after the later update although it is after
    # the recorded event cutoff and timestamp.
    rewrite(path, lambda p: p["window_ceiling"].update(after_policy_revision=1))
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


def test_cli_seal_and_retention(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    _, path = init(tmp_path)
    monkeypatch.setattr(sys, "argv", ["green-guard", "seal-window", "--store", str(path),
                                      "--max-window-ms", "50", "--install-id", "cli-install",
                                      "--time-ms", "1", "--expected-policy-revision", "0"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["window_ceiling_ms"] == 50
    assert result["status"]["window_ceiling_ms"] == 50
    monkeypatch.setattr(sys, "argv", ["green-guard", "retention-plan", "--store", str(path),
                                      "--max-window-ms", "50"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["retention_bound_enforced"] is True
    assert result["journal_compaction_enabled"] is False


def test_repeated_open_does_not_change_seal(tmp_path):
    g, path = init(tmp_path)
    seal(g, limit=100, time=0)
    original = path.read_bytes()
    for _ in range(3):
        reopened = TransitionGuard.open(path)
        assert reopened.status()["window_ceiling_ms"] == 100
        assert path.read_bytes() == original
