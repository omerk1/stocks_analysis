"""Tests for M8's new kernel families (`features/kernels.py`,
PREREGISTRATION.md 2026-09-24). Mechanics only -- hand-computed small
examples, the impulse-response center-of-mass method's own correctness
(validated against SMA/EMA's known-exact closed form before it's trusted
for HMA/DEMA/VWMA, which have no independent closed form), and each
family's basic sanity properties. Real-panel results are logged
separately.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.indicators import ema as ema_fn
from src.foundation.market_common.indicators import sma as sma_fn
from src.signals.moving_averages.features import kernels


def test_wma_matches_hand_computed_small_example():
    close = pd.Series([1.0, 2.0, 3.0])
    result = kernels.wma(close, period=3)
    # weights 1,2,3 (oldest to newest) -> (1*1 + 2*2 + 3*3) / 6 = 14/6
    assert result.iloc[2] == pytest.approx(14 / 6)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])


def test_wma_is_more_recent_weighted_than_sma():
    # A sharp recent jump should move WMA more than SMA over the same window.
    close = pd.Series([10.0] * 9 + [20.0])
    wma_val = kernels.wma(close, period=10).iloc[-1]
    sma_val = sma_fn(close, 10).iloc[-1]
    assert wma_val > sma_val


def test_dema_matches_hand_computed_formula():
    close = pd.Series(np.linspace(1, 50, 60))
    result = kernels.dema(close, period=5)
    e1 = ema_fn(close, 5)
    e2 = ema_fn(e1, 5)
    expected = 2 * e1 - e2
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_kama_tracks_faster_on_an_efficient_trend_than_on_noise():
    n = 200
    trend = pd.Series(np.linspace(0, 100, n))
    rng = np.random.default_rng(0)
    noisy = pd.Series(50 + rng.normal(0, 1, n).cumsum() * 0 + rng.normal(0, 5, n))

    kama_trend = kernels.kama(trend)
    kama_noise = kernels.kama(noisy)

    # On a perfectly efficient (straight-line) trend, KAMA should track
    # very close to price itself (high efficiency ratio -> fast_sc).
    trend_tracking_error = (trend.iloc[50:] - kama_trend.iloc[50:]).abs().mean()
    # On pure noise, KAMA should smooth heavily -- its own variance should
    # be well below the raw series' variance.
    assert kama_noise.iloc[50:].std() < noisy.iloc[50:].std()
    assert trend_tracking_error < 1.0  # tracks the line closely, not a lagged smoothing artefact


def test_vwma_reduces_to_sma_under_constant_volume():
    rng = np.random.default_rng(1)
    close = pd.Series(100 + rng.normal(0, 1, 100).cumsum())
    constant_volume = pd.Series([1_000.0] * 100)

    vwma_result = kernels.vwma(close, constant_volume, period=20)
    sma_result = sma_fn(close, 20)
    pd.testing.assert_series_equal(vwma_result, sma_result, check_names=False)


def test_vwma_weights_toward_high_volume_days():
    close = pd.Series([10.0, 10.0, 10.0, 20.0])
    volume = pd.Series([1.0, 1.0, 1.0, 1000.0])  # last (highest-price) day dominates
    result = kernels.vwma(close, volume, period=4)
    # Exact: (10*1 + 10*1 + 10*1 + 20*1000) / 1003 = 19.9701 -- much closer
    # to the high-volume day's price (20) than the unweighted mean (12.5).
    assert result.iloc[-1] == pytest.approx(20030 / 1003, abs=1e-6)
    assert result.iloc[-1] > 19.5


def test_impulse_center_of_mass_matches_sma_closed_form():
    for period in (10, 20, 50):
        measured = kernels.impulse_center_of_mass(lambda s, p: sma_fn(s, p), period)
        expected = (period - 1) / 2
        assert measured == pytest.approx(expected, abs=1e-6)


def test_impulse_center_of_mass_matches_ema_closed_form_approximately():
    # EMA's average lag converges to (period-1)/2 asymptotically (the same
    # value as SMA at the same period) -- a small tolerance since the
    # impulse response's own geometric tail is truncated at the test's
    # finite horizon, not because the closed form itself is approximate.
    for period in (10, 20, 50):
        measured = kernels.impulse_center_of_mass(lambda s, p: ema_fn(s, p), period)
        expected = (period - 1) / 2
        assert measured == pytest.approx(expected, rel=0.05)


def test_hma_has_lower_center_of_mass_than_plain_wma_same_period():
    # HMA is an explicitly lag-reduced construction -- its own measured lag
    # at a given period must sit below plain WMA's at that same period,
    # or the "reduced lag" premise DESIGN's own module text asserts is
    # simply wrong for this implementation.
    period = 50
    hma_com = kernels.impulse_center_of_mass(kernels.hma, period)
    wma_com = kernels.impulse_center_of_mass(kernels.wma, period)
    assert hma_com < wma_com


def test_dema_has_lower_center_of_mass_than_plain_ema_same_period():
    period = 50
    dema_com = kernels.impulse_center_of_mass(kernels.dema, period)
    ema_com = kernels.impulse_center_of_mass(lambda s, p: ema_fn(s, p), period)
    assert dema_com < ema_com


def test_impulse_center_of_mass_is_nan_when_response_is_degenerate():
    # period far larger than the series itself -> an all-NaN response.
    result = kernels.impulse_center_of_mass(lambda s, p: sma_fn(s, p), period=5000, n=100, impulse_at=50)
    assert math.isnan(result)


def test_solve_matched_period_recovers_known_wma_target():
    # WMA's own closed-form average lag is (period-1)/3 -- to match
    # SMA(50)'s own COM of 24.5, the exact real-valued solution is
    # period = 74.5; the nearest integer should be 74 or 75.
    target_com = (50 - 1) / 2
    period, measured_com = kernels.solve_matched_period(kernels.wma, target_com, bounds=(2, 150))
    assert period in (74, 75)
    assert measured_com == pytest.approx(target_com, abs=0.5)
