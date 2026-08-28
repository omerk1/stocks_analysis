import numpy as np
import pandas as pd

from src.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.detectors.cup_and_handle import CupAndHandleDetector
from src.patterns.models import PatternStatus
from src.patterns.plotting import render_pattern_chart
from src.patterns.scanner import scan_bars


def _chain(*segments, start="2020-01-01") -> pd.DataFrame:
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


def test_render_pattern_chart_builds_without_error_and_includes_candles_plus_pivots():
    bars = _chain((100.0, 130.0, 10), (128.0, 121.0, 5), (123.0, 129.0, 5), (127.0, 100.0, 10))
    config = PatternConfig(
        atr_period=3, pivot_atr_mult=1.0, volume_sma_period=5, prior_trend_min_bars=5, prior_trend_min_pct=10.0,
        double_top_typical_min_bars=1, double_top_typical_max_bars=200,
    )
    matches = scan_bars(bars, "TST", Timeframe.DAILY, config)
    assert matches  # sanity: fixture is known to produce at least one match

    fig = render_pattern_chart(bars, matches, ticker="TST", timeframe=Timeframe.DAILY)

    trace_types = [trace.type for trace in fig.data]
    assert "candlestick" in trace_types
    assert trace_types.count("scatter") >= len(matches)  # >= : pivot polyline + optional neckline/target lines


def test_render_pattern_chart_includes_a_volume_bar_trace_colored_by_up_down_day():
    # _chain sets open == close for every bar (both drawn from the same
    # linspace array), so it can't exercise the up/down color split --
    # build a frame with real distinct open/close values instead.
    idx = pd.bdate_range("2020-01-01", periods=4)
    bars = pd.DataFrame(
        {
            "open": [100.0, 105.0, 103.0, 108.0], "close": [105.0, 103.0, 108.0, 106.0],
            "high": [106.0, 106.0, 109.0, 109.0], "low": [99.0, 102.0, 102.0, 105.0],
            "volume": [1000.0, 2000.0, 1500.0, 1800.0],
        },
        index=idx,
    )

    fig = render_pattern_chart(bars, matches=[], ticker="TST", timeframe=Timeframe.DAILY)

    volume_traces = [trace for trace in fig.data if trace.type == "bar"]
    assert len(volume_traces) == 1
    volume_trace = volume_traces[0]
    assert list(volume_trace.y) == list(bars["volume"])
    assert volume_trace.xaxis == "x2"  # row 2 (below price), not overlaid on the candlesticks
    # bar0 (100->105) and bar2 (103->108) are up days; bar1 (105->103) and
    # bar3 (108->106) are down days -- confirms the split actually keys
    # off close vs. open per bar, not some flat/constant color.
    up = "rgba(44,160,44,0.5)"
    down = "rgba(214,39,40,0.5)"
    assert list(volume_trace.marker.color) == [up, down, up, down]


def test_cup_and_handle_neckline_starts_at_right_rim_not_the_second_pivot():
    # Regression: the key_levels["neckline"] fallback branch used to start
    # the drawn line at match.pivots[1] -- correct for double top/bottom's
    # fixed 3-pivot list (where index 1 is the trough), but wrong for cup
    # & handle's variable-length pivot list, where index 1 is whatever
    # pivot happens to follow the left rim (here, the cup's own bottom at
    # bar 44), not the right rim (bar 64) that actually set the trigger
    # level. The trigger-level pivot is always second-to-last, not index 1.
    uptrend = np.linspace(80.0, 140.0, 25)
    t = np.arange(41, dtype=float)
    cup = (0.1 * (t - 20) ** 2 + 100.0)[1:]
    handle = np.linspace(138.0, 130.0, 4)
    tail = np.linspace(132.0, 200.0, 20)
    closes = np.concatenate([uptrend, cup, handle, tail])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    bars = pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )

    def _pivot(i: int, price: float, kind: PivotKind) -> Pivot:
        ts = bars.index[i].isoformat()
        return Pivot(kind=kind, timestamp=ts, value=price, confirmed_at=ts, threshold_at_pivot=1.0, bar_index=i)

    pivots = [
        _pivot(24, 140.0, PivotKind.HIGH), _pivot(44, 100.0, PivotKind.LOW),
        _pivot(64, 140.0, PivotKind.HIGH), _pivot(68, 130.0, PivotKind.LOW),
    ]
    config = PatternConfig(atr_period=3, volume_sma_period=5, prior_trend_min_bars=5)
    matches = CupAndHandleDetector().scan(bars, pivots, "TST", Timeframe.DAILY, config)
    assert len(matches) == 1

    fig = render_pattern_chart(bars, matches, ticker="TST", timeframe=Timeframe.DAILY)
    neckline_traces = [
        tr for tr in fig.data if tr.type == "scatter" and tr.mode == "lines" and tr.line.dash == "dot"
    ]
    assert len(neckline_traces) == 1
    assert neckline_traces[0].x[0] == bars.index[64]  # right rim, not pivots[1] (bar 44)


