"""HMAC witness receipts: authenticated relative to external, caller-owned roots only."""

from copy import deepcopy
import json
import os
import sys

import pytest

from green_transition_guard import InvalidSnapshot, Policy, Reason, TransitionGuard
from green_transition_guard.experimental_archive import inspect_checkpoint_archive
from green_transition_guard.experimental_witness import (
    WITNESS_FORMAT, issue_checkpoint_witness, load_witness_key,
    verify_checkpoint_witness,
)
from green_transition_guard.storage import wrap

KEY = bytes(range(32))
KEY2 = bytes(range(1, 33))


def policy(window=10):
    return Policy(states=("on", "off"), edges=(("on", "off"), ("off", "on")),
                  min_dwell_ms={"on": 0, "off": 0}, min_interval_ms=0,
                  window_ms=window, max_transitions=100)


def setup(tmp_path, schema=1):
    live = tmp_path / "device.guard.json"
    archive = tmp_path / "device.archive.json"
    guard = TransitionGuard.initialize(live, device_id="device-123", policy=policy(),
                                       initial_state="on", entered_at_ms=0)
    assert guard.request(target="off", request_id="SENSITIVE-REQUEST-ID", at_ms=1).reason == Reason.ACCEPTED
    if schema >= 2:
        guard.update_policy(new_policy=policy(window=20), update_id="policy-1",
                            at_ms=2, expected_policy_revision=0)
    if schema >= 3:
        guard.seal_window_ceiling(max_future_window_ms=20, install_id="window-seal",
                                  at_ms=3, expected_policy_revision=1)
    if schema == 4:
        guard.seal_operation_budget(max_total_ids=20, install_id="budget-seal",
                                    at_ms=4, expected_policy_revision=1)
    view = guard.create_checkpoint_archive(archive)
    return guard, live, archive, view.to_dict()["source_snapshot_sha256"]


def receipt(archive, generation=5):
    return issue_checkpoint_witness(archive, secret=KEY, generation=generation, witness_id="test-witness")


def verify(archive, value, **overrides):
    args = {"secret": KEY, "expected_device_id": "device-123", "trusted_min_generation": 5,
            "trusted_snapshot_sha256": inspect_checkpoint_archive(archive).to_dict()["source_snapshot_sha256"]}
    args.update(overrides)
    return verify_checkpoint_witness(archive, value, **args)


@pytest.mark.parametrize("schema", [1, 2, 3, 4])
def test_witness_roundtrip_all_schemas(tmp_path, schema):
    g, live, archive, root = setup(tmp_path, schema)
    before = archive.read_bytes(), live.read_bytes()
    signed = receipt(archive)
    result = verify(archive, signed).to_dict()
    assert signed["format"] == result["format"] == WITNESS_FORMAT
    assert signed["source_schema"] == schema
    assert signed["source_snapshot_sha256"] == root
    assert signed["source_revision"] == 1
    assert result["authenticated_to_supplied_key"] is True
    assert result["matches_supplied_trusted_root"] is True
    assert result["trusted_generation_floor_satisfied"] is True
    assert result["status"] == "verified_relative_to_external_inputs"
    assert result["journal_compaction_enabled"] is False
    assert result["restoration_enabled"] is False
    assert result["independent_trust_established_by_module"] is False
    assert "SENSITIVE-REQUEST-ID" not in json.dumps(result)
    assert "SENSITIVE-REQUEST-ID" not in json.dumps(signed)
    assert (archive.read_bytes(), live.read_bytes()) == before


def test_hmac_is_deterministic_for_same_receipt_input(tmp_path):
    _, _, archive, _ = setup(tmp_path)
    assert receipt(archive) == receipt(archive)
    assert receipt(archive, generation=6)["hmac_sha256"] != receipt(archive)["hmac_sha256"]


def test_wrong_key_or_forged_hmac_fails_before_inspecting_history(tmp_path):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    with pytest.raises(InvalidSnapshot, match="authentication failed"):
        verify(archive, signed, secret=KEY2)
    signed["hmac_sha256"] = "0" * 64
    with pytest.raises(InvalidSnapshot, match="authentication failed"):
        verify(archive, signed)


