"""BreadthConfig -- every tunable knob for market-breadth computation, kept
in one place so the CLI can drive it without touching compute code (same
reasoning as sr_lines.config.SRConfig / gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.foundation.data_processing import db
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, source_for


def _default_indices() -> list[str]:
    return ["sp500", "nasdaq100"]


# Every breadth metric is really a weighted aggregate over an index's
# constituents -- "equal" weights every member 1.0 (today's original
# behavior, exactly reproduced -- see compute.py), "cap" weights each
# member by its real historical market cap that date (bars_1d price x
# shares_outstanding, split-reconciled via data_processing.market_cap --
# unblocked now that both shares_outstanding and a local splits cache are
# backfilled for sp500+nasdaq100; previously deferred here as a blocked
# backlog item for exactly that reason).
WEIGHTING_CHOICES = ("equal", "cap")


@dataclass
class BreadthConfig:
    # Which index_membership index_names to compute breadth for. "nasdaq100"
    # membership is only reliable from 2015-01-01 onward (see
    # data_processing/index_membership.py) -- earlier Nasdaq-100 breadth
    # rows will simply have very few/no constituents, not silently wrong
    # ones, since read_index_membership only returns intervals that actually
    # exist.
    indices: list[str] = field(default_factory=_default_indices)
    sma_periods: tuple[int, ...] = (50, 200)
    ema_periods: tuple[int, ...] = (8, 21)
    price_source: str = source_for(MODULE_PRICE_BASIS["breadth"])  # total_return; see market_common.price_basis
    # See WEIGHTING_CHOICES above.
    weighting: str = "equal"
    # Cap-weighted only: a member whose market cap that date exceeds this
    # many times the date's *median* member cap is treated as having no
    # weight (excluded, with a warning), not trusted. A backstop: share
    # counts are already cleaned per ticker in
    # `market_cap.reconcile_market_cap` (`share_counts.drop_scale_runs`);
    # this catches what that can't see, e.g. a ticker with a single
    # mis-scaled count and nothing to compare it with.
    #
    # 300 is calibrated for LARGE-CAP indices: the largest real S&P 500
    # member on any date 2009-2026 is ~90x the median (AAPL, 2023),
    # Nasdaq-100 less, while a 1e3 scale error puts a mid-cap at ~600x
    # (GRMN 2018-12: $12 trillion). On a broad index the real mega-caps
    # are themselves >1,000x the median small-cap, so pass a larger value
    # or None there (`--cap-outlier-ratio`). None disables the guard.
    cap_outlier_ratio: float | None = 300.0
    # The guard only runs on dates where at least this many members have a
    # cap: with a handful of covered members the median is dragged by the
    # outlier itself (two members: never flagged), and such dates are too
    # thin for cap weighting to mean much anyway (mid-2009: 13 of 499).
    cap_outlier_min_members: int = 20
