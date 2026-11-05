"""Read-only complete-history ancestry checks; no recovery or pruning."""

import json
import sys

import pytest

from green_transition_guard import InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.experimental_recovery import compare_recovery_lineage
from green_transition_guard.storage import wrap


def policy(window=20):
    return Policy(states=("awake", "sleep"), edges=(("awake", "sleep"), ("sleep", "awake")),
                  min_dwell_ms={"awake": 0, "sleep": 0}, min_interval_ms=0,
                  window_ms=window, max_transitions=100)


def fixture(tmp_path):
    path = tmp_path / "device.json"
    guard = TransitionGuard.initialize(path, device_id="device-A", policy=policy(),
                                       initial_state="awake", entered_at_ms=0)
    return guard, path, tmp_path / "saved.archive.json"


def req(g, at, key):
    to = "sleep" if g.status()["state"] == "awake" else "awake"
    assert g.request(target=to, request_id=key, at_ms=at).reason == Reason.ACCEPTED


def noop(g, at, key):
    assert g.request(target=g.status()["state"], request_id=key, at_ms=at).reason == Reason.NO_CHANGE


def update(g, at, key, window=20):
    g.update_policy(new_policy=policy(window), update_id=key, at_ms=at,
                    expected_policy_revision=g.status()["policy_revision"])


def seal(g, at=10):
    g.seal_window_ceiling(max_future_window_ms=30, install_id="window", at_ms=at,
                          expected_policy_revision=g.status()["policy_revision"])


def budget(g, at=11):
    g.seal_operation_budget(max_total_ids=30, install_id="budget", at_ms=at,
                            expected_policy_revision=g.status()["policy_revision"])


def snapshot(path):
    return json.loads(path.read_text())["payload"]


def assert_lineage(g, archive, relation):
    report = g.compare_checkpoint_lineage(archive).to_dict()
    assert report["relation"] == relation
    assert report["possible_live_rollback"] == (relation == "current_ancestor")
    assert report["journal_compaction_enabled"] is False
    assert report["restoration_enabled"] is False
    assert report["authenticated_rollback_protection"] is False
    assert len(report["archive_snapshot_sha256"]) == 64
    assert len(report["current_snapshot_sha256"]) == 64
    return report


def test_same_archive_and_live_are_identical_and_read_only(tmp_path):
    g, path, archive = fixture(tmp_path)
    req(g, 1, "sensitive-event")
    noop(g, 2, "sensitive-noop")
    g.create_checkpoint_archive(archive)
    before = path.read_bytes(), archive.read_bytes()
    m = assert_lineage(g, archive, "identical")
    assert m["archive_snapshot_sha256"] == m["current_snapshot_sha256"]
    assert "sensitive-event" not in json.dumps(m)
    assert "sensitive-noop" not in json.dumps(m)
    assert (path.read_bytes(), archive.read_bytes()) == before


@pytest.mark.parametrize("change", ["clock", "noop", "event", "policy", "window", "budget"])
def test_append_only_changes_show_archive_ancestor(tmp_path, change):
    g, _, archive = fixture(tmp_path)
    g.create_checkpoint_archive(archive)
    if change == "clock":
        assert g.request(target="unknown", request_id="rejected", at_ms=1).reason == Reason.UNKNOWN_STATE
    elif change == "noop":
        noop(g, 1, "n")
    elif change == "event":
        req(g, 1, "e")
    elif change == "policy":
        update(g, 1, "p")
    elif change == "window":
        seal(g, 1)
    else:
        seal(g, 1)
        budget(g, 2)
    report = assert_lineage(g, archive, "archive_ancestor")
    assert report["current_as_of_ms"] >= report["archive_as_of_ms"]


def test_complete_schema1_to_schema4_with_interleaving_and_equal_timestamps(tmp_path):
    g, path, archive = fixture(tmp_path)
    req(g, 1, "first")
    noop(g, 1, "first-noop")
    g.create_checkpoint_archive(archive)
    update(g, 1, "first-policy", 10)
    req(g, 1, "second")
    noop(g, 1, "second-noop")
    seal(g, 1)
    update(g, 1, "second-policy", 15)
    budget(g, 1)
    req(g, 2, "third")
    assert_lineage(g, archive, "archive_ancestor")
    g2 = TransitionGuard.open(path)
    assert g2.status()["operation_budget_max"] == 30
    assert_lineage(g2, archive, "archive_ancestor")


