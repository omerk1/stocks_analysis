"""Tests for M7's module logic (`modules/ribbon_compression.py`,
`features/ribbon.py`, `labels/forward_returns.py::forward_realized_vol`),
PREREGISTRATION.md 2026-09-22.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.features.ribbon import ribbon_width, ribbon_width_pctile
from src.signals.moving_averages.labels.forward_returns import forward_realized_vol
from src.signals.moving_averages.modules import ribbon_compression as rc


def test_ribbon_width_is_coefficient_of_variation_of_the_four_smas():
    panel = pd.DataFrame({
        "sma_20": [100.0, np.nan],
        "sma_50": [102.0, 50.0],
        "sma_150": [98.0, 50.0],
        "sma_200": [100.0, 50.0],
    })
    width = ribbon_width(panel)

    values = panel.loc[0, ["sma_20", "sma_50", "sma_150", "sma_200"]]
    expected = values.std() / values.mean()
    assert width.iloc[0] == pytest.approx(expected)
    # Row 1 has a NaN input (sma_20) -- arithmetic NaN propagation, no
    # explicit masking needed (this is arithmetic, not a comparison,
    # CLAUDE.md invariant #9 doesn't apply).
    assert pd.isna(width.iloc[1])


def test_ribbon_width_pctile_is_min_max_position_within_trailing_window():
    # A single ticker, deterministic ramp: width rises 0..9 then falls
    # back to 0 -- window=5 so we can hand-check a few rows past warmup.
    width = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 0.0])
    ticker = pd.Series(["AAA"] * 7)

    pctile = ribbon_width_pctile(width, ticker, window=5)

    # First 4 rows (< window) are warmup -- NaN.
    assert pctile.iloc[:4].isna().all()
    # Row 4 (0-indexed): trailing window is [0,1,2,3,4] -- min=0, max=4,
    # value=4 -> pctile=1.0.
    assert pctile.iloc[4] == pytest.approx(1.0)
    # Row 5: trailing window [1,2,3,4,5] -- min=1, max=5, value=5 -> 1.0.
    assert pctile.iloc[5] == pytest.approx(1.0)
    # Row 6: trailing window [2,3,4,5,0] -- min=0, max=5, value=0 -> 0.0.
    assert pctile.iloc[6] == pytest.approx(0.0)


def test_ribbon_width_pctile_masks_degenerate_zero_span_and_respects_ticker_boundary():
    # Ticker AAA is perfectly flat (span=0 once the window fills) --
    # masked, not silently reported as 0 or 1. Ticker BBB's own window
    # must not see AAA's trailing values (no cross-ticker bleed).
    width = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0] + [10.0, 20.0, 30.0, 40.0, 50.0])
    ticker = pd.Series(["AAA"] * 5 + ["BBB"] * 5)

    pctile = ribbon_width_pctile(width, ticker, window=5)

    assert pd.isna(pctile.iloc[4])  # AAA's flat window -- degenerate span
    # BBB's own window (rows 5-9) is its own 5 values, not mixed with
    # AAA's -- min=10, max=50, value=50 -> 1.0, not influenced by AAA.
    assert pctile.iloc[9] == pytest.approx(1.0)


def test_forward_realized_vol_matches_hand_computed_std_of_forward_daily_returns():
    # Two tickers so a cross-ticker-boundary bug would show up as row 4
    # (AAA's last row) leaking into BBB's own forward window.
    closes_a = [100, 101, 99, 102, 104, 103]
    closes_b = [50, 51, 52, 50, 49, 53]
    panel = pd.DataFrame({
        "ticker": ["AAA"] * 6 + ["BBB"] * 6,
        "close": closes_a + closes_b,
    })

    result = forward_realized_vol(panel, horizon=3)

    a = pd.Series(closes_a)
    daily_ret_a = a.pct_change()
    # fwd_vol at row 0 (AAA) = std(daily_ret[1], daily_ret[2], daily_ret[3])
    expected_row0 = daily_ret_a.iloc[1:4].std()
    assert result.iloc[0] == pytest.approx(expected_row0)
    # Last 3 rows of each ticker have fewer than `horizon` forward returns
    # -- NaN, not a partial-window number.
    assert result.iloc[3:6].isna().all()
    assert result.iloc[9:12].isna().all()


def _synthetic_panel(n_dates=500, n_tickers=60, seed=0):
    """A `prepare()`-shaped panel whose SMA ribbon genuinely oscillates
    over time per ticker (a ~60-day compress/expand cycle, phase-offset
    per ticker) -- `ribbon_width_pctile` is a per-ticker *rolling*
    measure, so (unlike a cross-sectional decile) a fixture with a
    constant-over-time ribbon width per ticker would make every rolling
    min-max span zero and the whole decile column NaN. `trend_up`
    (`mom_12_1`'s sign) is independent noise, uncorrelated with the
    compression cycle, so the trend-conditional cell isn't accidentally
    fed a group split correlated with `ribbon_decile` for a reason other
    than the planted effect itself.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i, ticker in enumerate([f"T{i}" for i in range(n_tickers)]):
        phase = 2 * np.pi * i / n_tickers
        trend_up_series = rng.random(n_dates) > 0.5
        for t, date in enumerate(dates):
            dispersion = 1 + np.sin(2 * np.pi * t / 60 + phase)  # in [0, 2], ~60-day cycle
            rows.append({
                "ticker": ticker, "date": date,
                "sma_20": 100 + dispersion * 1.5, "sma_50": 100 + dispersion * 0.5,
                "sma_150": 100 - dispersion * 0.5, "sma_200": 100 - dispersion * 1.5,
                "close": 100.0,
                "mom_12_1": 0.05 if trend_up_series[t] else -0.05,
                # Per-row variation, not a constant -- cross_sectional_bucket's
                # per-date qcut needs distinct values to form 3 buckets; a
                # constant column collapses to 1 bucket (or NaN throughout),
                # which would silently drop every row from the C2 match.
                "realized_vol_63": 0.02 + rng.normal(0, 0.005),
                "mom_1_0": rng.normal(0, 0.01),
                "sector": "X",
            })
    return pd.DataFrame(rows)


def test_direction_magnitude_and_conditional_cells_recover_a_planted_gradient():
    panel = _synthetic_panel()
    prepared = rc.prepare(panel)

    # `prepare()` computes `fwd_ret_21`/`fwd_absret_21`/`fwd_vol_21` from
    # `close` via forward_return/forward_realized_vol, which need real
    # forward price history this fixture's flat `close` doesn't have --
    # plant the gradient directly on top of the *actually computed*
    # `ribbon_decile`/`prior_trend_up` (not an assumed one), same
    # injection pattern `_state_slope_panel`-style fixtures elsewhere in
    # this test suite use, so the cell functions are exercised on their
    # own restriction/bootstrap logic, not on label mechanics already
    # covered by `test_forward_realized_vol_...` above.
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.01, size=len(prepared))
    is_compressed = (prepared["ribbon_decile"] == 0).fillna(False).to_numpy()
    trend_up = prepared["prior_trend_up"].fillna(False).to_numpy()
    planted = np.where(is_compressed, np.where(trend_up, 0.05, -0.05), 0.0)
    prepared["fwd_ret_21"] = planted + noise
    prepared["fwd_absret_21"] = prepared["fwd_ret_21"].abs()

    assert is_compressed.sum() >= 200  # sanity: the fixture actually produces a usable decile-0 population

    direction_table = rc.direction_unconditional_table(prepared)
    magnitude_cell = direction_table[direction_table["outcome"] == "direction_magnitude"].iloc[0]
    # Spread convention is decile9 - decile0 (`block_bootstrap_spread`'s
    # own high-minus-low order); the planted magnitude gradient lives in
    # decile0 (compressed), so a correctly-recovered effect is *negative*
    # here -- decile9 (already-dispersed) has the smaller |return|.
    assert magnitude_cell["c2"] < 0
    assert magnitude_cell["c2_ci_high"] < 0
    assert not magnitude_cell["below_threshold"]

    conditional_cell = rc.direction_conditional_on_trend_table(prepared)
    assert conditional_cell["c2"] > 0
    assert conditional_cell["c2_ci_low"] > 0
    assert not conditional_cell["below_threshold"]


def test_prepare_masks_prior_trend_up_where_momentum_is_nan():
    panel = pd.DataFrame({
        "ticker": ["AAA"] * 3, "date": pd.bdate_range("2021-01-04", periods=3),
        "close": [100.0, 101.0, 102.0],
        "sma_20": [100.0, 101.0, 102.0], "sma_50": [100.0, 101.0, 102.0],
        "sma_150": [100.0, 101.0, 102.0], "sma_200": [100.0, 101.0, 102.0],
        "mom_12_1": [np.nan, 0.05, -0.02], "realized_vol_63": [np.nan, 0.02, 0.02],
        "mom_1_0": [np.nan, 0.01, -0.01],
        "sector": "X",
    })

    prepared = rc.prepare(panel)

    assert pd.isna(prepared["prior_trend_up"].iloc[0])
    assert bool(prepared["prior_trend_up"].iloc[1]) is True
    assert bool(prepared["prior_trend_up"].iloc[2]) is False
