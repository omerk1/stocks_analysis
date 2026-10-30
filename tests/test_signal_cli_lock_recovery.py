"""A `--all` run must survive one ticker's write hitting a lock held by
another process.

A failed write leaves the connection's transaction open; once the other
writer commits, every later write on that connection fails too ("database is
locked") until it rolls back -- one collision used to fail the rest of the run.
"""

import importlib
import sqlite3
import sys
from contextlib import ExitStack, closing
from types import SimpleNamespace

import pytest

from src.foundation.market_common import derived_db
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, source_for

# module -> (per-ticker function the CLI's --all loop calls, its success return value,
#            the result tables the module's own create function must have made)
CLIS = {
    "gaps": ("run_for_ticker", ([], None), {"gaps"}),
    "avwap": ("run_for_ticker", ([], None), {"avwap_anchors"}),
    "volume_profile": ("run_for_ticker", ([], None), {"volume_profiles"}),
    "patterns": ("run_for_ticker", ([], None), {"pattern_matches"}),
    "divergences": ("_run_one", (0, False), {"divergences"}),   # its --all run reads it at startup (#196)
    "fibonacci": ("_run_one", True, {"fib_sets", "fib_levels"}),
    "sr_lines": ("_run_for_ticker", SimpleNamespace(data_quality=SimpleNamespace(rows_loaded=1), lines=[]),
                 {"sr_lines", "sr_line_events"}),
}


@pytest.mark.parametrize("module", list(CLIS))
def test_a_lock_on_one_ticker_does_not_fail_the_rest(module, tmp_path, monkeypatch):
    cli = importlib.import_module(f"src.signals.{module}.cli")
    fn_name, success, result_tables = CLIS[module]

    # The config points into tmp_path, so a connection opened by path from it can only
    # ever reach this test's files.
    raw_dir, derived_dir = tmp_path / "raw", tmp_path / "derived"
    db_path = derived_db.default_derived_db_path(derived_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        raw = stack.enter_context(closing(sqlite3.connect(":memory:")))
        derived_db.raw_db.create_tables(raw)   # the real raw schema, not a stub table
        raw.executemany("INSERT INTO bars_1d (ticker, timestamp, source) VALUES (?, '2020-01-02', ?)",
                        [(t, source_for(MODULE_PRICE_BASIS[module])) for t in ("AAA", "BBB")])
        derived = stack.enter_context(closing(sqlite3.connect(db_path, timeout=0.1)))
        derived.execute("PRAGMA journal_mode=WAL")
        other = stack.enter_context(closing(sqlite3.connect(db_path, timeout=0.1)))  # the other process

        def run(raw_conn, derived_conn, ticker, *args, **kwargs):
            if ticker == "AAA":   # the other process holds the write lock -> this write fails
                other.execute("INSERT INTO runs (run_id, module, ticker, timeframe, config_json, started_at, "
                              "rows_dropped, quality_warning) VALUES ('other', 'x', 'X', 'daily', '{}', '', 0, 0)")
                derived_db.record_run(derived_conn, module, ticker, "daily", None, "{}", 0, False)
            else:                 # it has finished; this write must succeed
                derived_conn.execute("SELECT COUNT(*) FROM runs").fetchone()
                other.commit()
                derived_db.record_run(derived_conn, module, ticker, "daily", None, "{}", 0, False)
            return success

        def swap(expected, conn):
            # Only the configured file is swapped for this test's handle; any other path
            # means bootstrap_cli changed how it connects.
            def connect(path, *_, **__):
                assert path == expected, f"opened {path}, not the configured {expected}"
                return conn
            return connect

        monkeypatch.setattr(cli, fn_name, run)
        # The real bootstrap_cli runs, so the runs table and the module's own tables are
        # created exactly as in production; only the connections it opens are swapped.
        config = SimpleNamespace(data_paths=SimpleNamespace(raw=str(raw_dir), derived=str(derived_dir)))
        monkeypatch.setattr(derived_db, "load_dotenv", lambda *_, **__: None)
        monkeypatch.setattr(derived_db, "load_config", lambda *_, **__: config)
        monkeypatch.setattr(derived_db.raw_db, "get_connection",
                            swap(derived_db.raw_db.default_db_path(raw_dir), raw))
        monkeypatch.setattr(derived_db, "get_connection", swap(db_path, derived))
        monkeypatch.setattr(sys, "argv", ["cli", "--all", "--timeframe", "daily"])
        cli.main()

        check = stack.enter_context(closing(sqlite3.connect(db_path)))
        tickers = {r[0] for r in check.execute("SELECT ticker FROM runs WHERE module = ?", (module,))}
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert tickers == {"BBB"}
    assert result_tables <= tables, f"missing result tables: {sorted(result_tables - tables)}"
