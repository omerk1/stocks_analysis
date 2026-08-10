"""sr_lines-specific data loading -- thin wrapper around
`market_common.data`, supplying `SRConfig`'s `window_years`/`bar_interval`/
`corruption_warning_threshold` (this module's own loader isn't
config-driven; every other detection module built on `market_common`
just takes `timeframe`/`as_of` directly and loads all available history).

See `market_common/data.py` for the actual loading/validation/resampling
logic -- not duplicated here.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.market_common import data as market_common_data
from src.market_common.models import DataQualityReport, Timeframe
from src.sr_lines.config import SRConfig

REQUIRED_SOURCE = market_common_data.REQUIRED_SOURCE


def load_bars(
    conn: sqlite3.Connection,
    ticker: str,
    config: SRConfig,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Load bars for `ticker`, windowed to `config.window_years` ending at
    `end` (default: latest available), excluding partial rows -- weekly
    resampling per `config.bar_interval` handled by `market_common.data`.

    Returns a DataFrame indexed by a sorted, deduplicated DatetimeIndex
    with columns open/high/low/close/volume -- raw, pre-validation.
    """
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp.now()
    start_ts = end_ts - pd.DateOffset(years=config.window_years)

    timeframe = Timeframe.WEEKLY if config.bar_interval == "1w" else Timeframe.DAILY
    return market_common_data.load_bars(conn, ticker, timeframe, as_of=end_ts, start=start_ts)


def validate_bars(
    bars: pd.DataFrame, ticker: str, config: SRConfig
) -> tuple[pd.DataFrame, DataQualityReport]:
    return market_common_data.validate_bars(bars, ticker, config.corruption_warning_threshold)


def load_and_validate(
    conn: sqlite3.Connection,
    ticker: str,
    config: SRConfig,
    end: str | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Convenience wrapper: load_bars + validate_bars in one call."""
    raw = load_bars(conn, ticker, config, end=end)
    return validate_bars(raw, ticker, config)
