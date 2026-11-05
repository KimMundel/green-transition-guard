# Durable future policy-window ceiling (experimental v0.1.10)

## Contract

An explicit `seal_window_ceiling()` operation converts a schema-1 or schema-2
simulated guard journal to **schema 3**, retaining the complete event/no-op
history and policy epoch log. It persists an immutable `window_ceiling` record:

- `max_window_ms`: positive integer ceiling for every policy activated **after sealing**
- `id`: one unique installation idempotency key (shared namespace with requests and policy changes)
- `at_ms`: the same monotonic millisecond clock domain used by the guard
- `after_event_seq`: last accepted transition sequence at installation
- `after_policy_revision`: last active policy revision at installation

The initial/current policy must be at or below the ceiling when it is sealed.
Older epochs may have used larger windows; historical legality is preserved.
The ceiling applies at equality (`window_ms <= max_window_ms`). Attempts to
activate larger windows fail before writing. All later reads validate that
both the policy at installation and every subsequent policy honor the bound.
The seal is one-way: the supported API offers no replacement, enlargement,
reduction, or removal. A caller must plan its value carefully.

## API example

```python
from green_transition_guard import TransitionGuard

guard = TransitionGuard.open("device.guard.json")
status = guard.status()
ceiling = guard.seal_window_ceiling(
    max_future_window_ms=60_000,
    install_id="seal-001",
    at_ms=123_456,
    expected_policy_revision=status["policy_revision"],
)
assert ceiling == 60_000
```

Or via CLI:

```bash
green-guard seal-window \
  --store device.guard.json \
  --max-window-ms 60000 \
  --install-id seal-001 \
  --time-ms 123456 \
  --expected-policy-revision 0
```

Use a real monotonic and persistent time domain in a production implementation;
the sample timestamp is illustrative. Installation requires the caller's last
observed policy revision. File locking provides single-host writer exclusion.
Replaying the original installation ID with the same ceiling returns the
committed value; the timestamp must remain nondecreasing. A distinct ID,
or the same ID with a different ceiling, is rejected after sealing.

## Retention analysis

`retention-plan` remains read-only. It emits:

- `enforced_ceiling_ms`: persisted ceiling, or `null` for older schemas
- `retention_bound_enforced`: `true` only when the analysis bound is at least
  as large as the persisted ceiling
- `journal_compaction_enabled`: always `false`

The analytical premise is now enforceable by this simulated software version.
**No history is deleted or compacted.** Exact request ID replay/collision
behavior, policy-epoch chain validation, last-transition interval anchors,
operation volume limits, and crash-consistent checkpoint installation remain
unsolved prerequisites for physical compaction.

## Safety and compatibility limits

- Schema-3 files are **unreadable** to v0.1.9 and earlier. Do not downgrade
  readers or attempt to reopen sealed journals using older binaries.
- This is a **single-host, simulated logical guard**. The physical actuator
  experiment and experimental YANG module are unchanged.
- The checksum detects accidental file corruption. It provides **no signature,
  trusted monotonic clock, rollback prevention, or authorization**. A caller
  with filesystem write access can restore an older schema or rewrite the
  journal. Hardware and standards compliance remain unverified.
- Failure **after** `os.replace()` leaves on-media durability unproven. Reopen,
  validate, and reconcile the installation ID before retrying after any I/O
  error. The tests do not simulate a real sudden power failure.
- The event log, no-op IDs and policy epochs remain unbounded.

## Verification

See `tests/test_window_ceiling.py` and `docs/test-report.md` for migration,
replay, stale revisions, post-seal update enforcement, corrupt snapshot,
CLI and persistence-failure regressions.
