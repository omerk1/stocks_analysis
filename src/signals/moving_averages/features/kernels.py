"""New MA kernel families for M8's horse race (DESIGN.md lines ~930-934,
PREREGISTRATION.md, 2026-09-24). Module-local -- WMA/HMA/DEMA/KAMA/VWMA are
NOT added to the shared cached panel (a sibling M10 fork owns
`features/panel.py` exclusively this batch); every function here takes and
returns a plain `pd.Series` (the same calling convention
`market_common.indicators.sma`/`ema` already use), so `modules/
kernel_horse_race.py` applies them per-ticker via
`.groupby("ticker").transform(...)`, the same pattern M3/M6.6/M12 already
used for their own module-local columns.

Lag-matching (the module's own load-bearing methodology -- full writeup in
PREREGISTRATION.md): each family's own average lag ("center of mass") is
measured empirically via `impulse_center_of_mass`, an impulse-response
test, rather than hand-derived closed-form formulas for every family. This
is deliberate: SMA/EMA have clean, well-known closed forms
(`(period-1)/2` for both, at the same `period` -- SMA is an exact
rolling-window average, EMA's asymptotic mean lag under the standard
alpha=2/(period+1) convention converges to the same value), but HMA/DEMA
do not have an equally clean closed form, and KAMA's lag is inherently
data-adaptive, not fixed at all. Measuring every family the same way
(numerically) avoids a hand-derivation error in the harder cases silently
biasing the whole module's matched-lag comparison, and is validated
against SMA/EMA's own known-exact values in
`tests/test_moving_averages_kernels.py` before being trusted for the
others.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.market_common.indicators import ema as ema_fn


def wma(close: pd.Series, period: int) -> pd.Series:
    """Linearly weighted moving average: weight `period` at lag 0 (most
    recent bar), weight 1 at lag `period - 1` (oldest bar in the window) --
    the standard convention. Closed-form average lag: `(period - 1) / 3`.
    """
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return close.rolling(period).apply(lambda w: np.dot(w, weights) / weight_sum, raw=True)


def hma(close: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average (Hull, 2005): `WMA(sqrt(n))` of
    `2*WMA(n/2) - WMA(n)` -- an explicitly lag-reduced construction with no
    clean closed-form average lag (measured empirically, see module
    docstring). `n/2` and `sqrt(n)` are rounded to the nearest integer
    (minimum 1) since `wma` needs an integer window.
    """
    half = max(1, round(period / 2))
    sqrt_n = max(1, round(np.sqrt(period)))
    raw = 2 * wma(close, half) - wma(close, period)
    return wma(raw, sqrt_n)


def dema(close: pd.Series, period: int) -> pd.Series:
    """Double EMA (Mulloy, 1994): `2*EMA(n) - EMA(EMA(n))` -- reduces (does
    not eliminate) the single-EMA lag. No clean closed-form average lag
    either (measured empirically). Reuses `market_common.indicators.ema`
    directly (the same EMA this study's cached panel itself uses), not a
    second EMA implementation.
    """
    e1 = ema_fn(close, period)
    e2 = ema_fn(e1, period)
    return 2 * e1 - e2


