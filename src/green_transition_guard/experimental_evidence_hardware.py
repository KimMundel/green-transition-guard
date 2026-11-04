"""Simulation-only physical transition guard using conservative time evidence.

This experiment integrates two independently researched mechanisms:
- a durable, independent simulated physical-edge ledger; and
- bounded clocks (with proof of elapsed time across clock epochs when possible).

No clock authentication, hardware attestation, real actuation or GREEN wire
protocol is provided. Callers MUST supply trustworthy clock intervals. A
reported completion time is used as the conservative latest event time.
The reference v0.1.2 integer-time simulator remains available unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .experimental_hardware import ActuatorMismatch, InjectedCrash, SimulatedActuator, _nonempty
from .experimental_time import (
    Bounds, InconsistentTimeEvidence, TimeEvidence, guaranteed_elapsed_ms,
    conservative_active_count,
)
from .model import Policy, positive_int
from .storage import InvalidSnapshot, SnapshotStore


def _encode_time(evidence: TimeEvidence) -> dict[str, Any]:
    return {
        "boot_id": evidence.boot_id,
        "boottime": {"low_ms": evidence.boottime.low_ms, "high_ms": evidence.boottime.high_ms},
        "trusted_absolute": None if evidence.trusted_absolute is None else {
            "low_ms": evidence.trusted_absolute.low_ms,
            "high_ms": evidence.trusted_absolute.high_ms,
        },
    }


def _decode_time(value: Any) -> TimeEvidence:
    if not isinstance(value, dict) or set(value) != {"boot_id", "boottime", "trusted_absolute"}:
        raise ValueError("invalid evidence fields")
    def bounds(v: Any) -> Bounds:
        if not isinstance(v, dict) or set(v) != {"low_ms", "high_ms"}:
            raise ValueError("invalid evidence bounds")
        return Bounds(v["low_ms"], v["high_ms"])
    return TimeEvidence(value["boot_id"], bounds(value["boottime"]),
                        None if value["trusted_absolute"] is None else bounds(value["trusted_absolute"]))


def _chronology(before: TimeEvidence, after: TimeEvidence) -> None:
    """Reject contradictory clocks; a different boot without UTC is unknown."""
    guaranteed_elapsed_ms(before, after)  # InconsistentTimeEvidence propagates


def _validate(p: dict[str, Any]) -> Policy:
    try:
        if not isinstance(p, dict) or set(p) != {
            "schema", "energy_object_id", "policy", "initial_state", "state",
            "initial_evidence", "state_verified", "last_evidence", "counter",
            "revision", "events", "noops", "pending", "quarantine",
        } or p["schema"] != 1:
            raise ValueError("unsupported evidence journal schema")
        _nonempty(p["energy_object_id"], "energy_object_id")
        policy = Policy.from_dict(p["policy"])
        if p["initial_state"] not in policy.states or p["state"] not in policy.states:
            raise ValueError("invalid power state")
        origin = _decode_time(p["initial_evidence"])
        current_evidence = _decode_time(p["state_verified"])
        checked = _decode_time(p["last_evidence"])
        positive_int(p["counter"], "counter")
        positive_int(p["revision"], "revision")
        if type(p["events"]) is not list or p["counter"] != p["revision"] or len(p["events"]) != p["revision"]:
            raise ValueError("event/counter mismatch")
        current_state, previous_evidence = p["initial_state"], origin
        seen: set[str] = set()
        for index, event in enumerate(p["events"], 1):
            if not isinstance(event, dict) or set(event) != {
                "seq", "op_id", "from", "to", "counter", "verified",
            }:
                raise ValueError("invalid event fields")
            rid = _nonempty(event["op_id"], "op_id")
            if rid in seen:
                raise ValueError("duplicate operation")
            seen.add(rid)
            if type(event["seq"]) is not int or event["seq"] != index or type(event["counter"]) is not int or event["counter"] != index:
                raise ValueError("counter/sequence disagreement")
            if event["from"] != current_state or (current_state, event["to"]) not in policy.edges:
                raise ValueError("invalid event chain")
            now = _decode_time(event["verified"])
            _chronology(previous_evidence, now)
            previous_evidence, current_state = now, event["to"]
        if current_state != p["state"] or _encode_time(previous_evidence) != p["state_verified"]:
            raise ValueError("verified state mismatch")
        _chronology(previous_evidence, checked)
        if type(p["noops"]) is not list:
            raise ValueError("invalid noop list")
        for noop in p["noops"]:
            if not isinstance(noop, dict) or set(noop) != {"op_id", "target"}:
                raise ValueError("invalid noop fields")
            rid = _nonempty(noop["op_id"], "noop ID")
            if rid in seen or noop["target"] not in policy.states:
                raise ValueError("duplicate/invalid noop")
            seen.add(rid)
        pending = p["pending"]
        if pending is not None:
            if not isinstance(pending, dict) or set(pending) != {
                "op_id", "target", "from", "expected_counter", "phase", "prepared", "dispatch",
            }:
                raise ValueError("invalid pending fields")
            rid = _nonempty(pending["op_id"], "pending ID")
            if rid in seen or pending["from"] != current_state or (current_state, pending["target"]) not in policy.edges:
                raise ValueError("invalid pending operation")
            if type(pending["expected_counter"]) is not int or pending["expected_counter"] != p["counter"]:
                raise ValueError("pending counter mismatch")
            prepared = _decode_time(pending["prepared"])
            _chronology(previous_evidence, prepared)
            _chronology(prepared, checked)
            if pending["phase"] == "prepared":
                if pending["dispatch"] is not None:
                    raise ValueError("prepared cannot have dispatch time")
            elif pending["phase"] in ("may-have-dispatched", "acknowledged", "unresolved"):
                dispatched = _decode_time(pending["dispatch"])
                _chronology(prepared, dispatched)
                _chronology(dispatched, checked)
            else:
                raise ValueError("invalid pending phase")
        if p["quarantine"] not in (None, "physical-divergence", "clock-inconsistent"):
            raise ValueError("invalid quarantine")
        return policy
    except (TypeError, ValueError, KeyError, InconsistentTimeEvidence) as exc:
        raise InvalidSnapshot("invalid evidence hardware journal; fail closed") from exc


@dataclass(frozen=True)
class EvidenceDecision:
    allowed: bool
    reason: str
    phase: str
    oper: str
    admin: str
    revision: int
    # No absolute retry is asserted: bounds across reboot may be unknowable.


class EvidenceHardwareExperiment:
    """One simulated device, serialized writers, and fail-closed time proofs."""

    def __init__(self, path: str | Path, *, actuator: SimulatedActuator):
        self.store = SnapshotStore(path)
        self.actuator = actuator

    @classmethod
    def initialize(cls, path: str | Path, *, actuator: SimulatedActuator, policy: Policy,
                   energy_object_id: str, evidence: TimeEvidence) -> "EvidenceHardwareExperiment":
        _nonempty(energy_object_id, "energy_object_id")
        if not isinstance(evidence, TimeEvidence):
            raise TypeError("time evidence required")
        hw = actuator.snapshot()
        if hw["energy_object_id"] != energy_object_id or hw["counter"] != 0 or hw["events"]:
            raise ValueError("fresh actuator journal required")
        if hw["state"] not in policy.states:
            raise ValueError("hardware state missing from policy")
        obj = cls(path, actuator=actuator)
        with obj.store.lock():
            obj.store.create({
                "schema": 1, "energy_object_id": energy_object_id, "policy": policy.to_dict(),
                "initial_state": hw["state"], "state": hw["state"],
                "initial_evidence": _encode_time(evidence), "state_verified": _encode_time(evidence),
                "last_evidence": _encode_time(evidence), "counter": 0, "revision": 0,
                "events": [], "noops": [], "pending": None, "quarantine": None,
            })
        return obj

    @classmethod
    def open(cls, path: str | Path, *, actuator: SimulatedActuator) -> "EvidenceHardwareExperiment":
        obj = cls(path, actuator=actuator)
        with obj.store.lock():
            _validate(obj.store.read())
        return obj

    @staticmethod
    def _decision(p: dict[str, Any], allowed: bool, reason: str) -> EvidenceDecision:
        pending = p["pending"]
        return EvidenceDecision(allowed, reason, pending["phase"] if pending else "idle",
                                p["state"], pending["target"] if pending else p["state"],
                                p["revision"])

    def status(self) -> dict[str, Any]:
        with self.store.lock():
            p = self.store.read()
            _validate(p)
            return {
                "energy_object_id": p["energy_object_id"], "oper": p["state"],
                "admin": p["pending"]["target"] if p["pending"] else p["state"],
                "counter": p["counter"], "revision": p["revision"],
                "pending": dict(p["pending"]) if p["pending"] else None,
                "quarantine": p["quarantine"], "events": [dict(e) for e in p["events"]],
            }

    def _observe(self, p: dict[str, Any], evidence: TimeEvidence) -> bool:
        if not isinstance(evidence, TimeEvidence):
            raise TypeError("TimeEvidence required")
        try:
            _chronology(_decode_time(p["last_evidence"]), evidence)
        except InconsistentTimeEvidence:
            p["quarantine"] = "clock-inconsistent"
            self.store.save(p)
            return False
        p["last_evidence"] = _encode_time(evidence)
        return True

    @staticmethod
    def _policy_reason(p: dict[str, Any], policy: Policy, target: str, now: TimeEvidence) -> str | None:
        if target not in policy.states:
            return "unknown-state"
        if (p["state"], target) not in policy.edges:
            return "unsupported-transition"
        try:
            residence = guaranteed_elapsed_ms(_decode_time(p["state_verified"]), now)
            if policy.min_dwell_ms[p["state"]] > 0 and (
                residence is None or residence < policy.min_dwell_ms[p["state"]]
            ):
                return "min-dwell-unproven"
            if p["events"]:
                elapsed = guaranteed_elapsed_ms(_decode_time(p["events"][-1]["verified"]), now)
                if (elapsed is None or elapsed < policy.min_interval_ms) and policy.min_interval_ms > 0:
                    return "min-interval-unproven"
            events = [_decode_time(event["verified"]) for event in p["events"]]
            if conservative_active_count(events, now, policy.window_ms) >= policy.max_transitions:
                return "rate-limit-unproven"
            return None
        except InconsistentTimeEvidence:
            return "clock-inconsistent"

    def _matches_hardware(self, p: dict[str, Any]) -> bool:
        hw = self.actuator.snapshot()
        return (hw["energy_object_id"] == p["energy_object_id"] and
                hw["counter"] == p["counter"] and hw["state"] == p["state"])

    def prepare(self, *, op_id: str, target: str, evidence: TimeEvidence,
                expected_revision: int | None = None) -> EvidenceDecision:
        _nonempty(op_id, "op_id")
        _nonempty(target, "target")
        if expected_revision is not None:
            positive_int(expected_revision, "expected_revision")
        with self.store.lock():
            p = self.store.read()
            policy = _validate(p)
            if p["quarantine"] is not None:
                return self._decision(p, False, p["quarantine"])
            if not self._observe(p, evidence):
                return self._decision(p, False, "clock-inconsistent")
            def finish(allowed: bool, reason: str) -> EvidenceDecision:
                self.store.save(p)
                return self._decision(p, allowed, reason)
            for event in p["events"] + p["noops"]:
                if event["op_id"] == op_id:
                    return finish(event.get("to", event.get("target")) == target,
                                  "replay" if event.get("to", event.get("target")) == target else "op-id-collision")
            if p["pending"] is not None:
                pending = p["pending"]
                if pending["op_id"] == op_id:
                    return finish(pending["target"] == target,
                                  "pending-replay" if pending["target"] == target else "op-id-collision")
                return finish(False, "busy")
            if expected_revision is not None and expected_revision != p["revision"]:
                return finish(False, "stale-revision")
            if not self._matches_hardware(p):
                p["quarantine"] = "physical-divergence"
                return finish(False, "physical-divergence")
            if target == p["state"]:
                p["noops"].append({"op_id": op_id, "target": target})
                return finish(True, "no-change")
            reason = self._policy_reason(p, policy, target, evidence)
            if reason is not None:
                if reason == "clock-inconsistent":
                    p["quarantine"] = "clock-inconsistent"
                return finish(False, reason)
            p["pending"] = {
                "op_id": op_id, "from": p["state"], "target": target,
                "expected_counter": p["counter"], "phase": "prepared",
                "prepared": _encode_time(evidence), "dispatch": None,
            }
            return finish(True, "prepared")

    def abort_prepared(self, *, op_id: str) -> EvidenceDecision:
        """Cancel only before a durable may-have-dispatched mark exists."""
        _nonempty(op_id, "op_id")
        with self.store.lock():
            p = self.store.read()
            _validate(p)
            pending = p["pending"]
            if p["quarantine"] is not None:
                return self._decision(p, False, p["quarantine"])
            if pending is None or pending["op_id"] != op_id or pending["phase"] != "prepared":
                return self._decision(p, False, "abort-unavailable")
            p["pending"] = None
            self.store.save(p)
            return self._decision(p, True, "aborted-before-dispatch")

    def timeout(self, *, op_id: str) -> EvidenceDecision:
        """Timeout leaves a possibly dispatched operation unresolved."""
        _nonempty(op_id, "op_id")
        with self.store.lock():
            p = self.store.read()
            _validate(p)
            pending = p["pending"]
            if pending is None or pending["op_id"] != op_id or pending["phase"] == "prepared":
                return self._decision(p, False, "timeout-unavailable")
            pending["phase"] = "unresolved"
            self.store.save(p)
            return self._decision(p, False, "unresolved")

    def dispatch(self, *, op_id: str, evidence: TimeEvidence,
                 crash_at: str | None = None) -> EvidenceDecision:
        _nonempty(op_id, "op_id")
        if crash_at not in (None, "before_mark", "after_mark", "after_effect", "after_ack"):
            raise ValueError("unknown fault point")
        with self.store.lock():
            p = self.store.read()
            policy = _validate(p)
            pending = p["pending"]
            if pending is None or pending["op_id"] != op_id or pending["phase"] != "prepared":
                return self._decision(p, False, "dispatch-unavailable")
            if p["quarantine"] is not None:
                return self._decision(p, False, p["quarantine"])
            if not self._observe(p, evidence):
                return self._decision(p, False, "clock-inconsistent")
            reason = self._policy_reason(p, policy, pending["target"], evidence)
            if reason is not None:
                if reason == "clock-inconsistent":
                    p["quarantine"] = "clock-inconsistent"
                self.store.save(p)
                return self._decision(p, False, reason)
            if not self._matches_hardware(p):
                p["quarantine"] = "physical-divergence"
                self.store.save(p)
                return self._decision(p, False, "physical-divergence")
            if crash_at == "before_mark":
                self.store.save(p)
                raise InjectedCrash("before persisted dispatch mark")
            pending["phase"] = "may-have-dispatched"
            pending["dispatch"] = _encode_time(evidence)
            self.store.save(p)
            if crash_at == "after_mark":
                raise InjectedCrash("after persisted dispatch mark")
            try:
                self.actuator.apply(op_id=op_id, target=pending["target"],
                                    expected_state=pending["from"], expected_counter=pending["expected_counter"])
            except ActuatorMismatch:
                pending["phase"] = "unresolved"
                self.store.save(p)
                return self._decision(p, False, "hardware-mismatch")
            if crash_at == "after_effect":
                raise InjectedCrash("after simulated physical edge")
            pending["phase"] = "acknowledged"
            self.store.save(p)
            if crash_at == "after_ack":
                raise InjectedCrash("after simulated ACK")
            return self._decision(p, True, "acknowledged")

    def reconcile(self, *, evidence: TimeEvidence) -> EvidenceDecision:
        with self.store.lock():
            p = self.store.read()
            _validate(p)
            if p["quarantine"] is not None:
                return self._decision(p, False, p["quarantine"])
            if not self._observe(p, evidence):
                return self._decision(p, False, "clock-inconsistent")
            pending = p["pending"]
            if pending is None or pending["phase"] == "prepared":
                self.store.save(p)
                return self._decision(p, False, "nothing-to-reconcile")
            hw = self.actuator.snapshot()
            counter = p["counter"] + 1
            matching = (hw["energy_object_id"] == p["energy_object_id"] and
                        hw["counter"] == counter and hw["state"] == pending["target"] and
                        len(hw["events"]) == counter)
            if matching:
                last = hw["events"][-1]
                matching = (last["counter"] == counter and last["id"] == pending["op_id"] and
                            last["kind"] == "managed" and last["from"] == pending["from"] and
                            last["to"] == pending["target"])
            if matching:
                p["revision"] += 1
                p["counter"] = counter
                p["state"] = pending["target"]
                p["state_verified"] = _encode_time(evidence)
                p["events"].append({
                    "seq": counter, "counter": counter, "op_id": pending["op_id"],
                    "from": pending["from"], "to": pending["target"],
                    "verified": _encode_time(evidence),
                })
                p["pending"] = None
                self.store.save(p)
                return self._decision(p, True, "verified")
            pending["phase"] = "unresolved"
            self.store.save(p)
            return self._decision(p, False, "unresolved")
