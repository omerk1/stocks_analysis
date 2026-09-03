import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.head_shoulders import HeadShouldersDetector
from src.signals.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        expire_lifespan_mult=2.0, breakout_buffer_pct=0.001,
        head_shoulders_symmetry_hard_gate_pct=15.0, head_shoulders_min_leg_bars=5,
        head_shoulders_neckline_max_slope_pct=10.0,
        head_shoulders_typical_min_bars=1, head_shoulders_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


def _chain(*segments: tuple[float, float, int], start: str = "2020-01-01") -> pd.DataFrame:
    """Same helper as test_patterns_double_top_bottom.py: segments are
    (start_price, end_price, n_bars) tuples laid out back to back."""
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


# Prior uptrend (0-9, 100->130) -> left shoulder @9=130 -> decline to
# trough1 (10-14, 128->121) -> rally to head @19=140 (>130, dominant peak)
# -> decline to trough2 (20-24, 138->119) -> rally to right shoulder
# @29=129 (close to 130) -> shared prefix for every H&S-top scenario
# below; each test appends its own bars 30+.
_PREFIX = [(100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 140.0, 5), (138.0, 119.0, 5), (121.0, 129.0, 5)]
# neckline through (14, 121) and (24, 119): slope=-0.2, intercept=123.8
# neckline_at_p2(29) = 118.0; head_height = 140 - neckline_at(19)=120.0 = 20
# target = 118.0 - 20 = 98.0; stop = head = 140.0


def _hs_pivots(df, p1_i=9, p1_price=130.0, t1_i=14, t1_price=121.0, head_i=19, head_price=140.0,
                t2_i=24, t2_price=119.0, p2_i=29, p2_price=129.0):
    return [
        _pivot(p1_i, p1_price, PivotKind.HIGH, df),
        _pivot(t1_i, t1_price, PivotKind.LOW, df),
        _pivot(head_i, head_price, PivotKind.HIGH, df),
        _pivot(t2_i, t2_price, PivotKind.LOW, df),
        _pivot(p2_i, p2_price, PivotKind.HIGH, df),
    ]


def test_head_shoulders_confirmed_breakout_hits_target():
    df = _chain(*_PREFIX, (127.0, 90.0, 15))
    df.loc[df.index[34], "volume"] = 1600.0  # breakout bar gets volume expansion
    pivots = _hs_pivots(df)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.HEAD_AND_SHOULDERS
    assert m.direction == Direction.BEARISH
    assert m.key_levels == {
        "left_shoulder": 130.0, "neckline_t1": 121.0, "head": 140.0,
        "neckline_t2": 119.0, "right_shoulder": 129.0,
    }
    assert m.trendlines["neckline"] == pytest.approx((-0.2, 123.8))
    assert m.target_price == pytest.approx(98.0)
    assert m.stop_price == pytest.approx(140.0)
    assert m.breakout_bar == 34
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_inverse_head_shoulders_mirrors_head_shoulders():
    df = _chain(
        (100.0, 70.0, 10), (72.0, 79.0, 5), (77.0, 60.0, 5), (62.0, 81.0, 5), (79.0, 71.0, 5),
        (73.0, 110.0, 15),
    )
    pivots = [
        _pivot(9, 70.0, PivotKind.LOW, df),
        _pivot(14, 79.0, PivotKind.HIGH, df),
        _pivot(19, 60.0, PivotKind.LOW, df),
        _pivot(24, 81.0, PivotKind.HIGH, df),
        _pivot(29, 71.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.INVERSE_HEAD_AND_SHOULDERS
    assert m.direction == Direction.BULLISH
    # neckline through (14,79),(24,81): slope=0.2, intercept=76.2
    # neckline_at_p2(29)=82.0; head_height=80.0-60.0=20; target=82+20=102
    assert m.target_price == pytest.approx(102.0)
    assert m.stop_price == pytest.approx(60.0)
    assert m.breakout_bar == 34
    assert m.status == PatternStatus.HIT_TARGET


def test_head_not_exceeding_both_shoulders_rejects_candidate():
    # Head (135) fails to exceed the right shoulder (138) -- not a
    # structurally valid H&S at all, per §4.1 point 3.
    df = _chain(*_PREFIX)
    pivots = _hs_pivots(df, head_price=135.0, p2_price=138.0)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_symmetry_hard_gate_rejects_far_apart_shoulders():
    # |130-100|/140 = 21.4% > 15% gate.
    df = _chain(*_PREFIX)
    pivots = _hs_pivots(df, p2_price=100.0)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_weak_prior_trend_rejects_candidate():
    # Flat run-up into the left shoulder instead of _PREFIX's 30% rise.
    df = _chain((129.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 140.0, 5), (138.0, 119.0, 5), (121.0, 129.0, 5))
    pivots = _hs_pivots(df)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_short_leg_rejects_candidate():
    # trough1 pulled in to bar 12 -- leg(p1->t1) = 12-9 = 3 < min of 5.
    df = _chain(*_PREFIX)
    pivots = _hs_pivots(df, t1_i=12)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_neckline_slope_cap_rejects_steep_neckline():
    # t2 dropped to 50 (from 119): slope=(50-121)/10=-7.1/bar, implying a
    # ~58.7% change over the neckline's own span -- way past the 10% cap.
    df = _chain(*_PREFIX)
    pivots = _hs_pivots(df, t2_price=50.0)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_new_high_beyond_head_before_breakout_invalidates():
    # After the right shoulder, price rallies straight through the head
    # level (140) without ever closing below the neckline first.
    df = _chain(*_PREFIX, (129.0, 145.0, 10))
    pivots = _hs_pivots(df)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.INVALIDATED
    assert matches[0].breakout_bar is None


def test_reclaim_without_reaching_target_flags_failed_breakout():
    # Breaks the neckline for one bar, then reclaims back above it and
    # never reaches target before the resolution horizon elapses (the tail
    # has to outrun that horizon -- see the double-top equivalent).
    df = _chain(*_PREFIX, (115.0, 115.0, 1), (125.0, 128.0, 40))
    pivots = _hs_pivots(df)
    config = _config(target_horizon_min_bars=5, target_horizon_max_bars=10)

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 30  # first bar of the (115, 115, 1) segment
    assert m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_expired_when_no_breakout_within_deadline():
    # formation_bars = 29-9 = 20; expire_lifespan_mult=2.0 -> pending
    # deadline at bar 29+40=69. Flat bars that stay above the (declining)
    # neckline and below the head run well past that with no breakout.
    df = _chain(*_PREFIX, (122.0, 122.0, 45))
    pivots = _hs_pivots(df)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.EXPIRED
    assert matches[0].breakout_bar is None


def test_pending_when_not_enough_bars_yet_to_resolve():
    df = _chain(*_PREFIX, (128.0, 126.0, 3))
    pivots = _hs_pivots(df)
    config = _config()

    matches = HeadShouldersDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.PENDING
    assert matches[0].breakout_bar is None
