import json

import pandas as pd

from src.foundation.market_common import basis_cleanup, derived_db
from src.foundation.market_common.models import Timeframe
from src.signals.fibonacci import store as fib_store
from src.signals.gaps import store as gaps_store
from src.signals.gaps.models import Direction, Gap, GapKind
from src.signals.sr_lines import store as sr_store


def _db():
    conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(conn)
    gaps_store.create_gaps_table(conn)
    sr_store.create_sr_lines_tables(conn)
    fib_store.create_tables(conn)
    return conn


def _run(conn, module, basis):
    cfg = {"fill_by": "wick"} if basis is None else {"fill_by": "wick", "price_basis": basis}
    return derived_db.record_run(conn, module, "X", "daily", None, json.dumps(cfg), 0, False)


def _gap(gid, created, run_id):
    return Gap(id=gid, ticker="X", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC, direction=Direction.BULLISH,
               created_at=pd.Timestamp(created).isoformat(), zone_top=11.0, zone_bottom=10.0, size_atr=1.0, run_id=run_id)


def test_only_rows_from_runs_on_another_basis_are_counted_and_deleted():
    conn = _db()
    old = _run(conn, "gaps", None)          # before the setting existed -> total_return
    new = _run(conn, "gaps", "traded")      # gaps' current basis
    gaps_store.upsert_gaps(conn, [_gap("g-old", "2020-01-02", old)], old)
    gaps_store.upsert_gaps(conn, [_gap("g-new", "2020-02-03", new)], new)

    assert basis_cleanup.stale_counts(conn)["gaps"] == (1, 2)
    assert basis_cleanup.delete_stale(conn)["gaps"] == 1
    assert [r[0] for r in conn.execute("SELECT id FROM gaps")] == ["g-new"]
    assert basis_cleanup.stale_counts(conn)["gaps"] == (0, 1)


def test_rows_whose_run_is_missing_are_treated_as_stale():
    conn = _db()
    gaps_store.upsert_gaps(conn, [_gap("g-orphan", "2020-01-02", "no-such-run")], "no-such-run")
    assert basis_cleanup.stale_counts(conn)["gaps"] == (1, 1)


def _insert(conn, table, **values):
    """Insert with every NOT NULL column filled (dummy values) plus `values`."""
    row = {}
    for _, name, typ, notnull, _, pk in conn.execute(f"PRAGMA table_info({table})"):
        if notnull and not pk:
            row[name] = 0 if typ.upper() in ("INTEGER", "REAL") else "x"
    row.update(values)
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))


def test_child_rows_go_with_their_parents():
    conn = _db()
    old = _run(conn, "sr_lines", None)
    _insert(conn, "sr_lines", id="L1", ticker="X", timeframe="daily", run_id=old)
    _insert(conn, "sr_line_events", line_id="L1", run_id=old)
    _insert(conn, "fib_sets", id="F1", ticker="X", timeframe="daily", run_id=old)
    _insert(conn, "fib_levels", id="FL1", fib_set_id="F1", ratio=0.618, kind="retracement")
    conn.commit()

    deleted = basis_cleanup.delete_stale(conn)
    assert deleted["sr_lines"] == 1 and deleted["sr_line_events"] == 1
    assert deleted["fib_sets"] == 1 and deleted["fib_levels"] == 1


def test_tables_that_dont_exist_are_skipped():
    conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(conn)
    assert basis_cleanup.stale_counts(conn) == {}
    assert basis_cleanup.delete_stale(conn) == {}
