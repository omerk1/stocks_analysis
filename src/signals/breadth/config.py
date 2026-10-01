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
    # Cap-weighted only: a member whose market cap that date exceeds this
    # many times the date's *median* member cap is treated as having no
    # weight (excluded that date, counted in a warning), not trusted. No
    # real index member is 1,000x the median (the largest S&P 500 names
    # run ~100-150x); a share count mis-scaled by 1e3/1e6 in its filing
    # is (found 2026-10-01: CB at 338 trillion shares was 99.96% of the
    # index on 2010-06-30, AJG likewise in 2020). The SEC ingest now drops
    # those filings at the source; this is the last line of defence for
    # the next one. None disables the guard.
    cap_outlier_ratio: float | None = 1000.0
