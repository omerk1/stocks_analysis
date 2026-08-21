import numpy as np
import pandas as pd
import pytest

from src.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.detectors.double_top_bottom import DoubleTopBottomDetector
from src.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        expire_lifespan_mult=2.0, failed_breakout_reclaim_bars=3, breakout_buffer_pct=0.001,
        double_top_symmetry_hard_gate_pct=8.0, double_top_typical_min_bars=1, double_top_typical_max_bars=200,
    )
    defaults.update(overrides)
    return PatternConfig(**defaults)


def _chain(*segments: tuple[float, float, int], start: str = "2020-01-01") -> pd.DataFrame:
    """segments: (start_price, end_price, n_bars) tuples, laid out back to
    back in time -- bar_index of the k-th segment's j-th bar is the sum of
    all prior segments' lengths plus j."""
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


def _double_top_pivots(df: pd.DataFrame, p1_i=9, p1_price=130.0, t_i=14, t_price=121.0, p2_i=19, p2_price=129.0):
    return [
        _pivot(p1_i, p1_price, PivotKind.HIGH, df),
        _pivot(t_i, t_price, PivotKind.LOW, df),
        _pivot(p2_i, p2_price, PivotKind.HIGH, df),
    ]


# Prior uptrend (0-9, 100->130) -> decline to trough (10-14, 128->121) ->
# recovery near the first peak (15-19, 123->129) -> shared prefix for every
# double-top scenario below; each test appends its own bars 20+.
_PREFIX = [(100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5)]


def test_double_top_confirmed_breakout_hits_target():
    # neckline=121, target = 121 - ((130+129)/2 - 121) = 112.5
    df = _chain(*_PREFIX, (127.0, 100.0, 10))
    df.loc[df.index[23], "volume"] = 1600.0  # breakout bar gets volume expansion
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.DOUBLE_TOP
    assert m.direction == Direction.BEARISH
    assert m.key_levels == {"p1": 130.0, "neckline": 121.0, "p2": 129.0}
    assert m.target_price == pytest.approx(112.5)
    assert m.stop_price == pytest.approx(130.0)
    assert m.breakout_bar == 23
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_double_bottom_mirrors_double_top():
    # Mirror of the double-top fixture: 200 - price, so a downtrend into a
    # LOW-HIGH-LOW pivot triple, bullish breakout upward through target.
    df = _chain((100.0, 70.0, 10), (72.0, 79.0, 5), (77.0, 71.0, 5), (73.0, 100.0, 10))
    pivots = [
        _pivot(9, 70.0, PivotKind.LOW, df),
        _pivot(14, 79.0, PivotKind.HIGH, df),
        _pivot(19, 71.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.DOUBLE_BOTTOM
    assert m.direction == Direction.BULLISH
    # neckline=79, target = 79 + (79 - (70+71)/2) = 79 + 8.5 = 87.5
    assert m.target_price == pytest.approx(87.5)
    assert m.stop_price == pytest.approx(70.0)
    assert m.breakout_bar == 23
    assert m.status == PatternStatus.HIT_TARGET


def test_symmetry_hard_gate_rejects_far_apart_peaks():
    df = _chain((100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 150.0, 5), (148.0, 100.0, 10))
    pivots = _double_top_pivots(df, p2_price=150.0)  # |130-150|/130 = 15.4% > 8% gate
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_weak_prior_trend_rejects_candidate():
    # Flat run-up (no real prior trend) instead of _PREFIX's 30% rise.
    df = _chain((129.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 100.0, 10))
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_new_high_beyond_both_peaks_before_breakout_invalidates():
    # After p2, price makes a new high above max(p1, p2)=130 without ever
    # closing below the neckline first.
    df = _chain(*_PREFIX, (129.0, 135.0, 10))
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.INVALIDATED
    assert matches[0].breakout_bar is None


def test_failed_breakout_reclaim_within_window_flags_failed_breakout():
    # Breaks the neckline, then reclaims back above it within
    # failed_breakout_reclaim_bars=3, well before ever reaching target.
    df = _chain(*_PREFIX, (118.0, 118.0, 1), (125.0, 128.0, 4))
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 20  # first bar of the (118, 118, 1) segment
    assert m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_expired_when_no_breakout_within_deadline():
    # formation_bars = 19 - 9 = 10; expire_lifespan_mult=2.0 -> pending
    # deadline at bar 19+20=39. Flat bars near the neckline (never actually
    # crossing it) run well past that with no breakout.
    df = _chain(*_PREFIX, (122.0, 122.0, 30))
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.EXPIRED
    assert matches[0].breakout_bar is None


def test_pending_when_not_enough_bars_yet_to_resolve():
    # Only a few bars past p2, none of them breaking out or expiring yet.
    df = _chain(*_PREFIX, (128.0, 126.0, 3))
    pivots = _double_top_pivots(df)
    config = _config()

    matches = DoubleTopBottomDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.PENDING
    assert matches[0].breakout_bar is None
