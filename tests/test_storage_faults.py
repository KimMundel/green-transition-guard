"""In-process POSIX persistence faults across atomic snapshot boundaries.

These inject errors around actual storage syscalls. They cannot model power
loss, torn sectors, lying filesystems or proof of durable writes after fsync
errors, and they never establish any physical-device safety guarantee.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat

import pytest

from green_transition_guard import InvalidSnapshot, Policy, TransitionGuard
from green_transition_guard.experimental_hardware import HardwareTransitionExperiment, SimulatedActuator
from green_transition_guard.storage import SnapshotStore
from green_transition_guard import storage


BEFORE_REPLACE = ("temp-create", "temp-fdopen", "partial-write", "buffer-flush", "file-fsync", "replace-before")
AFTER_REPLACE = ("replace-after", "directory-open", "directory-fsync")
SAVE_FAILURE_POINTS = BEFORE_REPLACE + AFTER_REPLACE


@contextmanager
def fail_save_at(monkeypatch, store: SnapshotStore, stage: str):
    """Raise one simulated OSError at a named step of save(), then restore OS calls."""
    fired = []
    captured = {}

    def fail():
        fired.append(stage)
        raise OSError(f"injected {stage} failure")

    with monkeypatch.context() as m:
        prefix = f".{store.path.name}."
        if stage == "temp-create":
            original = storage.tempfile.mkstemp

            def mkstemp(*args, **kwargs):
                if kwargs.get("prefix") == prefix and Path(kwargs["dir"]) == store.path.parent:
                    fail()
                return original(*args, **kwargs)

            m.setattr(storage.tempfile, "mkstemp", mkstemp)
        elif stage in {"temp-fdopen", "buffer-flush"}:
            original = storage.os.fdopen

            def fdopen(fd, *args, **kwargs):
                is_target = Path(os.readlink(f"/proc/self/fd/{fd}")).name.startswith(prefix)
                if is_target and stage == "temp-fdopen":
                    captured["fd"] = fd
                    fail()
                handle = original(fd, *args, **kwargs)
                if not is_target:
                    return handle

                class FlushFailingFile:
                    def __enter__(self):
                        handle.__enter__()
                        return self

                    def __exit__(self, *args):
                        return handle.__exit__(*args)

                    def write(self, data):
                        return handle.write(data)

                    def flush(self):
                        fail()

                    def fileno(self):
                        return handle.fileno()

                return FlushFailingFile()

            m.setattr(storage.os, "fdopen", fdopen)
        elif stage == "partial-write":
            original = storage.json.dump

            def dump(value, handle, **kwargs):
                if Path(os.readlink(f"/proc/self/fd/{handle.fileno()}")).name.startswith(prefix):
                    handle.write('{"payload":')
                    fail()
                return original(value, handle, **kwargs)

            m.setattr(storage.json, "dump", dump)
        elif stage == "file-fsync":
            original = storage.os.fsync

            def fsync(fd):
                if (stat.S_ISREG(os.fstat(fd).st_mode) and
                        Path(os.readlink(f"/proc/self/fd/{fd}")).name.startswith(prefix)):
                    fail()
                return original(fd)

            m.setattr(storage.os, "fsync", fsync)
        elif stage == "directory-open":
            original = storage.os.open

            def open_directory(path, flags, *args, **kwargs):
                if Path(path) == store.path.parent and flags & storage.os.O_DIRECTORY:
                    fail()
                return original(path, flags, *args, **kwargs)

            original_sync = store._sync_directory

            def sync_with_directory_open_failure():
                with m.context() as scoped:
                    scoped.setattr(storage.os, "open", open_directory)
                    return original_sync()

            m.setattr(store, "_sync_directory", sync_with_directory_open_failure)
        elif stage == "directory-fsync":
            m.setattr(store, "_sync_directory", fail)
        elif stage in {"replace-before", "replace-after"}:
            original = storage.os.replace

            def replace(source, destination):
                if Path(destination) == store.path:
                    if stage == "replace-before":
                        fail()
                    original(source, destination)
                    fail()  # In-process exception after successful replacement.
                return original(source, destination)

            m.setattr(storage.os, "replace", replace)
        else:
            raise AssertionError(f"unrecognized injection stage: {stage}")
        try:
            yield captured
        finally:
            assert fired == [stage], f"fault point {stage} was never reached"


def test_initial_write_exclusive_open_failure_is_retryable(tmp_path, monkeypatch):
    path = tmp_path / "device.guard.json"
    store = SnapshotStore(path)
    original = Path.open
    fired = []

    def fail_exclusive_open(self, mode="r", *args, **kwargs):
        if self == path and mode == "x":
            fired.append(1)
            raise OSError("injected exclusive-open error")
        return original(self, mode, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "open", fail_exclusive_open)
        with pytest.raises(OSError, match="exclusive-open"):
            store.create({"revision": 0})
    assert fired == [1]
    assert not path.exists()
    store.create({"revision": 0})
    assert store.read() == {"revision": 0}


@pytest.mark.parametrize("stage", ["partial-write", "file-fsync", "directory-fsync"])
def test_initial_write_failure_does_not_allow_reset(tmp_path, monkeypatch, stage):
    path = tmp_path / "device.guard.json"
    store = SnapshotStore(path)
    with monkeypatch.context() as m:
        if stage == "partial-write":
            def dump(_value, handle, **_kwargs):
                handle.write('{"payload":')
                raise OSError("partial write")

            m.setattr(storage.json, "dump", dump)
        elif stage == "file-fsync":
            original = storage.os.fsync

            def fsync(fd):
                if stat.S_ISREG(os.fstat(fd).st_mode):
                    raise OSError("file fsync")
                return original(fd)

            m.setattr(storage.os, "fsync", fsync)
        else:
            original = storage.os.fsync

            def fsync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("directory fsync")
                return original(fd)

            m.setattr(storage.os, "fsync", fsync)
        with pytest.raises(OSError):
            store.create({"revision": 0})

    # After an exclusive create, a failed first write must not reset a
    # possibly-used journal. Operators must handle an ambiguous startup.
    assert path.exists()
    with pytest.raises(FileExistsError):
        store.create({"revision": 0})
    if stage == "partial-write":
        with pytest.raises(InvalidSnapshot):
            store.read()
    else:
        # A visible valid file does not establish physical durability of the
        # fsync operation that reported failure.
        assert store.read() == {"revision": 0}


@pytest.mark.parametrize("stage", SAVE_FAILURE_POINTS)
def test_atomic_save_preserves_valid_old_or_new_snapshot(tmp_path, monkeypatch, stage):
    store = SnapshotStore(tmp_path / "journal.json")
    store.create({"revision": 0, "events": []})
    with fail_save_at(monkeypatch, store, stage) as captured:
        with pytest.raises(OSError):
            store.save({"revision": 1, "events": ["edge-1"]})
    if stage == "temp-fdopen":
        with pytest.raises(OSError):
            os.fstat(captured["fd"])  # A rejected fdopen must release mkstemp's fd.
    visible_revision = 0 if stage in BEFORE_REPLACE else 1
    assert store.read()["revision"] == visible_revision
    assert list(tmp_path.glob(".journal.json.*")) == []
    store.save({"revision": 2, "events": ["edge-1", "edge-2"]})
    assert store.read()["revision"] == 2


def policy():
    return Policy(states=("on", "sleep"), edges=(("on", "sleep"), ("sleep", "on")),
                  min_dwell_ms={"on": 0, "sleep": 0}, min_interval_ms=0,
                  window_ms=100, max_transitions=1)


def lab(tmp_path):
    hw = SimulatedActuator.initialize(tmp_path / "hardware.json", energy_object_id="eo-1", initial_state="on")
    guard = HardwareTransitionExperiment.initialize(tmp_path / "guard.json", actuator=hw,
                                                     policy=policy(), energy_object_id="eo-1",
                                                     entered_at_ms=0)
    assert guard.prepare(op_id="op-1", target="sleep", at_ms=1).reason == "prepared"
    return guard, hw


@pytest.mark.parametrize("stage", SAVE_FAILURE_POINTS)
def test_dispatch_marker_fault_never_sends_hardware_command(tmp_path, monkeypatch, stage):
    guard, hw = lab(tmp_path)
    with fail_save_at(monkeypatch, guard.store, stage):
        with pytest.raises(OSError):
            guard.dispatch(op_id="op-1", at_ms=2)
    assert hw.snapshot()["counter"] == 0
    recovered = HardwareTransitionExperiment.open(guard.store.path, actuator=hw)
    expected = "prepared" if stage in BEFORE_REPLACE else "may-have-dispatched"
    assert recovered.status()["pending"]["phase"] == expected
    if stage in AFTER_REPLACE:
        assert recovered.dispatch(op_id="op-1", at_ms=3).reason == "dispatch-unavailable"
        assert recovered.reconcile(at_ms=3).reason == "unresolved"
    else:
        assert recovered.abort_prepared(op_id="op-1").reason == "aborted-before-dispatch"
    assert hw.snapshot()["counter"] == 0


@pytest.mark.parametrize("stage", SAVE_FAILURE_POINTS)
def test_actuator_write_fault_never_retries_ambiguous_command(tmp_path, monkeypatch, stage):
    guard, hw = lab(tmp_path)
    with fail_save_at(monkeypatch, hw.store, stage):
        with pytest.raises(OSError):
            guard.dispatch(op_id="op-1", at_ms=2)
    recovered = HardwareTransitionExperiment.open(guard.store.path, actuator=hw)
    assert recovered.status()["pending"]["phase"] == "may-have-dispatched"
    assert recovered.dispatch(op_id="op-1", at_ms=3).reason == "dispatch-unavailable"
    expected = 0 if stage in BEFORE_REPLACE else 1
    assert hw.snapshot()["counter"] == expected
    result = recovered.reconcile(at_ms=4)
    assert result.reason == ("unresolved" if stage in BEFORE_REPLACE else "verified")
    assert hw.snapshot()["counter"] == expected


@pytest.mark.parametrize("stage", SAVE_FAILURE_POINTS)
def test_reconciliation_write_fault_never_duplicates_physical_edge(tmp_path, monkeypatch, stage):
    guard, hw = lab(tmp_path)
    assert guard.dispatch(op_id="op-1", at_ms=2).reason == "acknowledged"
    with fail_save_at(monkeypatch, guard.store, stage):
        with pytest.raises(OSError):
            guard.reconcile(at_ms=3)
    recovered = HardwareTransitionExperiment.open(guard.store.path, actuator=hw)
    if stage in BEFORE_REPLACE:
        assert recovered.status()["revision"] == 0
        assert recovered.reconcile(at_ms=4).reason == "verified"
    else:
        assert recovered.status()["revision"] == 1
        assert recovered.reconcile(at_ms=4).reason == "nothing-to-reconcile"
    assert hw.snapshot()["counter"] == 1
    assert recovered.status()["revision"] == 1


@pytest.mark.parametrize("stage", SAVE_FAILURE_POINTS)
def test_logical_guard_write_fault_does_not_bypass_quota(tmp_path, monkeypatch, stage):
    path = tmp_path / "device.guard.json"
    guard = TransitionGuard.initialize(path, device_id="dev-1", policy=policy(),
                                       initial_state="on", entered_at_ms=0)
    with fail_save_at(monkeypatch, guard.store, stage):
        with pytest.raises(OSError):
            guard.request(target="sleep", at_ms=1, request_id="id-1")
    recovered = TransitionGuard.open(path)
    if stage in BEFORE_REPLACE:
        assert recovered.status()["revision"] == 0
    else:
        assert recovered.status()["revision"] == 1
        assert recovered.request(target="sleep", at_ms=2, request_id="id-1").reason.value == "replay"
        assert recovered.request(target="on", at_ms=3, request_id="id-2").reason.value == "rate-limit"
    assert recovered.status()["revision"] <= 1
