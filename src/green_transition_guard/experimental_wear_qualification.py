"""Offline comparison of mechanical durability references with synthetic counts.

An industry qualification rating is a test/design reference, never an
operational wear limit, a measured device capability, or a laser cycle budget.
No function in this module can authorize a physical power-state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit


Component = Literal["module", "connector-cage"]
Event = Literal["module-mating-unmating-cycle"]
Coverage = Literal["complete-synthetic", "partial-synthetic"]
_MAX_BYTES = 262_144
_MAX_RECORDS = 32
_MAX_COUNT = 2**63 - 1
_RECORD_FIELDS = frozenset({
    "id", "source_url", "source_revision", "source_locator", "authority",
    "form_factor", "component", "event", "claim_kind", "rated_cycles",
})


class InvalidWearEvidence(ValueError):
    """Unrecognized scope, count, or reference corpus."""


def _label(value: str, name: str) -> str:
    if (not isinstance(value, str) or not value or value.strip() != value or
            len(value) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise InvalidWearEvidence(f"invalid {name}")
    return value


def _nonnegative_count(value: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_COUNT:
        raise InvalidWearEvidence(f"invalid {name}")
    return value


@dataclass(frozen=True)
class WearQualification:
    """A stated *qualification* endurance figure for a component design."""

    id: str
    source_url: str
    source_revision: str
    source_locator: str
    authority: Literal["industry-consortium-specification"]
    form_factor: str
    component: Component
    event: Event
    claim_kind: Literal["rated-mechanical-durability-cycles"]
    rated_cycles: int

    def __post_init__(self) -> None:
        for name in ("id", "source_url", "source_revision", "source_locator", "form_factor"):
            _label(getattr(self, name), name)
        try:
            parsed = urlsplit(self.source_url)
        except ValueError as exc:
            raise InvalidWearEvidence("malformed source URL") from exc
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or any(ch.isspace() for ch in self.source_url)):
            raise InvalidWearEvidence("source must be an HTTPS URL without credentials")
        if self.authority != "industry-consortium-specification":
            raise InvalidWearEvidence("unsupported source authority")
        if self.component not in ("module", "connector-cage"):
            raise InvalidWearEvidence("unsupported component scope")
        if self.event != "module-mating-unmating-cycle":
            raise InvalidWearEvidence("unsupported counted event")
        if self.claim_kind != "rated-mechanical-durability-cycles":
            raise InvalidWearEvidence("unsupported claim semantics")
        _nonnegative_count(self.rated_cycles, "rated cycles")
        if self.rated_cycles == 0:
            raise InvalidWearEvidence("zero durability rating is invalid")


@dataclass(frozen=True)
class SyntheticWearCount:
    """An invented comparison count, tied to one asserted component instance.

    The assertion 'complete-synthetic' means only that the fixture represents
    a complete synthetic history. No telemetry is collected or verified.
    """

    form_factor: str
    component: str
    event: str
    component_instance_id: str
    count: int
    coverage: Coverage

    def __post_init__(self) -> None:
        for name in ("form_factor", "component", "event", "component_instance_id"):
            _label(getattr(self, name), name)
        _nonnegative_count(self.count, "synthetic count")
        if self.coverage not in ("complete-synthetic", "partial-synthetic"):
            raise InvalidWearEvidence("unsupported history coverage")


@dataclass(frozen=True)
class WearComparison:
    """Research interpretation only, with immutable safety invariants."""

    reason: str
    counted_cycles: int | None = None
    qualification_reference_cycles: int | None = None
    green_power_state_capability: bool = False
    hardware_authorized: bool = False

    def __post_init__(self) -> None:
        if self.reason not in (
            "synthetic-below-qualification-reference",
            "synthetic-at-or-above-qualification-reference",
            "different-form-factor", "different-component-scope",
            "different-event-domain", "different-component-instance",
            "incomplete-synthetic-history",
        ):
            raise InvalidWearEvidence("unknown wear comparison reason")
        if self.green_power_state_capability or self.hardware_authorized:
            raise InvalidWearEvidence("qualification cannot authorize power controls")
        comparable = self.reason in (
            "synthetic-below-qualification-reference",
            "synthetic-at-or-above-qualification-reference",
        )
        if comparable:
            if self.counted_cycles is None or self.qualification_reference_cycles is None:
                raise InvalidWearEvidence("comparable results require both counts")
            _nonnegative_count(self.counted_cycles, "comparison count")
            _nonnegative_count(self.qualification_reference_cycles, "reference count")
            if self.qualification_reference_cycles == 0:
                raise InvalidWearEvidence("reference count must be positive")
            expected = ("synthetic-at-or-above-qualification-reference" if
                        self.counted_cycles >= self.qualification_reference_cycles else
                        "synthetic-below-qualification-reference")
            if self.reason != expected:
                raise InvalidWearEvidence("contradictory comparison classification")
        elif self.counted_cycles is not None or self.qualification_reference_cycles is not None:
            raise InvalidWearEvidence("incomparable evidence must not expose a count")


def compare_synthetic_wear(
    reference: WearQualification,
    sample: SyntheticWearCount,
    *, expected_component_instance_id: str,
) -> WearComparison:
    """Compare mechanical test references against explicitly synthetic counts.

    No remaining-life estimate is computed: test ratings are neither hard
    maximums nor field failure thresholds. Missing event coverage blocks even
    a synthetic comparison. The physical component identity is caller-asserted.
    """
    if not isinstance(reference, WearQualification) or not isinstance(sample, SyntheticWearCount):
        raise TypeError("typed reference and synthetic sample required")
    _label(expected_component_instance_id, "expected component instance")
    if sample.form_factor != reference.form_factor:
        return WearComparison("different-form-factor")
    if sample.component != reference.component:
        return WearComparison("different-component-scope")
    if sample.event != reference.event:
        return WearComparison("different-event-domain")
    if sample.component_instance_id != expected_component_instance_id:
        return WearComparison("different-component-instance")
    if sample.coverage != "complete-synthetic":
        return WearComparison("incomplete-synthetic-history")
    return WearComparison(
        "synthetic-at-or-above-qualification-reference" if
        sample.count >= reference.rated_cycles else
        "synthetic-below-qualification-reference",
        sample.count, reference.rated_cycles,
    )


def _no_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise InvalidWearEvidence("duplicate evidence field")
        output[key] = value
    return output


def parse_wear_manifest(raw: str) -> tuple[WearQualification, ...]:
    """Strictly parse the reviewed reference corpus without fetching its URLs."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BYTES:
        raise InvalidWearEvidence("wear corpus is invalid or oversized")
    try:
        payload = json.loads(raw, object_pairs_hook=_no_duplicate_fields)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidWearEvidence("invalid wear evidence JSON") from exc
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "records"} or
            type(payload["schema_version"]) is not int or payload["schema_version"] != 1):
        raise InvalidWearEvidence("unsupported wear evidence schema")
    records = payload["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= _MAX_RECORDS:
        raise InvalidWearEvidence("invalid wear evidence record count")
    seen: set[str] = set()
    out: list[WearQualification] = []
    for row in records:
        if not isinstance(row, dict) or set(row) != _RECORD_FIELDS:
            raise InvalidWearEvidence("unexpected wear evidence fields")
        evidence = WearQualification(**row)
        if evidence.id in seen:
            raise InvalidWearEvidence("duplicate wear evidence ID")
        seen.add(evidence.id)
        out.append(evidence)
    return tuple(out)


def load_wear_manifest(path: str | Path) -> tuple[WearQualification, ...]:
    """Read bounded local UTF-8 data; never download remote evidence."""
    with Path(path).open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise InvalidWearEvidence("wear corpus is oversized")
    try:
        return parse_wear_manifest(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise InvalidWearEvidence("wear corpus must be UTF-8") from exc
