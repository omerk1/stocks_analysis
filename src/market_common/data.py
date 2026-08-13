"""Data loading and validation gate -- extracted from `sr_lines/data.py`
(which now delegates here) so every detection module shares one
implementation of "load bars, validate them, apply as_of" rather than each
reimplementing it.

yfinance prices are split-AND-dividend adjusted (total-return style,
back-adjusted from the most recent date) -- confirmed directly against
Polygon and Alpha Vantage in this project (see docs/limitations.md).
Historical prices drift slightly between runs as new dividends shift the
adjustment base -- fine *within* a single run, but derived results must
never be cached across runs/months without recomputing against the
current series.

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
from src.market_common import indicators
from src.market_common.models import DataQualityReport, Timeframe

logger = logging.getLogger(__name__)

REQUIRED_SOURCE = db.YFINANCE

_JUMP_RATIO_LOW = 1 / 3
_JUMP_RATIO_HIGH = 3.0

# ATR period for the intraday-range check below -- 14 is the idiomatic
# default every other module in this project uses for ATR (sr_lines,
# gaps, divergences, fibonacci, avwap configs all default atr_period=14).
_INTRADAY_ATR_PERIOD = 14

# A bar's (high - low) vs. the *prior* bar's ATR(14) -- prior, not the
# same bar's own ATR, so one huge spike day can't inflate the very
# baseline it's being measured against. Tuned against real data (see
# docs/done.md): T's real 2023-01-24 bar -- a ~13% intraday spike that
# fully round-trips by the close, invisible to the close-to-close check
# above -- comes in at ratio 7.9, by far T's own all-time high (next
# highest in T's ~16y history: 5.4). Spot-checked against ~10 other real
# tickers spanning blue-chip (AAPL, MSFT, KO, JNJ) to meme/penny-stock
# volatility (GEVO, AMC, SMCI): a 3.0 threshold flags roughly 0.1-1.3% of
# trading days per ticker -- rare enough not to be "every normal volatile
# day," while still catching genuine outliers (including real, non-data-
# error events like AMC's 2021 short squeeze -- a soft flag surfacing
# those for review is correct, not a false positive).
_INTRADAY_RANGE_ATR_RATIO = 3.0

# 0.5% -- matches sr_lines' own long-standing default (SRConfig.
# corruption_warning_threshold). Not a config field here since this
# loader, unlike sr_lines' own, isn't driven by a per-package config
# object -- callers who need a different threshold pass it explicitly.
DEFAULT_CORRUPTION_WARNING_THRESHOLD = 0.005


def load_bars(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    as_of: str | pd.Timestamp | None = None,
    *,
    start: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Load bars for `ticker` from `bars_1d`, source=yfinance only, up to
    `as_of` (default: latest available), excluding partial (same-day)
    rows. `start` defaults to `None` (*all* available history) -- unlike
    sr_lines' own `SRConfig`-driven loader, callers here don't need a
    window/lookback; each module's own `min_bars` check decides whether
    the returned history is enough. `start` exists as a keyword-only
    escape hatch for `sr_lines.data.load_bars`, which does need a
    `window_years`-based window applied *before* weekly resampling (not
    after -- windowing a completed weekly resample would either produce a
    malformed partial boundary week or silently drop a real one).

    `timeframe=Timeframe.WEEKLY` resamples live from `bars_1d` via
    `resample.to_weekly` -- never reads the separately-ingested `bars_1w`
    table directly, which is incomplete for several tickers (e.g. T and
    GEVO both have zero rows despite a fully backfilled `bars_1d`) and can
    itself carry not-yet-finalized data. Resampling live sidesteps both
    and can never drift out of sync with `bars_1d` in the future either.

    Returns a DataFrame indexed by a sorted, deduplicated DatetimeIndex
    with columns open/high/low/close/volume -- raw, pre-validation.
    """
    end_ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now()
    start_str = pd.Timestamp(start).strftime("%Y-%m-%d") if start is not None else None

    raw = db.read_bars(
        conn, "bars_1d", ticker=ticker, source=REQUIRED_SOURCE,
        start=start_str, end=end_ts.strftime("%Y-%m-%d"),
    )
    if "is_partial" in raw.columns:
        raw = raw[raw["is_partial"] != 1]
    raw = raw[["open", "high", "low", "close", "volume"]]

    raw = raw[~raw.index.duplicated(keep="last")].sort_index()

    if timeframe == Timeframe.WEEKLY:
        # Every remaining daily row already survived the is_partial filter
        # above, so `is_partial=False` here -- to_weekly still correctly
        # flags the current in-progress week as partial purely from its own
        # calendar-closure rule, it just won't also see a same-day partial
        # constituent to flag on.
        #
        # `as_of` for to_weekly is deliberately `raw.index.max()`, not
        # `end_ts` -- this DB's daily data lags real wall-clock time by
        # however long it's been since the last ingestion run (confirmed on
        # real PAAS data). Judging week-closure against wall-clock "now"
        # let a week with only Mon-Wed rows read as "closed" purely because
        # enough real time had passed -- judging against the data's own
        # latest timestamp can only ever be *too* conservative, never
        # silently wrong the other way.
        weekly_as_of = raw.index.max() if not raw.empty else end_ts
        weekly = resample_mod.to_weekly(raw.assign(is_partial=False), as_of=weekly_as_of)
        raw = weekly[weekly["is_partial"] != True][["open", "high", "low", "close", "volume"]]  # noqa: E712
    return raw


