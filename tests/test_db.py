import pandas as pd
import pytest

from src.foundation.data_processing import db


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume, is_partial)"""
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_upsert_and_read_roundtrip(conn):
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),
            ("2024-01-02", 100.5, 103.0, 100.0, 102.0, 1500, 0),
        ]
    )
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, bars)

    result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.POLYGON)

    assert len(result) == 2
    assert result.iloc[0]["close"] == 100.5
    assert result.iloc[1]["close"] == 102.0
    assert "ticker" not in result.columns
    assert "source" not in result.columns


def test_upsert_replaces_existing_row_not_duplicates(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 1)]),
    )
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0, 105.0, 99.0, 104.0, 2000, 0)]),
    )

    result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.POLYGON)

    assert len(result) == 1
    assert result.iloc[0]["close"] == 104.0
    assert result.iloc[0]["is_partial"] == 0


def test_different_sources_do_not_collide(conn):
    # Same ticker, same date, different sources -- both rows should survive,
    # not overwrite each other, since source is part of the primary key.
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0)]),
    )
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.7, 1000, 0)]),
    )

    polygon_result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.POLYGON)
    yfinance_result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE)

    assert len(polygon_result) == 1
    assert len(yfinance_result) == 1
    assert polygon_result.iloc[0]["close"] == 100.5
    assert yfinance_result.iloc[0]["close"] == 100.7


def test_read_filters_by_ticker_and_date_range(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
    db.upsert_bars(conn, "bars_1d", "MSFT", db.POLYGON, _bars([("2024-01-01", 2, 2, 2, 2, 2, 0)]))
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, _bars([("2024-06-01", 1, 1, 1, 1, 1, 0)]))

    result = db.read_bars(
        conn, "bars_1d", ticker="AAPL", source=db.POLYGON, start="2024-02-01", end="2024-12-31"
    )

    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2024-06-01")


def test_read_without_ticker_includes_ticker_column(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
    db.upsert_bars(conn, "bars_1d", "MSFT", db.POLYGON, _bars([("2024-01-01", 2, 2, 2, 2, 2, 0)]))

    result = db.read_bars(conn, "bars_1d", source=db.POLYGON)

    assert set(result["ticker"]) == {"AAPL", "MSFT"}


def test_read_without_source_includes_source_column(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
    db.upsert_bars(conn, "bars_1d", "AAPL", db.YFINANCE, _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))

    result = db.read_bars(conn, "bars_1d", ticker="AAPL")

    assert set(result["source"]) == {db.POLYGON, db.YFINANCE}


def test_upsert_rejects_unknown_table(conn):
    with pytest.raises(ValueError):
        db.upsert_bars(
            conn, "not_a_table", "AAPL", db.POLYGON, _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)])
        )


def test_upsert_bars_drops_rows_with_close_outside_high_low_range(conn):
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),  # valid
            ("2024-01-02", 2575.0, 532.0, 532.0, 2380.0, 1000, 0),  # close/open way outside high/low
        ]
    )

    db.upsert_bars(conn, "bars_1d", "BMC", db.YFINANCE, bars)

    result = db.read_bars(conn, "bars_1d", ticker="BMC", source=db.YFINANCE)
    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2024-01-01")


def test_upsert_bars_drops_all_zero_ohlc_rows(conn):
    bars = _bars([("2024-01-01", 0.0, 0.0, 0.0, 0.0605, 1000, 0)])

    db.upsert_bars(conn, "bars_1d", "ADD", db.YFINANCE, bars)

    assert db.read_bars(conn, "bars_1d", ticker="ADD", source=db.YFINANCE).empty


def test_upsert_bars_drops_rows_with_nan_ohlc(conn):
    bars = _bars([("2024-01-01", float("nan"), 101.0, 99.0, 100.5, 1000, 0)])

    db.upsert_bars(conn, "bars_1d", "AAPL", db.POLYGON, bars)

    assert db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.POLYGON).empty


def test_upsert_bars_bulk_drops_only_the_invalid_rows(conn):
    bars = _multi_ticker_bars(
        [
            ("AAPL", "2024-01-01", 100, 101, 99, 100.5, 1000, 0),  # valid
            ("BMC", "2024-01-01", 2575.0, 532.0, 532.0, 2380.0, 1000, 0),  # invalid
        ]
    )

    db.upsert_bars_bulk(conn, "bars_1d", db.YFINANCE, bars)

    result = db.read_bars(conn, "bars_1d", source=db.YFINANCE)
    assert set(result["ticker"]) == {"AAPL"}


def _multi_ticker_bars(rows):
    """rows: list of (ticker, date_str, open, high, low, close, volume, is_partial)"""
    return pd.DataFrame(
        rows,
        columns=["ticker", "timestamp", "open", "high", "low", "close", "volume", "is_partial"],
    )


def test_upsert_bars_bulk_stores_many_tickers_in_one_call(conn):
    bars = _multi_ticker_bars(
        [
            ("AAPL", "2024-01-01", 100, 101, 99, 100.5, 1000, 0),
            ("MSFT", "2024-01-01", 200, 201, 199, 200.5, 2000, 0),
            ("SPY", "2024-01-01", 300, 301, 299, 300.5, 3000, 0),
        ]
    )

    db.upsert_bars_bulk(conn, "bars_1d", db.POLYGON, bars)

    result = db.read_bars(conn, "bars_1d", source=db.POLYGON)
    assert len(result) == 3
    assert set(result["ticker"]) == {"AAPL", "MSFT", "SPY"}


def test_upsert_bars_bulk_replaces_not_duplicates(conn):
    db.upsert_bars_bulk(
        conn, "bars_1d", db.POLYGON,
        _multi_ticker_bars([("AAPL", "2024-01-01", 100, 101, 99, 100.5, 1000, 1)]),
    )
    db.upsert_bars_bulk(
        conn, "bars_1d", db.POLYGON,
        _multi_ticker_bars([("AAPL", "2024-01-01", 100, 105, 99, 104.0, 2000, 0)]),
    )

    result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.POLYGON)
    assert len(result) == 1
    assert result.iloc[0]["close"] == 104.0


def _tickers_df(rows):
    """rows: list of (ticker, name, type, active, delisted_utc)"""
    return pd.DataFrame(rows, columns=["ticker", "name", "type", "active", "delisted_utc"])


def test_upsert_and_read_tickers_roundtrip(conn):
    tickers = _tickers_df(
        [
            ("AAPL", "Apple Inc.", "CS", True, None),
            ("AABA", "Altaba Inc.", "CS", False, "2019-10-07T04:00:00Z"),
        ]
    )

    db.upsert_tickers(conn, tickers)

    active_only = db.read_tickers(conn, type_="CS", active=True)
    assert list(active_only["ticker"]) == ["AAPL"]

    all_cs = db.read_tickers(conn, type_="CS")
    assert set(all_cs["ticker"]) == {"AAPL", "AABA"}
    delisted_row = all_cs[all_cs["ticker"] == "AABA"].iloc[0]
    assert delisted_row["delisted_utc"] == "2019-10-07T04:00:00Z"


def test_upsert_tickers_replaces_existing_row(conn):
    db.upsert_tickers(conn, _tickers_df([("AAPL", "Apple Inc.", "CS", True, None)]))
    db.upsert_tickers(conn, _tickers_df([("AAPL", "Apple Inc.", "CS", False, "2030-01-01T00:00:00Z")]))

    result = db.read_tickers(conn)
    assert len(result) == 1
    assert result.iloc[0]["active"] == 0
    assert result.iloc[0]["delisted_utc"] == "2030-01-01T00:00:00Z"


def test_pending_keys_excludes_only_successful_ones(conn):
    db.record_job_result(conn, "polygon_grouped_daily", "2024-01-01", "success")
    db.record_job_result(conn, "polygon_grouped_daily", "2024-01-02", "failed", "boom")

    pending = db.pending_keys(
        conn, "polygon_grouped_daily", ["2024-01-01", "2024-01-02", "2024-01-03"]
    )

    # 01-01 succeeded (excluded), 01-02 failed (still pending), 01-03 never attempted (pending)
    assert pending == ["2024-01-02", "2024-01-03"]


def _metadata_df(rows):
    """rows: list of (ticker, market_cap, sic_code, sic_description,
    shares_outstanding, weighted_shares_outstanding, employees, exchange, list_date)"""
    return pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "market_cap",
            "sic_code",
            "sic_description",
            "share_class_shares_outstanding",
            "weighted_shares_outstanding",
            "total_employees",
            "primary_exchange",
            "list_date",
        ],
    )


def test_upsert_and_read_ticker_metadata_roundtrip(conn):
    metadata = _metadata_df(
        [
            ("AAPL", 4_891_183_295_120.0, "3571", "ELECTRONIC COMPUTERS", 1.5e10, 1.51e10, 164000, "XNAS", "1980-12-12"),
        ]
    )

    db.upsert_ticker_metadata(conn, metadata)

    result = db.read_ticker_metadata(conn, ticker="AAPL")
    assert len(result) == 1
    assert result.iloc[0]["market_cap"] == 4_891_183_295_120.0
    assert result.iloc[0]["sic_description"] == "ELECTRONIC COMPUTERS"


def test_upsert_ticker_metadata_replaces_existing_row(conn):
    db.upsert_ticker_metadata(
        conn, _metadata_df([("AAPL", 100.0, "3571", "ELECTRONIC COMPUTERS", 10, 10, 100, "XNAS", "1980-12-12")])
    )
    db.upsert_ticker_metadata(
        conn, _metadata_df([("AAPL", 200.0, "3571", "ELECTRONIC COMPUTERS", 20, 20, 200, "XNAS", "1980-12-12")])
    )

    result = db.read_ticker_metadata(conn, ticker="AAPL")
    assert len(result) == 1
    assert result.iloc[0]["market_cap"] == 200.0


def test_upsert_ticker_metadata_handles_missing_values(conn):
    metadata = _metadata_df([("XYZ", None, None, None, None, None, None, None, None)])

    db.upsert_ticker_metadata(conn, metadata)

    result = db.read_ticker_metadata(conn, ticker="XYZ")
    assert len(result) == 1
    assert pd.isna(result.iloc[0]["market_cap"])


def test_read_ticker_metadata_without_ticker_returns_all_rows(conn):
    db.upsert_ticker_metadata(
        conn,
        _metadata_df(
            [
                ("AAPL", 100.0, "3571", "ELECTRONIC COMPUTERS", 10, 10, 100, "XNAS", "1980-12-12"),
                ("MSFT", 200.0, "7372", "SERVICES-PREPACKAGED SOFTWARE", 20, 20, 200, "XNAS", "1986-03-13"),
            ]
        ),
    )

    result = db.read_ticker_metadata(conn)
    assert set(result["ticker"]) == {"AAPL", "MSFT"}


def _sector_df(rows):
    """rows: list of (ticker, sector, industry)"""
    return pd.DataFrame(rows, columns=["ticker", "sector", "industry"])


def test_upsert_and_read_ticker_sector_roundtrip(conn):
    db.upsert_ticker_sector(conn, _sector_df([("AAPL", "Technology", "Consumer Electronics")]))

    result = db.read_ticker_sector(conn, ticker="AAPL")
    assert len(result) == 1
    assert result.iloc[0]["sector"] == "Technology"
    assert result.iloc[0]["industry"] == "Consumer Electronics"


def test_upsert_ticker_sector_replaces_existing_row(conn):
    db.upsert_ticker_sector(conn, _sector_df([("AAPL", "Technology", "Consumer Electronics")]))
    db.upsert_ticker_sector(conn, _sector_df([("AAPL", "Technology", "Consumer Electronics Revised")]))

    result = db.read_ticker_sector(conn, ticker="AAPL")
    assert len(result) == 1
    assert result.iloc[0]["industry"] == "Consumer Electronics Revised"


def test_read_ticker_sector_without_ticker_returns_all_rows(conn):
    db.upsert_ticker_sector(
        conn,
        _sector_df(
            [
                ("AAPL", "Technology", "Consumer Electronics"),
                ("JPM", "Financial Services", "Banks - Diversified"),
            ]
        ),
    )

    result = db.read_ticker_sector(conn)
    assert set(result["ticker"]) == {"AAPL", "JPM"}


def _shares(rows):
    """rows: list of (date_str, shares_outstanding)"""
    dates = pd.to_datetime([r[0] for r in rows])
    return pd.Series([r[1] for r in rows], index=dates, name="shares_outstanding")


def test_upsert_and_read_shares_outstanding_roundtrip(conn):
    db.upsert_shares_outstanding(
        conn, "AAPL", db.YFINANCE,
        _shares([("2020-01-01", 4_600_000_000), ("2020-06-01", 4_500_000_000)]),
    )

    result = db.read_shares_outstanding(conn, "AAPL", db.YFINANCE)

    assert len(result) == 2
    assert list(result["date"]) == ["2020-01-01", "2020-06-01"]
    assert result.iloc[0]["shares_outstanding"] == 4_600_000_000
    assert result.iloc[1]["shares_outstanding"] == 4_500_000_000


def test_upsert_shares_outstanding_replaces_existing_date_not_duplicates(conn):
    db.upsert_shares_outstanding(conn, "AAPL", db.YFINANCE, _shares([("2020-01-01", 4_600_000_000)]))
    db.upsert_shares_outstanding(conn, "AAPL", db.YFINANCE, _shares([("2020-01-01", 4_275_630_080)]))

    result = db.read_shares_outstanding(conn, "AAPL", db.YFINANCE)

    assert len(result) == 1
    assert result.iloc[0]["shares_outstanding"] == 4_275_630_080


def test_shares_outstanding_different_sources_do_not_collide(conn):
    db.upsert_shares_outstanding(conn, "AAPL", db.YFINANCE, _shares([("2020-01-01", 4_600_000_000)]))
    db.upsert_shares_outstanding(conn, "AAPL", db.POLYGON, _shares([("2020-01-01", 4_601_000_000)]))

    yf_result = db.read_shares_outstanding(conn, "AAPL", db.YFINANCE)
    polygon_result = db.read_shares_outstanding(conn, "AAPL", db.POLYGON)

    assert yf_result.iloc[0]["shares_outstanding"] == 4_600_000_000
    assert polygon_result.iloc[0]["shares_outstanding"] == 4_601_000_000


def test_upsert_shares_outstanding_ignores_an_empty_series(conn):
    db.upsert_shares_outstanding(conn, "AAPL", db.YFINANCE, pd.Series(dtype="float64"))

    result = db.read_shares_outstanding(conn, "AAPL", db.YFINANCE)
    assert result.empty


def _macro_values(rows):
    """rows: list of (date_str, value)"""
    dates = pd.to_datetime([r[0] for r in rows])
    return pd.Series([r[1] for r in rows], index=dates, name="value")


def test_upsert_and_read_macro_series_roundtrip(conn):
    db.upsert_macro_series(
        conn, "M2SL", db.FRED,
        _macro_values([("2024-01-01", 20800.5), ("2024-02-01", 20900.1)]),
    )

    result = db.read_macro_series(conn, "M2SL", db.FRED)

    assert len(result) == 2
    assert list(result["date"]) == ["2024-01-01", "2024-02-01"]
    assert result.iloc[0]["value"] == 20800.5
    assert result.iloc[1]["value"] == 20900.1


def test_upsert_macro_series_replaces_existing_date_not_duplicates(conn):
    db.upsert_macro_series(conn, "M2SL", db.FRED, _macro_values([("2024-01-01", 20800.5)]))
    db.upsert_macro_series(conn, "M2SL", db.FRED, _macro_values([("2024-01-01", 20805.2)]))

    result = db.read_macro_series(conn, "M2SL", db.FRED)

    assert len(result) == 1
    assert result.iloc[0]["value"] == 20805.2


def test_macro_series_different_series_ids_do_not_collide(conn):
    db.upsert_macro_series(conn, "M2SL", db.FRED, _macro_values([("2024-01-01", 20800.5)]))
    db.upsert_macro_series(conn, "DGS10", db.FRED, _macro_values([("2024-01-01", 4.02)]))

    m2 = db.read_macro_series(conn, "M2SL", db.FRED)
    dgs10 = db.read_macro_series(conn, "DGS10", db.FRED)

    assert m2.iloc[0]["value"] == 20800.5
    assert dgs10.iloc[0]["value"] == 4.02


def test_upsert_macro_series_ignores_an_empty_series(conn):
    db.upsert_macro_series(conn, "M2SL", db.FRED, pd.Series(dtype="float64"))

    result = db.read_macro_series(conn, "M2SL", db.FRED)
    assert result.empty


def test_upsert_macro_series_without_publication_leaves_new_columns_null(conn):
    db.upsert_macro_series(conn, "M2SL", db.FRED, _macro_values([("2024-01-01", 20800.5)]))

    result = db.read_macro_series(conn, "M2SL", db.FRED)

    assert pd.isna(result.iloc[0]["published_at"])
    assert pd.isna(result.iloc[0]["first_published_value"])


def test_upsert_macro_series_stores_publication_pair(conn):
    values = _macro_values([("2024-01-01", 20800.5), ("2024-02-01", 20900.1)])
    publication = pd.DataFrame(
        {"published_at": ["2024-01-10", "2024-02-12"], "first_published_value": [20790.0, 20895.0]},
        index=values.index,
    )

    db.upsert_macro_series(conn, "M2SL", db.FRED, values, publication=publication)

    result = db.read_macro_series(conn, "M2SL", db.FRED)
    assert list(result["published_at"]) == ["2024-01-10", "2024-02-12"]
    assert list(result["first_published_value"]) == [20790.0, 20895.0]
    # value (latest-known) is untouched by publication -- distinct meaning.
    assert list(result["value"]) == [20800.5, 20900.1]


def test_upsert_macro_series_publication_partially_covering_values_leaves_the_rest_null(conn):
    # publication need not cover every date `values` does -- e.g. a
    # first-release query returned a narrower window than the plain pull.
    values = _macro_values([("2024-01-01", 20800.5), ("2024-02-01", 20900.1)])
    publication = pd.DataFrame(
        {"published_at": ["2024-01-10"], "first_published_value": [20790.0]},
        index=pd.to_datetime(["2024-01-01"]),
    )

    db.upsert_macro_series(conn, "M2SL", db.FRED, values, publication=publication)

    result = db.read_macro_series(conn, "M2SL", db.FRED)
    assert result.iloc[0]["published_at"] == "2024-01-10"
    assert pd.isna(result.iloc[1]["published_at"])
    assert pd.isna(result.iloc[1]["first_published_value"])


def _membership_df(rows):
    """rows: list of (ticker, start_date, end_date)"""
    return pd.DataFrame(rows, columns=["ticker", "start_date", "end_date"])


def test_replace_index_membership_and_read_all(conn):
    membership = _membership_df(
        [
            ("AAPL", "1996-01-02", None),
            ("AABA", "1999-12-08", "2017-06-19"),
        ]
    )

    db.replace_index_membership(conn, "sp500", membership)

    result = db.read_index_membership(conn, "sp500")
    assert len(result) == 2
    assert set(result["ticker"]) == {"AAPL", "AABA"}


def test_read_index_membership_as_of_filters_to_current_members(conn):
    membership = _membership_df(
        [
            ("AAPL", "1996-01-02", None),  # still a member
            ("AABA", "1999-12-08", "2017-06-19"),  # left before as_of
            ("ABNB", "2023-09-18", None),  # joined after as_of
        ]
    )
    db.replace_index_membership(conn, "sp500", membership)

    result = db.read_index_membership(conn, "sp500", as_of="2020-01-01")

    assert set(result["ticker"]) == {"AAPL"}


def test_replace_index_membership_is_a_full_replace_not_an_upsert(conn):
    db.replace_index_membership(
        conn, "sp500", _membership_df([("AAPL", "1996-01-02", None), ("AABA", "1999-12-08", "2017-06-19")])
    )
    # Simulate a corrected re-download that no longer includes AABA at all.
    db.replace_index_membership(conn, "sp500", _membership_df([("AAPL", "1996-01-02", None)]))

    result = db.read_index_membership(conn, "sp500")
    assert set(result["ticker"]) == {"AAPL"}


def test_replace_index_membership_scoped_per_index_name(conn):
    db.replace_index_membership(conn, "sp500", _membership_df([("AAPL", "1996-01-02", None)]))
    db.replace_index_membership(conn, "nasdaq100", _membership_df([("MSFT", "2000-01-01", None)]))

    sp500 = db.read_index_membership(conn, "sp500")
    nasdaq100 = db.read_index_membership(conn, "nasdaq100")
    assert set(sp500["ticker"]) == {"AAPL"}
    assert set(nasdaq100["ticker"]) == {"MSFT"}


def test_record_job_result_accumulates_attempts(conn):
    db.record_job_result(conn, "yfinance_daily", "AAPL", "failed", "first failure")
    db.record_job_result(conn, "yfinance_daily", "AAPL", "success")

    row = conn.execute(
        "SELECT attempts, status FROM fetch_jobs WHERE job_type = ? AND key = ?",
        ("yfinance_daily", "AAPL"),
    ).fetchone()

    assert row == (2, "success")


def _splits_df(rows):
    """rows: list of (execution_date, split_from, split_to, ratio)"""
    return pd.DataFrame(
        {
            "execution_date": pd.to_datetime([r[0] for r in rows]),
            "split_from": [r[1] for r in rows], "split_to": [r[2] for r in rows], "ratio": [r[3] for r in rows],
        }
    )


def test_upsert_and_read_splits_roundtrip(conn):
    db.upsert_splits(conn, "AAPL", db.POLYGON, _splits_df([("2020-08-31", 1.0, 4.0, 4.0)]))

    result = db.read_splits(conn, "AAPL", db.POLYGON)

    assert len(result) == 1
    assert result.iloc[0]["execution_date"] == pd.Timestamp("2020-08-31")
    assert result.iloc[0]["split_from"] == 1.0
    assert result.iloc[0]["split_to"] == 4.0
    assert result.iloc[0]["ratio"] == 4.0


def test_upsert_splits_replaces_existing_execution_date_not_duplicates(conn):
    db.upsert_splits(conn, "AAPL", db.POLYGON, _splits_df([("2020-08-31", 1.0, 4.0, 4.0)]))
    db.upsert_splits(conn, "AAPL", db.POLYGON, _splits_df([("2020-08-31", 1.0, 4.0, 4.0)]))

    result = db.read_splits(conn, "AAPL", db.POLYGON)
    assert len(result) == 1


def test_splits_different_tickers_do_not_collide(conn):
    db.upsert_splits(conn, "AAPL", db.POLYGON, _splits_df([("2020-08-31", 1.0, 4.0, 4.0)]))
    db.upsert_splits(conn, "TSLA", db.POLYGON, _splits_df([("2020-08-31", 1.0, 5.0, 5.0)]))

    aapl = db.read_splits(conn, "AAPL", db.POLYGON)
    tsla = db.read_splits(conn, "TSLA", db.POLYGON)

    assert aapl.iloc[0]["ratio"] == 4.0
    assert tsla.iloc[0]["ratio"] == 5.0


def test_upsert_splits_ignores_an_empty_frame(conn):
    db.upsert_splits(conn, "AAPL", db.POLYGON, pd.DataFrame(columns=["execution_date", "split_from", "split_to", "ratio"]))

    result = db.read_splits(conn, "AAPL", db.POLYGON)
    assert result.empty


def test_read_index_universe_tickers_dedups_across_indices_and_sorts(conn):
    db.replace_index_membership(conn, "sp500", _membership_df([("AAPL", "1996-01-02", None), ("MSFT", "1996-01-02", None)]))
    db.replace_index_membership(conn, "nasdaq100", _membership_df([("MSFT", "2000-01-01", None), ("GOOGL", "2000-01-01", None)]))

    result = db.read_index_universe_tickers(conn, ["sp500", "nasdaq100"])

    assert result == ["AAPL", "GOOGL", "MSFT"]


def test_read_index_universe_tickers_includes_past_non_current_members(conn):
    # A ticker that left the index years ago must still appear -- this
    # feeds bulk backfill scripts that need the *all-time* universe, not
    # today's roster.
    db.replace_index_membership(conn, "sp500", _membership_df([("AABA", "1999-12-08", "2017-06-19")]))

    result = db.read_index_universe_tickers(conn, ["sp500"])

    assert result == ["AABA"]


def test_read_index_universe_tickers_empty_index_list_returns_empty(conn):
    assert db.read_index_universe_tickers(conn, []) == []
