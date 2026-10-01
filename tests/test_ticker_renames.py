import json
import zipfile

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


def _submissions(tmp_path, companies):
    """A tiny stand-in for SEC's submissions.zip: {cik: (name, [former names])}."""
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for cik, (name, former) in companies.items():
            zf.writestr(f"CIK{cik:010d}.json", json.dumps(
                {"cik": str(cik), "name": name, "formerNames": [{"name": n, "from": "", "to": ""} for n in former]}
            ))
    return path


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

    row = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {"name": "Old Co", "cik": "0000000042"}, {42: ["NEW"]},
                     {42: ["New Co", "Old Co"]})

    assert row["status"] == "matched" and row["new_ticker"] == "NEW" and row["coverage"] == pytest.approx(1.0)


def test_resolve_rejects_partial_history_and_other_outcomes(conn):
    _bars(conn, "SPY")
    _bars(conn, "PART", days=_DAYS[:20])
    _bars(conn, "A1")
    _bars(conn, "A2")

    names = {1: ["Xylo Corp"], 2: ["Xylo Corp"], 3: ["Xylo Corp"]}
    listing = {"name": "Xylo Corp"}
    low = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {**listing, "cik": "1"}, {1: ["PART"]}, names)
    amb = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {**listing, "cik": "2"}, {2: ["A1", "A2"]}, names)
    none = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", {**listing, "cik": "3"}, {3: ["NOBARS"]}, names)
    missing = tr.resolve(conn, "OLD", "2015-01-01", "2015-03-31", None, {}, names)

    assert low["status"] == "low_coverage"
    assert amb["status"] == "ambiguous"
    assert none["status"] == "no_current_ticker"
    assert missing["status"] == "no_listing"


def test_run_looks_up_inside_membership_and_skips_decided_tickers(conn, tmp_path):
    _bars(conn, "SPY")
    _bars(conn, "NEW")
    _members(conn, [("OLD", "2015-01-01", "2015-03-31")])
    client = FakePolygon({"OLD": {"name": "Old Co", "cik": "42"}})
    zip_path = _submissions(tmp_path, {42: ("New Co", ["Old Co"])})

    tr.run(conn, client, {"NEW": 42}, zip_path, ["sp500"], "2009-01-01")
    tr.run(conn, client, {"NEW": 42}, zip_path, ["sp500"], "2009-01-01")

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
    db.upsert_ticker_rename(conn, {"old_ticker": "OLD", "new_ticker": "NEW", "status": "matched",
                                   "valid_from": "2020-01-01", "valid_to": "2020-01-08"})
    config = BreadthConfig(indices=["sp500"], sma_periods=(3,), ema_periods=(), price_source=db.YFINANCE)

    result = compute_breadth(conn, "sp500", config)

    assert (result["n_with_data"] == 1).all()
    assert result["n_advancing"].iloc[1] == 1


@pytest.mark.parametrize("old, sec_names, expected", [
    # Real renames: the old name is a former SEC name of the CIK.
    ("FACEBOOK INC CL A COM STK (DE)", ["Meta Platforms, Inc.", "FACEBOOK INC"], True),
    ("AMERISOURCEBERGEN CORP", ["Cencora, Inc.", "AMERISOURCEBERGEN CORP"], True),
    ("DowDuPont Inc.", ["DuPont de Nemours, Inc.", "DowDuPont Inc."], True),
    ("The Bank Of New York Mellon Corp", ["Bank of New York Mellon Corp"], True),
    # Polygon's wrong CIKs, seen on real data 2026-09-30.
    ("MONSTER WORLDWIDE INC", ["MORGAN STANLEY", "MORGAN STANLEY DEAN WITTER & CO"], False),
    ("L-3 COMMUNICATIONS HLDGS INC", ["JETBLUE AIRWAYS CORP"], False),
    ("LEVEL 3 COMMUNICATIONS INC NEW", ["EXPEDITORS INTERNATIONAL OF WASHINGTON INC"], False),
    ("Anything", [], False),
    # Abbreviations in Polygon's historical names.
    ("DEVELOPERS DIVERSIFIED RLTY CP", ["SITE Centers Corp.", "DEVELOPERS DIVERSIFIED REALTY CORP"], True),
    ("WHOLE FOODS MKT INC", ["WHOLE FOODS MARKET INC"], True),
    ("NOVELLUS SYS INC", ["NOVELLUS SYSTEMS INC"], True),
    ("Interpublic Group Cos", ["INTERPUBLIC GROUP OF COMPANIES, INC."], True),
])
def test_names_match_accepts_renames_and_rejects_wrong_ciks(old, sec_names, expected):
    assert tr.names_match(old, sec_names) is expected


def test_a_wrong_polygon_cik_is_rejected_as_name_mismatch(conn):
    _bars(conn, "SPY")
    _bars(conn, "MS")
    row = tr.resolve(conn, "MWW", "2015-01-01", "2015-03-31", {"name": "MONSTER WORLDWIDE INC", "cik": "895421"},
                     {895421: ["MS"]}, {895421: ["MORGAN STANLEY"]})
    assert row["status"] == "name_mismatch" and "new_ticker" not in row


