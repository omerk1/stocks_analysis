"""Tests for M19's module logic (`modules/respect_history.py`,
PREREGISTRATION.md 2026-09-30). Feature correctness is covered in
`test_moving_averages_respect.py`; these exercise the respect join, the
real-minus-synthetic DiD cell, and the kill-criterion logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.respect import RESISTANCE, SUPPORT, respect_column
from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW
from src.signals.moving_averages.modules import respect_history as rh
from src.signals.moving_averages.stats.inference import block_bootstrap_delta_diff


def _events(n_dates=150, n_per_date=70, focal_lift=0.0, synth_lift=0.0, base=0.45, seed=0):
    """A pooled touch table shaped like `attach_respect`'s output: per date,
    `n_per_date` focal and `n_per_date` synthetic events, half of each
    with high respect. `hold_flag` is Bernoulli(base + lift) for
    high-respect rows in the arm that gets a lift, Bernoulli(base) else.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(n_per_date):
            high = i % 2 == 0
            for is_focal, lift in ((True, focal_lift), (False, synth_lift)):
                p = base + (lift if high else 0.0)
                rows.append({
                    "ticker": f"{'F' if is_focal else 'S'}{i}", "date": date, "direction": FROM_ABOVE,
                    "is_focal": is_focal, "hold_flag": float(rng.random() < p),
                    "fwd_ret_21": rng.normal(0.01 if high and is_focal else 0.0, 0.05),
                    "respect": 2.0 if high else 0.0, "respect_bucket": 2.0 if high else 0.0,
                    "high_respect": high,
                    "mom_tercile": i % 3, "vol_tercile": (i // 3) % 3, "sector": "X", "rev_tercile": (i // 9) % 3,
                })
    frame = pd.DataFrame(rows)
    frame["high_respect"] = frame["high_respect"].astype("boolean")
    return frame


def test_did_cell_recovers_a_planted_focal_only_lift():
    events = _events(focal_lift=0.25, synth_lift=0.0)
    cell = rh.did_cell(events, FROM_ABOVE, "hold_flag", {"group": "t"}, n_boot=200)
    assert cell["did_c2_rev"] > 0.15
    assert cell["did_c2_rev_ci_low"] > 0
    assert cell["ci_excludes_zero"] is True
    assert cell["sign"] == 1
    assert not cell["below_threshold"]
    assert cell["delta_focal_c2_rev"] > 0.15 and abs(cell["delta_synth_c2_rev"]) < 0.1


def test_did_cell_cancels_a_lift_present_in_both_arms():
    # The generic "bouncy stocks keep bouncing" case: both arms lift equally.
    events = _events(focal_lift=0.25, synth_lift=0.25, seed=1)
    cell = rh.did_cell(events, FROM_ABOVE, "hold_flag", {"group": "t"}, n_boot=200)
    assert cell["delta_focal_c2_rev"] > 0.15
    assert cell["did_c2_rev_ci_low"] <= 0 <= cell["did_c2_rev_ci_high"]
    assert cell["ci_excludes_zero"] is False


def test_did_cell_return_outcome_reports_shape_and_cost_fields():
    events = _events(focal_lift=0.0, seed=2)
    cell = rh.did_cell(events, FROM_ABOVE, "fwd_ret_21", {"group": "t"}, n_boot=100,
                       panel_years=10.0, panel_tickers=30)
    for key in ("hit_rate", "hit_rate_delta_c1", "hit_rate_delta_c2", "win_loss_ratio", "skew",
                "signals_per_year", "cost_hurdle_annual", "delta_focal_annualized", "ci_clears_cost"):
        assert key in cell
    assert cell["signals_per_year"] > 0
    assert cell["cost_hurdle_annual"] == cell["signals_per_year"] * rh.ROUND_TRIP_COST


def test_primary_population_drops_the_one_bounce_middle_and_undefined_rows():
    events = _events(n_dates=5, n_per_date=6)
    events.loc[0, "respect"], events.loc[0, "respect_bucket"] = 1.0, 1.0
    events.loc[1, "respect"] = np.nan
    events.loc[2, "hold_flag"] = np.nan
    pop = rh.primary_population(events, FROM_ABOVE, "hold_flag", rh.C2_MATCH_COLS_WITH_REVERSAL)
    assert len(pop) == len(events) - 3
    assert (pop["respect_bucket"] != 1).all()


def test_attach_respect_uses_the_same_side_column():
    dates = pd.bdate_range("2021-01-04", periods=3)
    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates,
        respect_column("sma_50", SUPPORT): [0.0, 2.0, 5.0],
        respect_column("sma_50", RESISTANCE): [1.0, 1.0, 1.0],
    })
    events = pd.DataFrame({
        "ticker": "AAA", "date": [dates[1], dates[2]], "direction": [FROM_ABOVE, FROM_BELOW],
        "ma_col": "sma_50", "is_focal": True,
    })
    out = rh.attach_respect(events, panel)
    assert out["respect"].tolist() == [2.0, 1.0]
    assert out["respect_bucket"].tolist() == [2.0, 1.0]
    assert out["high_respect"].tolist() == [True, False]


