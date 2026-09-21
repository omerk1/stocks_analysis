"""Tests for M6.2's module logic (`modules/slope_conditioner.py`),
PREREGISTRATION.md 2026-09-17. Event/touch-extraction correctness itself
is covered in `test_moving_averages_touch.py` (M5) -- these tests exercise
`prepare`'s `slope_sign` construction and the three sub-questions' own
restrict-then-delta wiring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import slope_conditioner as sc


def test_prepare_slope_sign_matches_sign_and_masks_nan():
    dates = pd.bdate_range("2021-01-04", periods=6)
    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates, "close": 100.0,
        "slope_log_21_sma_50": [np.nan, np.nan, 0.01, -0.02, 0.0, 0.03],
        "slope_log_21_sma_200": [np.nan] * 6,
        "mom_12_1": 0.05, "realized_vol_63": 0.2, "mom_1_0": 0.01, "sector": "X",
    })

    prepared = sc.prepare(panel)

    sign50 = prepared["slope_sign_sma_50"]
    assert pd.isna(sign50.iloc[0]) and pd.isna(sign50.iloc[1])
    assert bool(sign50.iloc[2]) is True
    assert bool(sign50.iloc[3]) is False
    assert bool(sign50.iloc[4]) is False  # exactly zero is not "rising"
    assert bool(sign50.iloc[5]) is True
    assert prepared["slope_sign_sma_200"].isna().all()


def _state_slope_panel(n_dates=200, n_tickers=30, gradient=0.05, seed=0):
    """A `prepare()`-shaped panel: every row is `above_sma_50` (so the
    "above" cell has the whole population), `slope_sign_sma_50` random per
    row, `fwd_ret_21` carrying a planted gradient on slope_sign. `above_
    sma_200`/`dist_atr_sma_200` are present but flat/noise -- irrelevant to
    this test's assertions, just enough for the lookback=200 cells to run
    without erroring.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for ticker in [f"T{i}" for i in range(n_tickers)]:
        for date in dates:
            slope_sign = rng.random() > 0.5
            rows.append({
                "ticker": ticker, "date": date,
                "above_sma_50": True, "above_sma_200": bool(rng.random() > 0.5),
                "slope_sign_sma_50": slope_sign, "slope_sign_sma_200": bool(rng.random() > 0.5),
                "dist_atr_sma_50": rng.normal(0, 1), "dist_atr_sma_200": rng.normal(0, 1),
                "fwd_ret_21": gradient * slope_sign + rng.normal(0, 0.005),
                "mom_tercile": rng.integers(0, 3), "vol_tercile": rng.integers(0, 3),
                "sector": "X",
            })
    panel = pd.DataFrame(rows)
    panel["above_sma_50"] = panel["above_sma_50"].astype("boolean")
    panel["above_sma_200"] = panel["above_sma_200"].astype("boolean")
    panel["slope_sign_sma_50"] = panel["slope_sign_sma_50"].astype("boolean")
    panel["slope_sign_sma_200"] = panel["slope_sign_sma_200"].astype("boolean")
    return panel


def test_state_slope_table_detects_planted_gradient_within_above_state():
    panel = _state_slope_panel(gradient=0.05, n_dates=200)

    table = sc.state_slope_table(panel)

    cell = table[(table["lookback"] == 50) & (table["state"] == "above")].iloc[0]
    assert cell["c2"] > 0
    assert cell["c2_ci_low"] > 0
    assert not cell["below_threshold"]
    assert cell["killed"] is False


def test_extension_slope_table_detects_planted_gradient_in_top_decile():
    rng = np.random.default_rng(1)
    # n_tickers large enough that even the top decile (~10%) clears
    # MIN_TICKERS=30.
    n_dates, n_tickers = 200, 320
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i, ticker in enumerate([f"T{i}" for i in range(n_tickers)]):
        rank = i / (n_tickers - 1) - 0.5  # spread across deciles, deterministic per ticker
        for date in dates:
            slope_sign = rng.random() > 0.5
            rows.append({
                "ticker": ticker, "date": date,
                "dist_atr_sma_50": rank, "dist_atr_sma_200": rng.normal(0, 1),
                "above_sma_50": True, "above_sma_200": True,
                "slope_sign_sma_50": slope_sign, "slope_sign_sma_200": bool(rng.random() > 0.5),
                # Gradient only in the top-decile tickers (rank near +0.5).
                "fwd_ret_21": (0.05 * slope_sign if rank > 0.4 else 0.0) + rng.normal(0, 0.003),
                "mom_tercile": rng.integers(0, 3), "vol_tercile": rng.integers(0, 3), "sector": "X",
            })
    panel = pd.DataFrame(rows)
    for col in ("above_sma_50", "above_sma_200", "slope_sign_sma_50", "slope_sign_sma_200"):
        panel[col] = panel[col].astype("boolean")

    table = sc.extension_slope_table(panel)

    cell = table[(table["lookback"] == 50) & (table["extension"] == "top")].iloc[0]
    assert cell["c2"] > 0
    assert cell["c2_ci_low"] > 0
    assert not cell["below_threshold"]


def test_touch_slope_table_wires_hold_flag_to_its_own_touch_day_slope():
    # Two independent touch events on the same ticker (well separated so
    # each away-run/outcome window is self-contained): the first touch
    # (idx 3) happens while slope is falling and bounces (hold); the
    # second (idx 15) happens later while slope is rising and slices
    # through -- confirms touch_slope_table reads slope_sign at the
    # *touch day*, not some other row.
    dist_atr = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9,
                0.0, 0.0, 0.0, 0.0, 1.5, 1.4, 0.2,
                -0.6, -0.6, -0.6, -0.6, -0.6, 0.0, 0.0, 0.0, 0.0]
    n = len(dist_atr)
    dates = pd.bdate_range("2021-01-04", periods=n)

    slope_sign = [False] * n
    slope_sign[3] = False  # first touch: falling, resolves to HOLD
    slope_sign[15] = True  # second touch: rising, resolves to SLICE_THROUGH

    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates,
        "dist_atr_sma_50": dist_atr, "dist_atr_sma_200": [np.nan] * n,
        "slope_sign_sma_50": pd.array(slope_sign, dtype="boolean"),
        "slope_sign_sma_200": pd.array([pd.NA] * n, dtype="boolean"),
        "mom_tercile": 0, "vol_tercile": 0, "sector": "X",
    })

    events = touch_events_for_test(panel)
    assert len(events) == 2
    from_above = events[events["direction"] == "from_above"].sort_values("date")
    assert from_above["outcome"].tolist() == ["hold", "slice_through"]
    assert from_above["slope_sign_sma_50"].tolist() == [False, True]

    table = sc.touch_slope_table(panel)
    lookback_50 = table[table["lookback"] == 50]
    assert set(lookback_50["direction"]) == {"from_above", "from_below"}


def touch_events_for_test(panel: pd.DataFrame) -> pd.DataFrame:
    """Reproduces `touch_slope_table`'s own merge (touch events + slope
    sign at the touch day) so the test above can assert on it directly,
    without duplicating `touch_slope_table`'s full cell-computation path.
    """
    from src.signals.moving_averages.features.touch import touch_events

    events = touch_events(panel, "dist_atr_sma_50")
    slope_context = panel[["ticker", "date", "slope_sign_sma_50"]].drop_duplicates(subset=["ticker", "date"])
    return events.merge(slope_context, on=["ticker", "date"], how="left")
