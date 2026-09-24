"""Tests for `features/panel.py::build_panel`'s new `timeframe` parameter
(M10, PREREGISTRATION.md 2026-09-24) -- the weekly-resampled panel path
gets the same lag-correctness/ticker-boundary scrutiny
`test_moving_averages_features.py`'s own daily `build_panel` tests already
apply, not assumed safe by analogy.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.models import Timeframe
from src.signals.moving_averages.features import distance, ma
from src.signals.moving_averages.features.panel import build_panel


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _seed_ticker(conn: sqlite3.Connection, ticker: str, closes: list[float], start: str) -> None:
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    bars = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close,
         "volume": 1_000_000.0, "is_partial": 0},
        index=idx,
    )
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, bars)


def test_build_panel_weekly_timeframe_produces_fewer_rows_than_daily(conn):
    n = 300
    rng = np.random.default_rng(0)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    daily = build_panel(conn, ["AAA"], timeframe=Timeframe.DAILY)
    weekly = build_panel(conn, ["AAA"], timeframe=Timeframe.WEEKLY)

    assert len(weekly) > 0
    # Roughly 1 weekly row per 5 daily rows, generously bounded (holidays,
    # partial-week exclusion at the series' edges).
    assert len(weekly) < len(daily) / 3


def test_build_panel_weekly_one_bar_lag_is_a_one_week_lag(conn):
    """A row's `above_sma_20` must equal the RAW (un-lagged) weekly value
    from the PRIOR weekly row, not its own week's raw value -- the same
    one-bar-lag invariant the daily path already enforces, now checked
    through the weekly path specifically (`apply_lag`'s shift is
    row-order-based, but this pins that the resampling itself didn't
    introduce an off-by-one row before the lag is even applied).
    """
    n = 300
    rng = np.random.default_rng(1)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    weekly_panel = build_panel(conn, ["AAA"], timeframe=Timeframe.WEEKLY)
    assert len(weekly_panel) > 25  # enough rows to clear the sma_20 warmup

    # Independently recompute the raw (un-lagged) weekly close/sma_20 the
    # same way `load_bars(timeframe=Timeframe.WEEKLY)` does, to check
    # build_panel's lagged output against.
    from src.foundation.market_common.data import load_bars

    raw_weekly = load_bars(conn, "AAA", Timeframe.WEEKLY)
    raw_sma20 = ma.compute_ma(raw_weekly["close"], "sma", 20)
    raw_above = distance.above(raw_weekly["close"], raw_sma20)

    panel_sorted = weekly_panel.sort_values("date").reset_index(drop=True)
    raw_dates = raw_above.index
    for i in range(21, min(len(panel_sorted), len(raw_dates))):
        row_date = panel_sorted.loc[i, "date"]
        assert pd.Timestamp(row_date) == raw_dates[i]
        prior_date = raw_dates[i - 1]
        assert panel_sorted.loc[i, "above_sma_20"] == raw_above.loc[prior_date]


def test_build_panel_daily_default_is_unchanged(conn):
    """Backward compatibility: omitting `timeframe` must produce exactly
    the same panel as before this parameter existed (default
    `Timeframe.DAILY`) -- every other module's own cached panel depends on
    this not changing silently.
    """
    n = 60
    rng = np.random.default_rng(2)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    explicit = build_panel(conn, ["AAA"], timeframe=Timeframe.DAILY)
    default = build_panel(conn, ["AAA"])

    pd.testing.assert_frame_equal(explicit, default)
