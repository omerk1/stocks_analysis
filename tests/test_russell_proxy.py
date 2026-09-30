import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing import russell_proxy as rp


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


@pytest.fixture
def small_counts(monkeypatch):
    # 2 large caps, 2 more small caps -- the real 1,000 / 3,000 split scaled down.
    monkeypatch.setattr(rp, "LARGE_CAP_COUNT", 2)
    monkeypatch.setattr(rp, "TOTAL_COUNT", 4)


def _add_stock(conn, ticker, close, shares, share_date="2019-01-15", type_="CS", bar_days=None):
    db.upsert_tickers(conn, pd.DataFrame(
        {"ticker": [ticker], "name": [ticker], "type": [type_], "active": [1], "delisted_utc": [None]}
    ))
    days = bar_days if bar_days is not None else pd.bdate_range("2019-04-22", "2019-04-30")
    bars = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000, "is_partial": 0},
        index=pd.DatetimeIndex(days, name="timestamp"),
    )
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, bars)
    if shares is not None:
        db.upsert_shares_outstanding(
            conn, ticker, db.SEC_EDGAR, pd.Series([shares], index=[pd.Timestamp(share_date)], name="shares_outstanding")
        )


def test_reconstitution_day_is_the_weekday_after_the_fourth_friday_of_june():
    # June 2019: Fridays 7, 14, 21, 28 -> Monday July 1.
    assert rp.reconstitution_day(2019) == pd.Timestamp("2019-07-01")
    # June 2021: Fridays 4, 11, 18, 25 -> Monday June 28.
    assert rp.reconstitution_day(2021) == pd.Timestamp("2021-06-28")


def test_rank_day_caps_uses_price_times_shares_and_applies_the_price_and_type_floors(conn):
    _add_stock(conn, "AAA", 10.0, 1_000)
    _add_stock(conn, "PENNY", 0.5, 1_000_000)        # under the $1 floor
    _add_stock(conn, "FUND", 50.0, 1_000, type_="ETF")  # not common stock
    _add_stock(conn, "NOSHR", 20.0, None)            # no share count at all

    caps = rp.rank_day_caps(conn, [rp.rank_day(2019)])

    assert list(caps["ticker"]) == ["AAA"]
    assert caps["market_cap"].iloc[0] == pytest.approx(10_000)


def test_rank_day_caps_ignores_a_share_count_filed_after_the_rank_day(conn):
    _add_stock(conn, "LATE", 10.0, 1_000, share_date="2019-05-15")

    assert rp.rank_day_caps(conn, [rp.rank_day(2019)]).empty


def test_rank_day_caps_skips_a_ticker_whose_last_close_is_stale(conn):
    _add_stock(conn, "OLD", 10.0, 1_000, bar_days=pd.bdate_range("2019-04-01", "2019-04-12"))

    assert rp.rank_day_caps(conn, [rp.rank_day(2019)]).empty


def test_rank_day_caps_undoes_split_adjustment_before_multiplying_by_raw_shares(conn):
    # A 2-for-1 split after the rank day: the stored (split-adjusted) close is
    # half the real one, the raw pre-split share count is real -- the true cap
    # is 2 x stored close x shares.
    _add_stock(conn, "SPL", 10.0, 1_000)
    db.upsert_splits(conn, "SPL", db.YFINANCE, pd.DataFrame(
        {"execution_date": [pd.Timestamp("2019-08-01")], "split_from": [1.0], "split_to": [2.0], "ratio": [2.0]}
    ))

    caps = rp.rank_day_caps(conn, [rp.rank_day(2019)])

    assert caps["market_cap"].iloc[0] == pytest.approx(20_000)


def test_rank_year_splits_large_and_small_caps_and_drops_the_rest(small_counts):
    caps = pd.DataFrame({"ticker": list("ABCDE"), "close": 1.0, "market_cap": [50, 40, 30, 20, 10]})

    ranked = rp.rank_year(caps)

    assert list(ranked["ticker"]) == list("ABCD")
    assert list(ranked["index_name"]) == [rp.R1000, rp.R1000, rp.R2000, rp.R2000]


def test_membership_intervals_merge_consecutive_years_and_leave_the_latest_open(small_counts):
    y2019 = rp.rank_year(pd.DataFrame({"ticker": list("ABCD"), "close": 1.0, "market_cap": [50, 40, 30, 20]}))
    # 2020: C grows into the large caps, B drops to small caps, D falls out.
    y2020 = rp.rank_year(pd.DataFrame({"ticker": list("ACBE"), "close": 1.0, "market_cap": [60, 55, 30, 25]}))

    result = rp.membership_intervals({2019: y2019, 2020: y2020})

    r1000 = result[rp.R1000].set_index("ticker")
    assert r1000.loc["A", "start_date"] == "2019-07-01" and pd.isna(r1000.loc["A", "end_date"])
    assert r1000.loc["B", "end_date"] == "2020-06-28"          # day before 2020's reconstitution
    assert r1000.loc["C", "start_date"] == "2020-06-29"
    r3000 = result[rp.R3000].set_index("ticker")
    assert r3000.loc["B", "start_date"] == "2019-07-01" and pd.isna(r3000.loc["B", "end_date"])  # merged across the move
    assert r3000.loc["D", "end_date"] == "2020-06-28"
    assert "D" not in set(result[rp.R2000][result[rp.R2000]["end_date"].isna()]["ticker"])


def test_build_end_to_end_is_readable_point_in_time(conn, small_counts):
    for ticker, close in [("AAA", 40.0), ("BBB", 30.0), ("CCC", 20.0), ("DDD", 10.0), ("EEE", 5.0)]:
        _add_stock(conn, ticker, close, 1_000)

    membership, summary = rp.build(conn, 2019, 2019)
    for name, frame in membership.items():
        db.replace_index_membership(conn, name, frame)

    assert summary["eligible"].iloc[0] == 5
    assert set(db.read_index_membership(conn, rp.R1000, as_of="2019-08-01")["ticker"]) == {"AAA", "BBB"}
    assert set(db.read_index_membership(conn, rp.R2000, as_of="2019-08-01")["ticker"]) == {"CCC", "DDD"}
    assert db.read_index_membership(conn, rp.R1000, as_of="2019-06-01").empty


def test_rank_day_caps_across_years_uses_each_years_own_share_count(conn):
    days = list(pd.bdate_range("2019-04-22", "2019-04-30")) + list(pd.bdate_range("2020-04-22", "2020-04-30"))
    _add_stock(conn, "AAA", 10.0, 1_000, bar_days=days)
    db.upsert_shares_outstanding(
        conn, "AAA", db.SEC_EDGAR, pd.Series([3_000], index=[pd.Timestamp("2020-01-15")], name="shares_outstanding")
    )

    caps = rp.rank_day_caps(conn, [rp.rank_day(2019), rp.rank_day(2020)]).set_index("rank_day")

    assert caps.loc[rp.rank_day(2019), "market_cap"] == pytest.approx(10_000)
    assert caps.loc[rp.rank_day(2020), "market_cap"] == pytest.approx(30_000)
