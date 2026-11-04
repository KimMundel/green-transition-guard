"""Offline, passive parsers for documented hardware/driver counter output.

Research only. The supplied text and identities are untrusted observations. These
adapters do not invoke ethtool, nvme-cli or any device commands and cannot
turn vendor counters into evidence that is sufficient for safety enforcement.

Only exact, documented metric names are recognized. Unknown versions, missing
fields, duplicate entries, and malformed data fail closed during parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Literal

from .experimental_counter_provenance import (
    CounterAssessment, CounterContract, CounterSample, assess_counter_pair,
)


IgcDirection = Literal["tx", "rx"]
NvmeMetric = Literal["power_cycles", "thm_temp1_trans_count", "thm_temp2_trans_count"]

_IGC_METRICS = {"tx": "tx_lpi_counter", "rx": "rx_lpi_counter"}
_NVME_THERMAL_METRICS = {"thm_temp1_trans_count", "thm_temp2_trans_count"}
_MAX_U64 = 2**64 - 1
_MAX_U128 = 2**128 - 1
_MAX_U32 = 2**32 - 1
_MAX_BYTES = 1_048_576


class UnsupportedCounterInput(ValueError):
    """The source format cannot be verified from the provided text."""


@dataclass(frozen=True)
class OfflineCounterReading:
    """A count and its declared source semantics, always diagnostic-only."""

    sample: CounterSample
    contract: CounterContract
    metric: str
    meaning: str
    reference: str
    caution: str

    def __post_init__(self) -> None:
        if self.contract.provisional_candidate():
            raise ValueError("offline vendor counters cannot authorize safety transitions")
        if (self.sample.source_id != self.contract.source_id or
                self.sample.energy_object_id != self.contract.energy_object_id):
            raise ValueError("counter/source binding mismatch")


def _required_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\n" in value:
        raise ValueError(f"{label} must be a nonempty opaque identifier")
    if len(value) > 256:
        raise ValueError(f"{label} exceeds size limit")
    return value


def _sequence(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid sample sequence")
    return value


def _raw_limit(raw: str) -> str:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_BYTES:
        raise UnsupportedCounterInput("counter input must be bounded UTF-8 text")
    return raw


def _diagnostic_contract(*, energy_object_id: str, source_id: str, kind: str,
                         maximum: int | None = None) -> CounterContract:
    # Deliberately false: a source being documented does not prove full policy
    # edge coverage, atomicity, durable epoch, reset protection or zero gaps.
    return CounterContract(
        energy_object_id=energy_object_id, source_id=source_id, kind=kind,
        covers_all_policy_edges=False, includes_autonomous_edges=False,
        survives_full_power_loss=False, atomic_with_physical_edge=False,
        protected_from_unauthorized_reset=False, stable_component_binding=False,
        documented_reset_epoch=False, no_undetected_wrap=False,
        max_counter_value=maximum,
    )


def parse_igc_ethtool_stats(raw: str, *, energy_object_id: str, pci_id: str,
                            boot_id: str, driver_epoch: str, direction: IgcDirection,
                            sample_sequence: int, oper: str) -> OfflineCounterReading:
    """Parse a Linux igc `ethtool -S IFACE` dump, selecting one LPI direction.

    The driver maps names to its *software-accumulated* stats.tlpic / rlpic.
    boot_id and driver_epoch are operator assertions, not verified identity.
    The driver epoch must change across a reload/discontinuity. Neither
    host boot ID nor a consistent text header proves that no reload occurred.
    """
    raw = _raw_limit(raw)
    for name, value in (
        ("energy_object_id", energy_object_id), ("pci_id", pci_id),
        ("boot_id", boot_id), ("driver_epoch", driver_epoch), ("oper", oper),
    ):
        _required_identity(value, name)
    _sequence(sample_sequence)
    if direction not in _IGC_METRICS:
        raise ValueError("unsupported igc direction")
    found: dict[str, int] = {}
    for line in raw.splitlines():
        # Ignore all other ethtool statistics. Reject duplicated relevant
        # keys and invalid values even when selecting just one direction.
        match = re.match(r"^\s*(tx_lpi_counter|rx_lpi_counter)\s*:\s*(\S+)\s*$", line)
        if match:
            name, unparsed = match.groups()
            if name in found:
                raise UnsupportedCounterInput("duplicate igc LPI statistic")
            if not re.fullmatch(r"[0-9]+", unparsed):
                raise UnsupportedCounterInput("invalid igc LPI count")
            value = int(unparsed)
            if value > _MAX_U64:
                raise UnsupportedCounterInput("igc count exceeds uint64")
            found[name] = value
    selected = _IGC_METRICS[direction]
    if selected not in found:
        raise UnsupportedCounterInput("requested igc LPI statistic absent")
    source_id = f"igc:{pci_id}:{selected}"
    contract = _diagnostic_contract(energy_object_id=energy_object_id,
                                    source_id=source_id, kind="lpi-entry")
    sample = CounterSample(
        energy_object_id=energy_object_id, source_id=source_id,
        counter_epoch=f"asserted-boot:{boot_id}|asserted-driver:{driver_epoch}",
        sample_sequence=sample_sequence, count=found[selected], oper=oper,
    )
    meaning = ("Tx LPI entry events at the local NIC" if direction == "tx"
               else "Rx LPI entry events associated with received link signaling")
    return OfflineCounterReading(
        sample, contract, selected, meaning,
        "https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/intel/igc/igc_ethtool.c",
        "Driver-accumulated LPI statistic; reboot/reload coverage, reset epoch, "
        "NIC identity and GREEN state mapping are unverified.",
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise UnsupportedCounterInput("duplicate NVMe JSON field")
        obj[key] = value
    return obj


def _parse_nvme_count(value: object, *, maximum: int) -> int:
    if type(value) is int:
        count = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        count = int(value)
    else:
        raise UnsupportedCounterInput("NVMe count must be a decimal integer")
    if count < 0 or count > maximum:
        raise UnsupportedCounterInput("NVMe count out of range")
    return count


def parse_nvme_smart_json(raw: str, *, energy_object_id: str, controller_id: str,
                          asserted_counter_epoch: str, metric: NvmeMetric,
                          sample_sequence: int, oper: str) -> OfflineCounterReading:
    """Parse selected libnvme-style SMART JSON keys (offline, read-only).

    The input must explicitly contain the exact named field. CLI output
    naming/version support is deliberately narrow: no guessed aliases or
    interpretation of a whole-device NVMe state from a SMART metric.
    """
    raw = _raw_limit(raw)
    for name, value in (
        ("energy_object_id", energy_object_id), ("controller_id", controller_id),
        ("asserted_counter_epoch", asserted_counter_epoch), ("oper", oper),
    ):
        _required_identity(value, name)
    _sequence(sample_sequence)
    if metric not in ("power_cycles", *sorted(_NVME_THERMAL_METRICS)):
        raise ValueError("unsupported NVMe metric")
    try:
        obj = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise UnsupportedCounterInput("invalid NVMe SMART JSON") from exc
    if not isinstance(obj, dict) or metric not in obj:
        raise UnsupportedCounterInput("requested NVMe SMART metric absent")
    thermal = metric in _NVME_THERMAL_METRICS
    max_value = _MAX_U32 if thermal else _MAX_U128
    count = _parse_nvme_count(obj[metric], maximum=max_value)
    source_id = f"nvme:{controller_id}:{metric}"
    contract = _diagnostic_contract(energy_object_id=energy_object_id, source_id=source_id,
                                    kind="thermal-action" if thermal else "power-cycle",
                                    maximum=max_value if thermal else None)
    sample = CounterSample(
        energy_object_id=energy_object_id, source_id=source_id,
        counter_epoch=f"asserted-controller:{controller_id}|asserted-epoch:{asserted_counter_epoch}",
        sample_sequence=sample_sequence, count=count, oper=oper,
        # NVMe thermal count = 0 can mean no occurrences OR unsupported field.
        coverage_gap=thermal and count == 0,
    )
    return OfflineCounterReading(
        sample, contract, metric,
        ("Controller power cycles" if not thermal else
         "Thermal-management actions or lower-power active state transitions"),
        "https://libnvme.readthedocs.io/en/latest/rst/types.html",
        ("Zero cannot establish implementation support; saturated uint32 count "
         "cannot establish further entries. " if thermal else "") +
        "SMART counter does not prove complete GREEN policy transition coverage "
        "or an authenticated hardware reset epoch.",
    )


def assess_offline_pair(previous: OfflineCounterReading,
                        current: OfflineCounterReading) -> CounterAssessment:
    """Diagnostic comparison only. Never releases a hardware safety quota."""
    if not isinstance(previous, OfflineCounterReading) or not isinstance(current, OfflineCounterReading):
        raise TypeError("offline readings required")
    if previous.metric != current.metric or previous.contract != current.contract:
        return CounterAssessment("source-or-component-mismatch", None, True, False)
    return assess_counter_pair(current.contract, previous.sample, current.sample)
