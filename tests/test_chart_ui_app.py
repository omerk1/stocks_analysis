import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import rs
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.overlays import Overlay


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

    def _overlays(self, ticker, timeframe):
        self.calls.append(("overlays", ticker))
        return app_mod.OverlaySet(tuple(self.items), {"fibonacci": "ValueError: boom"}, 0.1)

    # last close 359, ATR 2 (high - low): reach 3 ATR = 353..365
    items = (
        Overlay("sr_lines", "near", "Support 358", "zone", pd.Timestamp("2024-06-03"), 357.5, 358.5, 1.0, True),
        Overlay("sr_lines", "dead", "Support 359", "zone", pd.Timestamp("2024-06-03"), 358.5, 359.5, 9.0, False),
        Overlay("sr_lines", "far", "Support 300", "zone", pd.Timestamp("2024-06-03"), 299.5, 300.5, 5.0, True),
        Overlay("gaps", "gap", "FVG up 356–357", "zone", pd.Timestamp("2024-09-02"), 356.0, 357.0, 1.0, True),
    )


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


def test_hidden_days_are_market_closures_the_ticker_also_lacks():
    data = FakeData()
    full = data._frame
    spy = full.drop(pd.Timestamp("2024-07-04")).drop(pd.Timestamp("2024-03-12"))  # holiday + a SPY data hole
    abc = full.drop(pd.Timestamp("2024-07-04")).drop(pd.Timestamp("2024-05-15"))  # holiday + ABC's own gap
    data.bars = lru_cache(maxsize=32)(lambda ticker, timeframe: {"SPY": spy, "ABC": abc}[ticker])
    hidden = data.holidays("ABC")
    assert hidden == ("2024-07-04",)  # not ABC's real 2024-03-12 bar, not ABC's own 2024-05-15 gap


def test_relayout_forms():
    assert app_mod.x_range_from_relayout(None) is None
    assert app_mod.x_range_from_relayout({"xaxis.autorange": True}) is None
    assert app_mod.x_range_from_relayout({"xaxis.range[0]": "a", "xaxis.range[1]": "b"}) == ("a", "b")
    assert app_mod.x_range_from_relayout({"xaxis2.range": ["a", "b"]}) == ("a", "b")
    assert app_mod.is_autorange({"xaxis.autorange": True})
    assert not app_mod.is_autorange({"xaxis.range[0]": "a", "xaxis.range[1]": "b"})


def test_app_builds_with_injected_data():
    dash_app = app_mod.create_app(FakeData(), ChartConfig())
    ids = {c.id for c in dash_app.layout._traverse() if isinstance(getattr(c, "id", None), str)}
    assert {"ticker", "timeframe", "chart-type", "volume", "mas", "chart", "rs-strip", "view",
            "weight", "reset", "menu", "menu-key", "overlay-count", "earnings", "earnings-open", "panes"} <= ids


def _by_type(children):
    """{(type, family): component} for the menu's pattern-matched components."""
    out = {}
    for block in children:
        for c in [block, *block._traverse()]:
            if isinstance(getattr(c, "id", None), dict):
                out[(c.id["type"], c.id["family"])] = c
    return out


def test_menu_lists_alive_items_and_ticks_the_defaults():
    data = FakeData()
    children, key = app_mod.menu(data, ChartConfig(), " abc ", Timeframe.DAILY)
    assert key == "ABC-daily"
    parts = _by_type(children[1:])
    sr = parts[("items", "sr_lines")]
    assert [o["value"] for o in sr.options] == ["near", "far"]  # the dead line isn't listed
    assert sr.value == ["near"]  # far is out of reach: listed, not ticked
    assert parts[("family", "sr_lines")].value == ["sr_lines"]
    assert parts[("family-count", "sr_lines")].children == "1 of 2 shown"
    assert parts[("family-defaults", "sr_lines")].data == ["near"]
    assert parts[("items", "gaps")].value == ["gap"]
    # a family with nothing alive is unticked, and its failure is shown
    assert parts[("family", "fibonacci")].value == []
    assert "failed: ValueError: boom" in str(children)


def test_ticking_a_family_with_nothing_in_reach_picks_its_nearest():
    data = FakeData()
    data.items = data.items[2:3]  # only "far"
    parts = _by_type(app_mod.menu(data, ChartConfig(), "ABC", Timeframe.DAILY)[0][1:])
    assert parts[("items", "sr_lines")].value == []
    assert parts[("family-defaults", "sr_lines")].data == ["far"]


def test_selected_overlays_only_for_the_menus_own_chart():
    data = FakeData()
    chosen = app_mod.chosen_items([{"type": "items", "family": "sr_lines"}, {"type": "items", "family": "gaps"}],
                                  [["near", "far"], None])
    assert chosen == {"sr_lines": ["near", "far"], "gaps": []}
    assert app_mod.selected_overlays(data, "ABC", Timeframe.DAILY, "XYZ-daily", chosen) == ()
    assert data.overlays.cache_info().misses == 0  # a stale menu never runs the detectors
    picked = app_mod.selected_overlays(data, "abc", Timeframe.DAILY, "ABC-daily", chosen)
    assert [o.item_id for o in picked] == ["near", "far"]
    fig, _ = _render_with(data, picked)
    assert [t.name for t in fig.data][:3] == ["Support 358", "Support 300", "ABC"]


def _render_with(data, overlays):
    return app_mod.render(data, ChartConfig(), "ABC", Timeframe.DAILY, ChartType.CANDLES, [], True, None, overlays)


def test_family_box_and_items_stay_in_step():
    sync = app_mod.family_sync
    five = {"of": 5, "events": False}
    assert sync("family", "gaps", ["gaps"], [], ["a", "b"], five) == (["gaps"], ["a", "b"], "2 of 5 shown")
    assert sync("family", "gaps", [], ["a", "b"], ["a", "b"], five) == ([], [], "0 of 5 shown")
    # unticking the last item by hand unticks the box, so the next tick restores the defaults
    assert sync("items", "gaps", ["gaps"], [], ["a", "b"], five) == ([], [], "0 of 5 shown")
    assert sync("items", "gaps", [], ["c"], ["a", "b"], five) == (["gaps"], ["c"], "1 of 5 shown")
    # a family with nothing to pick can't stay ticked
    assert sync("family", "gaps", ["gaps"], [], [], {"of": 0}) == ([], [], "0 of 0 shown")
    assert sync("items", "divergences", [], ["d"], [], {"of": 2, "events": True})[2] == "1 of 2 recent"


def test_count_texts():
    assert app_mod.family_count_text(3, 41) == "3 of 41 shown"
    assert app_mod.family_count_text(0, 2, events=True) == "0 of 2 recent"
    assert app_mod.family_count_text(3, 0, events=True) == "3 shown, 0 recent"  # older ones ticked
    assert app_mod.total_count_text(10, 10) == "10 / 10 on the chart"
    assert app_mod.total_count_text(12, 10) == "12 / 10 on the chart — busy"