def kama(close: pd.Series, er_period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average (Kaufman, 1998), at its standard
    canonical parameters (`er_period=10, fast=2, slow=30`) -- deliberately
    NOT force-matched to a fixed lag target the way every other family in
    this module is. KAMA's own smoothing constant continuously adapts
    between the `fast`/`slow` bounds based on a rolling efficiency ratio,
    so "this family's fixed matched-lag parameter" is a category error for
    KAMA specifically (PREREGISTRATION.md's own scope note names this
    explicitly). Its own empirically-measured lag on this module's impulse
    test is still reported as a diagnostic number, just not treated as a
    parameter search target.
    """
    change = (close - close.shift(er_period)).abs()
    volatility = close.diff().abs().rolling(er_period).sum()
    er = (change / volatility).fillna(0.0)
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    smoothing = (er * (fast_sc - slow_sc) + slow_sc) ** 2

    values = close.to_numpy()
    smoothing_values = smoothing.to_numpy()
    out = np.full(len(values), np.nan)
    first_valid = er_period
    if len(values) <= first_valid:
        return pd.Series(out, index=close.index)

    out[first_valid] = values[first_valid]
    for i in range(first_valid + 1, len(values)):
        prev = out[i - 1]
        if np.isnan(prev) or np.isnan(values[i]):
            out[i] = values[i]
        else:
            out[i] = prev + smoothing_values[i] * (values[i] - prev)
    return pd.Series(out, index=close.index)


def vwma(close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    """Volume-weighted moving average: rolling `sum(close*volume) /
    sum(volume)`. Under a constant-volume idealization this reduces
    exactly to `SMA(period)` -- and this module's own lag-matching
    methodology uses a constant synthetic volume series for its impulse
    test (an impulse test has no real volume pattern to weight by), so
    VWMA's own matched-lag parameter, honestly, ends up identical to
    SMA's. PREREGISTRATION.md names this explicitly as a limitation: VWMA's
    *real* average lag on actual, non-uniform volume will generally be
    shorter than this idealized value (volume tends to concentrate near
    price extremes/reversals, not spread evenly across the window) -- not
    measured here, flagged as an open caveat rather than silently assumed
    away.
    """
    pv = (close * volume).rolling(period).sum()
    v = volume.rolling(period).sum()
    return pv / v


def impulse_center_of_mass(kernel_fn, period: int, n: int = 1000, impulse_at: int = 500) -> float:
    """Empirical average lag of `kernel_fn` (a callable taking a single
    `pd.Series` positional arg plus `period`, matching `wma`/`hma`/`dema`/
    `kama`'s own signatures) via a unit-impulse response: a synthetic
    series that is 0 everywhere except a single 1 at `impulse_at`, run
    through the kernel, center-of-mass'd over the causal response
    (indices >= `impulse_at`). `impulse_at` must sit well past the
    kernel's own warmup and leave enough trailing samples to capture
    (nearly) the whole response -- the defaults (1000 total, impulse at
    500, leaving 500 tail samples) comfortably cover every period this
    module's own search bounds (2-300) produce, including DEMA's slower
    geometric decay at larger periods. Returns NaN if the response is
    degenerate (e.g. `period` larger than the series itself).

    This function's own correctness is load-bearing for every family's
    matched-lag parameter, not just reported for interest -- validated
    against SMA/EMA's known-exact closed-form `(period-1)/2` in
    `tests/test_moving_averages_kernels.py` before being trusted for HMA/
    DEMA/VWMA, which have no independent closed form to check against.
    """
    x = np.zeros(n)
    x[impulse_at] = 1.0
    series = pd.Series(x)
    response = kernel_fn(series, period)
    tail = response.iloc[impulse_at:].fillna(0.0).to_numpy()
    lags = np.arange(len(tail))
    total = tail.sum()
    if total == 0 or np.isnan(total):
        return float("nan")
    return float((lags * tail).sum() / total)


def solve_matched_period(kernel_fn, target_com: float, bounds: tuple[int, int] = (2, 300)) -> tuple[int, float]:
    """Integer-period search (plain linear scan over `bounds`, not
    bisection -- center-of-mass is not guaranteed perfectly monotonic in
    `period` for every family, particularly HMA's own construction, so
    bisection could converge to a local rather than global match; `bounds`
    is small enough that a full scan is cheap and unambiguous) for the
    period whose `impulse_center_of_mass` sits closest to `target_com`.
    Returns `(best_period, its_own_measured_com)` -- the measured COM is
    returned alongside so the caller can report the actual matched value
    achieved (rounding to an integer period means it is never exact).
    """
    best_period, best_com, best_gap = bounds[0], float("nan"), float("inf")
    for period in range(bounds[0], bounds[1] + 1):
        com = impulse_center_of_mass(kernel_fn, period)
        if np.isnan(com):
            continue
        gap = abs(com - target_com)
        if gap < best_gap:
            best_period, best_com, best_gap = period, com, gap
    return best_period, best_com
