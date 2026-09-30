"""Tests for M20 (`modules/bounce_entry.py` and
`features/respect.py::bounce_flags`), PREREGISTRATION.md 2026-09-30.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.respect import bounce_flags
from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW
from src.signals.moving_averages.modules import bounce_entry as be

COL = "dist_atr_sma_50"


def _frame(values, ticker="AAA"):
    return pd.DataFrame({"ticker": ticker, "date": pd.bdate_range("2021-01-04", periods=len(values)), COL: values})


def test_bounce_flag_is_true_only_on_the_confirmation_row():
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.9, 1.1, 1.3, 0.4]
    flags = bounce_flags(_frame(values), COL)
    above = flags["bounce_sma_50_from_above"]
    assert pd.isna(above.iloc[0])
    assert above.iloc[6] is np.True_ or bool(above.iloc[6]) is True
    assert not above.iloc[1:6].astype(bool).any() and not above.iloc[7:].astype(bool).any()
    assert not flags["bounce_sma_50_from_below"].iloc[1:].astype(bool).any()


def test_bounce_flags_do_not_bleed_across_tickers():
    a = [np.nan, 1.5, 1.4, 0.2, 0.6, 0.9, 1.1, 1.3, 0.4]
    b = [np.nan, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2]
    panel = pd.concat([_frame(a, "AAA"), _frame(b, "BBB")], ignore_index=True)
    flags = bounce_flags(panel, COL)
    assert bool(flags["bounce_sma_50_from_above"].iloc[6])
    assert not flags["bounce_sma_50_from_above"].iloc[9:].fillna(False).astype(bool).any()


def _synthetic_panel(n_tickers=60, n_days=400, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    dates = pd.bdate_range("2019-01-01", periods=n_days)
    for i in range(n_tickers):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n_days)))
        frames.append(pd.DataFrame({
            "ticker": f"T{i:02d}", "date": dates, "close": close,
            "atr_14": np.full(n_days, 1.2), "sector": ["a", "b", "c"][i % 3],
            "mom_12_1": rng.normal(0, 0.1, n_days), "realized_vol_63": rng.uniform(0.01, 0.03, n_days),
            "mom_1_0": rng.normal(0, 0.05, n_days),
            "dist_atr_sma_50": rng.normal(0, 1.0, n_days), "dist_atr_sma_47": rng.normal(0, 1.0, n_days),
            "dist_atr_sma_53": rng.normal(0, 1.0, n_days),
        }))
    return pd.concat(frames, ignore_index=True)


def test_generic_move_flags_require_a_move_same_side_and_no_recent_touch():
    n = 12
    close = np.array([100.0] * 6 + [100, 100.5, 101, 101.6, 102.5, 103.5])  # rises ~3.5 over the last 5 rows
    dist = np.array([1.5] * n)                                                # always far above the MA: no touch
    panel = pd.DataFrame({"ticker": "AAA", "date": pd.bdate_range("2021-01-04", periods=n), "close": close,
                          "atr_14": 1.0, COL: dist})
    flags = be.generic_move_flags(panel, COL, {"confirm_window": 5, "confirm_distance": 1.0})
    up = flags["generic_move_sma_50_from_above"].astype("boolean")
    # Lagged close: row 11 sees close[10]=102.5 vs close[5]=100 -> +2.5 ATR over j=5: flagged.
    assert bool(up.iloc[11])
    # Row 8 sees close[7]=100.5 vs earlier 100: +0.5 < R.
    assert not bool(up.iloc[8])
    assert not flags["generic_move_sma_50_from_below"].iloc[6:].astype(bool).any()
    # A recent touch of the MA disqualifies the row.
    panel.loc[9, COL] = 0.1
    flags = be.generic_move_flags(panel, COL, {"confirm_window": 5, "confirm_distance": 1.0})
    assert not bool(flags["generic_move_sma_50_from_above"].astype("boolean").iloc[11])
    # Below the MA disqualifies an up-move from the from_above flag.
    panel.loc[9, COL] = 1.5
    panel.loc[11, COL] = -1.5
    flags = be.generic_move_flags(panel, COL, {"confirm_window": 5, "confirm_distance": 1.0})
    assert not bool(flags["generic_move_sma_50_from_above"].astype("boolean").iloc[11])


def test_prepare_adds_flags_and_forward_returns_for_present_columns():
    out = be.prepare(_synthetic_panel(n_tickers=6, n_days=120))
    for h in be.HORIZONS:
        assert be.fwd_col(h) in out.columns
    assert "bounce_sma_50_from_above" in out.columns and "bounce_sma_47_from_below" in out.columns
    assert "generic_move_sma_50_from_above" in out.columns
    assert "generic_move_sma_47_from_above" not in out.columns   # generic flags only for focal columns
    assert "bounce_sma_200_from_above" not in out.columns


def test_did_cell_recovers_a_planted_focal_only_return_lift():
    panel = be.prepare(_synthetic_panel())
    focal = panel["bounce_sma_50_from_above"].fillna(False).astype(bool)
    assert focal.sum() > 200
    panel.loc[focal, be.fwd_col(5)] = panel.loc[focal, be.fwd_col(5)] + 0.05
    cell = be.did_cell(panel, "sma50", FROM_ABOVE, 5, {"variant": "t"}, n_boot=150, panel_years=1.6, panel_tickers=60)
    assert cell["delta_focal_c2_rev"] > 0.03 and cell["focal_ci_excludes_zero"]
    assert cell["did_c2_rev"] > 0.03 and cell["did_ci_excludes_zero"]
    assert cell["did_hypothesised_direction"] and cell["focal_hypothesised_direction"]
    assert 0 <= cell["focal_also_synth_share"] <= 1
    for key in ("hit_rate", "win_loss_ratio", "skew", "signals_per_year", "cost_hurdle_annual", "ci_clears_cost"):
        assert key in cell


def test_did_cell_cancels_a_lift_shared_with_the_generic_move_arm():
    panel = be.prepare(_synthetic_panel(seed=1))
    focal = panel["bounce_sma_50_from_above"].fillna(False).astype(bool)
    generic = panel["generic_move_sma_50_from_above"].fillna(False).astype(bool)
    panel.loc[focal | generic, be.fwd_col(5)] += 0.05
    cell = be.did_cell(panel, "sma50", FROM_ABOVE, 5, {"variant": "t"}, n_boot=150, with_synth=False)
    assert cell["delta_focal_c2_rev"] > 0.03
    assert cell["did_c2_rev_ci_low"] <= 0 <= cell["did_c2_rev_ci_high"]


def _cells(did_by_key, focal_ok=True):
    rows = []
    for (g, d, h), did in did_by_key.items():
        rows.append({"group": g, "direction": d, "horizon": h, "did_c2_rev": did, "did_c2_rev_ci_low": did - 0.001,
                     "did_c2_rev_ci_high": did + 0.001, "delta_focal_c2_rev": did, "below_threshold": False,
                     "focal_ci_excludes_zero": focal_ok, "focal_hypothesised_direction": did * be.HYPOTHESISED_SIGN[d] > 0,
                     "did_ci_excludes_zero": True, "did_hypothesised_direction": did * be.HYPOTHESISED_SIGN[d] > 0})
    return pd.DataFrame(rows)


def test_kill_criterion_confirms_only_with_every_gate():
    keys = [(g, d, h) for g in be.GROUP_ORDER for d in be.DIRECTIONS for h in be.HORIZONS]
    dids = {k: (0.01 if k[1] == FROM_ABOVE else -0.01) for k in keys}
    primary = _cells(dids)
    sens = pd.concat([_cells({k: dids[k]}).assign(variant=v) for v in be.SENSITIVITY_VARIANTS for k in keys], ignore_index=True)
    verdict = be.evaluate_kill_criterion(primary, sens)
    assert verdict["n_confirmed"] == 32 and not verdict["module_killed"]

    # Break the term structure at sma50 / from_above / 21d: neighbours 10d and 63d flip.
    dids2 = dict(dids); dids2[("sma50", FROM_ABOVE, 10)] = -0.01; dids2[("sma50", FROM_ABOVE, 63)] = -0.01
    verdict = be.evaluate_kill_criterion(_cells(dids2), sens)
    cell = verdict["cells"].set_index(["group", "direction", "horizon"]).loc[("sma50", FROM_ABOVE, 21)]
    assert not cell["term_structure_pass"] and not cell["confirmed"]

    # Wrong hypothesised direction everywhere -> killed.
    dids3 = {k: -v for k, v in dids.items()}
    verdict = be.evaluate_kill_criterion(_cells(dids3), sens)
    assert verdict["module_killed"]

    # Focal gate fails (focal CI spans zero) -> killed even if the DiD clears.
    verdict = be.evaluate_kill_criterion(_cells(dids, focal_ok=False), sens)
    assert verdict["module_killed"]
