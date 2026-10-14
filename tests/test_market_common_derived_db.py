import pandas as pd
import pytest

from src.foundation.market_common import derived_db
from src.signals.relative_strength import store as rs_store


@pytest.fixture
def conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    yield connection
    connection.close()


def test_default_derived_db_path():
    assert str(derived_db.default_derived_db_path("data/derived")) == "data/derived/analysis.sqlite"


def test_record_run_returns_a_fresh_run_id_each_time(conn):
    run_id_1 = derived_db.record_run(
        conn, "gaps", "AAPL", "daily", "2024-01-01", "{}", rows_dropped=0, quality_warning=False,
    )
    run_id_2 = derived_db.record_run(
        conn, "gaps", "AAPL", "daily", "2024-01-01", "{}", rows_dropped=0, quality_warning=False,
    )

    assert run_id_1 != run_id_2
    rows = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
    assert rows[0] == 2


def test_record_run_stores_all_fields(conn):
    run_id = derived_db.record_run(
        conn, "divergences", "PAAS", "weekly", None, '{"indicators": ["rsi"]}',
        rows_dropped=3, quality_warning=True,
    )

    row = conn.execute(
        "SELECT module, ticker, timeframe, as_of, config_json, rows_dropped, quality_warning "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row == ("divergences", "PAAS", "weekly", None, '{"indicators": ["rsi"]}', 3, 1)


def test_create_runs_table_is_idempotent(conn):
    derived_db.create_runs_table(conn)  # second call must not raise
    derived_db.record_run(conn, "fibonacci", "T", "daily", None, "{}", rows_dropped=0, quality_warning=False)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_connections_wait_on_locks_instead_of_failing_fast(tmp_path):
    """A writer must outlast a concurrent reader's lock rather than dying
    with "database is locked" after sqlite3's 5s default."""
    from src.foundation.data_processing import db as raw_db

    path = tmp_path / "x.sqlite"
    for get_conn in (raw_db.get_connection, derived_db.get_connection):
        conn = get_conn(path)
        (busy_ms,) = conn.execute("PRAGMA busy_timeout").fetchone()
        assert busy_ms >= 30_000
        conn.close()


def test_readonly_uri_connection_cannot_write(tmp_path):
    import sqlite3

    path = tmp_path / "x.sqlite"
    rw = derived_db.get_connection(path)
    rw.execute("CREATE TABLE t (x INTEGER)")
    rw.commit()
    rw.close()

    ro = derived_db.get_connection(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()


def _rs_rows(conn, dates, ticker, run_id):
    frame = pd.DataFrame(
        [{"ticker": ticker, "date": d, "benchmark": "SPY", "rs_ratio": 1.0, "rs_mansfield": 1.0,
          "rs_weighted_return": 0.1, "rs_rating": 50.0} for d in dates]
    )
    rs_store.upsert_relative_strength(conn, "vs_market", frame, run_id)


@pytest.fixture
def sweep_conn(conn):
    rs_store.create_relative_strength_tables(conn)
    return conn


def test_delete_rows_from_other_runs_sweeps_stale_and_null_run_ids(sweep_conn):
    dates = pd.bdate_range("2020-01-01", periods=2)
    # AAPL recomputed by the new run; DELISTED only exists under the old
    # run (its bars are gone, so a fresh run never overwrites its keys).
    _rs_rows(sweep_conn, dates, "DELISTED", "old-run")
    _rs_rows(sweep_conn, dates, "AAPL", "new-market")
    sweep_conn.execute(
        "INSERT INTO relative_strength (ticker, date, comparison, run_id) VALUES ('NULLROW', '2020-01-02', 'vs_market', NULL)"
    )

    deleted = derived_db.delete_rows_from_other_runs(sweep_conn, "relative_strength", ["new-market"])

    assert deleted == 3  # DELISTED x 2 dates + the NULL-run_id row
    remaining = sweep_conn.execute("SELECT DISTINCT ticker, run_id FROM relative_strength").fetchall()
    assert {row[0] for row in remaining} == {"AAPL"}
    assert {row[1] for row in remaining} == {"new-market"}


def test_delete_rows_from_other_runs_leaves_other_tables_alone(sweep_conn):
    dates = pd.bdate_range("2020-01-01", periods=1)
    sector = pd.DataFrame(
        [{"sector": "Technology", "date": dates[0], "benchmark": "SPY", "rs_ratio": 1.0,
          "rs_mansfield": 1.0, "rs_weighted_return": 0.1, "rs_rating": 50.0}]
    )
    rs_store.upsert_sector_relative_strength(sweep_conn, sector, "old-run")
    _rs_rows(sweep_conn, dates, "AAPL", "new-run")

    derived_db.delete_rows_from_other_runs(sweep_conn, "relative_strength", ["new-run"])

    assert len(rs_store.read_sector_relative_strength(sweep_conn, "Technology")) == 1


def test_delete_rows_from_other_runs_refuses_an_empty_keep_list_and_unlisted_tables(sweep_conn):
    with pytest.raises(ValueError, match="empty"):
        derived_db.delete_rows_from_other_runs(sweep_conn, "relative_strength", [])
    with pytest.raises(ValueError, match="not sweepable"):
        derived_db.delete_rows_from_other_runs(sweep_conn, "runs", ["run-1"])