def test_prepare_adds_respect_columns_only_for_present_dist_atr_columns():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2019-01-01", periods=300)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    panel = pd.DataFrame({
        "ticker": "AAA", "date": dates, "close": close,
        "dist_atr_sma_20": rng.normal(0, 1, 300), "dist_atr_sma_50": rng.normal(0, 1, 300),
        "mom_12_1": rng.normal(0, 0.1, 300), "realized_vol_63": rng.uniform(0.01, 0.03, 300),
        "mom_1_0": rng.normal(0, 0.05, 300),
    })
    out = rh.prepare(panel)
    assert respect_column("sma_20", SUPPORT) in out.columns
    assert respect_column("sma_50", RESISTANCE) in out.columns
    assert respect_column("sma_200", SUPPORT) not in out.columns
    assert respect_column("ema_21", SUPPORT) not in out.columns
    assert {"fwd_ret_21", "mom_tercile", "vol_tercile", "rev_tercile"} <= set(out.columns)
    assert len(out) == len(panel)


def _primary_frame(dids: dict, ci_half=0.02, excludes=None):
    rows = []
    for (group, direction), did in dids.items():
        exc = excludes.get((group, direction), abs(did) > ci_half) if excludes else abs(did) > ci_half
        half = ci_half if exc else abs(did) + 0.01
        rows.append({
            "group": group, "direction": direction, "outcome": "hold_flag", "below_threshold": False,
            "did_c2_rev": did, "did_c2_rev_ci_low": did - half, "did_c2_rev_ci_high": did + half,
            "ci_excludes_zero": exc,
        })
    return pd.DataFrame(rows)


def _sensitivity_frame(group, direction, dids, excludes):
    rows = []
    for (variant, did, exc) in zip(rh.SENSITIVITY_VARIANTS, dids, excludes):
        half = 0.01 if exc else abs(did) + 0.01
        rows.append({"group": group, "direction": direction, "variant": variant, "outcome": "hold_flag",
                     "did_c2_rev": did, "did_c2_rev_ci_low": did - half, "did_c2_rev_ci_high": did + half})
    return pd.DataFrame(rows)


def test_kill_criterion_confirms_a_cell_that_clears_all_three_gates():
    dids = {(g, FROM_ABOVE): 0.03 for g in rh.GROUP_ORDER}
    dids.update({(g, FROM_BELOW): 0.0 for g in rh.GROUP_ORDER})
    primary = _primary_frame(dids)
    sens = pd.concat([
        _sensitivity_frame(g, FROM_ABOVE, [0.03] * 6, [True] * 5 + [False]) for g in rh.GROUP_ORDER
    ] + [_sensitivity_frame(g, FROM_BELOW, [0.0] * 6, [False] * 6) for g in rh.GROUP_ORDER], ignore_index=True)
    verdict = rh.evaluate_kill_criterion(primary, sens)
    assert verdict["n_confirmed"] == 4
    assert verdict["module_killed"] is False


