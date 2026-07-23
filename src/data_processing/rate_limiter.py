import time
from collections import deque


class RateLimiter:
    """Sliding-window rate limiter: `wait()` blocks until issuing another call
    would stay within `max_calls` per `period_seconds`.

    This is deliberately proactive rather than reactive -- the library we call
    Polygon through retries on 429 with a sub-second backoff (tuned for
    transient blips, not a hard per-minute budget), so relying on it alone
    means hammering into repeated 429s instead of just not exceeding the
    limit in the first place.
    """

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._call_times: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()
        self._evict_expired(now)
        if len(self._call_times) >= self.max_calls:
            sleep_for = self.period_seconds - (now - self._call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._evict_expired(time.monotonic())
        self._call_times.append(time.monotonic())

    def _evict_expired(self, now: float) -> None:
        while self._call_times and now - self._call_times[0] >= self.period_seconds:
            self._call_times.popleft()
