"""Full-journal replay/checkpoint oracle. Compaction remains disabled."""

import hashlib
import json
import random
import sys

import pytest

from green_transition_guard import InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.experimental_checkpoint import build_replay_index
from green_transition_guard.storage import canonical_bytes, wrap


def policy(*, window=10, limit=100):
    return Policy(
        states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
        min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
        window_ms=window, max_transitions=limit,
    )


def init(tmp_path):
    path = tmp_path / "device.json"
    return TransitionGuard.initialize(path, device_id="device-A", policy=policy(),
                                      initial_state="on", entered_at_ms=0), path


def event(g, at, key):
    next_state = "sleep" if g.status()["state"] == "on" else "on"
    assert g.request(target=next_state, request_id=key, at_ms=at).reason == Reason.ACCEPTED
    return next_state


def sha(obj):
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def seal(g, at=40, window=10):
    return g.seal_window_ceiling(
        max_future_window_ms=window, install_id="seal-key",
        at_ms=at, expected_policy_revision=g.status()["policy_revision"],
    )


def update(g, at, key="policy-key", window=10):
    return g.update_policy(new_policy=policy(window=window), update_id=key,
                           at_ms=at, expected_policy_revision=g.status()["policy_revision"])


def test_empty_schema1_preflight_is_read_only(tmp_path):
    g, path = init(tmp_path)
    before = path.read_bytes()
    preview = g.checkpoint_preflight()
    report = preview.to_dict()
    assert path.read_bytes() == before
    assert report["schema"] == 1
    assert report["revision"] == report["policy_revision"] == 0
    assert report["replay_identity_count"] == 0
    assert report["last_transition_ms"] is None
    assert report["quota_expired_prefix_events"] == 0
    assert report["sealed_window_ceiling_ms"] is None
    assert report["journal_compaction_enabled"] is False
    assert preview.replay.probe_request("never-seen", "on") == ("unknown", None)
    assert preview.replay.probe_policy_update("never-seen", policy()) == "unknown"
    assert preview.replay.probe_window_seal("never-seen", 20) == "unknown"
    assert report["source_snapshot_sha256"] == json.loads(before)["sha256"]


def test_event_and_noop_replays_match_guard(tmp_path):
    g, path = init(tmp_path)
    assert g.request(target="on", request_id="noop-key", at_ms=1).reason == Reason.NO_CHANGE
    event(g, 2, "accepted-key")
    preview = g.checkpoint_preflight()
    assert preview.replay.count == 2
    assert preview.replay.probe_request("noop-key", "on") == ("replay", None)
    assert preview.replay.probe_request("noop-key", "sleep") == ("collision", None)
    assert preview.replay.probe_request("accepted-key", "sleep") == ("replay", "device-A:1")
    assert preview.replay.probe_request("accepted-key", "on") == ("collision", None)
    assert g.request(target="on", request_id="noop-key", at_ms=3).reason == Reason.REPLAY
    assert g.request(target="sleep", request_id="noop-key", at_ms=4).reason == Reason.REQUEST_ID_COLLISION
    result = g.request(target="sleep", request_id="accepted-key", at_ms=5)
    assert result.reason == Reason.REPLAY and result.event_id == "device-A:1"
    assert g.request(target="on", request_id="accepted-key", at_ms=6).reason == Reason.REQUEST_ID_COLLISION
    assert TransitionGuard.open(path).checkpoint_preflight().replay.digest == g.checkpoint_preflight().replay.digest


def test_schema2_policy_replay_and_cross_namespace_collisions(tmp_path):
    g, _ = init(tmp_path)
    event(g, 1, "edge")
    update(g, 2)
    preview = g.checkpoint_preflight()
    assert preview.to_dict()["schema"] == 2
    assert preview.replay.probe_policy_update("policy-key", policy()) == "replay"
    assert preview.replay.probe_policy_update("policy-key", policy(window=11)) == "collision"
    assert preview.replay.probe_policy_update("edge", policy()) == "collision"
    assert preview.replay.probe_request("policy-key", "on") == ("collision", None)
    assert preview.replay.probe_window_seal("policy-key", 10) == "collision"
    assert preview.replay.probe_window_seal("edge", 10) == "collision"
    assert preview.replay.probe_window_seal("new-key", 10) == "unknown"
    assert preview.to_dict()["policy_revision"] == 1


