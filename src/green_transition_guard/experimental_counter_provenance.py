"""Research-only counter provenance checks. No real hardware claims.

The contract consists entirely of caller assertions. An assessment of
'conditional-candidate' means that the declared properties would be sufficient
for *count comparison* in this lab; it is not device certification, nor proof
that a reported event corresponds to a particular command or occurred at a
known instant. The module never actuates or authorizes a transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CounterKind = Literal["physical-edge", "power-cycle", "lpi-entry", "thermal-action", "event-log", "host-state"]


@dataclass(frozen=True)
class CounterContract:
    energy_object_id: str
    source_id: str
    kind: CounterKind
    # All flags MUST be verified from a real device contract before deployment.
    covers_all_policy_edges: bool
    includes_autonomous_edges: bool
    survives_full_power_loss: bool
    atomic_with_physical_edge: bool
    protected_from_unauthorized_reset: bool
    stable_component_binding: bool
    documented_reset_epoch: bool
    no_undetected_wrap: bool
    max_counter_value: int | None = None

    def __post_init__(self) -> None:
        if not self.energy_object_id or not self.source_id:
            raise ValueError("nonempty source and Energy Object identifiers required")
        if self.kind not in ("physical-edge", "power-cycle", "lpi-entry", "thermal-action", "event-log", "host-state"):
            raise ValueError("unsupported counter kind")
        for name in (
            "covers_all_policy_edges", "includes_autonomous_edges",
            "survives_full_power_loss", "atomic_with_physical_edge",
            "protected_from_unauthorized_reset", "stable_component_binding",
            "documented_reset_epoch", "no_undetected_wrap",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError("counter contract flags must be boolean")
        if self.max_counter_value is not None and (
            type(self.max_counter_value) is not int or self.max_counter_value < 1
        ):
            raise ValueError("invalid counter maximum")

    def provisional_candidate(self) -> bool:
        """A declared contract gate only. External verification is mandatory."""
        return self.kind == "physical-edge" and all((
            self.covers_all_policy_edges, self.includes_autonomous_edges,
            self.survives_full_power_loss, self.atomic_with_physical_edge,
            self.protected_from_unauthorized_reset, self.stable_component_binding,
            self.documented_reset_epoch, self.no_undetected_wrap,
        ))


@dataclass(frozen=True)
class CounterSample:
    energy_object_id: str
    source_id: str
    counter_epoch: str
    sample_sequence: int
    count: int
    oper: str
    coverage_gap: bool = False

    def __post_init__(self) -> None:
        if any(type(v) is not str or not v for v in (
            self.energy_object_id, self.source_id, self.counter_epoch, self.oper,
        )):
            raise ValueError("counter sample identities must be nonempty strings")
        if type(self.sample_sequence) is not int or self.sample_sequence < 0:
            raise ValueError("invalid sample sequence")
        if type(self.count) is not int or self.count < 0:
            raise ValueError("invalid counter value")
        if type(self.coverage_gap) is not bool:
            raise ValueError("invalid coverage flag")


@dataclass(frozen=True)
class CounterAssessment:
    reason: str
    count_delta: int | None
    quarantine: bool
    conditional_candidate: bool


def assess_counter_pair(contract: CounterContract, previous: CounterSample,
                        current: CounterSample) -> CounterAssessment:
    """Conservatively compare two asserted observations of one source.

    A new edge count remains *unattributed*. No count delta identifies the
    issuing controller or proves exact transition time. The caller must
    reconcile with the device-side physical operation journal separately.
    """
    if any(s.energy_object_id != contract.energy_object_id or
           s.source_id != contract.source_id for s in (previous, current)):
        return CounterAssessment("source-or-component-mismatch", None, True, False)
    if current.sample_sequence <= previous.sample_sequence:
        return CounterAssessment("stale-or-reordered-sample", None, True, False)
    if previous.coverage_gap or current.coverage_gap:
        return CounterAssessment("reported-coverage-gap", None, True, False)
    if current.counter_epoch != previous.counter_epoch:
        return CounterAssessment("counter-reset-epoch-changed", None, True, False)
    if contract.max_counter_value is not None:
        if max(previous.count, current.count) > contract.max_counter_value:
            return CounterAssessment("counter-exceeds-declared-range", None, True, False)
        if max(previous.count, current.count) == contract.max_counter_value:
            return CounterAssessment("counter-at-maximum", None, True, False)
    if current.count < previous.count:
        return CounterAssessment("counter-decreased-or-wrapped", None, True, False)
    delta = current.count - previous.count
    if not contract.provisional_candidate():
        # A diagnostic counter need not cover the reported GREEN state. A
        # zero delta with changed oper is not itself a source contradiction.
        # It never justifies releasing a safety quota.
        return CounterAssessment("diagnostic-source-only", delta, True, False)
    if delta == 0 and previous.oper != current.oper:
        return CounterAssessment("state-changed-without-counted-edge", 0, True, False)
    if delta:
        return CounterAssessment("new-unattributed-edges", delta, True, True)
    return CounterAssessment("no-counted-edges", 0, False, True)
