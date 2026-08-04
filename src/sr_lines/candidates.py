"""Candidate zone generation.

Levels are zones, not exact prices, throughout this package. Horizontal
clustering and diagonal (RANSAC-style trendline) candidates are both
implemented here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np

from src.sr_lines.config import SRConfig
from src.sr_lines.models import Pivot, PivotKind


@dataclass
class HorizontalCandidate:
    center: float
    half_width: float
    pivots: list[Pivot] = field(default_factory=list)

    def center_at(self, bar_index: int) -> float:
        return self.center

    def zone_at(self, bar_index: int) -> tuple[float, float]:
        return self.center - self.half_width, self.center + self.half_width


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


@dataclass
class DiagonalCandidate:
    slope: float
    intercept: float
    origin_index: int
    half_width: float
    pivots: list[Pivot] = field(default_factory=list)

    def log_price_at(self, bar_index: int) -> float:
        return self.intercept + self.slope * (bar_index - self.origin_index)

    def center_at(self, bar_index: int) -> float:
        return math.exp(self.log_price_at(bar_index))

    def zone_at(self, bar_index: int) -> tuple[float, float]:
        log_center = self.log_price_at(bar_index)
        return math.exp(log_center - self.half_width), math.exp(log_center + self.half_width)


Candidate = HorizontalCandidate | DiagonalCandidate


def generate_diagonal_candidates(pivots: list[Pivot], config: SRConfig) -> list[DiagonalCandidate]:
    """RANSAC-style trendline fitting in log-price/bar-index space -- same
    two-stage shape as `generate_horizontal_candidates` (candidate geometry,
    then a threshold on membership), just in a different coordinate space and
    seeded from pairs instead of grown by sorted-neighbor clustering, since a
    trendline's members aren't adjacent in any single 1-D sort order the way
    a horizontal cluster's are.

    Only same-kind pivots pair up (HIGH-HIGH -> resistance trendline,
    LOW-LOW -> support trendline) -- mixing kinds would fit a line through
    points that were never actually the same side of price to begin with.

    1. Seed: every same-kind pivot pair >= `diagonal_min_pivot_separation_bars`
       apart in bar-index defines a candidate line through their
       (bar_index, ln(price)) points.
    2. Reject if the fitted slope exceeds `max_diagonal_slope_atr_per_bar` --
       treated as a direct cap on log-price-per-bar (i.e. roughly "max %
       price move per bar along the trend"), the diagonal analogue of
       treating `zone_width_atr` as an ATR% multiplier rather than a raw
       dollar amount (see the horizontal clustering docstring above).
    3. Inliers: every same-kind pivot within `zone_width_atr * (its own
       atr_at_pivot / price)` (log-space, additive -- a close first-order
       approximation of the same % tolerance in real price terms) of the
       seed line at that pivot's own bar-index. Keep if
       `inlier_count >= diagonal_min_inliers`.
    4. Refit via least-squares over *all* inliers (not just the seed pair)
       for a more robust final line -- two arbitrary pivots can imply a
       noisier slope than the full inlier set supports.
    5. Greedily dedupe: sort by inlier count descending, drop any candidate
       whose inlier set overlaps an already-kept candidate's by more than
       half (the same seed structure repeatedly finds near-identical lines
       through overlapping pivot subsets). Cap at `diagonal_max_candidates`.

    `half_width` is the **log-space** band half-width (see `models.Line`'s
    own docstring, which already anticipates this contract): multiplicative
    in real-price terms, so it scales with price along the trend's own
    rise/fall the same way the ATR%-of-price fix made horizontal zones scale
    across price levels.
    """
    if not config.diagonal_enabled:
        return []

    candidates: list[DiagonalCandidate] = []
    for kind in (PivotKind.HIGH, PivotKind.LOW):
        same_kind = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.bar_index)
        candidates.extend(_fit_diagonal_candidates(same_kind, config))

    candidates.sort(key=lambda c: -len(c.pivots))
    kept: list[DiagonalCandidate] = []
    kept_index_sets: list[set[int]] = []
    for cand in candidates:
        idx_set = {p.bar_index for p in cand.pivots}
        if any(len(idx_set & existing) / len(idx_set) > 0.5 for existing in kept_index_sets):
            continue
        kept.append(cand)
        kept_index_sets.append(idx_set)
        if len(kept) >= config.diagonal_max_candidates:
            break

    return kept


def _fit_diagonal_candidates(same_kind_pivots: list[Pivot], config: SRConfig) -> list[DiagonalCandidate]:
    results: list[DiagonalCandidate] = []
    n = len(same_kind_pivots)
    for i in range(n):
        for j in range(i + 1, n):
            p_i, p_j = same_kind_pivots[i], same_kind_pivots[j]
            if p_j.bar_index - p_i.bar_index < config.diagonal_min_pivot_separation_bars:
                continue

            x_i, x_j = p_i.bar_index, p_j.bar_index
            y_i, y_j = math.log(p_i.price), math.log(p_j.price)
            slope = (y_j - y_i) / (x_j - x_i)
            if abs(slope) > config.max_diagonal_slope_atr_per_bar:
                continue

            inliers = [
                p for p in same_kind_pivots
                if abs(math.log(p.price) - (y_i + slope * (p.bar_index - x_i)))
                <= config.zone_width_atr * (p.atr_at_pivot / p.price)
            ]
            if len(inliers) < config.diagonal_min_inliers:
                continue

            xs = np.array([p.bar_index for p in inliers], dtype=float)
            ys = np.array([math.log(p.price) for p in inliers], dtype=float)
            refit_slope, refit_intercept_at_zero = np.polyfit(xs, ys, 1)
            origin_index = inliers[0].bar_index
            intercept = float(refit_intercept_at_zero + refit_slope * origin_index)

            atr_pcts = [p.atr_at_pivot / p.price for p in inliers]
            half_width = (config.zone_width_atr * statistics.median(atr_pcts)) / 2

            results.append(
                DiagonalCandidate(
                    slope=float(refit_slope), intercept=intercept, origin_index=origin_index,
                    half_width=half_width, pivots=inliers,
                )
            )
    return results
