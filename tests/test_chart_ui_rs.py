import sqlite3

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.relative_strength import store
from src.ui.chart import rs


def _rows(dates, ratings, **cols) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "rs_ratio": 1.0, "rs_mansfield": 0.0,
                         "rs_weighted_return": 0.0, "rs_rating": ratings, **cols})


@pytest.fixture
def conns():
    raw, derived = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    db.create_tables(raw)
    store.create_relative_strength_tables(derived)
    db.upsert_ticker_sector(raw, pd.DataFrame({"ticker": ["ABC"], "sector": ["Technology"],
                                               "industry": ["Software"]}))
    dates = ["2026-08-31", "2026-09-02", "2026-09-30"]
    store.upsert_relative_strength(derived, "vs_market", _rows(dates, [60.0, 65.0, 71.0], ticker="ABC",
                                                               benchmark="SPY"), "r1")
    store.upsert_relative_strength(derived, "vs_sector", _rows(dates[-1:], [44.0], ticker="ABC",
                                                               benchmark="XLK"), "r1")
    for sector, rating in [("Technology", 82.0), ("Energy", 90.0), ("Utilities", 10.0)]:
        store.upsert_sector_relative_strength(derived, _rows(dates[-1:], [rating], sector=sector,
                                                             benchmark="SPY"), "r1")
    yield raw, derived
    raw.close()
    derived.close()


def test_strip_reads_ratings_change_and_sector_rank(conns):
    strip = rs.rs_strip(*conns, "abc", change_days=28)
    assert strip.vs_market.value == 71.0
    # vs 2026-09-02 (exactly 28 days earlier, the last row on or before then), not 2026-08-31
    assert strip.vs_market.change == 6.0
    assert strip.vs_market.as_of == "2026-09-30"
    assert strip.vs_sector.value == 44.0 and strip.vs_sector.change is None
    assert strip.vs_sector.benchmark == "XLK"
    assert (strip.sector, strip.industry) == ("Technology", "Software")
    assert (strip.sector_rank.rank, strip.sector_rank.of) == (2, 3)


def test_strip_text(conns):
    parts = rs.strip_parts(rs.rs_strip(*conns, "ABC", change_days=28), change_days=28)
    assert parts == ["RS vs market: 71 (+6 in 28d)", "RS vs sector (XLK): 44",
                     "Technology · RS 82 · 2nd of 3", "Software", "as of 2026-09-30"]


def test_ticker_without_rs_rows_says_so(conns):
    strip = rs.rs_strip(*conns, "XYZ", change_days=28)
    assert strip.vs_market is None and strip.sector is None
    assert rs.strip_parts(strip, 28) == ["RS vs market: no RS run", "RS vs sector: no RS run"]


def test_sector_rank_uses_one_date_and_counts_sectors_missing_that_day(conns):
    _, derived = conns
    store.upsert_sector_relative_strength(derived, _rows(["2026-09-29"], [95.0], sector="Healthcare",
                                                         benchmark="SPY"), "r1")
    strip = rs.rs_strip(*conns, "ABC", change_days=28)
    # Healthcare's older, higher rating isn't ranked against Technology's 2026-09-30 one.
    assert (strip.sector_rank.rank, strip.sector_rank.of, strip.sector_rank.missing) == (2, 3, 1)
    assert "Technology · RS 82 · 2nd of 3 (1 not rated that day)" in rs.strip_parts(strip, 28)


@pytest.mark.parametrize("n, text", [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"),
                                     (12, "12th"), (21, "21st")])
def test_ordinal(n, text):
    assert rs._ordinal(n) == text
