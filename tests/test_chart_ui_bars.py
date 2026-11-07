import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.models import Timeframe
from src.ui.chart.bars import load_chart_bars, moving_averages
from src.ui.chart.config import MAKind, MASpec


def _bars(start: str, n: int, base: float) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    close = base + np.arange(n, dtype=float)
    return pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close,
                         "volume": 1000.0, "is_partial": 0}, index=idx)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    db.create_tables(c)
    yield c
    c.close()


def test_loads_traded_prices_not_total_return(conn):
    # The chart is on split-only (traded) prices, so S/R, gap and AVWAP levels sit on its bars.
    db.upsert_bars(conn, "bars_1d", "ABC", db.YFINANCE, _bars("2024-01-01", 30, 50.0))
    db.upsert_bars(conn, "bars_1d", "ABC", db.YFINANCE_SPLIT_ONLY, _bars("2024-01-01", 30, 100.0))
    bars = load_chart_bars(conn, "abc", Timeframe.DAILY)
    assert len(bars) == 30
    assert bars["close"].iloc[0] == 100.0


def test_weekly_bars_aggregate_the_daily_ones(conn):
    db.upsert_bars(conn, "bars_1d", "ABC", db.YFINANCE_SPLIT_ONLY, _bars("2024-01-01", 30, 100.0))
    weekly = load_chart_bars(conn, "ABC", Timeframe.WEEKLY)
    first_week = _bars("2024-01-01", 5, 100.0)
    assert weekly["open"].iloc[0] == first_week["open"].iloc[0]
    assert weekly["close"].iloc[0] == first_week["close"].iloc[-1]
    assert weekly["high"].iloc[0] == first_week["high"].max()
    assert weekly["volume"].iloc[0] == first_week["volume"].sum()


def test_unknown_ticker_is_empty(conn):
    assert load_chart_bars(conn, "NOPE", Timeframe.DAILY).empty


def test_moving_averages_match_definitions_and_keep_warmup_nan():
    close = pd.Series(np.arange(1.0, 41.0), index=pd.bdate_range("2024-01-01", periods=40))
    mas = moving_averages(close, (MASpec(MAKind.SMA, 10), MASpec(MAKind.EMA, 10)))
    assert set(mas) == {"sma_10", "ema_10"}
    pd.testing.assert_series_equal(mas["sma_10"], close.rolling(10).mean(), check_names=False)
    assert mas["sma_10"].iloc[:9].isna().all()
    assert mas["ema_10"].iloc[:9].isna().all()
    assert mas["ema_10"].iloc[9:].notna().all()
