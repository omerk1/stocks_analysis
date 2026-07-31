"""Candidate zone generation.

Levels are zones, not exact prices, throughout this package. Horizontal
clustering is implemented here; diagonal (RANSAC-style trendline) candidates
are deferred to milestone 5 (see docs/backlog.md) -- `generate_diagonal_candidates`
is a stub with the intended signature so the pipeline shape is stable across
that milestone boundary.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from src.sr_lines.config import SRConfig
from src.sr_lines.models import Pivot


@dataclass
class HorizontalCandidate:
    center: float
    half_width: float
    pivots: list[Pivot] = field(default_factory=list)


def generate_horizontal_candidates(
    pivots: list[Pivot], config: SRConfig
) -> list[HorizontalCandidate]:
    """Agglomerative clustering of pivot prices: a pivot joins the running
    cluster if it's within `zone_width_atr * median(cluster's own pivot
    ATRs)` of the cluster's *mean* price so far. Both swing highs and swing
    lows can land in the same cluster -- that's a role-flipping level, not
    an error, and is exactly what later marks a line FLIPPED.

    Compared against the cluster mean, not just its nearest member (which an
    earlier version did): comparing only to the nearest member is prone to
    chaining -- a real ~5-year AAPL run showed it fragmenting one visually
    obvious level into 2-3 separate, barely-adjacent zones that never quite
    touched closely enough to trigger lifecycle.dedup_lines afterward.
    Anchoring to the mean keeps a cluster from drifting/splitting that way.

    A cluster needs >= `min_pivots_per_cluster` pivots to become a candidate.
    """
    if not pivots:
        return []

    ordered = sorted(pivots, key=lambda p: p.price)

    clusters: list[list[Pivot]] = []
    current = [ordered[0]]
    for pivot in ordered[1:]:
        median_atr = statistics.median(p.atr_at_pivot for p in current)
        threshold = config.zone_width_atr * median_atr
        cluster_mean = statistics.mean(p.price for p in current)
        if pivot.price - cluster_mean <= threshold:
            current.append(pivot)
        else:
            clusters.append(current)
            current = [pivot]
    clusters.append(current)

    candidates = []
    for cluster in clusters:
        if len(cluster) < config.min_pivots_per_cluster:
            continue
        prices = [p.price for p in cluster]
        atrs = [p.atr_at_pivot for p in cluster]
        center = statistics.mean(prices)
        half_width = (config.zone_width_atr * statistics.median(atrs)) / 2
        candidates.append(HorizontalCandidate(center=center, half_width=half_width, pivots=cluster))

    return candidates


def generate_diagonal_candidates(pivots: list[Pivot], config: SRConfig) -> list:
    """Not implemented yet -- milestone 5 (RANSAC-style trendlines in log
    price, see the module spec). Returns an empty list so callers written
    against this signature don't need to change once it's implemented.
    """
    if not config.diagonal_enabled:
        return []
    raise NotImplementedError("Diagonal candidate generation is milestone 5, not yet implemented.")
