"""Tests for the cost-annotation infrastructure (DESIGN.md §6.10;
CLAUDE.md invariant #8) added for M1's cost check -- `signals_per_year`'s
panel-measurement, the linear annualization label, and the corrected
CI-based cost test's spans-zero fix.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.signals.moving_averages.stats.costs import (
    annualize,
    ci_clears_cost,
    cost_hurdle,
    point_clears_cost,
    signals_per_year,
)


def test_signals_per_year_counts_flips_not_rows():
    # Ticker A: True,True,False,False,False,True -> 2 flips over 6 rows.
    # Ticker B: True,True,True,True -> 0 flips over 4 rows (no transition).
    panel = pd.DataFrame(
        {
            "ticker": ["A"] * 6 + ["B"] * 4,
            "state": pd.array(
                [True, True, False, False, False, True, True, True, True, True], dtype="boolean"
            ),
        }
    )

    result = signals_per_year(panel, "state", trading_days_per_year=10)

    # total_flips=2, total_valid_rows=10 -> ticker_years=1.0 -> 2.0/year.
    assert result == pytest.approx(2.0)


def test_signals_per_year_ignores_rows_where_state_is_na():
    panel = pd.DataFrame(
        {
            "ticker": ["A"] * 5,
            "state": pd.array([None, None, True, True, False], dtype="boolean"),
        }
    )

    result = signals_per_year(panel, "state", trading_days_per_year=3)

    # 1 flip (True->False), 3 valid rows -> 1.0 ticker-year -> 1.0/year.
    assert result == pytest.approx(1.0)


def test_cost_hurdle_is_signals_times_round_trip_cost():
    assert cost_hurdle(30.0, 0.0010) == pytest.approx(0.03)


def test_annualize_scales_linearly_by_trading_days_over_horizon():
    assert annualize(-0.002146, horizon=21, trading_days_per_year=252) == pytest.approx(-0.002146 * 12)


def test_ci_clears_cost_fails_automatically_when_ci_spans_zero():
    # Point estimate is meaningfully negative, but the CI includes zero --
    # must fail regardless of how the endpoints compare in magnitude.
    assert ci_clears_cost(ci_low=-0.03, ci_high=0.01, hurdle=0.005) is False


def test_ci_clears_cost_uses_the_near_zero_endpoint_when_ci_excludes_zero():
    # Both endpoints negative (doesn't span zero); the near-zero one
    # (-0.001) must clear the hurdle for the test to pass.
    assert ci_clears_cost(ci_low=-0.03, ci_high=-0.001, hurdle=0.0005) is True
    assert ci_clears_cost(ci_low=-0.03, ci_high=-0.001, hurdle=0.002) is False


def test_ci_clears_cost_handles_a_ci_touching_zero_exactly():
    assert ci_clears_cost(ci_low=-0.02, ci_high=0.0, hurdle=0.0001) is False


def test_point_clears_cost_is_a_pure_magnitude_test():
    assert point_clears_cost(-0.03, hurdle=0.01) is True
    assert point_clears_cost(-0.005, hurdle=0.01) is False
