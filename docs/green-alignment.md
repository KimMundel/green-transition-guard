# GREEN and related standards

This mapping is based on specific draft revisions, since the GREEN models are still changing. The source links below are preferable to treating these notes as normative.

The practical question is whether devices need a common way to advertise **restrictions on how often a power state may change**. The existing drafts already cover several adjacent concepts.

| Source | Relevant part | Gap for this experiment |
| --- | --- | --- |
| [GREEN Use Cases -02](https://datatracker.ietf.org/doc/html/draft-ietf-green-use-cases-02) | Section 2.1.4 mentions protecting lasers/connectors from frequent cycling. | It does not define machine-readable limits. |
| [GREEN Framework -03](https://datatracker.ietf.org/doc/html/draft-ietf-green-framework-03) | Section 3.5.1 discusses transition-frequency and duty-cycle restrictions. | Exact enforcement and discovery semantics remain open. |
| [Power and Energy YANG -05](https://datatracker.ietf.org/doc/html/draft-ietf-green-power-and-energy-yang-05) | Energy Object power state: configured `admin`, observed `oper`. | No minimum dwell or rolling cycling quota in the tested model. |
| [Capability Discovery -03](https://datatracker.ietf.org/doc/html/draft-claise-green-capability-discovery-03) | Available power states and entry/exit characteristics. | Explicit transition restrictions remain outside its scope. |
| [RFC 7460](https://www.rfc-editor.org/rfc/rfc7460) | Power-state entry counts and residence-time statistics. | Measurements of past behavior are different from safe future limits. |

A technology-specific precedent also exists: ITU-T G.9807.1 includes timing parameters for XGS-PON power-management states. That does not establish a generic rule for all GREEN Energy Objects.

## Model boundaries

The tested Power and Energy YANG -05 uses separate paths:

- Requested state: `/energy-control/energy-objects/energy-object/power-state/admin`
- Observed state: `/energy-objects/energy-object/power-state/oper`

The Energy Object entries are correlated by `id`. Power-state values are YANG identities; sample names such as `sleep` are internal to the simulator and require explicit identity mapping before serialization.

The [experimental augmentation](yang-augmentation-experiment.md) attaches a read-only `transition-safety` subtree to the operational Energy Object. It leaves the existing `admin` and `oper` leaves alone. Its phase, quarantine and count values describe a laboratory model, including unresolved transitions. It cannot substantiate manufacturer capabilities.

This is a useful distinction for controller implementations: accepting an intent, receiving an acknowledgement, and observing the physical change may happen at different times. Lost acknowledgements and autonomous transitions make a simple request counter insufficient.

## Questions for implementers

- Which limits are documented by real equipment? Do they apply to the whole device, an Energy Object, a particular transition, or a component lifetime?
- Should these values be discovered from hardware, configured by an operator, or both?
- Should the quota count accepted requests, observed transitions, or another event? How should restart and counter discontinuity be represented?
- Is an existing technology-specific model preferable to a common GREEN extension?

No WG decision has been made for this experiment. The code and schema are independent research artifacts. For the actual tested compiler and instance results, see [test evidence](test-report.md).
