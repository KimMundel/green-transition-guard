"""Reference implementation of simulated power-state safety decisions.

Scope: accepted transitions are simulated state changes. No physical
actuation, authentication, redundancy, or trusted clock implementation.
"""
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .model import Decision, Policy, Reason, positive_int
from .storage import InvalidSnapshot, SnapshotStore


class GuardError(RuntimeError):
    pass


def _validate_payload(p: dict[str, Any]) -> Policy:
    required = {"schema", "device_id", "policy", "initial_state", "initial_entered_ms", "state", "entered_ms", "last_checked_ms", "revision", "events", "noops"}
    if set(p) != required or p.get("schema") != 1:
        raise InvalidSnapshot("unknown schema or fields")
    try:
        policy = Policy.from_dict(p["policy"])
        if not isinstance(p["device_id"], str) or not p["device_id"]:
            raise ValueError("missing device id")
        if p["initial_state"] not in policy.states or p["state"] not in policy.states:
            raise ValueError("unknown state")
        initial = positive_int(p["initial_entered_ms"], "initial_entered_ms")
        entered = positive_int(p["entered_ms"], "entered_ms")
        checked = positive_int(p["last_checked_ms"], "last_checked_ms")
        revision = positive_int(p["revision"], "revision")
        events = p["events"]
        if not isinstance(events, list) or len(events) != revision:
            raise ValueError("event count does not match revision")
        cur, cur_ts, prev_ts = p["initial_state"], initial, initial
        request_ids = set()
        for seq, e in enumerate(events, start=1):
            if not isinstance(e, dict) or set(e) != {"seq", "id", "request_id", "from", "to", "at_ms"}:
                raise ValueError("event fields")
            ts = positive_int(e["at_ms"], "at_ms")
            if type(e["seq"]) is not int or e["seq"] != seq or e["id"] != f"{p['device_id']}:{seq}":
                raise ValueError("event sequence")
            if not isinstance(e["request_id"], str) or not e["request_id"] or e["request_id"] in request_ids:
                raise ValueError("event request id")
            request_ids.add(e["request_id"])
            if ts < prev_ts or e["from"] != cur or (e["from"], e["to"]) not in policy.edges:
                raise ValueError("invalid event history")
            prev_ts, cur, cur_ts = ts, e["to"], ts
        if cur != p["state"] or cur_ts != entered or checked < prev_ts:
            raise ValueError("inconsistent snapshot state")
        noops = p["noops"]
        if not isinstance(noops, list):
            raise ValueError("invalid noop log")
        for entry in noops:
            if not isinstance(entry, dict) or set(entry) != {"request_id", "target", "at_ms", "revision"}:
                raise ValueError("noop fields")
            rid = entry["request_id"]
            if not isinstance(rid, str) or not rid or rid in request_ids:
                raise ValueError("duplicate noop request id")
            request_ids.add(rid)
            r = positive_int(entry["revision"], "noop revision")
            t = positive_int(entry["at_ms"], "noop timestamp")
            if r > revision or t < initial or t > checked:
                raise ValueError("invalid noop revision or time")
            state_at_revision = p["initial_state"] if r == 0 else events[r - 1]["to"]
            low = initial if r == 0 else events[r - 1]["at_ms"]
            high = checked if r == revision else events[r]["at_ms"]
            if entry["target"] != state_at_revision or not (low <= t <= high):
                raise ValueError("inconsistent noop history")
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidSnapshot("invalid snapshot contents; fail closed") from exc
    return policy


