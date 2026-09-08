"""Phase 2 tests: the starting-subset MA feature layer (DESIGN.md §4).

Three layers, matching the Phase 0/Phase 1 pattern:
- Exact-formula tests for each feature against DESIGN's own definitions
  (dist_pct/dist_atr §4.3, slope_log_k Appendix A) -- hand-computable,
  deterministic inputs, no synthetic-generator noise.
- A rolling-vs-full-sample test for `dist_z`, pinning CLAUDE.md invariant
  #3 ("no full-sample statistics") for this specific feature.
- An end-to-end `build_panel` test against a real (in-memory) DB, checking
  the central lag (§7.2) is actually applied and doesn't bleed across
  ticker boundaries -- the same failure mode Phase 1's
  `test_apply_lag_does_not_bleed_across_ticker_boundaries` guards, now
  exercised through the real feature-building path, not just the
  primitive.
- A parquet cache round-trip test against DESIGN §4.4's partitioned schema.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.moving_averages.features import context, distance, ma, slope
from src.signals.moving_averages.features.panel import build_panel, read_panel, write_panel


# ---- exact-formula tests ----

def test_dist_pct_formula():
    close = pd.Series([110.0])
    ma_series = pd.Series([100.0])

    assert distance.dist_pct(close, ma_series).iloc[0] == pytest.approx(0.10)


def test_dist_atr_formula():
    close = pd.Series([110.0])
    ma_series = pd.Series([100.0])
    atr = pd.Series([5.0])

    assert distance.dist_atr(close, ma_series, atr).iloc[0] == pytest.approx(2.0)


def test_above_formula():
    close = pd.Series([110.0, 90.0, 100.0])
    ma_series = pd.Series([100.0, 100.0, 100.0])

    result = distance.above(close, ma_series)

    assert result.tolist() == [True, False, False]


def test_slope_log_k_formula():
    ma_series = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 110.0])

    result = slope.slope_log_k(ma_series, k=5)

    assert pd.isna(result.iloc[0])  # no ma_{t-5} yet
    assert pd.isna(result.iloc[4])
    assert result.iloc[5] == pytest.approx(np.log(110.0) - np.log(100.0))


def test_dist_z_is_rolling_not_full_sample():
    """CLAUDE.md invariant #3, pinned for this specific feature: dist_z at
    a given row must not change depending on what data exists *after* it.
    """
    values = pd.Series([0.01 * i for i in range(1, 21)])  # 20 points
    window = 5

    full = distance.dist_z(values, window=window)
    truncated = distance.dist_z(values.iloc[:10], window=window)

    assert full.iloc[9] == pytest.approx(truncated.iloc[9])


def test_mom_12_1_formula():
    # 260 flat days of 100 except a known ramp, so close[t-21]/close[t-252]-1
    # is hand-computable at a specific point.
    n = 260
    close = pd.Series([100.0] * n)
    close.iloc[7] = 80.0    # this will land at t-252 for row index 259
    close.iloc[238] = 120.0  # this will land at t-21 for row index 259

    result = context.mom_12_1(close)

    assert result.iloc[259] == pytest.approx(120.0 / 80.0 - 1)
    assert pd.isna(result.iloc[251])  # not enough history yet (needs t-252)


def test_realized_vol_63_formula():
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 100))))

    result = context.realized_vol_63(close)

    expected_last = close.pct_change().iloc[-63:].std()
    assert result.iloc[-1] == pytest.approx(expected_last)
    assert pd.isna(result.iloc[60])  # fewer than 63 returns available yet


def test_compute_ma_dispatches_to_the_existing_sma_ema_wrappers():
    from src.foundation.market_common.indicators import ema, sma

    close = pd.Series([100.0 + i for i in range(30)])

    pd.testing.assert_series_equal(ma.compute_ma(close, "sma", 10), sma(close, 10), check_names=False)
    pd.testing.assert_series_equal(ma.compute_ma(close, "ema", 10), ema(close, 10), check_names=False)


def test_compute_ma_rejects_an_unknown_family():
    close = pd.Series([100.0])

    with pytest.raises(ValueError, match="Unknown MA family"):
        ma.compute_ma(close, "wma", 10)


# ---- build_panel: end-to-end lag correctness and ticker-boundary safety ----

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


def test_build_panel_lags_features_relative_to_the_raw_computation(conn):
    n = 40
    rng = np.random.default_rng(0)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    panel = build_panel(conn, ["AAA"])

    # Recompute the raw (un-lagged) above/sma_20 feature independently,
    # outside build_panel, to check against.
    close_series = pd.Series(closes, index=pd.bdate_range("2020-01-01", periods=n))
    raw_sma20 = ma.compute_ma(close_series, "sma", 20)
    raw_above = distance.above(close_series, raw_sma20)

    aaa = panel.set_index("date")["above_sma_20"]
    # A row at date d must equal the raw value at date d-1 (the prior
    # trading day), not date d's own raw value -- that's the one-bar lag.
    for i in range(21, n):  # skip the sma_20 warmup region
        row_date = close_series.index[i]
        prior_date = close_series.index[i - 1]
        assert aaa.loc[row_date] == raw_above.loc[prior_date]


def test_build_panel_does_not_bleed_lag_across_ticker_boundaries(conn):
    n = 30
    _seed_ticker(conn, "AAA", [100.0 + i for i in range(n)], "2020-01-01")
    _seed_ticker(conn, "BBB", [500.0 - i for i in range(n)], "2020-01-01")  # different date range would also work; same range exercises groupby-by-ticker directly

    panel = build_panel(conn, ["AAA", "BBB"])

    bbb_first_row = panel[panel["ticker"] == "BBB"].sort_values("date").iloc[0]
    # BBB's first row must be NaN (no prior BBB row to lag from) -- not
    # bled from AAA's last row, which a naive global .shift() would do.
    assert pd.isna(bbb_first_row["dist_pct_sma_20"])


def test_build_panel_casts_numeric_features_to_float32_and_keeps_booleans_bool(conn):
    _seed_ticker(conn, "AAA", [100.0 + i * 0.1 for i in range(40)], "2020-01-01")

    panel = build_panel(conn, ["AAA"])

    assert panel["dist_pct_sma_20"].dtype == np.float32
    assert panel["atr_14"].dtype == np.float32
    # Nullable "boolean", not plain bool -- plain bool can't hold the NaN
    # the lag introduces into each ticker's first row (see panel.py).
    assert panel["stacked_sma"].dtype == "boolean"
    assert panel["above_sma_20"].dtype == "boolean"


def test_build_panel_includes_lagged_context_features(conn):
    n = 300  # comfortably past mom_12_1's 252-day warmup
    rng = np.random.default_rng(0)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    panel = build_panel(conn, ["AAA"])

    assert {"mom_12_1", "realized_vol_63"}.issubset(panel.columns)
    assert panel["mom_12_1"].dtype == np.float32

    close_series = pd.Series(closes, index=pd.bdate_range("2020-01-01", periods=n))
    raw_mom = context.mom_12_1(close_series)
    panel_mom = panel.set_index("date")["mom_12_1"]
    # Same lag convention as every other feature: row at date d holds the
    # raw value as of date d-1, not d's own value.
    for i in range(255, n):
        row_date, prior_date = close_series.index[i], close_series.index[i - 1]
        assert panel_mom.loc[row_date] == pytest.approx(raw_mom.loc[prior_date])


def test_build_panel_returns_empty_frame_for_unknown_ticker(conn):
    panel = build_panel(conn, ["NOPE"])

    assert panel.empty


def test_build_panel_end_enforces_the_holdout_boundary(conn):
    """CLAUDE.md invariant #1: data past the holdout boundary must never
    even be loaded. `end` is passed straight through to `load_bars`'s
    `as_of`, so this pins that no row past `end` ever reaches the
    returned panel -- not just that a later step happens to exclude it.
    """
    _seed_ticker(conn, "AAA", [100.0 + i * 0.1 for i in range(60)], "2020-01-01")

    cutoff = pd.Timestamp("2020-02-01")
    panel = build_panel(conn, ["AAA"], end=cutoff)

    assert not panel.empty
    assert panel["date"].max() <= cutoff


# ---- parquet cache round-trip (DESIGN §4.4) ----

def test_write_and_read_panel_round_trips(conn, tmp_path):
    _seed_ticker(conn, "AAA", [100.0 + i * 0.1 for i in range(40)], "2020-01-01")
    _seed_ticker(conn, "BBB", [50.0 + i * 0.2 for i in range(40)], "2020-01-01")

    panel = build_panel(conn, ["AAA", "BBB"])
    output_dir = tmp_path / "ma_panel"
    write_panel(panel, output_dir)

    partitions = sorted(output_dir.glob("year=*"))
    assert len(partitions) == pd.to_datetime(panel["date"]).dt.year.nunique()

    read_back = read_panel(output_dir)

    pd.testing.assert_frame_equal(
        panel.reset_index(drop=True), read_back.reset_index(drop=True), check_like=True
    )


def test_read_panel_respects_start_end_bounds_across_a_year_boundary(conn, tmp_path):
    # Starting in November and running 100 business days crosses into the
    # next calendar year -- exercises reading multiple year=YYYY partitions
    # and trimming to an exact day bound within them, not just a single-
    # partition read.
    _seed_ticker(conn, "AAA", [100.0 + i * 0.1 for i in range(100)], "2020-11-01")

    panel = build_panel(conn, ["AAA"])
    output_dir = tmp_path / "ma_panel"
    write_panel(panel, output_dir)

    partitions = sorted(output_dir.glob("year=*"))
    assert len(partitions) == 2  # 2020 and 2021

    mid_date = panel["date"].sort_values().iloc[50]
    read_back = read_panel(output_dir, start=mid_date)

    assert read_back["date"].min() >= mid_date
    assert len(read_back) < len(panel)
