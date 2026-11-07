"""Evidence-scope regression tests. Inputs are documentation claims, not device data."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from green_transition_guard import Policy, Reason, TransitionGuard
from green_transition_guard.experimental_restriction_evidence import (
    InvalidRestrictionEvidence, MappingAssessment, RestrictionEvidence,
    TargetScope, assess_simulation_mapping, load_restriction_manifest,
    parse_restriction_manifest,
)


CORPUS = Path(__file__).resolve().parents[1] / "conformance" / "restriction-evidence.json"


def records():
    return {r.id: r for r in load_restriction_manifest(CORPUS)}


def target(r, **changes):
    fields = dict(platform=r.platform, component=r.component,
                  operation=r.operation, state=r.state, purpose=r.purpose)
    fields.update(changes)
    return TargetScope(**fields)


def base():
    return records()["juniper-mx204-psu-power-on-residence"]


def test_source_corpus_has_five_distinct_explicitly_scoped_entries():
    corpus = records()
    assert len(corpus) == 5
    assert all(v.source_url.startswith("https://") for v in corpus.values())
    assert all(v.purpose != "wear" for v in corpus.values())


def test_both_manufacturer_psu_instructions_are_exact_minimum_residence_claims():
    corpus = records()
    for state in ("on", "off"):
        r = corpus[f"juniper-mx204-psu-power-{state}-residence"]
        assert (r.component, r.operation, r.bound, r.value, r.unit) == (
            "power-supply", "physical-psu-power-switch", "min-residence", 60000,
            "milliseconds")
        result = assess_simulation_mapping(r, target(r))
        assert result.reason == "simulation-min-dwell-compatible"
        assert result.simulation_min_dwell_ms == 60000
        assert not result.hardware_authorized


@pytest.mark.parametrize("change,expected", [
    ({"platform": "NCS-57C3-MOD-SYS"}, "different-platform-or-component"),
    ({"component": "optical-transceiver"}, "different-platform-or-component"),
    ({"operation": "optics-controller-admin-sleep"}, "different-operation-or-state"),
    ({"state": "low"}, "different-operation-or-state"),
    ({"purpose": "wear"}, "different-purpose"),
    ({"purpose": "protocol-operation"}, "different-purpose"),
])
def test_psu_timing_cannot_be_reused_for_unrelated_hardware_or_purpose(change, expected):
    result = assess_simulation_mapping(base(), target(base(), **change))
    assert result.reason == expected and result.simulation_min_dwell_ms is None
    assert not result.hardware_authorized


def test_optics_readback_cannot_supply_a_numeric_restriction():
    optics = records()["cisco-ncs5500-optics-reported-high-mode"]
    result = assess_simulation_mapping(optics, target(optics))
    assert result.reason == "telemetry-has-no-restriction"
    assert result.simulation_min_dwell_ms is None
    assert not result.hardware_authorized


def test_xgspon_aware_parameter_has_no_fixed_value():
    r = records()["itu-xgspon-aware-minimum-parameter"]
    assert r.value_status == "configured" and r.value is None
    assert assess_simulation_mapping(r, target(r)).reason == "source-parameter-has-no-fixed-value"


def test_xgspon_maximum_low_power_residence_is_unsupported_by_current_guard():
    r = records()["itu-xgspon-low-power-maximum-parameter"]
    assert r.bound == "max-residence"
    result = assess_simulation_mapping(r, target(r))
    assert result.reason == "guard-does-not-model-maximum-residence"
    assert result.simulation_min_dwell_ms is None


def test_xgspon_parameter_is_not_an_optical_wear_rule():
    r = records()["itu-xgspon-aware-minimum-parameter"]
    result = assess_simulation_mapping(r, target(r, purpose="wear"))
    assert result.reason == "different-purpose"


@pytest.mark.parametrize("frames,expected", [
    (0, 0), (8, 1), (16, 2), (8000, 1000),
])
def test_exact_125us_frame_to_millisecond_conversion(frames, expected):
    standard = records()["itu-xgspon-aware-minimum-parameter"]
    populated = replace(standard, value_status="fixed", value=frames)
    result = assess_simulation_mapping(populated, target(populated))
    assert result.reason == "simulation-min-dwell-compatible"
    assert result.simulation_min_dwell_ms == expected and not result.hardware_authorized


@pytest.mark.parametrize("frames", [1, 2, 3, 4, 7, 9, 15, 7999])
def test_no_submillisecond_rounding_or_flooring(frames):
    r = records()["itu-xgspon-aware-minimum-parameter"]
    populated = replace(r, value_status="fixed", value=frames)
    result = assess_simulation_mapping(populated, target(populated))
    assert result.reason == "submillisecond-bound-is-unrepresentable"
    assert result.simulation_min_dwell_ms is None


@pytest.mark.parametrize("bad", [
    {"value": True}, {"value": -1}, {"value": 2**63}, {"value": 1.5},
    {"value": "60000"}, {"unit": "seconds"}, {"bound": "cycles"},
    {"purpose": "unknown"}, {"authority": "operator"},
    {"value_status": "configured"}, {"value": None},
    {"source_url": "http://example.com"}, {"source_url": "https://user:pass@example.com/file"},
    {"platform": "MX204\nNCS"}, {"id": " " * 4},
])
def test_invalid_evidence_rejected(bad):
    with pytest.raises(InvalidRestrictionEvidence):
        replace(base(), **bad)


@pytest.mark.parametrize("changes", [
    {"bound": "reported-state"},
    {"bound": "reported-state", "unit": "none"},
    {"bound": "reported-state", "value": None},
    {"bound": "reported-state", "value_status": "absent"},
])
def test_telemetry_cannot_accidentally_retain_a_bound(changes):
    with pytest.raises(InvalidRestrictionEvidence):
        replace(base(), **changes)


def test_unknown_value_cannot_be_misrepresented_as_a_fixed_constant():
    with pytest.raises(InvalidRestrictionEvidence):
        replace(base(), value=None)
    with pytest.raises(InvalidRestrictionEvidence):
        replace(base(), value_status="configured")


def test_deep_source_evidence_is_still_not_control_authority():
    with pytest.raises(InvalidRestrictionEvidence, match="cannot authorize"):
        MappingAssessment("simulation-min-dwell-compatible", 60000, hardware_authorized=True)
    with pytest.raises(InvalidRestrictionEvidence):
        MappingAssessment("scope-mismatch", 60000)
    with pytest.raises(InvalidRestrictionEvidence):
        MappingAssessment("simulation-min-dwell-compatible", None)
    with pytest.raises(InvalidRestrictionEvidence):
        MappingAssessment("simulation-min-dwell-compatible", True)


def test_wrong_input_types_rejected():
    with pytest.raises(TypeError):
        assess_simulation_mapping("manufacturer statement", target(base()))
    with pytest.raises(TypeError):
        assess_simulation_mapping(base(), "MX204")


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schema_version=2),
    lambda p: p.update(schema_version=True),
    lambda p: p.update(records=[]),
    lambda p: p.update(records=[*p["records"], p["records"][0]]),
    lambda p: p["records"][0].update(unknown_field=True),
    lambda p: p["records"][0].pop("source_url"),
    lambda p: p.update(extra="unexpected"),
])
def test_manifest_fails_closed_on_unknown_schema_fields_and_duplicate_ids(mutation):
    obj = json.loads(CORPUS.read_text(encoding="utf-8"))
    mutation(obj)
    with pytest.raises(InvalidRestrictionEvidence):
        parse_restriction_manifest(json.dumps(obj))


@pytest.mark.parametrize("raw", [
    '{"schema_version": 1, "schema_version": 1, "records": []}',
    '{"schema_version": 1, "records": [{"id": "x", "id": "x"}]}',
    '{', '', 'x' * 300000,
])
def test_malformed_duplicate_or_oversized_json_is_rejected(raw):
    with pytest.raises(InvalidRestrictionEvidence):
        parse_restriction_manifest(raw)


def test_loading_non_utf8_source_fails_cleanly(tmp_path):
    f = tmp_path / "invalid.json"
    f.write_bytes(b"\xff")
    with pytest.raises(InvalidRestrictionEvidence, match="UTF-8"):
        load_restriction_manifest(f)


def test_reading_oversized_file_fails_cleanly(tmp_path):
    f = tmp_path / "huge.json"
    f.write_bytes(b"x" * 262145)
    with pytest.raises(InvalidRestrictionEvidence, match="input limit"):
        load_restriction_manifest(f)


def test_only_read_only_local_manifest_and_static_comparison():
    assert set(records()) == {
        "juniper-mx204-psu-power-on-residence",
        "juniper-mx204-psu-power-off-residence",
        "cisco-ncs5500-optics-reported-high-mode",
        "itu-xgspon-aware-minimum-parameter",
        "itu-xgspon-low-power-maximum-parameter",
    }


def test_documented_psu_timing_fits_both_simulated_dwell_boundaries(tmp_path):
    # Simulated two-state power switch only. No PSU or remote command exists.
    claims = records()
    bounds = {}
    for state in ("on", "off"):
        evidence = claims[f"juniper-mx204-psu-power-{state}-residence"]
        assessment = assess_simulation_mapping(evidence, target(evidence))
        assert not assessment.hardware_authorized
        bounds[state] = assessment.simulation_min_dwell_ms
    p = Policy(
        states=("off", "on"), edges=(("off", "on"), ("on", "off")),
        min_dwell_ms=bounds, min_interval_ms=0, window_ms=240000,
        max_transitions=3,
    )
    guard = TransitionGuard.initialize(
        tmp_path / "fictional-psu.guard.json", device_id="fictional-psu",
        policy=p, initial_state="off", entered_at_ms=0,
    )
    def request(state, at):
        return guard.request(target=state, request_id=f"synthetic-{state}-{at}", at_ms=at)
    assert request("on", 59999).reason == Reason.MIN_DWELL
    assert request("on", 60000).allowed
    assert request("off", 119999).reason == Reason.MIN_DWELL
    assert request("off", 120000).allowed
    assert request("on", 179999).reason == Reason.MIN_DWELL
    assert request("on", 180000).allowed
