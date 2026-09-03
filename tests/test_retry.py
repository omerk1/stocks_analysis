from src.foundation.data_processing.retry import attempt_with_limited_retries


def test_succeeds_on_first_attempt():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    ok, result, error = attempt_with_limited_retries(fn, max_attempts=2, backoff_seconds=0)

    assert ok is True
    assert result == "ok"
    assert error is None
    assert len(calls) == 1


def test_succeeds_on_second_attempt_after_first_failure():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("transient")
        return "ok"

    ok, result, error = attempt_with_limited_retries(fn, max_attempts=2, backoff_seconds=0)

    assert ok is True
    assert result == "ok"
    assert len(calls) == 2


def test_gives_up_after_max_attempts_without_looping_forever():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("persistent failure")

    ok, result, error = attempt_with_limited_retries(fn, max_attempts=2, backoff_seconds=0)

    assert ok is False
    assert result is None
    assert "persistent failure" in error
    assert len(calls) == 2  # exactly max_attempts, not more
