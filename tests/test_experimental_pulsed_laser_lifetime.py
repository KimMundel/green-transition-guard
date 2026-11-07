"""Synthetic examples: vendor pulse-life estimates are never safety authority."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from green_transition_guard.experimental_pulsed_laser_lifetime import (
    InvalidPulsedLifetimeEvidence, PulseLifetimeAssessment,
    PulsedLifetimeClaim, SyntheticPulseHistory, compare_synthetic_pulses,
    load_pulsed_lifetime_manifest, parse_pulsed_lifetime_manifest,
)


CORPUS = Path(__file__).resolve().parents[1] / "conformance" / "pulsed-laser-lifetime.json"


def references():
    return {r.pulse_width_ms: r for r in load_pulsed_lifetime_manifest(CORPUS)}


def history(reference=None, **changes):
    ref = reference or references()[5]
    attrs = dict(product_model=ref.product_model, component_instance_id="qc-stack-A",
                 component_kind=ref.component_kind, event=ref.event,
                 pulse_width_ms=ref.pulse_width_ms,
                 pulse_frequency_hz=ref.pulse_frequency_hz,
                 duty_cycle_percent=ref.duty_cycle_percent,
                 case_temperature_c=ref.case_temperature_c,
                 observed_shots=0, coverage="complete-synthetic")
    attrs.update(changes)
    return SyntheticPulseHistory(**attrs)


def compare(reference=None, observation=None, expected="qc-stack-A"):
    ref = reference or references()[5]
    return compare_synthetic_pulses(ref, observation or history(ref),
                                    expected_component_instance_id=expected)


def corpus_obj():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def modify(field, value, idx=0):
    obj = corpus_obj()
    obj["records"][idx][field] = value
    return json.dumps(obj)


def test_supplier_modes_and_source_conflict_are_recorded():
    items = references()
    assert set(items) == {5, 20, 100}
    assert items[5].expected_shots == 30_000_000
    assert items[20].expected_shots == 15_000_000
    assert items[100].expected_shots == 15_000_000
    assert items[100].table_peak_power_w == 1500
    assert items[100].summary_peak_power_w == 1200
    assert all(items[w].source_conditions_consistent for w in (5, 20))
    assert not items[100].source_conditions_consistent
    assert {x.claim_kind for x in items.values()} == {"mode-dependent-expected-lifetime-shots"}
    assert {x.case_temperature_c for x in items.values()} == {22}


@pytest.mark.parametrize("width,n,reason", [
    (5, 0, "synthetic-below-vendor-estimate"),
    (5, 29_999_999, "synthetic-below-vendor-estimate"),
    (5, 30_000_000, "synthetic-at-or-above-vendor-estimate"),
    (5, 30_000_001, "synthetic-at-or-above-vendor-estimate"),
    (20, 14_999_999, "synthetic-below-vendor-estimate"),
    (20, 15_000_000, "synthetic-at-or-above-vendor-estimate"),
    (20, 2**63 - 1, "synthetic-at-or-above-vendor-estimate"),
])
def test_only_exact_synthetic_modes_have_descriptive_comparisons(width, n, reason):
    ref = references()[width]
    assessment = compare(ref, history(ref, observed_shots=n))
    assert (assessment.reason, assessment.synthetic_shots,
            assessment.vendor_expected_shots) == (reason, n, ref.expected_shots)
    assert not assessment.green_power_state_capability
    assert not assessment.hardware_authorized


@pytest.mark.parametrize("n", [0, 14_999_999, 15_000_000, 30_000_000])
def test_conflicting_long_pulse_conditions_never_release_count(n):
    ref = references()[100]
    result = compare(ref, history(ref, observed_shots=n))
    assert result.reason == "conflicting-source-conditions"
    assert result.synthetic_shots is None and result.vendor_expected_shots is None
    assert not result.hardware_authorized


@pytest.mark.parametrize("change,expected", [
    ({"product_model": "Cisco-NCS5500-transceiver"}, "different-product"),
    ({"product_model": "C1Y-808F-3000Q-VH(1-20)-clone"}, "different-product"),
    ({"component_kind": "telecom-optical-transceiver"}, "different-component-kind"),
    ({"component_kind": "thermoelectric-cooler"}, "different-component-kind"),
    ({"event": "optical-transceiver-admin-sleep"}, "different-event"),
    ({"event": "mechanical-shutter-open-close"}, "different-event"),
    ({"event": "module-mating-unmating-cycle"}, "different-event"),
    ({"event": "cooled-module-qualification-power-cycle"}, "different-event"),
    ({"component_instance_id": "qc-stack-B"}, "different-component-instance"),
    ({"case_temperature_c": 23}, "different-case-temperature"),
    ({"case_temperature_c": 0}, "different-case-temperature"),
    ({"coverage": "partial-synthetic"}, "partial-synthetic-history"),
    ({"pulse_width_ms": 10, "pulse_frequency_hz": 10}, "different-pulse-mode"),
    ({"pulse_width_ms": 20, "pulse_frequency_hz": 5}, "different-pulse-mode"),
])
def test_cross_application_cannot_receive_numeric_claim(change, expected):
    report = compare(observation=history(**change))
    assert report.reason == expected
    assert report.vendor_expected_shots is None
    assert report.synthetic_shots is None
    assert not report.hardware_authorized
    assert not report.green_power_state_capability


def test_expected_component_instance_is_a_required_external_assertion():
    report = compare(observation=history(observed_shots=30000000), expected="qc-stack-B")
    assert report.reason == "different-component-instance"


@pytest.mark.parametrize("field,value", [
    ("product_model", ""), ("product_model", " model"),
    ("product_model", "a" * 257), ("event", "bad\x00event"),
    ("component_instance_id", ""), ("component_instance_id", "a\nb"),
    ("observed_shots", -1), ("observed_shots", True),
    ("observed_shots", 1.5), ("observed_shots", 2**63),
    ("case_temperature_c", False), ("case_temperature_c", 151),
    ("pulse_width_ms", 0), ("pulse_width_ms", 1.2),
    ("pulse_frequency_hz", 0), ("pulse_frequency_hz", True),
    ("duty_cycle_percent", -1), ("duty_cycle_percent", 101),
    ("coverage", "hardware-verified"), ("coverage", None),
])
def test_invalid_synthetic_input_rejected(field, value):
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        history(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("id", " "), ("source_url", "http://example.org/claims"),
    ("source_url", "https://user:pass@ephotonics.com/x"),
    ("source_url", "https://[bad-ipv6"),
    ("source_url", "https://ephotonics.com/x\t"),
    ("source_locator", "line\n5"),
    ("component_kind", "transceiver"),
    ("event", "on-to-sleep"),
    ("claim_kind", "absolute-maximum-safe-shots"),
    ("pulse_width_ms", 0), ("pulse_width_ms", -1),
    ("pulse_frequency_hz", 0), ("pulse_frequency_hz", 1.2),
    ("case_temperature_c", 200),
    ("duty_cycle_percent", 0), ("duty_cycle_percent", True),
    ("table_peak_power_w", -1), ("summary_peak_power_w", True),
    ("expected_shots", 0), ("expected_shots", -1),
    ("expected_shots", 2**63),
])
def test_invalid_supplier_reference_rejected(field, value):
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        parse_pulsed_lifetime_manifest(modify(field, value))


def test_source_conflict_is_a_valid_claim_but_ineligible_for_comparison():
    old = references()[5]
    ref = replace(old, summary_peak_power_w=1200)
    result = compare(ref, history(old))
    assert result.reason == "conflicting-source-conditions"


def test_inconsistent_duty_requires_rejection_instead_of_rounding():
    with pytest.raises(InvalidPulsedLifetimeEvidence, match="duty"):
        history(pulse_width_ms=7, pulse_frequency_hz=20)
    with pytest.raises(InvalidPulsedLifetimeEvidence, match="duty"):
        parse_pulsed_lifetime_manifest(modify("duty_cycle_percent", 11))


@pytest.mark.parametrize("mutation", [
    lambda obj: obj.pop("schema_version"),
    lambda obj: obj.update(schema_version=True),
    lambda obj: obj.update(schema_version=2),
    lambda obj: obj.update(records=[]),
    lambda obj: obj.update(records=obj["records"] * 11),
    lambda obj: obj["records"].append(obj["records"][0]),
    lambda obj: obj["records"][0].update(unexpected=True),
    lambda obj: obj["records"][0].pop("product_model"),
])
def test_bad_manifest_shapes_rejected(mutation):
    obj = corpus_obj()
    mutation(obj)
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        parse_pulsed_lifetime_manifest(json.dumps(obj))


def test_duplicate_mode_with_new_id_still_rejected():
    obj = corpus_obj()
    row = dict(obj["records"][0], id="new-id")
    obj["records"].append(row)
    with pytest.raises(InvalidPulsedLifetimeEvidence, match="duplicate"):
        parse_pulsed_lifetime_manifest(json.dumps(obj))


@pytest.mark.parametrize("raw", [
    '{"schema_version":1,"schema_version":1,"records":[]}',
    '{"schema_version":1,"records":[{"id":"a","id":"b"}]}',
    "[]", "null", "{}", "not-json", "x" * 131073, "\ud800",
])
def test_invalid_raw_manifest_rejected(raw):
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        parse_pulsed_lifetime_manifest(raw)


def test_loader_bound_and_invalid_encoding(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_bytes(b"\xff\xfe")
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        load_pulsed_lifetime_manifest(target)
    target.write_bytes(b"x" * 131073)
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        load_pulsed_lifetime_manifest(target)


def test_corpus_loading_never_modifies_corpus():
    before = CORPUS.read_bytes()
    assert len(load_pulsed_lifetime_manifest(CORPUS)) == 3
    assert CORPUS.read_bytes() == before


@pytest.mark.parametrize("reason,counts", [
    ("synthetic-below-vendor-estimate", (30, 30)),
    ("synthetic-at-or-above-vendor-estimate", (29, 30)),
    ("different-product", (1, 30)),
    ("unknown", (None, None)),
])
def test_immutable_reports_reject_contradictory_claims(reason, counts):
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        PulseLifetimeAssessment(reason, *counts)


@pytest.mark.parametrize("kwargs", [
    {"hardware_authorized": True},
    {"green_power_state_capability": True},
])
def test_admission_flags_cannot_be_overridden(kwargs):
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        PulseLifetimeAssessment("synthetic-below-vendor-estimate", 0, 30, **kwargs)


def test_typed_values_and_immutable_reference():
    with pytest.raises(TypeError):
        compare_synthetic_pulses(None, history(), expected_component_instance_id="qc-stack-A")
    with pytest.raises(TypeError):
        compare_synthetic_pulses(references()[5], {"observed_shots": 0},
                                 expected_component_instance_id="qc-stack-A")
    with pytest.raises(InvalidPulsedLifetimeEvidence):
        compare(expected="\n")
    with pytest.raises(AttributeError):
        references()[5].expected_shots = 1
