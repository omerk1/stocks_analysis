import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import panes
from src.ui.chart.config import ChartConfig, ChartType, PaneConfig
from src.ui.chart.earnings import EarningsCard
from src.ui.chart.figure import build_figure, earnings_annotations, figure_annotations, pane_axes, y_axis_ranges
from src.ui.chart.overlays import Guide, Overlay

CFG = PaneConfig()


@pytest.fixture
def bars():
    idx = pd.bdate_range("2022-01-03", periods=400)
    close = 100 + 10 * np.sin(np.arange(400) / 15) + np.arange(400) * 0.1
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
                        index=idx)


def _pane(key, bars):
    return panes.Pane(key, panes.pane_label(key, CFG), panes.pane_frame(key, bars, CFG))


def test_pane_frames(bars):
    rsi = panes.pane_frame(panes.RSI, bars, CFG)
    assert rsi["rsi"].iloc[:CFG.rsi_period].isna().all() and rsi["rsi"].dropna().between(0, 100).all()
    macd = panes.pane_frame(panes.MACD, bars, CFG)
    assert list(macd.columns) == ["macd", "signal", "hist"]
    assert np.allclose((macd["macd"] - macd["signal"]).dropna(), macd["hist"].dropna())
    with pytest.raises(ValueError):
        panes.pane_frame("nope", bars, CFG)


@pytest.fixture
def weekly():
    """Weekly closes labelled by Monday, like the loader's: the ticker rises 1% a week, the market is flat."""
    idx = pd.date_range("2020-01-06", periods=120, freq="W-MON")
    return pd.Series(100 * 1.01 ** np.arange(120), index=idx), pd.Series(50.0, index=idx)


def test_rs_is_the_modules_weekly_mansfield(weekly):
    ticker, market = weekly
    ratio = ticker / 50.0
    expected = (ratio / ratio.rolling(52).mean() - 1) * 100
    on_weekly = panes.rs_frame(ticker.index, Timeframe.WEEKLY, ticker, market, CFG)["mansfield"]
    assert on_weekly.iloc[:51].isna().all() and on_weekly.iloc[-1] == pytest.approx(expected.iloc[-1])


def test_rs_on_a_daily_chart_carries_the_last_completed_week(weekly):
    ticker, market = weekly
    days = pd.bdate_range(ticker.index[60], ticker.index[62] + pd.Timedelta(days=4))  # three weeks, Mon-Fri
    daily = panes.rs_frame(days, Timeframe.DAILY, ticker, market, CFG)["mansfield"]
    weekly_values = panes.rs_frame(ticker.index, Timeframe.WEEKLY, ticker, market, CFG)["mansfield"]
    # a week's value (its Friday close) first shows the Monday after: never on its own days
    assert (daily.loc[days[:5]] == weekly_values.iloc[59]).all()
    assert (daily.loc[days[5:10]] == weekly_values.iloc[60]).all()
    empty = panes.rs_frame(days, Timeframe.DAILY, ticker, market.iloc[0:0], CFG)
    assert empty["mansfield"].isna().all()


def test_pane_range_keeps_zero_and_fits_the_window(bars):
    frame = pd.DataFrame({"x": np.linspace(5, 10, len(bars))}, index=bars.index)
    low, high = panes.pane_range(panes.MACD, frame, bars.index[-10], bars.index[-1])
    assert low < 0 < 9.8 < high
    assert panes.pane_range(panes.RSI, frame, bars.index[0], bars.index[1]) == [0.0, 100.0]
    # nothing in the window (a warmup): a neutral range, so a stale one from the last view never stays
    assert panes.pane_range(panes.MACD, frame, "2030-01-01", "2030-02-01") == [-1.0, 1.0]


def test_panes_go_below_volume_in_menu_order(bars):
    chosen = (_pane(panes.RSI, bars), _pane(panes.MACD, bars))
    assert pane_axes(True, chosen) == {"volume": "yaxis2", "rsi": "yaxis3", "macd": "yaxis4"}
    assert pane_axes(False, chosen) == {"rsi": "yaxis2", "macd": "yaxis3"}
    fig = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), show_volume=True,
                       x_range=(bars.index[-60], bars.index[-1]), panes=chosen)
    uids = [t.uid for t in fig.data]
    assert uids == ["price", "volume", "rsi", "macd-hist", "macd", "macd-signal"]
    assert [t.yaxis for t in fig.data][-4:] == ["y3", "y4", "y4", "y4"]
    assert [(a.text, a.xref, a.yref) for a in fig.layout.annotations] == [
        ("RSI 14", "x3 domain", "y3 domain"), ("MACD 12/26/9", "x4 domain", "y4 domain")]
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


class _Data(app_mod.ChartData):
    def __init__(self, bars, market_weekly):
        super().__init__(None, None)
        self._frame, self._market = bars, market_weekly

    def _bars(self, ticker, timeframe):
        return self._frame

    def _rs_closes(self, ticker):
        return self._market if ticker == "SPY" else self._frame["close"].resample("W-MON", label="left").last()


