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


class InsufficientBlocksError(ValueError):
    """Raised by `_validate_block_length` specifically -- a `ValueError`
    subclass (not a bare `ValueError`) so a caller that wants to treat "too
    few dates for a reliable bootstrap" as an expected, flaggable condition
    (e.g. `modules/baseline_state.py::_cell_row`, thin secondary cells) can
    catch this exact type instead of a bare `except ValueError`, which
    would also silently swallow an unrelated bug elsewhere in this call
    chain (`stratum_deltas`'s own dropna/groupby, `np.quantile`, etc.) and
    misreport it as the same "too few dates" condition.
    """


def _validate_block_length(n_dates: int, block_length: int) -> None:
    if n_dates < MIN_BLOCKS * block_length:
        raise InsufficientBlocksError(
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


def block_bootstrap_group_diff(
    panel: pd.DataFrame,
    group_col_a: str,
    group_col_b: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on (delta_a - delta_b): the difference between
    two *different* boolean groupings' C2-style matched-control deltas,
    computed on the same panel/match_cols/date structure -- e.g. M2's "does
    the full stack add anything over a single-MA state" test
    (`stack_fully_bullish`'s C2 delta minus `above_sma_50`'s C2 delta,
    PREREGISTRATION.md 2026-09-12).

    Generalizes `block_bootstrap_spread` (which differences two *deciles
    of the same column*) to two independent group columns. Same
    correlated-draws requirement: `group_col_a` and `group_col_b` are
    computed over the same underlying dates, so they must be resampled
    together within each draw, not independently CI'd and differenced
    (see `block_bootstrap_spread`'s own docstring) -- the implementation
    below mirrors it exactly, just keyed by two group columns instead of
    one column's two decile labels.

    Caller is responsible for restricting `panel` to whatever row
    population makes `group_col_a` and `group_col_b` comparable (e.g. the
    intersection of their own eligibility masks) -- this function only
    differences and resamples, it doesn't decide eligibility.
    """
    strata_cols = [date_col, *match_cols]
    a = stratum_deltas(panel, group_col_a, value_col, strata_cols)
    b = stratum_deltas(panel, group_col_b, value_col, strata_cols)

    all_dates = np.array(sorted(set(a[date_col]).union(b[date_col])))
    if len(all_dates) == 0:
        return _summarize_draws(np.array([]), float("nan"), 0, ci)
    _validate_block_length(len(all_dates), block_length)
    date_index = {d: i for i, d in enumerate(all_dates)}

    a_idx, a_vals = a[date_col].map(date_index).to_numpy(), a["delta"].to_numpy()
    b_idx, b_vals = b[date_col].map(date_index).to_numpy(), b["delta"].to_numpy()

    point_a = a_vals.mean() if len(a_vals) else float("nan")
    point_b = b_vals.mean() if len(b_vals) else float("nan")
    point_estimate = point_a - point_b

    rng = np.random.default_rng(seed)
    boot_draws = np.empty(n_boot)
    for i in range(n_boot):
        weight = _block_weights(all_dates, block_length, rng)
        a_mean = _weighted_mean(a_vals, weight[a_idx])
        b_mean = _weighted_mean(b_vals, weight[b_idx])
        boot_draws[i] = a_mean - b_mean

    return _summarize_draws(boot_draws, point_estimate, len(all_dates), ci)


def block_bootstrap_spread_diff(
    panel: pd.DataFrame,
    focal_decile_col: str,
    neighbor_decile_col: str,
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
    """Block-bootstrap CI on the *difference* between two decile spreads
    computed on the same underlying dates/universe (PREREGISTRATION.md's
    §7.5 placebo test: a focal MA's `dist_pct` decile spread minus a
    placebo-neighbor MA's own decile spread). Same principle as
    `block_bootstrap_spread`'s own high-minus-low computation: the two
    spreads share the same dates and are correlated, so the difference is
    computed *within* each draw, using that draw's single set of date
    weights for both sides -- differencing two separately-bootstrapped
    CIs afterwards would be wrong.
    """
    strata_cols = [date_col, *match_cols]

    def _low_high(decile_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        low_panel = panel.assign(__is_event=panel[decile_col] == decile_low)
        high_panel = panel.assign(__is_event=panel[decile_col] == decile_high)
        return (
            stratum_deltas(low_panel, "__is_event", value_col, strata_cols),
            stratum_deltas(high_panel, "__is_event", value_col, strata_cols),
        )

    focal_low, focal_high = _low_high(focal_decile_col)
    neighbor_low, neighbor_high = _low_high(neighbor_decile_col)

    all_dates = np.array(sorted(
        set(focal_low[date_col]) | set(focal_high[date_col])
        | set(neighbor_low[date_col]) | set(neighbor_high[date_col])
    ))
    if len(all_dates) == 0:
        return _summarize_draws(np.array([]), float("nan"), 0, ci)
    _validate_block_length(len(all_dates), block_length)
    date_index = {d: i for i, d in enumerate(all_dates)}

    def _idx_vals(table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        return table[date_col].map(date_index).to_numpy(), table["delta"].to_numpy()

    fl_idx, fl_vals = _idx_vals(focal_low)
    fh_idx, fh_vals = _idx_vals(focal_high)
    nl_idx, nl_vals = _idx_vals(neighbor_low)
    nh_idx, nh_vals = _idx_vals(neighbor_high)

    def _spread(low_vals, low_idx, high_vals, high_idx, weight) -> float:
        return _weighted_mean(high_vals, weight[high_idx]) - _weighted_mean(low_vals, weight[low_idx])

    point_focal = (fh_vals.mean() if len(fh_vals) else float("nan")) - \
        (fl_vals.mean() if len(fl_vals) else float("nan"))
    point_neighbor = (nh_vals.mean() if len(nh_vals) else float("nan")) - \
        (nl_vals.mean() if len(nl_vals) else float("nan"))
    point_estimate = point_focal - point_neighbor

    rng = np.random.default_rng(seed)
    boot_draws = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(all_dates, block_length, rng)
        spread_focal = _spread(fl_vals, fl_idx, fh_vals, fh_idx, weight)
        spread_neighbor = _spread(nl_vals, nl_idx, nh_vals, nh_idx, weight)
        boot_draws[b] = spread_focal - spread_neighbor

    return _summarize_draws(boot_draws, point_estimate, len(all_dates), ci)


def block_bootstrap_series(
    values_by_date: pd.Series,
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Block-bootstrap CI on the mean of a statistic already computed once
    per date (e.g. M11's daily cross-sectional Spearman rank-IC) -- for
    values that don't come from a per-(date, stratum) delta table, so
    `stratum_deltas`'s per-stratum reweighting (`block_bootstrap_delta`/
    `block_bootstrap_spread`) doesn't apply. Same moving-block resampling
    over dates as those two (§6.2/§6.3), applied directly to
    `values_by_date` instead.

    `values_by_date` must be indexed by date, one value per date; NaN
    dates (e.g. a date with too few names to compute the statistic) are
    dropped before resampling.
    """
    values_by_date = values_by_date.dropna()
    if values_by_date.empty:
        return _summarize_draws(np.array([]), float("nan"), 0, ci)

    dates = np.array(sorted(values_by_date.index))
    _validate_block_length(len(dates), block_length)
    vals = values_by_date.reindex(dates).to_numpy()
    point_estimate = vals.mean()

    rng = np.random.default_rng(seed)
    boot_draws = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(dates, block_length, rng)
        boot_draws[b] = _weighted_mean(vals, weight)

    return _summarize_draws(boot_draws, point_estimate, len(dates), ci)
