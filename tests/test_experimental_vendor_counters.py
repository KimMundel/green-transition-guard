"""Offline synthetic snapshots grounded in documented Linux/NVMe field names.

No tests claim physical-device access or vendor certification.
"""

from dataclasses import replace

import pytest

from green_transition_guard.experimental_vendor_counters import (
    UnsupportedCounterInput, assess_offline_pair, parse_igc_ethtool_stats,
    parse_nvme_smart_json,
)
from green_transition_guard.experimental_counter_provenance import (
    CounterContract, assess_counter_pair,
)


IGC = "NIC statistics:\n     tx_lpi_counter: 12\n     rx_lpi_counter: 7\n"
NVME = '{"power_cycles": "1234", "thm_temp1_trans_count": 17, "thm_temp2_trans_count": 0}'


def igc(raw=IGC, **changes):
    args = dict(energy_object_id="nic-0", pci_id="0000:01:00.0",
                boot_id="boot-a", driver_epoch="igc-loaded-a", direction="tx",
                sample_sequence=1, oper="on")
    args.update(changes)
    return parse_igc_ethtool_stats(raw, **args)


def nvme(raw=NVME, **changes):
    args = dict(energy_object_id="ssd-0", controller_id="serial-abc",
                asserted_counter_epoch="device-generation-1", metric="power_cycles",
                sample_sequence=1, oper="on")
    args.update(changes)
    return parse_nvme_smart_json(raw, **args)


def test_igc_uses_actual_driver_stat_names():
    a = igc()
    assert a.sample.count == 12 and a.metric == "tx_lpi_counter"
    assert a.contract.kind == "lpi-entry"
    assert not a.contract.provisional_candidate()


def test_igc_rx_counts_different_events_and_cannot_be_merged_with_tx():
    tx = igc()
    rx = igc(direction="rx", sample_sequence=2)
    assert rx.metric == "rx_lpi_counter" and rx.sample.count == 7
    assert tx.sample.source_id != rx.sample.source_id
    assert assess_offline_pair(tx, rx).reason == "source-or-component-mismatch"


def test_igc_same_instance_delta_is_diagnostic_only():
    old = igc()
    new = igc("tx_lpi_counter: 14", sample_sequence=2)
    a = assess_offline_pair(old, new)
    assert (a.reason, a.count_delta, a.quarantine, a.conditional_candidate) == (
        "diagnostic-source-only", 2, True, False)


def test_diagnostic_lpi_count_can_stay_same_despite_green_oper_change():
    a = assess_offline_pair(igc(), igc(sample_sequence=2, oper="sleep"))
    assert a.reason == "diagnostic-source-only" and a.quarantine


@pytest.mark.parametrize("change", [{"boot_id": "boot-b"},
                                    {"driver_epoch": "loaded-b"}])
def test_new_boot_or_driver_epoch_is_discontinuity(change):
    a = assess_offline_pair(igc(), igc(sample_sequence=2, **change))
    assert a.reason == "counter-reset-epoch-changed" and a.quarantine


def test_igc_counter_decrease_quarantined():
    a = assess_offline_pair(igc(), igc("tx_lpi_counter: 1", sample_sequence=2))
    assert a.reason == "counter-decreased-or-wrapped"


def test_igc_duplicate_relevant_entry_fails():
    with pytest.raises(UnsupportedCounterInput, match="duplicate"):
        igc(IGC + "tx_lpi_counter: 13\n")


@pytest.mark.parametrize("dump", ["rx_lpi_counter: 3", "tx_lpi_counter: -1",
                                   "tx_lpi_counter: NaN", "tx_lpi_counter: 1.2",
                                   "tx_lpi_counter: " + str(2**64)])
def test_igc_rejects_missing_or_invalid_metric(dump):
    with pytest.raises(UnsupportedCounterInput):
        igc(dump)


def test_igc_other_driver_stats_ignored():
    a = igc("NIC statistics:\nrx_packets: 400\ntx_lpi_counter: 18\n")
    assert a.sample.count == 18


def test_nvme_power_cycle_value_is_controller_lifetime_diagnostic():
    a = nvme()
    assert a.sample.count == 1234 and a.contract.kind == "power-cycle"
    assert not a.contract.covers_all_policy_edges
    assert not a.contract.provisional_candidate()


