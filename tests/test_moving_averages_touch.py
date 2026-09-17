"""Tests for M5's touch/test/bounce event extraction (`features/touch.py`,
PREREGISTRATION.md 2026-09-17).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.touch import (
    CHOP,
    FROM_ABOVE,
    FROM_BELOW,
    HOLD,
    SLICE_THROUGH,
    touch_events,
)

COL = "dist_atr_sma_test"


def _frame(values: list[float], ticker: str = "AAA") -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=len(values))
    return pd.DataFrame({"ticker": ticker, "date": dates, COL: values})


def test_hold_from_above():
    # away (>=1 ATR above) for 2 days, touch on day 3 (days_since_away_end=1),
    # outcome 5 days later bounces back up -- support held.
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9]
    events = touch_events(_frame(values), COL)

    assert len(events) == 1
    row = events.iloc[0]
    assert row["direction"] == FROM_ABOVE
    assert row["outcome"] == HOLD
    assert bool(row["hold_flag"]) is True
    assert row["date"] == pd.bdate_range("2021-01-04", periods=len(values))[3]


def test_slice_through_from_below():
    # away (<=-1 ATR below) for 2 days, touch (resistance test), outcome
    # breaks up through the level -- resistance failed.
    values = [np.nan, -1.2, -1.1, 0.1, -0.1, -0.2, -0.3, -0.4, 0.9]
    events = touch_events(_frame(values), COL)

    assert len(events) == 1
    row = events.iloc[0]
    assert row["direction"] == FROM_BELOW
    assert row["outcome"] == SLICE_THROUGH
    assert bool(row["hold_flag"]) is False


def test_chop_outcome():
    values = [np.nan, 1.5, 1.4, 0.2, 0.3, 0.2, 0.1, 0.2, 0.1]  # outcome stays inside +-0.5
    events = touch_events(_frame(values), COL)

    assert len(events) == 1
    assert events.iloc[0]["outcome"] == CHOP
    assert bool(events.iloc[0]["hold_flag"]) is False


def test_touch_beyond_max_days_to_touch_is_not_an_event():
    # Away for 2 days, then 11 days with dist_atr sitting just outside the
    # touch band (never <= 0.25) before finally touching on day 12 after
    # leaving the away zone -- one day past the default 10-day window.
    plateau = [0.5] * 11
    values = [np.nan, 1.5, 1.4, *plateau, 0.2]
    events = touch_events(_frame(values), COL)

    assert len(events) == 0


def test_leading_censored_run_with_no_preceding_away_has_no_direction():
    # The series starts already "not away" (no observed away run before
    # it) -- even if it touches, there's no direction to assign, so this
    # must not silently produce a fabricated event.
    values = [np.nan, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    events = touch_events(_frame(values), COL)

    assert len(events) == 0


def test_warmup_nan_is_not_read_as_away_or_touch():
    # NaN region must never contribute an away run or a touch -- only the
    # single real away-then-touch cycle after warmup should surface.
    values = [np.nan, np.nan, np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9]
    events = touch_events(_frame(values), COL)

    assert len(events) == 1
    assert events.iloc[0]["date"] == pd.bdate_range("2021-01-04", periods=len(values))[5]


def test_event_censored_at_series_end_is_dropped():
    # Touch happens, but fewer than OUTCOME_HORIZON days of data remain --
    # the outcome can't be observed, so no event should be reported.
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.5]  # only 2 rows after the touch, need 5
    events = touch_events(_frame(values), COL)

    assert len(events) == 0


def test_does_not_bleed_across_ticker_boundaries():
    aaa = _frame([np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9], ticker="AAA")
    bbb = _frame([np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9], ticker="BBB")
    panel = pd.concat([aaa, bbb], ignore_index=True)

    events = touch_events(panel, COL)

    assert len(events) == 2
    assert set(events["ticker"]) == {"AAA", "BBB"}
