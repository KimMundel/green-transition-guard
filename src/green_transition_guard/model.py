"""Transition constraint and decision types.

All time values are integer milliseconds from one trusted, nondecreasing
clock domain. Runtime systems must define reliable wall-clock semantics.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Reason(StrEnum):
    ACCEPTED = "accepted"
    NO_CHANGE = "no-change"
    REPLAY = "replay"
    REQUEST_ID_COLLISION = "request-id-collision"
    CLOCK_REGRESSION = "clock-regression"
    STALE_REVISION = "stale-revision"
    STALE_POLICY_REVISION = "stale-policy-revision"
    UNKNOWN_STATE = "unknown-state"
    UNSUPPORTED_TRANSITION = "unsupported-transition"
    MIN_DWELL = "min-dwell"
    MIN_INTERVAL = "min-interval"
    RATE_LIMIT = "rate-limit"


def positive_int(value: Any, name: str, *, allow_zero: bool = True) -> int:
    if type(value) is not int or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be a {'nonnegative' if allow_zero else 'positive'} integer")
    return value


@dataclass(frozen=True)
class Policy:
    """Immutable per-device constraints; all possible transitions are explicit."""
    states: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    min_dwell_ms: dict[str, int]
    min_interval_ms: int
    window_ms: int
    max_transitions: int

    def __post_init__(self) -> None:
        if not self.states or any(not isinstance(s, str) or not s for s in self.states):
            raise ValueError("states must be nonempty strings")
        if len(set(self.states)) != len(self.states):
            raise ValueError("states must be unique")
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("edges must be unique")
        if any(len(e) != 2 or e[0] not in self.states or e[1] not in self.states or e[0] == e[1] for e in self.edges):
            raise ValueError("edges must connect two different declared states")
        if set(self.min_dwell_ms) != set(self.states):
            raise ValueError("min_dwell_ms must specify every state")
        for state, value in self.min_dwell_ms.items():
            positive_int(value, f"min_dwell_ms[{state}]")
        positive_int(self.min_interval_ms, "min_interval_ms")
        positive_int(self.window_ms, "window_ms", allow_zero=False)
        positive_int(self.max_transitions, "max_transitions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "states": list(self.states),
            "edges": [list(edge) for edge in self.edges],
            "min_dwell_ms": dict(self.min_dwell_ms),
            "min_interval_ms": self.min_interval_ms,
            "window_ms": self.window_ms,
            "max_transitions": self.max_transitions,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Policy":
        if not isinstance(raw, dict) or set(raw) != {
            "states", "edges", "min_dwell_ms", "min_interval_ms", "window_ms", "max_transitions"
        }:
            raise ValueError("invalid policy fields")
        if not isinstance(raw["states"], list) or not isinstance(raw["edges"], list) or not isinstance(raw["min_dwell_ms"], dict):
            raise ValueError("invalid policy collections")
        if any(not isinstance(edge, list) or len(edge) != 2 for edge in raw["edges"]):
            raise ValueError("invalid transition edge")
        return cls(
            states=tuple(raw["states"]),
            edges=tuple(tuple(edge) for edge in raw["edges"]),
            min_dwell_ms=raw["min_dwell_ms"],
            min_interval_ms=raw["min_interval_ms"],
            window_ms=raw["window_ms"],
            max_transitions=raw["max_transitions"],
        )


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: Reason
    current_state: str
    revision: int
    retry_at_ms: int | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "current_state": self.current_state,
            "revision": self.revision,
            "retry_at_ms": self.retry_at_ms,
            "event_id": self.event_id,
        }