def validate_bars(
    bars: pd.DataFrame,
    ticker: str,
    corruption_warning_threshold: float = DEFAULT_CORRUPTION_WARNING_THRESHOLD,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Mandatory sanity pass before any detection runs.

    Hard checks (row dropped if violated):
      low <= min(open, close), max(open, close) <= high, low <= high,
      volume >= 0, all prices > 0.

    Soft checks (logged, not dropped):
      - day-over-day close ratio outside [1/3, 3] -- splits are already
        adjusted in this data, so a 3x jump is suspicious, but not
        necessarily wrong, so it's flagged for review rather than
        auto-dropped.
      - intraday range (high - low) more than 3x the prior bar's ATR(14)
        -- catches a same-day spike-and-round-trip (e.g. T's real
        2023-01-24 bar) that the close-based check above can't see, since
        the close ends up looking perfectly normal. Same soft treatment:
        flagged, not dropped -- a single unusually volatile-but-real
        trading day shouldn't get silently deleted from history.

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

    prior_atr = indicators.atr(clean, _INTRADAY_ATR_PERIOD).shift(1)
    intraday_range = clean["high"] - clean["low"]
    intraday_ratio = intraday_range / prior_atr
    # `prior_atr > 0` also excludes the NaN ATR warmup tail (NaN comparisons
    # are always False), same effect as suspicious_mask's `.fillna(False)`
    # above, just applied a step earlier since this mask feeds a ratio too.
    intraday_range_mask = (prior_atr > 0) & (intraday_ratio > _INTRADAY_RANGE_ATR_RATIO)
    suspicious_intraday_range_dates = [
        ts.strftime("%Y-%m-%d") for ts in clean.index[intraday_range_mask]
    ]

    if dropped:
        logger.warning("Dropped %d row(s) with invalid OHLC values for %s", dropped, ticker)
    for d in suspicious_dates:
        logger.warning("Suspicious day-over-day close jump for %s on %s (ratio outside [1/3, 3])", ticker, d)
    for d in suspicious_intraday_range_dates:
        logger.warning(
            "Suspicious intraday range for %s on %s (high-low > %.1fx prior ATR(%d))",
            ticker, d, _INTRADAY_RANGE_ATR_RATIO, _INTRADAY_ATR_PERIOD,
        )

    drop_rate = dropped / rows_loaded if rows_loaded else 0.0
    unreliable = drop_rate > corruption_warning_threshold
    if unreliable:
        logger.warning(
            "%s: drop rate %.2f%% exceeds threshold %.2f%% -- treat this ticker's output as unreliable",
            ticker, drop_rate * 100, corruption_warning_threshold * 100,
        )

    report = DataQualityReport(
        ticker=ticker,
        rows_loaded=rows_loaded,
        rows_dropped=dropped,
        drop_rate=drop_rate,
        suspicious_jump_dates=suspicious_dates,
        suspicious_intraday_range_dates=suspicious_intraday_range_dates,
        unreliable=unreliable,
    )
    return clean, report


def load_and_validate(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    as_of: str | pd.Timestamp | None = None,
    corruption_warning_threshold: float = DEFAULT_CORRUPTION_WARNING_THRESHOLD,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Convenience wrapper: load_bars + validate_bars in one call."""
    raw = load_bars(conn, ticker, timeframe, as_of=as_of)
    return validate_bars(raw, ticker, corruption_warning_threshold)