@pytest.mark.parametrize("field,replacement", [
    ("generation", 123), ("source_revision", 99), ("source_schema", 4),
    ("witness_id", "evil"), ("device_id", "device-124"),
    ("source_snapshot_sha256", "a" * 64), ("archive_payload_sha256", "b" * 64),
    ("source_policy_revision", 12), ("source_as_of_ms", 999),
])
def test_modification_without_hmac_key_detected(tmp_path, field, replacement):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    signed[field] = replacement
    with pytest.raises(InvalidSnapshot, match="authentication failed"):
        verify(archive, signed)


@pytest.mark.parametrize("field,replacement", [
    ("generation", True), ("generation", 0), ("generation", -1),
    ("witness_id", ""), ("witness_id", "x" * 129),
    ("source_revision", False), ("source_as_of_ms", -1),
    ("source_snapshot_sha256", "G" * 64), ("hmac_sha256", "not-a-hmac"),
    ("format", "wrong-format"),
])
def test_invalid_receipt_field_types_rejected(tmp_path, field, replacement):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    signed[field] = replacement
    with pytest.raises(InvalidSnapshot, match="contents"):
        verify(archive, signed)


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("source_revision"),
    lambda p: p.update(extra="unexpected"),
    lambda p: p.pop("hmac_sha256"),
])
def test_receipt_shape_rejected(tmp_path, mutation):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    mutation(signed)
    with pytest.raises(InvalidSnapshot, match="fields"):
        verify(archive, signed)


@pytest.mark.parametrize("invalid", [b"", b"short", "string", None, bytearray(range(32)), b"x" * 4097])
def test_weak_or_unsafe_keys_rejected(tmp_path, invalid):
    _, _, archive, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="secret"):
        issue_checkpoint_witness(archive, secret=invalid, generation=5, witness_id="w")
    signed = receipt(archive)
    with pytest.raises(ValueError, match="secret"):
        verify(archive, signed, secret=invalid)


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.0, "4", None])
def test_invalid_claimed_generation_rejected(tmp_path, invalid):
    _, _, archive, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="generation"):
        issue_checkpoint_witness(archive, secret=KEY, generation=invalid, witness_id="w")


@pytest.mark.parametrize("invalid", ["", "a" * 129, None, 234])
def test_invalid_witness_id_rejected(tmp_path, invalid):
    _, _, archive, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="witness_id"):
        issue_checkpoint_witness(archive, secret=KEY, generation=3, witness_id=invalid)


def test_below_independently_supplied_generation_floor_is_flagged(tmp_path):
    _, _, archive, root = setup(tmp_path)
    signed = receipt(archive, generation=5)
    r = verify(archive, signed, trusted_min_generation=6).to_dict()
    assert r["status"] == "below_trusted_floor"
    assert r["trusted_generation_floor_satisfied"] is False
    assert r["source_snapshot_sha256"] == root


def test_wrong_trusted_device_and_snapshot_root_rejected(tmp_path):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    with pytest.raises(InvalidSnapshot, match="different device"):
        verify(archive, signed, expected_device_id="another")
    with pytest.raises(InvalidSnapshot, match="trusted root"):
        verify(archive, signed, trusted_snapshot_sha256="0" * 64)


@pytest.mark.parametrize("override", [
    {"expected_device_id": ""}, {"trusted_min_generation": True},
    {"trusted_min_generation": 0}, {"trusted_min_generation": 1.5},
    {"trusted_snapshot_sha256": "0"}, {"trusted_snapshot_sha256": "A" * 64},
])
def test_invalid_external_trust_inputs_rejected(tmp_path, override):
    _, _, archive, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        verify(archive, receipt(archive), **override)


def test_authentic_witness_for_another_valid_archive_rejected(tmp_path):
    g, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    assert g.request(target="on", request_id="later", at_ms=10).reason == Reason.ACCEPTED
    new_archive = tmp_path / "new.archive.json"
    g.create_checkpoint_archive(new_archive)
    with pytest.raises(InvalidSnapshot, match="does not match complete archive"):
        verify(new_archive, signed)


