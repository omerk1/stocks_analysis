import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Timeframe
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.figure import build_figure, y_fit

SPECS = ChartConfig().ma_options[Timeframe.DAILY]


@pytest.fixture
def bars():
    idx = pd.bdate_range("2023-01-02", periods=300)
    close = 100 + np.arange(300, dtype=float)
    return pd.DataFrame({"open": close - 0.5, "high": close + 2, "low": close - 2, "close": close,
                         "volume": np.where(np.arange(300) % 2 == 0, 1000.0, 2000.0)}, index=idx)


@pytest.mark.parametrize("chart_type, trace", [(ChartType.LINE, "scatter"), (ChartType.BARS, "ohlc"),
                                               (ChartType.CANDLES, "candlestick")])
def test_price_trace_follows_chart_type(bars, chart_type, trace):
    fig = build_figure(bars, "ABC", Timeframe.DAILY, chart_type, {}, SPECS)
    assert fig.data[0].type == trace


def test_only_selected_moving_averages_are_drawn(bars):
    mas = {"sma_50": bars["close"].rolling(50).mean()}
    fig = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, mas, SPECS)
    assert [t.name for t in fig.data] == ["ABC", "SMA 50", "Volume"]


def test_volume_pane_is_optional(bars):
    on = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.LINE, {}, SPECS, show_volume=True)
    off = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.LINE, {}, SPECS, show_volume=False)
    assert any(t.type == "bar" for t in on.data)
    assert not any(t.type == "bar" for t in off.data)
    assert "yaxis2" not in off.layout.to_plotly_json()


def test_weekends_skipped_on_daily_only(bars):
    daily = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.LINE, {}, SPECS)
    weekly = build_figure(bars, "ABC", Timeframe.WEEKLY, ChartType.LINE, {}, SPECS)
    assert daily.layout.xaxis.rangebreaks
    assert not weekly.layout.xaxis.rangebreaks


def test_span_sets_initial_range_and_fits_y_to_it(bars):
    fig = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, SPECS, span_days=30)
    start = pd.Timestamp(fig.layout.xaxis.range[0])
    assert start == bars.index.max() - pd.Timedelta(days=30)
    visible = bars.loc[bars.index >= start]
    low, high = fig.layout.yaxis.range
    assert low < visible["low"].min() and high > visible["high"].max()
    assert low > bars["low"].min()  # fitted to the window, not the whole history


def test_y_fit_includes_moving_averages_and_skips_their_warmup(bars):
    ma = pd.Series(np.nan, index=bars.index)
    ma.iloc[-10:] = 10_000.0  # far above the bars, only at the end
    start, end = bars.index[-20], bars.index[-1]
    (low, high), volume_top = y_fit(bars, {"x": ma}, start, end)
    assert high > 10_000.0
    assert volume_top == pytest.approx(2200.0)
    (_, high_early), _ = y_fit(bars, {"x": ma}, bars.index[0], bars.index[50])
    assert high_early < 1_000


def test_y_fit_never_goes_below_zero(bars):
    cheap = bars.copy()
    cheap.loc[cheap.index[-1], ["low", "open", "close"]] = 0.01  # padding would push the axis negative
    (low, _), _ = y_fit(cheap, {}, bars.index[0], bars.index[-1])
    assert low == 0.0


def test_y_fit_none_outside_the_data(bars):
    assert y_fit(bars, {}, "2030-01-01", "2030-02-01") is None
