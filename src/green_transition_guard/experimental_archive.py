"""Experimental immutable, exact-replay checkpoint *archive candidate*.

A complete validated journal is preserved in a separate checksum-wrapped file,
installed by an atomic, no-replace hardlink on a single POSIX filesystem. The
live journal remains authoritative; this archive never authorizes compaction,
actuation, or recovery of a stale/rolled-back live journal.

This is in-process failure protection, NOT authenticated anti-rollback storage
or proof of durability after a machine power loss.
"""

import contextlib
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .experimental_checkpoint import ReplayIndex, build_checkpoint_preflight
from .storage import InvalidSnapshot, SnapshotStore, canonical_bytes, wrap

ARCHIVE_FORMAT = "experimental-checkpoint-archive-1"


def _source_hash(payload: dict[str, Any]) -> str:
    return sha256(canonical_bytes(payload)).hexdigest()


def make_archive_payload(source: dict[str, Any]) -> dict[str, Any]:
    """Create a complete-history candidate from a validated source journal."""
    preview = build_checkpoint_preflight(source)
    return {
        "format": ARCHIVE_FORMAT,
        "source_snapshot": source,
        "preflight_manifest": preview.to_dict(),
    }


def _validated_archive(payload: dict[str, Any]) -> ReplayIndex:
    """Verify independent archive consistency; never trust its manifest alone."""
    if not isinstance(payload, dict) or set(payload) != {
        "format", "source_snapshot", "preflight_manifest"
    } or payload["format"] != ARCHIVE_FORMAT:
        raise InvalidSnapshot("unsupported checkpoint archive format")
    source = payload["source_snapshot"]
    if not isinstance(source, dict):
        raise InvalidSnapshot("missing checkpoint archive source")

    # The same state/edge/epoch/snapshot validator used by the live guard.
    # Local import avoids a module cycle with TransitionGuard's archive APIs.
    from .engine import _validate_payload

    _validate_payload(source)
    preview = build_checkpoint_preflight(source)
    if payload["preflight_manifest"] != preview.to_dict():
        raise InvalidSnapshot("checkpoint archive manifest disagrees with source")
    return preview.replay


@dataclass(frozen=True)
class CheckpointArchiveView:
    """Verified archive metadata and an exact in-memory replay-ID oracle."""

    _archive: dict[str, Any] = field(repr=False)
    replay: ReplayIndex = field(repr=False)
    matches_current_journal: bool | None

    def to_dict(self) -> dict[str, Any]:
        m = self._archive["preflight_manifest"]
        return {
            "format": ARCHIVE_FORMAT,
            "source_snapshot_sha256": m["source_snapshot_sha256"],
            "archive_payload_sha256": _source_hash(self._archive),
            "source_schema": m["schema"],
            "source_revision": m["revision"],
            "source_policy_revision": m["policy_revision"],
            "replay_identity_count": m["replay_identity_count"],
            "replay_index_sha256": m["replay_index_sha256"],
            "complete_source_history_preserved": True,
            "matches_current_journal": self.matches_current_journal,
            "journal_compaction_enabled": False,
            "authenticated_rollback_protection": False,
        }


def verify_archive_payload(archive: dict[str, Any], current: dict[str, Any] | None = None) -> CheckpointArchiveView:
    """Standalone archive validity and explicit comparison with the live source."""
    replay = _validated_archive(archive)
    return CheckpointArchiveView(
        archive, replay,
        (archive["preflight_manifest"]["source_snapshot_sha256"] == _source_hash(current)
         if current is not None else None),
    )


def _atomic_create_archive(path: Path, payload: dict[str, Any]) -> None:
    """Publish a complete archive with an atomic, exclusive hardlink.

    Temporary file data are fsynced before publishing. The destination name
    cannot be replaced, including when it is a symlink. After link/unlink,
    the containing directory is fsynced. Errors after link may leave a valid
    visible archive with unproven power-loss durability. The caller must
    inspect it instead of blindly repeating the operation.
    """
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        with handle:
            json.dump(wrap(payload), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic create-only: unlike os.replace, link fails for existing files.
        os.link(name, path)
    finally:
        # On all error paths, the temporary name can safely be discarded.
        if os.path.exists(name):
            os.unlink(name)
    SnapshotStore(path)._sync_directory()


def archive_sibling_path(journal_path: Path, requested: str | Path) -> Path:
    """Require an explicit sibling file so the archive and journal share FS."""
    path = Path(requested)
    if not path.is_absolute():
        raise ValueError("checkpoint archive path must be absolute")
    if path.parent.resolve(strict=True) != journal_path.parent.resolve(strict=True):
        raise ValueError("checkpoint archive must be in journal directory")
    if path.name in {journal_path.name, journal_path.name + ".lock"} or path.name.endswith(".lock"):
        raise ValueError("checkpoint archive collides with journal or lock")
    return path


def read_checkpoint_archive(path: Path, current: dict[str, Any] | None = None) -> CheckpointArchiveView:
    """Verify the checksum-wrapped archive and re-derive all replay identities."""
    archive = SnapshotStore(path).read()
    return verify_archive_payload(archive, current)


def create_checkpoint_archive(path: Path, current: dict[str, Any]) -> CheckpointArchiveView:
    """Create exactly once. Existing/ambiguous archive state must be inspected."""
    candidate = make_archive_payload(current)
    _atomic_create_archive(path, candidate)
    return read_checkpoint_archive(path, current)


def inspect_checkpoint_archive(path: str | Path) -> CheckpointArchiveView:
    """Independently validate an archive when the original journal is unavailable.

    Without a trusted external checkpoint root, standalone validity cannot
    prove the newest generation or authorize restoring an old journal.
    """
    return read_checkpoint_archive(Path(path))
