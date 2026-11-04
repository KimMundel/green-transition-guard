"""Crash-injected, device-side transition experiment; never actuates real hardware.

The simulated actuator has its own durable event ledger. The controller
journal and actuator ledger are deliberately separate: there is no atomic
commit across the two. Operation IDs and independently observed counters
let reconciliation prove exactly one simulated edge, or fail closed.

A real device must provide equivalent *authenticated* evidence, exclusive
actuator authority, and trustworthy time before this design can be used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import Policy, positive_int
from .storage import InvalidSnapshot, SnapshotStore


class InjectedCrash(RuntimeError):
    """A deterministic crash at a persistence / hardware boundary."""


class ActuatorMismatch(RuntimeError):
    """The simulated hardware rejected an operation without side effects."""


@dataclass(frozen=True)
class HardwareDecision:
    allowed: bool
    reason: str
    phase: str
    oper: str
    admin: str
    revision: int
    retry_at_ms: int | None = None


def _nonempty(v: Any, label: str) -> str:
    if not isinstance(v, str) or not v or len(v) > 256:
        raise ValueError(f"{label} must contain 1..256 characters")
    return v


def _validate_actuator(p: dict[str, Any]) -> None:
    try:
        if set(p) != {"schema", "energy_object_id", "state", "counter", "events"} or p["schema"] != 1:
            raise ValueError("actuator schema")
        _nonempty(p["energy_object_id"], "energy_object_id")
        _nonempty(p["state"], "state")
        positive_int(p["counter"], "counter")
        if type(p["events"]) is not list or len(p["events"]) != p["counter"]:
            raise ValueError("actuator event count")
        seen = set()
        previous = None
        for index, e in enumerate(p["events"], 1):
            if not isinstance(e, dict) or set(e) != {"counter", "id", "from", "to", "kind"}:
                raise ValueError("actuator event fields")
            if type(e["counter"]) is not int or e["counter"] != index:
                raise ValueError("actuator counter")
            _nonempty(e["id"], "actuator event id")
            if e["id"] in seen or e["kind"] not in ("managed", "external"):
                raise ValueError("actuator event ID/kind")
            seen.add(e["id"])
            if not isinstance(e["from"], str) or not isinstance(e["to"], str) or e["from"] == e["to"]:
                raise ValueError("actuator edge")
            if previous is not None and e["from"] != previous:
                raise ValueError("broken actuator history")
            previous = e["to"]
        if previous is not None and p["state"] != previous:
            raise ValueError("actuator state mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidSnapshot("invalid simulated actuator journal; fail closed") from exc


class SimulatedActuator:
    """Durable simulated hardware with an independent physical-edge counter."""

    def __init__(self, path: str | Path):
        self.store = SnapshotStore(path)

    @classmethod
    def initialize(cls, path: str | Path, *, energy_object_id: str, initial_state: str) -> "SimulatedActuator":
        _nonempty(energy_object_id, "energy_object_id")
        _nonempty(initial_state, "initial_state")
        a = cls(path)
        with a.store.lock():
            a.store.create({"schema": 1, "energy_object_id": energy_object_id, "state": initial_state,
                            "counter": 0, "events": []})
        return a

    def snapshot(self) -> dict[str, Any]:
        with self.store.lock():
            p = self.store.read()
            _validate_actuator(p)
            return {"energy_object_id": p["energy_object_id"], "state": p["state"],
                    "counter": p["counter"], "events": [dict(e) for e in p["events"]]}

    def _edge(self, *, op_id: str, target: str, kind: str,
              expected_state: str | None = None, expected_counter: int | None = None) -> dict[str, Any]:
        _nonempty(op_id, "op_id")
        _nonempty(target, "target")
        with self.store.lock():
            p = self.store.read()
            _validate_actuator(p)
            duplicates = [e for e in p["events"] if e["id"] == op_id]
            if duplicates:
                e = duplicates[0]
                if e["to"] != target or e["kind"] != kind:
                    raise ActuatorMismatch("operation ID collision")
                return dict(e)  # simulated actuator deduplicates even if caller retries
            if expected_counter is not None and p["counter"] != expected_counter:
                raise ActuatorMismatch("physical counter changed")
            if expected_state is not None and p["state"] != expected_state:
                raise ActuatorMismatch("physical state changed")
            if p["state"] == target:
                raise ActuatorMismatch("no physical edge")
            e = {"counter": p["counter"] + 1, "id": op_id, "from": p["state"],
                 "to": target, "kind": kind}
            p["events"].append(e)
            p["state"] = target
            p["counter"] += 1
            self.store.save(p)
            return dict(e)

    def apply(self, *, op_id: str, target: str, expected_state: str, expected_counter: int) -> dict[str, Any]:
        """Called by the experimental controller only after a durable dispatch mark."""
        return self._edge(op_id=op_id, target=target, kind="managed",
                          expected_state=expected_state, expected_counter=expected_counter)

    def external_edge(self, *, event_id: str, target: str) -> dict[str, Any]:
        """Models firmware/manual changes outside the controller."""
        return self._edge(op_id=event_id, target=target, kind="external")


def _validate_controller(p: dict[str, Any]) -> Policy:
    try:
        required = {"schema", "energy_object_id", "policy", "initial_state", "initial_at_ms",
                    "oper", "oper_at_ms", "last_checked_ms", "counter", "revision", "events",
                    "noops", "pending", "quarantine"}
        if set(p) != required or p["schema"] != 2:
            raise ValueError("controller schema")
        obj = _nonempty(p["energy_object_id"], "energy_object_id")
        policy = Policy.from_dict(p["policy"])
        if p["initial_state"] not in policy.states or p["oper"] not in policy.states:
            raise ValueError("unknown operational state")
        origin = positive_int(p["initial_at_ms"], "initial timestamp")
        oper_at = positive_int(p["oper_at_ms"], "oper timestamp")
        checked = positive_int(p["last_checked_ms"], "last checked")
        counter = positive_int(p["counter"], "hardware counter")
        revision = positive_int(p["revision"], "revision")
        if not (origin <= oper_at <= checked):
            raise ValueError("time order")
        if type(p["events"]) is not list or len(p["events"]) != revision or revision != counter:
            raise ValueError("event/revision count")
        current, last_at, ids = p["initial_state"], origin, set()
        for i, e in enumerate(p["events"], 1):
            if not isinstance(e, dict) or set(e) != {"seq", "op_id", "from", "to", "at_ms", "dispatch_ms", "counter"}:
                raise ValueError("event fields")
            if type(e["seq"]) is not int or e["seq"] != i or type(e["counter"]) is not int or e["counter"] != i:
                raise ValueError("event sequence")
            rid = _nonempty(e["op_id"], "op_id")
            if rid in ids or e["from"] != current or (current, e["to"]) not in policy.edges:
                raise ValueError("event sequence/edge")
            ids.add(rid)
            dispatch = positive_int(e["dispatch_ms"], "dispatch timestamp")
            when = positive_int(e["at_ms"], "verification timestamp")
            if dispatch < last_at or when < dispatch or when < last_at:
                raise ValueError("event time order")
            current, last_at = e["to"], when
        if current != p["oper"] or last_at != oper_at:
            raise ValueError("confirmed operational state")
        if type(p["noops"]) is not list:
            raise ValueError("noop log")
        for e in p["noops"]:
            if not isinstance(e, dict) or set(e) != {"op_id", "target"}:
                raise ValueError("noop fields")
            rid = _nonempty(e["op_id"], "noop ID")
            if rid in ids or e["target"] not in policy.states:
                raise ValueError("noop ID")
            ids.add(rid)
        pending = p["pending"]
        if pending is not None:
            if not isinstance(pending, dict) or set(pending) != {"op_id", "target", "from", "prepared_at_ms",
                                                                    "dispatch_at_ms", "expected_counter", "phase"}:
                raise ValueError("pending fields")
            rid = _nonempty(pending["op_id"], "pending ID")
            if rid in ids or pending["from"] != current or (current, pending["target"]) not in policy.edges:
                raise ValueError("pending edge/ID")
            if type(pending["expected_counter"]) is not int or pending["expected_counter"] != counter:
                raise ValueError("pending counter")
            prepared = positive_int(pending["prepared_at_ms"], "prepared timestamp")
            if prepared < oper_at or prepared > checked:
                raise ValueError("prepared time")
            phase = pending["phase"]
            if phase not in ("prepared", "may-have-dispatched", "acknowledged", "unresolved"):
                raise ValueError("pending phase")
            when = pending["dispatch_at_ms"]
            if phase == "prepared" and when is not None:
                raise ValueError("prepared may not contain dispatch timestamp")
            if phase != "prepared" and (type(when) is not int or when < prepared or when > checked):
                raise ValueError("dispatch timestamp")
        if p["quarantine"] is not None and p["quarantine"] not in ("physical-divergence",):
            raise ValueError("quarantine reason")
        if not isinstance(obj, str):
            raise ValueError("energy object")
        return policy
    except (TypeError, ValueError, KeyError) as exc:
        raise InvalidSnapshot("invalid experimental controller journal; fail closed") from exc


class HardwareTransitionExperiment:
    """A single authoritative simulated controller for one GREEN Energy Object."""

    def __init__(self, path: str | Path, actuator: SimulatedActuator):
        self.store = SnapshotStore(path)
        self.actuator = actuator

    @classmethod
    def initialize(cls, path: str | Path, *, actuator: SimulatedActuator, policy: Policy,
                   energy_object_id: str, entered_at_ms: int) -> "HardwareTransitionExperiment":
        _nonempty(energy_object_id, "energy_object_id")
        positive_int(entered_at_ms, "entered_at_ms")
        hw = actuator.snapshot()
        if hw["energy_object_id"] != energy_object_id or hw["counter"] != 0 or hw["events"]:
            raise ValueError("fresh hardware journal required for this isolated experiment")
        if hw["state"] not in policy.states:
            raise ValueError("hardware state absent from policy")
        experiment = cls(path, actuator)
        with experiment.store.lock():
            experiment.store.create({"schema": 2, "energy_object_id": energy_object_id,
                                     "policy": policy.to_dict(), "initial_state": hw["state"],
                                     "initial_at_ms": entered_at_ms, "oper": hw["state"],
                                     "oper_at_ms": entered_at_ms, "last_checked_ms": entered_at_ms,
                                     "counter": 0, "revision": 0, "events": [], "noops": [],
                                     "pending": None, "quarantine": None})
        return experiment

    @classmethod
    def open(cls, path: str | Path, *, actuator: SimulatedActuator) -> "HardwareTransitionExperiment":
        e = cls(path, actuator)
        with e.store.lock():
            _validate_controller(e.store.read())
        return e

    @staticmethod
    def _decision(p: dict[str, Any], allowed: bool, reason: str, retry: int | None = None) -> HardwareDecision:
        pending = p["pending"]
        return HardwareDecision(allowed, reason, pending["phase"] if pending else "idle",
                                p["oper"], pending["target"] if pending else p["oper"],
                                p["revision"], retry)

    @staticmethod
    def _policy_reason(p: dict[str, Any], policy: Policy, target: str, at_ms: int) -> tuple[str | None, int | None]:
        if target not in policy.states:
            return "unknown-state", None
        if (p["oper"], target) not in policy.edges:
            return "unsupported-transition", None
        bounds: list[tuple[str, int | None]] = []
        dwell = p["oper_at_ms"] + policy.min_dwell_ms[p["oper"]]
        if at_ms < dwell:
            bounds.append(("min-dwell", dwell))
        if p["events"]:
            interval = p["events"][-1]["at_ms"] + policy.min_interval_ms
            if at_ms < interval:
                bounds.append(("min-interval", interval))
        active = [e["at_ms"] for e in p["events"] if e["at_ms"] > at_ms - policy.window_ms]
        if len(active) >= policy.max_transitions:
            release = None if policy.max_transitions == 0 else active[-policy.max_transitions] + policy.window_ms
            bounds.append(("rate-limit", release))
        if not bounds:
            return None, None
        when = None if any(t is None for _, t in bounds) else max(t for _, t in bounds if t is not None)
        return bounds[0][0], when

    def status(self) -> dict[str, Any]:
        with self.store.lock():
            p = self.store.read()
            _validate_controller(p)
            return {"energy_object_id": p["energy_object_id"], "admin": p["pending"]["target"] if p["pending"] else p["oper"],
                    "oper": p["oper"], "pending": dict(p["pending"]) if p["pending"] else None,
                    "counter": p["counter"], "revision": p["revision"],
                    "quarantine": p["quarantine"], "events": [dict(e) for e in p["events"]]}

    def prepare(self, *, op_id: str, target: str, at_ms: int, expected_revision: int | None = None) -> HardwareDecision:
        _nonempty(op_id, "op_id")
        _nonempty(target, "target")
        positive_int(at_ms, "at_ms")
        if expected_revision is not None:
            positive_int(expected_revision, "expected_revision")
        with self.store.lock():
            p = self.store.read()
            policy = _validate_controller(p)
            if at_ms < p["last_checked_ms"]:
                return self._decision(p, False, "clock-regression")
            p["last_checked_ms"] = at_ms
            def finish(allowed: bool, reason: str, retry: int | None = None) -> HardwareDecision:
                self.store.save(p)
                return self._decision(p, allowed, reason, retry)
            if p["quarantine"] is not None:
                return finish(False, "physical-divergence")
            for entry in p["events"] + p["noops"]:
                if entry["op_id"] == op_id:
                    return finish(entry.get("to", entry.get("target")) == target,
                                  "replay" if entry.get("to", entry.get("target")) == target else "op-id-collision")
            if p["pending"] is not None:
                pending = p["pending"]
                if pending["op_id"] == op_id:
                    return finish(pending["target"] == target,
                                  "pending-replay" if pending["target"] == target else "op-id-collision")
                return finish(False, "busy")
            if expected_revision is not None and expected_revision != p["revision"]:
                return finish(False, "stale-revision")
            hardware = self.actuator.snapshot()
            if (hardware["energy_object_id"] != p["energy_object_id"] or
                    hardware["counter"] != p["counter"] or hardware["state"] != p["oper"]):
                p["quarantine"] = "physical-divergence"
                return finish(False, "physical-divergence")
            if target == p["oper"]:
                p["noops"].append({"op_id": op_id, "target": target})
                return finish(True, "no-change")
            reason, retry = self._policy_reason(p, policy, target, at_ms)
            if reason is not None:
                return finish(False, reason, retry)
            p["pending"] = {"op_id": op_id, "target": target, "from": p["oper"],
                            "prepared_at_ms": at_ms, "dispatch_at_ms": None,
                            "expected_counter": p["counter"], "phase": "prepared"}
            return finish(True, "prepared")

    def abort_prepared(self, *, op_id: str) -> HardwareDecision:
        """Safe in this lab only because dispatch requires a prior durable phase change."""
        _nonempty(op_id, "op_id")
        with self.store.lock():
            p = self.store.read()
            _validate_controller(p)
            pending = p["pending"]
            if pending is None or pending["op_id"] != op_id or pending["phase"] != "prepared":
                return self._decision(p, False, "abort-unavailable")
            p["pending"] = None
            self.store.save(p)
            return self._decision(p, True, "aborted-before-dispatch")

    def dispatch(self, *, op_id: str, at_ms: int, crash_at: str | None = None) -> HardwareDecision:
        """Mark dispatch possibility durably *before* the simulated physical side effect.

        Valid fault points: before_mark, after_mark, after_effect, after_ack.
        A restart must never automatically retransmit a MAY_HAVE_DISPATCHED op.
        """
        _nonempty(op_id, "op_id")
        positive_int(at_ms, "at_ms")
        if crash_at not in (None, "before_mark", "after_mark", "after_effect", "after_ack"):
            raise ValueError("unknown fault point")
        with self.store.lock():
            p = self.store.read()
            policy = _validate_controller(p)
            pending = p["pending"]
            if pending is None or pending["op_id"] != op_id or pending["phase"] != "prepared":
                return self._decision(p, False, "dispatch-unavailable")
            if p["quarantine"] is not None:
                return self._decision(p, False, "physical-divergence")
            if at_ms < p["last_checked_ms"]:
                return self._decision(p, False, "clock-regression")
            p["last_checked_ms"] = at_ms
            reason, retry = self._policy_reason(p, policy, pending["target"], at_ms)
            if reason is not None:
                self.store.save(p)
                return self._decision(p, False, reason, retry)
            if crash_at == "before_mark":
                self.store.save(p)
                raise InjectedCrash("before durable dispatch possibility")
            pending["phase"] = "may-have-dispatched"
            pending["dispatch_at_ms"] = at_ms
            self.store.save(p)
            if crash_at == "after_mark":
                raise InjectedCrash("after durable dispatch mark, before hardware call")
            try:
                self.actuator.apply(op_id=op_id, target=pending["target"],
                                    expected_state=pending["from"], expected_counter=pending["expected_counter"])
            except ActuatorMismatch:
                pending["phase"] = "unresolved"
                self.store.save(p)
                return self._decision(p, False, "hardware-mismatch")
            if crash_at == "after_effect":
                raise InjectedCrash("after simulated physical effect, before acknowledgement")
            pending["phase"] = "acknowledged"
            self.store.save(p)
            if crash_at == "after_ack":
                raise InjectedCrash("after acknowledgement, before verification")
            return self._decision(p, True, "acknowledged")

    def timeout(self, *, op_id: str) -> HardwareDecision:
        """Timeout changes bookkeeping only; it cannot prove no physical effect."""
        _nonempty(op_id, "op_id")
        with self.store.lock():
            p = self.store.read()
            _validate_controller(p)
            pending = p["pending"]
            if pending is None or pending["op_id"] != op_id or pending["phase"] == "prepared":
                return self._decision(p, False, "timeout-unavailable")
            pending["phase"] = "unresolved"
            self.store.save(p)
            return self._decision(p, False, "unresolved")

    def reconcile(self, *, at_ms: int) -> HardwareDecision:
        """Require *one* durable actuator event, matching ID, target and counter.

        Verification time is used as a conservative latest-event timestamp:
        the event may have happened earlier. A real system must prove the
        clock bound and observe every relevant physical edge.
        """
        positive_int(at_ms, "at_ms")
        with self.store.lock():
            p = self.store.read()
            _validate_controller(p)
            if at_ms < p["last_checked_ms"]:
                return self._decision(p, False, "clock-regression")
            p["last_checked_ms"] = at_ms
            pending = p["pending"]
            if pending is None:
                self.store.save(p)
                return self._decision(p, False, "nothing-to-reconcile")
            if pending["phase"] == "prepared":
                self.store.save(p)
                return self._decision(p, False, "prepared-only")
            hardware = self.actuator.snapshot()
            expected_counter = p["counter"] + 1
            matching = (hardware["energy_object_id"] == p["energy_object_id"] and
                        hardware["counter"] == expected_counter and
                        hardware["state"] == pending["target"] and
                        len(hardware["events"]) == expected_counter)
            if matching:
                e = hardware["events"][-1]
                matching = (e["counter"] == expected_counter and e["id"] == pending["op_id"] and
                            e["kind"] == "managed" and e["from"] == pending["from"] and
                            e["to"] == pending["target"])
            if matching:
                p["revision"] += 1
                p["counter"] = expected_counter
                p["oper"] = pending["target"]
                p["oper_at_ms"] = at_ms
                p["events"].append({"seq": p["revision"], "op_id": pending["op_id"],
                                    "from": pending["from"], "to": pending["target"],
                                    "dispatch_ms": pending["dispatch_at_ms"],
                                    "at_ms": at_ms, "counter": expected_counter})
                p["pending"] = None
                self.store.save(p)
                return self._decision(p, True, "verified")
            pending["phase"] = "unresolved"
            self.store.save(p)
            return self._decision(p, False, "unresolved")
