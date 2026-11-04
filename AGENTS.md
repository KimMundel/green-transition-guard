# Repository instructions for coding agents

Project: independent experimental reference implementation, not a certified
safety controller or IETF-endorsed deliverable.

Rules:
1. Preserve fail-closed behavior after storage or clock uncertainty.
2. Add regression tests for changes to semantics. Run `pytest -q`.
3. Never claim physical hardware protection from simulator-only tests.
4. Avoid dependency expansion unless objectively needed.
5. Keep source of truth at the device-side guard; controller restart must
   never reset the accepted transition history.
6. Do not modify, delete, or rewrite historical events to make tests pass.
7. Do not push directly to `main`; prepare local changes for PR review.
8. No paid API services or hidden external telemetry.
9. No automatic GitHub or email operations through the coding agent.
10. Follow `docs/semantics.md` for experimental choices; preserve open questions.
