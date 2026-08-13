"""Small cross-process locks for bridge, scanner, and dashboard."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows launchers serialize processes.
    fcntl = None


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def process_lock(path, blocking: bool = False):
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="ascii")
    try:
        if fcntl is not None:
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(handle.fileno(), flags)
            except BlockingIOError as exc:
                raise AlreadyRunning(str(lock_path)) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
