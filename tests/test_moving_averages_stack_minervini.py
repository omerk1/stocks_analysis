"""Tests for M2 -- stack states and Minervini ablation (DESIGN.md §8, M2;
PREREGISTRATION.md, 2026-09-12).

`prepare()`'s `rs_rating` join needs a live DB connection (index
membership + sector + bars) and isn't exercised end-to-end here -- these
tests build already-`prepare()`-shaped frames directly (the same "test the
per-feature logic, not the DB plumbing" split `test_moving_averages_features
.py` already uses for `context.py`'s per-ticker functions) and cover:
- the 8 Trend Template criteria's NaN handling (CLAUDE.md invariant #9),
- `stack_perm`/`stack_fully_bullish`/`stack_fully_bearish` construction,
- the part-(a) kill-criterion evaluation logic,
- the 256-subset ablation's bitmask correctness,
- `linear_attribution`'s OLS recovery on a known-coefficient synthetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.modules import stack_minervini as smv


def _base_frame(n=8):
    """A minimal frame with the columns `_add_trend_template_criteria`/
    `_add_stack_features` need, hand-built so expected values are exact.
    """
    dates = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({
        "date": dates,
        "ticker": ["AAA"] * n,
        "close": [110.0] * n,
        "sma_20": [108.0] * n,
        "sma_50": [106.0] * n,
        "sma_150": [104.0] * n,
        "sma_200": [102.0] * n,
        "slope_log_21_sma_200": [0.01] * n,
        "dist_from_52w_low": [0.35] * n,
        "dist_from_52w_high": [-0.10] * n,
        "rs_rating": [80.0] * n,
    })


def test_trend_template_criteria_all_true_for_a_clean_bullish_stack():
    frame = smv._add_trend_template_criteria(_base_frame())

    for col in smv.CRITERIA_COLS:
        assert frame[col].dtype == "boolean"
        assert frame[col].all()


def test_trend_template_criteria_are_na_not_false_during_sma200_warmup():
    frame = _base_frame()
    frame.loc[0, "sma_200"] = np.nan
    frame.loc[0, "slope_log_21_sma_200"] = np.nan

    result = smv._add_trend_template_criteria(frame)

    assert pd.isna(result.loc[0, "tt_c1"])  # depends on sma_200
    assert pd.isna(result.loc[0, "tt_c3"])  # depends on the slope column directly
    assert pd.isna(result.loc[0, "tt_c4"])  # depends on sma_200
    assert result.loc[0, "tt_c5"] == True  # noqa: E712 -- doesn't depend on sma_200, must be unaffected


def test_trend_template_criterion_6_and_7_are_na_during_52w_warmup_not_false():
    frame = _base_frame()
    frame.loc[0, "dist_from_52w_low"] = np.nan
    frame.loc[0, "dist_from_52w_high"] = np.nan

    result = smv._add_trend_template_criteria(frame)

    assert pd.isna(result.loc[0, "tt_c6"])
    assert pd.isna(result.loc[0, "tt_c7"])


def test_trend_template_criterion_8_is_na_when_rs_rating_missing_not_false():
    frame = _base_frame()
    frame.loc[0, "rs_rating"] = np.nan

    result = smv._add_trend_template_criteria(frame)

    assert pd.isna(result.loc[0, "tt_c8"])


def test_trend_template_criterion_6_7_8_thresholds():
    frame = _base_frame()
    frame.loc[0, "dist_from_52w_low"] = 0.29  # just under the 30% floor
    frame.loc[1, "dist_from_52w_high"] = -0.26  # just outside 25% of the high
    frame.loc[2, "rs_rating"] = 69.9  # just under 70

    result = smv._add_trend_template_criteria(frame)

    assert result.loc[0, "tt_c6"] == False  # noqa: E712
    assert result.loc[1, "tt_c7"] == False  # noqa: E712
    assert result.loc[2, "tt_c8"] == False  # noqa: E712


def test_stack_fully_bullish_and_bearish_are_mutually_exclusive_and_correct():
    frame = _base_frame(n=3)
    # Row 0: clean bullish (close > 20 > 50 > 150 > 200).
    # Row 1: clean bearish (reverse order).
    # Row 2: mixed (not fully ordered either way).
    frame.loc[1, ["close", "sma_20", "sma_50", "sma_150", "sma_200"]] = [90.0, 92.0, 94.0, 96.0, 98.0]
    frame.loc[2, ["close", "sma_20", "sma_50", "sma_150", "sma_200"]] = [100.0, 108.0, 106.0, 104.0, 102.0]

    result = smv._add_stack_features(frame)

    assert result.loc[0, "stack_fully_bullish"] == True  # noqa: E712
    assert result.loc[0, "stack_fully_bearish"] == False  # noqa: E712
    assert result.loc[1, "stack_fully_bearish"] == True  # noqa: E712
    assert result.loc[1, "stack_fully_bullish"] == False  # noqa: E712
    assert result.loc[2, "stack_fully_bullish"] == False  # noqa: E712
    assert result.loc[2, "stack_fully_bearish"] == False  # noqa: E712


def test_stack_fully_bullish_stays_na_not_false_when_only_sma20_has_warmed_up():
    # Regression for a real shape found against sp500 data: close > sma_20
    # resolves to a determinate False while sma_50/150/200 are still NaN
    # (mid-warmup) -- Kleene AND short-circuits `False & NaN` to `False`,
    # which would make `stack_fully_bullish` flip False-then-NaN over
    # calendar time instead of a single leading gap. Must stay NA here,
    # not silently read as "not fully bullish" (CLAUDE.md invariant #9).
    frame = _base_frame(n=1)
    frame.loc[0, ["sma_50", "sma_150", "sma_200"]] = np.nan
    frame.loc[0, "close"] = 90.0  # below sma_20 (108) -- would short-circuit to False

    result = smv._add_stack_features(frame)

    assert pd.isna(result.loc[0, "stack_fully_bullish"])
    assert pd.isna(result.loc[0, "stack_fully_bearish"])


def test_stack_perm_is_na_when_any_of_the_four_smas_is_na():
    frame = _base_frame(n=2)
    frame.loc[0, "sma_150"] = np.nan

    result = smv._add_stack_features(frame)

    assert pd.isna(result.loc[0, "stack_perm"])
    assert pd.notna(result.loc[1, "stack_perm"])


def test_stack_perm_differs_for_different_orderings():
    frame = _base_frame(n=2)
    # Row 1: reverse the 20/50 order relative to row 0's clean bullish stack.
    frame.loc[1, ["sma_20", "sma_50"]] = [104.0, 108.0]

    result = smv._add_stack_features(frame)

    assert result.loc[0, "stack_perm"] != result.loc[1, "stack_perm"]


def test_evaluate_part_a_kill_criterion_fires_when_both_cells_below_floor():
    incremental = pd.DataFrame({"cell": ["fully_bullish", "fully_bearish"], "kill_cell": [True, True]})
    verdict = smv.evaluate_part_a_kill_criterion(incremental)

    assert verdict["module_killed"] is True
    assert verdict["n_cells_killed"] == 2
    assert verdict["n_unresolved"] == 0


def test_evaluate_part_a_kill_criterion_does_not_fire_when_one_cell_survives():
    incremental = pd.DataFrame({"cell": ["fully_bullish", "fully_bearish"], "kill_cell": [True, False]})
    verdict = smv.evaluate_part_a_kill_criterion(incremental)

    assert verdict["module_killed"] is False
    assert verdict["n_cells_killed"] == 1


def test_evaluate_part_a_kill_criterion_treats_unresolved_cells_as_not_killed():
    # A cell whose CI couldn't be computed (InsufficientBlocksError) is
    # `None`, not True/False -- must not silently count as "killed".
    incremental = pd.DataFrame({"cell": ["fully_bullish", "fully_bearish"], "kill_cell": [True, None]})
    verdict = smv.evaluate_part_a_kill_criterion(incremental)

    assert verdict["module_killed"] is False
    assert verdict["n_unresolved"] == 1


def test_ablation_subset_table_bitmask_partitions_rows_correctly():
    n = 40
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2021-01-01", periods=n)
    frame = pd.DataFrame({
        "date": dates, "ticker": [f"T{i}" for i in range(n)],
        "fwd_ret_21": rng.normal(0, 0.01, n),
    })
    for i, col in enumerate(smv.CRITERIA_COLS):
        # Deterministic pattern per criterion so bitmasks are hand-checkable.
        frame[col] = pd.array([(row % (2 ** (i + 1))) >= 2 ** i for row in range(n)], dtype="boolean")

    table = smv.ablation_subset_table(frame)

    assert table["bitmask"].min() >= 0
    assert table["bitmask"].max() <= 255
    assert table["n_events"].sum() == n  # every eligible row lands in exactly one subset
    # Row 0 satisfies none of the 8 criteria by the pattern above -> bitmask 0.
    row0_mask = int("".join("1" if frame.loc[0, c] else "0" for c in reversed(smv.CRITERIA_COLS)), 2)
    assert row0_mask in table["bitmask"].to_numpy()


def test_ablation_subset_table_flags_below_threshold_without_dropping():
    n = 10  # well under MIN_EVENTS=200
    dates = pd.bdate_range("2021-01-01", periods=n)
    frame = pd.DataFrame({
        "date": dates, "ticker": [f"T{i}" for i in range(n)],
        "fwd_ret_21": np.linspace(-0.01, 0.01, n),
    })
    for col in smv.CRITERIA_COLS:
        frame[col] = pd.array([True] * n, dtype="boolean")

    table = smv.ablation_subset_table(frame)

    assert len(table) == 1  # all rows satisfy every criterion -> one subset
    assert table.loc[0, "below_threshold"]
    assert table.loc[0, "n_events"] == n  # flagged, not dropped


def test_linear_attribution_recovers_planted_coefficients():
    rng = np.random.default_rng(0)
    n = 4000
    dates = pd.bdate_range("2021-01-01", periods=n)
    frame = pd.DataFrame({"date": dates, "ticker": [f"T{i}" for i in range(n)]})
    true_coefs = [0.05, -0.03, 0.02, 0.0, 0.01, 0.0, -0.02, 0.04]
    fwd_ret = np.full(n, 0.001)  # intercept
    for coef, col in zip(true_coefs, smv.CRITERIA_COLS):
        values = rng.integers(0, 2, n).astype(bool)
        frame[col] = pd.array(values, dtype="boolean")
        fwd_ret = fwd_ret + coef * values
    frame["fwd_ret_21"] = fwd_ret + rng.normal(0, 0.001, n)

    result = smv.linear_attribution(frame)

    recovered = dict(zip(result["criterion"], result["coefficient"]))
    for coef, col in zip(true_coefs, smv.CRITERIA_COLS):
        assert recovered[col] == pytest.approx(coef, abs=0.01)
    assert recovered["intercept"] == pytest.approx(0.001, abs=0.01)
