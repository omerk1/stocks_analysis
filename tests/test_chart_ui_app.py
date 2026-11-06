import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import rs
from src.ui.chart.config import ChartConfig, ChartType


class FakeData:
    def __init__(self):
        idx = pd.bdate_range("2024-01-01", periods=260)
        close = 100 + np.arange(260, dtype=float)
        self._bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                                   "volume": 1.0}, index=idx)
        self.calls = []

    def bars(self, ticker, timeframe):
        self.calls.append((ticker, timeframe))
        return self._bars if ticker == "ABC" else self._bars.iloc[0:0]

    def strip(self, ticker, change_days):
        return rs.RSStrip(None, None, None, None, None)


def _render(data, ticker, ma_keys=("sma_50",)):
    return app_mod.render(data, ChartConfig(), ticker, Timeframe.DAILY, ChartType.CANDLES, list(ma_keys), True)


def test_render_normalises_the_ticker_and_draws():
    data = FakeData()
    fig, parts, message = _render(data, " abc ")
    assert data.calls == [("ABC", Timeframe.DAILY)]
    assert [t.name for t in fig.data] == ["ABC", "SMA 50", "Volume"]
    assert parts[0] == "RS vs market: no RS run"
    assert message.startswith("ABC · daily · 260 bars")


def test_render_ignores_ma_keys_not_offered_for_the_timeframe():
    fig, _, _ = _render(FakeData(), "ABC", ma_keys=("sma_50", "sma_40"))
    assert [t.name for t in fig.data] == ["ABC", "SMA 50", "Volume"]


def test_render_messages_for_empty_and_unknown_tickers():
    assert _render(FakeData(), "")[0] is None
    fig, parts, message = _render(FakeData(), "NOPE")
    assert fig is None and parts == [] and message == "No bars for NOPE."


def test_x_range_from_relayout_forms():
    assert app_mod.x_range_from_relayout(None) is None
    assert app_mod.x_range_from_relayout({"xaxis.autorange": True}) is None
    assert app_mod.x_range_from_relayout({"xaxis.range[0]": "a", "xaxis.range[1]": "b"}) == ("a", "b")
    assert app_mod.x_range_from_relayout({"xaxis2.range": ["a", "b"]}) == ("a", "b")


def test_app_builds_with_injected_data():
    dash_app = app_mod.create_app(FakeData(), ChartConfig())
    ids = {c.id for c in dash_app.layout._traverse() if getattr(c, "id", None)}
    assert {"ticker", "timeframe", "chart-type", "volume", "mas", "chart", "rs-strip"} <= ids
