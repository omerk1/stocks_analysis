"""Data loading and validation gate.

yfinance prices are split-AND-dividend adjusted (total-return style,
back-adjusted from the most recent date) -- confirmed directly against
Polygon and Alpha Vantage in this project (see docs/limitations.md).
Consequences for this module:

- Historical prices drift slightly between runs as new dividends shift the
  adjustment base. This is fine *within* a single run (the series is
  internally consistent, which is all detection needs) but means detected
  line prices must never be cached across runs/months -- always recompute
  against the current series.
- No round-number scoring component: back-adjusted historical prices are
  not round, so a "psychological level at $150" bonus would be meaningless
  and isn't implemented anywhere in this package.

Always filter to a single source (yfinance) -- Polygon and yfinance use
different adjustment conventions (split-only vs. split-and-dividend), and
mixing them in one series produces phantom levels.
"""

from __future__ import annotations

import logging
import sqlite3

import pandas as pd

from src.data_processing import db
from src.data_processing import resample as resample_mod
from src.sr_lines.config import SRConfig
from src.sr_lines.models import DataQualityReport

logger = logging.getLogger(__name__)

REQUIRED_SOURCE = db.YFINANCE

_JUMP_RATIO_LOW = 1 / 3
_JUMP_RATIO_HIGH = 3.0


def load_bars(
    conn: sqlite3.Connection,
    ticker: str,
    config: SRConfig,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Load bars for `ticker` from `bars_1d`, source=yfinance only, windowed
    to `config.window_years` ending at `end` (default: latest available),
    excluding partial (same-day) rows. If `config.bar_interval == "1w"`,
    resamples to weekly via `resample.to_weekly` (the same utility bulk
    ingestion's `resample_bulk.py` uses to populate `bars_1w`) -- always
    from `bars_1d`, never the separately-ingested `bars_1w` table directly.
    `bars_1w` is incomplete for several tickers (e.g. T and GEVO both have
    zero rows despite a fully backfilled `bars_1d` -- `resample_bulk.py`
    exists to fix that but was apparently never run against the full
    universe after the bulk daily backfill). Resampling live from `bars_1d`
    sidesteps that gap and can never drift out of sync with it in the
    future either.

    Returns a DataFrame indexed by a sorted, deduplicated DatetimeIndex with
    columns open/high/low/close/volume -- raw, pre-validation.
    """
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp.now()
    start_ts = end_ts - pd.DateOffset(years=config.window_years)

    raw = db.read_bars(
        conn, "bars_1d", ticker=ticker, source=REQUIRED_SOURCE,
        start=start_ts.strftime("%Y-%m-%d"), end=end_ts.strftime("%Y-%m-%d"),
    )
    if "is_partial" in raw.columns:
        raw = raw[raw["is_partial"] != 1]
    raw = raw[["open", "high", "low", "close", "volume"]]

    raw = raw[~raw.index.duplicated(keep="last")].sort_index()

    if config.bar_interval == "1w":
        # Every remaining daily row already survived the is_partial filter
        # above, so `is_partial=False` here -- to_weekly still correctly
        # flags the current in-progress week as partial purely from its own
        # calendar-closure rule, it just won't also see a same-day partial
        # constituent to flag on.
        #
        # `as_of` is deliberately `raw.index.max()`, not `end_ts` -- this
        # DB's daily data lags real wall-clock time by however long it's
        # been since the last ingestion run (confirmed on real PAAS data:
        # bars_1d's latest row was 2026-08-05, three real days behind
        # "now"). Judging week-closure against wall-clock "now" let a week
        # with only Mon-Wed rows read as "closed" purely because enough
        # real time had passed, silently aggregating an incomplete week as
        # if it were final -- a worse failure than the reverse: judging
        # against the data's own latest timestamp can only ever be *too*
        # conservative (a genuinely-closed week landing on a weekend as_of
        # might wait one extra day to be included), never silently wrong.
        as_of = raw.index.max() if not raw.empty else end_ts
        weekly = resample_mod.to_weekly(raw.assign(is_partial=False), as_of=as_of)
        raw = weekly[weekly["is_partial"] != True][["open", "high", "low", "close", "volume"]]  # noqa: E712
    return raw


def validate_bars(
    bars: pd.DataFrame, ticker: str, config: SRConfig
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Mandatory sanity pass before any detection runs.

    Hard checks (row dropped if violated):
      low <= min(open, close), max(open, close) <= high, low <= high,
      volume >= 0, all prices > 0.

    Soft check (logged, not dropped): day-over-day close ratio outside
    [1/3, 3] -- splits are already adjusted in this data, so a 3x jump is
    suspicious, but not necessarily wrong, so it's flagged for review rather
    than auto-dropped.

    Defensive: if `bars` carries a `source` column (e.g. a hand-built or
    multi-source frame passed in directly rather than via `load_bars`),
    assert it's a single value -- mixing sources here would silently
    produce phantom levels.
    """
    if "source" in bars.columns:
        distinct_sources = bars["source"].unique()
        if len(distinct_sources) != 1:
            raise ValueError(
                f"Expected exactly one source in input bars, got {list(distinct_sources)}"
            )
        bars = bars.drop(columns=["source"])

    rows_loaded = len(bars)

    hard_valid = (
        (bars["open"] > 0)
        & (bars["high"] > 0)
        & (bars["low"] > 0)
        & (bars["close"] > 0)
        & (bars["volume"] >= 0)
        & (bars["high"] >= bars["low"])
        & (bars[["open", "close"]].min(axis=1) >= bars["low"])
        & (bars[["open", "close"]].max(axis=1) <= bars["high"])
    )
    dropped = int((~hard_valid).sum())
    clean = bars[hard_valid].sort_index()

    close_ratio = clean["close"] / clean["close"].shift(1)
    suspicious_mask = (close_ratio < _JUMP_RATIO_LOW) | (close_ratio > _JUMP_RATIO_HIGH)
    suspicious_dates = [ts.strftime("%Y-%m-%d") for ts in clean.index[suspicious_mask.fillna(False)]]

    if dropped:
        logger.warning("Dropped %d row(s) with invalid OHLC values for %s", dropped, ticker)
    for d in suspicious_dates:
        logger.warning("Suspicious day-over-day close jump for %s on %s (ratio outside [1/3, 3])", ticker, d)

    drop_rate = dropped / rows_loaded if rows_loaded else 0.0
    unreliable = drop_rate > config.corruption_warning_threshold
    if unreliable:
        logger.warning(
            "%s: drop rate %.2f%% exceeds threshold %.2f%% -- treat this ticker's output as unreliable",
            ticker, drop_rate * 100, config.corruption_warning_threshold * 100,
        )

    report = DataQualityReport(
        ticker=ticker,
        rows_loaded=rows_loaded,
        rows_dropped=dropped,
        drop_rate=drop_rate,
        suspicious_jump_dates=suspicious_dates,
        unreliable=unreliable,
    )
    return clean, report


def load_and_validate(
    conn: sqlite3.Connection,
    ticker: str,
    config: SRConfig,
    end: str | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Convenience wrapper: load_bars + validate_bars in one call."""
    raw = load_bars(conn, ticker, config, end=end)
    return validate_bars(raw, ticker, config)
