# Recovery ancestry and external checkpoint witness (experimental v0.1.14)

## 1. Full-journal ancestry inspection

`TransitionGuard.compare_checkpoint_lineage(archive_path)` and
`green-guard checkpoint-lineage --store LIVE --archive ARCHIVE` verify the
complete archive and the complete live journal under the existing journal lock.
The check requires append-only continuity for events, accepted no-ops, policy
updates, original initialization, schema upgrades and immutable window/budget
seals. Newly recorded operations must also respect the earlier snapshot's
monotonic `last_checked_ms`.

| `relation` | Interpretation | CLI exit |
|---|---|---|
| `identical` | Exact same complete source payload | 0 |
| `archive_ancestor` | Live history could extend the archived history | 0 |
| `current_ancestor` | The live file is older than the archive; **possible rollback** | 3 |
| `diverged` | Divergent histories, different initial parameters or retroactive additions | 3 |
| `different_device` | Device IDs differ | 3 |

Corrupt or missing inputs produce exit 2. A missing or rewritten event/no-op
ID, policy epoch, seal or earlier clock causes a failed lineage comparison.
Equal timestamps remain valid when append-only rules hold. The report omits raw
request IDs and includes content hashes. Neither path is edited.

A **possible rollback** is a diagnostic finding: an archive may have been
created from a separate branch, or the live file could actually have been
restored from an older backup. An append-only comparison cannot prove archive
freshness or the provenance of a future live operation. These two files can be
rolled back or rewritten together by an attacker with write access.

## 2. External HMAC witness (illustrative protocol)

`issue_checkpoint_witness()` signs a verified archive's full-source digest,
archive digest, device ID, schema, event/policy revisions, observed clock,
claimed integer `generation` and `witness_id` with HMAC-SHA256. Receipt output
contains no raw request IDs or secret. The archive itself **does** contain raw
IDs and histories.

`verify_checkpoint_witness()` checks:

1. The receipt structure and HMAC using a caller-held **32+ byte random key**.
2. Independent full archive validation and exact match to the signed metadata.
3. A caller-supplied expected device ID.
4. A caller-supplied **trusted source SHA256 root**, obtained from outside the
   archive/journal host trust domain.
5. A caller-supplied **trusted minimum generation**, likewise maintained by an
   independently trusted monotonic authority.

A signed generation below the trusted floor yields `below_trusted_floor`
(exit 3). Authentication, root or structural mismatch fails closed (exit 2).
Successful verification returns `verified_relative_to_external_inputs`
(exit 0). This means the archive matches the supplied key/root/floor. The
module **cannot establish** that those inputs are actually independently
trusted or latest. It cannot enforce unique generation assignment, prevent
rollback of external files, or stop someone holding the HMAC key from signing
a fraudulent generation. Authentic receipts at the same generation can exist
for two different archives unless the external issuing service prevents it.

### Python example

```python
from green_transition_guard.experimental_witness import (
    issue_checkpoint_witness, verify_checkpoint_witness,
)

# Only an external, trusted witness should own this secret and generation.
secret = externally_provided_random_key  # at least 32 bytes, supplied by caller
receipt = issue_checkpoint_witness(
    "/private/device.archive.json", secret=secret,
    generation=42, witness_id="lab-witness",
)

# Obtain these independently from a trusted service, rather than the archive.
report = verify_checkpoint_witness(
    "/private/device.archive.json", receipt, secret=secret,
    expected_device_id="device-123",
    trusted_min_generation=trusted_generation_floor,
    trusted_snapshot_sha256=trusted_source_sha256,
).to_dict()
```

The test CLI uses an **owner-only regular key file** and rejects symlinks.
This is a software integration fixture, with no HSM or remote monotonic
counter. Keep keys **outside the repository**, protect permissions (`0600`),
and never send a key to the journal host in a real threat model where that host
may be compromised.

```bash
# Illustrative test commands. Store the receipt and trusted root with an
# independent witness service; never trust copies kept only beside the journal.
green-guard checkpoint-witness-issue \
  --archive /private/device.archive.json \
  --key-file /independent-witness/witness.key \
  --generation 42 --witness-id lab-witness > /independent-witness/receipt.json

green-guard checkpoint-witness-verify \
  --archive /private/device.archive.json \
  --receipt /independent-witness/receipt.json \
  --key-file /independent-witness/witness.key \
  --expected-device-id device-123 \
  --trusted-min-generation 42 \
  --trusted-snapshot-sha256 "$TRUSTED_SHA256_FROM_EXTERNAL_WITNESS"
```

The last argument must be an independently obtained exact digest.

## Security and recovery boundaries

- Neither the lineage result nor a successful HMAC verification **authorizes
  restored operation**. `restoration_enabled` and `journal_compaction_enabled`
  remain false. There is no journal-restore command.
- A locally stored key, root or high-water mark has the same rollback exposure
  as the journal. Correct cryptographic verification cannot repair compromised
  trust inputs. The witness must enforce uniqueness and monotonicity outside
  the journal's failure/attacker domain for stronger claims.
- The archive's JSON checksum detects accidental corruption. It is unkeyed;
  its trust depends on the independently checked HMAC and root.
- There is no physical power-loss proof, hardware anchor, secure monotonic
  clock, signed hardware actuation or experimental YANG compliance claim.
- Identity count budgets do not bound file bytes or memory; no history
  truncation takes place.

Tests: `tests/test_recovery_lineage.py`, `tests/test_checkpoint_witness.py`.