def test_selected_panes_in_menu_order_and_cached(bars):
    data = _Data(bars, pd.Series(50.0, index=pd.date_range("2021-01-04", periods=200, freq="W-MON")))
    picked = app_mod.selected_panes(data, ChartConfig(), "ABC", Timeframe.DAILY, ["rs", "rsi", "bogus"])
    assert [p.key for p in picked] == ["rsi", "rs"]
    app_mod.selected_panes(data, ChartConfig(), "ABC", Timeframe.DAILY, ["rsi"])
    assert data.pane.cache_info().hits == 1
    fig, _ = app_mod.render(data, ChartConfig(), "ABC", Timeframe.DAILY, ChartType.LINE, [], True, None, (), [],
                            None, ["macd"])
    assert "macd" in [t.uid for t in fig.data]


def test_rs_pane_without_market_bars_says_so(bars):
    data = _Data(bars, pd.Series(dtype=float))
    _, message = app_mod.render(data, ChartConfig(), "ABC", Timeframe.DAILY, ChartType.LINE, [], True, None, (),
                                [], None, ["rs"])
    assert message.endswith("RS pane: no SPY bars")


def test_figure_annotations_label_each_pane_and_place_cards_by_the_given_range(bars):
    chosen = (_pane(panes.RSI, bars),)
    out = figure_annotations(bars, False, chosen)
    assert [(a["text"], a["yref"]) for a in out] == [("RSI 14", "y2 domain")]


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
    fell = EarningsCard(**{**card.__dict__, "move_pct": -2.0})
    (near_bottom,) = earnings_annotations(bars, [fell], {fell.key}, [high - 1, high * 3])
    assert near_bottom["ay"] < 0 and near_bottom["y"] == high  # room above: not down into the panes
    (fell_flag,) = earnings_annotations(bars, [fell], set(), [high - 1, high * 3])
    assert fell_flag["ay"] > 0  # a flag still follows the reaction


def _divergence(bars, pane="rsi", hidden=False):
    p1, p2 = bars.index[-40], bars.index[-20]
    return Overlay(family="divergences", item_id=f"d-{pane}", label="RSI bullish", kind="segment", x0=p1,
                   lo=90.0, hi=95.0, strength=0.5, alive=True, tag="RSI↑", points=((p1, 95.0), (p2, 90.0)),
                   pane=pane, pane_points=((p1, 30.0), (p2, 35.0)), age_bars=15, same_key="k", bullish=True,
                   dashed=hidden)


def test_a_divergence_is_drawn_on_price_and_on_its_pane_when_shown(bars):
    div = _divergence(bars, hidden=True)
    with_pane = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), show_volume=False,
                             overlays=(div,), panes=(_pane(panes.RSI, bars),))
    price, pane = (t for t in with_pane.data if t.uid.startswith("divergences:"))
    assert (price.uid, list(price.y), price.yaxis) == ("divergences:d-rsi", [95.0, 90.0], "y")
    assert (pane.uid, list(pane.y), pane.yaxis) == ("divergences:d-rsi:pane", [30.0, 35.0], "y2")
    assert price.line.dash == "dash" and price.line.color == "#16a34a"
    without = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), show_volume=False,
                           overlays=(div,))
    assert [t.uid for t in without.data if t.uid.startswith("divergences:")] == ["divergences:d-rsi"]


def test_a_pattern_draws_its_outline_and_guides_to_the_right_edge(bars):
    pivots = tuple((bars.index[i], 90.0 + i % 2 * 5) for i in (-60, -50, -40))
    pattern = Overlay(family="patterns", item_id="p", label="Double bottom ↑", kind="segment", x0=pivots[0][0],
                      lo=90.0, hi=95.0, strength=0.6, alive=True, tag="2Bot↑", points=pivots, bullish=True,
                      guides=(Guide(bars.index[-50], 95.0, bars.index[-30], 95.0),
                              Guide(bars.index[-30], 300.0, None, 300.0, "dash", "2Bot↑ target")))
    fig = build_figure(bars, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), show_volume=False,
                       overlays=(pattern,))
    outline, trigger, target = (t for t in fig.data if t.uid.startswith("patterns:"))
    assert len(outline.x) == 3 and list(outline.text) == ["", "", "2Bot↑"]
    assert trigger.line.dash == "dot" and target.x[1] > bars.index[-1]  # runs to the right edge
    assert target.text[1] == "2Bot↑ target"
    low = Overlay(**{**pattern.__dict__, "lo": 1.0})
    during = y_axis_ranges(bars, {}, (bars.index[-35], bars.index[-1]), ChartType.CANDLES, False, (low,))
    after = y_axis_ranges(bars, {}, (bars.index[-10], bars.index[-1]), ChartType.CANDLES, False, (low,))
    assert during["yaxis"][0] < 1.0 < after["yaxis"][0]  # outline and trigger gone: only the target is left


def test_a_divergence_counts_in_the_y_fit_only_while_in_the_window(bars):
    div = _divergence(bars)
    low_div = Overlay(**{**div.__dict__, "lo": 1.0, "hi": 2.0})
    in_view = y_axis_ranges(bars, {}, (bars.index[-30], bars.index[-1]), ChartType.CANDLES, False, (low_div,))
    after = y_axis_ranges(bars, {}, (bars.index[-10], bars.index[-1]), ChartType.CANDLES, False, (low_div,))
    assert in_view["yaxis"][0] < 2.0 < after["yaxis"][0]
