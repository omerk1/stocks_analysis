import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.derived_db import create_runs_table, record_run
from src.signals.relative_strength import store
from src.ui.chart import app as app_mod
from src.ui.chart import groups, rs
from src.ui.chart.config import GroupsConfig

AS_OF = "2026-09-30"


def _rs_rows(dates, ratings, **cols) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "rs_ratio": 1.0, "rs_mansfield": 0.0,
                         "rs_weighted_return": 0.0, "rs_rating": ratings, **cols})


def _bars(raw, ticker, end, n, step, source=db.YFINANCE_SPLIT_ONLY):
    idx = pd.bdate_range(end=end, periods=n)
    close = 100 + step * np.arange(n, dtype=float)
    frame = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0,
                          "is_partial": 0}, index=idx)
    db.upsert_bars(raw, "bars_1d", ticker, source, frame)


def _tickers(raw, active: dict[str, bool]):
    db.upsert_tickers(raw, pd.DataFrame({"ticker": list(active), "name": "x", "type": "CS",
                                         "active": list(active.values()), "delisted_utc": None}))


def _gone(raw, tickers: dict[str, str], sector="Technology"):
    """Add tickers that left the S&P 500 on the given dates (keeping the fixture's rows)."""
    rows = db.read_index_membership(raw, "sp500")[["ticker", "start_date", "end_date"]]
    new = pd.DataFrame({"ticker": list(tickers), "start_date": "2020-01-01", "end_date": list(tickers.values())})
    db.replace_index_membership(raw, "sp500", pd.concat([rows, new], ignore_index=True))
    db.upsert_ticker_sector(raw, pd.DataFrame({"ticker": list(tickers), "sector": sector, "industry": "x"}))


@pytest.fixture
def conns():
    raw, derived = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    db.create_tables(raw)
    db.replace_index_membership(raw, "sp500", pd.DataFrame({
        "ticker": ["AAA", "BBB", "SHORT", "GONE", "LEFT", "OLD", "NOSEC"],
        "start_date": ["2020-01-01"] * 7,
        "end_date": [None, None, None, "2026-08-20", "2026-09-10", "2026-01-02", None]}))
    db.replace_index_membership(raw, "nasdaq100", pd.DataFrame({
        "ticker": ["AAA", "CCC"], "start_date": ["2020-01-01"] * 2, "end_date": [None, None]}))
    db.upsert_ticker_sector(raw, pd.DataFrame({
        "ticker": ["AAA", "BBB", "SHORT", "GONE", "LEFT", "OLD", "CCC"],
        "sector": ["Technology"] * 6 + ["Energy"], "industry": ["x"] * 7}))
    _bars(raw, "AAA", AS_OF, 300, 1.0)  # rising: above both averages, at its high
    _bars(raw, "BBB", AS_OF, 300, -0.1)  # falling: below both
    _bars(raw, "SHORT", AS_OF, 100, 1.0)  # too short for the 200-day average and the 52-week high
    _bars(raw, "CCC", AS_OF, 300, 1.0)
    _bars(raw, "LEFT", AS_OF, 300, 1.0)  # left the index, still trading
    _bars(raw, "GONE", "2026-08-19", 300, 1.0, source=db.TIINGO_SPLIT_ONLY)  # delisted: Tiingo bars only
    _bars(raw, "SPY", "2026-11-06", 10, 1.0)
    _tickers(raw, {"GONE": False})

    store.create_relative_strength_tables(derived)
    create_runs_table(derived)
    sp = record_run(derived, "relative_strength", "sp500", "daily", None, "{}", 0, False)
    ndx = record_run(derived, "relative_strength", "nasdaq100", "daily", None, "{}", 0, False)
    store.upsert_relative_strength(derived, "vs_market", _rs_rows(["2026-09-02", AS_OF], [70.0, 90.0], ticker="AAA",
                                                                  benchmark="SPY"), ndx)
    store.upsert_relative_strength(derived, "vs_market", _rs_rows([AS_OF], [30.0], ticker="BBB", benchmark="SPY"), sp)
    store.upsert_relative_strength(derived, "vs_market", _rs_rows(["2026-08-19"], [55.0], ticker="GONE",
                                                                  benchmark="SPY"), sp)
    sectors = {"2026-09-02": {"Technology": 50.0, "Energy": 70.0, "Utilities": 10.0},
               "2026-09-29": {"Healthcare": 95.0},  # rated that week, not on the page date
               AS_OF: {"Technology": 80.0, "Energy": 60.0, "Utilities": 20.0},
               "2026-10-01": {"Technology": 81.0}}  # later, but only one sector rated
    for date, ratings in sectors.items():
        for sector, rating in ratings.items():
            store.upsert_sector_relative_strength(derived, _rs_rows([date], [rating], sector=sector,
                                                                    benchmark="SPY"), "r1")
    yield raw, derived
    raw.close()
    derived.close()


