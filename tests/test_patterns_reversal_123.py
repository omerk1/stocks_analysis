import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.reversal_123 import Reversal123Detector
from src.signals.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        expire_lifespan_mult=2.0, breakout_buffer_pct=0.001,
        reversal_123_typical_min_bars=1, reversal_123_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


def _chain(*segments: tuple[float, float, int], start: str = "2020-01-01") -> pd.DataFrame:
    frames = []
    cursor = pd.Timestamp(start)
    for p0, p1, n in segments:
        idx = pd.bdate_range(cursor, periods=n)
        closes = np.linspace(p0, p1, n)
        frames.append(pd.DataFrame(
            {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0},
            index=idx,
        ))
        cursor = idx[-1] + pd.Timedelta(days=1)
    return pd.concat(frames)


def _pivot(bar_index: int, price: float, kind: PivotKind, df: pd.DataFrame) -> Pivot:
    ts = df.index[bar_index].isoformat()
    return Pivot(kind=kind, timestamp=ts, value=price, confirmed_at=ts, threshold_at_pivot=1.0, bar_index=bar_index)


# Prior downtrend (0-9, 130->100) -> Point 1 low (bar 9, 100) -> retracement
# to Point 2 high (bar 14, 110) -> Point 3 higher low (bar 19, 104) -> break
# above Point 2 (110) confirms the bullish reversal.
_BULLISH_PREFIX = [(130.0, 100.0, 10), (101.0, 110.0, 5), (109.0, 104.0, 5)]


def _bullish_pivots(df: pd.DataFrame, p1_i=9, p1_price=100.0, p2_i=14, p2_price=110.0, p3_i=19, p3_price=104.0):
    return [
        _pivot(p1_i, p1_price, PivotKind.LOW, df),
        _pivot(p2_i, p2_price, PivotKind.HIGH, df),
        _pivot(p3_i, p3_price, PivotKind.LOW, df),
    ]


def test_bullish_reversal_confirmed_breakout_hits_target():
    # trigger=110, target = 110 + (110-100) = 120
    df = _chain(*_BULLISH_PREFIX, (105.0, 130.0, 10))
    pivots = _bullish_pivots(df)
    config = _config()

    matches = Reversal123Detector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.REVERSAL_123
    assert m.direction == Direction.BULLISH
    assert m.key_levels == {"point1": 100.0, "point2": 110.0, "point2_bar": 14.0, "point3": 104.0}
    assert m.target_price == pytest.approx(120.0)
    assert m.stop_price == pytest.approx(100.0)
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0


def test_bearish_reversal_mirrors_bullish():
    # Mirror: prior uptrend into Point 1 high, retrace to Point 2 low
    # (trigger), Point 3 lower high, breakdown below Point 2.
    df = _chain((70.0, 100.0, 10), (99.0, 90.0, 5), (91.0, 96.0, 5), (95.0, 70.0, 10))
    pivots = [
        _pivot(9, 100.0, PivotKind.HIGH, df),
        _pivot(14, 90.0, PivotKind.LOW, df),
        _pivot(19, 96.0, PivotKind.HIGH, df),
    ]
    config = _config()

    matches = Reversal123Detector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.direction == Direction.BEARISH
    assert m.target_price == pytest.approx(80.0)  # 90 - (100-90)
    assert m.stop_price == pytest.approx(100.0)
    assert m.status == PatternStatus.HIT_TARGET


def test_point3_not_higher_than_point1_rejects_candidate():
    # Point 3 (99) fails to clear Point 1 (100) -- not a genuine higher low.
    df = _chain(*_BULLISH_PREFIX, (105.0, 130.0, 10))
    pivots = _bullish_pivots(df, p3_price=99.0)
    config = _config()

    matches = Reversal123Detector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_breach_of_point1_before_point2_invalidates():
    # Price falls back below Point 1 (100) before ever closing above
    # Point 2 (110) -- design doc: invalidate, don't wait for Point 2.
    df = _chain((130.0, 100.0, 10), (101.0, 108.0, 5), (107.0, 104.0, 5), (98.0, 90.0, 5))
    pivots = _bullish_pivots(df, p2_price=108.0, p3_price=104.0)
    config = _config()

    matches = Reversal123Detector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.INVALIDATED
