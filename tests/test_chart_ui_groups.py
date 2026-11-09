import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.derived_db import create_runs_table, record_run
from src.signals.relative_strength import store
from src.ui.chart import app as app_mod
from src.ui.chart import groups
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
    assert gone.member and gone.status == f"no bar on {AS_OF}, last 2026-08-19"
    assert page.sectors[0].members == 4 and page.sectors[0].n_counted == (3, 2)  # no bar that day: not counted


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
    assert names == ["Rank", "Sector", "ETF", "RS", "Rank Δ 4w", "Rank Δ 13w", "> 50d MA", "> 200d MA", "Members"]
    assert [c["name"] for c in app_mod.member_columns(GroupsConfig())][2] == "RS Δ 4w"


def test_app_opens_on_the_groups_tab_and_says_why_without_a_database():
    data = app_mod.ChartData(Path("/nonexistent/raw.sqlite"), Path("/nonexistent/derived.sqlite"))
    app = app_mod.create_app(data=data, page="groups")
    assert app.layout["page"].value == "groups"
    assert data.groups(GroupsConfig()) == "Groups: no derived database"
