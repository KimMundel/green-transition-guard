"""Synthetic mechanical qualification checks; no real equipment is sampled."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from green_transition_guard.experimental_wear_qualification import (
    InvalidWearEvidence, SyntheticWearCount, WearComparison,
    WearQualification, compare_synthetic_wear, load_wear_manifest,
    parse_wear_manifest,
)

CORPUS = Path(__file__).resolve().parents[1] / "conformance" / "mechanical-wear-qualification.json"


def references():
    return {item.component: item for item in load_wear_manifest(CORPUS)}


def sample(**changes):
    data = dict(form_factor="SFP-DD", component="module",
                event="module-mating-unmating-cycle",
                component_instance_id="module-A-generation-1", count=0,
                coverage="complete-synthetic")
    data.update(changes)
    return SyntheticWearCount(**data)


def compare(reference=None, observation=None, **kwargs):
    reference = reference or references()["module"]
    observation = observation or sample()
    return compare_synthetic_wear(
        reference, observation,
        expected_component_instance_id=kwargs.get("expected", "module-A-generation-1"),
    )


def payload():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def modified(field, value, record=0):
    data = payload()
    data["records"][record][field] = value
    return json.dumps(data)


def test_industry_reference_values_are_separate_component_scopes():
    ref = references()
    assert len(ref) == 2
    assert ref["module"].rated_cycles == 50
    assert ref["connector-cage"].rated_cycles == 100
    for item in ref.values():
        assert item.form_factor == "SFP-DD"
        assert item.event == "module-mating-unmating-cycle"
        assert item.claim_kind == "rated-mechanical-durability-cycles"
        assert item.authority == "industry-consortium-specification"
        assert "Table 13" in item.source_locator
        assert "2020-08-17" in item.source_revision


@pytest.mark.parametrize("count,reason", [
    (0, "synthetic-below-qualification-reference"),
    (49, "synthetic-below-qualification-reference"),
    (50, "synthetic-at-or-above-qualification-reference"),
    (51, "synthetic-at-or-above-qualification-reference"),
    (100, "synthetic-at-or-above-qualification-reference"),
    (2**63 - 1, "synthetic-at-or-above-qualification-reference"),
])
def test_module_qualification_boundary_is_descriptive_only(count, reason):
    result = compare(observation=sample(count=count))
    assert (result.reason, result.counted_cycles, result.qualification_reference_cycles) == (
        reason, count, 50,
    )
    assert not result.green_power_state_capability
    assert not result.hardware_authorized


@pytest.mark.parametrize("count,reason", [
    (0, "synthetic-below-qualification-reference"),
    (50, "synthetic-below-qualification-reference"),
    (99, "synthetic-below-qualification-reference"),
    (100, "synthetic-at-or-above-qualification-reference"),
    (101, "synthetic-at-or-above-qualification-reference"),
])
def test_connector_cage_has_separate_rating(count, reason):
    report = compare(
        reference=references()["connector-cage"],
        observation=sample(component="connector-cage", count=count),
    )
    assert report.reason == reason
    assert report.qualification_reference_cycles == 100
    assert not report.hardware_authorized


@pytest.mark.parametrize("change,reason", [
    ({"form_factor": "SFP"}, "different-form-factor"),
    ({"form_factor": "QSFP-DD"}, "different-form-factor"),
    ({"component": "connector-cage"}, "different-component-scope"),
    ({"event": "optical-laser-power-on"}, "different-event-domain"),
    ({"event": "optics-controller-admin-sleep"}, "different-event-domain"),
    ({"event": "module-TxDisable-assert"}, "different-event-domain"),
    ({"component_instance_id": "replacement-module"}, "different-component-instance"),
    ({"coverage": "partial-synthetic"}, "incomplete-synthetic-history"),
])
def test_incompatible_scope_never_releases_numeric_rating(change, reason):
    report = compare(observation=sample(count=500, **change))
    assert (report.reason, report.counted_cycles, report.qualification_reference_cycles) == (
        reason, None, None,
    )
    assert not report.hardware_authorized
    assert not report.green_power_state_capability


def test_expected_component_generation_must_match():
    report = compare(observation=sample(count=50), expected="module-A-generation-2")
    assert report.reason == "different-component-instance"
    assert report.qualification_reference_cycles is None


def test_partial_history_cannot_establish_number_of_mating_cycles():
    report = compare(observation=sample(count=100000, coverage="partial-synthetic"))
    assert report.reason == "incomplete-synthetic-history"
    assert report.counted_cycles is None


@pytest.mark.parametrize("name,value", [
    ("form_factor", ""), ("form_factor", " SFP-DD"),
    ("component", ""), ("component", "optics\nmodule"),
    ("event", "tx-disable\x00assert"),
    ("component_instance_id", ""),
    ("component_instance_id", "x" * 257),
    ("count", -1), ("count", True), ("count", 1.0),
    ("count", 2**63), ("coverage", "hardware-verified"),
    ("coverage", None),
])
def test_invalid_synthetic_counts_are_rejected(name, value):
    with pytest.raises(InvalidWearEvidence):
        sample(**{name: value})


@pytest.mark.parametrize("field,value", [
    ("authority", "vendor-confirmed-laser-limit"),
    ("form_factor", ""), ("component", "laser"),
    ("event", "laser-switch-cycle"),
    ("claim_kind", "hardware-operational-cycle-maximum"),
    ("rated_cycles", 0), ("rated_cycles", -1),
    ("rated_cycles", True), ("rated_cycles", 1.5),
    ("rated_cycles", 2**63),
    ("source_url", "http://sfp-dd.com/reference"),
    ("source_url", "https://alice:secret@sfp-dd.com/rev.pdf"),
    ("source_url", "https://[bad-ipv6"),
    ("source_url", "https://sfp-dd.com/rev.pdf\t"),
    ("source_revision", "  "),
    ("source_locator", "Table\n13"),
])
def test_manually_entered_reference_fields_fail_closed(field, value):
    with pytest.raises(InvalidWearEvidence):
        parse_wear_manifest(modified(field, value))


@pytest.mark.parametrize("mutation", [
    lambda data: data.pop("schema_version"),
    lambda data: data.update(schema_version=True),
    lambda data: data.update(schema_version=2),
    lambda data: data.update(records=[]),
    lambda data: data.update(records=data["records"] * 17),
    lambda data: data["records"].append(data["records"][0]),
    lambda data: data["records"][0].pop("component"),
    lambda data: data["records"][0].update(untrusted_extra="oops"),
])
def test_manifest_rejects_invalid_shape_and_duplicate_ids(mutation):
    data = payload()
    mutation(data)
    with pytest.raises(InvalidWearEvidence):
        parse_wear_manifest(json.dumps(data))


@pytest.mark.parametrize("raw", [
    '{"schema_version":1,"schema_version":1,"records":[]}',
    '{"schema_version":1,"records":[{"id":"x","id":"y"}]}',
    "{}", "[]", "null", "not JSON", "x" * 262145,
])
def test_manifest_rejects_malformed_input(raw):
    with pytest.raises(InvalidWearEvidence):
        parse_wear_manifest(raw)


def test_loader_rejects_invalid_utf8_and_oversize(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(InvalidWearEvidence):
        load_wear_manifest(path)
    path.write_bytes(b"x" * 262145)
    with pytest.raises(InvalidWearEvidence):
        load_wear_manifest(path)


def test_parser_does_not_modify_corpus():
    before = CORPUS.read_bytes()
    assert len(load_wear_manifest(CORPUS)) == 2
    assert CORPUS.read_bytes() == before


@pytest.mark.parametrize("reason,counts", [
    ("synthetic-below-qualification-reference", (50, 50)),
    ("synthetic-at-or-above-qualification-reference", (49, 50)),
    ("different-event-domain", (1, 50)),
    ("unrecognized", (None, None)),
])
def test_assessment_rejects_inconsistent_claims(reason, counts):
    with pytest.raises(InvalidWearEvidence):
        WearComparison(reason, *counts)


@pytest.mark.parametrize("kwargs", [
    {"hardware_authorized": True},
    {"green_power_state_capability": True},
])
def test_no_qualification_report_can_authorize_power_control(kwargs):
    with pytest.raises(InvalidWearEvidence):
        WearComparison("synthetic-below-qualification-reference", 0, 50, **kwargs)


def test_typed_objects_are_required():
    with pytest.raises(TypeError):
        compare_synthetic_wear(None, sample(), expected_component_instance_id="module-A-generation-1")
    with pytest.raises(TypeError):
        compare_synthetic_wear(references()["module"], {"count": 0},
                               expected_component_instance_id="module-A-generation-1")
    with pytest.raises(InvalidWearEvidence):
        compare(expected="\n")


def test_reference_fields_are_immutable():
    with pytest.raises(AttributeError):
        references()["module"].rated_cycles = 500
    with pytest.raises(InvalidWearEvidence):
        replace(references()["module"], claim_kind="operational-wear-limit")
