import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing import ticker_renames as tr
from src.signals.breadth.compute import compute_breadth
from src.signals.breadth.config import BreadthConfig

_DAYS = pd.bdate_range("2015-01-01", "2015-03-31")


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(conn, ticker, days=_DAYS, closes=None):
    closes = closes if closes is not None else [10.0] * len(days)
    frame = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000, "is_partial": 0},
        index=pd.DatetimeIndex(days, name="timestamp"),
    )
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, frame)


class FakePolygon:
    def __init__(self, listings):
        self.listings = listings
        self.calls = []

    def ticker_as_of(self, ticker, as_of):
        self.calls.append((ticker, as_of))
        return self.listings.get(ticker)


def _members(conn, rows):
    db.replace_index_membership(conn, "sp500", pd.DataFrame(rows, columns=["ticker", "start_date", "end_date"]))


def test_candidates_are_members_without_bars_after_since(conn):
    _bars(conn, "SPY")
    _bars(conn, "KEEP")
    _members(conn, [("OLD", "2012-01-01", "2015-06-30"), ("KEEP", "2012-01-01", None), ("GONE", "2001-01-01", "2005-01-01")])

    result = tr.candidates(conn, ["sp500"], "2009-01-01")

    assert list(result["ticker"]) == ["OLD"]


def test_resolve_matches_same_cik_with_covering_history(conn):
    _bars(conn, "SPY")
    _bars(conn, "NEW")

    row = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {"name": "Old Co", "cik": "0000000042"}, {42: ["NEW"]})

    assert row["status"] == "matched" and row["new_ticker"] == "NEW" and row["coverage"] == pytest.approx(1.0)


def test_resolve_rejects_partial_history_and_other_outcomes(conn):
    _bars(conn, "SPY")
    _bars(conn, "PART", days=_DAYS[:20])
    _bars(conn, "A1")
    _bars(conn, "A2")

    low = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {"name": "x", "cik": "1"}, {1: ["PART"]})
    amb = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {"name": "x", "cik": "2"}, {2: ["A1", "A2"]})
    none = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {"name": "x", "cik": "3"}, {3: ["NOBARS"]})
    missing = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", None, {})

    assert low["status"] == "low_coverage"
    assert amb["status"] == "ambiguous"
    assert none["status"] == "no_current_ticker"
    assert missing["status"] == "no_listing"


def test_run_looks_up_inside_membership_and_skips_decided_tickers(conn):
    _bars(conn, "SPY")
    _bars(conn, "NEW")
    _members(conn, [("OLD", "2015-01-01", "2015-03-31")])
    client = FakePolygon({"OLD": {"name": "Old Co", "cik": "42"}})

    tr.run(conn, client, {"NEW": 42}, ["sp500"], "2009-01-01")
    tr.run(conn, client, {"NEW": 42}, ["sp500"], "2009-01-01")

    assert len(client.calls) == 1
    assert "2015-01-01" < client.calls[0][1] < "2015-03-31"
    assert tr.price_ticker_map(conn) == {"OLD": "NEW"}


def test_share_class_symbols_come_back_in_project_spelling():
    assert tr.tickers_by_cik({"BRK-B": 7, "BRK-A": 7}) == {7: ["BRK.B", "BRK.A"]}


def test_breadth_counts_a_renamed_member_once_under_its_new_symbol(conn):
    days = pd.bdate_range("2020-01-01", periods=10)
    _bars(conn, "NEW", days=days, closes=[10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
    # Old symbol's membership ends the day the new one's starts (touching intervals).
    _members(conn, [("OLD", "2020-01-01", "2020-01-08"), ("NEW", "2020-01-08", None)])
    db.upsert_ticker_rename(conn, {"old_ticker": "OLD", "new_ticker": "NEW", "status": "matched"})
    config = BreadthConfig(indices=["sp500"], sma_periods=(3,), ema_periods=(), price_source=db.YFINANCE)

    result = compute_breadth(conn, "sp500", config)

    assert (result["n_with_data"] == 1).all()
    assert result["n_advancing"].iloc[1] == 1
