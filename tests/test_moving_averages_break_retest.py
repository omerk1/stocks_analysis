"""Tests for M22 (`features/respect.py::retest_positions` / `retest_flags`,
`modules/break_retest.py`), PREREGISTRATION.md 2026-10-01.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.respect import BREAK_ABOVE, BREAK_BELOW, retest_flags, retest_positions
from src.signals.moving_averages.modules import break_retest as br

COL = "dist_atr_sma_50"

# from below: away, touch at 3, break above confirmed at 6, away above, touch from above at 9,
# bounce confirmed at 11.
BASE = [np.nan, -1.5, -1.4, -0.2, 0.3, 0.7, 1.2, 1.4, 1.3, 0.2, 0.6, 1.1, 1.3]


def _frame(values, ticker="AAA"):
    return pd.DataFrame({"ticker": ticker, "date": pd.bdate_range("2021-01-04", periods=len(values)), COL: values})


def test_break_then_retest_bounce_is_flagged_on_the_bounce_confirmation_row():
    out = retest_positions(pd.Series(BASE))
    assert out[["touch_pos", "break_pos", "confirm_pos"]].values.tolist() == [[9, 6, 11]]
    assert out["direction_sign"].tolist() == [1.0]
    flags = retest_flags(_frame(BASE), COL)
    above = flags[f"retest_sma_50_{BREAK_ABOVE}"]
    assert bool(above.iloc[11]) and not above.iloc[1:11].astype(bool).any() and not bool(above.iloc[12])
    assert not flags[f"retest_sma_50_{BREAK_BELOW}"].iloc[1:].astype(bool).any()


def test_retest_outside_the_window_is_not_flagged():
    values = BASE[:9] + [1.5] * 25 + BASE[9:]    # retest touch now ~28 rows after the break
    assert len(retest_positions(pd.Series(values), retest_window=21)) == 0
    assert len(retest_positions(pd.Series(values), retest_window=30)) == 1


def test_retest_that_breaks_back_through_is_not_a_retest_bounce():
    values = BASE[:10] + [-0.3, -1.1, -1.3]      # touch from above at 9, then breaks back down
    assert len(retest_positions(pd.Series(values))) == 0


def test_bounce_without_a_preceding_break_is_not_a_retest():
    values = [np.nan, 1.5, 1.4, 0.2, 0.6, 1.1, 1.3, 1.4, 0.2, 0.6, 1.2]   # two plain bounces from above
    assert len(retest_positions(pd.Series(values))) == 0


def test_break_below_then_retest_from_below_mirrors():
    values = [-v if not np.isnan(v) else v for v in BASE]
    out = retest_positions(pd.Series(values))
    assert out["direction_sign"].tolist() == [-1.0] and out["confirm_pos"].tolist() == [11]
    assert bool(retest_flags(_frame(values), COL)[f"retest_sma_50_{BREAK_BELOW}"].iloc[11])


def _synthetic_panel(n_tickers=80, n_days=500, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    for i in range(n_tickers):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n_days)))
        frames.append(pd.DataFrame({
            "ticker": f"T{i:02d}", "date": dates, "close": close, "atr_14": np.full(n_days, 1.2),
            "sector": ["a", "b", "c"][i % 3], "mom_12_1": rng.normal(0, 0.1, n_days),
            "realized_vol_63": rng.uniform(0.01, 0.03, n_days), "mom_1_0": rng.normal(0, 0.05, n_days),
            COL: rng.normal(0, 1.0, n_days),
        }))
    return pd.concat(frames, ignore_index=True)


def test_plain_bounce_excludes_retest_rows_and_prepare_adds_flags():
    out = br.prepare(_synthetic_panel(n_tickers=10, n_days=200))
    retest = out[f"retest_sma_50_{BREAK_ABOVE}"].fillna(False).astype(bool)
    plain = out[f"plain_bounce_sma_50_{BREAK_ABOVE}"].fillna(False).astype(bool)
    assert not (retest & plain).any()
    assert "generic_move_sma_50_from_above" in out.columns
    assert "retest_sma_200_above" not in out.columns


def test_did_cell_recovers_a_retest_only_lift_and_cancels_a_shared_one():
    panel = br.prepare(_synthetic_panel())
    retest = panel[f"retest_sma_50_{BREAK_ABOVE}"].fillna(False).astype(bool)
    plain = panel[f"plain_bounce_sma_50_{BREAK_ABOVE}"].fillna(False).astype(bool)
    assert retest.sum() > 100

    lifted = panel.copy()
    lifted.loc[retest, br.be.fwd_col(5)] += 0.05
    cell = br.did_cell(lifted, "sma50", BREAK_ABOVE, 5, {"variant": "t"}, n_boot=150, panel_years=2.0, panel_tickers=80)
    assert cell["did_c2_rev"] > 0.03 and cell["did_ci_excludes_zero"] and cell["did_hypothesised_direction"]
    for key in ("did_generic", "hit_rate", "win_loss_ratio", "skew", "signals_per_year", "ci_clears_cost"):
        assert key in cell

    shared = panel.copy()
    shared.loc[retest | plain, br.be.fwd_col(5)] += 0.05
    cell = br.did_cell(shared, "sma50", BREAK_ABOVE, 5, {"variant": "t"}, n_boot=150, with_generic=False)
    assert cell["delta_focal_c2_rev"] > 0.03
    assert cell["did_c2_rev_ci_low"] <= 0 <= cell["did_c2_rev_ci_high"]
