"""The divergence vendor fallback (backlog: survivors-only event base):
`load_bars` source override, `price_basis.resolve_sources` (fallback +
whole-history-dispute exclusion), the CLI's resolved universe, and
`detect` reading a fallback-only ticker's bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common import derived_db
from src.foundation.market_common import price_basis as pb
from src.foundation.market_common.data import load_bars
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import (
    MODULES_WITH_FALLBACK,
    PriceBasis,
    resolve_sources,
)
from src.foundation.market_common.price_disputes import DisputedDay
from src.signals.divergences.cli import _run_one, resolve_universe
from src.signals.divergences.config import VENDOR_FALLBACK, DivergenceConfig
from src.signals.divergences.detect import detect
from src.signals.divergences.store import (
    PRIMARY_SOURCE,
    builder_sources,
    create_divergences_table,
    forget_ticker,
    purge_ticker,
    recorded_run_sources,
    stored_tickers,
    vendor_changed,
)

# A synthetic whole-history dispute injected per test (monkeypatching the
# loaded DISPUTED_DAYS), so these tests don't pin the live
# price_disputes.csv content -- resolving a real dispute must not break
# the unit suite.
DISPUTED = "FAKEDD"


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


@pytest.fixture
def synthetic_dispute(monkeypatch):
    from src.foundation.market_common import price_disputes
    monkeypatch.setattr(
        price_disputes, "DISPUTED_DAYS",
        (DisputedDay(DISPUTED, None, "yfinance", "synthetic whole-history dispute"),),
    )


def _bars(n: int, close: float, start: str = "2015-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=n)
    df = pd.DataFrame(
        {
            "timestamp": idx,
            "open": close, "high": close + 1.0, "low": close - 1.0, "close": close,
            "volume": 1000, "is_partial": 0,
        }
    )
    return df.set_index("timestamp")


def test_load_bars_source_override_reads_that_source(conn):
    db.upsert_bars(conn, "bars_1d", "AAA", db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "AAA", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))

    default = load_bars(conn, "AAA", Timeframe.DAILY, basis=PriceBasis.TRADED)
    tiingo = load_bars(conn, "AAA", Timeframe.DAILY, basis=PriceBasis.TRADED,
                       source=db.TIINGO_SPLIT_ONLY)
    assert default["close"].iloc[0] == 100.0  # unchanged default: primary vendor
    assert tiingo["close"].iloc[0] == 50.0


def test_load_bars_source_must_hold_the_same_basis(conn):
    with pytest.raises(ValueError, match="does not hold"):
        load_bars(conn, "AAA", Timeframe.DAILY, basis=PriceBasis.TRADED, source=db.TIINGO)


def test_resolve_sources_prefers_primary_then_falls_back(conn):
    db.upsert_bars(conn, "bars_1d", "LIVE", db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "DEAD", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))

    out = resolve_sources(conn, ["LIVE", "DEAD", "NONE"], PriceBasis.TRADED, fallback=True)
    assert out == {"LIVE": db.YFINANCE_SPLIT_ONLY, "DEAD": db.TIINGO_SPLIT_ONLY}

    # Without fallback: the documented no-lookup mapping to the primary source.
    flat = resolve_sources(conn, ["LIVE", "DEAD"], PriceBasis.TRADED, fallback=False)
    assert flat == dict.fromkeys(["LIVE", "DEAD"], db.YFINANCE_SPLIT_ONLY)


def test_resolve_sources_drops_whole_history_disputed(conn, synthetic_dispute):
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    out = resolve_sources(conn, [DISPUTED], PriceBasis.TRADED, fallback=True)
    assert out == {}  # the disputed ticker has no bars at all, nowhere


def test_divergences_is_a_fallback_module():
    assert "divergences" in MODULES_WITH_FALLBACK
    assert VENDOR_FALLBACK is True


def test_resolve_universe_spans_both_sources_and_counts_disputed(conn, synthetic_dispute):
    db.upsert_bars(conn, "bars_1d", "LIVE", db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "DEAD", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))

    sources, n_disputed = resolve_universe(conn)
    assert sources == {"LIVE": db.YFINANCE_SPLIT_ONLY, "DEAD": db.TIINGO_SPLIT_ONLY}
    assert n_disputed == 1


def test_vendor_changed_legacy_runs_count_as_primary():
    recorded = {"T": None, "AAPL": db.YFINANCE_SPLIT_ONLY, "DEAD": db.TIINGO_SPLIT_ONLY}
    # Legacy run (no recorded bar_source) == primary source by construction.
    assert vendor_changed(recorded, "T", db.TIINGO_SPLIT_ONLY) is True
    assert vendor_changed(recorded, "AAPL", PRIMARY_SOURCE) is False
    assert vendor_changed(recorded, "DEAD", db.TIINGO_SPLIT_ONLY) is False
    assert vendor_changed(recorded, "NEVER_RAN", db.TIINGO_SPLIT_ONLY) is False


def test_recorded_run_sources_reads_bar_source_latest_wins():
    import json
    derived = db.get_connection(":memory:")
    derived_db.create_runs_table(derived)
    derived_db.record_run(derived, "divergences", "LEGACY", "daily", None, "{}", 0, False)
    derived_db.record_run(derived, "divergences", "SWITCHED", "daily", None,
                          json.dumps({"bar_source": db.YFINANCE_SPLIT_ONLY}), 0, False)
    derived_db.record_run(derived, "divergences", "SWITCHED", "daily", None,
                          json.dumps({"bar_source": db.TIINGO_SPLIT_ONLY}), 0, False)
    out = recorded_run_sources(derived, "daily")
    assert out["LEGACY"] is None  # caller substitutes the primary source
    assert out["SWITCHED"] == db.TIINGO_SPLIT_ONLY  # latest run wins
    derived.close()


def test_purge_ticker_deletes_events_context_and_pairs():
    derived = db.get_connection(":memory:")
    create_divergences_table(derived)
    derived.execute(
        "INSERT INTO divergences (id, ticker, timeframe, indicator, direction, p2_date)"
        " VALUES ('x1', 'T', 'daily', 'rsi', 'bearish', '2015-01-05')"
    )
    derived.execute(
        "CREATE TABLE divergence_context (divergence_id TEXT PRIMARY KEY, ticker TEXT, timeframe TEXT)"
    )
    derived.execute("INSERT INTO divergence_context VALUES ('x1', 'T', 'daily')")
    from src.signals.divergences.controls import create_control_pairs_table
    create_control_pairs_table(derived)
    derived.execute(
        "INSERT INTO divergence_control_pairs (id, ticker, timeframe, direction, p2_date)"
        " VALUES ('p1', 'T', 'daily', 'bearish', '2015-01-05')"
    )
    n = purge_ticker(derived, "T", "daily")
    assert n == 1
    for table in ("divergences", "divergence_context", "divergence_control_pairs"):
        assert derived.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # ... and a DB without the context table doesn't blow up
    bare = db.get_connection(":memory:")
    create_divergences_table(bare)
    assert purge_ticker(bare, "T", "daily") == 0
    bare.close()
    derived.close()


def test_detect_reads_a_fallback_only_ticker(conn):
    rng = np.random.default_rng(7)
    n = 400
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.bdate_range("2015-01-02", periods=n)
    bars = pd.DataFrame(
        {
            "timestamp": idx,
            "open": closes, "high": closes + 1.0, "low": closes - 1.0, "close": closes,
            "volume": 1000, "is_partial": 0,
        }
    ).set_index("timestamp")
    db.upsert_bars(conn, "bars_1d", "DEAD", db.TIINGO_SPLIT_ONLY, bars)

    config = DivergenceConfig()
    # Primary source has nothing -> skipped for too little data...
    _, report0, skip0 = detect(conn, "DEAD", Timeframe.DAILY, config)
    assert skip0 is not None and report0.rows_loaded == 0
    # ...the resolved fallback source has the full history.
    _, report1, skip1 = detect(conn, "DEAD", Timeframe.DAILY, config, source=db.TIINGO_SPLIT_ONLY)
    assert skip1 is None and report1.rows_loaded == n


def _walk(n: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.bdate_range("2015-01-02", periods=n)
    return pd.DataFrame(
        {"timestamp": idx, "open": closes, "high": closes + 1.0, "low": closes - 1.0,
         "close": closes, "volume": 1000, "is_partial": 0}
    ).set_index("timestamp")


@pytest.fixture
def derived():
    connection = db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    create_divergences_table(connection)
    yield connection
    connection.close()


def _seed_old_vendor_event(derived):
    """A ticker detected long ago on the primary vendor (legacy run, no
    recorded bar_source) with one stored event."""
    import json
    derived_db.record_run(derived, "divergences", "T", "daily", None, json.dumps({}), 0, False)
    derived.execute(
        "INSERT INTO divergences (id, ticker, timeframe, indicator, direction, p2_date)"
        " VALUES ('old1', 'T', 'daily', 'rsi', 'bearish', '2000-01-03')"
    )
    derived.commit()


def test_vendor_change_with_too_short_new_vendor_forgets_the_ticker(conn, derived):
    """The old vendor's events can't stay (the builders would strip their
    context and pairs, stranding them), and the new vendor can't support
    detection: the ticker is forgotten -- same state as any too-short ticker."""
    _seed_old_vendor_event(derived)
    db.upsert_bars(conn, "bars_1d", "T", db.TIINGO_SPLIT_ONLY, _walk(20))  # < min_bars
    n, _ = _run_one(conn, derived, "T", Timeframe.DAILY, None, DivergenceConfig(), None, "rsi",
                    source=db.TIINGO_SPLIT_ONLY, replace_from=PRIMARY_SOURCE)
    assert n is None  # skipped
    assert derived.execute("SELECT COUNT(*) FROM divergences WHERE ticker = 'T'").fetchone()[0] == 0
    assert "T" not in recorded_run_sources(derived, "daily")  # retried later as never-scanned


def test_vendor_change_with_successful_rescan_replaces_events(conn, derived):
    _seed_old_vendor_event(derived)
    db.upsert_bars(conn, "bars_1d", "T", db.TIINGO_SPLIT_ONLY, _walk(400))
    n, _ = _run_one(conn, derived, "T", Timeframe.DAILY, None, DivergenceConfig(), None, "rsi",
                    source=db.TIINGO_SPLIT_ONLY, replace_from=PRIMARY_SOURCE)
    assert n is not None
    assert derived.execute("SELECT COUNT(*) FROM divergences WHERE id = 'old1'").fetchone()[0] == 0
    rec = recorded_run_sources(derived, "daily")
    assert rec["T"] == db.TIINGO_SPLIT_ONLY
    assert not vendor_changed(rec, "T", db.TIINGO_SPLIT_ONLY)
    # single-ticker filter returns only that ticker
    assert set(recorded_run_sources(derived, "daily", ticker="T")) == {"T"}


def test_builder_sources_flags_unresolved_and_vendor_stale(conn, derived, synthetic_dispute):
    import json
    db.upsert_bars(conn, "bars_1d", "OK", db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "STALE", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))
    for t in ("OK", DISPUTED, "STALE"):  # legacy runs: no recorded bar_source
        derived_db.record_run(derived, "divergences", t, "daily", None, json.dumps({}), 0, False)
    sources, flagged = builder_sources(
        conn, derived, ["OK", DISPUTED, "STALE"], PriceBasis.TRADED, fallback=True, timeframe="daily"
    )
    assert flagged == {DISPUTED: "unresolved", "STALE": "vendor_stale"}
    assert sources["OK"] == db.YFINANCE_SPLIT_ONLY


def test_stored_tickers_lists_tickers_with_events(derived):
    _seed_old_vendor_event(derived)
    assert stored_tickers(derived, "daily") == {"T"}
    assert stored_tickers(derived, "weekly") == set()


def test_control_builder_purges_pairs_of_flagged_tickers(conn, derived, synthetic_dispute):
    import json
    from src.signals.divergences.controls import build_control_pairs, create_control_pairs_table

    create_control_pairs_table(derived)
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "STALE", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))
    for t in (DISPUTED, "STALE"):
        derived_db.record_run(derived, "divergences", t, "daily", None, json.dumps({}), 0, False)
        derived.execute(
            "INSERT INTO divergence_control_pairs (id, ticker, timeframe, direction, p2_date)"
            " VALUES (?, ?, 'daily', 'bearish', '2015-01-05')", (f"p-{t}", t),
        )
    derived.commit()

    _w, _p, _s, unresolved, vendor_stale = build_control_pairs(conn, derived)
    assert (unresolved, vendor_stale) == (1, 1)
    assert derived.execute("SELECT COUNT(*) FROM divergence_control_pairs").fetchone()[0] == 0


def test_vendor_change_rescan_is_atomic_on_write_failure(conn, derived, monkeypatch):
    """Purge + run row + new events are one transaction: a failing event
    write must roll back the purge and the run row too -- otherwise the
    ticker reads as scanned on its new vendor with no events."""
    from src.signals.divergences import cli

    _seed_old_vendor_event(derived)
    db.upsert_bars(conn, "bars_1d", "T", db.TIINGO_SPLIT_ONLY, _walk(400))

    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(cli, "upsert_divergences", boom)
    with pytest.raises(RuntimeError):
        _run_one(conn, derived, "T", Timeframe.DAILY, None, DivergenceConfig(), None, "rsi",
                 source=db.TIINGO_SPLIT_ONLY, replace_from=PRIMARY_SOURCE)
    derived.rollback()  # what the --all loop does on an exception
    assert derived.execute("SELECT COUNT(*) FROM divergences WHERE id = 'old1'").fetchone()[0] == 1
    assert derived.execute("SELECT COUNT(*) FROM runs WHERE ticker = 'T'").fetchone()[0] == 1
    assert vendor_changed(recorded_run_sources(derived, "daily"), "T", db.TIINGO_SPLIT_ONLY)


def test_forget_ticker_drops_events_pairs_and_runs(derived):
    from src.signals.divergences.controls import create_control_pairs_table

    _seed_old_vendor_event(derived)
    create_control_pairs_table(derived)
    derived.execute(
        "INSERT INTO divergence_control_pairs (id, ticker, timeframe, direction, p2_date)"
        " VALUES ('p1', 'T', 'daily', 'bearish', '2015-01-05')"
    )
    for module in ("divergence_context", "divergence_control_pairs"):
        derived_db.record_run(derived, module, "T", "daily", None, "{}", 0, False)
    assert forget_ticker(derived, "T", "daily") == 1
    derived.commit()
    for table in ("divergences", "divergence_control_pairs", "runs"):
        assert derived.execute(f"SELECT COUNT(*) FROM {table} WHERE ticker = 'T'").fetchone()[0] == 0
    assert "T" not in recorded_run_sources(derived, "daily")  # a later --missing-only rescans it


def test_control_builder_runs_past_flagged_and_normal_tickers(conn, derived, synthetic_dispute):
    """A real multi-ticker build: flagged tickers skipped AND normal tickers
    processed (an earlier version shadowed the flagged-ticker dict inside the
    loop and crashed on the second normal ticker -- a test seeding only
    flagged tickers never entered the loop body)."""
    import json
    from src.signals.divergences.controls import build_control_pairs, create_control_pairs_table

    create_control_pairs_table(derived)
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _walk(400, seed=1))
    for i, t in enumerate(("AAA", "BBB")):
        db.upsert_bars(conn, "bars_1d", t, db.YFINANCE_SPLIT_ONLY, _walk(400, seed=10 + i))
    for t in (DISPUTED, "AAA", "BBB"):
        derived_db.record_run(derived, "divergences", t, "daily", None,
                              json.dumps({"bar_source": db.YFINANCE_SPLIT_ONLY}), 0, False)

    written, processed, _skipped, unresolved, vendor_stale = build_control_pairs(conn, derived)
    assert (unresolved, vendor_stale) == (1, 0)
    assert processed == 2 and written > 0
    tickers = {r[0] for r in derived.execute("SELECT DISTINCT ticker FROM divergence_control_pairs")}
    assert tickers == {"AAA", "BBB"}


def test_as_of_never_replaces_a_vendor_changed_ticker(conn, derived, monkeypatch, capsys):
    """A replacement purges the full stored history, so a truncated --as-of
    rescan must not perform one."""
    import sys
    from src.signals.divergences import cli

    _seed_old_vendor_event(derived)
    db.upsert_bars(conn, "bars_1d", "T", db.TIINGO_SPLIT_ONLY, _walk(400))
    monkeypatch.setattr(cli.derived_db, "bootstrap_cli", lambda _create: (conn, derived))
    monkeypatch.setattr(sys, "argv", ["cli", "T", "--timeframe", "daily", "--as-of", "2015-06-30"])
    with pytest.raises(SystemExit) as exc:  # a refusal exits non-zero
        cli.main()
    assert exc.value.code == 1
    assert "not replaced under --as-of" in capsys.readouterr().out


def test_control_builder_replaces_with_nothing_when_a_ticker_yields_no_pairs(conn, derived):
    """Replace-per-ticker must hold for zero-pair outcomes: a ticker whose
    history got too short keeps no rows from its earlier, longer history."""
    import json
    from src.signals.divergences.controls import build_control_pairs, create_control_pairs_table

    create_control_pairs_table(derived)
    db.upsert_bars(conn, "bars_1d", "SHORT", db.YFINANCE_SPLIT_ONLY, _walk(30))  # < min_bars
    derived_db.record_run(derived, "divergences", "SHORT", "daily", None,
                          json.dumps({"bar_source": db.YFINANCE_SPLIT_ONLY}), 0, False)
    derived.execute(
        "INSERT INTO divergence_control_pairs (id, ticker, timeframe, direction, p2_date)"
        " VALUES ('old', 'SHORT', 'daily', 'bearish', '2010-01-05')"
    )
    derived.commit()
    build_control_pairs(conn, derived)
    assert derived.execute("SELECT COUNT(*) FROM divergence_control_pairs").fetchone()[0] == 0


def test_purge_flagged_only_accepts_builder_tables(derived):
    import logging
    from src.signals.divergences.store import purge_flagged
    with pytest.raises(ValueError):
        purge_flagged(derived, "divergences", {"T": "unresolved"}, "daily", logging.getLogger("t"))


def test_resolve_sources_never_lists_sources_on_its_own(conn, monkeypatch):
    """Modeling passes ~1,000 mostly-primary tickers: the shared resolver
    must keep the cheap per-ticker probe unless a caller opts into listing."""
    calls = []
    monkeypatch.setattr(pb, "source_members", lambda *a, **k: calls.append(1) or {})
    tickers = [f"T{i}" for i in range(2000)]
    resolve_sources(conn, tickers, PriceBasis.TRADED, fallback=True)
    assert calls == []


def test_builder_sources_lists_sources_only_for_large_builds(conn, derived, monkeypatch):
    from src.signals.divergences import store
    calls = []
    real = store.source_members

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(store, "source_members", spy)
    monkeypatch.setattr(store, "MEMBERS_THRESHOLD", 2)
    db.upsert_bars(conn, "bars_1d", "A", db.YFINANCE_SPLIT_ONLY, _bars(3, 1.0))
    db.upsert_bars(conn, "bars_1d", "B", db.TIINGO_SPLIT_ONLY, _bars(3, 1.0))
    small, _ = builder_sources(conn, derived, ["A", "B"], PriceBasis.TRADED, True, "daily")
    assert calls == []
    big, _ = builder_sources(conn, derived, ["A", "B", "C"], PriceBasis.TRADED, True, "daily")
    assert calls == [1] and big == small  # same answer either way
