"""Tests for M6.6's module logic (`modules/ribbon_slope_agreement.py`),
PREREGISTRATION.md 2026-09-23.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import ribbon_slope_agreement as rsa

# Long enough for sma_100 (min_periods=100) plus its own slope_log_21 shift
# plus the one-bar lag to all clear: sma_100 first defined at row idx 99;
# slope_log_21_sma_100 (raw) first defined at row idx 120 (needs idx-21=99
# also defined); the lagged column is therefore first defined at row idx
# 121. `N_WARMUP_ROWS` rows (0..120 inclusive) must read NaN, not a false
# "flat"/"falling" reading (CLAUDE.md invariant #9).
N_WARMUP_ROWS = 121


def _trend_panel(n_dates: int, drift: float, cached_lookback_sign: float) -> pd.DataFrame:
    """One ticker's close path growing (drift > 0) or shrinking (drift < 0)
    exponentially -- sustained positive/negative `slope_log_21` at every
    lookback once warmed up, including the module-local sma_10/sma_100.
    `slope_log_21_sma_{20,50,200}` are supplied directly as constants
    (same convention `modules/slope_magnitude.py`'s own tests use for
    already-cached columns), sign given by `cached_lookback_sign`.
    """
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    t = np.arange(n_dates)
    close = 100.0 * np.exp(drift * t)
    return pd.DataFrame({
        "ticker": "T0", "date": dates, "close": close, "low": close * 0.99,
        "slope_log_21_sma_20": cached_lookback_sign * 0.01,
        "slope_log_21_sma_50": cached_lookback_sign * 0.01,
        "slope_log_21_sma_200": cached_lookback_sign * 0.01,
        "mom_12_1": 0.0, "mom_1_0": 0.0, "realized_vol_63": 0.2, "sector": "X",
    })


def test_ribbon_agreement_state_is_na_during_sma_100_warmup():
    panel = _trend_panel(n_dates=140, drift=0.001, cached_lookback_sign=+1.0)
    prepared = rsa.prepare(panel)

    state = prepared["ribbon_agreement_state"]
    assert state.iloc[:N_WARMUP_ROWS].isna().all()
    assert state.iloc[N_WARMUP_ROWS:].notna().all()


def test_ribbon_agreement_state_counts_all_five_lookbacks():
    up = _trend_panel(n_dates=140, drift=0.001, cached_lookback_sign=+1.0)
    down = _trend_panel(n_dates=140, drift=-0.001, cached_lookback_sign=+1.0)
    down["ticker"] = "T1"
    down["slope_log_21_sma_20"] = -0.01
    down["slope_log_21_sma_50"] = -0.01
    down["slope_log_21_sma_200"] = -0.01
    panel = pd.concat([up, down], ignore_index=True)

    prepared = rsa.prepare(panel)
    state = prepared["ribbon_agreement_state"]

    up_last = state[(prepared["ticker"] == "T0")].iloc[-1]
    down_last = state[(prepared["ticker"] == "T1")].iloc[-1]
    assert up_last == 5  # all 5 lookbacks positive
    assert down_last == 0  # all 5 lookbacks negative


def _identical_pair_panel(n_tickers: int = 35) -> pd.DataFrame:
    dates = pd.bdate_range("2015-01-01", periods=3)
    rows = []
    for i in range(n_tickers):
        rank = (i - n_tickers / 2) / n_tickers  # varies per ticker, constant across dates
        for date in dates:
            rows.append({
                "ticker": f"T{i}", "date": date, "close": 100.0 * (1 + i * 0.001), "low": 99.0,
                "slope_log_21_sma_20": rank, "slope_log_21_sma_50": rank,  # identical by construction
                "slope_log_21_sma_200": 0.0,
                "mom_12_1": 0.0, "mom_1_0": 0.0, "realized_vol_63": 0.2, "sector": "X",
            })
    return pd.DataFrame(rows)


def test_slope_correlation_matrix_detects_identical_columns_as_perfectly_correlated():
    panel = _identical_pair_panel()
    prepared = rsa.prepare(panel)

    matrix = rsa.slope_correlation_matrix(prepared)
    identical_pair = matrix[matrix["pair"] == "slope_20_vs_slope_50"]
    assert len(identical_pair) == 1
    assert identical_pair["median_spearman"].iloc[0] > 0.99
    # 10 lookback pairs + 5 lookback-vs-state rows.
    assert len(matrix) == 10 + 5


def _extreme_state_panel(n_tickers=320, n_dates=260, effect=0.02, seed=0):
    """Half the tickers agree bullish (all 5 lookbacks positive, close
    trending up), half agree bearish (all 5 negative, close trending down)
    -- `extreme_state_test` should recover a `+effect` C2 delta on
    `fwd_ret_21` between the two (state 5 minus state 0), planted directly
    (overwritten after `prepare()`, same pattern
    `modules/slope_magnitude.py`'s own planted-effect test uses).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i in range(n_tickers):
        bullish = i < n_tickers // 2
        drift = 0.001 if bullish else -0.001
        sign = 1.0 if bullish else -1.0
        close = 100.0 * np.exp(drift * np.arange(n_dates))
        for j, date in enumerate(dates):
            rows.append({
                "ticker": f"T{i}", "date": date, "close": close[j], "low": close[j] * 0.99,
                "slope_log_21_sma_20": sign * 0.01, "slope_log_21_sma_50": sign * 0.01,
                "slope_log_21_sma_200": sign * 0.01,
                "fwd_ret_21": (effect if bullish else -effect) + rng.normal(0, 0.01),
                "mom_12_1": rng.normal(0, 0.05), "mom_1_0": rng.normal(0, 0.02),
                "realized_vol_63": abs(rng.normal(0.2, 0.05)),
                "sector": "X",
            })
    return pd.DataFrame(rows)


def test_extreme_state_test_recovers_planted_return_spread():
    panel = _extreme_state_panel(effect=0.02)
    prepared = rsa.prepare(panel)
    prepared["fwd_ret_21"] = panel["fwd_ret_21"].to_numpy()

    result = rsa.extreme_state_test(prepared, "fwd_ret_21")

    assert result["c2"] > 0
    assert result["ci_low"] > 0  # CI excludes zero, entirely positive
    assert result["ci_excludes_zero"] is True
    assert result["killed"] is False
    assert not result["below_threshold"]


def test_extreme_state_test_with_reversal_match_cols_attenuates_a_planted_reversal_confound():
    # A planted state-5-vs-state-0 spread on fwd_mdd_21 whose *entire*
    # effect is actually a short-term-reversal artifact: `mom_1_0` is drawn
    # from overlapping (not disjoint) bullish/bearish distributions --
    # enough separation in the mean to drive a real bullish-vs-bearish gap,
    # enough overlap that per-date rev_tercile buckets actually mix both
    # groups' tickers, so matching on rev_tercile can remove most of it.
    # `fwd_mdd_21` is a pure linear function of `mom_1_0` for every row, no
    # separate bullish/bearish term. Same mechanism/pattern as
    # `modules/slope_magnitude.py`'s own reversal-confound test.
    rng = np.random.default_rng(4)
    n_tickers, n_dates = 320, 260
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i in range(n_tickers):
        bullish = i < n_tickers // 2
        drift = 0.001 if bullish else -0.001
        sign = 1.0 if bullish else -1.0
        close = 100.0 * np.exp(drift * np.arange(n_dates))
        for j, date in enumerate(dates):
            mom_1_0 = (0.04 if bullish else -0.04) + rng.normal(0, 0.06)
            fwd_mdd = 0.03 * mom_1_0 + rng.normal(0, 0.0005)  # entirely mom_1_0-driven
            rows.append({
                "ticker": f"T{i}", "date": date, "close": close[j], "low": close[j] * 0.99,
                "slope_log_21_sma_20": sign * 0.01, "slope_log_21_sma_50": sign * 0.01,
                "slope_log_21_sma_200": sign * 0.01,
                "fwd_mdd_21": fwd_mdd,
                "mom_12_1": rng.normal(0, 0.05), "mom_1_0": mom_1_0,
                "realized_vol_63": abs(rng.normal(0.2, 0.05)), "sector": "X",
            })
    panel = pd.DataFrame(rows)
    prepared = rsa.prepare(panel)
    prepared["fwd_mdd_21"] = panel["fwd_mdd_21"].to_numpy()

    default = rsa.extreme_state_test(prepared, "fwd_mdd_21", match_cols=rsa.C2_MATCH_COLS)
    with_reversal = rsa.extreme_state_test(
        prepared, "fwd_mdd_21", match_cols=rsa.C2_MATCH_COLS_WITH_REVERSAL
    )

    assert default["ci_excludes_zero"] is True  # confound read as "real" under default C2
    assert abs(with_reversal["c2"]) < abs(default["c2"]) * 0.5  # substantially attenuated


def test_cost_annotation_returns_finite_positive_turnover():
    rng = np.random.default_rng(2)
    n_tickers, n_dates = 40, 160
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i in range(n_tickers):
        # A random-walk-ish close so the ribbon-agreement state actually
        # flips over time -- a ticker whose state never changes contributes
        # zero flips by construction, which would test the fixture, not
        # `cost_annotation`.
        steps = rng.normal(0, 0.01, size=n_dates)
        close = 100.0 * np.exp(np.cumsum(steps))
        for j, date in enumerate(dates):
            rows.append({
                "ticker": f"T{i}", "date": date, "close": close[j], "low": close[j] * 0.99,
                "slope_log_21_sma_20": rng.normal(0, 0.01), "slope_log_21_sma_50": rng.normal(0, 0.01),
                "slope_log_21_sma_200": rng.normal(0, 0.01),
                "mom_12_1": 0.0, "mom_1_0": 0.0, "realized_vol_63": 0.2, "sector": "X",
            })
    panel = pd.DataFrame(rows)
    prepared = rsa.prepare(panel)

    cost = rsa.cost_annotation(prepared)

    assert cost["signals_per_year"] > 0
    assert cost["hurdle_annual"] > 0


def test_shape_table_has_one_row_per_state_with_effective_n():
    panel = _extreme_state_panel(effect=0.02)
    prepared = rsa.prepare(panel)
    prepared["fwd_ret_21"] = panel["fwd_ret_21"].to_numpy()

    table = rsa.shape_table(prepared)

    assert sorted(table["state"].tolist()) == list(range(rsa.N_RUNGS + 1))
    populated = table[table["state"].isin([0, rsa.N_RUNGS])]
    assert (populated["n_events"] > 0).all()
    assert (populated["n_dates"] > 0).all()
