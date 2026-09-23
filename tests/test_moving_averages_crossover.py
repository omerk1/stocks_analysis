"""Tests for M3's crossover event extraction (`features/crossover.py`,
PREREGISTRATION.md 2026-09-23).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.crossover import (
    DEATH,
    GOLDEN,
    crossover_events,
    fast_above_slow_state,
)


def _frame(fast: list[float], slow: list[float], ticker: str = "AAA") -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=len(fast))
    return pd.DataFrame({"ticker": ticker, "date": dates, "fast": fast, "slow": slow})


def test_fast_above_slow_state_na_safe():
    panel = _frame([np.nan, 1.0, 2.0], [1.0, np.nan, 1.5])
    state = fast_above_slow_state(panel, "fast", "slow")
    assert state.isna().tolist() == [True, True, False]
    assert bool(state.iloc[2]) is True


def test_golden_cross_detected_once():
    # fast starts below slow, crosses above on day 3, stays above.
    fast = [1, 2, 3, 5, 6, 7]
    slow = [4, 4, 4, 4, 4, 4]
    panel = _frame(fast, slow)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state")

    assert len(events) == 1
    assert events.iloc[0]["crossover_type"] == GOLDEN
    assert events.iloc[0]["date"] == pd.bdate_range("2021-01-04", periods=6)[3]


def test_death_cross_detected():
    fast = [7, 6, 5, 3, 2, 1]
    slow = [4, 4, 4, 4, 4, 4]
    panel = _frame(fast, slow)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state")

    assert len(events) == 1
    assert events.iloc[0]["crossover_type"] == DEATH


def test_golden_then_death_both_detected_in_order():
    fast = [1, 2, 5, 6, 5, 2, 1]
    slow = [4, 4, 4, 4, 4, 4, 4]
    panel = _frame(fast, slow)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state").sort_values("date")

    assert events["crossover_type"].tolist() == [GOLDEN, DEATH]


def test_left_censored_first_run_has_no_event():
    # fast is already above slow on day 0 -- that state's true start is
    # unobserved, so it must not be reported as a golden-cross event.
    fast = [5, 6, 7, 8]
    slow = [4, 4, 4, 4]
    panel = _frame(fast, slow)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state")

    assert len(events) == 0


def test_warmup_nan_is_not_read_as_a_crossover():
    fast = [np.nan, np.nan, 1, 2, 5, 6]
    slow = [np.nan, np.nan, 4, 4, 4, 4]
    panel = _frame(fast, slow)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state")

    assert len(events) == 1
    assert events.iloc[0]["date"] == pd.bdate_range("2021-01-04", periods=6)[4]


def test_does_not_bleed_across_ticker_boundaries():
    fast = [1, 2, 5, 6]
    slow = [4, 4, 4, 4]
    aaa = _frame(fast, slow, ticker="AAA")
    bbb = _frame(fast, slow, ticker="BBB")
    panel = pd.concat([aaa, bbb], ignore_index=True)
    panel["state"] = fast_above_slow_state(panel, "fast", "slow")

    events = crossover_events(panel, "state")

    assert len(events) == 2
    assert set(events["ticker"]) == {"AAA", "BBB"}
    # BBB's fast/slow series restarts its own left-censoring -- a false
    # cross-ticker bleed would manufacture a spurious event on BBB's first
    # row (state != AAA's trailing state) instead of correctly treating
    # BBB's own day-0 state as its own left-censored run.
    for ticker in ("AAA", "BBB"):
        assert events.loc[events["ticker"] == ticker, "date"].iloc[0] == pd.bdate_range(
            "2021-01-04", periods=4
        )[2]
