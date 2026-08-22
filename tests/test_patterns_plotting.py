import numpy as np
import pandas as pd

from src.market_common.models import Pivot, PivotKind, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.detectors.cup_and_handle import CupAndHandleDetector
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
