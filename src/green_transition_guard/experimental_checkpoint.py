"""Read-only checkpoint preflight and exact replay index for a validated journal.

The complete journal remains authoritative. A digest is an integrity hint,
not an authenticated root or a substitute for preserved replay identities.
No durable checkpoint or pruning is implemented here.
"""

from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

from .model import Policy
from .storage import canonical_bytes


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ReplayRecord:
    kind: str
    expected: str | int
    event_id: str | None = None


@dataclass(frozen=True)
class ReplayIndex:
    """Exact, detached lookup for IDs in the COMPLETE validated journal.

    This unbounded in-memory index is a verification tool, not a durable
    tombstone solution. A missing ID is only 'unknown' while the complete
    validated source is available; no caller may use this to prune IDs.
    """

    _records: Mapping[str, ReplayRecord] = field(repr=False)
    digest: str

    @property
    def count(self) -> int:
        return len(self._records)

    def probe_request(self, request_id: str, target: str) -> tuple[str, str | None]:
        """Return (unknown|replay|collision, original event ID if any)."""
        record = self._records.get(request_id)
        if record is None:
            return "unknown", None
        if record.kind in ("transition", "noop") and record.expected == target:
            return "replay", record.event_id
        return "collision", None

    def probe_policy_update(self, update_id: str, policy: Policy) -> str:
        record = self._records.get(update_id)
        if record is None:
            return "unknown"
        if record.kind == "policy-update" and record.expected == canonical_bytes(policy.to_dict()).decode("ascii"):
            return "replay"
        return "collision"

    def probe_operation_budget(self, install_id: str, max_total_ids: int) -> str:
        record = self._records.get(install_id)
        if record is None:
            return "unknown"
        if record.kind == "operation-budget" and type(max_total_ids) is int and record.expected == max_total_ids:
            return "replay"
        return "collision"

    def probe_window_seal(self, install_id: str, max_window_ms: int) -> str:
        record = self._records.get(install_id)
        if record is None:
            return "unknown"
        if record.kind == "window-seal" and type(max_window_ms) is int and record.expected == max_window_ms:
            return "replay"
        return "collision"


def build_replay_index(payload: Mapping[str, Any]) -> ReplayIndex:
    """Build an exact replay oracle from a previously validated snapshot."""
    records: dict[str, ReplayRecord] = {}

    def add(request_id: str, record: ReplayRecord) -> None:
        if not isinstance(request_id, str) or not request_id or request_id in records:
            raise ValueError("invalid or duplicate replay identity")
        records[request_id] = record

    for event in payload["events"]:
        add(event["request_id"], ReplayRecord("transition", event["to"], event["id"]))
    for noop in payload["noops"]:
        add(noop["request_id"], ReplayRecord("noop", noop["target"]))
    if payload["schema"] >= 2:
        for update in payload["policy_updates"]:
            add(update["id"], ReplayRecord("policy-update", canonical_bytes(update["policy"]).decode("ascii")))
    if payload["schema"] >= 3:
        seal = payload["window_ceiling"]
        add(seal["id"], ReplayRecord("window-seal", seal["max_window_ms"]))

    if payload["schema"] == 4:
        budget = payload["operation_budget"]
        add(budget["id"], ReplayRecord("operation-budget", budget["max_total_ids"]))

    serializable = [
        {"id": key, "kind": rec.kind, "expected": rec.expected, "event_id": rec.event_id}
        for key, rec in sorted(records.items())
    ]
    return ReplayIndex(MappingProxyType(records), _digest(serializable))


@dataclass(frozen=True)
class CheckpointPreflight:
    """Snapshot-bound preview; the caller must treat it as stale after writes."""

    _manifest: Mapping[str, Any] = field(repr=False)
    replay: ReplayIndex = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._manifest))


def build_checkpoint_preflight(payload: Mapping[str, Any]) -> CheckpointPreflight:
    """Create a complete-history candidate from an already validated payload."""
    replay = build_replay_index(payload)
    events = payload["events"]
    updates = payload["policy_updates"] if payload["schema"] >= 2 else []
    initial_policy = payload["initial_policy"] if payload["schema"] >= 2 else payload["policy"]
    seal = payload["window_ceiling"] if payload["schema"] >= 3 else None
    as_of = payload["last_checked_ms"]
    # This prefix is quota-expired under a SEALED future-window ceiling only.
    # Replay, interval, policy-epoch and crash-recovery obligations still block
    # all deletion, including the event at the exact left boundary.
    times = [event["at_ms"] for event in events]
    expired = bisect_right(times, as_of - seal["max_window_ms"]) if seal else 0
    manifest = {
        "format": "experimental-checkpoint-preflight-1",
        "source_snapshot_sha256": _digest(payload),
        "device_id": payload["device_id"],
        "schema": payload["schema"],
        "revision": payload["revision"],
        "policy_revision": len(updates),
        "as_of_ms": as_of,
        "state": payload["state"],
        "entered_ms": payload["entered_ms"],
        "last_transition_ms": times[-1] if times else None,
        "sealed_window_ceiling_ms": seal["max_window_ms"] if seal else None,
        "operation_budget_max": (
            payload["operation_budget"]["max_total_ids"] if payload["schema"] == 4 else None
        ),
        "quota_expired_prefix_events": expired,
        "quota_retained_suffix_events": len(events) - expired,
        "event_prefix_sha256": _digest(events[:expired]),
        "event_suffix_sha256": _digest(events[expired:]),
        "policy_chain_sha256": _digest({"initial_policy": initial_policy, "updates": updates, "seal": seal}),
        "replay_identity_count": replay.count,
        "replay_index_sha256": replay.digest,
        "journal_compaction_enabled": False,
        "unresolved_dependencies": [
            "durable exact replay identities or explicitly conservative rejection",
            "verifiable state and policy epoch checkpoint after prefix removal",
            "bounded operation volume with fail-closed saturation",
            "crash-consistent archive installation and rollback resistance",
            "real clock and hardware validation",
        ],
    }
    return CheckpointPreflight(MappingProxyType(manifest), replay)
