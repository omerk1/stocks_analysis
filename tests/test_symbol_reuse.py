import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing import symbol_reuse as sr
from src.foundation.data_processing import ticker_renames as tr

DAYS = pd.bdate_range("2015-01-01", "2015-03-31")


@pytest.fixture
def conn():
    c = db.get_connection(":memory:")
    db.create_tables(c)
    yield c
    c.close()


def _bars(conn, ticker):
    frame = pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000, "is_partial": 0},
                         index=pd.DatetimeIndex(DAYS, name="timestamp"))
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, frame)


def _row(ticker="BBT"):
    return pd.Series({"ticker": ticker, "valid_from": "1997-12-04", "valid_to": "2019-12-09",
                      "start_date": "2009-01-01", "end_date": "2019-12-09"})


def test_candidates_are_former_members_with_bars_not_already_in_renames(conn):
    for t in ("OLD", "LIVE", "RENAMED", "EARLY"):
        _bars(conn, t)
    db.replace_index_membership(conn, "sp500", pd.DataFrame([
        ("OLD", "2010-01-01", "2019-12-09"), ("LIVE", "2010-01-01", None), ("LIVE", "2000-01-01", "2005-01-01"),
        ("RENAMED", "2010-01-01", "2018-01-01"), ("EARLY", "2000-01-01", "2005-01-01"), ("NOBARS", "2010-01-01", "2019-01-01"),
    ], columns=["ticker", "start_date", "end_date"]))
    db.upsert_ticker_rename(conn, {"old_ticker": "RENAMED", "status": "matched"})
    _bars(conn, "UNMAPPED")  # a ticker_renames row decided before any bars existed under it
    db.replace_index_membership(conn, "nasdaq100", pd.DataFrame([("UNMAPPED", "2011-01-01", "2016-01-01")],
                                                               columns=["ticker", "start_date", "end_date"]))
    db.upsert_ticker_rename(conn, {"old_ticker": "UNMAPPED", "status": "no_current_ticker"})

    assert list(sr.candidates(conn, ["sp500", "nasdaq100"], "2009-01-01")["ticker"]) == ["OLD", "UNMAPPED"]


def test_a_symbol_now_held_by_another_company_is_reused():
    names = {92230: ["TRUIST FINANCIAL CORP", "BB&T CORP"], 1108134: ["Beacon Financial Corp", "BERKSHIRE HILLS BANCORP INC"]}
    out = sr.decide(_row(), {"name": "BB&T CORP", "cik": "92230"}, 1108134, names)

    assert out["status"] == "reused" and out["cik_verified"] == 1 and out["holder_name"] == "Beacon Financial Corp"


def test_a_renamed_holder_is_the_same_company():
    names = {55067: ["Kellanova", "KELLOGG CO"]}
    out = sr.decide(_row("K"), {"name": "Kellogg Co", "cik": "55067"}, 55067, names)

    assert out["status"] == "same_company"


def test_no_listing_and_no_holder_are_left_for_review():
    assert sr.decide(_row(), None, 1, {1: ["X"]})["status"] == "no_listing"
    out = sr.decide(_row(), {"name": "Gone Co", "cik": "7"}, None, {7: ["MORGAN STANLEY"]})
    assert out["status"] == "no_holder" and out["cik_verified"] == 0


