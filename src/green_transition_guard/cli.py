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
    checkpoint = sub.add_parser("checkpoint-plan", help="read-only replay and checkpoint preflight")
    checkpoint.add_argument("--store", required=True)
    inspect = sub.add_parser("checkpoint-inspect", help="independently inspect archived history")
    inspect.add_argument("--archive", required=True)
    archive = sub.add_parser("checkpoint-export", help="create-only complete-history archive; no compaction")
    archive.add_argument("--store", required=True)
    archive.add_argument("--archive", required=True, help="absolute sibling path for immutable archive")
    verify = sub.add_parser("checkpoint-verify", help="verify checkpoint archive and current generation")
    verify.add_argument("--store", required=True)
    verify.add_argument("--archive", required=True)
    lineage = sub.add_parser("checkpoint-lineage", help="read-only archive/live ancestry comparison")
    lineage.add_argument("--store", required=True)
    lineage.add_argument("--archive", required=True)
    witness_issue = sub.add_parser("checkpoint-witness-issue", help="experimental HMAC receipt for an external witness")
    witness_issue.add_argument("--archive", required=True)
    witness_issue.add_argument("--key-file", required=True, help="owner-only external witness key (never print)")
    witness_issue.add_argument("--generation", type=int, required=True)
    witness_issue.add_argument("--witness-id", required=True)
    witness_verify = sub.add_parser("checkpoint-witness-verify", help="verify receipt against externally trusted root")
    witness_verify.add_argument("--archive", required=True)
    witness_verify.add_argument("--receipt", required=True)
    witness_verify.add_argument("--key-file", required=True)
    witness_verify.add_argument("--expected-device-id", required=True)
    witness_verify.add_argument("--trusted-min-generation", type=int, required=True)
    witness_verify.add_argument("--trusted-snapshot-sha256", required=True)
    seal = sub.add_parser("seal-window", help="one-way durable bound for future policy windows")
    seal.add_argument("--store", required=True)
    seal.add_argument("--max-window-ms", type=int, required=True)
    seal.add_argument("--install-id", required=True)
    seal.add_argument("--time-ms", type=int, required=True)
    seal.add_argument("--expected-policy-revision", type=int, required=True)
    budget = sub.add_parser("seal-budget", help="one-way limit on accepted operation identities")
    budget.add_argument("--store", required=True)
    budget.add_argument("--max-identities", type=int, required=True)
    budget.add_argument("--install-id", required=True)
    budget.add_argument("--time-ms", type=int, required=True)
    budget.add_argument("--expected-policy-revision", type=int, required=True)
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
        elif args.cmd == "checkpoint-inspect":
            from .experimental_archive import inspect_checkpoint_archive
            out = inspect_checkpoint_archive(args.archive).to_dict()
        elif args.cmd in ("checkpoint-witness-issue", "checkpoint-witness-verify"):
            from .experimental_witness import (
                issue_checkpoint_witness, load_checkpoint_receipt,
                load_witness_key, verify_checkpoint_witness,
            )
            secret = load_witness_key(args.key_file)
            if args.cmd == "checkpoint-witness-issue":
                out = issue_checkpoint_witness(
                    args.archive, secret=secret, generation=args.generation, witness_id=args.witness_id
                )
            else:
                out = verify_checkpoint_witness(
                    args.archive, load_checkpoint_receipt(args.receipt), secret=secret,
                    expected_device_id=args.expected_device_id,
                    trusted_min_generation=args.trusted_min_generation,
                    trusted_snapshot_sha256=args.trusted_snapshot_sha256,
                ).to_dict()
        else:
            guard = TransitionGuard.open(args.store)
            if args.cmd == "status":
                out = guard.status()
            elif args.cmd == "retention-plan":
                out = guard.quota_retention_view(
                    max_future_window_ms=args.max_window_ms
                ).to_dict()
            elif args.cmd == "checkpoint-plan":
                out = guard.checkpoint_preflight().to_dict()
            elif args.cmd == "checkpoint-lineage":
                out = guard.compare_checkpoint_lineage(args.archive).to_dict()
            elif args.cmd == "checkpoint-export":
                out = guard.create_checkpoint_archive(args.archive).to_dict()
            elif args.cmd == "checkpoint-verify":
                out = guard.verify_checkpoint_archive(args.archive).to_dict()
            elif args.cmd == "seal-budget":
                total = guard.seal_operation_budget(
                    max_total_ids=args.max_identities, install_id=args.install_id,
                    at_ms=args.time_ms, expected_policy_revision=args.expected_policy_revision,
                )
                out = {"operation_budget_max": total, "status": guard.status()}
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
        if args.cmd == "checkpoint-verify":
            return 0 if out["matches_current_journal"] else 3
        if args.cmd == "checkpoint-lineage":
            return 0 if out["relation"] in ("identical", "archive_ancestor") else 3
        if args.cmd == "checkpoint-witness-verify":
            return 0 if out["trusted_generation_floor_satisfied"] else 3
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