def test_schema3_seal_and_earlier_policy_epoch_protected(tmp_path):
    g, path = init(tmp_path)
    event(g, 1, "first")
    update(g, 2, window=20)
    update(g, 3, key="policy-tighten", window=10)
    seal(g, at=40, window=10)
    preview = g.checkpoint_preflight()
    report = preview.to_dict()
    assert report["schema"] == 3
    assert report["policy_revision"] == 2
    assert report["replay_identity_count"] == 4
    assert report["sealed_window_ceiling_ms"] == 10
    assert report["quota_expired_prefix_events"] == 1
    assert report["quota_retained_suffix_events"] == 0
    assert report["last_transition_ms"] == 1
    assert preview.replay.probe_window_seal("seal-key", 10) == "replay"
    assert preview.replay.probe_window_seal("seal-key", 11) == "collision"
    assert preview.replay.probe_window_seal("seal-key", 10.0) == "collision"
    assert preview.replay.probe_window_seal("seal-key", True) == "collision"
    assert preview.replay.probe_request("seal-key", "on") == ("collision", None)
    assert preview.replay.probe_policy_update("seal-key", policy()) == "collision"
    assert preview.replay.probe_policy_update("policy-key", policy(window=20)) == "replay"
    assert report["event_prefix_sha256"] == sha(list(g.history()))
    assert report["event_suffix_sha256"] == sha([])
    assert len(g.history()) == 1
    assert TransitionGuard.open(path).checkpoint_preflight().to_dict() == report


def test_exact_expiration_boundary_and_last_interval_anchor(tmp_path):
    g, _ = init(tmp_path)
    for at, key in ((1, "a"), (10, "b"), (20, "c"), (30, "d")):
        event(g, at, key)
    seal(g, at=40, window=10)
    m = g.checkpoint_preflight().to_dict()
    assert m["quota_expired_prefix_events"] == 4  # 30 == 40 - 10
    assert m["quota_retained_suffix_events"] == 0
    assert m["last_transition_ms"] == 30
    assert m["revision"] == 4
    assert len(g.history()) == 4


def test_no_seal_means_zero_candidate_prefix_even_if_events_old(tmp_path):
    g, _ = init(tmp_path)
    event(g, 1, "a")
    g.request(target="sleep", request_id="clock", at_ms=1000)
    m = g.checkpoint_preflight().to_dict()
    assert m["quota_expired_prefix_events"] == 0
    assert m["quota_retained_suffix_events"] == 1
    assert m["sealed_window_ceiling_ms"] is None
    assert m["journal_compaction_enabled"] is False


def test_rejected_request_id_is_not_added_to_replay_index(tmp_path):
    g, _ = init(tmp_path)
    assert g.request(target="missing", request_id="rejected-id", at_ms=1).reason == Reason.UNKNOWN_STATE
    view = g.checkpoint_preflight()
    assert view.replay.probe_request("rejected-id", "sleep") == ("unknown", None)
    assert view.to_dict()["replay_identity_count"] == 0
    assert g.request(target="sleep", request_id="rejected-id", at_ms=2).reason == Reason.ACCEPTED
    assert g.checkpoint_preflight().replay.probe_request("rejected-id", "sleep")[0] == "replay"


def test_manifest_digests_are_stable_and_source_bound(tmp_path):
    g, path = init(tmp_path)
    event(g, 10, "a")
    before = path.read_bytes()
    first = g.checkpoint_preflight().to_dict()
    second = TransitionGuard.open(path).checkpoint_preflight().to_dict()
    assert first == second
    assert path.read_bytes() == before
    assert first["source_snapshot_sha256"] == json.loads(before)["sha256"]
    assert len(first["replay_index_sha256"]) == len(first["policy_chain_sha256"]) == 64
    # A caller must never treat a preview as a transactionally current reference.
    assert g.request(target="sleep", request_id="clock", at_ms=11).reason == Reason.NO_CHANGE
    third = g.checkpoint_preflight().to_dict()
    assert third["source_snapshot_sha256"] != first["source_snapshot_sha256"]
    assert third["replay_identity_count"] == 2
    assert third["replay_index_sha256"] != first["replay_index_sha256"]
    assert first["replay_identity_count"] == 1


