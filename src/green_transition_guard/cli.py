"""Small command-line demonstration interface."""
import argparse
import json
import sys

from .engine import TransitionGuard
from .model import Policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Experimental simulated power-state guard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="create a new device simulator")
    init.add_argument("--store", required=True)
    init.add_argument("--policy", required=True, help="JSON policy path")
    init.add_argument("--device-id", required=True)
    init.add_argument("--state", required=True)
    init.add_argument("--time-ms", type=int, required=True)
    status = sub.add_parser("status")
    status.add_argument("--store", required=True)
    request = sub.add_parser("request")
    request.add_argument("--store", required=True)
    request.add_argument("--target", required=True)
    request.add_argument("--request-id", required=True)
    request.add_argument("--time-ms", type=int, required=True)
    request.add_argument("--expected-revision", type=int)
    request.add_argument("--expected-policy-revision", type=int)
    update = sub.add_parser("update-policy", help="activate a new simulated policy without resetting history")
    update.add_argument("--store", required=True)
    update.add_argument("--policy", required=True, help="new JSON policy path")
    update.add_argument("--update-id", required=True, help="unique idempotency key")
    update.add_argument("--time-ms", type=int, required=True)
    update.add_argument("--expected-policy-revision", type=int, required=True)
    retention = sub.add_parser("retention-plan", help="read-only quota-history projection; never deletes events")
    retention.add_argument("--store", required=True)
    retention.add_argument("--max-window-ms", type=int, required=True)
    seal = sub.add_parser("seal-window", help="one-way durable bound for future policy windows")
    seal.add_argument("--store", required=True)
    seal.add_argument("--max-window-ms", type=int, required=True)
    seal.add_argument("--install-id", required=True)
    seal.add_argument("--time-ms", type=int, required=True)
    seal.add_argument("--expected-policy-revision", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.cmd == "init":
            with open(args.policy, encoding="utf-8") as f:
                policy = Policy.from_dict(json.load(f))
            guard = TransitionGuard.initialize(
                args.store, device_id=args.device_id, policy=policy,
                initial_state=args.state, entered_at_ms=args.time_ms,
            )
            out = guard.status()
        else:
            guard = TransitionGuard.open(args.store)
            if args.cmd == "status":
                out = guard.status()
            elif args.cmd == "retention-plan":
                out = guard.quota_retention_view(
                    max_future_window_ms=args.max_window_ms
                ).to_dict()
            elif args.cmd == "seal-window":
                ceiling = guard.seal_window_ceiling(
                    max_future_window_ms=args.max_window_ms,
                    install_id=args.install_id, at_ms=args.time_ms,
                    expected_policy_revision=args.expected_policy_revision,
                )
                out = {"window_ceiling_ms": ceiling, "status": guard.status()}
            elif args.cmd == "update-policy":
                with open(args.policy, encoding="utf-8") as f:
                    new_policy = Policy.from_dict(json.load(f))
                revision = guard.update_policy(
                    new_policy=new_policy, update_id=args.update_id,
                    at_ms=args.time_ms,
                    expected_policy_revision=args.expected_policy_revision,
                )
                out = {"policy_revision": revision, "status": guard.status()}
            else:
                out = guard.request(target=args.target, request_id=args.request_id,
                                    at_ms=args.time_ms,
                                    expected_revision=args.expected_revision,
                                    expected_policy_revision=args.expected_policy_revision).to_dict()
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
