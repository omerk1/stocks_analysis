import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import panes
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.earnings import EarningsCard
from src.ui.chart.figure import build_figure, earnings_annotations, pane_axes, y_axis_ranges

CFG = panes.PaneConfig()


@pytest.fixture
def bars():
    idx = pd.bdate_range("2022-01-03", periods=400)
    close = 100 + 10 * np.sin(np.arange(400) / 15) + np.arange(400) * 0.1
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
                        index=idx)


def _pane(key, bars, market=None, timeframe=Timeframe.DAILY):
    return panes.Pane(key, panes.pane_label(key, CFG), panes.pane_frame(key, bars, timeframe, CFG, market))


def test_pane_frames(bars):
    rsi = panes.pane_frame(panes.RSI, bars, Timeframe.DAILY, CFG)
    assert rsi["rsi"].iloc[:CFG.rsi_period].isna().all() and rsi["rsi"].dropna().between(0, 100).all()
    macd = panes.pane_frame(panes.MACD, bars, Timeframe.DAILY, CFG)
    assert list(macd.columns) == ["macd", "signal", "hist"]
    assert np.allclose((macd["macd"] - macd["signal"]).dropna(), macd["hist"].dropna())
    with pytest.raises(ValueError):
        panes.pane_frame("nope", bars, Timeframe.DAILY, CFG)


def test_rs_is_mansfield_of_the_ratio_to_the_market(bars):
    market = bars.assign(close=bars["close"] * 0 + 50.0).iloc[5:]  # flat market, missing the first days
    rs = panes.pane_frame(panes.RS, bars, Timeframe.DAILY, CFG, market)["mansfield"]
    assert panes.mansfield_period(Timeframe.DAILY, CFG) == 252 and panes.mansfield_period(Timeframe.WEEKLY, CFG) == 52
    ratio = bars["close"].iloc[5:] / 50.0
    expected = (ratio / ratio.rolling(252).mean() - 1) * 100
    assert rs.iloc[:5].isna().all()  # days the market lacks: NaN, not filled
    assert rs.iloc[-1] == pytest.approx(expected.iloc[-1])
    assert panes.pane_frame(panes.RS, bars, Timeframe.DAILY, CFG, None)["mansfield"].isna().all()


def test_pane_range_keeps_zero_and_fits_the_window(bars):
    frame = pd.DataFrame({"x": np.linspace(5, 10, len(bars))}, index=bars.index)
    low, high = panes.pane_range(panes.MACD, frame, bars.index[-10], bars.index[-1])
    assert low < 0 < 9.8 < high
    assert panes.pane_range(panes.RSI, frame, bars.index[0], bars.index[1]) == [0.0, 100.0]
    assert panes.pane_range(panes.MACD, frame, "2030-01-01", "2030-02-01") is None


def test_panes_go_below_volume_in_menu_order(bars):
    chosen = (_pane(panes.RSI, bars), _pane(panes.MACD, bars))
    assert pane_axes(True, chosen) == {"volume": "yaxis2", "rsi": "yaxis3", "macd": "yaxis4"}
    assert pane_axes(False, chosen) == {"rsi": "yaxis2", "macd": "yaxis3"}
    fig = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), show_volume=True,
                       x_range=(bars.index[-60], bars.index[-1]), panes=chosen)
    uids = [t.uid for t in fig.data]
    assert uids == ["price", "volume", "rsi", "macd-hist", "macd", "macd-signal"]
    assert [t.yaxis for t in fig.data][-4:] == ["y3", "y4", "y4", "y4"]
    assert [a.text for a in fig.layout.annotations] == ["RSI 14", "MACD 12/26/9"]
    assert list(fig.layout.yaxis3.range) == [0.0, 100.0]
    domains = [fig.layout[f"yaxis{i}"].domain for i in (1, 2, 3, 4)]
    assert domains[0][1] - domains[0][0] >= 0.45  # the price pane stays the biggest


def test_refit_covers_the_panes(bars):
    chosen = (_pane(panes.MACD, bars),)
    ranges = y_axis_ranges(bars, {}, (bars.index[-60], bars.index[-1]), ChartType.CANDLES, False, (), chosen)
    assert set(ranges) == {"yaxis", "yaxis2"}
    window = chosen[0].frame.iloc[-60:]
    assert ranges["yaxis2"][0] < window.min().min() and ranges["yaxis2"][1] > window.max().max()


def test_relayout_from_any_pane():
    assert app_mod.x_range_from_relayout({"xaxis4.range[0]": "a", "xaxis4.range[1]": "b"}) == ("a", "b")
    assert app_mod.is_autorange({"xaxis5.autorange": True})
    assert app_mod.x_range_from_relayout({"yaxis.range[0]": 1, "yaxis.range[1]": 2}) is None


def test_selected_panes_in_menu_order_and_cached(bars):
    class Data(app_mod.ChartData):
        def __init__(self):
            super().__init__(None, None)

        def _bars(self, ticker, timeframe):
            return bars

    data = Data()
    picked = app_mod.selected_panes(data, ChartConfig(), "ABC", Timeframe.DAILY, ["rs", "rsi", "bogus"])
    assert [p.key for p in picked] == ["rsi", "rs"]
    app_mod.selected_panes(data, ChartConfig(), "ABC", Timeframe.DAILY, ["rsi"])
    assert data.pane.cache_info().hits == 1
    fig, _ = app_mod.render(data, ChartConfig(), "ABC", Timeframe.DAILY, ChartType.LINE, [], True, None, (), [],
                            None, ["macd"])
    assert "macd" in [t.uid for t in fig.data]


def test_an_open_card_near_the_top_hangs_below_the_bar(bars):
    card = EarningsCard(period_end=pd.Timestamp("2023-03-31"), label="Q1", report_form="10-Q",
                        accepted_at="2023-05-01T20:30:00+00:00", timing="after_close",
                        reaction_date=bars.index[-5], revenue=None, revenue_year_ago=None, eps=None,
                        eps_year_ago=None, gap_pct=1.0, gap_atr=0.5, move_pct=2.0, move_atr=1.0)
    high = float(bars["high"].iloc[-5])
    (top,) = earnings_annotations(bars, [card], {card.key}, [0.0, high + 1])
    assert top["ay"] > 0 and top["y"] == bars["low"].iloc[-5]
    (low_in_range,) = earnings_annotations(bars, [card], {card.key}, [high - 1, high * 3])
    assert low_in_range["ay"] < 0
    (flag,) = earnings_annotations(bars, [card], set(), [0.0, high + 1])
    assert flag["ay"] < 0  # a flag is small: stays above the high
