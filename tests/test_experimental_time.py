"""Conservative clock research tests; no hardware safety assertions."""
import pytest

from green_transition_guard.experimental_time import (
    Bounds,
    InconsistentTimeEvidence,
    TimeEvidence,
    conservative_active_count,
    definitely_expired,
    guaranteed_elapsed_ms,
)


def t(boot: str, uptime_low: int, uptime_high: int | None = None,
      abs_low: int | None = None, abs_high: int | None = None) -> TimeEvidence:
    uptime = Bounds(uptime_low, uptime_low if uptime_high is None else uptime_high)
    absolute = None if abs_low is None else Bounds(abs_low, abs_low if abs_high is None else abs_high)
    return TimeEvidence(boot, uptime, absolute)


def test_same_boot_window_boundary_exact():
    start = t('boot-a', 100)
    assert definitely_expired(start, t('boot-a', 60_100), 60_000)
    assert not definitely_expired(start, t('boot-a', 60_099), 60_000)


def test_suspend_aware_clock_elapsed_even_when_process_slept():
    # Clock evidence deliberately includes suspended time.
    assert guaranteed_elapsed_ms(t('boot-a', 1_000), t('boot-a', 91_000)) == 90_000


def test_reboot_without_clock_evidence_cannot_expire_previous_transition():
    event = t('boot-a', 50_000)
    now = t('boot-b', 100)
    assert guaranteed_elapsed_ms(event, now) is None
    assert not definitely_expired(event, now, 60_000)


def test_cross_reboot_with_bounded_trusted_time_at_exact_boundary():
    event = t('boot-a', 50_000, abs_low=1_000_000, abs_high=1_000_100)
    now = t('boot-b', 100, abs_low=1_060_100, abs_high=1_060_200)
    assert guaranteed_elapsed_ms(event, now) == 60_000
    assert definitely_expired(event, now, 60_000)


def test_uncertainty_requires_latest_plausible_event_time():
    event = t('a', 20_000, abs_low=1_000, abs_high=1_100)
    almost = t('b', 1, abs_low=61_099, abs_high=61_500)
    boundary = t('b', 2, abs_low=61_100, abs_high=61_600)
    assert not definitely_expired(event, almost, 60_000)
    assert definitely_expired(event, boundary, 60_000)


def test_count_ambiguous_events_as_active():
    events = [t('a', 100), t('a', 110)]
    assert conservative_active_count(events, t('b', 100), 60_000) == 2
    assert conservative_active_count(events, t('a', 60_109), 60_000) == 1


def test_inconsistent_same_boot_and_absolute_evidence_fails_closed():
    event = t('a', 1_000, abs_low=1_000_000, abs_high=1_000_010)
    now = t('a', 61_000, abs_low=1_000_100, abs_high=1_000_110)
    with pytest.raises(InconsistentTimeEvidence):
        definitely_expired(event, now, 60_000)


def test_nonchronological_observations_fail_closed():
    with pytest.raises(InconsistentTimeEvidence):
        guaranteed_elapsed_ms(t('a', 10_000), t('a', 1_000))


def test_valid_evidence_bounds_must_be_ordered():
    with pytest.raises(ValueError):
        Bounds(100, 99)
    with pytest.raises(ValueError):
        Bounds(-1, 0)


def test_random_bounded_evidence_never_overstates_elapsed():
    # Independent known-truth oracle: both claimed bounds contain the actual
    # event instant; a conservative result may underestimate elapsed time.
    import random
    rng = random.Random(20261104)
    for _ in range(2000):
        truth_event = rng.randrange(1_000, 100_000)
        actual_elapsed = rng.randrange(0, 120_000)
        truth_now = truth_event + actual_elapsed
        left_before, right_before = rng.randrange(0, 500), rng.randrange(0, 500)
        left_now, right_now = rng.randrange(0, 500), rng.randrange(0, 500)
        event = t('older-boot', 123,
                  abs_low=truth_event - left_before,
                  abs_high=truth_event + right_before)
        now = t('new-boot', 5,
                abs_low=truth_now - left_now,
                abs_high=truth_now + right_now)
        lower = guaranteed_elapsed_ms(event, now)
        assert lower is not None
        assert 0 <= lower <= actual_elapsed
        if definitely_expired(event, now, 60_000):
            assert actual_elapsed >= 60_000
