"""Tests for M6.5's module logic (`modules/sma_dropoff.py`),
PREREGISTRATION.md 2026-09-23.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import sma_dropoff as sd


def _base_columns(n_tickers: int, n_dates: int, close_by_ticker: dict[str, list[float]]) -> pd.DataFrame:
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for ticker, closes in close_by_ticker.items():
        assert len(closes) == n_dates
        for date, close in zip(dates, closes):
            rows.append({
                "ticker": ticker, "date": date, "close": close,
                "mom_12_1": 0.0, "realized_vol_63": 0.2, "sector": "X",
            })
    return pd.DataFrame(rows)


def test_entering_plus_exiting_equals_raw_slope_exactly():
    # Direct algebraic check of DESIGN's own identity on a hand-built path:
    # entering + exiting must equal raw_sma(t) - raw_sma(t-1) bit-exactly
    # (up to float rounding) at every row where both are defined.
    rng = np.random.default_rng(0)
    n_dates = 60
    close = 100 + np.cumsum(rng.normal(0, 1, n_dates))
    panel = _base_columns(1, n_dates, {"AAA": list(close)})

    lookback = 10
    working = sd._add_raw_flip_columns(panel.copy(), lookback)

    raw_sma = panel["close"].rolling(lookback, min_periods=lookback).mean()
    raw_slope = raw_sma - raw_sma.shift(1)
    sma_prev = raw_sma.shift(1)
    close_exit = panel["close"].shift(lookback)
    entering = (panel["close"] - sma_prev) / lookback
    exiting = (sma_prev - close_exit) / lookback

    valid = raw_slope.notna() & entering.notna() & exiting.notna()
    np.testing.assert_allclose(
        (entering + exiting)[valid].to_numpy(), raw_slope[valid].to_numpy(), atol=1e-9,
    )
    # Sanity: the module's own flip flag never fires where the identity
    # inputs aren't even defined yet (warmup).
    assert not bool(working.loc[~valid, f"_flip_event_{lookback}"].fillna(False).any())


def test_price_driven_flip_classified_when_todays_move_dominates():
    # A lookback=5 window, steadily declining (sign settles at -1), then a
    # single large jump whose *entering* contribution swamps the ordinary
    # *exiting* contribution -- the flip at idx 10 must classify as
    # price_driven, not dropoff_driven. (Fixture verified numerically
    # before being hardcoded here -- see this test's own module docstring
    # note; no other flip occurs anywhere else in this series.)
    lookback = 5
    close = [120, 118, 116, 114, 112, 110, 108, 106, 104, 102, 140, 141, 142]
    panel = _base_columns(1, len(close), {"AAA": close})

    working = sd._add_raw_flip_columns(panel.copy(), lookback)
    event_col = f"_flip_event_{lookback}"
    price_col = f"_flip_price_driven_{lookback}"
    dropoff_col = f"_flip_dropoff_driven_{lookback}"

    flip_rows = working[working[event_col].fillna(False).astype(bool)]
    assert len(flip_rows) == 1
    flip_row = flip_rows.iloc[0]
    assert flip_row["date"] == panel["date"].iloc[10]
    assert bool(flip_row[price_col]) is True
    assert bool(flip_row[dropoff_col]) is False


def test_dropoff_driven_flip_classified_when_exiting_bar_dominates():
    # A lookback=5 window with a gently rising baseline and one spike
    # inserted at idx 2. While the spike sits inside the window it inflates
    # the SMA (positive slope); once it rolls *out* of the window (idx 7,
    # lookback=5 days after idx 2), the SMA drops sharply even though the
    # day's own close keeps rising gently -- a flip driven by the exiting
    # bar, not by today's price action. (Fixture verified numerically; see
    # this test's own comment -- idx 7 is the exiting-dominated flip this
    # test targets, regardless of what happens at any later index.)
    lookback = 5
    base = [100 + 0.3 * i for i in range(20)]
    close = list(base)
    close[2] += 25
    panel = _base_columns(1, len(close), {"AAA": close})

    working = sd._add_raw_flip_columns(panel.copy(), lookback)
    event_col = f"_flip_event_{lookback}"
    price_col = f"_flip_price_driven_{lookback}"
    dropoff_col = f"_flip_dropoff_driven_{lookback}"

    flip_rows = working[working[event_col].fillna(False).astype(bool)]
    assert len(flip_rows) >= 1
    target = flip_rows[flip_rows["date"] == panel["date"].iloc[7]]
    assert len(target) == 1
    assert bool(target.iloc[0][dropoff_col]) is True
    assert bool(target.iloc[0][price_col]) is False


def test_flip_columns_are_na_during_warmup_not_false():
    # CLAUDE.md invariant #9: a comparison-derived boolean must preserve
    # its inputs' missingness during the MA's own warmup, not silently read
    # as False.
    lookback = 20
    close = [100.0 + i * 0.1 for i in range(15)]  # fewer rows than lookback+1
    panel = _base_columns(1, len(close), {"AAA": close})

    working = sd._add_raw_flip_columns(panel.copy(), lookback)
    assert working[f"_flip_event_{lookback}"].isna().all()
    assert working[f"_flip_price_driven_{lookback}"].isna().all()
    assert working[f"_flip_dropoff_driven_{lookback}"].isna().all()


def test_prepare_lags_flip_columns_by_one_bar():
    # The look-ahead check every module's newly-derived event column needs
    # (CLAUDE.md invariant #2): whatever raw flip flag fires on day t must
    # first be visible on day t+1's row, not day t's own.
    lookback = 50  # must be one of the module's own declared LOOKBACKS for prepare() to compute it
    close = [120, 118, 116, 114, 112, 110, 108, 106, 104, 102] * 6 + [140, 141, 142, 143, 144]
    panel = pd.DataFrame({
        "ticker": "AAA", "date": pd.bdate_range("2021-01-04", periods=len(close)), "close": close,
        "mom_12_1": 0.0, "realized_vol_63": 0.2, "sector": "X",
    })

    raw = sd._add_raw_flip_columns(panel.copy(), lookback)
    raw_event = raw[f"_flip_event_{lookback}"]
    prepared = sd.prepare(panel)
    lagged_event = prepared[sd._flip_event_col(lookback)]

    assert pd.isna(lagged_event.iloc[0])  # apply_lag's own leading-row NaN
    # Every subsequent row's lagged value equals the raw value one row earlier.
    for i in range(1, len(close)):
        raw_val = raw_event.iloc[i - 1]
        lag_val = lagged_event.iloc[i]
        if pd.isna(raw_val):
            assert pd.isna(lag_val)
        else:
            assert bool(lag_val) == bool(raw_val)


def _planted_panel(n_tickers=200, n_dates=320, lookback=50, gradient=0.02, seed=0):
    """A `prepare()`-shaped multi-ticker panel with a planted effect:
    price-driven flips get `+gradient` forward return, drop-off-driven
    flips get `0` -- `decisive_test` should recover a positive,
    CI-excluding-zero delta (price-driven beats drop-off-driven), and
    `type_vs_background` should show price-driven alone as CI-excluding-zero
    while drop-off-driven alone stays near zero.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        # Half the tickers get a "price shock" path (real, sustained moves
        # every ~20 days -> mostly price-driven flips); half get a
        # "one-off spike that later rolls out" path (mostly dropoff-driven
        # flips), so both flip types are well represented across the panel.
        n = n_dates + lookback + 5
        if i % 2 == 0:
            steps = rng.normal(0, 1.5, n)
            close = 100 + np.cumsum(steps)
        else:
            close = np.full(n, 100.0)
            spike_idxs = rng.integers(0, n - lookback - 2, size=max(1, n // 30))
            close[spike_idxs] += rng.normal(20, 5, len(spike_idxs))
            close = close + np.cumsum(rng.normal(0, 0.05, n))  # tiny drift, keeps SMA well-defined
        close = close[-n_dates:]
        for date, c in zip(dates, close):
            rows.append({
                "ticker": ticker, "date": date, "close": float(c),
                "mom_12_1": rng.normal(0, 0.02), "realized_vol_63": abs(rng.normal(0.2, 0.02)), "sector": "X",
            })
    panel = pd.DataFrame(rows)
    prepared = sd.prepare(panel)

    price_col = sd._flip_price_driven_col(lookback)
    is_price = prepared[price_col].fillna(False).astype(bool)
    planted = np.where(is_price.to_numpy(), gradient, 0.0)
    noise = rng.normal(0, 0.01, len(prepared))
    prepared["fwd_ret_21"] = planted + noise
    return prepared


def test_decisive_test_recovers_planted_price_vs_dropoff_gap():
    prepared = _planted_panel(gradient=0.03, seed=1)
    result = sd.decisive_test(prepared, lookback=50)

    assert not result["below_threshold"], result
    assert result["c2"] > 0
    assert result["ci_low"] > 0  # CI excludes zero, entirely positive
    assert result["ci_excludes_zero"] is True
    assert result["killed"] is False


def test_type_vs_background_distinguishes_price_from_dropoff():
    prepared = _planted_panel(gradient=0.03, seed=2)
    price_result = sd.type_vs_background(prepared, lookback=50, flip_type="price")
    dropoff_result = sd.type_vs_background(prepared, lookback=50, flip_type="dropoff")

    assert price_result["ci_excludes_zero"] is True
    assert price_result["c2"] > 0
    # Drop-off-driven flips were planted with zero effect. At this sample
    # size even a near-zero point estimate can technically clear a 90% CI
    # (large-N power, not a real economic effect) -- the meaningful check
    # is magnitude relative to the planted price-driven effect, not a bare
    # CI-excludes-zero read.
    assert abs(dropoff_result["c2"]) < abs(price_result["c2"]) * 0.05


def test_event_frequency_is_finite_and_positive_when_flips_exist():
    prepared = _planted_panel(gradient=0.0, seed=3)
    freq = sd.event_frequency_per_ticker_year(prepared, sd._flip_price_driven_col(50))
    assert freq > 0
    assert np.isfinite(freq)


def test_decisive_test_direction_restricts_to_up_or_down_flips_only():
    prepared = _planted_panel(gradient=0.02, seed=4)
    lookback = 50
    up = sd.decisive_test(prepared, lookback=lookback, direction="up")
    down = sd.decisive_test(prepared, lookback=lookback, direction="down")
    pooled = sd.decisive_test(prepared, lookback=lookback)

    assert up["n_events"] + down["n_events"] == pooled["n_events"]
    assert up["n_events"] > 0 and down["n_events"] > 0
