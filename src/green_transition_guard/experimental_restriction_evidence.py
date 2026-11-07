"""Scope checks for source-backed hardware restriction research.

The records are manually transcribed research claims, not authenticated device
capabilities. The only positive result is compatibility with *simulation*
policy semantics. No result authorizes hardware control.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit


Bound = Literal["min-residence", "max-residence", "reported-state"]
Unit = Literal["milliseconds", "125us-frames", "none"]
ValueStatus = Literal["fixed", "configured", "absent"]
Purpose = Literal["maintenance", "protocol-operation", "monitoring", "wear"]
Authority = Literal["manufacturer-instruction", "standard-parameter", "device-observation"]
_MAX_RECORDS = 128
_MAX_BYTES = 262_144
_MAX_VALUE = 2**63 - 1
_RECORD_KEYS = frozenset({
    "id", "source_url", "authority", "platform", "component", "operation",
    "state", "bound", "value", "unit", "value_status", "purpose",
})


class InvalidRestrictionEvidence(ValueError):
    """The supplied evidence entry or corpus is malformed."""


def _identifier(value: str, field: str) -> str:
    if (
        not isinstance(value, str) or not value or value.strip() != value or
        len(value) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise InvalidRestrictionEvidence(f"invalid {field}")
    return value


@dataclass(frozen=True)
class RestrictionEvidence:
    id: str
    source_url: str
    authority: Authority
    platform: str
    component: str
    operation: str
    state: str
    bound: Bound
    value: int | None
    unit: Unit
    value_status: ValueStatus
    purpose: Purpose

    def __post_init__(self) -> None:
        for field in ("id", "source_url", "platform", "component", "operation", "state"):
            _identifier(getattr(self, field), field)
        url = urlsplit(self.source_url)
        if (url.scheme != "https" or not url.hostname or url.username or
                url.password or any(ch.isspace() for ch in self.source_url)):
            raise InvalidRestrictionEvidence("source_url must be a public HTTPS source")
        if self.authority not in ("manufacturer-instruction", "standard-parameter", "device-observation"):
            raise InvalidRestrictionEvidence("unknown evidence authority")
        if self.purpose not in ("maintenance", "protocol-operation", "monitoring", "wear"):
            raise InvalidRestrictionEvidence("unknown evidence purpose")
        if self.bound not in ("min-residence", "max-residence", "reported-state"):
            raise InvalidRestrictionEvidence("unknown restriction bound")
        if self.unit not in ("milliseconds", "125us-frames", "none"):
            raise InvalidRestrictionEvidence("unknown restriction unit")
        if self.value_status not in ("fixed", "configured", "absent"):
            raise InvalidRestrictionEvidence("unknown numeric value status")
        if self.value is not None and (type(self.value) is not int or not 0 <= self.value <= _MAX_VALUE):
            raise InvalidRestrictionEvidence("invalid numeric restriction value")
        if self.bound == "reported-state":
            if self.unit != "none" or self.value is not None or self.value_status != "absent":
                raise InvalidRestrictionEvidence("reported states have no numeric bound")
        else:
            if self.unit == "none" or self.value_status == "absent":
                raise InvalidRestrictionEvidence("missing restriction units/status")
            if (self.value_status == "fixed") != (self.value is not None):
                raise InvalidRestrictionEvidence("fixed bounds require a value; configured bounds remain unknown")


@dataclass(frozen=True)
class TargetScope:
    platform: str
    component: str
    operation: str
    state: str
    purpose: Purpose

    def __post_init__(self) -> None:
        for field in ("platform", "component", "operation", "state"):
            _identifier(getattr(self, field), field)
        if self.purpose not in ("maintenance", "protocol-operation", "monitoring", "wear"):
            raise InvalidRestrictionEvidence("unknown target purpose")


@dataclass(frozen=True)
class MappingAssessment:
    reason: str
    simulation_min_dwell_ms: int | None
    hardware_authorized: bool = False

    def __post_init__(self) -> None:
        if self.hardware_authorized:
            raise InvalidRestrictionEvidence("evidence mapping cannot authorize hardware")
        if self.reason == "simulation-min-dwell-compatible":
            if (type(self.simulation_min_dwell_ms) is not int or
                    not 0 <= self.simulation_min_dwell_ms <= _MAX_VALUE):
                raise InvalidRestrictionEvidence("compatible simulation mapping needs an integer bound")
        elif self.simulation_min_dwell_ms is not None:
            raise InvalidRestrictionEvidence("only compatible simulation rules can return a value")


def assess_simulation_mapping(evidence: RestrictionEvidence, target: TargetScope) -> MappingAssessment:
    """Check semantic shape and exact scope, without trusting the source claim.

    Even a compatible numerical value is a proposed *model input*. An operator
    must independently verify source, hardware identity and applicability.
    """
    if not isinstance(evidence, RestrictionEvidence) or not isinstance(target, TargetScope):
        raise TypeError("RestrictionEvidence and TargetScope are required")
    if evidence.platform != target.platform or evidence.component != target.component:
        return MappingAssessment("different-platform-or-component", None)
    if evidence.operation != target.operation or evidence.state != target.state:
        return MappingAssessment("different-operation-or-state", None)
    if evidence.purpose != target.purpose:
        return MappingAssessment("different-purpose", None)
    if evidence.bound == "reported-state":
        return MappingAssessment("telemetry-has-no-restriction", None)
    if evidence.bound != "min-residence":
        return MappingAssessment("guard-does-not-model-maximum-residence", None)
    if evidence.value is None:
        return MappingAssessment("source-parameter-has-no-fixed-value", None)
    if evidence.unit == "milliseconds":
        value_ms = evidence.value
    elif evidence.unit == "125us-frames":
        # Eight PHY frames are exactly one millisecond. Rounding down would
        # weaken the bound, while rounding up changes the source semantics.
        if evidence.value % 8:
            return MappingAssessment("submillisecond-bound-is-unrepresentable", None)
        value_ms = evidence.value // 8
    else:
        return MappingAssessment("unsupported-unit", None)
    return MappingAssessment("simulation-min-dwell-compatible", value_ms)


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise InvalidRestrictionEvidence("duplicate JSON field")
        result[name] = value
    return result


def parse_restriction_manifest(raw: str) -> tuple[RestrictionEvidence, ...]:
    """Parse a small, self-contained research corpus; no URL is fetched."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BYTES:
        raise InvalidRestrictionEvidence("evidence corpus exceeds input limit")
    try:
        payload = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidRestrictionEvidence("invalid evidence JSON") from exc
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "records"} or
            type(payload["schema_version"]) is not int or payload["schema_version"] != 1):
        raise InvalidRestrictionEvidence("unsupported evidence manifest schema")
    rows = payload["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_RECORDS:
        raise InvalidRestrictionEvidence("invalid evidence record count")
    out = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _RECORD_KEYS:
            raise InvalidRestrictionEvidence("invalid evidence record fields")
        record = RestrictionEvidence(**row)
        if record.id in seen:
            raise InvalidRestrictionEvidence("duplicate evidence record ID")
        seen.add(record.id)
        out.append(record)
    return tuple(out)


def load_restriction_manifest(path: str | Path) -> tuple[RestrictionEvidence, ...]:
    """Read only an explicitly selected local UTF-8 corpus."""
    path = Path(path)
    with path.open("rb") as stream:
        payload = stream.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        raise InvalidRestrictionEvidence("evidence corpus exceeds input limit")
    try:
        return parse_restriction_manifest(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InvalidRestrictionEvidence("evidence corpus is not UTF-8") from exc
