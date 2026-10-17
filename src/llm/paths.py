"""Where the LLM code keeps its local, git-ignored files: `data/llm/` in the main checkout.

Found through git, so every worktree writes to the same place: the Gemini usage ledger
charges one daily total, and the unsupported-requests log collects every session's
requests instead of each worktree keeping its own.
"""

from __future__ import annotations

import subprocess
from contextlib import AbstractContextManager
from pathlib import Path

from src.foundation.utils.file_lock import file_lock


def locked(path: Path) -> AbstractContextManager[None]:
    """A context manager holding an exclusive lock on `path` (through a `.lock` file next
    to it, see `file_lock`), so processes in different worktrees don't interleave their
    writes. Unix only (`fcntl`).

    The lock file replaces the suffix (`gemini_usage.jsonl` -> `gemini_usage.lock`): that
    name is the one older code locks, and two names for one ledger would be two locks."""
    return file_lock(path.with_suffix(".lock"))


def llm_data_dir() -> Path:
    """`data/llm/` in the main checkout, from any worktree."""
    here = Path(__file__).resolve().parent
    try:
        # Without --path-format (git >= 2.31 only), the answer may be relative to `cwd`.
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=here,
        ).stdout.strip()
        root = (here / common).resolve().parent
    except (OSError, subprocess.CalledProcessError):
        root = Path(__file__).resolve().parents[2]
    return root / "data" / "llm"
