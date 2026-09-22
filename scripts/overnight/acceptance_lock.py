"""Cross-process lock for overnight scheduled-output acceptance."""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from scripts.overnight.store import OvernightStore

_thread_locks: dict[tuple[str, str], threading.Lock] = {}
_registry_lock = threading.Lock()


def _thread_lock(state_root: Path, run_id: str) -> threading.Lock:
    key = (str(state_root.resolve()), run_id)
    with _registry_lock:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


@contextmanager
def overnight_acceptance_lock(store: OvernightStore, overnight_run_id: str) -> Iterator[None]:
    state_root = store.state_root
    lock_dir = state_root / "data" / "overnight" / ".acceptance-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{overnight_run_id}.lock"
    tlock = _thread_lock(state_root, overnight_run_id)
    tlock.acquire()
    lock_file = None
    try:
        lock_file = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if lock_file is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        tlock.release()
