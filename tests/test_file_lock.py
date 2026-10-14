import fcntl

import pytest

from src.foundation.utils.file_lock import file_lock


def _try_lock(path):
    """Take the lock without waiting, through a separate open of the file (as another
    process would); returns whether it was free."""
    with path.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(f, fcntl.LOCK_UN)
        return True


def test_lock_is_held_inside_the_block_and_released_after(tmp_path):
    path = tmp_path / "new_dir" / "x.lock"
    with file_lock(path):
        assert path.exists()  # parent made
        assert not _try_lock(path)
    assert _try_lock(path)


def test_lock_is_released_when_the_block_raises(tmp_path):
    path = tmp_path / "x.lock"
    with pytest.raises(RuntimeError):
        with file_lock(path):
            raise RuntimeError
    assert _try_lock(path)


def test_callers_keep_their_lock_file_names(tmp_path):
    # The name is what processes agree on: these are the names code already running uses.
    from src.llm.paths import locked

    with locked(tmp_path / "gemini_usage.jsonl"):
        assert not _try_lock(tmp_path / "gemini_usage.lock")
