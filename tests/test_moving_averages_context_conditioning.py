"""Tests for M13 -- context conditioning (DESIGN.md line 974;
PREREGISTRATION.md, 2026-09-21).

`prepare()`'s `vix_tercile` join needs a live DB connection (`macro_series`)
and isn't exercised end-to-end here -- same "test the per-feature logic,
not the DB plumbing" split `test_moving_averages_stack_minervini.py` uses
for M2's own `rs_rating` join. These tests cover:
- `_rolling_tercile`'s trailing-window (not full-sample) bucketing and its
  NaN warmup,
- `regime_table`/`_cell`'s restrict-then-delta wiring on an already-
  `prepare()`-shaped synthetic frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import context_conditioning as cc


def test_rolling_tercile_nan_during_warmup_and_buckets_correctly():
    # A ramp series: window=10, so the first 9 values are NaN (warmup),
    # and every subsequent value ranks at the very top of its own trailing
    # 10-value window (a strictly increasing ramp), so it always lands in
    # the top tercile once the window fills.
    values = pd.Series(np.arange(30, dtype=float))
    bucket = cc._rolling_tercile(values, window=10)

    assert bucket.iloc[:9].isna().all()
    assert bucket.iloc[9:].notna().all()
    assert (bucket.iloc[9:] == 2).all()


def test_rolling_tercile_does_not_use_future_values():
    # CLAUDE.md invariant #3: a bucket at date t must not change if future
    # (post-t) values change. Two series identical up to index 19, then
    # diverging -- the bucket at index 19 (window=10, i.e. based on
    # indices 10-19 only) must be identical in both.
    base = np.concatenate([np.random.RandomState(0).normal(size=20), np.zeros(10)])
    series_a = pd.Series(base.copy())
    series_b = series_a.copy()
    series_b.iloc[20:] = 999.0  # only the "future" (post-index-19) tail differs

    bucket_a = cc._rolling_tercile(series_a, window=10)
    bucket_b = cc._rolling_tercile(series_b, window=10)

    assert bucket_a.iloc[19] == bucket_b.iloc[19]


def _synthetic_prepared_panel(n_dates=200, n_tickers=30, gradient=-0.01, seed=0):
    """An already-`prepare()`-shaped panel: `above_sma_200` random per row,
    `fwd_ret_21` carrying a planted gradient on `above_sma_200`
    (negative, matching this module's own real-data sign), C2 match
    columns present, and `vix_tercile`/`breadth_tercile` split into a
    clean top/bottom/middle partition by date so both regime facets have
    a well-populated top and bottom bucket.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    date_regime = {d: rng.integers(0, 3) for d in dates}
    rows = []
    for ticker in [f"T{i}" for i in range(n_tickers)]:
        for date in dates:
            is_above = rng.random() > 0.5
            rows.append({
                "ticker": ticker, "date": date,
                "above_sma_200": is_above,
                "fwd_ret_21": gradient * is_above + rng.normal(0, 0.01),
                "mom_tercile": rng.integers(0, 3), "vol_tercile": rng.integers(0, 3),
                "sector": "X",
                "vix_tercile": date_regime[date],
                "breadth_tercile": date_regime[date],
            })
    panel = pd.DataFrame(rows)
    panel["above_sma_200"] = panel["above_sma_200"].astype("boolean")
    return panel


def test_regime_table_returns_four_cells_with_expected_labels():
    panel = _synthetic_prepared_panel()
    result = cc.regime_table(panel)

    assert len(result) == 4
    assert set(zip(result["regime"], result["bucket"])) == {
        ("vix", "top"), ("vix", "bottom"), ("breadth", "top"), ("breadth", "bottom"),
    }


def test_regime_table_recovers_planted_gradient_sign():
    # Every regime bucket draws from the same planted-gradient data
    # generating process (gradient doesn't depend on the regime column in
    # `_synthetic_prepared_panel`), so every cell's C2 point estimate
    # should recover the same (negative) sign.
    # n_dates must clear block_bootstrap_delta's default block_length=42
    # minimum (MIN_BLOCKS x block_length = 3 x 42 = 126 distinct dates)
    # *within* each regime bucket, not just overall -- with a 3-way random
    # regime split, 600 dates leaves ~200 per bucket.
    panel = _synthetic_prepared_panel(n_dates=600, n_tickers=40, gradient=-0.02)
    result = cc.regime_table(panel)

    assert result["c2"].notna().all()
    assert (result["c2"] < 0).all()
    assert (result["n_events"] > 0).all()


def test_cell_reports_ci_excludes_zero_and_edge_consistently():
    panel = _synthetic_prepared_panel(n_dates=300, n_tickers=40, gradient=-0.05)
    result = cc.regime_table(panel)

    for _, row in result.iterrows():
        if pd.isna(row["c2_ci_low"]):
            continue
        expected_edge = max(abs(row["c2_ci_low"]), abs(row["c2_ci_high"]))
        assert row["edge"] == expected_edge
        expected_excludes = not (row["c2_ci_low"] <= 0 <= row["c2_ci_high"])
        assert row["ci_excludes_zero"] == expected_excludes
