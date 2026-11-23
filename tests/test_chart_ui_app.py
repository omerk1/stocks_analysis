import sqlite3
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import overlay_cache, rs
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.overlays import FAMILIES, Overlay


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


def _item(family, item_id, lo=100.0):
    return Overlay(family, item_id, item_id, "hline", pd.Timestamp("2024-06-03"), lo, lo, None, True)


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


def test_data_age_counts_the_weekdays_after_the_market_s_last_bar():
    fri = pd.Timestamp("2026-11-06")
    assert app_mod.data_age(fri, date(2026, 11, 9), 2) == ("Data to 2026-11-06", False)  # Monday: today's not in yet
    assert app_mod.data_age(fri, date(2026, 11, 10), 2) == ("Data to 2026-11-06 · 1 weekday behind", False)
    assert app_mod.data_age(fri, date(2026, 11, 12), 2) == ("Data to 2026-11-06 · 3 weekdays behind", True)
    assert app_mod.data_age(fri, date(2026, 11, 17), 2) == ("Data to 2026-11-06 · 6 weekdays behind", True)
    assert app_mod.data_age(fri, date(2026, 11, 6), 2) == ("Data to 2026-11-06", False)
    assert app_mod.data_age(None, date(2026, 11, 6), 2) == ("No SPY bars: data age unknown", True)


def test_data_age_line_reads_spy_and_never_raises():
    data = FakeData()  # SPY's bars end 2024-12-27 (260 weekdays from 2024-01-01)
    text, style = app_mod.data_age_children(data, ChartConfig(), today=date(2024, 12, 30))
    assert (text, style["color"]) == ("Data to 2024-12-27", app_mod._MUTED)
    text, style = app_mod.data_age_children(data, ChartConfig(), today=date(2025, 1, 6))
    assert text == "Data to 2024-12-27 · 5 weekdays behind" and style["color"] == app_mod._RED

    class Failing(FakeData):
        def _bars(self, ticker, timeframe):
            raise OSError("disk")

    text, style = app_mod.data_age_children(Failing(), ChartConfig())
    assert text == "data age unknown (OSError)" and style["color"] == app_mod._RED


def test_a_failed_worker_pool_falls_back_to_running_here(monkeypatch):
    class Pooled(FakeData):
        def __init__(self):
            super().__init__()
            self.workers = 4

        _overlays = app_mod.ChartData._overlays  # the real one, not FakeData's stub

    data = Pooled()
    dropped, used = [], []
    monkeypatch.setattr(data, "_worker_pool", lambda: used.append("pool") or "pool")
    monkeypatch.setattr(data, "_drop_pool", lambda pool: dropped.append(pool) or True)
    monkeypatch.setattr(app_mod.overlays_mod, "all_overlays_in_pool",
                        lambda *a: (_ for _ in ()).throw(app_mod.overlays_mod.PoolFailed("shut down")))
    monkeypatch.setattr(app_mod, "_read_only", lambda path: sqlite3.connect(":memory:"))
    here = _item("sr_lines", "here")
    monkeypatch.setattr(app_mod.overlays_mod, "all_overlays", lambda conn, *a: ([here], {}))
    found = data.overlays("ABC", Timeframe.DAILY)
    # the pool couldn't take the tasks: run here, once, and the failed pool dropped
    assert found.items == (here,) and used == ["pool"] and dropped == ["pool"]


def test_a_worker_dying_drops_the_pool_and_is_not_run_again_here(monkeypatch):
    class Pooled(FakeData):
        def __init__(self):
            super().__init__()
            self.workers = 4

        _overlays = app_mod.ChartData._overlays

    data = Pooled()
    ran_here, dropped = [], []
    monkeypatch.setattr(data, "_worker_pool", lambda: "pool")
    monkeypatch.setattr(data, "_drop_pool", lambda pool: dropped.append(pool) or True)
    sr_item = _item("sr_lines", "sr item")
    monkeypatch.setattr(app_mod.overlays_mod, "all_overlays_in_pool",
                        lambda *a: ([sr_item], {"gaps": "RuntimeError: a detector worker died"}, True))
    monkeypatch.setattr(app_mod.overlays_mod, "all_overlays", lambda *a: ran_here.append(True) or ([], {}))
    found = data.overlays("ABC", Timeframe.DAILY)
    assert found.items == (sr_item,) and "worker died" in found.errors["gaps"]
    assert ran_here == [] and dropped == ["pool"]


