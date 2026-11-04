"""Simulated contract/snapshot invariants; no physical counter was sampled."""

from dataclasses import replace

import pytest

from green_transition_guard.experimental_counter_provenance import (
    CounterContract, CounterSample, assess_counter_pair,
)


def contract(**changes):
    base = dict(energy_object_id="linecard-1", source_id="protected-source-1",
                kind="physical-edge", covers_all_policy_edges=True,
                includes_autonomous_edges=True, survives_full_power_loss=True,
                atomic_with_physical_edge=True, protected_from_unauthorized_reset=True,
                stable_component_binding=True, documented_reset_epoch=True,
                no_undetected_wrap=True)
    base.update(changes)
    return CounterContract(**base)


def sample(**changes):
    base = dict(energy_object_id="linecard-1", source_id="protected-source-1",
                counter_epoch="hw-counter-epoch-1", sample_sequence=1,
                count=12, oper="on", coverage_gap=False)
    base.update(changes)
    return CounterSample(**base)


def assess(current, *, old=None, source=None):
    return assess_counter_pair(source or contract(), old or sample(), current)


def test_zero_delta_same_state_is_conditionally_usable():
    a = assess(sample(sample_sequence=2))
    assert (a.reason, a.quarantine, a.count_delta, a.conditional_candidate) == (
        "no-counted-edges", False, 0, True)


def test_external_edges_are_never_claimed_as_a_command_ack():
    a = assess(sample(count=14, sample_sequence=2))
    assert a.quarantine and a.reason == "new-unattributed-edges" and a.count_delta == 2


@pytest.mark.parametrize("modified", [
    {"counter_epoch": "reset-2"}, {"count": 11},
    {"sample_sequence": 1}, {"sample_sequence": 0},
    {"source_id": "other-source"}, {"energy_object_id": "other-device"},
    {"coverage_gap": True}, {"oper": "sleep"},
])
def test_unsafe_observations_quarantine(modified):
    a = assess(sample(sample_sequence=2, **modified) if "sample_sequence" not in modified else sample(**modified))
    assert a.quarantine and not a.conditional_candidate


@pytest.mark.parametrize("missing", [
    "covers_all_policy_edges", "includes_autonomous_edges", "survives_full_power_loss",
    "atomic_with_physical_edge", "protected_from_unauthorized_reset",
    "stable_component_binding", "documented_reset_epoch", "no_undetected_wrap",
])
def test_missing_contract_property_is_only_diagnostic(missing):
    c = replace(contract(), **{missing: False})
    a = assess(sample(sample_sequence=2), source=c)
    assert a.quarantine and a.reason == "diagnostic-source-only"


@pytest.mark.parametrize("kind", ["power-cycle", "lpi-entry", "thermal-action", "event-log", "host-state"])
def test_existing_counter_types_are_diagnostic_without_a_full_mapping(kind):
    c = contract(kind=kind)
    a = assess(sample(sample_sequence=2), source=c)
    assert a.reason == "diagnostic-source-only" and a.quarantine


def test_same_state_with_two_hidden_edges_is_detected():
    a = assess(sample(sample_sequence=2, count=14, oper="on"))
    assert a.count_delta == 2 and a.quarantine


def test_counter_wrap_cannot_be_guessed_from_decrement():
    old = sample(count=2**32 - 1)
    new = sample(sample_sequence=2, count=0)
    assert assess(new, old=old).reason == "counter-decreased-or-wrapped"


def test_bad_sample_types_rejected():
    with pytest.raises(ValueError):
        sample(count=True)
    with pytest.raises(ValueError):
        sample(coverage_gap=1)
    with pytest.raises(ValueError):
        contract(covers_all_policy_edges="yes")
    with pytest.raises(ValueError):
        contract(kind="unknown")


def test_source_switch_does_not_relabel_as_zero_delta():
    other = sample(source_id="protected-source-2", sample_sequence=2)
    assert assess(other).count_delta is None


def test_saturating_counter_at_max_quarantined_even_without_count_change():
    c = contract(max_counter_value=2**32 - 1)
    old = sample(count=2**32 - 1)
    new = sample(count=2**32 - 1, sample_sequence=2)
    assert assess(new, old=old, source=c).reason == "counter-at-maximum"


def test_counter_outside_declared_range_quarantined():
    c = contract(max_counter_value=100)
    assert assess(sample(count=101, sample_sequence=2), source=c).reason == "counter-exceeds-declared-range"


def test_undetectable_full_wrap_disqualifies_counter():
    c = contract(no_undetected_wrap=False)
    assert assess(sample(sample_sequence=2), source=c).reason == "diagnostic-source-only"
