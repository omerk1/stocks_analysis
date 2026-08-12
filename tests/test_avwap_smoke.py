import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.avwap import store
from src.avwap.anchors import detect
from src.avwap.config import AvwapConfig
from src.avwap.models import Timeframe
from src.data_processing import db as raw_db
from src.market_common import derived_db

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = REPO_ROOT / "data" / "raw" / "market_data.sqlite"


@pytest.fixture
def raw_conn():
    connection = raw_db.get_connection(":memory:")
    raw_db.create_tables(connection)
    yield connection
    connection.close()


@pytest.fixture
def derived_conn():
    connection = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(connection)
    store.create_avwap_table(connection)
    yield connection
    connection.close()


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume, is_partial)"""
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def _seed_series_with_a_clear_high_and_low(raw_conn, ticker="TEST", n=200):
    idx = pd.bdate_range("2020-01-01", periods=n)
    rows = [(d.strftime("%Y-%m-%d"), 100.0, 100.5, 99.5, 100.0, 1000.0, 0) for d in idx]
    # a lone spike-high and dip-low, well inside the series, guaranteeing
    # at least an ath and atl anchor without depending on cycle-pivot noise
    rows[50] = (idx[50].strftime("%Y-%m-%d"), 100.0, 500.0, 99.5, 100.0, 1000.0, 0)
    rows[100] = (idx[100].strftime("%Y-%m-%d"), 100.0, 100.5, 1.0, 100.0, 1000.0, 0)
    raw_db.upsert_bars(raw_conn, "bars_1d", ticker, raw_db.YFINANCE, _bars(rows))


def test_upsert_anchors_is_idempotent_across_repeated_detection_runs(raw_conn, derived_conn):
    _seed_series_with_a_clear_high_and_low(raw_conn)
    config = AvwapConfig(min_bars=1, warmup_bars=0)

    anchors_1, _, skip_reason = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    assert skip_reason is None
    assert len(anchors_1) >= 2  # at least ath + atl
    store.upsert_anchors(derived_conn, anchors_1, "run-1")
    count_after_first = derived_conn.execute("SELECT COUNT(*) FROM avwap_anchors").fetchone()[0]
    assert count_after_first == len(anchors_1)

    previous = store.get_anchor_types(derived_conn, "TEST", "daily")
    anchors_2, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config, previous_anchor_types=previous)
    store.upsert_anchors(derived_conn, anchors_2, "run-2")
    count_after_second = derived_conn.execute("SELECT COUNT(*) FROM avwap_anchors").fetchone()[0]

    assert count_after_second == count_after_first

    ids_after_second = {
        row[0] for row in derived_conn.execute("SELECT id FROM avwap_anchors").fetchall()
    }
    # Re-running detect() mints fresh uuid4s for every AnchoredVwap object,
    # but the upsert must preserve each row's *original* id on conflict --
    # same ON CONFLICT DO UPDATE reasoning as gaps.store.upsert_gaps.
    store.upsert_anchors(derived_conn, anchors_2, "run-3")
    ids_after_third = {
        row[0] for row in derived_conn.execute("SELECT id FROM avwap_anchors").fetchall()
    }
    assert ids_after_second == ids_after_third

    run_ids = {row[0] for row in derived_conn.execute("SELECT run_id FROM avwap_anchors").fetchall()}
    assert run_ids == {"run-3"}


def test_smoke_real_aapl_daily_ticker_detection():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")

    conn = sqlite3.connect(REAL_DB_PATH)
    config = AvwapConfig()

    anchors, report, skip_reason = detect(conn, "AAPL", Timeframe.DAILY, config)

    assert skip_reason is None
    assert report.rows_loaded > config.min_bars
    assert isinstance(anchors, list)
    assert len(anchors) > 0

    from src.avwap.models import AnchorType

    all_roles = {role for a in anchors for role in a.anchor_types}
    assert AnchorType.ATH in all_roles
    assert AnchorType.ATL in all_roles

    for anchor in anchors:
        assert anchor.ticker == "AAPL"
        assert anchor.timeframe == Timeframe.DAILY
        assert anchor.anchor_types
        if anchor.current_value is not None:
            assert anchor.current_value > 0
        # Interaction tracking: every anchor has at least one bar after its
        # own anchor date (the anchor date itself), so these should always
        # be populated for a real, successfully-detected anchor.
        assert anchor.n_crosses >= 0
        if anchor.pct_bars_above is not None:
            assert anchor.pct_bars_below is not None
            assert anchor.pct_bars_above + anchor.pct_bars_below == pytest.approx(1.0)

    conn.close()
