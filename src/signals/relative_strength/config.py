"""RelativeStrengthConfig -- every tunable knob for relative-strength
computation, kept in one place so the CLI can drive it without touching
compute code (same reasoning as breadth.config.BreadthConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.foundation.data_processing import db


def _default_indices() -> list[str]:
    return ["sp500", "nasdaq100"]


def _default_rs_rating_windows() -> tuple[int, ...]:
    return (63, 126, 189, 252)  # ~3/6/9/12 months in trading days


def _default_rs_rating_weights() -> tuple[float, ...]:
    return (0.4, 0.2, 0.2, 0.2)  # heaviest weight on the most recent window


# Yahoo/yfinance's fixed 11-sector taxonomy (confirmed live against real
# tickers -- AAPL/JPM/XOM/JNJ -- in `ticker_sector`) mapped onto its
# matching SPDR sector ETF. One-to-one: every sector has exactly one ETF
# and vice versa.
SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Healthcare": "XLV",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}


@dataclass
class RelativeStrengthConfig:
    # Which index_membership index_names to compute stock-level RS for
    # (stock-vs-market and stock-vs-sector; sector-vs-market isn't scoped
    # to an index -- it's always the fixed 11 sector ETFs).
    indices: list[str] = field(default_factory=_default_indices)
    # Ticker used as "the market" for stock-vs-market and sector-vs-market.
    # Must already be ingested into bars_1d (see bulk_yfinance_ingest.py
    # --tickers) -- this module doesn't fetch it itself.
    market_benchmark: str = "SPY"
    # Weeks, not days -- the Mansfield oscillator is computed on weekly-
    # resampled closes (the textbook definition), so 52 is a real ~1-year
    # SMA. See compute._weekly_mansfield.
    mansfield_period: int = 52
    rs_rating_windows: tuple[int, ...] = field(default_factory=_default_rs_rating_windows)
    rs_rating_weights: tuple[float, ...] = field(default_factory=_default_rs_rating_weights)
    price_source: str = db.YFINANCE