class TransitionGuard:
    def __init__(self, store: SnapshotStore):
        self.store = store

    @classmethod
    def initialize(
        cls,
        path: str | Path,
        *,
        device_id: str,
        policy: Policy,
        initial_state: str,
        entered_at_ms: int,
    ) -> "TransitionGuard":
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("device_id must be a nonempty string")
        if initial_state not in policy.states:
            raise ValueError("initial state must be declared in policy")
        positive_int(entered_at_ms, "entered_at_ms")
        store = SnapshotStore(path)
        payload: dict[str, Any] = {
            "schema": 1,
            "device_id": device_id,
            "policy": policy.to_dict(),
            "initial_state": initial_state,
            "initial_entered_ms": entered_at_ms,
            "state": initial_state,
            "entered_ms": entered_at_ms,
            "last_checked_ms": entered_at_ms,
            "revision": 0,
            "events": [],
            "noops": [],
        }
        with store.lock():
            store.create(payload)
        return cls(store)

    @classmethod
    def open(cls, path: str | Path) -> "TransitionGuard":
        store = SnapshotStore(path)
        with store.lock():
            _validate_payload(store.read())
        return cls(store)

    def status(self) -> dict[str, Any]:
        with self.store.lock():
            payload = self.store.read()
            _validate_payload(payload)
            return {
                "device_id": payload["device_id"],
                "state": payload["state"],
                "entered_ms": payload["entered_ms"],
                "last_checked_ms": payload["last_checked_ms"],
                "revision": payload["revision"],
                "transitions": len(payload["events"]),
                "noops": len(payload["noops"]),
                "policy": payload["policy"],
            }

    def history(self) -> tuple[Mapping[str, Any], ...]:
        with self.store.lock():
            payload = self.store.read()
            _validate_payload(payload)
            return tuple(dict(e) for e in payload["events"])

    def request(
        self,
        *,
        target: str,
        request_id: str,
        at_ms: int,
        expected_revision: int | None = None,
    ) -> Decision:
        """Attempt a simulated transition; persist each time observation.

        For a real actuator, accepting a request is only a reservation;
        use a separate durable actuation/reconciliation protocol.
        """
        if not isinstance(target, str):
            raise ValueError("target must be a string")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ValueError("request_id must contain 1..256 characters")
        positive_int(at_ms, "at_ms")
        if expected_revision is not None:
            positive_int(expected_revision, "expected_revision")
        with self.store.lock():
            p = self.store.read()
            policy = _validate_payload(p)
            current = p["state"]
            revision = p["revision"]
            if at_ms < p["last_checked_ms"]:
                return Decision(False, Reason.CLOCK_REGRESSION, current, revision)
            p["last_checked_ms"] = at_ms
            def denied(reason: Reason, retry_at_ms: int | None = None) -> Decision:
                self.store.save(p)
                return Decision(False, reason, current, revision, retry_at_ms)

            for event in p["events"]:
                if event["request_id"] == request_id:
                    if target != event["to"]:
                        return denied(Reason.REQUEST_ID_COLLISION)
                    self.store.save(p)
                    return Decision(True, Reason.REPLAY, current, revision, event_id=event["id"])

            for noop in p["noops"]:
                if noop["request_id"] == request_id:
                    if target != noop["target"]:
                        return denied(Reason.REQUEST_ID_COLLISION)
                    self.store.save(p)
                    return Decision(True, Reason.REPLAY, current, revision)

            if expected_revision is not None and expected_revision != revision:
                return denied(Reason.STALE_REVISION)
            if target not in policy.states:
                return denied(Reason.UNKNOWN_STATE)
            if target == current:
                p["noops"].append({
                    "request_id": request_id, "target": target,
                    "at_ms": at_ms, "revision": revision,
                })
                self.store.save(p)
                return Decision(True, Reason.NO_CHANGE, current, revision)
            if (current, target) not in policy.edges:
                return denied(Reason.UNSUPPORTED_TRANSITION)

            retry: list[tuple[Reason, int | None]] = []
            dwell_until = p["entered_ms"] + policy.min_dwell_ms[current]
            if at_ms < dwell_until:
                retry.append((Reason.MIN_DWELL, dwell_until))
            if p["events"]:
                interval_until = p["events"][-1]["at_ms"] + policy.min_interval_ms
                if at_ms < interval_until:
                    retry.append((Reason.MIN_INTERVAL, interval_until))

            # Events in (at_ms-window_ms, at_ms] are active; at the exact
            # expiration boundary, the event leaves the window.
            active = [e["at_ms"] for e in p["events"] if e["at_ms"] > at_ms - policy.window_ms]
            if len(active) >= policy.max_transitions:
                if policy.max_transitions == 0:
                    retry.append((Reason.RATE_LIMIT, None))
                else:
                    release = active[len(active) - policy.max_transitions] + policy.window_ms
                    retry.append((Reason.RATE_LIMIT, release))
            if retry:
                # Fixed reason precedence; provide time when *all* temporal
                # constraints would expire at the current observed history.
                retry_at = None if any(t is None for _, t in retry) else max(t for _, t in retry if t is not None)
                return denied(retry[0][0], retry_at)

            seq = revision + 1
            event_id = f"{p['device_id']}:{seq}"
            p["events"].append({
                "seq": seq, "id": event_id, "request_id": request_id,
                "from": current, "to": target, "at_ms": at_ms,
            })
            p["state"] = target
            p["entered_ms"] = at_ms
            p["revision"] = seq
            self.store.save(p)
            return Decision(True, Reason.ACCEPTED, target, seq, event_id=event_id)
