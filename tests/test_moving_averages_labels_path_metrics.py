"""Tests for `labels/path_metrics.py` (new for M6.6, PREREGISTRATION.md 2026-09-23)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.labels.path_metrics import forward_max_drawdown


def test_forward_max_drawdown_picks_the_worst_low_in_the_window_not_the_horizon_close():
    # Entry close = 100 on day 0. Day 1's low dips to 80 (-20%, the worst
    # point in the 3-day window) then recovers to a close of 105 by day 3
    # -- forward_return would report +5%, but forward_max_drawdown must
    # report the -20% trough, not the eventual close.
    dates = pd.bdate_range("2021-01-04", periods=5)
    close = [100.0, 90.0, 95.0, 105.0, 106.0]
    low = [99.0, 80.0, 93.0, 104.0, 105.0]
    panel = pd.DataFrame({"ticker": "AAA", "date": dates, "close": close, "low": low})

    mdd = forward_max_drawdown(panel, horizon=3)

    assert mdd.iloc[0] == pytest.approx(80.0 / 100.0 - 1)


def test_forward_max_drawdown_is_nan_in_the_final_horizon_rows_of_each_ticker():
    dates = pd.bdate_range("2021-01-04", periods=5)
    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates,
        "close": [100.0] * 5, "low": [99.0] * 5,
    })

    mdd = forward_max_drawdown(panel, horizon=3)

    assert mdd.iloc[:2].notna().all()
    assert mdd.iloc[2:].isna().all()  # fewer than 3 forward lows exist from here on


def test_forward_max_drawdown_never_crosses_a_ticker_boundary():
    dates = pd.bdate_range("2021-01-04", periods=3)
    panel = pd.DataFrame({
        "ticker": ["AAA", "AAA", "BBB"],
        "date": [dates[0], dates[1], dates[0]],
        "close": [100.0, 100.0, 100.0],
        "low": [100.0, 100.0, 100.0],
    })
    # AAA's last row has no forward data of its own; it must not borrow
    # BBB's leading row just because BBB comes next in a naive flat shift.
    panel = pd.concat([panel, pd.DataFrame({
        "ticker": ["BBB"], "date": [dates[1]], "close": [100.0], "low": [20.0],
    })], ignore_index=True)

    mdd = forward_max_drawdown(panel, horizon=1)

    aaa_last = mdd[(panel["ticker"] == "AAA") & (panel["date"] == dates[1])]
    assert aaa_last.isna().all()
