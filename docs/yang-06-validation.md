# GREEN Power and Energy YANG -06 validation

The official [November 15, 2026 `-06` draft](https://www.ietf.org/archive/id/draft-ietf-green-power-and-energy-yang-06.html) changes the Power and Energy module while retaining the module's `revision 2026-11-01`. Therefore filenames based only on the YANG module revision cannot distinguish `-05` from `-06`. The two schema sets are downloaded and compiled in **separate directories**.

The previous `official_yang_smoke.py` and `official_yang_instance_smoke.py` commands remain unchanged for `-05`. Their published-draft, augmentation and 14-case manifest fingerprints continue to be checked as before. The new `official_yang_06_smoke.py` invokes the original compiler against the exact published `-06` XML URL, records the actual SHA-256 of all source bytes, checks the expected `-06` schema changes, and independently validates the same 14 pinned RFC 7951 examples. It adds three **synthetic** cases: a valid 64-bit counter plus discontinuity date/time, an invalid date/time, and counter overflow. Invalid cases must fail for the correct node, so broken schema imports or absent compilers cannot be confused with successful rejection.

Run on Linux/WSL with installed `pyang` and `yanglint`, plus the project's Python dependencies:

```sh
python scripts/official_yang_smoke.py --output /tmp/green-05-schema
python scripts/official_yang_instance_smoke.py \
  --smoke-output /tmp/green-05-schema --output /tmp/green-05-instances
python scripts/official_yang_06_smoke.py --output /tmp/green-06
```

Use three **new, empty output directories**. GitHub Actions runs the commands automatically in `.github/workflows/official-yang-smoke.yml` and uploads source and validation evidence, even on failure.

## Scope of the `-06` checks

- `total-energy-received` and `total-energy-provided` use `yang:counter64`.
- `discontinuity-time` uses `yang:date-and-time` and is scoped to **energy counter discontinuities**.
- `source-component-id` still references the `ietf-hardware` component's device-local `name`; the draft recommends also reporting the component `uuid` for cross-system correlation.
- The existing `admin` (intent) and `oper` (observed state) leaves remain unchanged.
- `min-residency-time` and transition quotas remain outside this module; the authors are discussing the former in Capability Discovery.

The published `-06` XML and the original module/dependency bytes (including RFC 9911 `ietf-yang-types` and `ietf-inet-types` revisions `2025-12-22`) are copied to the evidence archive with SHA-256 digests. The new gate checks them against each other and the exact released URL; unlike the retained `-05` gate, the `-06` release digest **is recorded per run and has not yet been separately hard-pinned**. Once independently reviewed from successful CI output, that digest can become a regression pin. The older -05 release and its corpus remain strictly pinned throughout.

Passing tests demonstrate schema and instance compatibility only. They do not prove hardware counter continuity, certify a safe power transition interval, or authorize device actuation.
