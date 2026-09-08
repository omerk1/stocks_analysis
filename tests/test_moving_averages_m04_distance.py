"""Mechanics test for M4's decile_table (PREREGISTRATION.md, 2026-09-08) --
same spirit as Phase 1's synthetic gate: confirm the machinery recovers a
known, planted, monotonic decile->return relationship before trusting it
on real data. Not a replacement for Phase 1's gate (which validates
`apply_lag`/`forward_return`/`c1_delta` directly) -- this is one level up,
checking `decile_table`'s own bucketing + effective-N + threshold-flagging
logic specifically.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.modules import m04_distance as m04


def test_decile_table_recovers_a_planted_monotonic_effect():
    n_tickers = 10
    n_dates = 40
    dates = pd.bdate_range("2020-01-01", periods=n_dates)

    rows = [
        {"date": date, "ticker": f"T{i}", "feat": float(i), "fwd_ret_21": i * 0.01}
        for date in dates
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)
    panel["mom_tercile"] = 0
    panel["vol_tercile"] = 0
    panel["sector"] = "X"

    table = m04.decile_table(panel, "feat")

    assert len(table) == n_tickers
    assert table["c1"].is_monotonic_increasing
    assert table["c1"].iloc[0] < 0  # lowest decile trails the rest
    assert table["c1"].iloc[-1] > 0  # highest decile beats the rest

    # One ticker per decile by construction -- correctly flagged as too
    # sparse by DESIGN §6.9's n_tickers >= 30 bar, not silently accepted.
    assert table["below_threshold"].all()
    assert (table["n_tickers"] == 1).all()
    assert (table["n_dates"] == n_dates).all()


def test_prepare_adds_forward_return_and_c2_match_columns():
    n_tickers = 5
    n_dates = 300  # past mom_12_1's 252-day warmup
    dates = pd.bdate_range("2020-01-01", periods=n_dates)

    rows = [
        {"date": date, "ticker": f"T{i}", "close": 100.0 + i + d_idx * 0.01,
         "mom_12_1": float(i), "realized_vol_63": float(i)}
        for d_idx, date in enumerate(dates)
        for i in range(n_tickers)
    ]
    panel = pd.DataFrame(rows)

    prepared = m04.prepare(panel)

    assert "fwd_ret_21" in prepared.columns
    assert {"mom_tercile", "vol_tercile"}.issubset(prepared.columns)
    assert prepared["mom_tercile"].dropna().between(0, 2).all()


def test_decile_table_rejects_nothing_silently_when_c2_match_cols_missing():
    # If a caller forgets prepare(), the missing C2 match columns should
    # surface as a clear KeyError, not a silently wrong/empty C2 column.
    panel = pd.DataFrame(
        {"date": ["d1"], "ticker": ["T0"], "feat": [1.0], "fwd_ret_21": [0.01]}
    )
    with pytest.raises(KeyError):
        m04.decile_table(panel, "feat")
