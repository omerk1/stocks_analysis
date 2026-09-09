"""Tests for M1's baseline-state module (DESIGN.md §8; PREREGISTRATION.md,
2026-09-09) -- the row-loss diagnostic's own arithmetic, the shared C2-
eligible row set, and the kill-criterion evaluation. `state_table`/
`run_length_table` themselves are exercised end-to-end against the real
panel in the driving notebook, not re-derived here with a synthetic
fixture -- what's pinned here is the logic that must hold regardless of
what data flows through it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.modules import baseline_state as bs


def _synthetic_prepared_panel(n_dates: int = 200, n_tickers: int = 40, seed: int = 0) -> pd.DataFrame:
    """A panel already carrying `fwd_ret_21`/`mom_tercile`/`vol_tercile`/
    `sector` (i.e. post-`prepare`), with `above_sma_50` and a matching
    `run_length_bucket_sma_50`, and a deliberate slice of rows with
    missing C2 inputs (mimicking real warmup) -- enough distinct dates to
    clear `stats/inference.py`'s minimum-blocks requirement.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    tickers = [f"T{i}" for i in range(n_tickers)]

    rows = []
    for ticker in tickers:
        above = rng.random(n_dates) > 0.5
        for i, date in enumerate(dates):
            rows.append({"ticker": ticker, "date": date, "above_sma_50": bool(above[i])})
    panel = pd.DataFrame(rows)

    panel["fwd_ret_21"] = rng.normal(0, 0.02, len(panel))
    panel["mom_tercile"] = rng.integers(0, 3, len(panel)).astype(float)
    panel["vol_tercile"] = rng.integers(0, 3, len(panel)).astype(float)
    panel["sector"] = rng.choice(["Tech", "Health", "Energy"], len(panel))

    # First 10 dates per ticker: no C2 inputs yet (mimics a real warmup).
    warmup_mask = panel["date"].isin(dates[:10])
    panel.loc[warmup_mask, ["mom_tercile", "vol_tercile"]] = np.nan

    panel["above_sma_50"] = panel["above_sma_50"].astype("boolean")
    return panel


def test_cell_row_loss_diagnostic_splits_sum_to_the_total_lost():
    panel = _synthetic_prepared_panel()
    working = panel.rename(columns={"above_sma_50": "_is_event"})

    row = bs._cell_row(working, "_is_event", {"label": "test"})

    assert row["row_loss_n_missing_c2_inputs"] + row["row_loss_n_singleton_stratum"] == row["row_loss_n_lost"]
    assert row["row_loss_n_unrestricted"] - row["row_loss_n_eligible"] == row["row_loss_n_lost"]
    assert row["row_loss_n_missing_c2_inputs"] > 0  # the planted warmup rows


def test_cell_row_c0_unrestricted_and_c0_use_different_row_sets():
    panel = _synthetic_prepared_panel()
    working = panel.rename(columns={"above_sma_50": "_is_event"})

    row = bs._cell_row(working, "_is_event", {"label": "test"})

    # Both are the same statistic on different row populations -- must not
    # silently be the same number (would indicate the restriction is a
    # no-op, e.g. if the mask were mis-wired).
    assert row["row_loss_n_unrestricted"] > row["row_loss_n_eligible"]


def test_cell_row_reports_pooled_as_the_c0_dilution_factor_times_c0():
    # PREREGISTRATION.md's "waterfall re-rendered" addendum: pooled is the
    # actual C0 leg of the shrinkage waterfall; c0 is diluted by the event
    # group's own population share p, so c0 == (1-p) * pooled exactly on
    # the same (restricted) row set both are computed from.
    panel = _synthetic_prepared_panel()
    working = panel.rename(columns={"above_sma_50": "_is_event"})

    row = bs._cell_row(working, "_is_event", {"label": "test"})
    p = row["n_events"] / row["row_loss_n_eligible"]

    assert row["c0"] == pytest.approx((1 - p) * row["pooled"])


def test_evaluate_kill_criterion_uses_the_max_absolute_ci_edge():
    primary = pd.DataFrame(
        {
            "c2_ci_low": [-0.0005, -0.0015, -0.02],
            "c2_ci_high": [0.0008, -0.0002, -0.01],
        }
    )

    result = bs.evaluate_kill_criterion(primary)

    # Row 0: max(|-.0005|, |.0008|) = .0008 < .001 -> killed.
    # Row 1: max(|-.0015|, |-.0002|) = .0015 >= .001 -> not killed.
    # Row 2 (large real negative effect): max(.02, .01) = .02 >= .001 -> not killed.
    assert result["cell_killed"] == [True, False, False]
    assert result["module_killed"] is False
    assert result["n_cells_killed"] == 1


def test_evaluate_kill_criterion_fires_only_when_every_primary_cell_is_killed():
    all_dead = pd.DataFrame({"c2_ci_low": [-0.0003, -0.0004], "c2_ci_high": [0.0002, 0.0001]})

    result = bs.evaluate_kill_criterion(all_dead)

    assert result["module_killed"] is True
    assert result["n_cells_killed"] == 2


def test_evaluate_kill_criterion_is_a_magnitude_test_not_a_signed_one():
    # A large, real, negative effect (e.g. a below-MA cell) must not be
    # treated as "killed" just because its value is < 0.10% in the signed
    # sense -- PREREGISTRATION.md's M1 entry, "Magnitude, not signed."
    primary = pd.DataFrame({"c2_ci_low": [-0.006], "c2_ci_high": [-0.004]})

    result = bs.evaluate_kill_criterion(primary)

    assert result["cell_killed"] == [False]
