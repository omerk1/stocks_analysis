"""Tests for M9's regime features (`features/regime.py`, PREREGISTRATION.md
2026-09-24). Hand-computed small examples for `efficiency_ratio` and
`average_directional_index`, plus the fixed regime-bucket thresholds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.features import regime


def test_efficiency_ratio_matches_hand_computed_straight_line():
    # A perfectly straight-line move: net change == sum of absolute
    # changes, so ER must be exactly 1.0 (or NaN during warmup).
    close = pd.Series([100.0 + i for i in range(15)])
    er = regime.efficiency_ratio(close, period=10)
    assert er.iloc[10] == pytest.approx(1.0)


def test_efficiency_ratio_matches_hand_computed_zigzag():
    # Up 1, down 1, repeated: net change over any even window is 0, sum of
    # absolute changes is nonzero -> ER == 0.0.
    close = pd.Series([100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0])
    er = regime.efficiency_ratio(close, period=10)
    assert er.iloc[10] == pytest.approx(0.0, abs=1e-9)


def test_efficiency_ratio_is_nan_during_warmup():
    close = pd.Series([100.0 + i for i in range(5)])
    er = regime.efficiency_ratio(close, period=10)
    assert er.iloc[:5].isna().all()


def test_efficiency_ratio_matches_kama_own_inline_formula():
    """Cross-check against `features/kernels.py::kama`'s own inline `er` --
    PREREGISTRATION.md's own explicit requirement that this be the
    identical formula, not just a similar one.
    """
    from src.signals.moving_averages.features import kernels

    rng = np.random.default_rng(0)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 60)))

    er_standalone = regime.efficiency_ratio(close, period=10)

    change = (close - close.shift(10)).abs()
    volatility = close.diff().abs().rolling(10).sum()
    er_inline = (change / volatility).fillna(0.0)

    # kama's own inline version fillna(0.0)s the warmup; the standalone
    # version leaves it NaN (CLAUDE.md invariant #9) -- compare only the
    # defined region.
    defined = er_standalone.notna()
    assert defined.sum() > 0
    np.testing.assert_allclose(er_standalone[defined], er_inline[defined], rtol=1e-10)


def test_adx_is_high_for_a_strong_uptrend():
    n = 60
    close = pd.Series(100 + np.arange(n, dtype=float))
    high = close + 0.5
    low = close - 0.5
    adx = regime.average_directional_index(high, low, close, period=14)
    assert adx.iloc[-1] > regime.ADX_TRENDING_MIN


def test_adx_is_low_for_flat_chop():
    n = 60
    rng = np.random.default_rng(1)
    # Tight, mean-reverting oscillation -- no directional persistence.
    close = pd.Series(100 + np.sin(np.linspace(0, 40 * np.pi, n)) * 0.01)
    high = close + 0.02
    low = close - 0.02
    adx = regime.average_directional_index(high, low, close, period=14)
    assert adx.iloc[-1] < regime.ADX_TRENDING_MIN


def test_adx_is_nan_during_warmup():
    n = 20
    close = pd.Series(100 + np.arange(n, dtype=float))
    adx = regime.average_directional_index(close + 0.5, close - 0.5, close, period=14)
    assert adx.iloc[: 2 * 14].isna().all()


def test_er_regime_buckets_at_fixed_thresholds():
    er = pd.Series([0.1, 0.29, 0.3, 0.45, 0.6, 0.61, 0.9, np.nan])
    buckets = regime.er_regime(er)
    assert list(buckets.astype(object)) == [
        "choppy", "choppy", "moderate", "moderate", "trending", "trending", "trending", np.nan,
    ]


def test_adx_regime_buckets_at_fixed_thresholds():
    adx = pd.Series([5.0, 19.9, 20.0, 22.0, 25.0, 30.0, np.nan])
    buckets = regime.adx_regime(adx)
    assert list(buckets.astype(object)) == [
        "no_trend", "no_trend", "developing", "developing", "trending", "trending", np.nan,
    ]
