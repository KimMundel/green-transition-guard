# Storage failure boundaries — experimental v0.1.7

This is a deterministic **in-process POSIX fault-injection** suite. It exercises
`SnapshotStore` and the simulated guard / actuator ledgers. It does **not**
validate power-loss behavior of any filesystem or hardware controller.

## Boundaries exercised

| Persisted operation | Injected error | In-process snapshot after exception |
|---|---|---|
| Initial create | exclusive open fails | absent; explicit initialization may retry |
| Initial create | partial JSON write | incomplete; subsequent open fails closed, creation refuses overwrite |
| Initial create | file fsync or directory fsync fails | visible, checksum-valid, **durability unproven**; creation refuses overwrite |
| Replace | `mkstemp` fails | prior snapshot intact |
| Replace | `os.fdopen` fails | prior snapshot intact; allocated descriptor closed |
| Replace | partial JSON write / flush fails | prior snapshot intact; temporary file cleaned |
| Replace | temporary-file fsync fails | prior snapshot intact; temporary file cleaned |
| Replace | failure before `os.replace` | prior snapshot intact; temporary file cleaned |
| Replace | failure immediately after successful `os.replace` | new snapshot visible, **durability unproven** |
| Replace | directory open / fsync fails after replace | new snapshot visible, **durability unproven** |

Only files from the chosen journal are targeted; failure instrumentation must
not accidentally affect the independent actuator or controller journal.

## Invariants checked after reopening

1. A completed snapshot has a valid checksum and event/history structure.
2. A failed save before replacement preserves the old revision. After
   replacement, the in-process view may contain the newer revision, even if
   durability could not be confirmed by the failed operation.
3. If a controller dispatch marker raises before the actuator call, the
   simulated actuator has zero new edges. A visible `may-have-dispatched`
   marker blocks resend until reconciliation.
4. If actuator persistence raises, the controller has an unresolved dispatch
   possibility; it cannot automatically resend. A visible matching actuator
   event may be reconciled once; absent evidence remains unresolved.
5. A failed reconciliation write never triggers another actuator command.
6. The logical guard replays an accepted request ID and enforces its rolling
   quota if the updated snapshot is visible after failure.

## Known boundaries outside the test claim

- Abrupt power loss, torn sectors, delayed filesystem journal replay, unreliable
  storage cache flushes, disk/RAID firmware behavior, file descriptor reuse
  during concurrent failures, and `fsync` completion misreporting.
- Effects from errors in lock acquisition/release, unexpected directory
  deletion, cleanup unlink failure, or OS resource exhaustion across multiple
  writers. Existing file locking and snapshot validation still apply.
- A checksum detects accidental corruption and has no cryptographic trust
  guarantee against deliberate modification or counter rollback.
- The independent simulated actuator ledger is not a production physical
  edge source. Real safety requires an authoritative, reset-resistant counter,
  correct fencing, independent readback, and proven clock/storage guarantees.

The test helper raises `OSError` at selected real call boundaries. For the
post-replace case, it executes `os.replace` successfully and then raises to
model losing certainty about the result. A real kernel crash or power loss can
expose states beyond this deterministic in-process model.

Reproduction: `PYTHONPATH=src python3 -m pytest -q tests/test_storage_faults.py`.
