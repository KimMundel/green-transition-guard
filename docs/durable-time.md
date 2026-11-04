# Durable timekeeping research (2026-11-04)

**Status: experiment and design analysis.** A production implementation must supply
and validate clock evidence. These notes make no claim about hardware safety.

## Problem statement

Safety limits such as `min-dwell`, `min-interval`, and a rolling transition
budget need elapsed time. The existing v0.1 engine takes caller-supplied integer
milliseconds from a single assumed clock epoch. The engine detects regressions
within that epoch but cannot detect a fabricated forward jump. The single
integer timeline is insufficient for a rebooting real device.

A power loss can produce two physically possible histories with identical
journal contents and identical boot uptime after restart: (A) 1 second offline,
(B) 2 hours offline. With no other clock evidence, software cannot distinguish
them. The only safe algorithmic statement about expired quotas is **unknown**.

## Source comparison

| Source | Can measure suspended time? | Can span boot? | Qualification |
|---|---|---|---|
| Linux CLOCK_MONOTONIC | No | No | Reliable order within a boot; affected by frequency corrections |
| Linux CLOCK_BOOTTIME | Yes | No | Preferred within-boot elapsed source, conditional on kernel availability |
| Linux CLOCK_REALTIME | Yes in principle | Yes in principle | Subject to jumps, NTP correction, administrative changes and RTC errors |
| Battery-backed RTC | Usually | Often | Only with verified integrity, power, drift bound, and monotonicity assumptions |
| NTP-based synchronization | External time reference | On reacquisition | Need authentication, error bounds, and holdover handling; clock sync alone is insufficient |
| TPM clock | Depends on TPM's power state | Clock has continuity metadata | TPM clock is powered-time evidence; it cannot alone prove time spent fully unpowered |

The Linux kernel explicitly advises use of boottime for suspend-aware relative
timing and warns that realtime may jump. systemd-timesyncd keeps approximate
reboot continuity on systems without battery-backed RTC; this mechanism is not
an authoritative bound for a safety-critical decision.

References:
- https://docs.kernel.org/core-api/timekeeping.html
- https://www.man7.org/linux/man-pages/man3/clock_gettime.3.html
- https://www.freedesktop.org/software/systemd/man/260/systemd-timesyncd.html
- https://trustedcomputinggroup.org/wp-content/uploads/TPM-2.0-1.83-Part-2-Structures.pdf

## Proposed evidence contract

Persist each observed physical transition with:

- a unique boot epoch ID and a `CLOCK_BOOTTIME` interval `[b_min, b_max]`;
- optional **validated** absolute-time interval `[u_min, u_max]`;
- source/quality/provenance metadata, which future implementations must check;
- event identity, protected event history, and the applicable policy version.

The interval represents a guarantee: actual time lies within the endpoints.
It cannot be built by simply relabeling `time.time()` as trusted. Bounds need
actual source-specific error accounting, including oscillator drift,
communication delay, RTC holdover, and clock corrections.

For an event E and later observation N, compute a **lower bound on elapsed
time** using comparable intervals:

    elapsed_min = max(0, N.lower - E.upper)

Apply this separately to same-boot boottime and available trusted absolute
time; intersect the resulting possible-elapsed ranges. Contradictory evidence
must fail closed. If no comparable domain exists, elapsed is unknown.

For a positive window W, E is **definitely expired** only if
`elapsed_min >= W`. This agrees with the existing rolling-window `(T-W, T]`
semantics. For a minimum dwell D, a transition can pass the time check only
if `elapsed_min >= D`. Events with unknown expiry continue to consume quota.

The working implementation `experimental_time.py` evaluates these conditions
with injected evidence; it does not obtain or authenticate clocks.

### Worked example

Event E's possible absolute occurrence: `[1000, 1100]` ms.
Current trusted time: `[61099, 61500]` ms; window 60000 ms.
Earliest possible elapsed time = 61099 - 1100 = 59999 ms.
The event could still be active. At current lower bound 61100 ms the event
is definitely expired, using the end-exclusive window boundary.

## Recovery modes for future implementation

- `TIME_OK_SAME_BOOT`: use suspend-aware monotonic clock evidence.
- `TIME_OK_CROSS_BOOT`: validated absolute intervals permit comparison.
- `TIME_UNCERTAIN`: history intact; retain potentially active events, refuse
  unprovable automated transitions, and report `retry-at: unknown`.
- `TIME_CONTRADICTORY`: reject and require clock-source reconciliation.
- `HISTORY_MISSING`: automatic transition safety cannot be established;
  escalate according to an explicit recovery policy.

A reboot with only boot-relative clocks cannot automatically unlock a blocked
state, regardless of the duration of downtime. Operators may define tightly
scoped audited emergency actions; any bypass is outside the ordinary safety
proof and needs vendor guidance.

## Trust and security requirements

1. Local device/firmware must authenticate and bound observations; the
   controller's arbitrary client-supplied clock must be rejected.
2. Prevent rewriting history or boot identifiers by untrusted actors. Current
   SHA-256 snapshot checksum detects accidental corruption only.
3. Use crash-consistent storage and an independent powered management domain
   where possible. A journal stored on the powered-off component may be
   inaccessible at the moment it is needed.
4. Source drift, leap/time step handling, and replica disagreement must be
   specified before claiming elapsed-time guarantees.
5. A healthy clock does not resolve **unknown hardware execution**; hardware
   feedback and conservative attempt accounting remain necessary.

## Verification required before deployment

- Cross-boot uncertainty: retain quota with no trusted absolute anchor.
- RTC rollback/large forward step: reject weak/unbounded clock evidence.
- NTP holdover: widen intervals over time using a justified drift bound.
- Suspends, clock adjustment, reboot, prolonged power loss, and storage loss.
- Physical event timestamps recorded near the **actuation point**, with
  uncertainties including command propagation and telemetry latency.

Open decision: determine whether the target class provides a trustworthy RTC
or device-side nonvolatile cycle counter. Without either, strong cross-boot
availability and safety guarantees are incompatible under arbitrary outage.
