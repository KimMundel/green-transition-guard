"""Optional schema-4 operation-ID budget. All journal history remains intact."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import sys

import pytest

from green_transition_guard import GuardError, InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.storage import wrap


def policy(window=10):
    return Policy(states=("on", "off"), edges=(("on", "off"), ("off", "on")),
                  min_dwell_ms={"on": 0, "off": 0}, min_interval_ms=0,
                  window_ms=window, max_transitions=200)


def prepare(tmp_path):
    path = tmp_path / "journal.json"
    g = TransitionGuard.initialize(path, device_id="test", policy=policy(),
                                   initial_state="on", entered_at_ms=0)
    return g, path


def seal_window(g, at=1):
    return g.seal_window_ceiling(max_future_window_ms=20, install_id="window-seal",
                                 at_ms=at, expected_policy_revision=g.status()["policy_revision"])


def seal_budget(g, cap, *, at=2, ident="budget-seal", rev=None):
    return g.seal_operation_budget(max_total_ids=cap, install_id=ident, at_ms=at,
                                   expected_policy_revision=(g.status()["policy_revision"] if rev is None else rev))


def rewrite(path, change):
    envelope = json.loads(path.read_text())
    change(envelope["payload"])
    path.write_text(json.dumps(wrap(envelope["payload"])))


def test_budget_requires_sealed_window_and_preserves_original_journal(tmp_path):
    g, path = prepare(tmp_path)
    old = path.read_bytes()
    with pytest.raises(GuardError, match="window ceiling"):
        seal_budget(g, 3)
    assert path.read_bytes() == old
    assert seal_window(g) == 20
    assert seal_budget(g, 2) == 2
    reopened = TransitionGuard.open(path)
    assert json.loads(path.read_text())["payload"]["schema"] == 4
    status = reopened.status()
    assert status["operation_budget_max"] == status["total_identities"] == 2
    assert status["window_ceiling_ms"] == 20
    assert status["policy_revision"] == 0
    assert status["revision"] == 0
    assert reopened.checkpoint_preflight().replay.probe_operation_budget("budget-seal", 2) == "replay"


def test_saturation_denies_new_noops_and_transitions_but_allows_replays(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    seal_budget(g, 4)
    assert g.request(target="on", request_id="noop", at_ms=3).reason == Reason.NO_CHANGE
    assert g.request(target="off", request_id="edge", at_ms=4).reason == Reason.ACCEPTED
    assert g.status()["total_identities"] == 4
    assert g.request(target="on", request_id="new-edge", at_ms=5).reason == Reason.JOURNAL_CAPACITY
    assert g.request(target="off", request_id="new-noop", at_ms=6).reason == Reason.JOURNAL_CAPACITY
    assert g.request(target="on", request_id="noop", at_ms=7).reason == Reason.REPLAY
    assert g.request(target="off", request_id="edge", at_ms=8).reason == Reason.REPLAY
    assert g.request(target="on", request_id="edge", at_ms=9).reason == Reason.REQUEST_ID_COLLISION
    assert g.request(target="off", request_id="budget-seal", at_ms=10).reason == Reason.REQUEST_ID_COLLISION
    assert g.request(target="off", request_id="window-seal", at_ms=11).reason == Reason.REQUEST_ID_COLLISION
    assert g.request(target="unknown", request_id="unknown", at_ms=12).reason == Reason.UNKNOWN_STATE
    r = TransitionGuard.open(path)
    assert r.status()["revision"] == 1
    assert r.status()["noops"] == 1
    assert r.status()["total_identities"] == 4
    assert r.status()["last_checked_ms"] == 12
    assert r.checkpoint_preflight().replay.count == 4


def test_full_budget_blocks_policy_update_but_identical_update_replays(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    g.update_policy(new_policy=policy(15), update_id="policy-1", at_ms=2, expected_policy_revision=0)
    seal_budget(g, 3, at=3, rev=1)
    with pytest.raises(GuardError, match="exhausted"):
        g.update_policy(new_policy=policy(12), update_id="policy-2", at_ms=4, expected_policy_revision=1)
    assert g.update_policy(new_policy=policy(15), update_id="policy-1", at_ms=5,
                           expected_policy_revision=0) == 1
    assert seal_budget(g, 3, at=6, rev=0) == 3
    assert g.seal_window_ceiling(max_future_window_ms=20, install_id="window-seal",
                                 at_ms=7, expected_policy_revision=0) == 20
    assert g.status()["total_identities"] == 3
    assert g.status()["last_checked_ms"] == 7
    assert TransitionGuard.open(path).status()["policy_revision"] == 1


def test_identity_limit_one_spare_slot_accepts_one_more_action(tmp_path):
    g, _ = prepare(tmp_path)
    seal_window(g)
    seal_budget(g, 3)
    assert g.request(target="off", request_id="first", at_ms=3).reason == Reason.ACCEPTED
    assert g.request(target="on", request_id="next", at_ms=4).reason == Reason.JOURNAL_CAPACITY
    assert g.status()["revision"] == 1


def test_sealing_rejects_existing_identity_count_and_stale_revision(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    g.request(target="off", request_id="old-event", at_ms=2)
    g.request(target="off", request_id="old-noop", at_ms=3)
    g.update_policy(new_policy=policy(12), update_id="old-policy", at_ms=4,
                    expected_policy_revision=0)
    original = path.read_bytes()
    with pytest.raises(GuardError, match="below existing"):
        seal_budget(g, 4, at=5, rev=1)
    with pytest.raises(GuardError, match="stale policy"):
        seal_budget(g, 5, at=5, rev=0)
    assert path.read_bytes() == original
    assert seal_budget(g, 5, at=5, rev=1) == 5
    assert g.status()["total_identities"] == 5
    assert g.checkpoint_preflight().replay.count == 5


@pytest.mark.parametrize("bad", [0, -1, 1.2, True, "3", None])
def test_invalid_limit_rejected_without_mutation(tmp_path, bad):
    g, path = prepare(tmp_path)
    seal_window(g)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        seal_budget(g, bad)
    assert path.read_bytes() == original


@pytest.mark.parametrize("bad", ["", "x"*257, None, 7])
def test_invalid_or_colliding_ids_rejected(tmp_path, bad):
    g, path = prepare(tmp_path)
    seal_window(g)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        seal_budget(g, 5, ident=bad)
    assert path.read_bytes() == original


def test_colliding_budget_id_and_one_way_immutability(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    g.request(target="off", request_id="event", at_ms=2)
    g.request(target="off", request_id="noop", at_ms=3)
    g.update_policy(new_policy=policy(12), update_id="policy", at_ms=4,
                    expected_policy_revision=0)
    for ident in ("window-seal", "event", "noop", "policy"):
        with pytest.raises(GuardError, match="collision"):
            seal_budget(g, 8, at=5, ident=ident)
    seal_budget(g, 8, at=5)
    original_budget = json.loads(path.read_text())["payload"]["operation_budget"]
    with pytest.raises(GuardError, match="already sealed"):
        seal_budget(g, 8, at=6, ident="different")
    with pytest.raises(GuardError, match="already sealed"):
        seal_budget(g, 7, at=6)
    with pytest.raises(GuardError, match="collision"):
        g.update_policy(new_policy=policy(13), update_id="budget-seal", at_ms=6,
                        expected_policy_revision=1)
    assert json.loads(path.read_text())["payload"]["operation_budget"] == original_budget
    assert seal_budget(g, 8, at=6) == 8
    with pytest.raises(GuardError, match="clock regression"):
        seal_budget(g, 8, at=5)


def test_policy_update_consumes_slot_and_cap_includes_all_kinds(tmp_path):
    g, _ = prepare(tmp_path)
    seal_window(g)
    seal_budget(g, 3)
    assert g.update_policy(new_policy=policy(13), update_id="policy-one", at_ms=3,
                           expected_policy_revision=0) == 1
    with pytest.raises(GuardError, match="exhausted"):
        g.update_policy(new_policy=policy(14), update_id="policy-two", at_ms=4,
                           expected_policy_revision=1)
    assert g.request(target="off", request_id="event", at_ms=4).reason == Reason.JOURNAL_CAPACITY


@pytest.mark.parametrize("mutation", [
    lambda p: p["operation_budget"].update(max_total_ids=1),
    lambda p: p["operation_budget"].update(max_total_ids=True),
    lambda p: p["operation_budget"].update(id="window-seal"),
    lambda p: p["operation_budget"].update(id=""),
    lambda p: p["operation_budget"].update(at_ms=0),
    lambda p: p["operation_budget"].update(after_event_seq=99),
    lambda p: p["operation_budget"].update(after_noop_count=99),
    lambda p: p["operation_budget"].update(after_policy_revision=99),
    lambda p: p["operation_budget"].update(extra=10),
    lambda p: p.pop("operation_budget"),
    lambda p: p.update(schema=3),
])
def test_schema4_corruption_fails_closed_even_with_matching_checksum(tmp_path, mutation):
    g, path = prepare(tmp_path)
    seal_window(g)
    g.request(target="off", request_id="edge", at_ms=2)
    seal_budget(g, 4, at=3)
    g.request(target="on", request_id="another", at_ms=4)
    rewrite(path, mutation)
    with pytest.raises(InvalidSnapshot):
        TransitionGuard.open(path)


def test_archive_replay_includes_budget_seal(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    seal_budget(g, 3)
    g.request(target="off", request_id="edge", at_ms=3)
    archived = tmp_path / "journal.checkpoint-1.json"
    view = g.create_checkpoint_archive(archived)
    assert view.replay.count == 3
    assert view.replay.probe_operation_budget("budget-seal", 3) == "replay"
    assert view.replay.probe_operation_budget("budget-seal", 4) == "collision"
    assert view.replay.probe_window_seal("budget-seal", 20) == "collision"
    assert g.verify_checkpoint_archive(archived).matches_current_journal is True
    assert view.to_dict()["source_schema"] == 4
    assert TransitionGuard.open(path).status()["operation_budget_max"] == 3


def test_before_replace_failure_does_not_install_budget(tmp_path, monkeypatch):
    g, path = prepare(tmp_path)
    seal_window(g)
    before = path.read_bytes()
    monkeypatch.setattr(g.store, "save", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        seal_budget(g, 2)
    assert path.read_bytes() == before
    assert TransitionGuard.open(path).status()["operation_budget_max"] is None


def test_after_replace_error_reconciles_by_id(tmp_path, monkeypatch):
    g, path = prepare(tmp_path)
    seal_window(g)
    original_save = g.store.save
    def uncertain_write(data):
        original_save(data)
        raise OSError("durability uncertain")
    monkeypatch.setattr(g.store, "save", uncertain_write)
    with pytest.raises(OSError, match="uncertain"):
        seal_budget(g, 2)
    h = TransitionGuard.open(path)
    assert seal_budget(h, 2, at=3) == 2
    assert h.status()["operation_budget_max"] == 2


def test_cli_seal_budget_and_fail_closed_code(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, path = prepare(tmp_path)
    seal_window(g)
    monkeypatch.setattr(sys, "argv", ["green-guard", "seal-budget", "--store", str(path),
                                     "--max-identities", "2", "--install-id", "budget-seal",
                                     "--time-ms", "2", "--expected-policy-revision", "0"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"]["total_identities"] == 2
    monkeypatch.setattr(sys, "argv", ["green-guard", "request", "--store", str(path),
                                     "--target", "off", "--request-id", "first",
                                     "--time-ms", "3"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "journal-capacity" and not result["allowed"]


def _writer(arguments):
    path, ident = arguments
    g = TransitionGuard.open(path)
    return g.request(target="off", request_id=ident, at_ms=3).reason.value


def test_concurrent_writers_cannot_pass_identity_capacity(tmp_path):
    g, path = prepare(tmp_path)
    seal_window(g)
    seal_budget(g, 3)
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context("spawn")) as pool:
        results = list(pool.map(_writer, [(str(path), f"writer-{i}") for i in range(6)]))
    assert sorted(results) == ["accepted"] + ["journal-capacity"]*5
    assert TransitionGuard.open(path).status()["total_identities"] == 3
