"""Shared outcome-statistics primitive: "many per-event numbers -> one
honest summary", extracted from `patterns/backtest/evaluator.py::_return_stats`
(see `docs/features/shared_outcome_statistics_design.md`) so every signal
module's eventual backtest/aggregation step reports outcomes the same way,
without each one reinventing (or under-reporting) the same statistics.

Deliberately generic over what the values mean (returns, ATR-normalized
moves, days-to-fill, whatever) -- takes `list[float]`, no return-specific
assumptions baked in.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Fraction clipped off each tail for the winsorized mean. 1% is the
# conventional default for financial returns and is deliberately gentle:
# the aim is to stop one observation owning the statistic, not to reshape
# the distribution. See `evaluator.py`'s own history: dropping the top 1%
# alone moved falling_wedge's 60-bar mean from +0.61% to -2.47%.
DEFAULT_WINSOR_LIMIT: float = 0.01

DEFAULT_PERCENTILES: tuple[float, ...] = (0.10, 0.25, 0.75, 0.90)


@dataclass
class DistributionStats:
    n: int
    mean: float | None
    median: float | None
    winsorized_mean: float | None
    std: float | None
    # mean / std -- a per-event risk-adjusted return, analogous to Sharpe's
    # ratio of return to volatility but deliberately not called Sharpe:
    # there's no risk-free rate and no annualization here, just independent
    # per-event outcomes rather than a compounding equity curve. Use it to
    # compare pattern types by "edge relative to its own noise", not as a
    # substitute for an actual portfolio Sharpe ratio. None whenever std is
    # None or zero (a single-observation or constant-valued sample has no
    # meaningful noise to divide by).
    risk_adjusted_return: float | None
    percentiles: dict[float, float | None]


def distribution_stats(
    values: list[float],
    winsor_limit: float = DEFAULT_WINSOR_LIMIT,
    percentiles: tuple[float, ...] = DEFAULT_PERCENTILES,
) -> DistributionStats:
    """Summarize one horizon/bucket's resolved outcome values.

    Empty input reports every statistic as None, and `percentiles` as a
    dict with every requested key mapped to None (not an empty dict) --
    not zero, a right-censored/no-data case is not a zero outcome.

    Winsorizing clips each tail to its `winsor_limit` percentile rather than
    discarding those observations, so `n` stays the real sample size. With
    very few values the two percentiles collapse toward the min/max and the
    clip becomes a no-op, leaving the winsorized mean equal to the plain
    mean -- the honest outcome: there is no tail to bound yet.
    """
    if not values:
        return DistributionStats(
            n=0, mean=None, median=None, winsorized_mean=None, std=None,
            risk_adjusted_return=None, percentiles={p: None for p in percentiles},
        )

    series = pd.Series(values, dtype=float)
    lower, upper = series.quantile(winsor_limit), series.quantile(1 - winsor_limit)
    mean = float(series.mean())
    std = float(series.std()) if len(series) > 1 else None

    return DistributionStats(
        n=len(series),
        mean=mean,
        median=float(series.median()),
        winsorized_mean=float(series.clip(lower, upper).mean()),
        std=std,
        risk_adjusted_return=(mean / std) if std else None,
        percentiles={p: float(series.quantile(p)) for p in percentiles},
    )
