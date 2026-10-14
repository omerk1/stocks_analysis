"""An exclusive file lock between processes, for files several processes append to or
read-merge-write (the Gemini usage ledger, the unsupported-requests log, the level
cache's manifest). Unix only (`fcntl`).
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(lock_path: Path):
    """Hold an exclusive lock on `lock_path` (created, with its parent, if missing) for
    the body of the `with`. Callers name the lock file themselves: the name is what two
    processes agree on, so it must not change under code that's already running."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
