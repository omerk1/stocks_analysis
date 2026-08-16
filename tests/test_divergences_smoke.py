"""Real-ticker smoke test against the local, fully-populated raw DB -- no
network calls, no synthetic data. Just needs to not crash and produce
sane-looking output; the synthetic tests own exact-value correctness.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data_processing import db
from src.divergences.config import DivergenceConfig
from src.divergences.detect import compute_indicator_series, detect
from src.divergences.models import Direction
from src.divergences.plotting import render_divergence_chart
from src.divergences.store import create_divergences_table, upsert_divergences
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Timeframe

DB_PATH = "data/raw/market_data.sqlite"


@pytest.fixture
def conn():
    connection = db.get_connection(DB_PATH)
    yield connection
    connection.close()


def _has_data(connection, ticker: str) -> bool:
    row = connection.execute(
        "SELECT COUNT(*) FROM bars_1d WHERE ticker = ? AND source = 'yfinance'", (ticker,)
    ).fetchone()
    return row is not None and row[0] > 0


def test_aapl_daily_detection_runs_without_crashing_and_looks_sane(conn):
    if not _has_data(conn, "AAPL"):
        pytest.skip("AAPL not present in local market_data.sqlite")

    config = DivergenceConfig()
    divergences, report, skip_reason = detect(conn, "AAPL", Timeframe.DAILY, config)

    assert skip_reason is None
    assert report.rows_loaded > config.min_bars

    for d in divergences:
        assert d.ticker == "AAPL"
        assert d.timeframe == Timeframe.DAILY
        assert d.direction in (Direction.BULLISH, Direction.BEARISH)
        assert 0.0 <= d.strength <= 1.0
        assert pd.Timestamp(d.p1_date) < pd.Timestamp(d.p2_date)
        assert pd.Timestamp(d.p2_date) <= pd.Timestamp(d.appeared_at)
        assert pd.Timestamp(d.confirmed_at) >= pd.Timestamp(d.appeared_at)
        if d.direction == Direction.BEARISH:
            assert d.i2_value < d.i1_value
        else:
            assert d.i2_value > d.i1_value
        # Outcome tracking: None only for a divergence confirmed on the
        # data's very last available bar (no bars left to walk yet) --
        # true for at most one divergence in practice, everything else
        # should resolve.
        if d.outcome_computed_through is not None:
            assert pd.Timestamp(d.outcome_computed_through) > pd.Timestamp(d.confirmed_at)
            assert d.max_favorable_move_atr is not None
            assert d.max_favorable_move_atr >= 0.0
        if d.invalidated:
            assert d.invalidated_at is not None


def test_aapl_weekly_detection_runs_without_crashing(conn):
    if not _has_data(conn, "AAPL"):
        pytest.skip("AAPL not present in local market_data.sqlite")

    config = DivergenceConfig()
    divergences, report, skip_reason = detect(conn, "AAPL", Timeframe.WEEKLY, config)

    assert skip_reason is None or report.rows_loaded < config.min_bars
    assert isinstance(divergences, list)


def test_all_default_indicators_run_end_to_end_and_store_roundtrips(conn):
    if not _has_data(conn, "AAPL"):
        pytest.skip("AAPL not present in local market_data.sqlite")

    config = DivergenceConfig()  # indicators = ["rsi", "macd_hist", "obv"]
    divergences, report, skip_reason = detect(conn, "AAPL", Timeframe.DAILY, config)
    assert skip_reason is None

    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    create_divergences_table(derived_conn)
    run_id = derived_db.record_run(
        derived_conn, "divergences", "AAPL", "daily", None, "{}",
        report.rows_dropped, report.unreliable,
    )
    for d in divergences:
        d.run_id = run_id
    upsert_divergences(derived_conn, divergences, run_id)

    stored_count = derived_conn.execute("SELECT COUNT(*) FROM divergences").fetchone()[0]
    assert stored_count == len(divergences)

    # Every real row gets real confluence fields -- never left NULL/unset --
    # regardless of whether it actually clustered with anything.
    confluence_rows = derived_conn.execute(
        "SELECT confluence_count, agreeing_indicators FROM divergences"
    ).fetchall()
    assert confluence_rows
    for confluence_count, agreeing_indicators in confluence_rows:
        assert confluence_count >= 1
        assert agreeing_indicators

    # Re-run the exact same detection and upsert again -- row count must
    # not double (see test_divergences_synthetic's dedicated idempotency
    # test for the natural-key mechanics; this just confirms it holds
    # end-to-end against real data too).
    divergences_again, _report2, _skip2 = detect(conn, "AAPL", Timeframe.DAILY, config)
    upsert_divergences(derived_conn, divergences_again, run_id)
    stored_count_after_rerun = derived_conn.execute("SELECT COUNT(*) FROM divergences").fetchone()[0]
    assert stored_count_after_rerun == stored_count

    derived_conn.close()


def test_plotting_produces_html_for_aapl(conn, tmp_path):
    if not _has_data(conn, "AAPL"):
        pytest.skip("AAPL not present in local market_data.sqlite")

    config = DivergenceConfig()
    divergences, _report, skip_reason = detect(conn, "AAPL", Timeframe.DAILY, config)
    assert skip_reason is None

    bars, _ = data_mod.load_and_validate(conn, "AAPL", Timeframe.DAILY)
    rsi_series = compute_indicator_series(bars, "rsi", config)
    fig = render_divergence_chart(bars, rsi_series, divergences, "rsi", ticker="AAPL")

    out = tmp_path / "aapl_divergences.html"
    fig.write_html(out)
    assert out.exists()
    assert out.stat().st_size > 0
