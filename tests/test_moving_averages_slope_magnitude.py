"""Tests for M6.3's module logic (`modules/slope_magnitude.py`),
PREREGISTRATION.md 2026-09-22.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import slope_magnitude as sm


def test_prepare_recent_large_move_is_lagged_and_masks_first_row():
    # A 7-day close path for one ticker: a >7% single-day jump on day 3
    # (idx 3), otherwise flat. `recent_large_move` should first read True
    # on day 4 (the day *after* the jump -- one-bar lag, CLAUDE.md
    # invariant #2), not day 3 itself, and must be NA on day 0 (the
    # lag's own leading-row shift, not a comparison-on-undefined-input
    # bug -- there is no prior close to compute day 0's own return from).
    dates = pd.bdate_range("2021-01-04", periods=7)
    close = [100.0, 100.5, 101.0, 115.0, 116.0, 116.5, 117.0]  # +13.9% on idx 3
    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates, "close": close,
        "slope_log_21_sma_20": 0.01, "slope_log_21_sma_50": 0.01, "slope_log_21_sma_200": 0.01,
        "mom_12_1": 0.05, "realized_vol_63": 0.2, "sector": "X",
    })

    prepared = sm.prepare(panel)
    flag = prepared["recent_large_move"]

    assert pd.isna(flag.iloc[0])  # apply_lag's own leading-row NaN, not a false negative
    assert bool(flag.iloc[3]) is False  # jump day itself: not yet visible pre-lag
    assert bool(flag.iloc[4]) is True  # first day the jump is visible, post one-bar-lag
    assert bool(flag.iloc[6]) is True  # still inside the trailing LARGE_MOVE_LOOKBACK_DAYS window


def test_prepare_slope_pctile_is_a_per_date_decile_of_the_log_slope():
    n_tickers = 40
    dates = pd.bdate_range("2021-01-04", periods=3)
    rows = []
    for i, ticker in enumerate([f"T{i}" for i in range(n_tickers)]):
        for date in dates:
            rows.append({
                "ticker": ticker, "date": date, "close": 100.0,
                "slope_log_21_sma_20": i / n_tickers, "slope_log_21_sma_50": i / n_tickers,
                "slope_log_21_sma_200": np.nan,
                "mom_12_1": 0.0, "realized_vol_63": 0.2, "sector": "X",
            })
    panel = pd.DataFrame(rows)

    prepared = sm.prepare(panel)

    col50 = sm.slope_pctile_column(50)
    assert prepared[col50].min() == 0
    assert prepared[col50].max() == sm.N_DECILES - 1
    # Ticker 0 has the smallest slope_log_21_sma_50 on every date -> decile 0.
    assert (prepared.loc[prepared["ticker"] == "T0", col50] == 0).all()
    # NaN input (lookback 200 here) stays NaN, never silently bucketed.
    assert prepared[sm.slope_pctile_column(200)].isna().all()


def _u_shape_panel(n_dates=200, n_tickers=320, gradient=0.03, seed=0):
    """A `prepare()`-shaped panel with a planted U-shape on
    `slope_log_21_sma_50`: the pooled tail deciles (0,1,8,9) get
    `+gradient`, the pooled middle deciles (4,5) get `-gradient`, the
    remaining deciles get ~0 -- `humped_test` should recover a negative,
    CI-excluding-zero `c2` (middle underperforms tails).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i, ticker in enumerate([f"T{i}" for i in range(n_tickers)]):
        rank = i / (n_tickers - 1) - 0.5  # constant per ticker, spans deciles 0-9
        is_tail = abs(rank) >= 0.3
        is_middle = abs(rank) < 0.1
        planted = gradient if is_tail else (-gradient if is_middle else 0.0)
        for date in dates:
            rows.append({
                "ticker": ticker, "date": date, "close": 100.0,
                "slope_log_21_sma_20": rank, "slope_log_21_sma_50": rank, "slope_log_21_sma_200": rank,
                "fwd_ret_21": planted + rng.normal(0, 0.01),
                "mom_12_1": rng.normal(0, 0.05), "realized_vol_63": abs(rng.normal(0.2, 0.05)), "sector": "X",
            })
    panel = pd.DataFrame(rows)
    return panel


def test_humped_test_detects_planted_u_shape():
    panel = _u_shape_panel(gradient=0.03)
    prepared = sm.prepare(panel)
    # fwd_ret_21 is planted directly (not derived from `close`, which is
    # flat) -- overwrite prepare()'s own forward_return computation with
    # the planted column, same pattern slope_conditioner's own tests use.
    prepared["fwd_ret_21"] = panel["fwd_ret_21"].to_numpy()

    result = sm.humped_test(prepared, lookback=50)

    assert result["c2"] < 0
    assert result["ci_high"] < 0  # CI excludes zero, entirely negative
    assert result["killed"] is False
    assert not result["below_threshold"]
    assert result["ci_excludes_zero"] is True


def test_shape_table_has_one_row_per_decile_with_effective_n():
    panel = _u_shape_panel(gradient=0.03, n_dates=60)
    prepared = sm.prepare(panel)
    prepared["fwd_ret_21"] = panel["fwd_ret_21"].to_numpy()

    table = sm.shape_table(prepared, lookback=50)

    assert sorted(table["decile"].tolist()) == list(range(sm.N_DECILES))
    assert (table["n_events"] > 0).all()
    assert (table["n_dates"] > 0).all()


def test_cost_annotation_returns_finite_positive_turnover():
    # Unlike `_u_shape_panel`'s constant-per-ticker rank (deliberately
    # noiseless for the decile-detection tests above), turnover needs the
    # slope column to actually move day to day -- a ticker whose decile
    # never changes contributes zero flips by construction, which would
    # test the fixture, not `cost_annotation`.
    rng = np.random.default_rng(2)
    n_tickers, n_dates = 40, 120
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i, ticker in enumerate([f"T{i}" for i in range(n_tickers)]):
        base = i / (n_tickers - 1) - 0.5
        for date in dates:
            rows.append({
                "ticker": ticker, "date": date, "close": 100.0,
                "slope_log_21_sma_50": base + rng.normal(0, 0.15),
                "slope_log_21_sma_20": base, "slope_log_21_sma_200": base,
                "mom_12_1": 0.0, "realized_vol_63": 0.2, "sector": "X",
            })
    panel = pd.DataFrame(rows)
    prepared = sm.prepare(panel)

    cost = sm.cost_annotation(prepared, lookback=50)

    assert cost["signals_per_year"] > 0
    assert cost["hurdle_annual"] > 0
