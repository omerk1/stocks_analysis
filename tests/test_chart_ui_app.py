import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import rs
from src.ui.chart.config import ChartConfig, ChartType


class FakeData(app_mod.ChartData):
    """The real class's caching, with bars and the strip stubbed out."""

    def __init__(self, strip=rs.RSStrip(None, None, None, None, None)):
        super().__init__(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
        idx = pd.bdate_range("2024-01-01", periods=260)
        close = 100 + np.arange(260, dtype=float)
        self._frame = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                                    "volume": 1.0}, index=idx)
        self._strip = strip
        self.calls = []

    def _bars(self, ticker, timeframe):
        self.calls.append((ticker, timeframe))
        return self._frame if ticker in ("ABC", "SPY") else self._frame.iloc[0:0]

    def strip(self, ticker, change_days):
        return self._strip


def _render(data, ticker, ma_keys=("sma_50",), view=None):
    return app_mod.render(data, ChartConfig(), ticker, Timeframe.DAILY, ChartType.CANDLES, list(ma_keys), True,
                          view)


def test_render_normalises_the_ticker_and_draws():
    data = FakeData()
    fig, message = _render(data, " abc ")
    assert data.calls == [("ABC", Timeframe.DAILY), ("SPY", Timeframe.DAILY)]  # SPY: the holiday calendar
    assert [t.name for t in fig.data] == ["ABC", "SMA 50", "Volume"]
    assert message.startswith("ABC · daily · 260 bars")


def test_bars_and_moving_averages_are_cached():
    data = FakeData()
    _render(data, "ABC")
    _render(data, "ABC")
    assert data.calls == [("ABC", Timeframe.DAILY), ("SPY", Timeframe.DAILY)]
    assert data.moving_averages.cache_info().hits == 1
    assert data.holidays.cache_info().hits == 1


def test_render_ignores_ma_keys_not_offered_for_the_timeframe():
    fig, _ = _render(FakeData(), "ABC", ma_keys=("sma_50", "sma_40"))
    assert [t.name for t in fig.data] == ["ABC", "SMA 50", "Volume"]


def test_render_keeps_the_stored_view_only_for_the_same_chart():
    view = {"key": "ABC-daily", "range": ["2024-03-01", "2024-04-01"]}
    fig, _ = _render(FakeData(), "ABC", view=view)
    assert list(fig.layout.xaxis.range) == ["2024-03-01", "2024-04-01"]
    low, high = fig.layout.yaxis.range
    assert high < 200  # fitted to March 2024, not to the default span's later bars
    other, _ = _render(FakeData(), "ABC", view={"key": "XYZ-daily", "range": ["2024-03-01", "2024-04-01"]})
    assert list(other.layout.xaxis.range) != ["2024-03-01", "2024-04-01"]


def test_render_messages_for_empty_and_unknown_tickers():
    assert _render(FakeData(), "")[0] is None
    fig, message = _render(FakeData(), "NOPE")
    assert fig is None and message == "No bars for NOPE."


def test_strip_children_without_rs():
    assert app_mod.strip_children(FakeData(), ChartConfig(), "abc")[0] == "RS vs market: no RS run"
    assert app_mod.strip_children(FakeData(strip="RS: no derived database"), ChartConfig(), "abc") == [
        "RS: no derived database"]
    assert app_mod.strip_children(FakeData(), ChartConfig(), " ") == []


def test_strip_tells_missing_database_unrun_rs_and_read_errors_apart(tmp_path):
    raw, derived = tmp_path / "raw.sqlite", tmp_path / "derived.sqlite"
    sqlite3.connect(raw).close()
    assert app_mod.ChartData(raw, derived).strip("ABC", 28) == "RS: no derived database"
    sqlite3.connect(derived).close()  # exists, but RS was never run there: no tables
    strip = app_mod.ChartData(raw, derived).strip("ABC", 28)
    assert rs.strip_parts(strip, 28) == ["RS vs market: no RS run", "RS vs sector: no RS run"]
    derived.write_bytes(b"not a database" * 100)
    assert app_mod.ChartData(raw, derived).strip("ABC", 28).startswith("RS: read error")


def test_holidays_come_from_the_market_calendar_not_the_ticker():
    data = FakeData()
    data._frame = data._frame.drop(pd.Timestamp("2024-07-04"))
    assert "2024-07-04" in data.holidays()
    assert data.calls == [("SPY", Timeframe.DAILY)]


def test_relayout_forms():
    assert app_mod.x_range_from_relayout(None) is None
    assert app_mod.x_range_from_relayout({"xaxis.autorange": True}) is None
    assert app_mod.x_range_from_relayout({"xaxis.range[0]": "a", "xaxis.range[1]": "b"}) == ("a", "b")
    assert app_mod.x_range_from_relayout({"xaxis2.range": ["a", "b"]}) == ("a", "b")
    assert app_mod.is_autorange({"xaxis.autorange": True})
    assert not app_mod.is_autorange({"xaxis.range[0]": "a", "xaxis.range[1]": "b"})


def test_app_builds_with_injected_data():
    dash_app = app_mod.create_app(FakeData(), ChartConfig())
    ids = {c.id for c in dash_app.layout._traverse() if getattr(c, "id", None)}
    assert {"ticker", "timeframe", "chart-type", "volume", "mas", "chart", "rs-strip", "view"} <= ids
