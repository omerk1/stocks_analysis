import sqlite3
from pathlib import Path

import pytest

from src.fibonacci import store as store_mod
from src.fibonacci.config import FibConfig
from src.fibonacci.engine import detect
from src.fibonacci.plotting import render_fib_chart
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Timeframe

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DB_PATH = REPO_ROOT / "data" / "raw" / "market_data.sqlite"


def _real_conn():
    if not REAL_DB_PATH.exists():
        pytest.skip(f"real DB not found at {REAL_DB_PATH}")
    return sqlite3.connect(REAL_DB_PATH)


def test_smoke_real_aapl_daily_detection_and_store():
    conn = _real_conn()
    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    store_mod.create_tables(derived_conn)

    config = FibConfig()
    result = detect(conn, "AAPL", Timeframe.DAILY, config)

    assert result.quality.rows_loaded > config.min_bars
    assert isinstance(result.all_sets, list)
    assert 0 <= len(result.selected_sets) <= config.max_sets
    assert len(result.selected_sets) <= len(result.all_sets)

    for fib_set in result.all_sets:
        assert fib_set.swing.origin_date < fib_set.swing.end_date
        assert fib_set.swing.magnitude_atr >= config.min_swing_atr
        assert len(fib_set.levels) == len(config.retracement_ratios) + len(config.extension_ratios)
        for level in fib_set.levels:
            if level.kind.value == "retracement":
                # Always strictly between two real (positive) historical
                # prices. Extensions have no such floor -- a large enough
                # ratio on a big down-swing can legitimately extrapolate
                # below zero; that's correct linear extrapolation, not a bug.
                assert level.price > 0

    run_id = derived_db.record_run(
        derived_conn, "fibonacci", "AAPL", "daily", None, "{}",
        result.quality.rows_dropped, result.quality.unreliable,
    )
    for fib_set in result.selected_sets:
        store_mod.upsert_fib_set(derived_conn, fib_set, run_id)

    stored_count = derived_conn.execute("SELECT COUNT(*) FROM fib_sets").fetchone()[0]
    assert stored_count == len(result.selected_sets)

    conn.close()
    derived_conn.close()


def test_smoke_real_aapl_weekly_detection_does_not_crash():
    conn = _real_conn()
    config = FibConfig()

    result = detect(conn, "AAPL", Timeframe.WEEKLY, config)

    assert result.quality.rows_loaded > 0
    assert isinstance(result.selected_sets, list)

    conn.close()


def test_smoke_render_chart_for_real_selected_sets():
    conn = _real_conn()
    config = FibConfig()
    result = detect(conn, "AAPL", Timeframe.DAILY, config)
    if not result.selected_sets:
        pytest.skip("no fib sets detected for AAPL under default config -- nothing to plot")

    bars, _ = data_mod.load_and_validate(conn, "AAPL", Timeframe.DAILY)
    fig = render_fib_chart(bars, result.selected_sets)

    assert len(fig.data) > 0  # candlestick + at least one level/swing trace

    conn.close()


def test_smoke_ticker_with_too_little_history_is_skipped_not_crashed():
    conn = _real_conn()
    config = FibConfig()

    # GEVO is called out in market_common's own docs as a thin/edge-case
    # ticker (e.g. zero bars_1w rows) -- reuse it here as a real-data
    # "does this degrade gracefully" check rather than requiring it to
    # actually be too short (if it turns out to have plenty of history,
    # this just becomes an ordinary successful-detection assertion).
    result = detect(conn, "GEVO", Timeframe.DAILY, config)

    assert result.quality is not None
    if result.skip_reason is not None:
        assert result.all_sets == []
        assert result.selected_sets == []
    else:
        assert isinstance(result.selected_sets, list)

    conn.close()
