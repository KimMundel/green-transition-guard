"""Read-only quota-history retention proof for a bounded future window.

This projection NEVER deletes or rewrites persisted events. Its result is
conditional on future policy windows remaining within the supplied ceiling
and a nondecreasing clock. v0.1.10 can seal that premise in the journal;
compaction stays disabled for independent replay and checkpoint obligations.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Mapping

from .model import positive_int


@dataclass(frozen=True)
class QuotaRetentionView:
    as_of_ms: int
    max_future_window_ms: int
    total_events: int
    expired_for_quota: int
    last_transition_ms: int | None
    _retained_times: tuple[int, ...] = field(repr=False)
    enforced_ceiling_ms: int | None = None

    @property
    def retained_for_quota(self) -> int:
        return len(self._retained_times)

    def active_count(self, *, at_ms: int, window_ms: int) -> int:
        """Count accepted edges in (at_ms - window_ms, at_ms], subject to the proof bound."""
        positive_int(at_ms, "at_ms")
        positive_int(window_ms, "window_ms", allow_zero=False)
        if at_ms < self.as_of_ms:
            raise ValueError("clock earlier than retention reference time")
        if window_ms > self.max_future_window_ms:
            raise ValueError("window exceeds hypothetical retention ceiling")
        # Every retained timestamp is <= as_of_ms <= at_ms. The left window
        # boundary is excluded, including exact equality.
        return len(self._retained_times) - bisect_right(self._retained_times, at_ms - window_ms)

    def release_at(self, *, at_ms: int, window_ms: int, max_transitions: int) -> int | None:
        """Return the quota release time if already at cap; zero cap never releases."""
        positive_int(max_transitions, "max_transitions")
        count = self.active_count(at_ms=at_ms, window_ms=window_ms)
        if max_transitions == 0:
            return None
        if count < max_transitions:
            return None
        active = self._retained_times[bisect_right(self._retained_times, at_ms - window_ms):]
        return active[len(active) - max_transitions] + window_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_ms": self.as_of_ms,
            "max_future_window_ms": self.max_future_window_ms,
            "total_events": self.total_events,
            "expired_for_quota": self.expired_for_quota,
            "retained_for_quota": self.retained_for_quota,
            "last_transition_ms": self.last_transition_ms,
            "journal_compaction_enabled": False,
            "enforced_ceiling_ms": self.enforced_ceiling_ms,
            "retention_bound_enforced": (
                self.enforced_ceiling_ms is not None
                and self.enforced_ceiling_ms <= self.max_future_window_ms
            ),
            "unresolved_dependencies": (
                ([] if self.enforced_ceiling_ms is not None
                  and self.enforced_ceiling_ms <= self.max_future_window_ms
                  else ["enforce future policy-window ceiling"])
                + [
                "preserve global request ID deduplication and replay behavior",
                "preserve historical policy-epoch and event-chain validation",
                "preserve last-transition time for arbitrary future interval limits",
                "bound or deliberately fail closed on unbounded operation volume",
                ]
            ),
        }


def build_quota_retention_view(
    events: list[Mapping[str, Any]], *, as_of_ms: int, max_future_window_ms: int,
    enforced_ceiling_ms: int | None = None,
) -> QuotaRetentionView:
    """Find a quota-irrelevant event prefix, with a proof restricted to future windows.

    Call on an already validated journal. Additional checks make direct use
    with untrusted inputs fail rather than producing an unsound projection.
    """
    positive_int(as_of_ms, "as_of_ms")
    positive_int(max_future_window_ms, "max_future_window_ms", allow_zero=False)
    if enforced_ceiling_ms is not None:
        positive_int(enforced_ceiling_ms, "enforced_ceiling_ms", allow_zero=False)
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    times: list[int] = []
    previous = 0
    for event in events:
        if not isinstance(event, Mapping) or "at_ms" not in event:
            raise ValueError("event missing at_ms")
        timestamp = positive_int(event["at_ms"], "event time")
        if timestamp < previous or timestamp > as_of_ms:
            raise ValueError("event times must be monotonic and no later than as_of_ms")
        previous = timestamp
        times.append(timestamp)
    # The half-open interval excludes exactly as_of_ms - max_future_window_ms.
    first_retained = bisect_right(times, as_of_ms - max_future_window_ms)
    return QuotaRetentionView(
        as_of_ms=as_of_ms,
        max_future_window_ms=max_future_window_ms,
        total_events=len(times),
        expired_for_quota=first_retained,
        last_transition_ms=times[-1] if times else None,
        _retained_times=tuple(times[first_retained:]),
        enforced_ceiling_ms=enforced_ceiling_ms,
    )
