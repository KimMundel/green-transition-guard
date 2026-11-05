# Quota-history retention proof (experimental v0.1.9)

## Scope

`TransitionGuard.quota_retention_view(max_future_window_ms=...)` produces a
**read-only** quota-retention analysis. This is the first safety precondition
for potential durable history compaction. It does not modify, delete, archive
or rewrite events, no-op entries, policy epochs or request IDs.

`max_future_window_ms` is the analysis bound. On a legacy journal it remains
hypothetical. Since v0.1.10, a separate `seal-window` operation can persist an
immutable maximum for future policy windows. The report indicates when the
requested analysis bound is at least that sealed maximum; the output **still
does not authorize deletion** of any journal content.

## Window proof

For a complete accepted-event timestamp sequence `E`, a nondecreasing clock
`T0` and a *future-enforced* upper bound `Wmax` on every permitted policy
window, the following event prefix is quota-irrelevant at `T0` and afterward:

```text
expired = [e in E where e.at_ms <= T0 - Wmax]
retained = [e in E where e.at_ms > T0 - Wmax]
```

For any later observation `T >= T0` and admissible policy window
`0 < W <= Wmax`:

```text
T - W >= T0 - Wmax

therefore:
e.at_ms <= T0 - Wmax  =>  e.at_ms <= T - W
```

These events cannot be in the quota-active interval `(T-W, T]`.
The exact left boundary is excluded; timestamps may repeat. The view's
`active_count` and `release_at` methods reject timestamps before `T0` and
windows exceeding `Wmax` rather than making unsound estimates.

The plan is computed under the same per-file lock and snapshot validation as
normal guard reads. It is a detached view; future policy changes do not alter
that view's bounds. A later policy window larger than `Wmax` can invalidate
an **unsealed** or narrower-than-seal analysis. A view only reports
`retention_bound_enforced: true` when the journal's sealed maximum does not
exceed `Wmax`.

## Remaining obligations before any disk compaction

1. **Persist and enforce a maximum future window.** Available as the optional,
   one-way v0.1.10 schema-3 seal. Legacy schemas and analyses requesting a
   narrower bound remain unprotected. Authentic rollback resistance is open.
2. **Keep last-transition time.** A new policy may raise `min_interval_ms`
   arbitrarily. The most recent accepted event is needed even if quota-expired.
   State-entry time is needed for dwell constraints.
3. **Preserve idempotence and collision protection.** Historical request IDs,
   no-op IDs, and update IDs must never be accepted as new operations after
   compaction. Exact replay responses for arbitrary old IDs require retained
   identity information; a bounded conservative membership structure may
   instead reject possible replays, at the expense of false positives.
4. **Validate the historical state and policy chain.** Existing schema-2
   validation replays every edge under its policy epoch. Replacing a prefix
   needs a verifiable checkpoint with an unbroken revision/epoch boundary and
   safe recovery after partial storage failure.
5. **Bound accepted operations within the window.** A time bound alone does
   not imply a fixed number of retained transitions when quotas can increase.
   A bound on event count (or explicit fail-closed saturation) is necessary.
6. **Define trust and durability.** The existing checksum is for accidental
   corruption only. It offers no authenticated, rollback-resistant root of
   trust. None of the tests constitute a power-loss or hardware guarantee.

Because unlimited arbitrary request identifiers allow an unlimited number of
possible unique histories, exact permanent deduplication cannot be represented
in fixed finite storage without additional assumptions. Conservative rejection
of uncertain IDs is one possible design choice, requiring explicit review of
its availability cost.

## Command-line analysis

```bash
green-guard retention-plan \
  --store device.guard.json \
  --max-window-ms 60000
```

`expired_for_quota` is an **analytical count** under the requested window
ceiling. `retention_bound_enforced` reports whether this software journal
has sealed a ceiling no larger than the requested bound.
`journal_compaction_enabled` is always `false`. The output deliberately
lists unsatisfied deletion prerequisites and makes no persistent changes.

## Validation

Deterministic boundary tests and 240 randomized independent oracle histories,
including 4,800 sampled future times/windows, compare the projection with the
complete accepted-event list. Integration tests cover policy updates, replay,
old-schema handling, corrupted snapshots and the CLI. See `docs/test-report.md`.
