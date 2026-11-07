# Journal lineage and checkpoint witness

This is an incident-analysis experiment. Both commands inspect complete journals; they never restore one or delete history.

## Comparing a live journal with an archive

```bash
green-guard checkpoint-lineage --store LIVE --archive ARCHIVE
```

The checker validates both files and compares initialization, transition and no-op histories, policy updates, schema migrations, seals, operation cutoffs and recorded time. It also rejects retroactive additions that would contradict an older complete snapshot.

| Relation | Meaning | Exit code |
| --- | --- | ---: |
| `identical` | The source payloads match | 0 |
| `archive_ancestor` | The live history could extend the archived history | 0 |
| `current_ancestor` | The live history could be older; possible rollback | 3 |
| `diverged` | The valid histories disagree | 3 |
| `different_device` | Device IDs differ | 3 |

Missing or corrupt inputs return exit 2. Reports contain digests and revision metadata without printing request IDs. Valid equal-timestamp operations are allowed when their revision/operation order is consistent.

A lineage relation alone cannot tell which file is newer in the real world. The archive and journal may both be stale, or may have been replaced together.

## HMAC receipts

`checkpoint-witness-issue` signs the verified archive's identity, source and archive digests, revisions, time, claimed generation, and witness ID with HMAC-SHA256. The receipt omits raw request IDs; the archive still holds full history.

`checkpoint-witness-verify` requires a matching archive and HMAC, the expected device ID, a trusted snapshot SHA-256, and a trusted minimum generation. The last two values must come from a source outside the journal host's trust domain. An HMAC alone cannot establish that they are fresh.

The verification statuses are:

- `verified_relative_to_external_inputs` (exit 0): checks match the supplied key, root, and generation floor.
- `below_trusted_floor` (exit 3): the signed generation is too old.
- Exit 2: invalid receipt, mismatch or unreadable archive.

The CLI reads a local owner-only key file for testing. Real deployments would need an independently protected signing key and monotonic generation authority. The code provides neither service, and it does not prevent an issuer from signing conflicting archives with the same generation.

Source: `src/green_transition_guard/experimental_recovery.py` and `src/green_transition_guard/experimental_witness.py`. Tests: `tests/test_recovery_lineage.py` and `tests/test_checkpoint_witness.py`.

Recovery activation and journal compaction remain disabled. Physical durability after loss of power is untested.
