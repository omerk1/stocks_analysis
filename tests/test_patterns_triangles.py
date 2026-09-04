import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.triangles import TriangleWedgeDetector
from src.signals.patterns.models import PatternStatus, PatternType


def _config(**overrides) -> PatternConfig:
    defaults = dict(
        atr_period=3, volume_sma_period=5, expire_lifespan_mult=2.0, breakout_buffer_pct=0.001, triangle_typical_min_bars=1, triangle_typical_max_bars=200,
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


# ---------------------------------------------------------------------------
# Ascending triangle: flat upper (150 exactly, 3 highs) + rising lower
# (120->130->140, exactly linear -> slope=1.0/bar, intercept=106).
# upper=(0.0, 150.0), lower=(1.0, 106.0). apex: 150 = i+106 -> i=44.
# height at bar9 (widest) = 150 - 115 = 35. upper_target = 150+35 = 185;
# upper_stop = lower_at(34) = 140.
_ASCENDING_PREFIX = [
    (100.0, 150.0, 10), (148.0, 120.0, 5), (122.0, 150.0, 5),
    (148.0, 130.0, 5), (132.0, 150.0, 5), (148.0, 140.0, 5),
]


def _ascending_pivots(df):
    return [
        _pivot(9, 150.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 150.0, PivotKind.HIGH, df),
        _pivot(24, 130.0, PivotKind.LOW, df),
        _pivot(29, 150.0, PivotKind.HIGH, df),
        _pivot(34, 140.0, PivotKind.LOW, df),
    ]


def test_ascending_triangle_confirmed_breakout_hits_target():
    df = _chain(*_ASCENDING_PREFIX, (152.0, 152.0, 3), (155.0, 200.0, 10))
    df.loc[df.index[35], "volume"] = 1600.0
    pivots = _ascending_pivots(df)
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.ASCENDING_TRIANGLE
    assert m.trendlines["upper"] == pytest.approx((0.0, 150.0))
    assert m.trendlines["lower"] == pytest.approx((1.0, 106.0))
    assert m.key_levels["upper_target"] == pytest.approx(185.0)
    assert m.key_levels["lower_stop"] == pytest.approx(150.0)
    assert m.breakout_bar == 35
    assert m.direction == Direction.BULLISH
    assert m.target_price == pytest.approx(185.0)
    assert m.stop_price == pytest.approx(140.0)
    assert m.volume_confirmed is True
    assert m.status == PatternStatus.HIT_TARGET
    assert 0.0 < m.confidence <= 1.0
    assert len(m.notes) == 5


def test_non_converging_window_rejected():
    # Upper rising faster (slope=2.0) than lower (slope=1.0) -- diverging,
    # not a valid triangle/wedge.
    df = _chain(*_ASCENDING_PREFIX)
    pivots = [
        _pivot(9, 140.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 160.0, PivotKind.HIGH, df),
        _pivot(24, 130.0, PivotKind.LOW, df),
        _pivot(29, 180.0, PivotKind.HIGH, df),
        _pivot(34, 140.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_apex_already_behind_window_rejected():
    # Steep converging lines whose apex (31.5) falls before the window's
    # own last pivot (34) -- stale, not a valid triangle.
    df = _chain(*_ASCENDING_PREFIX)
    pivots = [
        _pivot(9, 160.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 150.0, PivotKind.HIGH, df),
        _pivot(24, 130.0, PivotKind.LOW, df),
        _pivot(29, 140.0, PivotKind.HIGH, df),
        _pivot(34, 140.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_insufficient_pivots_per_side_rejected():
    # Window of 3 pivots (H, L, H) -> 2 highs, only 1 low < min_touches_per_line.
    df = _chain(*_ASCENDING_PREFIX)
    pivots = _ascending_pivots(df)
    config = _config(triangle_window_pivots=3)

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)
    assert matches == []


def test_reclaim_without_reaching_target_flags_failed_breakout():
    df = _chain(*_ASCENDING_PREFIX, (151.0, 151.0, 1), (145.0, 145.0, 40))
    pivots = _ascending_pivots(df)
    config = _config(target_horizon_min_bars=5, target_horizon_max_bars=10)

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 35
    assert m.direction == Direction.BULLISH
    assert m.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT


def test_expired_at_apex_deadline_not_standard_deadline():
    # Close tracks the exact midline between the two converging boundaries
    # (128 + i/2) all the way to the apex (bar 44) without ever closing
    # beyond either -- the standard expire_lifespan_mult deadline would be
    # bar 84, so reaching EXPIRED at bar 45 proves the apex-tightened
    # pending_deadline_bar_index actually took effect.
    df = _chain(*_ASCENDING_PREFIX, (145.5, 150.0, 10), (150.0, 150.0, 1))
    pivots = _ascending_pivots(df)
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.EXPIRED
    assert matches[0].breakout_bar is None


def test_fractional_apex_still_gives_the_next_bar_a_real_breakout_chance():
    # Apex at bar 34.5 (window_end_i=34) -- passes the apex-ahead-of-
    # window-end gate by a hair. pending_deadline must ceil (not floor)
    # this to 35, or bar 35's own real breakout gets discarded by an
    # instant EXPIRED before its price is ever checked (regression for a
    # bug caught in code review: `int(34.5)` floors to 34, and the walk's
    # very first iteration is i=35, so `i > pending_deadline` fires
    # immediately).
    prefix = [
        (100.0, 150.0, 10), (148.0, 129.5, 5), (131.5, 150.0, 5),
        (148.0, 139.5, 5), (141.5, 150.0, 5), (148.0, 149.5, 5),
    ]
    df = _chain(*prefix, (152.0, 152.0, 3))
    pivots = [
        _pivot(9, 150.0, PivotKind.HIGH, df), _pivot(14, 129.5, PivotKind.LOW, df),
        _pivot(19, 150.0, PivotKind.HIGH, df), _pivot(24, 139.5, PivotKind.LOW, df),
        _pivot(29, 150.0, PivotKind.HIGH, df), _pivot(34, 149.5, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.breakout_bar == 35
    assert m.direction == Direction.BULLISH
    assert m.status != PatternStatus.EXPIRED


def test_pending_when_not_enough_bars_yet_to_resolve():
    df = _chain(*_ASCENDING_PREFIX, (147.0, 147.0, 3))
    pivots = _ascending_pivots(df)
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    assert matches[0].status == PatternStatus.PENDING
    assert matches[0].breakout_bar is None


# ---------------------------------------------------------------------------
# Symmetric triangle: falling upper (160->145, slope=-0.75) + rising lower
# (120->133, slope=0.65) -- gentler slopes than the ascending fixture so
# the apex (~39.89) lands safely past the window's own last pivot (34).
_SYMMETRIC_PREFIX = [
    (100.0, 160.0, 10), (158.0, 120.0, 5), (122.0, 152.5, 5),
    (150.0, 126.5, 5), (124.5, 145.0, 5), (143.0, 133.0, 5),
]


def test_symmetric_triangle_neutral_bias_resolves_bearish_on_downside_break():
    df = _chain(*_SYMMETRIC_PREFIX, (140.0, 125.0, 3), (120.0, 80.0, 10))
    pivots = [
        _pivot(9, 160.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 152.5, PivotKind.HIGH, df),
        _pivot(24, 126.5, PivotKind.LOW, df),
        _pivot(29, 145.0, PivotKind.HIGH, df),
        _pivot(34, 133.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.SYMMETRIC_TRIANGLE
    assert m.trendlines["upper"] == pytest.approx((-0.75, 166.75))
    assert m.trendlines["lower"] == pytest.approx((0.65, 110.9))
    assert m.breakout_bar == 36
    # A symmetric triangle's initial bias is NEUTRAL -- it resolved
    # BEARISH here purely because that's the side that actually broke.
    assert m.direction == Direction.BEARISH
    assert m.target_price == pytest.approx(89.75)
    assert m.stop_price == pytest.approx(141.25)  # upper_at(34) -- the opposite boundary
    assert m.status == PatternStatus.HIT_TARGET


# ---------------------------------------------------------------------------
# Wedges: both boundaries slope the same direction but converge (upper
# slower than lower for a rising wedge, upper faster-falling than lower
# for a falling wedge). Left PENDING -- classification/bias is what's
# under test, not the full lifecycle walk (already covered above).
_RISING_WEDGE_PREFIX = [
    (100.0, 140.0, 10), (138.0, 120.0, 5), (122.0, 146.0, 5),
    (144.0, 132.5, 5), (130.0, 152.0, 5), (150.0, 145.0, 5),
]


def test_rising_wedge_classifies_bearish_bias_and_stays_pending():
    df = _chain(*_RISING_WEDGE_PREFIX, (150.0, 150.0, 1))
    pivots = [
        _pivot(9, 140.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 146.0, PivotKind.HIGH, df),
        _pivot(24, 132.5, PivotKind.LOW, df),
        _pivot(29, 152.0, PivotKind.HIGH, df),
        _pivot(34, 145.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.RISING_WEDGE
    assert m.direction == Direction.BEARISH  # bias -- no breakout resolved it
    assert m.trendlines["upper"] == pytest.approx((0.6, 134.6))
    assert m.trendlines["lower"] == pytest.approx((1.25, 102.5))
    assert m.status == PatternStatus.PENDING


_FALLING_WEDGE_PREFIX = [
    (100.0, 160.0, 10), (158.0, 120.0, 5), (122.0, 147.5, 5),
    (145.5, 114.0, 5), (112.0, 135.0, 5), (133.0, 108.0, 5),
]


def test_falling_wedge_classifies_bullish_bias_and_stays_pending():
    df = _chain(*_FALLING_WEDGE_PREFIX, (115.0, 115.0, 3))
    pivots = [
        _pivot(9, 160.0, PivotKind.HIGH, df),
        _pivot(14, 120.0, PivotKind.LOW, df),
        _pivot(19, 147.5, PivotKind.HIGH, df),
        _pivot(24, 114.0, PivotKind.LOW, df),
        _pivot(29, 135.0, PivotKind.HIGH, df),
        _pivot(34, 108.0, PivotKind.LOW, df),
    ]
    config = _config()

    matches = TriangleWedgeDetector().scan(df, pivots, "TST", Timeframe.DAILY, config)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == PatternType.FALLING_WEDGE
    assert m.direction == Direction.BULLISH  # bias -- no breakout resolved it
    assert m.trendlines["upper"] == pytest.approx((-1.25, 171.25))
    assert m.trendlines["lower"] == pytest.approx((-0.6, 128.4))
    assert m.status == PatternStatus.PENDING
