"""Semantics tests; these do NOT replace pyang/yanglint compilation."""

from pathlib import Path
import json
import subprocess
import sys

import pytest

from green_transition_guard.model import Policy
from green_transition_guard.experimental_time import Bounds, TimeEvidence
from green_transition_guard.experimental_hardware import SimulatedActuator, InjectedCrash
from green_transition_guard.experimental_evidence_hardware import EvidenceHardwareExperiment
from green_transition_guard.experimental_yang_projection import (
    project_experimental_ietf_json, YANG_MODULE, BASE_REVISION, MAX_U64,
)


IDENTITIES = {
    "on": "ietf-power-and-energy:power-state-on",
    "sleep": "ietf-power-and-energy:power-state-sleep",
}


def t(ms, boot="boot-a", absolute=None):
    return TimeEvidence(boot, Bounds(ms, ms),
                        None if absolute is None else Bounds(absolute, absolute + 1))


def setup(tmp_path, *, max_transitions=2, window=100, dwell=3):
    policy = Policy(
        states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
        min_dwell_ms={"on": dwell, "sleep": dwell}, min_interval_ms=1,
        window_ms=window, max_transitions=max_transitions,
    )
    actuator = SimulatedActuator.initialize(tmp_path / "hw.json",
                                            energy_object_id="unit-1", initial_state="on")
    guard = EvidenceHardwareExperiment.initialize(tmp_path / "guard.json",
                                                   actuator=actuator, policy=policy,
                                                   energy_object_id="unit-1", evidence=t(0))
    return guard, actuator


def safety(experiment, identities=None):
    data = project_experimental_ietf_json(experiment,
                                           IDENTITIES if identities is None else identities)
    base = data["ietf-power-and-energy:energy-objects"]["energy-object"]
    assert len(base) == 1 and base[0]["id"] == "unit-1"
    assert set(base[0]) == {"id", f"{YANG_MODULE}:transition-safety"}
    return base[0][f"{YANG_MODULE}:transition-safety"]


def test_idle_instance_is_read_only_and_uses_rfc7951_uint64_strings(tmp_path):
    guard, _ = setup(tmp_path)
    s = safety(guard)
    assert s["operation-phase"] == "idle"
    assert s["simulated-ledger-status"] == "matched-simulation"
    assert s["clock-evidence-kind"] == "local-epoch-bounds"
    assert s["confirmed-edge-count"] == "0"
    assert "quarantine-reason" not in s
    assert s["applied-limits"] == {
        "minimum-interval-ms": "1", "window-ms": "100", "maximum-transitions": "2",
        "dwell-restriction": [
            {"state": IDENTITIES["on"], "minimum-dwell-ms": "3"},
            {"state": IDENTITIES["sleep"], "minimum-dwell-ms": "3"},
        ],
    }
    assert "admin" not in str(s) and "oper" not in s
    assert json.loads(json.dumps(s)) == s


def test_projection_does_not_mutate_existing_journals(tmp_path):
    guard, actuator = setup(tmp_path)
    before = (tmp_path / "guard.json").read_bytes(), (tmp_path / "hw.json").read_bytes()
    safety(guard)
    after = (tmp_path / "guard.json").read_bytes(), (tmp_path / "hw.json").read_bytes()
    assert before == after


def test_prepare_and_acknowledgment_are_not_reported_as_verified(tmp_path):
    guard, actuator = setup(tmp_path)
    assert guard.prepare(op_id="request-a", target="sleep", evidence=t(3)).reason == "prepared"
    s = safety(guard)
    assert s["operation-phase"] == "prepared"
    assert s["confirmed-edge-count"] == "0"
    assert s["simulated-ledger-status"] == "matched-simulation"
    assert guard.dispatch(op_id="request-a", evidence=t(4)).reason == "acknowledged"
    s = safety(guard)
    assert s["operation-phase"] == "acknowledged"
    assert s["simulated-ledger-status"] == "pending-confirmation-simulation"
    assert s["confirmed-edge-count"] == "0"
    assert guard.reconcile(evidence=t(5)).reason == "verified"
    assert safety(guard)["confirmed-edge-count"] == "1"
    assert safety(guard)["simulated-ledger-status"] == "matched-simulation"


def test_dispatch_crash_retains_pending_and_denies_optimistic_count(tmp_path):
    guard, actuator = setup(tmp_path)
    guard.prepare(op_id="request-a", target="sleep", evidence=t(3))
    with pytest.raises(InjectedCrash):
        guard.dispatch(op_id="request-a", evidence=t(4), crash_at="after_effect")
    s = safety(guard)
    assert s["operation-phase"] == "may-have-dispatched"
    assert s["simulated-ledger-status"] == "pending-confirmation-simulation"
    assert s["confirmed-edge-count"] == "0"


def test_external_edge_does_not_claim_attestation(tmp_path):
    guard, actuator = setup(tmp_path)
    actuator.external_edge(event_id="external-1", target="sleep")
    s = safety(guard)
    assert s["simulated-ledger-status"] == "divergent-simulation"
    assert s["confirmed-edge-count"] == "0"
    assert guard.prepare(op_id="request-a", target="sleep", evidence=t(5)).reason == "physical-divergence"
    s = safety(guard)
    assert s["quarantine-reason"] == "physical-divergence"


def test_absolute_time_is_only_an_assertion(tmp_path):
    guard, actuator = setup(tmp_path)
    assert safety(guard)["clock-evidence-kind"] == "local-epoch-bounds"
    assert guard.prepare(op_id="same", target="on", evidence=t(4, absolute=1000)).reason == "no-change"
    assert safety(guard)["clock-evidence-kind"] == "asserted-absolute-bounds"


@pytest.mark.parametrize("bad", [
    {},
    {"on": IDENTITIES["on"]},
    {"on": "on", "sleep": IDENTITIES["sleep"]},
    {"on": IDENTITIES["on"], "sleep": IDENTITIES["on"]},
    {"on": "bad:multiple:colons", "sleep": IDENTITIES["sleep"]},
    {"on": "1bad:state", "sleep": IDENTITIES["sleep"]},
    {"on": IDENTITIES["on"], "sleep": IDENTITIES["sleep"], "third": "xx:zz"},
])
def test_incomplete_or_invalid_identityrefs_are_rejected(tmp_path, bad):
    guard, _ = setup(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        safety(guard, bad)


def test_uint64_overflow_rejected_before_encoding(tmp_path):
    guard, _ = setup(tmp_path, max_transitions=MAX_U64 + 1)
    with pytest.raises(ValueError, match="uint64"):
        safety(guard)


def test_yang_module_is_separate_read_only_augmentation():
    src = (Path(__file__).parents[1] / "yang" /
           "green-transition-guard-experimental@2026-11-04.yang").read_text()
    assert 'import ietf-power-and-energy {' in src
    assert 'revision-date 2026-11-01;' in src
    assert 'augment "/eo:energy-objects/eo:energy-object"' in src
    assert 'config false;' in src
    assert 'base eo:power-state;' in src
    assert 'leaf admin {' not in src and 'leaf oper {' not in src
    assert 'namespace "urn:example:' in src


def test_yang_compile_gate_fails_without_official_imported_module(tmp_path):
    script = Path(__file__).parents[1] / "scripts" / "validate_yang.py"
    result = subprocess.run([sys.executable, str(script), "--modules", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "UNVERIFIED" in result.stderr
