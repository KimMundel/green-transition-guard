"""Offline scope checks for published industrial pulsed-laser lifetime claims.

Comparisons use synthetic histories. Published expected life is not an operating
limit, a GREEN capability, or authority to activate physical hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit


_MAX_BYTES = 131_072
_MAX_RECORDS = 32
_MAX_COUNT = 2**63 - 1
_FIELDS = frozenset({
    "id", "source_url", "source_locator", "product_model", "component_kind",
    "event", "claim_kind", "pulse_width_ms", "pulse_frequency_hz",
    "duty_cycle_percent", "case_temperature_c", "table_peak_power_w",
    "summary_peak_power_w", "expected_shots",
})


class InvalidPulsedLifetimeEvidence(ValueError):
    """Unknown scope, malformed input, or inconsistent assessment."""


def _label(value: str, field: str) -> str:
    if (not isinstance(value, str) or not value or value.strip() != value or
            len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise InvalidPulsedLifetimeEvidence(f"invalid {field}")
    return value


def _integer(value: int, field: str, *, min_value: int = 0,
             max_value: int = _MAX_COUNT) -> int:
    if type(value) is not int or not min_value <= value <= max_value:
        raise InvalidPulsedLifetimeEvidence(f"invalid {field}")
    return value


def _mode(width: int, frequency: int, duty: int, temperature: int) -> None:
    _integer(width, "pulse width", min_value=1, max_value=1_000_000)
    _integer(frequency, "pulse frequency", min_value=1, max_value=1_000_000)
    _integer(duty, "duty percent", min_value=1, max_value=100)
    _integer(temperature, "case temperature", max_value=150)
    if width * frequency != duty * 10:
        raise InvalidPulsedLifetimeEvidence("inconsistent pulse duty cycle")


@dataclass(frozen=True)
class PulsedLifetimeClaim:
    id: str
    source_url: str
    source_locator: str
    product_model: str
    component_kind: str
    event: str
    claim_kind: str
    pulse_width_ms: int
    pulse_frequency_hz: int
    duty_cycle_percent: int
    case_temperature_c: int
    table_peak_power_w: int
    summary_peak_power_w: int
    expected_shots: int

    def __post_init__(self) -> None:
        for field in ("id", "source_url", "source_locator", "product_model"):
            _label(getattr(self, field), field)
        try:
            url = urlsplit(self.source_url)
        except ValueError as exc:
            raise InvalidPulsedLifetimeEvidence("malformed source URL") from exc
        if (url.scheme != "https" or not url.hostname or url.username or url.password or
                any(c.isspace() for c in self.source_url)):
            raise InvalidPulsedLifetimeEvidence("source URL must be public HTTPS")
        if self.component_kind != "industrial-qcw-laser-diode-stack":
            raise InvalidPulsedLifetimeEvidence("unsupported component kind")
        if (self.event != "industrial-qcw-optical-shot" or
                self.claim_kind != "mode-dependent-expected-lifetime-shots"):
            raise InvalidPulsedLifetimeEvidence("unsupported event or claim meaning")
        _mode(self.pulse_width_ms, self.pulse_frequency_hz,
              self.duty_cycle_percent, self.case_temperature_c)
        _integer(self.table_peak_power_w, "table peak power", min_value=1)
        _integer(self.summary_peak_power_w, "summary peak power", min_value=1)
        _integer(self.expected_shots, "expected shots", min_value=1)

    @property
    def source_conditions_consistent(self) -> bool:
        return self.table_peak_power_w == self.summary_peak_power_w


@dataclass(frozen=True)
class SyntheticPulseHistory:
    product_model: str
    component_instance_id: str
    component_kind: str
    event: str
    pulse_width_ms: int
    pulse_frequency_hz: int
    duty_cycle_percent: int
    case_temperature_c: int
    observed_shots: int
    coverage: str

    def __post_init__(self) -> None:
        for field in ("product_model", "component_instance_id", "component_kind", "event"):
            _label(getattr(self, field), field)
        _mode(self.pulse_width_ms, self.pulse_frequency_hz,
              self.duty_cycle_percent, self.case_temperature_c)
        _integer(self.observed_shots, "synthetic shots")
        if self.coverage not in ("complete-synthetic", "partial-synthetic"):
            raise InvalidPulsedLifetimeEvidence("unknown synthetic coverage")


@dataclass(frozen=True)
class PulseLifetimeAssessment:
    reason: str
    synthetic_shots: int | None = None
    vendor_expected_shots: int | None = None
    green_power_state_capability: bool = False
    hardware_authorized: bool = False

    def __post_init__(self) -> None:
        comparable = self.reason in (
            "synthetic-below-vendor-estimate", "synthetic-at-or-above-vendor-estimate")
        if self.reason not in (
            "different-product", "different-component-kind", "different-event",
            "different-component-instance", "different-pulse-mode",
            "different-case-temperature", "partial-synthetic-history",
            "conflicting-source-conditions", "synthetic-below-vendor-estimate",
            "synthetic-at-or-above-vendor-estimate"):
            raise InvalidPulsedLifetimeEvidence("unknown assessment reason")
        if self.green_power_state_capability or self.hardware_authorized:
            raise InvalidPulsedLifetimeEvidence("research output cannot authorize hardware")
        if comparable:
            _integer(self.synthetic_shots, "synthetic shots")
            _integer(self.vendor_expected_shots, "vendor estimate", min_value=1)
            expected = ("synthetic-at-or-above-vendor-estimate" if
                        self.synthetic_shots >= self.vendor_expected_shots else
                        "synthetic-below-vendor-estimate")
            if expected != self.reason:
                raise InvalidPulsedLifetimeEvidence("contradictory assessment")
        elif self.synthetic_shots is not None or self.vendor_expected_shots is not None:
            raise InvalidPulsedLifetimeEvidence("inapplicable evidence cannot return counts")


def compare_synthetic_pulses(claim: PulsedLifetimeClaim, history: SyntheticPulseHistory,
                             *, expected_component_instance_id: str) -> PulseLifetimeAssessment:
    """Compare exact supplier modes against invented counts; never release controls."""
    if not isinstance(claim, PulsedLifetimeClaim) or not isinstance(history, SyntheticPulseHistory):
        raise TypeError("PulsedLifetimeClaim and SyntheticPulseHistory required")
    _label(expected_component_instance_id, "expected component instance")
    if claim.product_model != history.product_model:
        return PulseLifetimeAssessment("different-product")
    if claim.component_kind != history.component_kind:
        return PulseLifetimeAssessment("different-component-kind")
    if claim.event != history.event:
        return PulseLifetimeAssessment("different-event")
    if history.component_instance_id != expected_component_instance_id:
        return PulseLifetimeAssessment("different-component-instance")
    if (claim.pulse_width_ms, claim.pulse_frequency_hz, claim.duty_cycle_percent) != (
            history.pulse_width_ms, history.pulse_frequency_hz, history.duty_cycle_percent):
        return PulseLifetimeAssessment("different-pulse-mode")
    if claim.case_temperature_c != history.case_temperature_c:
        return PulseLifetimeAssessment("different-case-temperature")
    if history.coverage != "complete-synthetic":
        return PulseLifetimeAssessment("partial-synthetic-history")
    if not claim.source_conditions_consistent:
        return PulseLifetimeAssessment("conflicting-source-conditions")
    reason = ("synthetic-at-or-above-vendor-estimate" if
              history.observed_shots >= claim.expected_shots else
              "synthetic-below-vendor-estimate")
    return PulseLifetimeAssessment(reason, history.observed_shots, claim.expected_shots)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidPulsedLifetimeEvidence("duplicate JSON key")
        obj[key] = value
    return obj


def parse_pulsed_lifetime_manifest(raw: str) -> tuple[PulsedLifetimeClaim, ...]:
    if not isinstance(raw, str):
        raise InvalidPulsedLifetimeEvidence("manifest must be UTF-8 text")
    try:
        encoded_size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InvalidPulsedLifetimeEvidence("manifest contains invalid Unicode") from exc
    if encoded_size > _MAX_BYTES:
        raise InvalidPulsedLifetimeEvidence("oversized manifest")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidPulsedLifetimeEvidence("invalid manifest JSON") from exc
    if (not isinstance(obj, dict) or set(obj) != {"schema_version", "records"} or
            type(obj["schema_version"]) is not int or obj["schema_version"] != 1):
        raise InvalidPulsedLifetimeEvidence("unsupported manifest schema")
    if not isinstance(obj["records"], list) or not 1 <= len(obj["records"]) <= _MAX_RECORDS:
        raise InvalidPulsedLifetimeEvidence("invalid record count")
    claims: list[PulsedLifetimeClaim] = []
    ids: set[str] = set()
    modes: set[tuple[object, ...]] = set()
    for row in obj["records"]:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise InvalidPulsedLifetimeEvidence("invalid record fields")
        claim = PulsedLifetimeClaim(**row)
        mode = (claim.product_model, claim.event, claim.pulse_width_ms,
                claim.pulse_frequency_hz, claim.duty_cycle_percent, claim.case_temperature_c)
        if claim.id in ids or mode in modes:
            raise InvalidPulsedLifetimeEvidence("duplicate claim ID or mode")
        ids.add(claim.id)
        modes.add(mode)
        claims.append(claim)
    return tuple(claims)


def load_pulsed_lifetime_manifest(path: str | Path) -> tuple[PulsedLifetimeClaim, ...]:
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise InvalidPulsedLifetimeEvidence("oversized manifest")
    try:
        return parse_pulsed_lifetime_manifest(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InvalidPulsedLifetimeEvidence("manifest must be UTF-8") from exc
