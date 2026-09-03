import time
from typing import Callable, TypeVar

T = TypeVar("T")


def attempt_with_limited_retries(
    fn: Callable[[], T], max_attempts: int = 2, backoff_seconds: float = 5.0
) -> tuple[bool, T | None, str | None]:
    """Call `fn()` up to `max_attempts` times with a short backoff between
    attempts. Returns (True, result, None) on success, or (False, None, error)
    once attempts are exhausted.

    Deliberately capped low -- this is not meant to loop until something
    succeeds. The caller is expected to persist the failure (e.g. via
    fetch_jobs) and move on to the next item; a later run retries misses
    rather than this function retrying indefinitely in place.
    """
    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return True, fn(), None
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < max_attempts:
                time.sleep(backoff_seconds)
    return False, None, last_error
