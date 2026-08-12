import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.data_processing import db as raw_db
from src.gaps import store
from src.gaps.config import GapConfig
from src.gaps.detect import detect
from src.gaps.models import GapKind, GapStatus, Timeframe
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
    store.create_gaps_table(connection)
    yield connection
    connection.close()


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume, is_partial)"""
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def _seed_flat_series_with_one_gap(raw_conn, ticker="TEST", n_background=30):
    idx = pd.bdate_range("2020-01-01", periods=n_background)
    rows = [
        (d.strftime("%Y-%m-%d"), 100.0, 101.0, 99.0, 100.0, 1000.0, 0) for d in idx
    ]
    last = idx[-1] + pd.Timedelta(days=1)
    rows.append((pd.bdate_range(last, periods=1)[0].strftime("%Y-%m-%d"), 110.0, 111.0, 110.0, 110.0, 1000.0, 0))
    raw_db.upsert_bars(raw_conn, "bars_1d", ticker, raw_db.YFINANCE, _bars(rows))


def test_upsert_gaps_is_idempotent_across_repeated_detection_runs(raw_conn, derived_conn):
    _seed_flat_series_with_one_gap(raw_conn)
    config = GapConfig(atr_period=5, warmup_bars=0, min_bars=1, min_gap_atr=0.3)

    gaps_1, _, skip_reason = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    assert skip_reason is None
    assert len(gaps_1) >= 1
    store.upsert_gaps(derived_conn, gaps_1, "run-1")
    count_after_first = derived_conn.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]
    assert count_after_first == len(gaps_1)

    gaps_2, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    store.upsert_gaps(derived_conn, gaps_2, "run-2")
    count_after_second = derived_conn.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]

    assert count_after_second == count_after_first

    ids_after_first = {
        row[0] for row in derived_conn.execute("SELECT id FROM gaps").fetchall()
    }
    # Re-running detect() mints fresh uuid4s for every Gap object, but the
    # upsert must preserve each row's *original* id on conflict -- this is
    # the whole point of ON CONFLICT DO UPDATE over INSERT OR REPLACE.
    store.upsert_gaps(derived_conn, gaps_2, "run-3")
    ids_after_third = {
        row[0] for row in derived_conn.execute("SELECT id FROM gaps").fetchall()
    }
    assert ids_after_first == ids_after_third

    run_ids = {row[0] for row in derived_conn.execute("SELECT run_id FROM gaps").fetchall()}
    assert run_ids == {"run-3"}


def test_upsert_gaps_updates_lifecycle_fields_on_conflict(raw_conn, derived_conn):
    _seed_flat_series_with_one_gap(raw_conn)
    config = GapConfig(atr_period=5, warmup_bars=0, min_bars=1, min_gap_atr=0.3)

    gaps_1, _, _ = detect(raw_conn, "TEST", Timeframe.DAILY, config)
    classic = next(g for g in gaps_1 if g.kind == GapKind.CLASSIC)
    original_id = classic.id
    store.upsert_gaps(derived_conn, gaps_1, "run-1")

    classic.max_fill_pct = 55.0
    classic.status = GapStatus.SOFT_CLOSED
    store.upsert_gaps(derived_conn, [classic], "run-2")

    row = derived_conn.execute(
        "SELECT id, status, max_fill_pct, run_id FROM gaps WHERE id = ?", (original_id,)
    ).fetchone()
    assert row == (original_id, "soft_closed", 55.0, "run-2")


def test_smoke_real_aapl_daily_ticker_detection():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")

    conn = sqlite3.connect(REAL_DB_PATH)
    config = GapConfig()

    gaps, report, skip_reason = detect(conn, "AAPL", Timeframe.DAILY, config)

    assert skip_reason is None
    assert report.rows_loaded > config.min_bars
    assert isinstance(gaps, list)
    for gap in gaps:
        assert gap.zone_top > gap.zone_bottom
        assert gap.size_atr >= config.min_gap_atr
        assert 0.0 <= gap.max_fill_pct <= 100.0
        # Approach-event/volume/reaction tracking, added alongside the
        # existing fill-percentage curve.
        assert gap.n_approaches >= 0
        # A gap that was ever touched at all had at least one approach.
        if gap.max_fill_pct > 0.0:
            assert gap.n_approaches >= 1
        if gap.volume_ratio_at_creation is not None:
            assert gap.volume_ratio_at_creation >= 0.0
        if gap.status == GapStatus.CLOSED and gap.reaction_atr_after_close is not None:
            assert gap.reaction_atr_after_close >= 0.0

    conn.close()
