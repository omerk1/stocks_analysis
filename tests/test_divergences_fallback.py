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
    monkeypatch.setattr(
        pb, "DISPUTED_DAYS",
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


def test_purge_ticker_deletes_events_and_context():
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
    n = purge_ticker(derived, "T", "daily")
    assert n == 1
    assert derived.execute("SELECT COUNT(*) FROM divergences").fetchone()[0] == 0
    assert derived.execute("SELECT COUNT(*) FROM divergence_context").fetchone()[0] == 0
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


def test_vendor_change_with_failed_rescan_keeps_old_events_and_record(conn, derived):
    _seed_old_vendor_event(derived)
    db.upsert_bars(conn, "bars_1d", "T", db.TIINGO_SPLIT_ONLY, _walk(20))  # < min_bars
    n, _ = _run_one(conn, derived, "T", Timeframe.DAILY, None, DivergenceConfig(), None, "rsi",
                    source=db.TIINGO_SPLIT_ONLY, replace_from=PRIMARY_SOURCE)
    assert n is None  # skipped
    assert derived.execute("SELECT COUNT(*) FROM divergences WHERE id = 'old1'").fetchone()[0] == 1
    # still recorded on the old vendor -> still flagged, no purge loop
    assert vendor_changed(recorded_run_sources(derived, "daily"), "T", db.TIINGO_SPLIT_ONLY)


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
    for t, src in (("OK", None), (DISPUTED, None), ("STALE", None)):
        derived_db.record_run(derived, "divergences", t, "daily", None, json.dumps({}), 0, False)
    sources, flagged = builder_sources(
        conn, derived, ["OK", DISPUTED, "STALE"], PriceBasis.TRADED, fallback=True
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
