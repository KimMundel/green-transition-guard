"""Experimental HMAC checkpoint witness with caller-supplied external trust.

Receipts authenticate a complete archive to a caller-held key and state a
claimed generation. The caller MUST obtain the expected source digest and a
monotonic generation floor from an independent trusted service. This module
cannot create such a trust anchor; no recovery or compaction is authorized.
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Any

from .experimental_archive import inspect_checkpoint_archive
from .storage import InvalidSnapshot, canonical_bytes

WITNESS_FORMAT = "experimental-checkpoint-witness-1"
_FIELDS = frozenset({"format", "witness_id", "generation", "device_id", "source_snapshot_sha256",
                     "archive_payload_sha256", "source_schema", "source_revision",
                     "source_policy_revision", "source_as_of_ms"})
_HEX = frozenset("0123456789abcdef")


def _key(secret: bytes) -> bytes:
    if not isinstance(secret, bytes) or not 32 <= len(secret) <= 4096:
        raise ValueError("witness secret must be 32..4096 raw random bytes")
    return secret


def _hex_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in _HEX for ch in value)


def load_witness_key(path: str | Path) -> bytes:
    """Load a local test key. No symlinks, group access, or world access.

    Key-file permissions cannot establish independent hardware/storage trust.
    An actual witness service should supply signing/verifying functions outside
    the journal host. Never check key material into this repository.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
            raise ValueError("witness key must be an owner-only regular file")
        with os.fdopen(os.dup(fd), "rb") as handle:
            data = handle.read(4097)
        return _key(data)
    finally:
        os.close(fd)


def _receipt_fields(archive) -> dict[str, Any]:
    meta = archive.to_dict()
    preflight = archive._archive["preflight_manifest"]
    return {
        "device_id": preflight["device_id"],
        "source_snapshot_sha256": meta["source_snapshot_sha256"],
        "archive_payload_sha256": meta["archive_payload_sha256"],
        "source_schema": meta["source_schema"],
        "source_revision": meta["source_revision"],
        "source_policy_revision": meta["source_policy_revision"],
        "source_as_of_ms": preflight["as_of_ms"],
    }


def _mac(fields: dict[str, Any], secret: bytes) -> str:
    return hmac.new(secret, canonical_bytes(fields), hashlib.sha256).hexdigest()


def issue_checkpoint_witness(
    archive_path: str | Path, *, secret: bytes, generation: int, witness_id: str
) -> dict[str, Any]:
    """Sign a previously verified, complete archive for an external witness.

    A generation is merely a claim until independently recorded monotonicity
    and uniqueness are enforced outside the device/filesystem.
    """
    _key(secret)
    if type(generation) is not int or generation < 1:
        raise ValueError("generation must be a positive integer")
    if not isinstance(witness_id, str) or not 1 <= len(witness_id) <= 128:
        raise ValueError("witness_id must contain 1..128 characters")
    archive = inspect_checkpoint_archive(archive_path)
    body = {"format": WITNESS_FORMAT, "witness_id": witness_id, "generation": generation,
            **_receipt_fields(archive)}
    return {**body, "hmac_sha256": _mac(body, secret)}


def _validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != _FIELDS | {"hmac_sha256"}:
        raise InvalidSnapshot("invalid checkpoint witness fields")
    if (receipt["format"] != WITNESS_FORMAT
            or not isinstance(receipt["witness_id"], str)
            or not 1 <= len(receipt["witness_id"]) <= 128
            or not isinstance(receipt["device_id"], str) or not receipt["device_id"]
            or type(receipt["generation"]) is not int or receipt["generation"] < 1
            or not all(type(receipt[k]) is int and receipt[k] >= 0 for k in (
                "source_schema", "source_revision", "source_policy_revision", "source_as_of_ms"
            ))
            or not all(_hex_sha(receipt[k]) for k in (
                "source_snapshot_sha256", "archive_payload_sha256", "hmac_sha256"
            ))):
        raise InvalidSnapshot("invalid checkpoint witness contents")
    return {key: value for key, value in receipt.items() if key != "hmac_sha256"}


@dataclass(frozen=True)
class WitnessVerification:
    witness_id: str
    generation: int
    source_snapshot_sha256: str
    meets_trusted_floor: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": WITNESS_FORMAT,
            "witness_id": self.witness_id,
            "generation": self.generation,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "authenticated_to_supplied_key": True,
            "matches_supplied_trusted_root": True,
            "trusted_generation_floor_satisfied": self.meets_trusted_floor,
            "status": "verified_relative_to_external_inputs" if self.meets_trusted_floor else "below_trusted_floor",
            "independent_trust_established_by_module": False,
            "restoration_enabled": False,
            "journal_compaction_enabled": False,
        }


def verify_checkpoint_witness(
    archive_path: str | Path, receipt: dict[str, Any], *, secret: bytes,
    expected_device_id: str, trusted_min_generation: int,
    trusted_snapshot_sha256: str,
) -> WitnessVerification:
    """Verify HMAC and exact archive root against caller's trusted inputs.

    `trusted_min_generation` and `trusted_snapshot_sha256` MUST come from
    outside the journal/archive trust domain. If caller supplies stale or
    attacker-controlled values this offers no rollback protection.
    """
    _key(secret)
    if not isinstance(expected_device_id, str) or not expected_device_id:
        raise ValueError("expected_device_id must be a nonempty string")
    if type(trusted_min_generation) is not int or trusted_min_generation < 1:
        raise ValueError("trusted_min_generation must be a positive integer")
    if not _hex_sha(trusted_snapshot_sha256):
        raise ValueError("trusted_snapshot_sha256 must be a lowercase SHA256 digest")
    body = _validate_receipt(receipt)
    if not hmac.compare_digest(receipt["hmac_sha256"], _mac(body, secret)):
        raise InvalidSnapshot("checkpoint witness authentication failed")
    archive = inspect_checkpoint_archive(archive_path)
    if any(body[k] != v for k, v in _receipt_fields(archive).items()):
        raise InvalidSnapshot("checkpoint witness does not match complete archive")
    if body["device_id"] != expected_device_id:
        raise InvalidSnapshot("checkpoint witness identifies different device")
    if body["source_snapshot_sha256"] != trusted_snapshot_sha256:
        raise InvalidSnapshot("checkpoint witness disagrees with supplied trusted root")
    return WitnessVerification(body["witness_id"], body["generation"],
                               body["source_snapshot_sha256"],
                               body["generation"] >= trusted_min_generation)


def load_checkpoint_receipt(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        receipt = json.load(handle)
    _validate_receipt(receipt)
    return receipt
