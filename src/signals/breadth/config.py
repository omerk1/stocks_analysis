"""BreadthConfig -- every tunable knob for market-breadth computation, kept
in one place so the CLI can drive it without touching compute code (same
reasoning as sr_lines.config.SRConfig / gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.foundation.data_processing import db


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
    price_source: str = db.YFINANCE
    # See WEIGHTING_CHOICES above.
    weighting: str = "equal"
