"""Cost annotation (DESIGN.md §6.10; CLAUDE.md invariant #8: "Any claim
implying trading carries `signals_per_year × cost` next to the gross
number"). Added for M1's cost check -- previously computed ad hoc and
reported only in conversation/PREREGISTRATION.md prose, not as reproducible
code, which is exactly the gap invariant #8 exists to prevent.

`signals_per_year` measures turnover directly off the panel (state-flip
count per ticker-year) rather than assuming a number -- PREREGISTRATION.md's
M1 entry commits to this ("measured directly off the built panel... not
assumed in advance"). `annualize`'s ×(252/21) scaling is a labeled linear
approximation, not a derived quantity (21-day forward returns overlap and
don't compound this way) -- see PREREGISTRATION.md's cost-test addendum.
`ci_clears_cost` implements the corrected CI-based cost test found during
M1: a CI spanning zero automatically fails, since zero is itself a valid
point inside such an interval, and the pre-fix "nearest-to-zero endpoint"
comparison could land on the opposite sign from the point estimate.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import state

TRADING_DAYS_PER_YEAR = 252
HORIZON = 21


def signals_per_year(
    panel: pd.DataFrame, state_col: str, ticker_col: str = "ticker",
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """State-flip count per ticker-year, pooled across all tickers: total
    flips (each ticker's `max(state_run_id)` -- run 0 is the observation
    window's start, not a flip, so `max(run_id)` is exactly the transition
    count) divided by total ticker-years (`state_col`'s valid-row count /
    `trading_days_per_year`, pooled). `state_col` must already be a
    per-ticker-sorted panel column (e.g. `above_sma_50`); this groups by
    `ticker_col` and calls `features/state.py::state_run_id` per group.
    """
    total_flips = 0
    total_valid_rows = 0
    for _, group in panel.groupby(ticker_col, sort=False):
        s = group[state_col]
        run_id = state.state_run_id(s)
        if run_id.notna().any():
            total_flips += int(run_id.max())
        total_valid_rows += int(s.notna().sum())

    ticker_years = total_valid_rows / trading_days_per_year
    return total_flips / ticker_years if ticker_years else float("nan")


def cost_hurdle(signals_per_year_: float, round_trip_cost: float) -> float:
    """Annual cost hurdle: `signals_per_year × round_trip_cost` (DESIGN
    §6.10's formula, with `round_trip_cost` already resolved to a single
    per-round-trip figure -- see PREREGISTRATION.md's M1 cost-convention
    addendum for the derivation of the 10bps/round-trip figure used there).
    """
    return signals_per_year_ * round_trip_cost


def annualize(delta_21d: float, horizon: int = HORIZON, trading_days_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Linear (not compounded) annualization of a `horizon`-day delta:
    `delta_21d * trading_days_per_year / horizon`. An approximation, not a
    derived quantity -- overlapping `horizon`-day forward returns don't
    scale or compound this way in reality; treat the result as an order-
    of-magnitude comparison against the turnover hurdle, not a precise
    annual rate (PREREGISTRATION.md's M1 cost-test addendum).
    """
    return delta_21d * trading_days_per_year / horizon


def ci_clears_cost(ci_low: float, ci_high: float, hurdle: float) -> bool:
    """The corrected CI-based cost test (found during M1, 2026-09-09): a
    CI spanning (or touching) zero automatically fails -- zero is itself a
    valid point inside such an interval, so the true most-conservative
    achievable magnitude is exactly 0, not whichever endpoint happens to
    be numerically closest to zero (which can land on the opposite sign
    from the point estimate). Only a CI that excludes zero entirely
    proceeds to the magnitude comparison against `hurdle`.
    """
    if ci_low <= 0 <= ci_high:
        return False
    near_zero_edge = ci_low if abs(ci_low) < abs(ci_high) else ci_high
    return abs(near_zero_edge) > hurdle


def point_clears_cost(point_estimate: float, hurdle: float) -> bool:
    """The point-estimate cost test: does `|point_estimate|` alone clear
    `hurdle`? Unaffected by the CI-spans-zero fix (`ci_clears_cost`) --
    kept separate since DESIGN §6.10 and M4's own cost check report both
    the point estimate's and the CI's cost-clearance independently.
    """
    return abs(point_estimate) > hurdle
