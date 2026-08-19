import pandas as pd
import pytest

from src.market_common import derived_db
from src.relative_strength import store


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    store.create_relative_strength_tables(connection)
    yield connection
    connection.close()


def _rs(dates, tickers=("AAPL",), benchmark="SPY", rs_ratio=1.0) -> pd.DataFrame:
    rows = [
        {"ticker": t, "date": d, "benchmark": benchmark, "rs_ratio": rs_ratio, "rs_mansfield": 5.0, "rs_rating": 80.0}
        for t in tickers
        for d in dates
    ]
    return pd.DataFrame(rows)


def _sector_rs(dates, sectors=("Technology",), benchmark="SPY", rs_ratio=1.0) -> pd.DataFrame:
    rows = [
        {"sector": s, "date": d, "benchmark": benchmark, "rs_ratio": rs_ratio, "rs_mansfield": 5.0, "rs_rating": 80.0}
        for s in sectors
        for d in dates
    ]
    return pd.DataFrame(rows)


def test_upsert_and_read_relative_strength_roundtrip(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=3)
    store.upsert_relative_strength(derived_conn, "vs_market", _rs(dates), run_id="run-1")

    result = store.read_relative_strength(derived_conn, "AAPL", comparison="vs_market")

    assert len(result) == 3
    assert list(result["date"]) == [d.strftime("%Y-%m-%d") for d in dates]
    assert result.iloc[0]["benchmark"] == "SPY"
    assert result.iloc[0]["rs_rating"] == 80.0


def test_vs_market_and_vs_sector_do_not_collide_for_the_same_ticker_and_date(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    store.upsert_relative_strength(derived_conn, "vs_market", _rs(dates, rs_ratio=1.0), run_id="run-1")
    store.upsert_relative_strength(derived_conn, "vs_sector", _rs(dates, benchmark="XLK", rs_ratio=2.0), run_id="run-1")

    vs_market = store.read_relative_strength(derived_conn, "AAPL", comparison="vs_market")
    vs_sector = store.read_relative_strength(derived_conn, "AAPL", comparison="vs_sector")

    assert vs_market.iloc[0]["rs_ratio"] == 1.0
    assert vs_sector.iloc[0]["rs_ratio"] == 2.0
    assert vs_sector.iloc[0]["benchmark"] == "XLK"


def test_read_without_comparison_returns_both(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    store.upsert_relative_strength(derived_conn, "vs_market", _rs(dates), run_id="run-1")
    store.upsert_relative_strength(derived_conn, "vs_sector", _rs(dates, benchmark="XLK"), run_id="run-1")

    result = store.read_relative_strength(derived_conn, "AAPL")

    assert set(result["comparison"]) == {"vs_market", "vs_sector"}


def test_rerun_overwrites_existing_rows_not_duplicates(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_relative_strength(derived_conn, "vs_market", _rs(dates, rs_ratio=1.0), run_id="run-1")
    store.upsert_relative_strength(derived_conn, "vs_market", _rs(dates, rs_ratio=2.0), run_id="run-2")

    result = store.read_relative_strength(derived_conn, "AAPL", comparison="vs_market")

    assert len(result) == 2
    assert (result["rs_ratio"] == 2.0).all()
    assert (result["run_id"] == "run-2").all()


def test_upsert_relative_strength_ignores_an_empty_frame(derived_conn):
    store.upsert_relative_strength(derived_conn, "vs_market", pd.DataFrame(), run_id="run-1")

    result = store.read_relative_strength(derived_conn, "AAPL")
    assert result.empty


def test_upsert_relative_strength_raises_on_missing_expected_columns(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    incomplete = _rs(dates).drop(columns=["rs_mansfield"])

    with pytest.raises(ValueError, match="rs_mansfield"):
        store.upsert_relative_strength(derived_conn, "vs_market", incomplete, run_id="run-1")


def test_upsert_and_read_sector_relative_strength_roundtrip(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=3)
    store.upsert_sector_relative_strength(derived_conn, _sector_rs(dates), run_id="run-1")

    result = store.read_sector_relative_strength(derived_conn, "Technology")

    assert len(result) == 3
    assert result.iloc[0]["benchmark"] == "SPY"


def test_sector_rerun_overwrites_existing_rows_not_duplicates(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_sector_relative_strength(derived_conn, _sector_rs(dates, rs_ratio=1.0), run_id="run-1")
    store.upsert_sector_relative_strength(derived_conn, _sector_rs(dates, rs_ratio=2.0), run_id="run-2")

    result = store.read_sector_relative_strength(derived_conn, "Technology")

    assert len(result) == 2
    assert (result["rs_ratio"] == 2.0).all()


def test_different_sectors_do_not_collide(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    store.upsert_sector_relative_strength(derived_conn, _sector_rs(dates, sectors=("Technology",), rs_ratio=1.0), run_id="run-1")
    store.upsert_sector_relative_strength(derived_conn, _sector_rs(dates, sectors=("Energy",), rs_ratio=2.0), run_id="run-1")

    tech = store.read_sector_relative_strength(derived_conn, "Technology")
    energy = store.read_sector_relative_strength(derived_conn, "Energy")

    assert tech.iloc[0]["rs_ratio"] == 1.0
    assert energy.iloc[0]["rs_ratio"] == 2.0


def test_upsert_sector_relative_strength_ignores_an_empty_frame(derived_conn):
    store.upsert_sector_relative_strength(derived_conn, pd.DataFrame(), run_id="run-1")

    result = store.read_sector_relative_strength(derived_conn, "Technology")
    assert result.empty


def test_upsert_sector_relative_strength_raises_on_missing_expected_columns(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    incomplete = _sector_rs(dates).drop(columns=["rs_rating"])

    with pytest.raises(ValueError, match="rs_rating"):
        store.upsert_sector_relative_strength(derived_conn, incomplete, run_id="run-1")
