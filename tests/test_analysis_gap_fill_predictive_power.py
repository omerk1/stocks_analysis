"""Synthetic tests for `src/analysis/gap_fill_predictive_power.py` (the
standalone gap fill-percentage predictive-power research script), plus one
real-data smoke test mirroring `test_divergences_smoke.py`'s
skip-if-not-present pattern.

The synthetic tests hand-build small bars frames the same way
`test_gaps_lifecycle.py` does, with exact hand-computed expected values --
this is the "does the reconstruction actually match `_penetration_pct`'s
real formula" coverage the module docstring promises, independent of
whatever happens to be in the local `analysis.sqlite`/`market_data.sqlite`.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from src.analysis.gap_fill_predictive_power import (
    build_dataset,
    compute_signals,
    correlation_report,
    load_gaps,
    reconstruct_fill_series,
    _corr_row,
    _return_pct,
)
from src.data_processing import db as raw_db
from src.gaps import store as gaps_store
from src.gaps.models import Direction, Gap, GapKind, Timeframe
from src.market_common import derived_db


def _bars(rows: list[tuple[float, float, float, float, float]], start: str = "2020-01-01") -> pd.DataFrame:
    """rows: list of (open, high, low, close, volume)."""
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _gap_row(
    created_at: str,
    zone_top: float = 100.0,
    zone_bottom: float = 90.0,
    direction: str = "bullish",
    fill_by: str = "wick",
) -> pd.Series:
    return pd.Series({
        "id": "g1", "ticker": "TEST", "timeframe": "daily", "kind": "classic",
        "direction": direction, "created_at": created_at,
        "zone_top": zone_top, "zone_bottom": zone_bottom, "fill_by": fill_by,
    })


# ---------------------------------------------------------------------------
# reconstruct_fill_series
# ---------------------------------------------------------------------------

def test_reconstruct_fill_series_matches_hand_computed_penetration_and_stops_at_full_close():
    # zone=[90,100], height=10. lows: bar1=95 -> 50%, bar2=91 -> 90%,
    # bar3=89 -> 110% clamped to 100% (fully closed here). Two more bars
    # follow in the input frame but must NOT appear in the reconstructed
    # series -- once cummax hits 100 the walk stops (see docstring).
    bars = _bars([
        (100.0, 100.5, 99.5, 100.0, 1000.0),   # bar0: created_at
        (98.0, 99.0, 95.0, 101.0, 1000.0),     # bar1: low=95 -> 50%
        (94.0, 95.0, 91.0, 102.0, 1000.0),     # bar2: low=91 -> 90%
        (92.0, 93.0, 89.0, 90.0, 1000.0),      # bar3: low=89 -> 100% (closed)
        (80.0, 81.0, 79.0, 80.0, 1000.0),      # bar4: must be excluded
        (70.0, 71.0, 69.0, 70.0, 1000.0),      # bar5: must be excluded
    ])
    gap = _gap_row(created_at=bars.index[0].isoformat())

    series = reconstruct_fill_series(bars, gap)

    assert list(series.index) == [1, 2, 3]
    assert series.loc[1, "raw_pct"] == pytest.approx(50.0)
    assert series.loc[1, "cummax_pct"] == pytest.approx(50.0)
    assert series.loc[2, "raw_pct"] == pytest.approx(90.0)
    assert series.loc[2, "cummax_pct"] == pytest.approx(90.0)
    assert series.loc[3, "raw_pct"] == pytest.approx(100.0)
    assert series.loc[3, "cummax_pct"] == pytest.approx(100.0)


def test_reconstruct_fill_series_cummax_never_decreases_on_recede():
    # zone=[90,100]. bar1 touches to 80% (low=92), bar2 recedes entirely
    # (low=105, outside the zone -> raw 0%), cummax must hold at 80%.
    bars = _bars([
        (100.0, 100.5, 99.5, 100.0, 1000.0),
        (94.0, 95.0, 92.0, 94.0, 1000.0),     # bar1: low=92 -> 80%
        (106.0, 107.0, 105.0, 106.0, 1000.0),  # bar2: low=105 -> 0% (outside)
    ])
    gap = _gap_row(created_at=bars.index[0].isoformat())

    series = reconstruct_fill_series(bars, gap)

    assert series.loc[1, "raw_pct"] == pytest.approx(80.0)
    assert series.loc[2, "raw_pct"] == pytest.approx(0.0)
    assert series.loc[2, "cummax_pct"] == pytest.approx(80.0)


def test_reconstruct_fill_series_returns_none_when_created_at_not_in_bars():
    bars = _bars([(100.0, 100.5, 99.5, 100.0, 1000.0)])
    gap = _gap_row(created_at="1999-01-01")  # not in bars' index

    assert reconstruct_fill_series(bars, gap) is None


def test_reconstruct_fill_series_returns_none_when_created_at_is_the_last_bar():
    bars = _bars([(100.0, 100.5, 99.5, 100.0, 1000.0)])
    gap = _gap_row(created_at=bars.index[0].isoformat())

    assert reconstruct_fill_series(bars, gap) is None


def test_reconstruct_fill_series_respects_fill_by_body_close_vs_wick():
    # zone=[90,100]. bar1: low=80 (deep wick) but open/close=[96,97] --
    # body_close must use min(open, close)=96 (40%), wick must use low=80 (100%).
    bars = _bars([
        (100.0, 100.5, 99.5, 100.0, 1000.0),
        (96.0, 98.0, 80.0, 97.0, 1000.0),
    ])
    wick_gap = _gap_row(created_at=bars.index[0].isoformat(), fill_by="wick")
    body_gap = _gap_row(created_at=bars.index[0].isoformat(), fill_by="body_close")

    wick_series = reconstruct_fill_series(bars, wick_gap)
    body_series = reconstruct_fill_series(bars, body_gap)

    assert wick_series.loc[1, "raw_pct"] == pytest.approx(100.0)
    assert body_series.loc[1, "raw_pct"] == pytest.approx(40.0)


def test_reconstruct_fill_series_bearish_direction():
    # Bearish gap: zone=[90,100], fill comes from price rising back UP
    # toward zone_top. bar1 high=95 -> (95-90)/10*100 = 50%.
    bars = _bars([
        (90.0, 90.5, 89.5, 90.0, 1000.0),
        (92.0, 95.0, 91.0, 93.0, 1000.0),
    ])
    gap = _gap_row(created_at=bars.index[0].isoformat(), direction="bearish")

    series = reconstruct_fill_series(bars, gap)

    assert series.loc[1, "raw_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# compute_signals
# ---------------------------------------------------------------------------

def test_compute_signals_on_a_fully_closed_series():
    series = pd.DataFrame(
        {"raw_pct": [50.0, 90.0, 100.0], "cummax_pct": [50.0, 90.0, 100.0]},
        index=pd.Index([1, 2, 3], name="bars_since_creation"),
    )
    signals = compute_signals(series, fill_threshold=50.0)

    assert signals["peak_fill_pct"] == pytest.approx(100.0)
    assert signals["bars_to_peak"] == 3
    assert signals["bars_to_threshold"] == 1  # first bar already >= 50%
    assert signals["bars_to_closed_recomputed"] == 3
    assert signals["ever_closed_recomputed"] == 1


def test_compute_signals_on_a_partial_series_that_never_reaches_threshold():
    series = pd.DataFrame(
        {"raw_pct": [10.0, 20.0, 15.0], "cummax_pct": [10.0, 20.0, 20.0]},
        index=pd.Index([1, 2, 3], name="bars_since_creation"),
    )
    signals = compute_signals(series, fill_threshold=50.0)

    assert signals["peak_fill_pct"] == pytest.approx(20.0)
    assert signals["bars_to_peak"] == 2
    assert signals["bars_to_threshold"] is None
    assert signals["bars_to_closed_recomputed"] is None
    assert signals["ever_closed_recomputed"] == 0


# ---------------------------------------------------------------------------
# _return_pct
# ---------------------------------------------------------------------------

def test_return_pct_bullish_is_unflipped_bearish_is_sign_flipped():
    bars = _bars([
        (100.0, 100.0, 100.0, 100.0, 1000.0),
        (100.0, 100.0, 100.0, 110.0, 1000.0),  # +10% raw close move
    ])

    bullish = _return_pct(bars, 0, 1, Direction.BULLISH)
    bearish = _return_pct(bars, 0, 1, Direction.BEARISH)

    assert bullish == pytest.approx(10.0)
    assert bearish == pytest.approx(-10.0)


def test_return_pct_none_past_end_of_available_bars():
    bars = _bars([(100.0, 100.0, 100.0, 100.0, 1000.0)])

    assert _return_pct(bars, 0, 5, Direction.BULLISH) is None


# ---------------------------------------------------------------------------
# load_gaps -- fill_by recovery via the runs join
# ---------------------------------------------------------------------------

def test_load_gaps_recovers_fill_by_from_the_joined_runs_config_json():
    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    gaps_store.create_gaps_table(derived_conn)

    wick_run_id = derived_db.record_run(
        derived_conn, "gaps", "AAA", "daily", None,
        json.dumps({"fill_by": "wick"}), 0, False,
    )
    body_run_id = derived_db.record_run(
        derived_conn, "gaps", "BBB", "daily", None,
        json.dumps({"fill_by": "body_close"}), 0, False,
    )
    gap_wick = Gap(
        id="w1", ticker="AAA", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
        direction=Direction.BULLISH, created_at="2020-01-01T00:00:00",
        zone_top=10.0, zone_bottom=9.0, size_atr=1.0, run_id=wick_run_id,
    )
    gap_body = Gap(
        id="b1", ticker="BBB", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
        direction=Direction.BULLISH, created_at="2020-01-01T00:00:00",
        zone_top=10.0, zone_bottom=9.0, size_atr=1.0, run_id=body_run_id,
    )
    gaps_store.upsert_gaps(derived_conn, [gap_wick], wick_run_id)
    gaps_store.upsert_gaps(derived_conn, [gap_body], body_run_id)

    df = load_gaps(derived_conn)
    derived_conn.close()

    df = df.set_index("id")
    assert df.loc["w1", "fill_by"] == "wick"
    assert df.loc["b1", "fill_by"] == "body_close"
    assert "config_json" not in df.columns


# ---------------------------------------------------------------------------
# _corr_row / correlation_report
# ---------------------------------------------------------------------------

def test_corr_row_perfect_positive_correlation():
    df = pd.DataFrame({"signal": [1.0, 2.0, 3.0, 4.0], "target": [10.0, 20.0, 30.0, 40.0]})

    row = _corr_row(df, "signal", "target")

    assert row["n"] == 4
    assert row["pearson_r"] == pytest.approx(1.0)
    assert row["spearman_rho"] == pytest.approx(1.0)


def test_corr_row_returns_none_stats_below_minimum_n():
    df = pd.DataFrame({"signal": [1.0, 2.0], "target": [10.0, 20.0]})

    row = _corr_row(df, "signal", "target")

    assert row["n"] == 2
    assert row["pearson_r"] is None
    assert row["spearman_rho"] is None


def test_corr_row_handles_constant_signal_without_raising():
    df = pd.DataFrame({"signal": [5.0, 5.0, 5.0, 5.0], "target": [1.0, 2.0, 3.0, 4.0]})

    row = _corr_row(df, "signal", "target")

    assert row["pearson_r"] is None  # undefined for a constant series, not NaN-propagated garbage


def test_correlation_report_covers_every_signal_target_horizon_combo():
    df = pd.DataFrame({
        "peak_fill_pct": [10.0, 50.0, 100.0],
        "ever_closed_recomputed": [0, 0, 1],
        "bars_to_threshold": [None, 5, 2],
        "bars_to_peak": [3, 5, 2],
        "fwd_return_from_creation_5b": [1.0, -2.0, 3.0],
        "fwd_return_from_peak_5b": [0.5, -1.0, 2.0],
    })

    corr = correlation_report(df, horizons=(5,))

    assert len(corr) == 4 * 2  # 4 signals x 2 reference points x 1 horizon
    assert set(corr["target"]) == {"fwd_return_from_creation_5b", "fwd_return_from_peak_5b"}


# ---------------------------------------------------------------------------
# build_dataset -- end-to-end against synthetic raw/derived DBs
# ---------------------------------------------------------------------------

def test_build_dataset_end_to_end_synthetic():
    raw_conn = raw_db.get_connection(":memory:")
    raw_db.create_tables(raw_conn)
    bars_df = _bars([
        (100.0, 100.5, 99.5, 100.0, 1000.0),   # bar0: created_at, close=100
        (98.0, 101.5, 95.0, 101.0, 1000.0),    # bar1: low=95 -> 50%, close=101
        (94.0, 102.5, 91.0, 102.0, 1000.0),    # bar2: low=91 -> 90%, close=102
        (92.0, 93.0, 89.0, 90.0, 1000.0),      # bar3: low=89 -> 100% (closed), close=90
        (80.0, 81.0, 79.0, 80.0, 1000.0),      # bar4: post-close, close=80
    ])
    bars_df = bars_df.assign(is_partial=0)
    raw_db.upsert_bars(raw_conn, "bars_1d", "TEST", raw_db.YFINANCE, bars_df)

    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    gaps_store.create_gaps_table(derived_conn)
    run_id = derived_db.record_run(
        derived_conn, "gaps", "TEST", "daily", None,
        json.dumps({"fill_by": "wick"}), 0, False,
    )
    gap = Gap(
        id="g1", ticker="TEST", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
        direction=Direction.BULLISH, created_at=bars_df.index[0].isoformat(),
        zone_top=100.0, zone_bottom=90.0, size_atr=1.0, run_id=run_id,
    )
    gaps_store.upsert_gaps(derived_conn, [gap], run_id)

    per_bar_rows: list = []
    df, n_skipped = build_dataset(
        raw_conn, derived_conn, horizons=(2, 3), fill_threshold=50.0, per_bar_rows=per_bar_rows,
    )
    raw_conn.close()
    derived_conn.close()

    assert n_skipped == 0
    assert len(df) == 1
    row = df.iloc[0]
    assert row["peak_fill_pct"] == pytest.approx(100.0)
    assert row["bars_to_peak"] == 3
    assert row["bars_to_threshold"] == 1
    assert row["ever_closed_recomputed"] == 1
    # fwd_return_from_creation_2b: close bar0=100 -> close bar2=102 -> +2%
    assert row["fwd_return_from_creation_2b"] == pytest.approx(2.0)
    # fwd_return_from_creation_3b: close bar0=100 -> close bar3=90 -> -10%
    assert row["fwd_return_from_creation_3b"] == pytest.approx(-10.0)
    # peak is bar3 (close=90); fwd_return_from_peak_2b needs bar3+2=bar5, doesn't exist -> None
    assert row["fwd_return_from_peak_2b"] is None
    # only bar4 (close=80) exists after peak -> horizon 1 would work, not requested here
    assert len(per_bar_rows) == 3  # bars 1, 2, 3 (walk stops once cummax hits 100)


def test_build_dataset_skips_gap_whose_created_at_predates_loaded_bars():
    raw_conn = raw_db.get_connection(":memory:")
    raw_db.create_tables(raw_conn)
    bars_df = _bars([(100.0, 100.5, 99.5, 100.0, 1000.0)], start="2021-01-01")
    bars_df = bars_df.assign(is_partial=0)
    raw_db.upsert_bars(raw_conn, "bars_1d", "TEST", raw_db.YFINANCE, bars_df)

    derived_conn = derived_db.get_connection(":memory:")
    derived_db.create_runs_table(derived_conn)
    gaps_store.create_gaps_table(derived_conn)
    run_id = derived_db.record_run(
        derived_conn, "gaps", "TEST", "daily", None, json.dumps({"fill_by": "wick"}), 0, False,
    )
    gap = Gap(
        id="g1", ticker="TEST", timeframe=Timeframe.DAILY, kind=GapKind.CLASSIC,
        direction=Direction.BULLISH, created_at="2010-01-01T00:00:00",  # not in bars_df
        zone_top=100.0, zone_bottom=90.0, size_atr=1.0, run_id=run_id,
    )
    gaps_store.upsert_gaps(derived_conn, [gap], run_id)

    df, n_skipped = build_dataset(raw_conn, derived_conn, horizons=(2,), fill_threshold=50.0)
    raw_conn.close()
    derived_conn.close()

    assert n_skipped == 1
    assert df.empty


# ---------------------------------------------------------------------------
# Real-data smoke test -- skipped if the local DBs aren't populated
# ---------------------------------------------------------------------------

RAW_DB_PATH = "data/raw/market_data.sqlite"
DERIVED_DB_PATH = "data/derived/analysis.sqlite"


def _has_real_data() -> bool:
    try:
        raw_conn = sqlite3.connect(RAW_DB_PATH)
        derived_conn = sqlite3.connect(DERIVED_DB_PATH)
    except sqlite3.OperationalError:
        return False
    try:
        row = raw_conn.execute(
            "SELECT COUNT(*) FROM bars_1d WHERE ticker='AAPL' AND source='yfinance'"
        ).fetchone()
        gaps_row = derived_conn.execute(
            "SELECT COUNT(*) FROM gaps WHERE ticker='AAPL'"
        ).fetchone()
        return bool(row and row[0] > 0 and gaps_row and gaps_row[0] > 0)
    except sqlite3.OperationalError:
        return False
    finally:
        raw_conn.close()
        derived_conn.close()


def test_real_aapl_gap_reconstruction_matches_hand_verified_values():
    """Two real AAPL FVGs, hand-verified bar-for-bar against the raw OHLC
    data (see the PR description for the full manual arithmetic): both
    resolve during the May 6 2010 flash crash. This pins the script's
    output to those hand-checked numbers as a regression test, not just a
    "did it crash" smoke test.
    """
    if not _has_real_data():
        pytest.skip("Real AAPL data not present in local market_data.sqlite/analysis.sqlite")

    raw_conn = sqlite3.connect(RAW_DB_PATH)
    derived_conn = sqlite3.connect(DERIVED_DB_PATH)
    try:
        df, _n_skipped = build_dataset(
            raw_conn, derived_conn, horizons=(5,), fill_threshold=50.0, ticker_filter="AAPL",
        )
    finally:
        raw_conn.close()
        derived_conn.close()

    g1 = df[df["created_at"] == "2010-03-24T00:00:00"]
    g2 = df[df["created_at"] == "2010-03-30T00:00:00"]
    if g1.empty or g2.empty:
        pytest.skip("Expected hand-verified AAPL gaps not present in local analysis.sqlite")

    assert g1.iloc[0]["peak_fill_pct"] == pytest.approx(100.0)
    assert g1.iloc[0]["bars_to_closed_recomputed"] == 30
    assert g2.iloc[0]["peak_fill_pct"] == pytest.approx(100.0)
    assert g2.iloc[0]["bars_to_closed_recomputed"] == 26
