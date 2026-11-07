"""Synthetic, offline IOS XR readback tests; no real Cisco hardware involved."""

from dataclasses import replace

import pytest

from green_transition_guard.experimental_optics_observation import (
    OpticsAssessment,
    UnsupportedOpticsObservation,
    assess_cisco_optics_pair,
    parse_cisco_optics_status,
)


HIGH = """Router# show controllers optics 0/0/0/1
Controller State: Up
Transport Admin State: In Service
Laser State: On
Power Mode: High
PID: SFP-1G-SX
Serial Number: TEST-SN-001
"""
LOW = """Router# show controllers optics 0/0/0/1
Controller State: Administratively Down
Transport Admin State: Out Of Service
Laser State: Off
Power Mode: Low
PID: SFP-1G-SX
Serial Number: TEST-SN-001
"""


def read(raw=HIGH, **kwargs):
    args = dict(
        device_id="lab-router-1", energy_object_id="energy-object-1",
        location="0/0/0/1", platform_model="NCS-57C3-MOD-SYS",
        software_release="26.3.1", sample_sequence=1,
    )
    args.update(kwargs)
    return parse_cisco_optics_status(raw, **args)


def test_high_mode_reported_from_consistent_four_field_tuple():
    result = read()
    assert result.reported_mode == "high"
    assert result.matches_documented_platform_release
    assert result.serial == "TEST-SN-001"


def test_low_mode_reported_from_consistent_four_field_tuple():
    result = read(LOW)
    assert result.reported_mode == "low"


def test_changed_report_is_not_proof_of_a_single_physical_cycle():
    result = assess_cisco_optics_pair(read(), read(LOW, sample_sequence=2))
    assert result.reason == "reported-state-change-without-edge-proof"
    assert result.reported_mode_changed is True
    assert result.quarantine and not result.safe_to_dispatch
    assert result.proven_physical_edges is None


def test_equal_readback_can_hide_two_or_more_intermediate_cycles():
    result = assess_cisco_optics_pair(read(), read(sample_sequence=2))
    assert result.reason == "same-reported-state-may-hide-cycles"
    assert result.reported_mode_changed is False
    assert result.proven_physical_edges is None and result.quarantine


@pytest.mark.parametrize("key,value", [
    ("Power Mode", "Low"),
    ("Laser State", "Off"),
    ("Controller State", "Administratively Down"),
    ("Transport Admin State", "Out Of Service"),
    ("Power Mode", "Unknown"),
])
def test_conflicting_or_unknown_fields_never_authorize_operations(key, value):
    raw = HIGH.replace(key + ": " + {
        "Power Mode": "High", "Laser State": "On", "Controller State": "Up",
        "Transport Admin State": "In Service",
    }[key], key + ": " + value)
    reading = read(raw)
    assert reading.reported_mode == "ambiguous"
    result = assess_cisco_optics_pair(read(), replace(reading, sample_sequence=2))
    assert result.reason == "unknown-or-conflicting-status"
    assert result.quarantine and result.proven_physical_edges is None


@pytest.mark.parametrize("bad", [
    HIGH.replace("Power Mode: High\n", ""),
    HIGH + "Power Mode: High\n",
    HIGH.replace("PID: SFP-1G-SX", "PID: "),
    HIGH.replace("Serial Number: TEST-SN-001\n", ""),
    HIGH.replace("show controllers optics 0/0/0/1", "show controllers optics 0/0/0/2"),
    HIGH + "Router# show controllers optics 0/0/0/1\n",
    HIGH + LOW,
    "x" * 1_048_577,
])
def test_missing_duplicate_mixed_and_oversized_input_rejected(bad):
    with pytest.raises(UnsupportedOpticsObservation):
        read(bad)


@pytest.mark.parametrize("bad", [
    {"location": "0/0/0/1; shutdown"},
    {"location": "0/0/0"},
    {"device_id": "   "},
    {"device_id": "device\nother"},
    {"software_release": "latest"},
    {"sample_sequence": True},
    {"sample_sequence": -1},
])
def test_invalid_metadata_rejected(bad):
    with pytest.raises(ValueError):
        read(**bad)


def test_replacement_or_location_change_never_merged():
    old = read()
    new = read(HIGH.replace("TEST-SN-001", "TEST-SN-002"), sample_sequence=2)
    assessment = assess_cisco_optics_pair(old, new)
    assert assessment.reason == "source-or-component-mismatch"
    assert assessment.proven_physical_edges is None


def test_stale_or_repeated_snapshot_rejected():
    assessment = assess_cisco_optics_pair(read(), read(sample_sequence=1))
    assert assessment.reason == "stale-or-repeated-sample"


@pytest.mark.parametrize("model,release", [
    ("UNVERIFIED-MODEL", "26.3.1"),
    ("NCS-57C3-MOD-SYS", "26.2.1"),
    ("NCS-57C3-MOD-SYS", "26.3.2"),
])
def test_unsupported_platform_assertion_is_diagnostic_only(model, release):
    old = read(platform_model=model, software_release=release)
    new = read(platform_model=model, software_release=release, sample_sequence=2)
    assert not old.matches_documented_platform_release
    assessment = assess_cisco_optics_pair(old, new)
    assert assessment.reason == "platform-or-release-not-verified"
    assert assessment.quarantine


@pytest.mark.parametrize("model", [
    "N540-24Z8Q2C-SYS", "N540-ACC-SYS", "N540X-ACC-SYS", "NCS-57C3-MOD-SYS"
])
def test_26_3_1_matches_documented_platform_release_list(model):
    assert read(platform_model=model).matches_documented_platform_release


def test_assessment_cannot_claim_hardware_authority():
    with pytest.raises(ValueError, match="never authorize"):
        OpticsAssessment("unsafe", True, quarantine=False)
    with pytest.raises(ValueError, match="never authorize"):
        OpticsAssessment("unsafe", True, safe_to_dispatch=True)
    with pytest.raises(ValueError, match="never authorize"):
        OpticsAssessment("unsafe", True, proven_physical_edges=1)


def test_multiline_indentation_and_crlf_are_supported():
    raw = "\r\n".join("    " + line for line in HIGH.strip().splitlines()) + "\r\n"
    assert read(raw).reported_mode == "high"


def test_optics_location_change_is_component_mismatch():
    old = read()
    new = read(HIGH.replace("0/0/0/1", "0/0/0/2"),
               location="0/0/0/2", sample_sequence=2)
    assert assess_cisco_optics_pair(old, new).reason == "source-or-component-mismatch"
