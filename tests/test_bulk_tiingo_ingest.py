import pandas as pd
import pytest

from src.foundation.data_processing import bulk_tiingo_ingest as ti
from src.foundation.data_processing import db
from src.foundation.data_processing.tiingo_client import to_bars

_DAYS = pd.bdate_range("2015-01-01", "2015-03-31")


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _spy(conn, days=_DAYS):
    frame = pd.DataFrame(
        {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000, "is_partial": 0},
        index=pd.DatetimeIndex(days, name="timestamp"),
    )
    db.upsert_bars(conn, "bars_1d", "SPY", db.YFINANCE, frame)


def _prices(days=_DAYS, close=100.0, split_on=None, split=2.0, zero_volume_last=False):
    """Tiingo-shaped rows; `split_on` puts a `split`:1 split on that ex-date."""
    frame = pd.DataFrame(index=pd.DatetimeIndex(days, name="timestamp"))
    factor = pd.Series(1.0, index=frame.index)
    if split_on is not None:
        factor[pd.Timestamp(split_on)] = split
    raw = pd.Series(close, index=frame.index)
    if split_on is not None:
        raw[frame.index >= pd.Timestamp(split_on)] = close / split
    later = factor[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    for col in ("open", "high", "low", "close"):
        frame[col] = raw
        frame["adj" + col.capitalize()] = raw / later * 0.98  # a dividend shaves 2% off history
    frame["volume"] = 1000.0
    frame["adjVolume"] = 1000.0 * later
    frame["divCash"] = 0.0
    frame["splitFactor"] = factor
    if zero_volume_last:
        frame.iloc[-1, frame.columns.get_loc("volume")] = 0.0
    return frame


class FakeTiingo:
    def __init__(self, meta, prices):
        self.meta, self.prices, self.calls = meta, prices, []

    def metadata(self, ticker):
        self.calls.append(("meta", ticker))
        return self.meta.get(ticker)

    def daily_prices(self, ticker, start, end):
        self.calls.append(("prices", ticker))
        return self.prices.get(ticker)


def _listings(rows):
    return pd.DataFrame(rows, columns=["ticker", "exchange", "assetType", "priceCurrency", "startDate", "endDate"])


def _target(conn, ticker, name, valid_from="2014-06-01", valid_to="2015-03-31", status="no_current_ticker"):
    db.upsert_ticker_rename(conn, {"old_ticker": ticker, "status": status, "old_name": name,
                                   "valid_from": valid_from, "valid_to": valid_to})


def test_split_only_divides_by_later_splits_and_adjusted_uses_tiingo_adjustment():
    prices = _prices(split_on="2015-02-02")

    traded = to_bars(prices, split_only=True)
    total = to_bars(prices, split_only=False)

    # before the 2:1 split: raw 100 on the old share basis -> 50 on today's
    assert traded.loc["2015-01-30", "close"] == pytest.approx(50.0)
    assert traded.loc["2015-01-30", "volume"] == pytest.approx(2000.0)
    assert traded.loc["2015-02-02", "close"] == pytest.approx(50.0)
    assert total.loc["2015-01-30", "close"] == pytest.approx(49.0)
    assert list(traded.columns) == ["open", "high", "low", "close", "volume", "is_partial"]


def test_zero_volume_placeholder_bars_are_dropped():
    prices = _prices(zero_volume_last=True)

    assert to_bars(prices, split_only=True).index[-1] == _DAYS[-2]
    assert to_bars(prices, split_only=False).index[-1] == _DAYS[-2]


def test_targets_are_unmapped_members_without_yfinance_bars(conn):
    _target(conn, "OLD", "Old Co")
    _target(conn, "MAPPED", "Mapped Co", status="matched")
    _target(conn, "EARLY", "Early Co", valid_from="2001-01-01", valid_to="2005-01-01")

    assert list(ti.targets(conn, "2009-01-01")["ticker"]) == ["OLD"]


def test_check_listing_only_accepts_the_latest_listing():
    listings = _listings([
        ("EMC", "NYSE", "Stock", "USD", "1988-12-16", "2016-09-15"),
        ("EMC", "NYSE", "ETF", "USD", "2023-05-15", "2026-10-02"),
        ("FRX", "NYSE", "Stock", "USD", "1988-04-19", "2014-07-01"),
        ("FRX-U", "NYSE", "Stock", "USD", "2020-11-25", "2021-06-25"),
        ("GONE", "NYSE", "Stock", "USD", "1990-01-01", "2005-01-01"),
    ])

    assert ti.check_listing(listings, "FRX", "2009-01-01", "2014-07-01")[0] is None
    assert ti.check_listing(listings, "EMC", "2009-01-01", "2016-09-07")[0] == "symbol_reused"
    assert ti.check_listing(listings, "GONE", "2009-01-01", "2012-01-01")[0] == "not_in_tiingo"
    assert ti.check_listing(listings, "NOPE", "2009-01-01", "2012-01-01")[0] == "not_in_tiingo"


def test_run_stores_both_bases_for_a_verified_listing(conn):
    _spy(conn)
    _target(conn, "FRX", "FOREST LABORATORIES INC")
    listings = _listings([("FRX", "NYSE", "Stock", "USD", "1988-04-19", "2015-03-31")])
    client = FakeTiingo({"FRX": {"name": "Forest Laboratories Inc", "startDate": "1988-04-19",
                                 "endDate": "2015-03-31"}}, {"FRX": _prices()})

    table = ti.run(conn, client, listings, "2009-01-01")

    row = table.set_index("ticker").loc["FRX"]
    assert row["status"] == "stored" and row["coverage"] == pytest.approx(1.0)
    for source in (db.TIINGO, db.TIINGO_SPLIT_ONLY):
        assert len(db.read_bars(conn, "bars_1d", ticker="FRX", source=source)) == len(_DAYS)


def test_run_rejects_other_company_partial_history_and_skips_decided(conn):
    _spy(conn)
    _target(conn, "BBT", "BB&T CORP")
    _target(conn, "PART", "Part Co")
    listings = _listings([
        ("BBT", "NYSE", "Stock", "USD", "2000-06-28", "2026-10-02"),
        ("PART", "NYSE", "Stock", "USD", "2015-03-01", "2015-03-31"),
    ])
    client = FakeTiingo(
        {"BBT": {"name": "Beacon Financial Corp"}, "PART": {"name": "Part Co Inc"}},
        {"PART": _prices(days=_DAYS[-20:])},
    )

    table = ti.run(conn, client, listings, "2009-01-01").set_index("ticker")

    assert table.loc["BBT", "status"] == "name_mismatch"
    assert table.loc["PART", "status"] == "low_coverage"
    assert ("prices", "BBT") not in client.calls
    assert db.read_bars(conn, "bars_1d", source=db.TIINGO).empty

    calls = len(client.calls)
    ti.run(conn, client, listings, "2009-01-01")
    assert len(client.calls) == calls


def test_request_failure_is_left_for_the_next_run(conn):
    import requests

    _target(conn, "FLAKY", "Flaky Co")
    listings = _listings([("FLAKY", "NYSE", "Stock", "USD", "2010-01-01", "2015-03-31")])

    class Failing(FakeTiingo):
        def metadata(self, ticker):
            raise requests.ConnectionError("boom")

    table = ti.run(conn, Failing({}, {}), listings, "2009-01-01")

    assert table.empty


def test_client_waits_out_a_429_and_retries():
    from src.foundation.data_processing.tiingo_client import TiingoClient

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"name": "Ok Co"}

    class Session:
        def __init__(self):
            self.statuses = [429, 429, 200]

        def get(self, *args, **kwargs):
            return Response(self.statuses.pop(0))

    session = Session()
    client = TiingoClient(api_key="x", session=session, rate_limited_wait_seconds=0)

    assert client.metadata("OK") == {"name": "Ok Co"}
    assert session.statuses == []