def test_corrupt_archive_is_detected_even_with_authentic_receipt(tmp_path):
    _, _, archive, _ = setup(tmp_path)
    signed = receipt(archive)
    obj = json.loads(archive.read_text())
    obj["payload"]["preflight_manifest"]["revision"] = 987
    archive.write_text(json.dumps(wrap(obj["payload"])))
    with pytest.raises(InvalidSnapshot, match="manifest disagrees"):
        verify(archive, signed)


def test_receipt_works_offline_without_live_journal(tmp_path):
    _, live, archive, root = setup(tmp_path, 4)
    signed = receipt(archive)
    live.unlink()
    report = verify(archive, signed).to_dict()
    assert report["matches_supplied_trusted_root"] is True
    assert report["source_snapshot_sha256"] == root
    assert report["restoration_enabled"] is False


def test_key_file_owner_only_and_symlink_defense(tmp_path):
    path = tmp_path / "witness.key"
    path.write_bytes(KEY)
    path.chmod(0o600)
    assert load_witness_key(path) == KEY
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        load_witness_key(path)
    path.chmod(0o600)
    link = tmp_path / "link.key"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_witness_key(link)
    path.write_bytes(b"bad")
    with pytest.raises(ValueError, match="secret"):
        load_witness_key(path)
    path.write_bytes(b"x" * 4097)
    with pytest.raises(ValueError, match="owner-only"):
        load_witness_key(path)


def test_cli_issue_and_verify_with_external_root_and_floor(tmp_path, monkeypatch, capsys):
    from green_transition_guard.cli import main
    _, _, archive, root = setup(tmp_path, 4)
    key_file = tmp_path / "keyfile"
    key_file.write_bytes(KEY)
    key_file.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["green-guard", "checkpoint-witness-issue",
                                      "--archive", str(archive), "--key-file", str(key_file),
                                      "--generation", "7", "--witness-id", "issuer-1"])
    assert main() == 0
    issue_output = capsys.readouterr().out
    witness = json.loads(issue_output)
    assert witness["generation"] == 7
    assert "SENSITIVE-REQUEST-ID" not in issue_output
    assert KEY.hex() not in issue_output
    receipt_file = tmp_path / "trusted-receipt.json"
    receipt_file.write_text(issue_output)
    args = ["green-guard", "checkpoint-witness-verify", "--archive", str(archive),
            "--receipt", str(receipt_file), "--key-file", str(key_file),
            "--expected-device-id", "device-123", "--trusted-min-generation", "7",
            "--trusted-snapshot-sha256", root]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["trusted_generation_floor_satisfied"] is True
    monkeypatch.setattr(sys, "argv", args[:args.index("--trusted-min-generation") + 1]
                        + ["8", "--trusted-snapshot-sha256", root])
    assert main() == 3
    assert json.loads(capsys.readouterr().out)["status"] == "below_trusted_floor"
    receipt_file.write_text("{}")
    assert main() == 2
    capsys.readouterr()


def test_receipts_with_same_generation_do_not_establish_unique_order(tmp_path):
    g, _, older, old_root = setup(tmp_path)
    older_receipt = receipt(older, generation=10)
    assert g.request(target="on", request_id="new-event", at_ms=10).reason == Reason.ACCEPTED
    newer = tmp_path / "new.archive.json"
    g.create_checkpoint_archive(newer)
    newer_receipt = receipt(newer, generation=10)
    assert newer_receipt["generation"] == older_receipt["generation"]
    assert old_root != newer_receipt["source_snapshot_sha256"]
    # The experimental module does not run a uniqueness-enforcing trusted issuer.
    assert verify(older, older_receipt, trusted_min_generation=10).meets_trusted_floor
    assert verify(newer, newer_receipt, trusted_snapshot_sha256=newer_receipt["source_snapshot_sha256"]).meets_trusted_floor
