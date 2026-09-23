"""Tests for M12 -- volume/liquidity interaction (DESIGN.md line ~971;
PREREGISTRATION.md, 2026-09-23).

`prepare()`'s full raw-panel-to-features pipeline isn't exercised
end-to-end here -- same "test the per-feature logic, not the full
pipeline plumbing" split `test_moving_averages_context_conditioning.py`
uses. These tests cover:
- `future_state`'s forward shift and NaN tail,
- `_is_reclaim`'s state-transition-day detection, including left-censored
  first-run exclusion,
- `reclaim_durability_table`/`reclaim_hold_rate_table`/
  `evaluate_kill_criterion`'s restrict-then-delta wiring on an already-
  `prepare()`-shaped synthetic frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import volume_liquidity as vl


def test_future_state_shifts_forward_within_ticker():
    panel = pd.DataFrame({
        "ticker": ["A"] * 5 + ["B"] * 5,
        "state": [True, True, False, False, True] + [False, False, False, True, True],
    })
    result = vl.future_state(panel, "state", horizon=2)

    # A's row 0 should read A's row 2's value (False); B's row 0 should
    # read B's row 2's value (False) -- never bleeding across tickers.
    assert result.iloc[0] == False  # noqa: E712
    assert result.iloc[2] == True  # noqa: E712  (A's row 2 -> row 4 = True)
    # Final `horizon` rows of each ticker are NaN (no future value yet).
    assert pd.isna(result.iloc[3])
    assert pd.isna(result.iloc[4])
    assert pd.isna(result.iloc[8])
    assert pd.isna(result.iloc[9])


def test_is_reclaim_flags_only_first_day_of_a_new_above_run():
    # Ticker A: below, below, ABOVE(reclaim), above, below, ABOVE(reclaim), above.
    # The leading "below" run is left-censored (run_id 0), but it's a
    # `False` run so it wouldn't be flagged anyway -- also add a ticker
    # whose series *starts* True, to confirm that left-censored `True`
    # first run is correctly excluded (not treated as a reclaim day 1).
    panel = pd.DataFrame({
        "ticker": ["A"] * 7 + ["B"] * 4,
        "above": pd.array(
            [False, False, True, True, False, True, True] + [True, True, False, True],
            dtype="boolean",
        ),
    })
    result = vl._is_reclaim(panel, "above")

    expected_a = [False, False, True, False, False, True, False]
    assert list(result.iloc[:7]) == expected_a

    # B's first run (True, True) is left-censored -- not a reclaim, despite
    # being the "start" of an above-state. Only the day-4 transition
    # (False -> True) counts.
    expected_b = [False, False, False, True]
    assert list(result.iloc[7:]) == expected_b


def test_is_reclaim_no_reclaims_when_never_transitions():
    panel = pd.DataFrame({"ticker": ["A"] * 5, "above": pd.array([True] * 5, dtype="boolean")})
    result = vl._is_reclaim(panel, "above")
    assert not result.any()


def _synthetic_prepared_panel(n_dates=1000, n_tickers=300, gradient=-0.02, seed=0):
    """An already-`prepare()`-shaped panel for the 3 lookbacks' reclaim
    population and facet terciles, with `fwd_ret_21`/`hold_20` carrying a
    planted gradient on the relative-volume tercile split (top vs bottom),
    matching this module's own real-data sign convention loosely (sign
    itself is arbitrary for a synthetic recovery test).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_dates)
    rows = []
    for ticker in [f"T{i}" for i in range(n_tickers)]:
        for date in dates:
            is_reclaim_20 = rng.random() < 0.05
            rel_tercile = rng.integers(0, 3)
            is_top = rel_tercile == 2
            rows.append({
                "ticker": ticker, "date": date,
                "is_reclaim_20": is_reclaim_20,
                "relative_volume_tercile": rel_tercile,
                "dollar_volume_tercile": rng.integers(0, 3),
                "vwma_divergence_20_tercile": rng.integers(0, 3),
                "fwd_ret_21": gradient * is_top + rng.normal(0, 0.01),
                "hold_20": bool(rng.random() > 0.5),
                "mom_tercile": rng.integers(0, 3), "vol_tercile": rng.integers(0, 3),
                "sector": "X",
            })
    panel = pd.DataFrame(rows)
    panel["hold_20"] = panel["hold_20"].astype("boolean")
    # Only lookback 20 is populated for this synthetic frame -- reuse the
    # module's own LOOKBACKS-driven loop by monkeypatching to just [20]
    # is unnecessary; instead restrict the tables under test to lookback
    # 20 directly (see below).
    return panel


def test_reclaim_durability_cell_recovers_planted_gradient_sign():
    panel = _synthetic_prepared_panel(gradient=-0.03)
    reclaim_pop = panel[panel["is_reclaim_20"]]
    cell = vl._cell(
        reclaim_pop, "relative_volume_tercile", "fwd_ret_21",
        {"sub_question": "relative_volume", "lookback": 20},
    )
    assert cell["c2"] < 0
    assert cell["ci_excludes_zero"] is True
    assert cell["n_events"] > 0


def test_reclaim_hold_rate_cell_wiring_matches_durability_cell_shape():
    panel = _synthetic_prepared_panel(gradient=0.0)
    reclaim_pop = panel[panel["is_reclaim_20"]].copy()
    reclaim_pop["_hold_float"] = reclaim_pop["hold_20"].astype("float64")
    cell = vl._cell(
        reclaim_pop, "relative_volume_tercile", "_hold_float",
        {"sub_question": "relative_volume", "lookback": 20},
    )
    # No planted effect on hold rate here -- just confirm the machinery
    # runs and produces a valid CI, same field shape as the durability cell.
    assert set(cell) == {
        "sub_question", "lookback", "n_events", "n_dates", "n_tickers", "below_threshold",
        "c1", "c2", "c2_ci_low", "c2_ci_high", "c2_n_dates_boot", "kill_threshold", "edge",
        "killed", "ci_excludes_zero",
    }
    assert not pd.isna(cell["c2"])


def test_evaluate_kill_criterion_fires_only_when_every_cell_killed():
    all_killed = pd.DataFrame({"c2_ci_low": [-0.0005, -0.0003], "c2_ci_high": [0.0005, 0.0004]})
    one_survives = pd.DataFrame({"c2_ci_low": [-0.0005, -0.02], "c2_ci_high": [0.0005, -0.01]})

    killed_result = vl.evaluate_kill_criterion(all_killed)
    survives_result = vl.evaluate_kill_criterion(one_survives)

    assert killed_result["module_killed"] is True
    assert survives_result["module_killed"] is False
    assert survives_result["n_cells_killed"] == 1