def test_rounding_bottom_neckline_starts_at_right_rim_not_the_second_to_last_pivot():
    # Regression: a Rounding match's window ends *at* the right rim (no
    # trailing handle pivot), landing rim2 at index -1 rather than -2 --
    # the fixed "-2 is the invariant" fix (the test above) breaks for
    # exactly this case. rim1 and rim2 also share the exact same price
    # here (both 140.0), so the fix's own price-based lookup must prefer
    # the *later* match (rim2), not silently pick rim1 instead.
    uptrend = np.linspace(80.0, 140.0, 25)
    t = np.arange(41, dtype=float)
    cup = (0.1 * (t - 20) ** 2 + 100.0)[1:]
    tail = np.linspace(132.0, 200.0, 20)
    closes = np.concatenate([uptrend, cup, tail])
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    bars = pd.DataFrame(
        {"open": closes, "high": closes + 0.3, "low": closes - 0.3, "close": closes, "volume": 1000.0}, index=idx,
    )

    def _pivot(i: int, price: float, kind: PivotKind) -> Pivot:
        ts = bars.index[i].isoformat()
        return Pivot(kind=kind, timestamp=ts, value=price, confirmed_at=ts, threshold_at_pivot=1.0, bar_index=i)

    # No handle pivot at all -- rim2 (bar 64) is the window's last pivot.
    pivots = [_pivot(24, 140.0, PivotKind.HIGH), _pivot(44, 100.0, PivotKind.LOW), _pivot(64, 140.0, PivotKind.HIGH)]
    config = PatternConfig(atr_period=3, volume_sma_period=5, prior_trend_min_bars=5,
                            rounding_typical_min_bars=1, rounding_typical_max_bars=200)
    matches = CupAndHandleDetector().scan(bars, pivots, "TST", Timeframe.DAILY, config)
    assert len(matches) == 1
    assert matches[0].pattern_type.value == "rounding_bottom"

    fig = render_pattern_chart(bars, matches, ticker="TST", timeframe=Timeframe.DAILY)
    neckline_traces = [
        tr for tr in fig.data if tr.type == "scatter" and tr.mode == "lines" and tr.line.dash == "dot"
    ]
    assert len(neckline_traces) == 1
    assert neckline_traces[0].x[0] == bars.index[64]  # right rim, not pivots[-2] (bar 44)


def test_every_pattern_status_has_a_plotting_opacity():
    # _STATUS_OPACITY is an exhaustive lookup -- a status missing from it
    # raises KeyError mid-render, so any chart containing that status
    # crashes. Caught in practice when EXPIRED_UNRESOLVED was added to the
    # model without updating plotting; this makes the next one a red test
    # instead of a broken chart.
    from src.patterns.plotting import _STATUS_OPACITY

    assert set(_STATUS_OPACITY) == set(PatternStatus)


def test_every_direction_has_a_plotting_colour():
    from src.patterns.plotting import _DIRECTION_RGB

    assert set(_DIRECTION_RGB) == set(Direction)
