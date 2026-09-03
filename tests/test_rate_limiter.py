import time

from src.foundation.data_processing.rate_limiter import RateLimiter


def test_allows_max_calls_without_waiting():
    limiter = RateLimiter(max_calls=3, period_seconds=1.0)

    start = time.monotonic()
    for _ in range(3):
        limiter.wait()
    elapsed = time.monotonic() - start

    assert elapsed < 0.2  # first max_calls should be immediate


def test_blocks_once_max_calls_exceeded_within_period():
    limiter = RateLimiter(max_calls=2, period_seconds=0.3)

    start = time.monotonic()
    limiter.wait()
    limiter.wait()
    limiter.wait()  # third call within the window should block
    elapsed = time.monotonic() - start

    assert elapsed >= 0.25  # roughly period_seconds, allowing scheduling slack


def test_allows_calls_again_after_period_elapses():
    limiter = RateLimiter(max_calls=1, period_seconds=0.2)

    limiter.wait()
    time.sleep(0.25)

    start = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - start

    assert elapsed < 0.1  # window already expired, shouldn't block
