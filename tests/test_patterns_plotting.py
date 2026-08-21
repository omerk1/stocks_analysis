import numpy as np
import pandas as pd

from src.market_common.models import Timeframe
from src.patterns.config import PatternConfig
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
