"""Read-only ancestry proof between complete, validated guard journals.

This compares recorded identities and policy epochs across *whole* journals.
It cannot establish which file is trusted, current, or power-loss durable.
No journal is activated, altered, recovered, or compacted here.
"""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Mapping

from .storage import canonical_bytes


def _hash(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_bytes(payload)).hexdigest()


def _initial_policy(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return snapshot["initial_policy"] if snapshot["schema"] >= 2 else snapshot["policy"]


def _entries(snapshot: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    return snapshot[name] if name != "policy_updates" or snapshot["schema"] >= 2 else []


def _is_ancestor(older: Mapping[str, Any], newer: Mapping[str, Any]) -> bool:
    """Conservatively test whether `newer` could come from append-only writes.

    Existing operations, seal IDs, and initialization parameters are immutable.
    Additional operations must appear after the older observed clock, even
    when concurrent event/policy operations share the exact millisecond.
    """
    if older["schema"] > newer["schema"] or older["last_checked_ms"] > newer["last_checked_ms"]:
        return False
    if any(older[key] != newer[key] for key in (
        "device_id", "initial_state", "initial_entered_ms",
    )) or _initial_policy(older) != _initial_policy(newer):
        return False
    old_clock = older["last_checked_ms"]
    for name in ("events", "noops", "policy_updates"):
        before, after = _entries(older, name), _entries(newer, name)
        if len(before) > len(after) or before != after[:len(before)]:
            return False
        if any(item["at_ms"] < old_clock for item in after[len(before):]):
            return False
    if older["schema"] >= 3 and older["window_ceiling"] != newer["window_ceiling"]:
        return False
    if older["schema"] < 3 <= newer["schema"] and newer["window_ceiling"]["at_ms"] < old_clock:
        return False
    if older["schema"] == 4 and older["operation_budget"] != newer["operation_budget"]:
        return False
    if older["schema"] < 4 <= newer["schema"] and newer["operation_budget"]["at_ms"] < old_clock:
        return False
    return True


@dataclass(frozen=True)
class RecoveryLineage:
    """Detached, digest-only comparison for incident investigation."""

    relation: str
    _archive: Mapping[str, Any] = field(repr=False)
    _current: Mapping[str, Any] = field(repr=False)

    @property
    def possible_live_rollback(self) -> bool:
        return self.relation == "current_ancestor"

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "experimental-recovery-lineage-1",
            "relation": self.relation,
            "possible_live_rollback": self.possible_live_rollback,
            "archive_snapshot_sha256": _hash(self._archive),
            "current_snapshot_sha256": _hash(self._current),
            "archive_revision": self._archive["revision"],
            "current_revision": self._current["revision"],
            "archive_as_of_ms": self._archive["last_checked_ms"],
            "current_as_of_ms": self._current["last_checked_ms"],
            "archive_schema": self._archive["schema"],
            "current_schema": self._current["schema"],
            "lineage_proves_latest_generation": False,
            "authenticated_rollback_protection": False,
            "restoration_enabled": False,
            "journal_compaction_enabled": False,
        }


def compare_recovery_lineage(archived: dict[str, Any], current: dict[str, Any]) -> RecoveryLineage:
    """Revalidate inputs before comparing; refuse corrupt or partial history."""
    from .engine import _validate_payload

    _validate_payload(archived)
    _validate_payload(current)
    if archived["device_id"] != current["device_id"]:
        relation = "different_device"
    elif _hash(archived) == _hash(current):
        relation = "identical"
    elif _is_ancestor(archived, current):
        relation = "archive_ancestor"
    elif _is_ancestor(current, archived):
        relation = "current_ancestor"
    else:
        relation = "diverged"
    return RecoveryLineage(relation, archived, current)