def test_cik_verified_is_set_by_resolve_and_backfilled_from_status(conn):
    db.upsert_ticker_rename(conn, {"old_ticker": "OK", "status": "no_current_ticker", "cik": 1})
    db.upsert_ticker_rename(conn, {"old_ticker": "BAD", "status": "name_mismatch", "cik": 2})
    db.upsert_ticker_rename(conn, {"old_ticker": "NONE", "status": "no_listing"})

    db.upsert_ticker_rename(conn, {"old_ticker": "UNK", "status": "name_mismatch", "cik": 3,
                                   "detail": tr.CIK_NOT_IN_SEC, "cik_verified": 0})

    assert tr.backfill_cik_verified(conn) == 3  # OK -> 1, BAD -> 0, UNK 0 -> NULL (unknown, not wrong)
    assert tr.backfill_cik_verified(conn) == 0  # idempotent
    flags = dict(conn.execute("SELECT old_ticker, cik_verified FROM ticker_renames").fetchall())
    assert flags == {"OK": 1, "BAD": 0, "NONE": None, "UNK": None}
    assert db.verified_cik(conn, "OK", "2015-01-01") == 1
    assert db.verified_cik(conn, "BAD", "2015-01-01") is None and db.verified_cik(conn, "NONE", "2015-01-01") is None

    row = tr.resolve(conn, "YHOO", "2010-01-01", "2015-01-01", {"name": "YAHOO INC", "cik": "316736"}, {},
                     {316736: ["FIELDPOINT PETROLEUM CORP"]})
    assert row["status"] == "name_mismatch" and row["cik_verified"] == 0


def test_same_cik_with_a_misspelled_name_is_for_review_not_reused():
    names = {832988: ["SIGNET JEWELERS LTD"]}
    out = sr.decide(_row("SIG"), {"name": "Signet Jewlers Limited", "cik": "832988"}, 832988, names)

    assert out["status"] == "same_cik_name_differs"


def test_a_listing_without_a_name_is_for_review_not_reused():
    out = sr.decide(_row(), {"name": None, "cik": "5"}, 9, {5: ["A"], 9: ["B"]})

    assert out["status"] == "no_listing"


def test_the_lookup_date_is_inside_the_checked_window_not_the_whole_block(conn):
    _bars(conn, "BEAM")
    db.replace_index_membership(conn, "sp500", pd.DataFrame([("BEAM", "1996-01-02", "2014-05-01")],
                                                            columns=["ticker", "start_date", "end_date"]))
    row = sr.candidates(conn, ["sp500"], "2009-01-01").iloc[0]

    out = sr.decide(row, None, None, {})

    assert row["valid_from"] == "1996-01-02" and row["start_date"] == "2009-01-01"
    assert out["lookup_date"] == tr.lookup_date("2009-01-01", "2014-05-01")


class _Polygon:
    def __init__(self):
        self.calls = []

    def ticker_as_of(self, ticker, as_of):
        self.calls.append((ticker, as_of))
        return {"name": "Old Co", "cik": "1"}


def test_refresh_reuses_stored_answers_for_the_same_date_and_asks_for_a_new_one(conn, tmp_path):
    import json, zipfile
    zip_path = tmp_path / "s.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"CIK{1:010d}.json", json.dumps({"name": "OLD CO", "formerNames": []}))
    _bars(conn, "OLD")
    db.replace_index_membership(conn, "sp500", pd.DataFrame([("OLD", "2010-01-01", "2019-12-09")],
                                                            columns=["ticker", "start_date", "end_date"]))
    client = _Polygon()
    sr.run(conn, client, {"OLD": 1}, zip_path, ["sp500"], "2009-01-01")
    sr.run(conn, client, {"OLD": 1}, zip_path, ["sp500"], "2009-01-01", refresh=True)
    assert len(client.calls) == 1  # same lookup date: the stored answer is reused

    sr.run(conn, client, {"OLD": 1}, zip_path, ["sp500"], "2012-01-01", refresh=True)
    assert len(client.calls) == 2  # the window, and so the date, changed


def test_verified_cik_holds_only_inside_its_window(conn):
    db.upsert_ticker_rename(conn, {"old_ticker": "OLD", "status": "no_current_ticker", "cik": 42,
                                   "cik_verified": 1, "valid_from": "2010-01-01", "valid_to": "2015-12-31"})

    assert db.verified_cik(conn, "OLD", "2012-06-01") == 42
    assert db.verified_cik(conn, "OLD", "2005-06-01") is None  # an earlier block may be another company
