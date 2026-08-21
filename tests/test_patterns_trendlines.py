import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Pivot, PivotKind
from src.patterns.trendlines import (
    count_touches, fit_line, has_prior_trend, level_tolerance, prior_trend_pct, touches_level,
)


def _bars(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        index=idx,
    )


def _pivot(bar_index: int, price: float, kind: PivotKind = PivotKind.HIGH) -> Pivot:
    return Pivot(kind=kind, timestamp="2020-01-01", value=price, confirmed_at="2020-01-01",
                 threshold_at_pivot=1.0, bar_index=bar_index)


def test_fit_line_exact_through_two_points():
    slope, intercept = fit_line(np.array([0.0, 10.0]), np.array([100.0, 150.0]))
    assert slope == pytest.approx(5.0)
    assert intercept == pytest.approx(100.0)


def test_fit_line_least_squares_over_noisy_points():
    xs = np.array([0.0, 1.0, 2.0, 3.0])
    ys = np.array([0.0, 1.1, 1.9, 3.05])
    slope, intercept = fit_line(xs, ys)
    assert slope == pytest.approx(1.0, abs=0.1)
    assert intercept == pytest.approx(0.0, abs=0.1)


def test_has_prior_trend_true_for_qualifying_uptrend():
    # Flat at 100 for 10 bars, then a clean rise to 120 by bar 20 (20% over
    # 10 bars) -- pivot sits at the end of the rise.
    closes = [100] * 10 + list(np.linspace(100, 120, 11))[1:]
    bars = _bars(closes)
    pivot = _pivot(len(closes) - 1, closes[-1])

    assert has_prior_trend(bars, pivot, min_pct=15.0, min_bars=5, direction="up")


def test_has_prior_trend_false_when_move_too_small():
    closes = [100] * 10 + list(np.linspace(100, 105, 11))[1:]  # only 5%
    bars = _bars(closes)
    pivot = _pivot(len(closes) - 1, closes[-1])

    assert not has_prior_trend(bars, pivot, min_pct=15.0, min_bars=5, direction="up")


def test_has_prior_trend_false_when_not_enough_history_before_pivot():
    # Only 3 bars exist before the pivot at all -- can't measure a 5-bar
    # prior trend regardless of how large the move looks.
    closes = [100.0, 110.0, 120.0, 130.0]
    bars = _bars(closes)
    pivot = _pivot(len(closes) - 1, closes[-1])

    assert not has_prior_trend(bars, pivot, min_pct=15.0, min_bars=5, direction="up")


def test_prior_trend_pct_measures_magnitude_not_just_a_bool():
    closes = [100] * 10 + list(np.linspace(100, 120, 11))[1:]  # 20% rise
    bars = _bars(closes)
    pivot = _pivot(len(closes) - 1, closes[-1])

    pct = prior_trend_pct(bars, pivot, min_bars=5, direction="up")
    # extreme is the plateau's low (99.5, since _bars puts low = close-0.5),
    # pivot's own close is 120 -> (120-99.5)/99.5*100.
    assert pct == pytest.approx(20.6, abs=0.1)


def test_prior_trend_pct_none_when_not_enough_history():
    bars = _bars([100.0, 110.0, 120.0])
    pivot = _pivot(2, 120.0)
    assert prior_trend_pct(bars, pivot, min_bars=5, direction="up") is None


def test_has_prior_trend_down_direction_mirrors_up():
    closes = [100] * 10 + list(np.linspace(100, 80, 11))[1:]  # 20% decline
    bars = _bars(closes)
    pivot = _pivot(len(closes) - 1, closes[-1])

    assert has_prior_trend(bars, pivot, min_pct=15.0, min_bars=5, direction="down")


def test_level_tolerance_uses_the_looser_of_atr_and_pct():
    # ATR-based: 0.5 * 4.0 = 2.0; pct-based: 0.005 * 100 = 0.5 -- ATR wins.
    assert level_tolerance(price=100.0, atr=4.0, atr_mult=0.5, pct=0.005) == pytest.approx(2.0)
    # ATR-based: 0.5 * 0.1 = 0.05; pct-based: 0.005 * 100 = 0.5 -- pct wins.
    assert level_tolerance(price=100.0, atr=0.1, atr_mult=0.5, pct=0.005) == pytest.approx(0.5)


def test_touches_level_within_and_outside_tolerance():
    assert touches_level(bar_price=101.0, level_price=100.0, tolerance=2.0)
    assert not touches_level(bar_price=103.0, level_price=100.0, tolerance=2.0)


def test_count_touches_counts_bars_within_tolerance_of_a_flat_level():
    bars = _bars([100, 100, 105, 100, 110, 100, 95])
    atr = pd.Series([2.0] * len(bars), index=bars.index)
    # Level at 100: bars 0,1,3,5 close-to-level (highs/lows within 0.5 of
    # 100), bar 6 (close=95, high=95.5, low=94.5) is out of tolerance.
    count = count_touches(
        bars["high"], bars["low"], atr, level_at=lambda i: 100.0, atr_mult=0.5, pct=0.005
    )
    assert count == 4
