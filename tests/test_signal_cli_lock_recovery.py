"""A `--all` run must survive one ticker's write hitting a lock held by
another process.

A failed write leaves the connection's transaction open; once the other
writer commits, every later write on that connection fails too ("database is
locked") until it rolls back -- one collision used to fail the rest of the run.
"""

import importlib
import sqlite3
import sys
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.foundation.market_common import derived_db
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, source_for

# module -> (per-ticker function the CLI's --all loop calls, its success return value)
CLIS = {
    "gaps": ("run_for_ticker", ([], None)),
    "avwap": ("run_for_ticker", ([], None)),
    "volume_profile": ("run_for_ticker", ([], None)),
    "patterns": ("run_for_ticker", ([], None)),
    "divergences": ("_run_one", (0, False)),
    "fibonacci": ("_run_one", True),
    "sr_lines": ("_run_for_ticker", SimpleNamespace(data_quality=SimpleNamespace(rows_loaded=1), lines=[])),
}


@pytest.mark.parametrize("module", list(CLIS))
def test_a_lock_on_one_ticker_does_not_fail_the_rest(module, tmp_path, monkeypatch):
    cli = importlib.import_module(f"src.signals.{module}.cli")
    fn_name, success = CLIS[module]

    raw = sqlite3.connect(":memory:")
    derived_db.raw_db.create_tables(raw)   # the real raw schema, not a stub table
    raw.executemany("INSERT INTO bars_1d (ticker, timestamp, source) VALUES (?, '2020-01-02', ?)",
                    [(t, source_for(MODULE_PRICE_BASIS[module])) for t in ("AAA", "BBB")])

    # The config points into tmp_path too, so even if a redirect below stopped applying
    # (bootstrap_cli changed how it connects), nothing could reach the real databases.
    raw_dir, derived_dir = tmp_path / "raw", tmp_path / "derived"
    db_path = derived_db.default_derived_db_path(derived_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    derived = sqlite3.connect(db_path, timeout=0.1)
    derived.execute("PRAGMA journal_mode=WAL")
    derived_db.create_runs_table(derived)
    derived.commit()
    other = sqlite3.connect(db_path, timeout=0.1)   # the other process

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

    monkeypatch.setattr(cli, fn_name, run)

    # The real bootstrap_cli runs (so the module's own tables exist exactly as in
    # production); only the connections it opens are swapped for this test's handles
    # (the in-memory raw stub, and the short-timeout derived connection the lock needs).
    config = SimpleNamespace(data_paths=SimpleNamespace(raw=str(raw_dir), derived=str(derived_dir)))
    monkeypatch.setattr(derived_db, "load_dotenv", lambda *_, **__: None)
    monkeypatch.setattr(derived_db, "load_config", lambda *_, **__: config)
    monkeypatch.setattr(derived_db.raw_db, "get_connection", lambda *_, **__: raw)
    monkeypatch.setattr(derived_db, "get_connection", lambda *_, **__: derived)
    monkeypatch.setattr(sys, "argv", ["cli", "--all", "--timeframe", "daily"])
    try:
        cli.main()
        with closing(sqlite3.connect(db_path)) as check:
            tickers = {r[0] for r in check.execute("SELECT ticker FROM runs WHERE module = ?", (module,))}
            tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        for conn in (raw, derived, other):
            conn.close()
    assert tickers == {"BBB"}
    assert tables - {"runs"}, "the module's own result table was never created"
    if module == "divergences":   # the table its --all run reads at startup (#196)
        assert "divergences" in tables
