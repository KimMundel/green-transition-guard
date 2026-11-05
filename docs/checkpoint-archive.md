# Create-only checkpoint archive candidates (experimental v0.1.12)

## Scope and invariants

A checkpoint archive preserves a **complete validated journal snapshot** (events,
no-ops, historical policy epochs, ceiling installation and every replay ID), plus
its independently regenerated v0.1.11 preflight manifest. It is stored as a
checksum-wrapped JSON file separate from the live guard journal. The archive
contains exact identity material, enabling later offline replay/collision
inspection. It is **not** a compacted journal, a production backup service, or
an authenticated checkpoint root.

- The live journal is always the sole source of authority for guard decisions.
- Export does **not** edit the journal, change its revision or clear any IDs.
- The archive is **create-only through this API**; an existing destination,
  including a symlink, causes an error. A user with file permissions can still
  edit or delete it. There is no cryptographic anti-rollback protection.
- The archive path must be absolute and reside in the **same directory** as the
  journal. The exporting process must have POSIX hardlink and directory-fsync
  support. A temporary file is created with mode `0600`.
- The archive **contains raw request IDs, policies and full history**. Treat it
  as sensitive; CLI summaries omit the raw replay IDs. Do not publish archive
  files as CI artifacts or commit them into source control. Common archive
  filenames are excluded by `.gitignore`, but an arbitrary `--archive` name
  may require an additional local ignore rule.
- Exact replay information survives in the candidate, although **the guard
  never consults an archive** when authorizing transitions or upgrades.
- All compaction flags remain `false`. The journal and deduplication sets are
  still unbounded.

## Atomic, no-replace creation

Under the live guard's existing exclusive lock, export:

1. Reads and validates the entire source journal.
2. Builds a snapshot-bound preflight manifest and a complete-source archive.
3. Writes and fsyncs a temporary file in the archive directory.
4. Creates the destination name using `os.link(temp, destination)`. This
   publishes a complete file and fails if the destination already exists.
5. Unlinks the temporary name and fsyncs the containing directory.
6. Opens the published archive and independently checks its checksum, full
   source state/epoch history, and the exact regenerated manifest.

Errors before step 4 leave the destination absent. An error **after** the link
may leave a complete, visible archive with unknown power-loss durability. Do
not blindly retry the export: inspect the destination explicitly, and regard
any failed fsync as inconclusive about persistence after a crash. An actual
power-loss test would be needed for stronger guarantees.

The live snapshot and archive are **two files**. Holding the guard lock ensures
consistency with cooperating processes during export, but does not make later
journal writes transactional with an older archive. The snapshot digest in the
archive is always checked against the current journal when both exist.

## CLI usage

```bash
# Absolute sibling path. Use a fresh filename for each new generation.
green-guard checkpoint-export \
  --store /home/kim/projects/green-transition-guard/device.guard.json \
  --archive /home/kim/projects/green-transition-guard/device.checkpoint-001.json

# Verify the independently validated archive against the current live journal.
green-guard checkpoint-verify \
  --store /home/kim/projects/green-transition-guard/device.guard.json \
  --archive /home/kim/projects/green-transition-guard/device.checkpoint-001.json

# Independently inspect the archive if the live journal cannot be opened.
green-guard checkpoint-inspect \
  --archive /home/kim/projects/green-transition-guard/device.checkpoint-001.json
```

- `checkpoint-export`: exit `0` on success; exit `2` for existing destination,
  malformed journal/path, or I/O errors. A failed export may still have
  published a candidate; inspect it explicitly.
- `checkpoint-verify`: exit `0` when the archived generation equals the live
  journal, exit `3` when the archive is internally valid but **stale/different**,
  and exit `2` when either source fails validation or I/O fails.
- `checkpoint-inspect`: exit `0` if the archive itself validates, even when the
  journal is missing. The `matches_current_journal` field is `null` because no
  live comparison was made. Exit `2` for invalid archives.

The summary deliberately exposes hashes and counts only, with
`journal_compaction_enabled: false` and
`authenticated_rollback_protection: false`. In Python, the verified archive
view provides an in-memory `ReplayIndex` for exact ID/argument comparison.
It must not be used to bypass the authoritative live guard.

## Remaining obligations

- Validate actual power-loss durability on a specific filesystem/hardware.
- Add an independently trusted, authenticated monotonic checkpoint root to
  distinguish a legitimate historical archive from rollback or fabrication.
- Prove complete, crash-consistent **journal-to-checkpoint transition** and
  replay/epoch/interval continuity before considering any history deletion.
- Bound accepted operation volume, including no-ops and policy revisions.
- Preserve full replay semantics when a source journal is eventually pruned.
  A standalone archive is currently unbounded and cannot itself guarantee
  bounded state size.

Tests: `tests/test_checkpoint_archive.py` (schema 1/2/3, exact replay, stale
and corrupt archives, no-clobber creation, simultaneous writers, before/after
publication fault injection, independent inspection, and CLI exit codes).
No hardware or sudden power-off experiment was performed.

## v0.1.13 identity budget compatibility

Schema-4 archives preserve the additional immutable operation-budget seal.
Standalone archive inspection reconstructs the seal's exact replay identity
from the complete source journal. The budget is a count cap on accepted IDs;
it provides neither byte-size bounds nor anti-rollback protection.
