"""Immutable, full-history archive candidate tests; no journal pruning is authorized."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from green_transition_guard import InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard import experimental_archive as archive
from green_transition_guard.storage import wrap


def policy(window=20):
    return Policy(
        states=("active", "sleep"), edges=(("active", "sleep"), ("sleep", "active")),
        min_dwell_ms={"active": 0, "sleep": 0}, min_interval_ms=0,
        window_ms=window, max_transitions=100,
    )


def setup(tmp_path):
    path = tmp_path / "guard.json"
    guard = TransitionGuard.initialize(
        path, device_id="device", policy=policy(),
        initial_state="active", entered_at_ms=0,
    )
    return guard, path, tmp_path / "checkpoint.json"


def event(g, target="sleep", key="event", at=1):
    assert g.request(target=target, request_id=key, at_ms=at).reason == Reason.ACCEPTED


def set_schema(g, schema):
    event(g)
    if schema >= 2:
        g.update_policy(new_policy=policy(15), update_id="policy-id", at_ms=2,
                        expected_policy_revision=0)
    if schema == 3:
        g.seal_window_ceiling(max_future_window_ms=15, install_id="seal-id",
                              at_ms=3, expected_policy_revision=1)


def rewrite_archive(path, mutate):
    container = json.loads(path.read_text())
    payload = container["payload"]
    mutate(payload)
    path.write_text(json.dumps(wrap(payload)))


def reader(path):
    return json.loads(path.read_text())["payload"]


@pytest.mark.parametrize("schema", [1, 2, 3])
def test_create_exact_valid_archive_for_each_schema(tmp_path, schema):
    g, source, path = setup(tmp_path)
    set_schema(g, schema)
    before = source.read_bytes()
    result = g.create_checkpoint_archive(path).to_dict()
    assert source.read_bytes() == before
    assert reader(path)["source_snapshot"] == json.loads(before)["payload"]
    assert result["format"] == "experimental-checkpoint-archive-1"
    assert result["source_schema"] == schema
    assert result["matches_current_journal"] is True
    assert result["complete_source_history_preserved"] is True
    assert result["journal_compaction_enabled"] is False
    assert result["authenticated_rollback_protection"] is False
    assert result["source_snapshot_sha256"] == json.loads(before)["sha256"]
    assert result["archive_payload_sha256"] == json.loads(path.read_text())["sha256"]
    assert (path.stat().st_mode & 0o777) == 0o600
    assert TransitionGuard.open(source).verify_checkpoint_archive(path).to_dict() == result
    assert g.checkpoint_preflight().to_dict() == reader(path)["preflight_manifest"]


def test_exact_replay_ids_survive_in_independent_archive(tmp_path):
    g, source, path = setup(tmp_path)
    event(g, key="event-id", at=1)
    assert g.request(target="sleep", request_id="noop-id", at_ms=2).reason == Reason.NO_CHANGE
    g.update_policy(new_policy=policy(15), update_id="update-id", at_ms=3,
                    expected_policy_revision=0)
    g.seal_window_ceiling(max_future_window_ms=15, install_id="seal-id",
                          at_ms=4, expected_policy_revision=1)
    view = g.create_checkpoint_archive(path)
    assert view.replay.count == 4
    assert view.replay.probe_request("event-id", "sleep") == ("replay", "device:1")
    assert view.replay.probe_request("noop-id", "sleep") == ("replay", None)
    assert view.replay.probe_request("event-id", "active") == ("collision", None)
    assert view.replay.probe_policy_update("update-id", policy(15)) == "replay"
    assert view.replay.probe_policy_update("update-id", policy(20)) == "collision"
    assert view.replay.probe_window_seal("seal-id", 15) == "replay"
    assert view.replay.probe_window_seal("seal-id", 16) == "collision"
    assert view.replay.probe_request("update-id", "sleep") == ("collision", None)
    assert view.replay.probe_request("seal-id", "sleep") == ("collision", None)
    # Archive validity does not rely on the exporting Python process.
    reopened = TransitionGuard.open(source).verify_checkpoint_archive(path)
    assert reopened.replay.probe_request("event-id", "sleep") == ("replay", "device:1")
    assert reopened.replay.digest == view.replay.digest
    # No raw request IDs appear in the public inspection report.
    summary = json.dumps(view.to_dict())
    for key in ("event-id", "noop-id", "update-id", "seal-id"):
        assert key not in summary


def test_archive_is_create_only_even_for_identical_snapshot(tmp_path):
    g, source, path = setup(tmp_path)
    original = source.read_bytes()
    g.create_checkpoint_archive(path)
    archived = path.read_bytes()
    with pytest.raises(FileExistsError):
        g.create_checkpoint_archive(path)
    assert source.read_bytes() == original
    assert path.read_bytes() == archived
    assert g.verify_checkpoint_archive(path).matches_current_journal is True


@pytest.mark.parametrize("change", ["clock", "noop", "transition", "policy"])
def test_source_change_makes_archive_stale_without_corrupting_it(tmp_path, change):
    g, source, path = setup(tmp_path)
    g.create_checkpoint_archive(path)
    before = path.read_bytes()
    if change == "clock":
        g.request(target="missing", request_id="rejected", at_ms=4)
    elif change == "noop":
        assert g.request(target="active", request_id="noop", at_ms=4).reason == Reason.NO_CHANGE
    elif change == "transition":
        event(g, at=4)
    else:
        g.update_policy(new_policy=policy(15), update_id="update", at_ms=4,
                        expected_policy_revision=0)
    view = g.verify_checkpoint_archive(path)
    assert view.matches_current_journal is False
    assert view.replay.probe_request("event", "sleep")[0] == "unknown"
    assert path.read_bytes() == before
    new_path = tmp_path / "next-checkpoint.json"
    fresh = g.create_checkpoint_archive(new_path)
    assert fresh.matches_current_journal is True
    assert g.verify_checkpoint_archive(path).matches_current_journal is False


def test_archive_manifest_tamper_rejected_even_with_recomputed_checksum(tmp_path):
    g, _, path = setup(tmp_path)
    event(g)
    g.create_checkpoint_archive(path)
    rewrite_archive(path, lambda p: p["preflight_manifest"].update(revision=987))
    with pytest.raises(InvalidSnapshot, match="manifest"):
        g.verify_checkpoint_archive(path)


def test_archive_history_tamper_rejected_even_with_recomputed_checksum(tmp_path):
    g, _, path = setup(tmp_path)
    event(g)
    g.create_checkpoint_archive(path)
    rewrite_archive(path, lambda p: p["source_snapshot"]["events"][0].update(to="active"))
    with pytest.raises(InvalidSnapshot):
        g.verify_checkpoint_archive(path)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(format="unknown"),
    lambda p: p.pop("preflight_manifest"),
    lambda p: p.update(extra=1),
    lambda p: p.update(source_snapshot=None),
    lambda p: p.update(preflight_manifest={}),
])
def test_archive_structure_tamper_rejected(tmp_path, mutation):
    g, _, path = setup(tmp_path)
    g.create_checkpoint_archive(path)
    rewrite_archive(path, mutation)
    with pytest.raises(InvalidSnapshot):
        g.verify_checkpoint_archive(path)


def test_archive_checksum_mismatch_rejected(tmp_path):
    g, _, path = setup(tmp_path)
    g.create_checkpoint_archive(path)
    contents = json.loads(path.read_text())
    contents["sha256"] = "0" * 64
    path.write_text(json.dumps(contents))
    with pytest.raises(InvalidSnapshot, match="checksum"):
        g.verify_checkpoint_archive(path)


def test_corrupt_live_source_rejects_create_and_verify(tmp_path):
    g, source, path = setup(tmp_path)
    g.create_checkpoint_archive(path)
    original_archive = path.read_bytes()
    data = json.loads(source.read_text())
    data["payload"]["revision"] = 99
    source.write_text(json.dumps(data))
    with pytest.raises(InvalidSnapshot):
        g.verify_checkpoint_archive(path)
    with pytest.raises(InvalidSnapshot):
        g.create_checkpoint_archive(tmp_path / "other-archive.json")
    assert path.read_bytes() == original_archive
    assert not (tmp_path / "other-archive.json").exists()


@pytest.mark.parametrize("requested", [
    "relative.json", "../relative.json", "guard.json", "guard.json.lock",
    "archive.lock"
])
def test_unsafe_archive_names_rejected(tmp_path, requested):
    g, source, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        g.create_checkpoint_archive(requested if not requested.startswith("guard")
                                    and requested != "archive.lock" else tmp_path / requested)
    assert g.status()["revision"] == 0


def test_archive_must_be_same_directory(tmp_path):
    g, _, _ = setup(tmp_path)
    sibling = tmp_path / "external"
    sibling.mkdir()
    with pytest.raises(ValueError, match="directory"):
        g.create_checkpoint_archive(sibling / "archive.json")
    assert not (sibling / "archive.json").exists()


def test_existing_symlink_cannot_be_replaced(tmp_path):
    g, _, path = setup(tmp_path)
    other = tmp_path / "other.txt"
    other.write_text("precious")
    path.symlink_to(other)
    with pytest.raises(FileExistsError):
        g.create_checkpoint_archive(path)
    assert path.is_symlink()
    assert other.read_text() == "precious"


def test_missing_archive_is_error_and_source_unchanged(tmp_path):
    g, source, path = setup(tmp_path)
    before = source.read_bytes()
    with pytest.raises(FileNotFoundError):
        g.verify_checkpoint_archive(path)
    assert source.read_bytes() == before


@pytest.mark.parametrize("stage", ["mkstemp", "fdopen", "partial-write", "file-fsync", "link-before"])
def test_prepublication_errors_never_create_archive(tmp_path, monkeypatch, stage):
    g, source, path = setup(tmp_path)
    before = source.read_bytes()

    def fail(*args, **kwargs):
        raise OSError(f"injected {stage}")

    if stage == "mkstemp":
        monkeypatch.setattr(archive.tempfile, "mkstemp", fail)
    elif stage == "fdopen":
        monkeypatch.setattr(archive.os, "fdopen", fail)
    elif stage == "partial-write":
        def partial(obj, handle, **kwargs):
            handle.write('{"partial":')
            fail()
        monkeypatch.setattr(archive.json, "dump", partial)
    elif stage == "file-fsync":
        original_fsync = os.fsync
        def fsync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                fail()
            return original_fsync(fd)
        monkeypatch.setattr(archive.os, "fsync", fsync)
    elif stage == "link-before":
        monkeypatch.setattr(archive.os, "link", fail)
    with pytest.raises(OSError, match="injected"):
        g.create_checkpoint_archive(path)
    assert not path.exists()
    assert not list(tmp_path.glob(".checkpoint.json.*"))
    assert source.read_bytes() == before


@pytest.mark.parametrize("stage", ["link-after", "directory-fsync"])
def test_postpublication_errors_require_explicit_reconciliation(tmp_path, monkeypatch, stage):
    g, source, path = setup(tmp_path)
    before = source.read_bytes()
    if stage == "link-after":
        original = os.link
        def link(src, dst):
            original(src, dst)
            raise OSError("injected post-link uncertainty")
        monkeypatch.setattr(archive.os, "link", link)
    else:
        original = os.fsync
        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory fsync uncertainty")
            return original(fd)
        monkeypatch.setattr(archive.os, "fsync", fsync)
    with pytest.raises(OSError, match="injected"):
        g.create_checkpoint_archive(path)
    assert source.read_bytes() == before
    # In-process visibility is not a power-loss durability guarantee.
    assert path.exists()
    assert not list(tmp_path.glob(".checkpoint.json.*"))
    assert g.verify_checkpoint_archive(path).matches_current_journal is True
    with pytest.raises(FileExistsError):
        g.create_checkpoint_archive(path)


def _concurrent_export(source, target):
    try:
        TransitionGuard.open(source).create_checkpoint_archive(target)
        return "created"
    except FileExistsError:
        return "exists"


def test_concurrent_writers_cannot_overwrite_same_archive(tmp_path):
    g, source, path = setup(tmp_path)
    with ProcessPoolExecutor(max_workers=3, mp_context=get_context("spawn")) as pool:
        results = list(pool.map(_concurrent_export, [source] * 3, [path] * 3))
    assert sorted(results) == ["created", "exists", "exists"]
    assert g.verify_checkpoint_archive(path).matches_current_journal is True


def test_cli_export_verify_no_request_id_leak_and_stale_status(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, source, path = setup(tmp_path)
    event(g, key="secret-replay-id")
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-export", "--store", str(source),
                                      "--archive", str(path)])
    assert main() == 0
    exported = capsys.readouterr().out
    assert "secret-replay-id" not in exported
    assert json.loads(exported)["replay_identity_count"] == 1
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-verify", "--store", str(source),
                                      "--archive", str(path)])
    assert main() == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["matches_current_journal"] is True
    assert "secret-replay-id" not in json.dumps(verified)
    assert g.request(target="sleep", request_id="clock", at_ms=9).reason == Reason.NO_CHANGE
    assert main() == 3  # stale archive must have nonzero CLI status
    stale = json.loads(capsys.readouterr().out)
    assert stale["matches_current_journal"] is False


def test_cli_existing_archive_does_not_overwrite(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, source, path = setup(tmp_path)
    g.create_checkpoint_archive(path)
    original = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-export", "--store", str(source),
                                      "--archive", str(path)])
    assert main() == 2
    assert "FileExistsError" in capsys.readouterr().err
    assert path.read_bytes() == original


def test_standalone_archive_inspection_when_live_journal_is_lost(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    g, source, path = setup(tmp_path)
    event(g, key="private-event-id", at=1)
    g.create_checkpoint_archive(path)
    # The archival copy is complete enough for independent inspection.
    source.unlink()
    view = archive.inspect_checkpoint_archive(path)
    assert view.matches_current_journal is None
    assert view.replay.probe_request("private-event-id", "sleep") == ("replay", "device:1")
    assert view.to_dict()["journal_compaction_enabled"] is False
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-inspect", "--archive", str(path)])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["matches_current_journal"] is None
    assert "private-event-id" not in json.dumps(result)
    # Inspecting historical bytes does not imply the archive is latest or safe to restore.
    assert result["authenticated_rollback_protection"] is False


def test_independent_archive_inspection_detects_corrupt_source(tmp_path):
    g, source, path = setup(tmp_path)
    event(g)
    g.create_checkpoint_archive(path)
    rewrite_archive(path, lambda p: p["source_snapshot"].update(revision=991))
    source.unlink()
    with pytest.raises(InvalidSnapshot):
        archive.inspect_checkpoint_archive(path)


def test_archive_export_file_descriptor_is_closed_on_fdopen_failure(tmp_path, monkeypatch):
    g, _, path = setup(tmp_path)
    original_mkstemp = archive.tempfile.mkstemp
    captured = []
    def mkstemp(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        captured.append(fd)
        return fd, name
    def failed_fdopen(fd, *args, **kwargs):
        raise OSError("injected fdopen")
    monkeypatch.setattr(archive.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(archive.os, "fdopen", failed_fdopen)
    with pytest.raises(OSError, match="injected fdopen"):
        g.create_checkpoint_archive(path)
    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])
    assert not path.exists()
    assert not list(tmp_path.glob(".checkpoint.json.*"))