@pytest.fixture
def page(conns):
    return groups.build_page(*conns, GroupsConfig())


def test_page_date_is_the_latest_with_the_most_sectors_rated(page):
    assert page.as_of == AS_OF
    assert page.not_rated == ("Healthcare",)
    assert page.bars_end == "2026-11-06"


def test_sector_table_ranks_and_rank_changes(page):
    assert [(s.sector, s.rank, s.etf) for s in page.sectors] == [
        ("Technology", 1, "XLK"), ("Energy", 2, "XLE"), ("Utilities", 3, "XLU")]
    # 4 weeks earlier Energy was 1st and Technology 2nd; nothing was rated 13 weeks earlier
    assert [s.rank_changes for s in page.sectors] == [(1, None), (-1, None), (0, None)]


def test_breadth_counts_current_members_with_the_full_window(page):
    tech = page.sectors[0]
    assert tech.members == 3  # AAA, BBB, SHORT; not the two that left
    assert tech.n_counted == (3, 2)  # SHORT has no 200-day average
    assert tech.pct_above == pytest.approx((2 / 3, 1 / 2))
    utilities = page.sectors[2]
    assert (utilities.members, utilities.pct_above) == (0, (None, None))


def test_members_sorted_by_rating_with_gone_ones_last(page):
    tech = page.members["Technology"]
    assert [m.ticker for m in tech] == ["AAA", "BBB", "SHORT", "GONE", "LEFT"]
    aaa = tech[0]
    assert (aaa.rating, aaa.change, aaa.rated_in, aaa.status) == (90.0, 20.0, "Nasdaq-100", "")
    assert aaa.pct_from_high == pytest.approx(399 / 400 - 1)  # last close 399, highest high 400
    assert aaa.vs_ma[0] > 0 and aaa.vs_ma[1] > 0
    assert tech[1].rated_in == "S&P 500" and tech[1].vs_ma[0] < 0
    short = tech[2]
    assert short.rating is None and short.pct_from_high is None and short.vs_ma[1] is None
    gone, left = tech[3], tech[4]
    assert not gone.member and gone.status == "delisted, left the index 2026-08-20, last bar 2026-08-19"
    assert gone.rating == 55.0  # its last rating, read from the fallback-priced history too
    assert gone.vs_ma[0] is not None  # bars from Tiingo, the only source it has
    assert not left.member and left.status == "left the index 2026-09-10"
    assert "OLD" not in {m.ticker for ms in page.members.values() for m in ms}  # left before the window


def test_member_without_a_sector_is_reported(page):
    assert page.no_sector == ("NOSEC",)


def test_member_without_a_bar_on_the_page_date_says_so(conns):
    raw, derived = conns
    db.replace_index_membership(raw, "nasdaq100", pd.DataFrame({
        "ticker": ["AAA", "CCC", "GONE"], "start_date": ["2020-01-01"] * 3, "end_date": [None, None, None]}))
    page = groups.build_page(raw, derived, GroupsConfig())
    gone = next(m for m in page.members["Technology"] if m.ticker == "GONE")
    assert gone.member and gone.status == f"no bar on {AS_OF}, last 2026-08-19, rating from 2026-08-19"
    assert page.sectors[0].members == 4 and page.sectors[0].n_counted == (3, 2)  # no bar that day: not counted


def test_member_with_an_older_rating_says_from_when(conns):
    raw, derived = conns
    store.upsert_relative_strength(derived, "vs_market", _rs_rows(["2026-09-15"], [40.0], ticker="CCC",
                                                                  benchmark="SPY"), "r1")
    ccc = groups.build_page(raw, derived, GroupsConfig()).members["Energy"][0]
    assert (ccc.ticker, ccc.rating, ccc.status) == ("CCC", 40.0, "rating from 2026-09-15")


def test_gone_ticker_is_delisted_only_when_marked_inactive(conns):
    raw, derived = conns
    _gone(raw, {"NOBARS": "2026-09-01", "STALE": "2026-09-05", "ENDED": "2026-09-06"})
    _bars(raw, "STALE", "2026-09-04", 300, 1.0)  # bars stop, but nothing says it's delisted
    _bars(raw, "ENDED", "2026-09-04", 300, 1.0)
    _tickers(raw, {"STALE": True, "ENDED": False, "LEFT": False})  # LEFT: inactive today, still trading then
    status = {m.ticker: m.status for m in groups.build_page(raw, derived, GroupsConfig()).members["Technology"]}
    assert status["NOBARS"] == "left the index 2026-09-01, no bars"
    assert status["STALE"] == "left the index 2026-09-05, bars end 2026-09-04"
    assert status["ENDED"] == "delisted, left the index 2026-09-06, last bar 2026-09-04"
    assert status["GONE"] == "delisted, left the index 2026-08-20, last bar 2026-08-19"
    assert status["LEFT"] == "left the index 2026-09-10"  # a bar on the page date: not delisted


