"""Demonstrate passive counter parsing with explicitly fictional fixtures."""
from pathlib import Path

from green_transition_guard.experimental_vendor_counters import (
    assess_offline_pair, parse_igc_ethtool_stats, parse_nvme_smart_json,
)

fixtures = Path(__file__).resolve().parent / "fixtures"


def main() -> None:
    a = parse_igc_ethtool_stats(
        (fixtures / "igc-ethtool-before.txt").read_text(),
        energy_object_id="fictional-nic", pci_id="fictional-pci",
        boot_id="synthetic-boot", driver_epoch="synthetic-driver-instance",
        direction="tx", sample_sequence=1, oper="on",
    )
    b = parse_igc_ethtool_stats(
        (fixtures / "igc-ethtool-after.txt").read_text(),
        energy_object_id="fictional-nic", pci_id="fictional-pci",
        boot_id="synthetic-boot", driver_epoch="synthetic-driver-instance",
        direction="tx", sample_sequence=2, oper="on",
    )
    report = assess_offline_pair(a, b)
    print("Intel igc Tx LPI events (synthetic):", report.count_delta)
    print("Assessment:", report.reason, "quarantine=", report.quarantine)

    a = parse_nvme_smart_json(
        (fixtures / "nvme-smart-before.json").read_text(),
        energy_object_id="fictional-nvme", controller_id="synthetic-controller",
        asserted_counter_epoch="synthetic-controller-generation",
        metric="power_cycles", sample_sequence=1, oper="on",
    )
    b = parse_nvme_smart_json(
        (fixtures / "nvme-smart-after.json").read_text(),
        energy_object_id="fictional-nvme", controller_id="synthetic-controller",
        asserted_counter_epoch="synthetic-controller-generation",
        metric="power_cycles", sample_sequence=2, oper="on",
    )
    report = assess_offline_pair(a, b)
    print("NVMe controller power cycles (synthetic):", report.count_delta)
    print("Assessment:", report.reason, "quarantine=", report.quarantine)
    print("No hardware sampled; neither reading authorizes a transition.")


if __name__ == "__main__":
    main()
