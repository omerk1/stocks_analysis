"""Tests for M15's synthesis module (`modules/synthesis.py`,
PREREGISTRATION.md 2026-09-25). Synthetic fixtures only -- mechanics (the
tail-flag reuse, population construction, overlap-rate arithmetic), not a
real-data result (that's the real-panel run, logged separately). Track A
diagnostic: no CI/kill-criterion mechanics to test here, unlike the
Track B modules' own test files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import synthesis


N_TICKERS = 20
N_DAYS = 60


def _base_panel(n_tickers: int = N_TICKERS, n_days: int = N_DAYS) -> pd.DataFrame:
    """A synthetic panel with every raw column `slope_magnitude.prepare`
    and `pattern_context.prepare` need. `slope_log_21_sma_50` is set to a
    ticker index (0..n_tickers-1), constant across all dates, so
    `cross_sectional_bucket`'s per-date decile rank is identical and
    deterministic on every date -- deciles 0/1 are always the lowest two
    tickers, deciles (N_DECILES-2)/(N_DECILES-1) always the highest two
    (`TAIL_DECILES = (0, 1, 8, 9)` at `N_DECILES=10`, so with 20 tickers
    that is exactly tickers 0-3 and 16-19, 8 of 20 -- an exact 0.40
    unconditional tail rate by construction, not an approximation).
    `slope_log_21_sma_20`/`_200` are set to the same values (unused by
    this module, but `slope_magnitude.prepare` loops over all three
    lookbacks and would KeyError without them).
    """
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        close = 100 + np.linspace(0, 1, n_days)  # smooth, no large-move noise
        above_sma_50 = pd.array([False] * 29 + [True] * (n_days - 29), dtype="boolean")
        frame = pd.DataFrame({
            "ticker": ticker,
            "date": dates,
            "close": close,
            "above_sma_50": above_sma_50,
            # Per-ticker variation (not constant) is required: cross_sectional_bucket's
            # qcut needs distinct values per date to form real terciles -- a
            # constant column returns NaN for every row and silently drops every
            # reclaim event via the module's own dropna(subset=[..., "mom_tercile",
            # "vol_tercile"]).
            "mom_12_1": 0.05 + 0.001 * i,
            "realized_vol_63": 0.02 + 0.0005 * i,
            "mom_1_0": 0.001 * i,
            "sector": "tech",
            "slope_log_21_sma_20": float(i),
            "slope_log_21_sma_50": float(i),
            "slope_log_21_sma_200": float(i),
        })
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def _patterns(vcp_tickers: list[str], other_tickers: list[str], formation_end: str) -> pd.DataFrame:
    rows = []
    for ticker in vcp_tickers:
        rows.append({"ticker": ticker, "formation_end": pd.Timestamp(formation_end), "pattern_type": "vcp"})
    for ticker in other_tickers:
        rows.append({"ticker": ticker, "formation_end": pd.Timestamp(formation_end), "pattern_type": "double_top"})
    return pd.DataFrame(rows)


def test_attach_slope_tail_flag_matches_ticker_index_construction():
    panel = _base_panel()
    flags = synthesis.attach_slope_tail_flag(panel)
    assert set(flags.columns) == {"ticker", "date", "in_slope_tail_50"}
    per_ticker = flags.groupby("ticker")["in_slope_tail_50"].first()
    tail_tickers = {f"T{i}" for i in (0, 1, 2, 3, 16, 17, 18, 19)}
    for ticker, flag in per_ticker.items():
        assert bool(flag) == (ticker in tail_tickers), ticker
    # Constant per ticker across every date (slope value never varies by date here).
    for ticker in per_ticker.index:
        assert flags.loc[flags["ticker"] == ticker, "in_slope_tail_50"].nunique() == 1


def test_attach_slope_tail_flag_preserves_nan_not_false():
    panel = _base_panel(n_tickers=12)
    nan_ticker_rows = panel["ticker"] == "T0"
    panel.loc[nan_ticker_rows, "slope_log_21_sma_50"] = np.nan
    flags = synthesis.attach_slope_tail_flag(panel)
    t0_flags = flags.loc[flags["ticker"] == "T0", "in_slope_tail_50"]
    assert t0_flags.isna().all(), "NaN input must stay NaN, not collapse to False (CLAUDE.md invariant #9)"
    other_flags = flags.loc[flags["ticker"] != "T0", "in_slope_tail_50"]
    assert not other_flags.isna().any()


def test_build_reclaim_populations_membership_counts():
    panel = _base_panel()
    vcp_tickers = ["T0", "T1", "T4", "T5"]  # 2 tail (T0,T1), 2 non-tail (T4,T5)
    double_top_tickers = ["T2", "T6", "T7", "T8"]  # 1 tail (T2), 3 non-tail
    patterns_all = _patterns(vcp_tickers, double_top_tickers, formation_end="2020-02-10")

    populations = synthesis.build_reclaim_populations(panel, patterns_all)
    assert set(populations) == {"all_reclaims", "any_pattern_reclaims", "vcp_reclaims"}

    all_reclaims = populations["all_reclaims"]
    assert all_reclaims["ticker"].nunique() == N_TICKERS  # every ticker reclaims exactly once

    any_pattern = populations["any_pattern_reclaims"]
    assert set(any_pattern["ticker"]) == set(vcp_tickers + double_top_tickers)

    vcp = populations["vcp_reclaims"]
    assert set(vcp["ticker"]) == set(vcp_tickers)


def test_overlap_enrichment_arithmetic_matches_hand_computed_rates():
    panel = _base_panel()
    vcp_tickers = ["T0", "T1", "T4", "T5"]  # tail: T0,T1 -> 2/4 = 0.50
    double_top_tickers = ["T2", "T6", "T7", "T8"]  # any-pattern tail: T0,T1,T2 -> 3/8 = 0.375
    patterns_all = _patterns(vcp_tickers, double_top_tickers, formation_end="2020-02-10")

    result = synthesis.overlap_enrichment(panel, patterns_all)

    assert result["unconditional_rate"] == 0.40  # 8 of 20 tickers in TAIL_DECILES, by construction
    assert result["all_reclaims_rate"] == 0.40  # every ticker reclaims exactly once -> same 8/20
    assert result["n_any_pattern_reclaims"] == 8
    assert result["any_pattern_reclaims_rate"] == 0.375  # 3 of 8
    assert result["n_vcp_reclaims"] == 4
    assert result["vcp_overlap_rate"] == 0.50  # 2 of 4

    assert result["enrichment_vs_unconditional"] == 0.50 / 0.40
    assert result["enrichment_vs_all_reclaims"] == 0.50 / 0.40
    assert result["enrichment_vs_any_pattern_reclaims"] == 0.50 / 0.375


def test_overlap_enrichment_zero_overlap_case():
    panel = _base_panel()
    vcp_tickers = ["T5", "T6", "T7", "T8"]  # all non-tail -> overlap_rate == 0.0
    patterns_all = _patterns(vcp_tickers, [], formation_end="2020-02-10")

    result = synthesis.overlap_enrichment(panel, patterns_all)
    assert result["vcp_overlap_rate"] == 0.0
    assert result["enrichment_vs_unconditional"] == 0.0