def test_sector_with_members_but_no_rating_is_listed_unranked(conns):
    raw, derived = conns
    db.replace_index_membership(raw, "nasdaq100", pd.DataFrame({
        "ticker": ["AAA", "CCC", "RRR"], "start_date": ["2020-01-01"] * 3, "end_date": [None, None, None]}))
    db.upsert_ticker_sector(raw, pd.DataFrame({"ticker": ["RRR"], "sector": ["Real Estate"], "industry": ["x"]}))
    _bars(raw, "RRR", AS_OF, 300, 1.0)
    page = groups.build_page(raw, derived, GroupsConfig())
    last = page.sectors[-1]
    assert [s.sector for s in page.sectors] == ["Technology", "Energy", "Utilities", "Real Estate"]
    assert (last.rating, last.rank, last.rank_changes, last.etf) == (None, None, (None, None), "XLRE")
    assert (last.members, last.pct_above) == (1, (1.0, 1.0))
    assert [m.ticker for m in page.members["Real Estate"]] == ["RRR"]


def test_rank_date_window_is_inclusive_and_honours_allowed_dates(conns):
    _, derived = conns
    # 2026-09-23 is exactly 7 days before AS_OF: inside the window, as in the strip
    store.upsert_sector_relative_strength(derived, _rs_rows(["2026-09-23"] * 1, [1.0], sector="Energy",
                                                            benchmark="SPY"), "r1")
    assert rs.rank_date(derived, AS_OF) == AS_OF  # 3 sectors that day, the most
    assert rs.rank_date(derived, AS_OF, {"2026-09-23", "2026-09-29"}) == "2026-09-29"  # both 1: the latest
    assert rs.rank_date(derived, AS_OF, {"2026-09-23"}) == "2026-09-23"
    assert rs.rank_date(derived, "2026-09-22", {"2026-09-23"}) is None
    assert rs.window_sectors(derived, AS_OF) == {"Technology", "Energy", "Utilities", "Healthcare"}


def test_groups_and_strip_rank_a_sector_on_the_same_date(conns):
    raw, derived = conns
    page = groups.build_page(raw, derived, GroupsConfig())
    strip = rs.rs_strip(raw, derived, "AAA", change_days=28)  # AAA: Technology
    tech = next(s for s in page.sectors if s.sector == "Technology")
    # Technology's own latest rating is 2026-10-01, but both rank it on the page date
    assert strip.sector_rank.rank_date == page.as_of and strip.sector_rank.rank == tech.rank


def test_missing_tables_give_a_message():
    raw, derived = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    assert groups.build_page(raw, derived, GroupsConfig()) == "Groups: no sector RS run in the derived database."


def test_price_stats_need_the_full_window():
    prices = pd.DataFrame({"ticker": "A", "date": [f"2026-01-{d:02d}" for d in range(1, 6)],
                           "high": [10.0, 12.0, 11.0, 11.0, 11.0], "close": [9.0, 11.0, 10.0, 10.0, 8.0]})
    stats = groups.price_stats(prices, (3, 5), high_bars=4)
    row = stats.loc["A"]
    assert row["last_bar"] == "2026-01-05"
    assert row["pct_from_high"] == pytest.approx(8 / 12 - 1)
    assert row["vs_ma_3"] == pytest.approx(8 / ((10 + 10 + 8) / 3) - 1)
    assert row["vs_ma_5"] == pytest.approx(8 / 9.6 - 1)
    assert np.isnan(groups.price_stats(prices, (6,), high_bars=6).loc["A", "vs_ma_6"])


def test_table_rows_header_and_clicks(page):
    rows, tips = app_mod.sector_rows(page)
    assert rows[0]["id"] == "Technology" and rows[0]["rank_change_0"] == 1 and rows[0]["rank_change_1"] is None
    assert tips[0]["above_1"] == f"of 2 members with the full window and a bar on {AS_OF}"
    members = app_mod.member_rows(page, "Technology")
    assert [r["gone"] for r in members] == ["no", "no", "no", "yes", "yes"]
    assert app_mod.member_rows(page, None) == []
    assert app_mod.groups_header(page) == (
        f"As of {AS_OF}, the last sector RS date · bars run to 2026-11-06: rerun relative strength to catch up"
        " · not rated that day: Healthcare · members with no sector: NOSEC")
    assert app_mod.selected_sector(page, None) == "Technology"
    assert app_mod.selected_sector(page, "Energy") == "Energy"
    assert app_mod.selected_sector(page, "Nope") == "Technology"
    assert app_mod.clicked_row({"row": 0, "column_id": "ticker", "row_id": "AAA"}) == "AAA"
    assert app_mod.clicked_row(None) is None


