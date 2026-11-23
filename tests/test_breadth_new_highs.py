"""New 52-week highs/lows in the breadth table: warm-up handling (a stock
in its first year is undefined, never "not a new high" -- CLAUDE.md
invariant 9), point-in-time membership, per-sector rows, and the `end`
bound on what gets read."""

import numpy as np
import pandas as pd
import pytest

from src.signals.breadth.compute import _load_closes, compute_breadth, compute_breadth_with_sectors
from src.signals.breadth.config import BreadthConfig
from src.foundation.data_processing import db

_DATES = pd.bdate_range("2020-01-01", periods=10)


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(closes, dates) -> pd.DataFrame:
    closes = [float(c) for c in closes]
    return pd.DataFrame(
        {
            "timestamp": dates, "open": closes, "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes], "close": closes, "volume": [1000] * len(closes),
            "is_partial": [0] * len(closes),
        }
    ).set_index("timestamp")


def _add(conn, ticker, closes, dates=_DATES):
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, _bars(closes, dates))


def _members(conn, rows):
    """rows: (ticker, start_date, end_date-or-None)."""
    membership = pd.DataFrame(rows, columns=["ticker", "start_date", "end_date"])
    db.replace_index_membership(conn, "test_idx", membership)


def _config(**overrides) -> BreadthConfig:
    cfg = BreadthConfig(
        indices=["test_idx"], sma_periods=(3,), ema_periods=(), price_source=db.YFINANCE, new_high_window=3
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


_RISING = list(range(10, 20))
_FALLING = list(range(19, 9, -1))


def test_new_high_is_na_during_warmup_not_counted_as_not_a_new_high(conn):
    # AAA rises from day 0; BBB has bars only from day 5 and falls. Window 3:
    # AAA's first 3 days and BBB's first 3 bars (days 5-7) are undefined.
    _add(conn, "AAA", _RISING)
    _add(conn, "BBB", _FALLING[:5], _DATES[5:])
    _members(conn, [("AAA", _DATES[0], None), ("BBB", _DATES[0], None)])

    result = compute_breadth(conn, "test_idx", _config())

    # Every member in warm-up: undefined, not 0%.
    for column in ("pct_new_high_52w", "pct_new_low_52w", "net_new_high_52w"):
        assert result[column].iloc[:3].isna().all(), column
    assert result["pct_new_high_52w"].iloc[3] == 1.0
    # BBB has data but is still warming up on days 5-7: left out of the
    # denominator, so AAA alone is 100% -- not 50% with BBB as "no".
    assert result["n_with_data"].loc[_DATES[5]] == 2
    assert (result["pct_new_high_52w"].loc[_DATES[5]:_DATES[7]] == 1.0).all()
    assert (result["pct_new_low_52w"].loc[_DATES[5]:_DATES[7]] == 0.0).all()
    # Day 8: BBB's 4th bar, below its prior 3 -> a new low.
    assert result["pct_new_high_52w"].loc[_DATES[8]] == 0.5
    assert result["pct_new_low_52w"].loc[_DATES[8]] == 0.5
    assert result["net_new_high_52w"].loc[_DATES[8]] == 0.0


def test_default_window_leaves_exactly_the_first_252_bars_undefined(conn):
    dates = pd.bdate_range("2019-01-01", periods=260)
    _add(conn, "AAA", np.arange(100, 360), dates)
    _members(conn, [("AAA", dates[0], None)])

    result = compute_breadth(conn, "test_idx", _config(new_high_window=252))

    assert result["pct_new_high_52w"].iloc[:252].isna().all()
    assert (result["pct_new_high_52w"].iloc[252:] == 1.0).all()


def test_new_high_and_low_match_hand_computation_and_ties_count_as_neither(conn):
    _add(conn, "AAA", _RISING)
    _add(conn, "BBB", _FALLING)
    _add(conn, "CCC", [10] * 10)  # flat: equals its prior max/min, never beyond
    _add(conn, "DDD", [10, 12, 11, 12, 13, 9, 10, 11, 12, 13])
    _members(conn, [(t, _DATES[0], None) for t in ("AAA", "BBB", "CCC", "DDD")])

    result = compute_breadth(conn, "test_idx", _config())

    # Day 3: DDD 12 vs prior (10,12,11) -> ties the high, not above it.
    assert result["pct_new_high_52w"].iloc[3] == pytest.approx(1 / 4)
    assert result["pct_new_low_52w"].iloc[3] == pytest.approx(1 / 4)
    # Day 4: DDD 13 > max(12,11,12) -> new high. Day 5: DDD 9 < min(11,12,13) -> new low.
    assert result["pct_new_high_52w"].iloc[4] == pytest.approx(2 / 4)
    assert result["pct_new_low_52w"].iloc[5] == pytest.approx(2 / 4)
    assert result["net_new_high_52w"].iloc[5] == pytest.approx(1 / 4 - 2 / 4)  # AAA high; BBB, DDD low


def test_point_in_time_membership_for_new_highs(conn):
    # EEE has a full price history but joins the index only on day 5: its
    # window is warmed on pre-membership bars, so it counts from day 5 --
    # and not one day before. AAA leaves after day 6.
    _add(conn, "AAA", _RISING)
    _add(conn, "BBB", _FALLING)
    _add(conn, "EEE", _FALLING)
    _members(conn, [("AAA", _DATES[0], _DATES[6]), ("BBB", _DATES[0], None), ("EEE", _DATES[5], None)])

    result = compute_breadth(conn, "test_idx", _config())

    assert result["pct_new_low_52w"].loc[_DATES[4]] == pytest.approx(1 / 2)  # AAA, BBB
    assert result["pct_new_low_52w"].loc[_DATES[5]] == pytest.approx(2 / 3)  # + EEE
    assert result["pct_new_high_52w"].loc[_DATES[6]] == pytest.approx(1 / 3)
    assert result["pct_new_high_52w"].loc[_DATES[7]] == 0.0  # AAA gone
    assert result["pct_new_low_52w"].loc[_DATES[7]] == 1.0


def test_sector_rows_split_the_same_counts_and_skip_unknown_sectors(conn):
    _add(conn, "AAA", _RISING)
    _add(conn, "BBB", _FALLING)
    _add(conn, "CCC", _RISING)
    _add(conn, "NOS", _RISING)  # no sector on file
    _add(conn, "BLK", _RISING)  # blank sector
    _members(conn, [(t, _DATES[0], None) for t in ("AAA", "BBB", "CCC", "NOS", "BLK")])
    db.upsert_ticker_sector(
        conn,
        pd.DataFrame(
            {"ticker": ["AAA", "BBB", "CCC", "BLK"], "sector": ["Technology", "Technology", "Energy", ""],
             "industry": ["x", "x", "y", ""]}
        ),
    )

    market, sectors = compute_breadth_with_sectors(conn, "test_idx", _config())

    assert market["pct_new_high_52w"].iloc[3] == pytest.approx(4 / 5)  # unknown sectors count market-wide
    assert set(sectors["sector"]) == {"Technology", "Energy"}
    day3 = sectors[sectors["date"] == _DATES[3]].set_index("sector")
    assert day3.loc["Technology", "n_members"] == 2
    assert day3.loc["Technology", "pct_new_high_52w"] == 0.5
    assert day3.loc["Technology", "pct_new_low_52w"] == 0.5
    assert day3.loc["Technology", "net_new_high_52w"] == 0.0
    assert day3.loc["Energy", "pct_new_high_52w"] == 1.0
    # Warm-up days: rows exist (members have data) but the fractions are NA.
    day0 = sectors[sectors["date"] == _DATES[0]].set_index("sector")
    assert day0.loc["Technology", "n_members"] == 2
    assert day0[["pct_new_high_52w", "pct_new_low_52w", "net_new_high_52w"]].isna().all().all()


def test_end_bounds_what_is_read_and_returned(conn):
    _add(conn, "AAA", _RISING)
    _members(conn, [("AAA", _DATES[0], None), ("LATE", _DATES[8], None)])
    _add(conn, "LATE", _RISING)

    loaded = _load_closes(conn, ["AAA"], db.YFINANCE, end=str(_DATES[5].date()))
    assert loaded["date"].max() == _DATES[5]

    full = compute_breadth(conn, "test_idx", _config())
    bounded = compute_breadth(conn, "test_idx", _config(), end=str(_DATES[5].date()))
    # Backward-looking only: cutting the read at `end` changes nothing up to it.
    pd.testing.assert_frame_equal(bounded, full.loc[: _DATES[5]], check_freq=False)
