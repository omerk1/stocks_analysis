"""Tests for the §7.5 placebo test's feature build (`features/placebo_ma.py`)
and module logic (`modules/placebo_levels.py`), PREREGISTRATION.md
2026-09-12.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.signals.moving_averages.features import distance, ma
from src.signals.moving_averages.features.placebo_ma import GROUPS, build_placebo_panel, dist_pct_column
from src.signals.moving_averages.modules import placebo_levels as pl


# ---- build_placebo_panel: lag correctness, same convention as build_panel ----

@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _seed_ticker(conn: sqlite3.Connection, ticker: str, closes: list[float], start: str) -> None:
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    bars = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close,
         "volume": 1_000_000.0, "is_partial": 0},
        index=idx,
    )
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, bars)


def test_build_placebo_panel_lags_dist_pct_relative_to_the_raw_computation(conn):
    n = 260
    rng = np.random.default_rng(0)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1.0, n)))
    _seed_ticker(conn, "AAA", closes, "2020-01-01")

    panel = build_placebo_panel(conn, ["AAA"])

    close_series = pd.Series(closes, index=pd.bdate_range("2020-01-01", periods=n))
    raw_sma213 = ma.compute_ma(close_series, "sma", 213)
    raw_dist = distance.dist_pct(close_series, raw_sma213)

    col = dist_pct_column("sma", 213)
    aaa = panel.set_index("date")[col]
    for i in range(214, n):  # skip the sma_213 warmup region
        row_date = close_series.index[i]
        prior_date = close_series.index[i - 1]
        assert aaa.loc[row_date] == pytest.approx(raw_dist.loc[prior_date], rel=1e-5)


def test_build_placebo_panel_does_not_bleed_lag_across_ticker_boundaries(conn):
    n = 30
    _seed_ticker(conn, "AAA", [100.0 + i for i in range(n)], "2020-01-01")
    _seed_ticker(conn, "BBB", [500.0 - i for i in range(n)], "2020-01-01")

    panel = build_placebo_panel(conn, ["AAA", "BBB"])

    bbb_first_row = panel[panel["ticker"] == "BBB"].sort_values("date").iloc[0]
    assert pd.isna(bbb_first_row[dist_pct_column("sma", 47)])


def test_build_placebo_panel_has_every_group_focal_and_neighbor_column(conn):
    _seed_ticker(conn, "AAA", [100.0 + i * 0.1 for i in range(40)], "2020-01-01")

    panel = build_placebo_panel(conn, ["AAA"])

    for spec in GROUPS.values():
        family = spec["family"]
        for lookback in (spec["focal"], *spec["neighbors"]):
            assert dist_pct_column(family, lookback) in panel.columns

    assert {"mom_12_1", "realized_vol_63", "sector"}.issubset(panel.columns)
    assert panel[dist_pct_column("sma", 200)].dtype == np.float32


# ---- module mechanics: group_diff / group_verdict, planted panels ----

def _planted_group_panel(n_dates=120, n_tickers=20, focal_gradient=0.02, neighbor_gradient=0.0, seed=0):
    """Synthetic panel shaped like `prepare()`'s output for the "sma200"
    group (focal SMA200 + all 4 of its neighbors): focal `dist_pct`
    carries a real, planted gradient in `fwd_ret_21`; every neighbor
    `dist_pct` carries the same `neighbor_gradient` (0.0 -> no gradient,
    i.e. clean placebo neighbors; equal to `focal_gradient` -> neighbors
    indistinguishable from focal, the "killed" case).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    neighbor_scale = (neighbor_gradient / focal_gradient) if focal_gradient else 0.0
    rows = []
    for date in dates:
        for i in range(n_tickers):
            rank = i / (n_tickers - 1) - 0.5  # -0.5 .. 0.5
            row = {
                "date": date, "ticker": f"T{i}",
                "dist_pct_sma_200": rank,
                "fwd_ret_21": rank * focal_gradient + rng.normal(0, 0.001),
                "mom_tercile": 0, "vol_tercile": 0, "sector": "X",
            }
            for neighbor in GROUPS["sma200"]["neighbors"]:
                # A tiny independent noise term so a zero-gradient neighbor
                # still has cross-sectional variation to bucket into
                # deciles (a perfectly constant column can't be `qcut`
                # into 10 distinct buckets) -- it carries no relationship
                # to `fwd_ret_21` either way, which is the actual point.
                row[dist_pct_column("sma", neighbor)] = rank * neighbor_scale + rng.normal(0, 1e-6)
            rows.append(row)
    return pd.DataFrame(rows)


def test_group_diff_excludes_zero_when_neighbor_has_no_gradient():
    panel = _planted_group_panel(focal_gradient=0.05, neighbor_gradient=0.0, n_dates=150)

    diff = pl.group_diff(panel, "sma", 200, 187, block_length=10, n_boot=150, seed=0)

    assert diff["ci_low"] > 0


def test_group_diff_straddles_zero_when_neighbor_matches_focal():
    # Neighbor carries the same ranking (and thus the same decile
    # assignment) and the same gradient as focal -- the two spreads must
    # be indistinguishable, point estimate and CI both ~0.
    panel = _planted_group_panel(focal_gradient=0.05, neighbor_gradient=0.05, n_dates=150)

    diff = pl.group_diff(panel, "sma", 200, 187, block_length=10, n_boot=150, seed=0)

    assert diff["point_estimate"] == pytest.approx(0.0, abs=1e-6)
    assert diff["ci_low"] <= 0 <= diff["ci_high"]


def test_group_verdict_is_confirmed_when_focal_beats_every_neighbor():
    focal_cell = {"spread_c2": {"ci_low": 0.01, "ci_high": 0.02}}
    diffs = {187: {"ci_low": 0.005, "ci_high": 0.015}, 193: {"ci_low": 0.003, "ci_high": 0.01}}

    assert pl.group_verdict(focal_cell, diffs) == "confirmed"


def test_group_verdict_is_killed_when_any_neighbor_diff_spans_zero():
    focal_cell = {"spread_c2": {"ci_low": 0.01, "ci_high": 0.02}}
    diffs = {187: {"ci_low": -0.001, "ci_high": 0.015}, 193: {"ci_low": 0.003, "ci_high": 0.01}}

    assert pl.group_verdict(focal_cell, diffs) == "killed"


def test_group_verdict_is_killed_when_focal_itself_spans_zero():
    focal_cell = {"spread_c2": {"ci_low": -0.001, "ci_high": 0.02}}
    diffs = {187: {"ci_low": 0.005, "ci_high": 0.015}}

    assert pl.group_verdict(focal_cell, diffs) == "killed"


def test_run_group_reports_effective_n_and_below_threshold_flag():
    panel = _planted_group_panel(focal_gradient=0.05, neighbor_gradient=0.0, n_dates=150, n_tickers=40)
    prepared = panel  # already carries fwd_ret_21/mom_tercile/vol_tercile/sector

    result = pl.run_group(prepared, "sma200", block_length=10, n_boot=100, seed=0)

    assert result["focal_cell"]["n_dates"] == 150
    assert not result["focal_cell"]["below_threshold"]
    assert set(result["neighbor_cells"].keys()) == {187, 193, 207, 213}
    assert result["verdict"] in {"confirmed", "killed"}
    if result["verdict"] == "confirmed":
        assert "cost" in result
        assert "cost_hurdle_annual" in result["cost"]
