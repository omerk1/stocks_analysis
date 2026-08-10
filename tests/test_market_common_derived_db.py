import pytest

from src.market_common import derived_db


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