@pytest.mark.parametrize("tiingo_name, ref_name, expected", [
    ("Avalonbay Communities Inc", "Avalon Bay Communities", True),
    ("Arm Holdings plc.", "Arm Holdings plc American Depositary Shares", True),
    ("Forest Laboratories Inc", "FOREST LABORATORIES INC", True),
    ("Beacon Financial Corp", "BB&T CORP", False),
    ("AB CALIFORNIA INTERMEDIATE MUNICIPAL ETF ", "CAMERON INTERNATIONAL CORPORATION", False),
    (None, "Old Co", False),
])
def test_same_company(tiingo_name, ref_name, expected):
    assert ti.same_company(tiingo_name, ref_name) is expected


def test_retry_status_redecides_only_those_rows(conn):
    _spy(conn)
    _target(conn, "AVB", "Avalon Bay Communities")
    _target(conn, "GONE", "Gone Co")
    db.upsert_tiingo_listing(conn, {"ticker": "AVB", "status": "name_mismatch"})
    db.upsert_tiingo_listing(conn, {"ticker": "GONE", "status": "not_in_tiingo"})
    listings = _listings([("AVB", "NYSE", "Stock", "USD", "1994-03-11", "2015-03-31")])
    client = FakeTiingo({"AVB": {"name": "Avalonbay Communities Inc"}}, {"AVB": _prices()})

    table = ti.run(conn, client, listings, "2009-01-01", retry_statuses=["name_mismatch"]).set_index("ticker")

    assert table.loc["AVB", "status"] == "stored"
    assert table.loc["GONE", "status"] == "not_in_tiingo"
