"""Mechanics test for M11's cross-sectional module (PREREGISTRATION.md,
2026-09-09) -- same spirit as M4's own decile_table test: confirm the
machinery recovers a known, planted, monotonic rank/return relationship
before trusting it on real data.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.modules import cross_sectional as xsec


def _planted_panel(n_tickers=10, n_dates=60):
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = [
        {
            "date": date, "ticker": f"T{i}", "feat_sma_20": float(i),
            "fwd_ret_21": i * 0.01, "sector": "X" if i % 2 == 0 else "Y",
        }
        for date in dates
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)
    panel["vol_tercile"] = 0
    return panel


def test_daily_rank_ic_is_one_for_a_perfectly_monotonic_relationship():
    panel = _planted_panel(n_tickers=40)  # >= MIN_TICKERS so no date is dropped

    ic = xsec.daily_rank_ic(panel, "feat_sma_20", "fwd_ret_21")

    assert (ic.dropna() - 1.0).abs().max() < 1e-9


def test_daily_rank_ic_drops_dates_below_min_tickers():
    panel = _planted_panel(n_tickers=5)  # < MIN_TICKERS (30)

    ic = xsec.daily_rank_ic(panel, "feat_sma_20", "fwd_ret_21")

    assert ic.isna().all()


def test_cell_result_recovers_a_planted_monotonic_effect():
    panel = _planted_panel(n_tickers=40, n_dates=100)

    result = xsec.cell_result(panel, "feat", 20, 21, block_length=10, n_boot=100, seed=0)

    assert result["ic"]["point_estimate"] == pytest.approx(1.0)
    assert result["ic"]["ci_low"] > xsec.IC_FLOOR
    assert result["spread_c1"]["point_estimate"] > 0
    assert result["spread_c1"]["ci_low"] > 0
    assert result["n_dates"] == 100
    assert result["n_tickers"] == 40
    assert not result["below_threshold"]


def test_cell_result_neutralized_spread_matches_c1_when_sector_balanced():
    # With `sector` alternating T0..Tn evenly and no sector-return effect
    # baked in, the sector-neutralized spread should land close to the
    # unneutralized C1 spread -- a sanity check that the neutralization
    # layer isn't silently distorting a case where it shouldn't matter.
    panel = _planted_panel(n_tickers=40, n_dates=100)

    result = xsec.cell_result(panel, "feat", 20, 21, block_length=10, n_boot=100, seed=0)

    assert result["spread_neutralized"]["point_estimate"] == pytest.approx(
        result["spread_c1"]["point_estimate"], abs=1e-6
    )


def test_prepare_adds_forward_returns_and_vol_tercile():
    n_tickers, n_dates = 5, 10
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = [
        {"date": date, "ticker": f"T{i}", "close": 100.0 + i + d_idx * 0.01,
         "realized_vol_63": float(i)}
        for d_idx, date in enumerate(dates)
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)

    prepared = xsec.prepare(panel, horizons=(5, 21))

    assert {"fwd_ret_5", "fwd_ret_21", "vol_tercile"}.issubset(prepared.columns)
    assert prepared["vol_tercile"].dropna().between(0, 2).all()


def test_decile_turnover_hurdle_is_zero_for_a_never_changing_decile():
    n_tickers, n_dates = 10, 50
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = [
        {"ticker": f"T{i}", "decile": i % xsec.N_DECILES}
        for _ in dates
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)

    result = xsec.decile_turnover_hurdle(panel, "decile")

    # Every row has the same decile every "day" (no date column driving
    # variation here) -- a ticker's decile membership never flips, so
    # turnover and the resulting hurdle should both be zero.
    assert result["signals_per_year_combined"] == pytest.approx(0.0)
    assert result["cost_hurdle_annual"] == pytest.approx(0.0)


def test_run_grid_covers_the_pre_registered_cells():
    # run_grid calls prepare() internally, which needs real `close` prices
    # (not a pre-set fwd_ret column) and enough dates for the default
    # block_length=42 (>= 3 blocks' worth, DESIGN §6.2/MIN_BLOCKS).
    n_tickers, n_dates = 15, 150
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = [
        {
            "date": date, "ticker": f"T{i}", "close": 100.0 + i + d_idx * 0.01,
            "sector": "X" if i % 2 == 0 else "Y", "realized_vol_63": float(i),
            "cross_sectional_rank": float(i),  # varies by ticker, constant across dates
        }
        for d_idx, date in enumerate(dates)
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)
    for feature, lookback, _ in (xsec.PRIMARY_CELL, *xsec.SECONDARY_CELLS, *xsec.COMPANION_CELLS):
        col = f"{feature}_sma_{lookback}"
        if col not in panel.columns:
            panel[col] = panel["cross_sectional_rank"]

    results = xsec.run_grid(panel, block_length=10, n_boot=50, seed=0)

    expected_keys = {
        "dist_pct_sma_20_h21", "dist_pct_sma_50_h21", "dist_pct_sma_200_h21",
        "dist_pct_sma_20_h5", "dist_pct_sma_20_h63",
        "dist_atr_sma_20_h21", "dist_z_sma_20_h21",
    }
    assert set(results.keys()) == expected_keys
