"""A `--all` run must survive one ticker's write hitting a lock held by
another process.

A failed write leaves the connection's transaction open; once the other
writer commits, every later write on that connection fails too ("database is
locked") until it rolls back -- one collision used to fail the rest of the run.
"""

import importlib
import sqlite3
import sys

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
}


@pytest.mark.parametrize("module", list(CLIS))
def test_a_lock_on_one_ticker_does_not_fail_the_rest(module, tmp_path, monkeypatch):
    cli = importlib.import_module(f"src.signals.{module}.cli")
    fn_name, success = CLIS[module]

    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE bars_1d (ticker TEXT, source TEXT)")
    raw.executemany("INSERT INTO bars_1d VALUES (?, ?)",
                    [(t, source_for(MODULE_PRICE_BASIS[module])) for t in ("AAA", "BBB")])

    db_path = tmp_path / "derived.sqlite"
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
    monkeypatch.setattr(cli.derived_db, "bootstrap_cli", lambda *_: (raw, derived))
    monkeypatch.setattr(sys, "argv", ["cli", "--all", "--timeframe", "daily"])
    cli.main()

    check = sqlite3.connect(db_path)
    tickers = {r[0] for r in check.execute("SELECT ticker FROM runs WHERE module = ?", (module,))}
    assert tickers == {"BBB"}
