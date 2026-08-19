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


def test_equal_and_cap_weighting_do_not_collide_for_the_same_index_and_date(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_breadth(
        derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.5), run_id="run-1", weighting="equal"
    )
    store.upsert_breadth(
        derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.9), run_id="run-1", weighting="cap"
    )

    equal = store.read_breadth(derived_conn, "sp500", weighting="equal")
    cap = store.read_breadth(derived_conn, "sp500", weighting="cap")

    assert len(equal) == 2
    assert len(cap) == 2
    assert (equal["pct_above_sma50"] == 0.5).all()
    assert (cap["pct_above_sma50"] == 0.9).all()
    assert (equal["weighting"] == "equal").all()
    assert (cap["weighting"] == "cap").all()


def test_upsert_and_read_default_to_equal_weighting(derived_conn):
    # Backward-compat: existing callers that don't pass `weighting` at all
    # (every pre-cap-weighting call site) keep working unchanged.
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates), run_id="run-1")

    result = store.read_breadth(derived_conn, "sp500")

    assert len(result) == 2
    assert (result["weighting"] == "equal").all()


_PRE_WEIGHTING_SCHEMA = """
CREATE TABLE breadth (
    index_name TEXT NOT NULL,
    date TEXT NOT NULL,
    n_constituents INTEGER NOT NULL,
    n_with_data INTEGER NOT NULL,
    pct_above_sma50 REAL,
    pct_above_sma200 REAL,
    pct_above_ema8 REAL,
    pct_above_ema21 REAL,
    pct_golden_cross REAL,
    n_advancing INTEGER NOT NULL,
    n_declining INTEGER NOT NULL,
    net_advances INTEGER NOT NULL,
    ad_ratio REAL,
    run_id TEXT,
    PRIMARY KEY (index_name, date)
);
"""


def test_create_breadth_table_migrates_a_pre_weighting_table_in_place():
    # Regression: a real local analysis.sqlite already had a `breadth`
    # table from before the `weighting` column/PK existed (PR #31's
    # original schema) -- `CREATE TABLE IF NOT EXISTS` alone silently
    # no-ops against it, so every subsequent upsert_breadth call crashed
    # with "table breadth has no column named weighting". Confirmed
    # against a real DB with 4,172 existing rows before this fix.
    connection = derived_db.get_connection(":memory:")
    connection.execute(_PRE_WEIGHTING_SCHEMA)
    connection.execute(
        """
        INSERT INTO breadth
            (index_name, date, n_constituents, n_with_data, pct_above_sma50, pct_above_sma200,
             pct_above_ema8, pct_above_ema21, pct_golden_cross, n_advancing, n_declining,
             net_advances, ad_ratio, run_id)
        VALUES ('sp500', '2020-01-01', 500, 498, 0.5, 0.6, 0.55, 0.52, 0.7, 300, 198, 102, NULL, 'old-run')
        """
    )
    connection.commit()

    store.create_breadth_table(connection)

    # The pre-existing row survived the migration, backfilled to "equal"
    # (the only weighting that existed before this column did) --
    # not dropped, not silently orphaned under a renamed table.
    migrated = store.read_breadth(connection, "sp500", weighting="equal")
    assert len(migrated) == 1
    assert migrated.iloc[0]["n_constituents"] == 500
    assert migrated.iloc[0]["run_id"] == "old-run"

    # And a new cap-weighted upsert works -- proves the new schema
    # (weighting column + 3-column PK) is actually in place, not just
    # that the old data survived.
    dates = pd.bdate_range("2020-01-02", periods=1)
    store.upsert_breadth(connection, "sp500", _breadth(dates, pct_above_sma50=0.9), run_id="new-run", weighting="cap")
    cap = store.read_breadth(connection, "sp500", weighting="cap")
    assert len(cap) == 1

    connection.close()


def test_create_breadth_table_is_idempotent_against_the_new_schema(derived_conn):
    # Calling it again (e.g. a second CLI run in the same process/DB)
    # shouldn't re-migrate or lose data -- the weighting-column check
    # should short-circuit.
    dates = pd.bdate_range("2020-01-01", periods=1)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates), run_id="run-1")

    store.create_breadth_table(derived_conn)

    result = store.read_breadth(derived_conn, "sp500")
    assert len(result) == 1


def test_rerun_with_a_different_weighting_does_not_overwrite_the_other(derived_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.5), run_id="run-1", weighting="equal")
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.9), run_id="run-2", weighting="cap")
    # Re-running "equal" again shouldn't touch the "cap" rows.
    store.upsert_breadth(derived_conn, "sp500", _breadth(dates, pct_above_sma50=0.55), run_id="run-3", weighting="equal")

    cap = store.read_breadth(derived_conn, "sp500", weighting="cap")
    assert (cap["pct_above_sma50"] == 0.9).all()
    assert (cap["run_id"] == "run-2").all()
