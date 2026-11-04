"""Single-host POSIX serialized access and durable JSON snapshot storage.

A lock file serializes all cooperating writers. The checksum detects
accidental modification; it does not authenticate the persisted state.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator

try:
    import fcntl
except ImportError as exc:
    raise RuntimeError("This prototype needs Linux/WSL2 (fcntl is required)") from exc


class InvalidSnapshot(RuntimeError):
    pass


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def wrap(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload": payload, "sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}


def unwrap(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise InvalidSnapshot("invalid snapshot envelope")
    payload, hash_value = envelope["payload"], envelope["sha256"]
    if not isinstance(payload, dict) or not isinstance(hash_value, str):
        raise InvalidSnapshot("invalid snapshot envelope fields")
    if hashlib.sha256(canonical_bytes(payload)).hexdigest() != hash_value:
        raise InvalidSnapshot("snapshot checksum mismatch; fail closed")
    return payload


class SnapshotStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        if not self.path.parent.exists():
            raise FileNotFoundError(f"directory missing: {self.path.parent}")
        with open(self.lock_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as handle:
                data = json.load(handle)
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidSnapshot("snapshot JSON is corrupt") from exc
        return unwrap(data)

    def create(self, payload: dict[str, Any]) -> None:
        # An interrupted first write may leave a corrupt file; reopen then
        # fails closed. Refuse any existing file, including a corrupt one.
        with self.path.open("x", encoding="utf-8") as handle:
            json.dump(wrap(payload), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        self._sync_directory()

    def save(self, payload: dict[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            try:
                handle = os.fdopen(fd, "w", encoding="utf-8")
            except BaseException:
                # mkstemp already allocated an fd. If fdopen fails, its
                # context manager was never entered and cannot close it.
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise
            with handle:
                json.dump(wrap(payload), handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            self._sync_directory()
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _sync_directory(self) -> None:
        fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