def _saving(monkeypatch, tmp_path, failing=()):
    """A FakeData class whose results are saved under tmp_path (a new instance is the app
    restarted), and the families each run asked for. Families in `failing` fail."""
    class Saving(FakeData):
        def __init__(self):
            super().__init__()
            self.saved_overlays = overlay_cache.OverlayCache(tmp_path / "saved")

        _overlays = app_mod.ChartData._overlays

    raw = tmp_path / "raw.sqlite"
    conn = sqlite3.connect(raw)
    db.create_tables(conn)
    conn.close()
    monkeypatch.setattr(app_mod, "_read_only", lambda path: sqlite3.connect(raw))
    runs = []

    def run(conn, ticker, timeframe, bars, families=FAMILIES):
        runs.append(tuple(families))
        return ([_item(f, f"{f} item") for f in families if f not in failing],
                {f: "ValueError: boom" for f in families if f in failing})

    monkeypatch.setattr(app_mod.overlays_mod, "all_overlays", run)
    return Saving, runs


def _fields(items):
    return [(o.family, o.item_id, o.lo, o.x0) for o in items]


def test_saved_results_are_read_after_a_restart_instead_of_run(monkeypatch, tmp_path):
    Saving, runs = _saving(monkeypatch, tmp_path)
    first = Saving().overlays("ABC", Timeframe.DAILY)
    assert runs == [FAMILIES] and first.saved == 0
    again = Saving().overlays("ABC", Timeframe.DAILY)  # a new app: nothing in memory
    assert runs == [FAMILIES] and again.saved == len(FAMILIES) and again.errors == {}
    assert _fields(again.items) == _fields(first.items) == [(f, f"{f} item", 100.0, pd.Timestamp("2024-06-03"))
                                                           for f in FAMILIES]  # menu order


def test_a_failed_family_is_not_saved_and_runs_again(monkeypatch, tmp_path):
    Saving, runs = _saving(monkeypatch, tmp_path, failing=("gaps",))
    Saving().overlays("ABC", Timeframe.DAILY)
    again = Saving().overlays("ABC", Timeframe.DAILY)
    assert runs == [FAMILIES, ("gaps",)] and again.saved == len(FAMILIES) - 1
    assert again.errors == {"gaps": "ValueError: boom"}
    assert [o.family for o in again.items] == [f for f in FAMILIES if f != "gaps"]


def test_new_bars_or_new_code_run_every_family_again(monkeypatch, tmp_path):
    Saving, runs = _saving(monkeypatch, tmp_path)
    Saving().overlays("ABC", Timeframe.DAILY)
    newer = Saving()
    newer._frame = newer._frame.assign(close=newer._frame["close"] + 1)  # a refresh changed the bars
    assert newer.overlays("ABC", Timeframe.DAILY).saved == 0 and runs == [FAMILIES] * 2
    monkeypatch.setattr(overlay_cache, "code_hash", lambda: "edited")  # a detector was edited
    assert Saving().overlays("ABC", Timeframe.DAILY).saved == 0 and runs == [FAMILIES] * 3
    assert Saving().overlays("ABC", Timeframe.DAILY).saved == len(FAMILIES)