@pytest.mark.parametrize("metric", ["thm_temp1_trans_count", "thm_temp2_trans_count"])
def test_nvme_thermal_counts_are_ambiguous_metric_specific_actions(metric):
    a = nvme(metric=metric)
    assert a.contract.kind == "thermal-action"
    assert a.contract.max_counter_value == 2**32 - 1
    if metric == "thm_temp2_trans_count":
        assert a.sample.coverage_gap  # zero means never used OR unsupported
    else:
        assert not a.sample.coverage_gap


def test_nvme_zero_thermal_count_is_not_verified_implementation_support():
    zero = nvme(metric="thm_temp2_trans_count", sample_sequence=1)
    later = nvme('{"thm_temp2_trans_count": 1}', metric="thm_temp2_trans_count", sample_sequence=2)
    a = assess_offline_pair(zero, later)
    assert a.reason == "reported-coverage-gap" and a.quarantine


def test_nvme_thermal_counter_saturation_blocks_assessment():
    a = nvme('{"thm_temp1_trans_count": 4294967295}', metric="thm_temp1_trans_count")
    b = nvme('{"thm_temp1_trans_count": 4294967295}', metric="thm_temp1_trans_count", sample_sequence=2)
    assert assess_offline_pair(a, b).reason == "counter-at-maximum"


def test_nvme_large_uint128_is_accepted_as_decimal_without_precision_loss():
    n = 2**100 + 17
    a = nvme('{"power_cycles": "' + str(n) + '"}')
    assert a.sample.count == n


@pytest.mark.parametrize("dump", ['{"power_cycles": -1}', '{"power_cycles": true}',
                                   '{"power_cycles": 1.5}', '{"power_cycles": "1,000"}',
                                   '{"power_cycles": "1e6"}', '{"other": 1}',
                                   '{"power_cycles": 2, "power_cycles": 3}',
                                   '{"power_cycles": 340282366920938463463374607431768211456}',
                                   'invalid json'])
def test_nvme_rejects_unverifiable_json(dump):
    with pytest.raises(UnsupportedCounterInput):
        nvme(dump)


def test_nvme_thermal_32_bit_range_enforced():
    with pytest.raises(UnsupportedCounterInput):
        nvme('{"thm_temp1_trans_count": 4294967296}', metric="thm_temp1_trans_count")


def test_nvme_controller_replacement_is_source_mismatch():
    a = assess_offline_pair(nvme(), nvme(controller_id="new-ssd", sample_sequence=2))
    assert a.reason == "source-or-component-mismatch" and a.quarantine


def test_nvme_unknown_reset_is_detected_only_if_epoch_is_correctly_reported():
    a = assess_offline_pair(nvme(), nvme(sample_sequence=2, asserted_counter_epoch="generation-2"))
    assert a.reason == "counter-reset-epoch-changed"


def test_nvme_same_id_delta_still_diagnostic_only():
    a = assess_offline_pair(nvme(), nvme('{"power_cycles": 1235}', sample_sequence=2))
    assert a.reason == "diagnostic-source-only" and a.count_delta == 1


def test_nvme_different_metrics_cannot_be_subtracted():
    a = assess_offline_pair(nvme(), nvme(metric="thm_temp1_trans_count", sample_sequence=2))
    assert a.reason == "source-or-component-mismatch"


@pytest.mark.parametrize("parser", ["igc", "nvme"])
def test_bounded_input_and_identity_validation(parser):
    with pytest.raises(UnsupportedCounterInput):
        (igc if parser == "igc" else nvme)("x" * 1_100_000)
    with pytest.raises(ValueError):
        (igc if parser == "igc" else nvme)(energy_object_id="  ")
    with pytest.raises(ValueError):
        (igc if parser == "igc" else nvme)(sample_sequence=True)


def test_old_diagnostic_contract_does_not_claim_state_counter_contradiction():
    # A targeted regression for the generic analyzer: only complete edge
    # counters can interpret unchanged count + changed GREEN oper as a fault.
    old = igc().sample
    new = igc(sample_sequence=2, oper="sleep").sample
    report = assess_counter_pair(igc().contract, old, new)
    assert report.reason == "diagnostic-source-only"


def test_no_offline_adapter_can_construct_provisional_hardware_authority():
    for reading in [igc(), igc(direction="rx"), nvme(),
                    nvme(metric="thm_temp1_trans_count")]:
        assert not reading.contract.provisional_candidate()
        assert not reading.contract.survives_full_power_loss
        assert not reading.contract.protected_from_unauthorized_reset
