"""Tests for M5's module logic (`modules/touch_bounce.py`),
PREREGISTRATION.md 2026-09-17. Event-extraction correctness itself is
covered in `test_moving_averages_touch.py`; these tests exercise the
group-pooling, C1/C2 delta, and kill-criterion logic built on top of it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.features.placebo_ma import GROUPS, dist_atr_column
from src.signals.moving_averages.features.touch import CHOP, FROM_ABOVE, HOLD
from src.signals.moving_averages.modules import touch_bounce as tb


def _synthetic_events(n_dates=120, n_per_date=40, focal_hold_rate=0.7, synthetic_hold_rate=0.5, seed=0):
    """A pooled event table shaped like `group_event_table`'s output:
    `n_per_date` focal events and `n_per_date` synthetic events per date,
    `hold_flag` drawn with different Bernoulli rates for focal vs.
    synthetic so the module's delta statistic has a known, planted answer.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(n_per_date):
            focal_hold = rng.random() < focal_hold_rate
            synthetic_hold = rng.random() < synthetic_hold_rate
            rows.append({
                "ticker": f"F{i}", "date": date, "direction": FROM_ABOVE, "is_focal": True,
                "hold_flag": float(focal_hold), "outcome": HOLD if focal_hold else CHOP,
                "mom_tercile": i % 3, "vol_tercile": i % 2, "sector": "X",
            })
            rows.append({
                "ticker": f"S{i}", "date": date, "direction": FROM_ABOVE, "is_focal": False,
                "hold_flag": float(synthetic_hold), "outcome": HOLD if synthetic_hold else CHOP,
                "mom_tercile": i % 3, "vol_tercile": i % 2, "sector": "X",
            })
    return pd.DataFrame(rows)


def test_cell_row_detects_a_real_planted_hold_rate_gap():
    events = _synthetic_events(focal_hold_rate=0.75, synthetic_hold_rate=0.45, n_dates=150)

    cell = tb._cell_row(events, FROM_ABOVE, {"group": "synthetic"}, block_length=10, n_boot=200, seed=0)

    assert cell["c2"] > 0
    assert cell["c2_ci_low"] > 0
    assert not cell["below_threshold"]


def test_cell_row_ci_spans_near_zero_when_focal_and_synthetic_match():
    events = _synthetic_events(focal_hold_rate=0.5, synthetic_hold_rate=0.5, n_dates=150, seed=1)

    cell = tb._cell_row(events, FROM_ABOVE, {"group": "synthetic"}, block_length=10, n_boot=200, seed=0)

    # No planted gap -- the CI should span zero, unlike the real-gap case
    # above whose CI excludes zero entirely on the same sample size.
    assert cell["c2_ci_low"] <= 0 <= cell["c2_ci_high"]


def test_evaluate_kill_criterion_module_killed_when_every_cell_below_floor():
    primary = pd.DataFrame({"c2_ci_low": [-0.005, -0.01], "c2_ci_high": [0.005, 0.015]})

    result = tb.evaluate_kill_criterion(primary)

    assert result["module_killed"] is True
    assert result["n_cells_killed"] == 2


def test_evaluate_kill_criterion_not_killed_when_one_cell_survives():
    primary = pd.DataFrame({"c2_ci_low": [-0.005, 0.03], "c2_ci_high": [0.005, 0.05]})

    result = tb.evaluate_kill_criterion(primary)

    assert result["module_killed"] is False
    assert result["n_cells_killed"] == 1


def test_group_event_table_tags_focal_and_pools_every_neighbor():
    # A small real panel exercising features/touch.py end-to-end for one
    # group (sma50: focal 50, neighbors 47/53), confirming group_event_table
    # actually wires touch_events + is_focal + the C2 context merge
    # together correctly, not just the downstream stats.
    dates = pd.bdate_range("2021-01-04", periods=9)
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.55, 0.5, 0.45, 0.9]
    spec = GROUPS["sma50"]
    data = {"ticker": "AAA", "date": dates, "mom_tercile": 0, "vol_tercile": 0, "sector": "X"}
    for lookback in (spec["focal"], *spec["neighbors"]):
        data[dist_atr_column("sma", lookback)] = values
    panel = pd.DataFrame(data)

    pooled = tb.group_event_table(panel, "sma50")

    assert set(pooled["is_focal"]) == {True, False}
    assert (pooled["is_focal"] == True).sum() == 1  # noqa: E712 -- one focal touch event
    assert (pooled["is_focal"] == False).sum() == len(spec["neighbors"])  # noqa: E712
    assert pooled["mom_tercile"].notna().all()  # C2 context merged in
