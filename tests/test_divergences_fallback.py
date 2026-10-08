"""The divergence vendor fallback (backlog: survivors-only event base):
`load_bars` source override, `price_basis.resolve_sources` (fallback +
whole-history-dispute exclusion), the CLI's resolved universe, and
`detect` reading a fallback-only ticker's bars."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.market_common.data import load_bars
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import (
    MODULES_WITH_FALLBACK,
    PriceBasis,
    resolve_sources,
)
from src.signals.divergences.cli import resolve_universe
from src.signals.divergences.config import VENDOR_FALLBACK, DivergenceConfig
from src.signals.divergences.detect import detect

# A real whole-history yfinance dispute from price_disputes.csv (DowDuPont:
# the vendors' DD series are different securities). Used read-only.
DISPUTED = "DD"


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


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


def test_resolve_sources_drops_whole_history_disputed(conn):
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    out = resolve_sources(conn, [DISPUTED], PriceBasis.TRADED, fallback=True)
    assert out == {}  # the disputed ticker has no bars at all, nowhere


def test_divergences_is_a_fallback_module():
    assert "divergences" in MODULES_WITH_FALLBACK
    assert VENDOR_FALLBACK is True


def test_resolve_universe_spans_both_sources_and_counts_disputed(conn):
    db.upsert_bars(conn, "bars_1d", "LIVE", db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))
    db.upsert_bars(conn, "bars_1d", "DEAD", db.TIINGO_SPLIT_ONLY, _bars(3, 50.0))
    db.upsert_bars(conn, "bars_1d", DISPUTED, db.YFINANCE_SPLIT_ONLY, _bars(3, 100.0))

    sources, n_disputed = resolve_universe(conn)
    assert sources == {"LIVE": db.YFINANCE_SPLIT_ONLY, "DEAD": db.TIINGO_SPLIT_ONLY}
    assert n_disputed == 1


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
