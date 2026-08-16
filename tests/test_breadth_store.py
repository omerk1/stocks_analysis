import numpy as np
import pandas as pd
import pytest

from src.breadth import store
from src.market_common import derived_db


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    store.create_breadth_table(connection)
    yield connection
    connection.close()


def _breadth(dates, pct_above_sma50=0.5) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "n_constituents": [500] * n, "n_with_data": [498] * n,
            "pct_above_sma50": [pct_above_sma50] * n, "pct_above_sma200": [0.6] * n,
            "pct_above_ema8": [0.55] * n, "pct_above_ema21": [0.52] * n,
            "pct_golden_cross": [0.7] * n,
            "n_advancing": [300] * n, "n_declining": [198] * n, "net_advances": [102] * n,
            "ad_ratio": [np.nan] * n,
        },
        index=dates,
    )


def test_upsert_and_read_breadth_roundtrip(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=3)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates), run_id="run-1")

    result = store.read_breadth(derived_conn, "sp500")

    assert len(result) == 3
    assert list(result["date"]) == [d.strftime("%Y-%m-%d") for d in dates]
    assert result.iloc[0]["n_constituents"] == 500
    assert result.iloc[0]["pct_above_sma50"] == 0.5
    assert pd.isna(result.iloc[0]["ad_ratio"])


def test_rerun_overwrites_existing_rows_not_duplicates(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.5), run_id="run-1")
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.9), run_id="run-2")

    result = store.read_breadth(derived_conn, "sp500")

    assert len(result) == 2
    assert (result["pct_above_sma50"] == 0.9).all()
    assert (result["run_id"] == "run-2").all()


def test_different_indices_do_not_collide(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.5), run_id="run-1")
    store.upsert_breadth(derived_conn, "nasdaq100", _breadth(dates, pct_above_sma50=0.8), run_id="run-1")

    sp500 = store.read_breadth(derived_conn, "sp500")
    nasdaq = store.read_breadth(derived_conn, "nasdaq100")

    assert (sp500["pct_above_sma50"] == 0.5).all()
    assert (nasdaq["pct_above_sma50"] == 0.8).all()


def test_upsert_ignores_an_empty_frame(derived_conn):
    store.upsert_breadth(derived_conn, "sp500", pd.DataFrame(), run_id="run-1")

    result = store.read_breadth(derived_conn, "sp500")
    assert result.empty


def test_upsert_raises_on_missing_expected_columns(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    incomplete = _breadth(dates).drop(columns=["pct_above_sma200"])

    with pytest.raises(ValueError, match="pct_above_sma200"):
        store.upsert_breadth(derived_conn, "sp500", incomplete, run_id="run-1")
