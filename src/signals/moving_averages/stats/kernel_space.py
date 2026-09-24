"""Kernel-space diagnostics (DESIGN.md, "M16 -- Rules as linear filters",
lines ~854-865; PREREGISTRATION.md, 2026-09-25). Track A (exploration) --
see PREREGISTRATION.md's M16 entry for the track-determination reasoning.

Zakamulin's (2017) point: price-minus-MA, MA-crossover spreads, momentum,
and MA slope are all (approximately) linear filters of past daily returns,
differing only in kernel shape. Rather than hand-deriving each rule's own
closed-form weight formula (straightforward for a plain SMA distance --
triangular weights -- but genuinely error-prone for `slope_log_k`, which
involves a log-of-an-average and has no clean exact closed form), this
module measures every rule's own kernel **empirically**, via a unit-return
impulse response -- the same general technique `features/kernels.py
::impulse_center_of_mass` already validated for MA-family lag-matching
(M8), generalized here from "the MA level's own response to a price
impulse" to "any downstream feature's response to a single-day return
impulse," which is exactly what "linear filter of past returns" means by
definition (a filter's own impulse response *is* its kernel).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

Weights = np.ndarray


def impulse_response(
    feature_fn: Callable[[pd.Series], pd.Series],
    n: int = 1600,
    impulse_at: int = 800,
    epsilon: float = 1e-4,
    max_lag: int = 400,
) -> Weights:
    """Empirical weight vector (lag 0 = today's return, increasing = further
    back) for `feature_fn` (a callable taking a single `close` price Series
    and returning the already-computed feature Series -- matches this
    study's own `compute_ma`/`dist_pct`/`slope_log_k` signatures directly,
    no re-implementation needed). Builds a synthetic price path flat at
    100.0 before `impulse_at` and permanently stepped up by a fraction
    `epsilon` at `impulse_at` (a single unit-return impulse, since a price
    path is the cumulative product of its own daily returns -- one nonzero
    return shifts the level and it stays there), runs `feature_fn` on it,
    and reads the response for lags >= `impulse_at` as the feature's own
    weight on a return that occurred that many bars ago. `epsilon` is kept
    small (default 1e-4) so log/ratio-based features (`slope_log_k`, a
    ratio-based `dist_pct`) sit in their own local-linear regime -- this is
    precisely what "linear filter" means for a rule that isn't exactly
    linear in closed form. Response is normalized by `epsilon` (linearized)
    and trimmed to `max_lag` (long enough to comfortably capture every
    lookback this study uses, 200 bars, with headroom).

    Returns an all-NaN array of length `max_lag` if the response is
    degenerate (e.g. the feature needs more history than `impulse_at`
    provides before it's ever defined).
    """
    price = pd.Series(np.full(n, 100.0))
    price.iloc[impulse_at:] = 100.0 * (1.0 + epsilon)
    response = feature_fn(price)
    tail = response.iloc[impulse_at : impulse_at + max_lag].to_numpy(dtype=float)
    if len(tail) < max_lag:
        tail = np.pad(tail, (0, max_lag - len(tail)), constant_values=np.nan)
    baseline = response.iloc[impulse_at - 1] if impulse_at - 1 >= 0 else np.nan
    baseline = 0.0 if pd.isna(baseline) else baseline
    weights = (tail - baseline) / epsilon
    return weights


def kernel_centroid(weights: Weights) -> float:
    """Weighted mean lag (the kernel's own "effective lookback") over the
    *absolute* weight, since a kernel can have a sign-changing shape (a
    crossover spread's weights are positive from one MA and negative from
    the other) -- centroid should reflect where the filter's own energy
    concentrates, not cancel signed halves against each other. NaN if the
    weight vector is degenerate.
    """
    w = np.abs(weights)
    valid = ~np.isnan(w)
    if not valid.any() or w[valid].sum() == 0:
        return float("nan")
    lags = np.arange(len(weights))
    return float((lags[valid] * w[valid]).sum() / w[valid].sum())


def kernel_dispersion(weights: Weights) -> float:
    """Weighted standard deviation of lag around `kernel_centroid` -- the
    kernel's own "effective smoothing window width." Same absolute-weight
    convention as `kernel_centroid`, for the same reason.
    """
    w = np.abs(weights)
    valid = ~np.isnan(w)
    if not valid.any() or w[valid].sum() == 0:
        return float("nan")
    lags = np.arange(len(weights))
    centroid = kernel_centroid(weights)
    variance = (w[valid] * (lags[valid] - centroid) ** 2).sum() / w[valid].sum()
    return float(np.sqrt(variance))


def cosine_similarity(a: Weights, b: Weights) -> float:
    """Cosine similarity between two weight vectors, after zero-filling
    any NaN (a rule with a shorter effective kernel simply has zero weight
    at lags beyond its own reach, which is the correct comparison point --
    not a missing-data problem). Returns NaN if either vector is all-zero.
    """
    a = np.nan_to_num(a, nan=0.0)
    b = np.nan_to_num(b, nan=0.0)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return float("nan")
    return float(np.dot(a, b) / denom)


def similarity_matrix(named_weights: dict[str, Weights]) -> pd.DataFrame:
    """Pairwise cosine-similarity matrix, `names x names`, for a dict of
    already-computed weight vectors (all the same length, `impulse_response`'s
    own `max_lag` convention).
    """
    names = list(named_weights)
    mat = pd.DataFrame(index=names, columns=names, dtype=float)
    for a in names:
        for b in names:
            mat.loc[a, b] = cosine_similarity(named_weights[a], named_weights[b])
    return mat


def cluster_by_threshold(sim: pd.DataFrame, threshold: float = 0.95) -> dict[str, int]:
    """Simple transitive-closure clustering: any two rules with cosine
    similarity >= `threshold` are joined into the same cluster (union-find
    over the similarity graph's edges at that threshold) -- deliberately
    not a fitted clustering algorithm (k-means, hierarchical with a chosen
    cut) since DESIGN's own question is binary ("do these rules land
    uncomfortably close together or not"), not "how many natural clusters
    exist." Returns `{name: cluster_id}`, 0-indexed, in first-seen order.
    """
    names = list(sim.index)
    parent = {name: name for name in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for a in names:
        for b in names:
            if a != b and sim.loc[a, b] >= threshold:
                union(a, b)

    roots = {name: find(name) for name in names}
    root_to_id = {root: i for i, root in enumerate(sorted(set(roots.values())))}
    return {name: root_to_id[root] for name, root in roots.items()}
