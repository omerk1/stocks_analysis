"""Multiple-testing correction (DESIGN.md §6.6): "Benjamini-Hochberg FDR
at q = 0.10 as the primary screen. Bonferroni is too conservative for
exploratory work at this scale." This module is the whole-grid FDR pass's
own machinery -- `STATUS.md`'s "Whole-grid FDR pass" section is the
per-module bookkeeping that decides *which* cells go into `p_value_from_ci`
and `benjamini_hochberg` below, not re-implemented here.

`white_reality_check` (added 2026-09-24, M8 -- DESIGN.md's own named
procedure for that module: "Apply White's Reality Check to the
best-performer claim") is a different kind of correction than BH: BH
controls the false-discovery rate across many *separately reported*
hypotheses; White's Reality Check (White, 2000) tests whether the single
*best-of-K* candidate in a horse race beats a benchmark, once the act of
having searched over K candidates and picked the best is itself accounted
for -- the two are not interchangeable, and M8 needs the second, not BH,
because the whole point of a kernel horse race is "did the winner win by
more than data-snooping luck would produce," not "how many of K cells are
individually significant."
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.signals.moving_averages.stats.inference import _block_weights, _validate_block_length

DEFAULT_Q = 0.10


def p_value_from_ci(point_estimate: float, ci_low: float, ci_high: float, ci_level: float = 0.90) -> float:
    """Two-sided Wald p-value backed out of an already-computed
    block-bootstrap CI. This study's bootstrap functions
    (`stats/inference.py`) summarize each draw set to
    `point_estimate`/`ci_low`/`ci_high` and discard the raw draws -- they
    were never archived per-cell across modules, so a p-value re-derived
    directly from the empirical bootstrap distribution isn't available
    without rebuilding every module's own pipeline from scratch. This is
    a labeled approximation, not a derived quantity (same discipline as
    `stats/costs.py::annualize`'s own linear-approximation label): the
    standard error is backed out from the CI's own half-width under a
    normal approximation, `SE = (ci_high - ci_low) / (2 * z)`, `z` the
    two-sided critical value for `ci_level`. NaN if the CI itself is
    NaN/degenerate (e.g. an unresolved, `InsufficientBlocksError` cell --
    caller's responsibility to exclude these from the correction, not
    silently pass them through as p=1).
    """
    if any(math.isnan(v) for v in (point_estimate, ci_low, ci_high)):
        return float("nan")
    z_crit = norm.ppf(0.5 + ci_level / 2)
    se = (ci_high - ci_low) / (2 * z_crit)
    if se <= 0:
        return float("nan")
    z_stat = point_estimate / se
    return float(2 * (1 - norm.cdf(abs(z_stat))))


def benjamini_hochberg(p_values, q: float = DEFAULT_Q) -> np.ndarray:
    """Standard BH step-up procedure (DESIGN §6.6). Returns a boolean
    array, same order as `p_values`, True where that test's null is
    rejected at FDR level `q`. A NaN p-value is never rejected and is
    excluded from the ranked comparison entirely (not treated as `p=1`,
    which would silently shrink every other test's effective rank) --
    the caller decides whether a cell without a valid CI belongs in the
    correction at all (DESIGN's own "no CI, no kill criterion" cells,
    e.g. M2's ablation coefficients, are never passed in here).
    """
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    valid_mask = ~np.isnan(p)
    n_valid = int(valid_mask.sum())
    reject = np.zeros(n, dtype=bool)
    if n_valid == 0:
        return reject

    valid_idx = np.flatnonzero(valid_mask)
    order = valid_idx[np.argsort(p[valid_idx])]
    sorted_p = p[order]
    ranks = np.arange(1, n_valid + 1)
    thresholds = ranks / n_valid * q
    passes = sorted_p <= thresholds

    if passes.any():
        # BH: reject every hypothesis up to and including the largest
        # rank whose p-value still clears its own (rank/n * q) threshold
        # -- not just the individually-passing ones in isolation.
        largest_passing_rank = np.max(np.flatnonzero(passes))
        reject[order[: largest_passing_rank + 1]] = True

    return reject


def white_reality_check(
    diffs: pd.DataFrame,
    date_col: str = "date",
    block_length: int = 42,
    n_boot: int = 1000,
    seed: int = 0,
) -> dict:
    """White's (2000) Bootstrap Reality Check: tests whether the best of
    several candidates' mean performance differential (each candidate's
    own column in `diffs`, already computed as "candidate minus benchmark"
    per date -- the caller's job, e.g. `modules/kernel_horse_race.py`'s own
    per-family delta minus EMA's delta, both from `stats/controls.py::
    stratum_deltas` averaged to one value per date) is significantly
    better than zero, once having searched over every candidate and picked
    the best is itself accounted for.

    `diffs` must have exactly one row per date (already pre-averaged
    across whatever match-strata exist within a date -- a different
    aggregation from `block_bootstrap_delta`'s own per-(date,stratum)-row
    reweighting in `stats/inference.py`, because Reality Check's null
    resamples *dates* over a fixed per-date statistic per candidate, not
    raw stratum rows). Every non-`date_col` column is treated as one
    candidate.

    Method (standard construction, e.g. Hansen 2005 §2's exposition of
    White 2000):
    1. Observed statistic: `V = max_l sqrt(T) * mean_l`, `T` = n_dates,
       `mean_l` = candidate `l`'s own column mean.
    2. Bootstrap: for `n_boot` draws, block-resample dates the same way
       `stats/inference.py::_block_weights` already does for this study's
       other bootstrap machinery (reused directly, not reimplemented),
       compute each candidate's own resampled mean, **recenter it at its
       own observed mean** (the mechanism that makes the bootstrap
       distribution represent the *null* that every candidate's true
       outperformance is zero, not the alternative that it equals whatever
       was observed), and take the max across candidates.
    3. p-value: the fraction of bootstrap draws whose recentered max
       equals or exceeds the observed `V`.

    Returns `{"best_candidate", "observed_stat", "p_value",
    "candidate_means", "n_dates", "n_boot"}`. Raises
    `stats.inference.InsufficientBlocksError` (via `_validate_block_length`,
    reused unchanged) if there are too few dates for `block_length` to
    produce a meaningful resampling distribution -- same guard, same
    exception type, as every other block-bootstrap call in this study.
    """
    candidates = [c for c in diffs.columns if c != date_col]
    working = diffs.dropna(subset=[date_col, *candidates])
    dates = np.array(sorted(working[date_col].unique()))
    _validate_block_length(len(dates), block_length)

    by_date = working.set_index(date_col)[candidates].reindex(dates)
    values = by_date.to_numpy()  # shape (n_dates, n_candidates)
    n_dates = len(dates)

    observed_means = values.mean(axis=0)
    v_stat = float(np.sqrt(n_dates) * observed_means.max())
    best_candidate = candidates[int(np.argmax(observed_means))]

    rng = np.random.default_rng(seed)
    boot_stats = np.empty(n_boot)
    for b in range(n_boot):
        weight = _block_weights(dates, block_length, rng)
        boot_means = (values * weight[:, None]).sum(axis=0) / weight.sum()
        centered = np.sqrt(n_dates) * (boot_means - observed_means)
        boot_stats[b] = centered.max()

    p_value = float((boot_stats >= v_stat).mean())

    return {
        "best_candidate": best_candidate,
        "observed_stat": v_stat,
        "p_value": p_value,
        "candidate_means": dict(zip(candidates, observed_means.tolist())),
        "n_dates": n_dates,
        "n_boot": n_boot,
    }
