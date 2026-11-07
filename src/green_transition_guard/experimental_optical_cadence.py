"""Offline research on repeated optical control events.

This module evaluates *synthetic* event timestamps against vendor-documented
control timing. Source URLs and platform names are citations and assertions,
not authenticated capabilities. A positive result never authorizes dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit


CadenceKind = Literal["recommended-min-repeat", "documented-period-range"]
CadenceUnit = Literal["milliseconds", "seconds"]
CadencePurpose = Literal["fault-reset-signal", "automatic-laser-safety"]
CadenceAuthority = Literal["manufacturer-product-brief", "vendor-config-guide"]
_MAX_MS = 2**63 - 1
_MAX_BYTES = 262_144
_MAX_RECORDS = 32
_MAX_EVENTS = 512
_RECORD_KEYS = frozenset({
    "id", "source_url", "source_revision", "source_locator", "authority",
    "platform", "component", "operation", "event", "purpose", "kind",
    "minimum", "maximum", "unit",
})


class InvalidCadenceEvidence(ValueError):
    """A timing claim or synthetic trace cannot be evaluated unambiguously."""


def _label(value: str, field: str) -> str:
    if (not isinstance(value, str) or not value or value.strip() != value or
            len(value) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise InvalidCadenceEvidence(f"invalid {field}")
    return value


def _milliseconds(value: int, unit: CadenceUnit) -> int:
    if type(value) is not int or value <= 0 or unit not in ("milliseconds", "seconds"):
        raise InvalidCadenceEvidence("invalid positive interval")
    multiplier = 1 if unit == "milliseconds" else 1000
    if value > _MAX_MS // multiplier:
        raise InvalidCadenceEvidence("interval exceeds supported time range")
    return value * multiplier


@dataclass(frozen=True)
class OpticalCadenceEvidence:
    id: str
    source_url: str
    source_revision: str
    source_locator: str
    authority: CadenceAuthority
    platform: str
    component: str
    operation: str
    event: str
    purpose: CadencePurpose
    kind: CadenceKind
    minimum: int
    maximum: int | None
    unit: CadenceUnit

    def __post_init__(self) -> None:
        for name in (
            "id", "source_url", "source_revision", "source_locator", "platform",
            "component", "operation", "event",
        ):
            _label(getattr(self, name), name)
        try:
            url = urlsplit(self.source_url)
        except ValueError as exc:
            raise InvalidCadenceEvidence("malformed source URL") from exc
        if (url.scheme != "https" or not url.hostname or url.username or url.password or
                any(ch.isspace() for ch in self.source_url)):
            raise InvalidCadenceEvidence("source URL must be HTTPS and have no credentials")
        if self.authority not in ("manufacturer-product-brief", "vendor-config-guide"):
            raise InvalidCadenceEvidence("unknown evidence authority")
        if self.purpose not in ("fault-reset-signal", "automatic-laser-safety"):
            raise InvalidCadenceEvidence("unknown evidence purpose")
        if self.kind not in ("recommended-min-repeat", "documented-period-range"):
            raise InvalidCadenceEvidence("unknown cadence type")
        minimum_ms = _milliseconds(self.minimum, self.unit)
        if self.kind == "recommended-min-repeat":
            if self.maximum is not None:
                raise InvalidCadenceEvidence("minimum spacing has no maximum")
        else:
            if self.maximum is None or _milliseconds(self.maximum, self.unit) < minimum_ms:
                raise InvalidCadenceEvidence("invalid documented period range")

    @property
    def minimum_ms(self) -> int:
        return _milliseconds(self.minimum, self.unit)

    @property
    def maximum_ms(self) -> int | None:
        return None if self.maximum is None else _milliseconds(self.maximum, self.unit)


@dataclass(frozen=True)
class CadenceTarget:
    platform: str
    component: str
    operation: str
    event: str
    purpose: CadencePurpose

    def __post_init__(self) -> None:
        for name in ("platform", "component", "operation", "event"):
            _label(getattr(self, name), name)
        if self.purpose not in ("fault-reset-signal", "automatic-laser-safety"):
            raise InvalidCadenceEvidence("unknown target purpose")


@dataclass(frozen=True)
class SyntheticControlEvent:
    sequence: int
    at_ms: int
    event: str

    def __post_init__(self) -> None:
        _label(self.event, "event")
        if (type(self.sequence) is not int or self.sequence < 0 or
                type(self.at_ms) is not int or not 0 <= self.at_ms <= _MAX_MS):
            raise InvalidCadenceEvidence("invalid synthetic event index or timestamp")


@dataclass(frozen=True)
class CadenceAssessment:
    reason: str
    matching_events: int
    shortest_gap_ms: int | None
    violations: int
    hardware_authorized: bool = False

    def __post_init__(self) -> None:
        if self.hardware_authorized:
            raise InvalidCadenceEvidence("synthetic evidence cannot authorize hardware")
        if (type(self.matching_events) is not int or self.matching_events < 0 or
                type(self.violations) is not int or self.violations < 0 or
                (self.shortest_gap_ms is not None and
                 (type(self.shortest_gap_ms) is not int or self.shortest_gap_ms < 0))):
            raise InvalidCadenceEvidence("invalid cadence assessment")


def assess_synthetic_cadence(
    evidence: OpticalCadenceEvidence,
    target: CadenceTarget,
    events: list[SyntheticControlEvent] | tuple[SyntheticControlEvent, ...],
) -> CadenceAssessment:
    """Check repeated *same* events, ignoring intervening event types.

    Events are local synthetic inputs, not verified physical/driver telemetry.
    A documented configuration range never establishes the active setting.
    """
    if not isinstance(evidence, OpticalCadenceEvidence) or not isinstance(target, CadenceTarget):
        raise TypeError("typed evidence and target required")
    if not isinstance(events, (list, tuple)) or len(events) > _MAX_EVENTS:
        raise InvalidCadenceEvidence("bounded synthetic event sequence required")
    previous_sequence = -1
    previous_time = -1
    for event in events:
        if not isinstance(event, SyntheticControlEvent):
            raise InvalidCadenceEvidence("typed synthetic events required")
        if event.sequence <= previous_sequence or event.at_ms < previous_time:
            raise InvalidCadenceEvidence("event sequence or time is out of order")
        previous_sequence, previous_time = event.sequence, event.at_ms

    if evidence.platform != target.platform or evidence.component != target.component:
        return CadenceAssessment("different-platform-or-component", 0, None, 0)
    if evidence.operation != target.operation or evidence.event != target.event:
        return CadenceAssessment("different-operation-or-event", 0, None, 0)
    if evidence.purpose != target.purpose:
        return CadenceAssessment("different-purpose", 0, None, 0)

    timestamps = [event.at_ms for event in events if event.event == evidence.event]
    if len(timestamps) < 2:
        return CadenceAssessment("insufficient-repeated-events", len(timestamps), None, 0)
    intervals = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
    shortest = min(intervals)
    if evidence.kind == "documented-period-range":
        # Range of available or reported device parameters. The actual setting,
        # pulse provenance, and completeness of observed events are all unknown.
        return CadenceAssessment("effective-period-and-event-coverage-unknown",
                                 len(timestamps), shortest, 0)
    violations = sum(gap < evidence.minimum_ms for gap in intervals)
    return CadenceAssessment(
        "synthetic-spacing-below-recommendation" if violations else
        "synthetic-spacing-meets-recommendation",
        len(timestamps), shortest, violations,
    )


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCadenceEvidence("duplicate JSON field")
        result[key] = value
    return result


def parse_optical_cadence_manifest(raw: str) -> tuple[OpticalCadenceEvidence, ...]:
    """Strict parser for a small manually reviewed reference corpus."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BYTES:
        raise InvalidCadenceEvidence("invalid or oversized cadence corpus")
    try:
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_fields)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidCadenceEvidence("malformed cadence manifest") from exc
    if (not isinstance(data, dict) or set(data) != {"schema_version", "records"} or
            type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise InvalidCadenceEvidence("unsupported cadence schema")
    rows = data["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_RECORDS:
        raise InvalidCadenceEvidence("invalid cadence record count")
    seen: set[str] = set()
    records = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _RECORD_KEYS:
            raise InvalidCadenceEvidence("invalid cadence record shape")
        record = OpticalCadenceEvidence(**row)
        if record.id in seen:
            raise InvalidCadenceEvidence("duplicate cadence record ID")
        seen.add(record.id)
        records.append(record)
    return tuple(records)


def load_optical_cadence_manifest(path: str | Path) -> tuple[OpticalCadenceEvidence, ...]:
    """Load only a deliberately selected local corpus; never fetch a URL."""
    path = Path(path)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        raise InvalidCadenceEvidence("cadence corpus exceeds input limit")
    try:
        return parse_optical_cadence_manifest(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InvalidCadenceEvidence("cadence corpus is not UTF-8") from exc