def test_redecision_reuses_stored_polygon_listings(conn, tmp_path):
    _bars(conn, "SPY")
    _bars(conn, "NEW")
    _members(conn, [("OLD", "2015-01-01", "2015-03-31")])
    # First run stored a (wrong) match from before the name check existed.
    db.upsert_ticker_rename(conn, {"old_ticker": "OLD", "new_ticker": "NEW", "status": "matched",
                                   "cik": 42, "old_name": "Old Co", "lookup_date": "2015-02-14"})
    client = FakePolygon({})
    zip_path = _submissions(tmp_path, {42: ("Unrelated Industries", [])})

    tr.run(conn, client, {"NEW": 42}, zip_path, ["sp500"], "2009-01-01", refresh=True)

    assert client.calls == []
    assert tr.price_ticker_map(conn) == {}
    status = db.read_ticker_renames(conn, matched_only=False).set_index("old_ticker").loc["OLD", "status"]
    assert status == "name_mismatch"


def test_load_company_names_reads_current_and_former_names(tmp_path):
    zip_path = _submissions(tmp_path, {1326801: ("Meta Platforms, Inc.", ["FACEBOOK INC"])})
    names = tr.load_company_names(zip_path, {1326801, 7})
    assert names == {1326801: ["Meta Platforms, Inc.", "FACEBOOK INC"], 7: []}


def test_candidates_check_only_the_latest_membership_block(conn):
    _bars(conn, "SPY")
    # A reused symbol: one company 2001-2005, another 2012-2016 (plus a touching
    # Nasdaq-100 interval for the same holder).
    _members(conn, [("X", "2001-01-02", "2005-06-30"), ("X", "2012-03-01", "2015-12-31")])
    db.replace_index_membership(conn, "nasdaq100", pd.DataFrame(
        [("X", "2016-01-01", "2016-09-30")], columns=["ticker", "start_date", "end_date"]))

    row = tr.candidates(conn, ["sp500", "nasdaq100"], "2009-01-01").iloc[0]

    assert (row["valid_from"], row["valid_to"]) == ("2012-03-01", "2016-09-30")
    # The lookup date falls inside the latest block, never in the 2005-2012 gap.
    assert "2012-03-01" <= tr.lookup_date(row["start_date"], row["end_date"]) <= "2016-09-30"


def test_apply_renames_leaves_an_earlier_block_under_a_reused_symbol_alone(conn):
    db.upsert_ticker_rename(conn, {"old_ticker": "X", "new_ticker": "Y", "status": "matched",
                                   "valid_from": "2012-03-01", "valid_to": "2016-09-30"})
    membership = pd.DataFrame({"ticker": ["X", "X", "Z"],
                               "start_date": ["2001-01-02", "2012-03-01", "2001-01-02"],
                               "end_date": ["2005-06-30", "2015-12-31", None]})

    result = tr.apply_renames(conn, membership)

    assert list(result["ticker"]) == ["X", "Y", "Z"]


def test_a_rename_without_a_recorded_window_is_not_applied(conn):
    db.upsert_ticker_rename(conn, {"old_ticker": "X", "new_ticker": "Y", "status": "matched"})
    membership = pd.DataFrame({"ticker": ["X"], "start_date": ["2015-01-01"], "end_date": [None]})
    assert list(tr.apply_renames(conn, membership)["ticker"]) == ["X"]


class FailingPolygon(FakePolygon):
    def ticker_as_of(self, ticker, as_of):
        if ticker == "BBB":
            raise ConnectionError("rate limited")
        return super().ticker_as_of(ticker, as_of)


def test_an_interrupted_run_keeps_the_decisions_already_made(conn, tmp_path):
    _bars(conn, "SPY")
    _bars(conn, "NEW")
    _members(conn, [("AAA", "2015-01-01", "2015-03-31"), ("BBB", "2015-01-01", "2015-03-31")])
    client = FailingPolygon({"AAA": {"name": "Old Co", "cik": "42"}})
    zip_path = _submissions(tmp_path, {42: ("New Co", ["Old Co"])})

    with pytest.raises(ConnectionError):
        tr.run(conn, client, {"NEW": 42}, zip_path, ["sp500"], "2009-01-01")

    assert tr.price_ticker_map(conn) == {"AAA": "NEW"}
    stored = db.read_ticker_renames(conn).iloc[0]
    assert (stored["valid_from"], stored["valid_to"]) == ("2015-01-01", "2015-03-31")


def test_a_stored_listing_from_outside_the_window_is_looked_up_again(conn, tmp_path):
    _bars(conn, "SPY")
    _bars(conn, "NEW")
    _members(conn, [("OLD", "2015-01-01", "2015-03-31")])
    db.upsert_ticker_rename(conn, {"old_ticker": "OLD", "status": "name_mismatch", "cik": 7,
                                   "old_name": "Someone Else", "lookup_date": "2008-06-30"})
    client = FakePolygon({"OLD": {"name": "Old Co", "cik": "42"}})
    zip_path = _submissions(tmp_path, {42: ("New Co", ["Old Co"])})

    tr.run(conn, client, {"NEW": 42}, zip_path, ["sp500"], "2009-01-01", refresh=True)

    assert len(client.calls) == 1
    assert tr.price_ticker_map(conn) == {"OLD": "NEW"}


def test_create_tables_adds_the_window_columns_to_an_older_table():
    connection = db.get_connection(":memory:")
    connection.execute("""CREATE TABLE ticker_renames (old_ticker TEXT PRIMARY KEY, new_ticker TEXT,
        status TEXT NOT NULL, cik INTEGER, old_name TEXT, lookup_date TEXT, coverage REAL, detail TEXT,
        updated_at TEXT NOT NULL)""")
    db.create_tables(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(ticker_renames)")}
    assert {"valid_from", "valid_to"} <= columns