def test_column_names_follow_the_config():
    names = [c["name"] for c in app_mod.sector_columns(GroupsConfig())]
    assert names == ["#", "Sector", "ETF", "RS", "Rank Δ 4w", "Rank Δ 13w", "> 50d MA", "> 200d MA", "Members"]
    assert [c["name"] for c in app_mod.member_columns(GroupsConfig())][2] == "RS Δ 4w"


def test_app_opens_on_the_groups_tab_and_says_why_without_a_database():
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
    app = app_mod.create_app(data=data, page="groups")
    assert app.layout["page"].value == "groups"
    assert data.groups(GroupsConfig()) == "Groups: no derived database"


def test_unknown_start_page_is_refused():
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
    with pytest.raises(ValueError, match="page must be one of"):
        app_mod.create_app(data=data, page="group")


class CountingData(app_mod.ChartData):
    def __init__(self, results):
        super().__init__(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
        self.results, self.calls = list(results), 0

    def _groups(self, config):
        self.calls += 1
        return self.results.pop(0)


def test_a_failed_page_is_not_cached_and_reload_rebuilds(page):
    data = CountingData(["Groups failed: locked", page, page])
    assert data.groups(GroupsConfig()) == "Groups failed: locked"
    assert data.groups(GroupsConfig()) is page  # the failure was retried
    assert data.groups(GroupsConfig()) is page and data.calls == 2  # the page is cached
    assert data.groups(GroupsConfig(), reload=True) is page and data.calls == 3
    assert data.groups_note is None


def test_a_failed_reload_keeps_the_previous_page(page):
    data = CountingData([page, "Groups failed: locked"])
    assert data.groups(GroupsConfig()) is page
    assert data.groups(GroupsConfig(), reload=True) is page
    assert data.groups_note == "reload failed, showing the previous page (Groups failed: locked)"
    assert data.groups(GroupsConfig()) is page and data.groups_note is None and data.calls == 2


def test_sector_styles_bars_signs_and_selection(page):
    rows, _ = app_mod.sector_rows(page)
    styles = app_mod.sector_styles(rows, "Energy", 2)
    bars = [s for s in styles if "background" in s]
    # one bar per row and share that has a value
    assert len(bars) == sum(r[f"above_{i}"] is not None for r in rows for i in range(2))
    assert {s["if"]["column_id"] for s in styles if s.get("color") in ("#15803d", "#b91c1c")} == {
        "rank_change_0", "rank_change_1"}
    selected = [s for s in styles if s.get("backgroundColor") == app_mod._SELECTED]
    assert selected == [{"if": {"filter_query": '{id} = "Energy"'}, "backgroundColor": app_mod._SELECTED,
                         "fontWeight": 600}]
    assert styles[0] == selected[0]  # first, so the RS shading after it still shows on the selected row
    assert app_mod.sector_styles([], None, 2) == app_mod._rs_shading("rating")


def test_shown_values_have_no_negative_zero():
    assert str(app_mod.shown(-0.4, 0)) == "0.0" and app_mod.shown(-0.6, 0) == -1.0
    assert str(app_mod.shown(-0.004, 2)) == "0.0" and app_mod.shown(-0.026, 2) == -0.03
    assert app_mod.shown(None, 0) is None


def test_breadth_bar_is_clamped():
    assert "60%" in app_mod.breadth_bar(0.6)
    assert "100%, transparent 100%" in app_mod.breadth_bar(1.4)
    assert f"{app_mod._BAR} 0%, transparent 0%" in app_mod.breadth_bar(-0.1)


def test_rs_shading_is_one_hue_and_signs_keep_green_and_red():
    colours = {s["backgroundColor"] for s in app_mod._rs_shading("rating")}
    assert not colours & {"#15803d", "#b91c1c"} and all(c.startswith("#") for c in colours)
    assert [lo for lo, _, _ in app_mod._RS_SHADES] == sorted((lo for lo, _, _ in app_mod._RS_SHADES), reverse=True)


def test_members_title_counts_the_ones_that_left(page):
    rows = app_mod.member_rows(page, "Technology")
    assert app_mod.members_title("Technology", rows, GroupsConfig()) == (
        "Technology · 3 members (+2 left in the last 91 days) · click a ticker for its chart")