def test_older_schema2_and_schema3_are_ancestors_of_schema4(tmp_path):
    g, _, archive2 = fixture(tmp_path)
    update(g, 1, "before-seal", 10)
    g.create_checkpoint_archive(archive2)
    seal(g, 2)
    archive3 = tmp_path / "saved3.archive.json"
    g.create_checkpoint_archive(archive3)
    budget(g, 3)
    assert_lineage(g, archive2, "archive_ancestor")
    assert_lineage(g, archive3, "archive_ancestor")


def test_current_behind_verified_archive_is_possible_rollback(tmp_path):
    g, path, archive = fixture(tmp_path)
    old_bytes = path.read_bytes()
    req(g, 1, "first")
    update(g, 2, "update", 15)
    seal(g, 3)
    budget(g, 4)
    g.create_checkpoint_archive(archive)
    path.write_bytes(old_bytes)  # deliberately simulate an adversarial/backup rollback
    reopened = TransitionGuard.open(path)
    m = assert_lineage(reopened, archive, "current_ancestor")
    assert m["archive_schema"] == 4 and m["current_schema"] == 1
    assert m["archive_revision"] > m["current_revision"]
    assert reopened.status()["revision"] == 0  # observation never activates archived state


def test_same_revision_with_noop_only_rollback_detected(tmp_path):
    g, path, archive = fixture(tmp_path)
    old = path.read_bytes()
    noop(g, 1, "noop")
    g.create_checkpoint_archive(archive)
    path.write_bytes(old)
    m = assert_lineage(TransitionGuard.open(path), archive, "current_ancestor")
    assert m["archive_revision"] == m["current_revision"] == 0


def test_same_revision_with_clock_only_rollback_detected(tmp_path):
    g, path, archive = fixture(tmp_path)
    old = path.read_bytes()
    g.request(target="missing", request_id="never-accepted", at_ms=20)
    g.create_checkpoint_archive(archive)
    path.write_bytes(old)
    m = assert_lineage(TransitionGuard.open(path), archive, "current_ancestor")
    assert m["archive_revision"] == m["current_revision"] == 0
    assert m["archive_as_of_ms"] == 20


def test_diverged_branches_with_same_event_revision(tmp_path):
    g, path, archive = fixture(tmp_path)
    req(g, 1, "shared")
    shared = path.read_bytes()
    req(g, 2, "branch-one")
    g.create_checkpoint_archive(archive)
    path.write_bytes(shared)
    reopened = TransitionGuard.open(path)
    req(reopened, 2, "branch-two")
    m = assert_lineage(reopened, archive, "diverged")
    assert m["archive_revision"] == m["current_revision"] == 2


def test_altered_initial_policy_from_valid_independent_device_snapshot(tmp_path):
    g, path, archive = fixture(tmp_path)
    g.create_checkpoint_archive(archive)
    other = tmp_path / "other.json"
    alt_policy = policy(30)
    TransitionGuard.initialize(other, device_id="device-A", policy=alt_policy,
                               initial_state="awake", entered_at_ms=0)
    path.write_bytes(other.read_bytes())
    assert_lineage(TransitionGuard.open(path), archive, "diverged")


def test_different_device_never_merges_histories(tmp_path):
    g, path, archive = fixture(tmp_path)
    g.create_checkpoint_archive(archive)
    other = tmp_path / "other.json"
    TransitionGuard.initialize(other, device_id="device-B", policy=policy(),
                               initial_state="awake", entered_at_ms=0)
    path.write_bytes(other.read_bytes())
    assert_lineage(TransitionGuard.open(path), archive, "different_device")


def test_payload_validation_prevents_corrupt_journal_comparison(tmp_path):
    g, path, archive = fixture(tmp_path)
    req(g, 1, "e")
    g.create_checkpoint_archive(archive)
    corrupted = snapshot(path)
    corrupted["events"][0]["to"] = "awake"
    path.write_text(json.dumps(wrap(corrupted)))
    with pytest.raises(InvalidSnapshot):
        g.compare_checkpoint_lineage(archive)


