"""Event-specific optical timing experiments: synthetic inputs only."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from green_transition_guard.experimental_optical_cadence import (
    CadenceAssessment, CadenceTarget, InvalidCadenceEvidence,
    OpticalCadenceEvidence, SyntheticControlEvent, assess_synthetic_cadence,
    load_optical_cadence_manifest, parse_optical_cadence_manifest,
)


CORPUS = Path(__file__).resolve().parents[1] / "conformance" / "optical-cadence-evidence.json"


def records():
    return {r.id: r for r in load_optical_cadence_manifest(CORPUS)}


def glenair():
    return records()["glenair-050-315-tx-disable-assert-spacing"]


def cisco():
    return records()["cisco-ncs2000-svo-als-recovery-pulse-range"]


def target(evidence, **changes):
    fields = {name: getattr(evidence, name) for name in (
        "platform", "component", "operation", "event", "purpose")}
    fields.update(changes)
    return CadenceTarget(**fields)


def event(seq, at, name="tx-disable-assert"):
    return SyntheticControlEvent(sequence=seq, at_ms=at, event=name)


def raw():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def edited(**changes):
    source = raw()
    source["records"][0].update(changes)
    return json.dumps(source)


def test_source_records_identify_independent_scopes():
    a, b = glenair(), cisco()
    assert a.source_revision.endswith("2017-03-02")
    assert "Page 7" in a.source_locator
    assert a.minimum_ms == 10 and a.maximum_ms is None
    assert a.kind == "recommended-min-repeat" and a.purpose == "fault-reset-signal"
    assert b.minimum_ms == 60000 and b.maximum_ms == 300000
    assert b.kind == "documented-period-range" and b.purpose == "automatic-laser-safety"
    assert a.operation != b.operation


def test_duplicate_event_type_spacing_below_ten_ms():
    a = glenair()
    # Deassertion between the two assertions cannot restart the 10 ms clock.
    trace = [event(0, 0), event(1, 1, "tx-disable-deassert"), event(2, 9)]
    r = assess_synthetic_cadence(a, target(a), trace)
    assert (r.reason, r.matching_events, r.shortest_gap_ms, r.violations) == (
        "synthetic-spacing-below-recommendation", 2, 9, 1)
    assert not r.hardware_authorized


def test_repeat_boundary_at_ten_ms():
    a = glenair()
    trace = [event(0, 0), event(1, 1, "tx-disable-deassert"), event(2, 10)]
    r = assess_synthetic_cadence(a, target(a), trace)
    assert r.reason == "synthetic-spacing-meets-recommendation"
    assert r.violations == 0 and r.shortest_gap_ms == 10
    assert not r.hardware_authorized


def test_multiple_assertions_count_only_relevant_events():
    a = glenair()
    trace = [event(0, 10), event(1, 12, "tx-disable-deassert"),
             event(2, 19), event(3, 20, "tx-disable-deassert"), event(4, 30)]
    r = assess_synthetic_cadence(a, target(a), trace)
    assert r.violations == 1 and r.matching_events == 3
    assert r.shortest_gap_ms == 9


@pytest.mark.parametrize("samples,count", [([], 0), ([event(0, 3)], 1),
                                          ([event(0, 0, "tx-disable-deassert")], 0)])
def test_insufficient_events_are_undecidable(samples, count):
    a = glenair()
    r = assess_synthetic_cadence(a, target(a), samples)
    assert (r.reason, r.matching_events, r.shortest_gap_ms) == (
        "insufficient-repeated-events", count, None)


@pytest.mark.parametrize("field,value,reason", [
    ("platform", "Cisco NCS 2000 SVO 12.3.x", "different-platform-or-component"),
    ("component", "different module", "different-platform-or-component"),
    ("operation", "controller optics shutdown", "different-operation-or-event"),
    ("event", "tx-disable-deassert", "different-operation-or-event"),
    ("purpose", "automatic-laser-safety", "different-purpose"),
])
def test_scope_mismatch_never_uses_timing(field, value, reason):
    a = glenair()
    r = assess_synthetic_cadence(a, target(a, **{field: value}), [event(0, 0), event(1, 1)])
    assert r.reason == reason and r.shortest_gap_ms is None
    assert r.violations == 0 and not r.hardware_authorized


@pytest.mark.parametrize("interval", [59000, 60000, 300000, 310000])
def test_cisco_reported_config_range_cannot_validate_observed_pulses(interval):
    b = cisco()
    trace = [event(0, 0, b.event), event(1, interval, b.event)]
    r = assess_synthetic_cadence(b, target(b), trace)
    assert r.reason == "effective-period-and-event-coverage-unknown"
    assert r.shortest_gap_ms == interval and r.violations == 0
    assert not r.hardware_authorized


def test_even_cisco_min_range_cannot_be_applied_as_guard_dwell():
    b = cisco()
    assert b.minimum_ms == 60000
    assert b.event == "als-recovery-pulse-start"
    assert b.kind != glenair().kind
    assert assess_synthetic_cadence(b, target(b), [event(0, 0, b.event),
                                                   event(1, 60000, b.event)]).reason == (
        "effective-period-and-event-coverage-unknown")


@pytest.mark.parametrize("samples", [
    [event(0, 3), event(1, 2)],
    [event(0, 3), event(0, 4)],
    [event(1, 1), event(0, 2)],
    [event(0, 0), {"sequence": 1, "at_ms": 2, "event": "tx-disable-assert"}],
    [event(0, 0)] * 513,
    "not a sequence",
])
def test_ambiguous_synthetic_trace_fails(samples):
    a = glenair()
    with pytest.raises(InvalidCadenceEvidence):
        assess_synthetic_cadence(a, target(a), samples)


@pytest.mark.parametrize("field,value", [
    ("sequence", -1), ("sequence", True), ("sequence", 1.4),
    ("at_ms", -1), ("at_ms", True), ("at_ms", 2**63),
    ("event", " "), ("event", "tx-disable-assert\nother"),
])
def test_invalid_synthetic_events_fail(field, value):
    fields = {"sequence": 1, "at_ms": 7, "event": "tx-disable-assert"}
    fields[field] = value
    with pytest.raises(InvalidCadenceEvidence):
        SyntheticControlEvent(**fields)


def test_assessment_cannot_authorize_hardware():
    with pytest.raises(InvalidCadenceEvidence, match="cannot authorize"):
        CadenceAssessment("synthetic-spacing-meets-recommendation", 2, 10, 0,
                          hardware_authorized=True)


@pytest.mark.parametrize("field,value", [
    ("authority", "self-attested"), ("kind", "wear-cycle-budget"),
    ("purpose", "wear"), ("minimum", 0), ("minimum", -1),
    ("minimum", True), ("minimum", 1.5), ("minimum", 2**64),
    ("maximum", 15), ("unit", "microseconds"),
    ("source_url", "http://example.org"), ("source_url", "https://bob:secret@example.org/x"),
    ("source_url", "https://example.org/\npath"),
    ("source_url", "https://[invalid-ipv6"),
    ("source_revision", " "), ("source_locator", "p\n7"),
    ("component", " "),
])
def test_invalid_vendor_claims_rejected(field, value):
    with pytest.raises(InvalidCadenceEvidence):
        parse_optical_cadence_manifest(edited(**{field: value}))


@pytest.mark.parametrize("minimum,maximum", [(0, 300), (300, 60), (60, None),
                                              (60, True), (60, 1.5), (60, 2**63)])
def test_config_range_must_have_positive_sorted_bounds(minimum, maximum):
    data = raw()
    data["records"][1]["minimum"] = minimum
    data["records"][1]["maximum"] = maximum
    with pytest.raises(InvalidCadenceEvidence):
        parse_optical_cadence_manifest(json.dumps(data))


@pytest.mark.parametrize("mutation", [
    lambda data: data.pop("schema_version"),
    lambda data: data.update(schema_version=True),
    lambda data: data.update(schema_version=2),
    lambda data: data.update(records=[]),
    lambda data: data.update(records=data["records"] * 17),
    lambda data: data["records"].append(data["records"][0]),
    lambda data: data["records"][0].pop("purpose"),
    lambda data: data["records"][0].update(extra="ignored?"),
])
def test_corpus_shape_and_ids_are_strict(mutation):
    data = raw()
    mutation(data)
    with pytest.raises(InvalidCadenceEvidence):
        parse_optical_cadence_manifest(json.dumps(data))


@pytest.mark.parametrize("payload", [
    '{"schema_version":1, "schema_version":1, "records":[]}',
    '{"schema_version":1, "records":[{"id":"a", "id":"b"}]}',
    "{}", "[]", "null", "invalid JSON", "x" * 262145,
])
def test_malformed_payloads_fail(payload):
    with pytest.raises(InvalidCadenceEvidence):
        parse_optical_cadence_manifest(payload)


def test_loader_rejects_non_utf8_and_oversized_input(tmp_path):
    p = tmp_path / "bad.json"
    p.write_bytes(b"\xff\x00")
    with pytest.raises(InvalidCadenceEvidence):
        load_optical_cadence_manifest(p)
    p.write_bytes(b"x" * 262145)
    with pytest.raises(InvalidCadenceEvidence):
        load_optical_cadence_manifest(p)


def test_loader_roundtrip_is_read_only():
    contents = CORPUS.read_bytes()
    assert len(load_optical_cadence_manifest(CORPUS)) == 2
    assert CORPUS.read_bytes() == contents
