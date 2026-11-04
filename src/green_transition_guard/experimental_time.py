"""Experimental conservative time-evidence comparisons, separate from the v0.1 engine.

Assumptions:
- A clock provider guarantees that actual time is inside every given interval.
- boot_id identifies the same monotonic clock epoch without collision.
- uptime is a suspend-aware elapsed time source, e.g. CLOCK_BOOTTIME.
- trusted_absolute is independently bounded global time; a plain OS clock
  value does not meet that contract without validated bounds.
- Timestamps are observations in chronological order of physical events.

This module deliberately does not authenticate or construct clock evidence.
It supports research tests only and does not enforce physical safety.
"""

from dataclasses import dataclass


class InconsistentTimeEvidence(ValueError):
    """The supplied intervals cannot describe chronological observations."""


@dataclass(frozen=True)
class Bounds:
    low_ms: int
    high_ms: int

    def __post_init__(self) -> None:
        if type(self.low_ms) is not int or type(self.high_ms) is not int:
            raise ValueError("time interval endpoints must be integers")
        if self.low_ms < 0 or self.high_ms < self.low_ms:
            raise ValueError("invalid nonnegative time interval")


@dataclass(frozen=True)
class TimeEvidence:
    boot_id: str
    boottime: Bounds
    trusted_absolute: Bounds | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.boot_id, str) or not self.boot_id:
            raise ValueError("boot_id must be nonempty")
        if not isinstance(self.boottime, Bounds):
            raise ValueError("boottime interval is required")
        if self.trusted_absolute is not None and not isinstance(self.trusted_absolute, Bounds):
            raise ValueError("invalid trusted_absolute interval")


def guaranteed_elapsed_ms(earlier: TimeEvidence, later: TimeEvidence) -> int | None:
    """Minimum guaranteed nonnegative elapsed time or None if unknowable.

    Conservative intersection of elapsed-time ranges from applicable clocks.
    Inconsistent ranges fail closed instead of selecting a convenient clock.
    """
    ranges: list[tuple[int, int]] = []
    if earlier.boot_id == later.boot_id:
        ranges.append((
            later.boottime.low_ms - earlier.boottime.high_ms,
            later.boottime.high_ms - earlier.boottime.low_ms,
        ))
    if earlier.trusted_absolute is not None and later.trusted_absolute is not None:
        ranges.append((
            later.trusted_absolute.low_ms - earlier.trusted_absolute.high_ms,
            later.trusted_absolute.high_ms - earlier.trusted_absolute.low_ms,
        ))
    if not ranges:
        return None
    lowest = max(0, *(a for a, _ in ranges))
    highest = min(b for _, b in ranges)
    if highest < lowest:
        raise InconsistentTimeEvidence("inconsistent time evidence; fail closed")
    return lowest


def definitely_expired(event: TimeEvidence, now: TimeEvidence, window_ms: int) -> bool:
    """Prove an event cannot remain in the half-open rolling window (now-W, now]."""
    if type(window_ms) is not int or window_ms <= 0:
        raise ValueError("window_ms must be positive")
    elapsed = guaranteed_elapsed_ms(event, now)
    return elapsed is not None and elapsed >= window_ms


def conservative_active_count(events: list[TimeEvidence], now: TimeEvidence, window_ms: int) -> int:
    """Unknown or overlapping event times always consume quota."""
    return sum(not definitely_expired(event, now, window_ms) for event in events)
