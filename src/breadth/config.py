"""BreadthConfig -- every tunable knob for market-breadth computation, kept
in one place so the CLI can drive it without touching compute code (same
reasoning as sr_lines.config.SRConfig / gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.data_processing import db


def _default_indices() -> list[str]:
    return ["sp500", "nasdaq100"]


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
    # Equal-weight only -- market-cap weighting is a separate, currently
    # blocked backlog item (shares_outstanding has no local backfill yet,
    # and market_cap.py has no local splits cache for ~500-ticker scale).
    price_source: str = db.YFINANCE