def test_kill_criterion_kills_a_lone_pixel_whose_neighbours_disagree():
    dids = {("sma50", FROM_ABOVE): 0.05, ("sma20", FROM_ABOVE): -0.01, ("ema21", FROM_ABOVE): -0.005,
            ("sma200", FROM_ABOVE): 0.002}
    dids.update({(g, FROM_BELOW): 0.0 for g in rh.GROUP_ORDER})
    primary = _primary_frame(dids)
    sens = pd.concat([_sensitivity_frame(g, d, [dids[(g, d)]] * 6, [True] * 6)
                      for g in rh.GROUP_ORDER for d in rh.DIRECTIONS], ignore_index=True)
    verdict = rh.evaluate_kill_criterion(primary, sens)
    cell = verdict["cells"].set_index(["group", "direction"]).loc[("sma50", FROM_ABOVE)]
    assert cell["positive_and_ci_excludes_zero"]
    assert cell["n_other_mas_agreeing"] == 1 and not cell["plateau_pass"]
    assert verdict["module_killed"] is True


def test_kill_criterion_kills_when_a_perturbation_flips_sign_or_too_many_span_zero():
    dids = {(g, FROM_ABOVE): 0.03 for g in rh.GROUP_ORDER}
    dids.update({(g, FROM_BELOW): 0.0 for g in rh.GROUP_ORDER})
    primary = _primary_frame(dids)
    sens = pd.concat([
        _sensitivity_frame("sma20", FROM_ABOVE, [0.03] * 5 + [-0.01], [True] * 6),   # sign flip
        _sensitivity_frame("ema21", FROM_ABOVE, [0.03] * 6, [True] * 4 + [False] * 2),  # only 4 of 6 exclude
        _sensitivity_frame("sma50", FROM_ABOVE, [0.03] * 6, [True] * 6),
        _sensitivity_frame("sma200", FROM_ABOVE, [0.03] * 6, [True] * 6),
    ] + [_sensitivity_frame(g, FROM_BELOW, [0.0] * 6, [False] * 6) for g in rh.GROUP_ORDER], ignore_index=True)
    verdict = rh.evaluate_kill_criterion(primary, sens)
    cells = verdict["cells"].set_index(["group", "direction"])
    assert not cells.loc[("sma20", FROM_ABOVE), "sensitivity_pass"]
    assert not cells.loc[("ema21", FROM_ABOVE), "sensitivity_pass"]
    assert cells.loc[("sma50", FROM_ABOVE), "confirmed"]
    assert verdict["n_confirmed"] == 2


def test_kill_criterion_does_not_confirm_a_negative_clearing_cell():
    dids = {(g, FROM_ABOVE): -0.03 for g in rh.GROUP_ORDER}
    dids.update({(g, FROM_BELOW): 0.0 for g in rh.GROUP_ORDER})
    primary = _primary_frame(dids)
    sens = pd.concat([_sensitivity_frame(g, d, [dids[(g, d)]] * 6, [True] * 6)
                      for g in rh.GROUP_ORDER for d in rh.DIRECTIONS], ignore_index=True)
    verdict = rh.evaluate_kill_criterion(primary, sens)
    assert verdict["module_killed"] is True
    assert not verdict["cells"]["positive_and_ci_excludes_zero"].any()


def test_block_bootstrap_delta_diff_matches_the_difference_of_the_two_arms_point_estimates():
    events = _events(focal_lift=0.2, synth_lift=0.05, n_dates=60)
    out = block_bootstrap_delta_diff(
        events[events["is_focal"]], events[~events["is_focal"]], "high_respect", "hold_flag",
        ["mom_tercile"], block_length=5, n_boot=50,
    )
    assert np.isclose(out["point_estimate"], out["point_a"] - out["point_b"])
    assert out["n_dates"] == 60 and out["n_dates_a"] == 60 and out["n_dates_b"] == 60
