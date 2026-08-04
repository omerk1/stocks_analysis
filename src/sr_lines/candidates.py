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
    ATR%s) * cluster_mean` of the cluster's *mean* price so far. Both swing
    highs and swing lows can land in the same cluster -- that's a
    role-flipping level, not an error, and is exactly what later marks a
    line FLIPPED.

    Threshold is derived from ATR *as a percentage of price*
    (`atr_at_pivot / price`), not raw dollar ATR, then converted back to a
    dollar amount using the cluster's own mean price. Raw-dollar ATR is only
    partly self-normalizing: it's computed locally per cluster, so a $50-era
    cluster of a stock already gets a smaller dollar threshold than a
    $300-era cluster of the *same* stock -- but that's coincidental to using
    local ATR, not a real price-relative guarantee, and it does nothing for
    comparing the *same* `zone_width_atr` value across different tickers'
    price levels. A real AAPL run showed this concretely: its 2019-2020
    zones (price $46-98) came out only ~$1.5-4 wide, vs. ~$7-8 wide for its
    2026 zones (price $240-280) at the identical `zone_width_atr` -- looking
    dense on a chart despite each individually being a reasonable width for
    its own era. ATR% removes that confound directly.

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
        median_atr_pct = statistics.median(p.atr_at_pivot / p.price for p in current)
        cluster_mean = statistics.mean(p.price for p in current)
        threshold = config.zone_width_atr * median_atr_pct * cluster_mean
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
        atr_pcts = [p.atr_at_pivot / p.price for p in cluster]
        center = statistics.mean(prices)
        half_width = (config.zone_width_atr * statistics.median(atr_pcts) * center) / 2
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
