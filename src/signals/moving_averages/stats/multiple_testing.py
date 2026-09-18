"""Multiple-testing correction (DESIGN.md §6.6): "Benjamini-Hochberg FDR
at q = 0.10 as the primary screen. Bonferroni is too conservative for
exploratory work at this scale." This module is the whole-grid FDR pass's
own machinery -- `STATUS.md`'s "Whole-grid FDR pass" section is the
per-module bookkeeping that decides *which* cells go into `p_value_from_ci`
and `benjamini_hochberg` below, not re-implemented here.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

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