def test_detached_preview_and_manifest_copy(tmp_path):
    g, _ = init(tmp_path)
    before = g.checkpoint_preflight()
    mutable = before.to_dict()
    mutable["unresolved_dependencies"].clear()
    mutable["revision"] = 9999
    assert before.to_dict()["revision"] == 0
    assert before.to_dict()["unresolved_dependencies"]
    event(g, 1, "new")
    assert before.replay.probe_request("new", "sleep") == ("unknown", None)
    assert g.checkpoint_preflight().replay.probe_request("new", "sleep")[0] == "replay"


def test_direct_replay_builder_rejects_duplicate_ids(tmp_path):
    g, path = init(tmp_path)
    event(g, 1, "first")
    payload = json.loads(path.read_text())["payload"]
    payload["noops"].append({"request_id": "first", "target": "sleep", "at_ms": 1, "revision": 1})
    with pytest.raises(ValueError, match="duplicate"):
        build_replay_index(payload)


def test_corrupt_journal_rejected_before_build_even_if_rehashed(tmp_path):
    g, path = init(tmp_path)
    event(g, 1, "first")
    envelope = json.loads(path.read_text())
    envelope["payload"]["events"][0]["to"] = "on"  # breaks state history
    path.write_text(json.dumps(wrap(envelope["payload"])))
    with pytest.raises(InvalidSnapshot):
        g.checkpoint_preflight()


def test_read_only_preflight_never_saves(tmp_path, monkeypatch):
    g, path = init(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(g.store, "save", lambda _: pytest.fail("preflight must never save"))
    assert g.checkpoint_preflight().to_dict()["revision"] == 0
    assert path.read_bytes() == before


def test_cli_preflight_emits_only_digests_not_raw_replay_ids(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, path = init(tmp_path)
    event(g, 1, "secret-request-id-for-local-test")
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-plan", "--store", str(path)])
    assert main() == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["replay_identity_count"] == 1
    assert parsed["journal_compaction_enabled"] is False
    assert "secret-request-id-for-local-test" not in output
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["noop", "accepted", "policy", "seal"])
def test_replay_namespace_cross_kind_probes(tmp_path, operation):
    g, _ = init(tmp_path)
    g.request(target="on", request_id="noop", at_ms=0)
    event(g, 1, "edge")
    update(g, 2, key="policy")
    seal(g, at=3, window=10)
    idx = g.checkpoint_preflight().replay
    ids = {"noop": "noop", "accepted": "edge", "policy": "policy", "seal": "seal-key"}
    key = ids[operation]
    assert idx.probe_request(key, "unrelated")[0] == "collision"
    assert idx.probe_policy_update(key, policy(window=999)) == "collision"
    assert idx.probe_window_seal(key, 999) == "collision"


def test_randomized_replay_identity_oracle_against_guard(tmp_path):
    rng = random.Random(20261105)
    g, _ = init(tmp_path)
    records = []
    clock = 0
    for i in range(85):
        clock += rng.randint(0, 2)
        if i % 6 == 0:
            target = g.status()["state"]
            assert g.request(target=target, request_id=f"key-{i}", at_ms=clock).reason == Reason.NO_CHANGE
            kind = "noop"
        else:
            target = event(g, clock, f"key-{i}")
            kind = "event"
        records.append((f"key-{i}", target, kind))
    before = g.checkpoint_preflight()
    for key, target, kind in records:
        outcome, event_id = before.replay.probe_request(key, target)
        assert outcome == "replay"
        assert (event_id is None) == (kind == "noop")
        other = "on" if target == "sleep" else "sleep"
        assert before.replay.probe_request(key, other) == ("collision", None)
        actual = g.request(target=target, request_id=key, at_ms=clock)
        assert actual.reason == Reason.REPLAY and actual.event_id == event_id
        actual = g.request(target=other, request_id=key, at_ms=clock)
        assert actual.reason == Reason.REQUEST_ID_COLLISION
    assert g.status()["revision"] == 85 - len([x for x in records if x[2] == "noop"])
    assert before.replay.count == 85
    assert g.checkpoint_preflight().replay.digest == before.replay.digest
