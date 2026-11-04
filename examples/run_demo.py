"""Reproducible controller failover and sliding-window demonstration."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from green_transition_guard import Policy, TransitionGuard


with TemporaryDirectory(prefix="green-guard-") as directory:
    path = Path(directory) / "device.guard.json"
    policy_data = json.loads((Path(__file__).parent / "demo_policy.json").read_text())
    guard = TransitionGuard.initialize(
        path, device_id="switch-01", initial_state="on",
        entered_at_ms=0, policy=Policy.from_dict(policy_data),
    )
    for t, target, key in [
        (5000, "sleep", "controller-a-1"),
        (10000, "on", "controller-a-2"),
        (15000, "sleep", "controller-a-3"),
        (20000, "on", "controller-a-4"),
    ]:
        result = guard.request(target=target, request_id=key, at_ms=t)
        print(f"time={t:>5} target={target:<5} allowed={str(result.allowed):<5} "
              f"reason={result.reason:<19} retry={result.retry_at_ms}")

    # Simulated controller failover: a new controller reopens the same device.
    del guard
    guard = TransitionGuard.open(path)
    result = guard.request(target="on", request_id="controller-b-1", at_ms=30000)
    print(f"FAILOVER time=30000 allowed={result.allowed} reason={result.reason} "
          f"retry={result.retry_at_ms}")
    result = guard.request(target="on", request_id="controller-b-2", at_ms=65000)
    print(f"WINDOW-EXPIRES time=65000 allowed={result.allowed} reason={result.reason}")
    print(f"FINAL state={guard.status()['state']} revisions={guard.status()['revision']}")
