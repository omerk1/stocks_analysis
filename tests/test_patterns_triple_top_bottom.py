import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.double_top_bottom import DoubleTopBottomDetector
from src.signals.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        expire_lifespan_mult=2.0, breakout_buffer_pct=0.001,
        triple_top_symmetry_hard_gate_pct=8.0, triple_top_typical_min_bars=1, triple_top_typical_max_bars=200,
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


# Prior uptrend (0-9, 100->130) -> 3 comparable peaks (130, 129, 131) with
# two intervening troughs (121, 120) -> shared prefix for every triple-top
# scenario below; each test appends its own breakdown bars.
_PREFIX = [(100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 120.0, 5), (122.0, 131.0, 5)]


def _triple_top_pivots(df, e1=130.0, t1=121.0, e2=129.0, t2=120.0, e3=131.0):
    return [
        _pivot(9, e1, PivotKind.HIGH, df),
        _pivot(14, t1, PivotKind.LOW, df),
        _pivot(19, e2, PivotKind.HIGH, df),
        _pivot(24, t2, PivotKind.LOW, df),
        _pivot(29, e3, PivotKind.HIGH, df),
    ]


def test_triple_top_confirmed_breakout_hits_target():
    # neckline=120, target = 120 - (130 avg - 120) = 110
    df = _chain(*_PREFIX, (118.0, 90.0, 10))
    pivots = _triple_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    triples = [m for m in matches if m.pattern_type == PatternType.TRIPLE_TOP]
    assert len(triples) == 1
    m = triples[0]
    assert m.direction == Direction.BEARISH
    assert m.key_levels["neckline"] == 120.0
    assert m.key_levels["p1"] == 130.0 and m.key_levels["p2"] == 129.0 and m.key_levels["p3"] == 131.0
    assert m.target_price == pytest.approx(110.0)
    assert m.stop_price == pytest.approx(131.0)
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0


def test_triple_bottom_mirrors_triple_top():
    # Mirror of the triple-top fixture: 250 - price.
    df = _chain((150.0, 120.0, 10), (122.0, 129.0, 5), (127.0, 121.0, 5), (123.0, 130.0, 5), (128.0, 119.0, 5), (132.0, 160.0, 10))
    pivots = [
        _pivot(9, 120.0, PivotKind.LOW, df),
        _pivot(14, 129.0, PivotKind.HIGH, df),
        _pivot(19, 121.0, PivotKind.LOW, df),
        _pivot(24, 130.0, PivotKind.HIGH, df),
        _pivot(29, 119.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    triples = [m for m in matches if m.pattern_type == PatternType.TRIPLE_BOTTOM]
    assert len(triples) == 1
    m = triples[0]
    assert m.direction == Direction.BULLISH
    assert m.key_levels["neckline"] == 130.0
    assert m.status == PatternStatus.HIT_TARGET


def test_triple_top_symmetry_hard_gate_rejects_far_apart_peaks():
    # |150-130|/130 = 15.4% > 8% gate
    df = _chain(*_PREFIX, (118.0, 90.0, 10))
    pivots = _triple_top_pivots(df, e3=150.0)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert [m for m in matches if m.pattern_type == PatternType.TRIPLE_TOP] == []
