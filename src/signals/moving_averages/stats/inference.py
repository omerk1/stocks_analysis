"""Block-bootstrap inference for matched-control deltas (DESIGN.md §6.2).

21-day forward returns overlap 20/21 -- naive SEs from the raw row/date
count are inflated by roughly sqrt(21) (DESIGN §6.2). This module resamples
*dates* in contiguous blocks (block length >= 2x horizon, per §6.2), not
rows, so the resampling unit respects the overlap structure rather than
pretending every row is an independent draw.

Performance note: a bootstrap draw does NOT re-run `c2_delta` on a
duplicated/resampled copy of the full panel (too slow at 500+ draws over a
1M+ row panel). Instead, `stats.controls.stratum_deltas` computes each
stratum's (event_mean - control_mean) exactly once -- the same quantity
`c2_delta` averages across strata -- and the bootstrap loop reweights that
small, precomputed table by how many times each date was drawn. Repeating
a date k times in the resampled sequence is mathematically identical to
giving that date's strata weight k in the stratum average, so this is not
an approximation of the literal block-resampling estimator, it's the same
estimator computed efficiently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.stats.controls import stratum_deltas

# A block-bootstrap draw needs several independent-ish blocks to actually
# vary from draw to draw; with too few, a single circular block can wrap
# around and cover nearly the whole date range almost every time,
# collapsing boot_std and producing a falsely narrow CI. Requiring at
# least this many blocks' worth of dates catches that before it silently
# produces a misleadingly tight interval.
MIN_BLOCKS = 3


def _validate_block_length(n_dates: int, block_length: int) -> None:
    if n_dates < MIN_BLOCKS * block_length:
        raise ValueError(
            f"block_length={block_length} is too large relative to n_dates={n_dates} "
            f"(need at least {MIN_BLOCKS}x{block_length}={MIN_BLOCKS * block_length} dates) -- "
            "with too few blocks, most draws cover nearly the full date range regardless of "
            "the random start, understating uncertainty rather than measuring it. Reduce "
            "block_length or gather more dates."
        )


def _block_weights(dates: np.ndarray, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """One moving-block-bootstrap draw's weight per original date index --
    circular blocks (wrapping at the end), enough blocks to cover the full
    date range. Weight[i] = how many times date i appears in this draw's
    resampled date sequence.
    """
    n_dates = len(dates)
    n_blocks = int(np.ceil(n_dates / block_length))
    starts = rng.integers(0, n_dates, size=n_blocks)
    weight = np.zeros(n_dates)
    for start in starts:
        idx = (start + np.arange(block_length)) % n_dates
        weight[idx] += 1
    return weight


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    total = weights.sum()
    return (weights * values).sum() / total if total > 0 else float("nan")


def _summarize_draws(draws: np.ndarray, point_estimate: float, n_dates: int, ci: float) -> dict:
    """Shared CI/summary construction for both bootstrap functions below --
    the only difference between them is how one draw's statistic is
    computed, not how the resulting draws are summarized.
    """
    draws = draws[~np.isnan(draws)]
    if len(draws) == 0:
        return {"point_estimate": point_estimate, "ci_low": float("nan"), "ci_high": float("nan"),
                "boot_std": float("nan"), "n_dates": n_dates, "n_boot": 0}
    tail = (1 - ci) / 2
    return {
        "point_estimate": point_estimate,
        "ci_low": float(np.quantile(draws, tail)),
        "ci_high": float(np.quantile(draws, 1 - tail)),
        "boot_std": float(draws.std()),
        "n_dates": n_dates,
        "n_boot": len(draws),
    }


def block_bootstrap_delta(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on the C2-style matched-control delta (DESIGN
    §6.2/§6.3). `block_length` defaults to 42 (2x the 21-day horizon this
    study uses everywhere, per §6.2's "block length >= 2x horizon").

    Returns `point_estimate` (identical to calling `c2_delta` directly),
    `ci_low`/`ci_high` at the requested `ci` level, `boot_std`, and
    `n_dates` (the effective-N count DESIGN §6.3 asks every table to
    carry -- distinct dates contributing at least one valid stratum, not
    the raw row count).
    """
    deltas = stratum_deltas(panel, group_col, value_col, [date_col, *match_cols])
    if deltas.empty:
        return _summarize_draws(np.array([]), float("nan"), 0, ci)

    dates = np.array(sorted(deltas[date_col].unique()))
    _validate_block_length(len(dates), block_length)
    date_index = {d: i for i, d in enumerate(dates)}
    strata_date_idx = deltas[date_col].map(date_index).to_numpy()
    delta_values = deltas["delta"].to_numpy()
    point_estimate = delta_values.mean()

    rng = np.random.default_rng(seed)
    boot_draws = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(dates, block_length, rng)
        boot_draws[b] = _weighted_mean(delta_values, weight[strata_date_idx])

    return _summarize_draws(boot_draws, point_estimate, len(dates), ci)


def block_bootstrap_spread(
    panel: pd.DataFrame,
    decile_col: str,
    decile_low: int,
    decile_high: int,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on the (decile_high - decile_low) C2 spread --
    the headline "C2 delta" per facet used throughout M4. Both deciles'
    per-stratum deltas are resampled with the *same* draw's date weights
    each iteration (not independently), since they share the same
    underlying dates and their bootstrap draws are correlated -- taking
    separately-bootstrapped CIs and differencing the endpoints would be
    wrong; the spread must be computed within each draw.
    """
    strata_cols = [date_col, *match_cols]
    panel_low = panel.assign(__is_event=panel[decile_col] == decile_low)
    panel_high = panel.assign(__is_event=panel[decile_col] == decile_high)
    low = stratum_deltas(panel_low, "__is_event", value_col, strata_cols)
    high = stratum_deltas(panel_high, "__is_event", value_col, strata_cols)

    all_dates = np.array(sorted(set(low[date_col]).union(high[date_col])))
    if len(all_dates) == 0:
        return _summarize_draws(np.array([]), float("nan"), 0, ci)
    _validate_block_length(len(all_dates), block_length)
    date_index = {d: i for i, d in enumerate(all_dates)}

    low_idx, low_vals = low[date_col].map(date_index).to_numpy(), low["delta"].to_numpy()
    high_idx, high_vals = high[date_col].map(date_index).to_numpy(), high["delta"].to_numpy()

    point_low = low_vals.mean() if len(low_vals) else float("nan")
    point_high = high_vals.mean() if len(high_vals) else float("nan")
    point_estimate = point_high - point_low

    rng = np.random.default_rng(seed)
    boot_draws = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(all_dates, block_length, rng)
        low_mean = _weighted_mean(low_vals, weight[low_idx])
        high_mean = _weighted_mean(high_vals, weight[high_idx])
        boot_draws[b] = high_mean - low_mean

    return _summarize_draws(boot_draws, point_estimate, len(all_dates), ci)