def test_a_refresh_while_the_app_runs_is_not_saved_under_the_old_bars(monkeypatch, tmp_path):
    # S/R, gaps and Fibonacci read the database, not the bars held in memory: after a
    # refresh, results from the new rows mustn't be keyed on the old bars.
    Saving, runs = _saving(monkeypatch, tmp_path)
    Saving().overlays("ABC", Timeframe.DAILY)
    conn = sqlite3.connect(tmp_path / "raw.sqlite")
    db.upsert_bars(conn, "bars_1d", "ABC", app_mod.source_for(app_mod.CHART_BASIS),
                   pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "is_partial": 0},
                                index=pd.bdate_range("2025-01-01", periods=1)))
    conn.commit()
    conn.close()
    assert Saving().overlays("ABC", Timeframe.DAILY).saved == 0 and runs == [FAMILIES] * 2


def test_the_code_is_hashed_when_the_app_starts(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(app_mod.overlay_cache, "code_hash", lambda: calls.append(1) or "h")
    app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
    assert calls == []  # nothing saved, nothing hashed
    app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"), overlay_dir=tmp_path)
    assert calls == [1]
    monkeypatch.setattr(app_mod.overlay_cache, "code_hash", lambda: (_ for _ in ()).throw(SyntaxError("mid-edit")))
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"),
                             overlay_dir=tmp_path)
    assert data.saved_overlays is None  # starts, saving nothing


def test_unreadable_key_inputs_run_every_family_and_save_nothing(monkeypatch, tmp_path):
    Saving, runs = _saving(monkeypatch, tmp_path)
    monkeypatch.setattr(app_mod.db, "read_splits", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("x")))
    found = Saving().overlays("ABC", Timeframe.DAILY)
    assert runs == [FAMILIES] and len(found.items) == len(FAMILIES)
    assert not (tmp_path / "saved").exists()


def test_dropping_a_failed_pool_leaves_a_newer_one_alone():
    class Pool:
        def __init__(self):
            self.shut = False

        def shutdown(self, wait):
            self.shut = True

    data = FakeData()
    old, new = Pool(), Pool()
    data._pool = new  # another chart already replaced `old`
    assert data._drop_pool(old) is False
    assert data._pool is new and not new.shut
    assert data._drop_pool(new) is True
    assert data._pool is None and new.shut


def test_the_same_chart_asked_for_at_once_runs_its_detectors_once():
    import threading

    started, release = threading.Event(), threading.Event()

    class Slow(FakeData):
        def _overlays(self, ticker, timeframe):
            self.calls.append(("overlays", ticker))
            started.set()
            release.wait(5)
            return app_mod.OverlaySet((), {}, 0.0)

    data = Slow()
    key = ("ABC", Timeframe.DAILY)
    results = []
    threads = [threading.Thread(target=lambda: results.append(data.overlays(*key))) for _ in range(2)]
    threads[0].start()
    started.wait(5)
    threads[1].start()  # asks while the first is still running
    deadline = time.monotonic() + 5
    while data._overlay_locks.get(key, [None, 0])[1] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert data._overlay_locks[key][1] == 2  # both callers are on the chart's one lock
    time.sleep(0.1)  # without the lock, the second would be running the detectors by now
    assert data.calls.count(("overlays", "ABC")) == 1
    release.set()
    for t in threads:
        t.join(5)
    assert data.calls.count(("overlays", "ABC")) == 1 and len(results) == 2 and results[0] is results[1]
    assert data._overlay_locks == {}  # dropped once no one uses it


def test_warm_pool_starts_one_task_per_worker_and_none_without_workers(monkeypatch):
    submitted = []
    pool = type("Pool", (), {"submit": lambda self, fn: submitted.append(fn)})()
    data = FakeData()
    monkeypatch.setattr(data, "_worker_pool", lambda: pool)
    data.warm_pool()  # workers 0: nothing
    assert submitted == []
    data.workers = 3
    data.warm_pool()
    assert submitted == [app_mod.overlays_mod.warm_worker] * 3


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
    assert data._overlays_cached.cache_info().misses == 0  # a stale menu never runs the detectors
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