def test_prevent_false_ancestry_from_retroactive_append(tmp_path):
    g, path, archive = fixture(tmp_path)
    req(g, 10, "a")
    g.request(target="missing", request_id="clock", at_ms=100)
    g.create_checkpoint_archive(archive)
    # This journal is individually valid, yet could not have been produced by
    # normal writes after an older observed clock of 100.
    payload = snapshot(path)
    payload["events"].append({"seq": 2, "id": "device-A:2", "request_id": "retro", "from": "sleep",
                              "to": "awake", "at_ms": 50})
    payload["revision"] = 2
    payload["state"] = "awake"
    payload["entered_ms"] = 50
    path.write_text(json.dumps(wrap(payload)))
    assert_lineage(TransitionGuard.open(path), archive, "diverged")


def test_cli_lineage_status_and_no_request_id_leak(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, path, archive = fixture(tmp_path)
    req(g, 1, "top-secret-request")
    g.create_checkpoint_archive(archive)
    args = ["green-guard", "checkpoint-lineage", "--store", str(path), "--archive", str(archive)]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["relation"] == "identical"
    assert "top-secret-request" not in output
    noop(g, 2, "second")
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["relation"] == "archive_ancestor"
    newer = path.read_bytes()
    archived_source = json.loads(archive.read_text())["payload"]["source_snapshot"]
    path.write_text(json.dumps(wrap(archived_source)))
    # Re-open current journal and compare against an archive of the newer state.
    path.write_bytes(newer)
    second_archive = tmp_path / "newer.archive.json"
    g.create_checkpoint_archive(second_archive)
    path.write_text(json.dumps(wrap(archived_source)))
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-lineage", "--store", str(path),
                                      "--archive", str(second_archive)])
    assert main() == 3
    assert json.loads(capsys.readouterr().out)["relation"] == "current_ancestor"
    second_archive.write_text("broken")
    assert main() == 2
    capsys.readouterr()


def test_direct_comparison_rejects_bad_inputs(tmp_path):
    g, path, _ = fixture(tmp_path)
    a = snapshot(path)
    b = json.loads(json.dumps(a))
    b["revision"] = -1
    with pytest.raises(InvalidSnapshot):
        compare_recovery_lineage(a, b)


@pytest.mark.parametrize("seed", range(16))
def test_randomized_valid_append_only_history_is_ancestor(tmp_path, seed):
    import random

    rng = random.Random(1016 + seed)
    g, path, archive = fixture(tmp_path)
    clock = 0
    for i in range(12):
        clock += rng.randint(0, 3)
        if i % 4 == 0:
            noop(g, clock, f"early-noop-{i}")
        elif i % 6 == 0:
            update(g, clock, f"early-policy-{i}", 10 + rng.randint(0, 8))
        else:
            req(g, clock, f"early-event-{i}")
    g.create_checkpoint_archive(archive)
    archive_source = json.loads(archive.read_text())["payload"]["source_snapshot"]
    for i in range(14):
        clock += rng.randint(0, 3)
        if i == 5:
            seal(g, clock)
        elif i == 10:
            budget(g, clock)
        elif i % 5 == 0:
            assert g.request(target="invalid", request_id=f"rejected-{i}",
                             at_ms=clock).reason == Reason.UNKNOWN_STATE
        elif i % 4 == 0:
            update(g, clock, f"later-policy-{i}", 10 + rng.randint(0, 8))
        elif i % 3 == 0:
            noop(g, clock, f"later-noop-{i}")
        else:
            req(g, clock, f"later-event-{i}")
        relation = g.compare_checkpoint_lineage(archive).relation
        assert relation in ("identical", "archive_ancestor")
    final_bytes = path.read_bytes()
    later_archive = tmp_path / "later.archive.json"
    g.create_checkpoint_archive(later_archive)
    path.write_text(json.dumps(wrap(archive_source)))
    assert_lineage(TransitionGuard.open(path), later_archive, "current_ancestor")
    path.write_bytes(final_bytes)
