"""Classic (2-bar) and FVG (3-bar) gap detection, plus the top-level
`detect()` entry point that loads/validates bars and runs the full
detect -> lifecycle pipeline for one (ticker, timeframe) as of a given date.

`detect_gaps` itself is a pure function over an already-loaded bars frame --
no DB access, no as_of handling -- so synthetic tests can hand it a small,
hand-built DataFrame directly. `detect()` is the only place as_of actually
gets applied (via `market_common.data.load_and_validate`), which is what
guarantees zero lookahead: nothing downstream (detection or lifecycle) ever
sees a bar later than as_of, because it's never in the frame to begin with.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date

import pandas as pd

from src.gaps import lifecycle
from src.gaps.config import GapConfig
from src.gaps.models import Direction, Gap, GapKind, Timeframe
from src.market_common import data as data_mod
from src.market_common import indicators
from src.market_common.models import DataQualityReport

logger = logging.getLogger(__name__)


def detect_gaps(
    bars: pd.DataFrame, ticker: str, timeframe: Timeframe, config: GapConfig
) -> list[Gap]:
    """Scan `bars` (ascending DatetimeIndex, columns open/high/low/close/
    volume, already validated) for classic and FVG gaps, sized against
    ATR at the creation bar.

    Skips the first `max(2, config.warmup_bars)` bars -- 2 is the hard
    floor an FVG's t-2 lookback needs regardless of config, warmup_bars is
    the ATR-warmup floor the config asks for on top of that.
    """
    n = len(bars)
    if n < 3:
        return []

    atr_series = indicators.atr(bars, config.atr_period)
    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    idx = bars.index

    gaps: list[Gap] = []
    start = max(2, config.warmup_bars)
    for t in range(start, n):
        atr_t = atr_series.iloc[t]
        if pd.isna(atr_t) or atr_t <= 0:
            continue
        created_at = idx[t].isoformat()

        classic_gap: Gap | None = None
        classic_direction: Direction | None = None
        if lows[t] > highs[t - 1]:
            classic_direction = Direction.BULLISH
            zone_bottom, zone_top = float(highs[t - 1]), float(lows[t])
        elif highs[t] < lows[t - 1]:
            classic_direction = Direction.BEARISH
            zone_bottom, zone_top = float(highs[t]), float(lows[t - 1])

        if classic_direction is not None:
            size_atr = (zone_top - zone_bottom) / atr_t
            if size_atr >= config.min_gap_atr:
                classic_gap = Gap(
                    id=str(uuid.uuid4()), ticker=ticker, timeframe=timeframe,
                    kind=GapKind.CLASSIC, direction=classic_direction, created_at=created_at,
                    zone_top=zone_top, zone_bottom=zone_bottom, size_atr=float(size_atr),
                )
                gaps.append(classic_gap)

        fvg_direction: Direction | None = None
        if highs[t - 2] < lows[t]:
            fvg_direction = Direction.BULLISH
            fvg_bottom, fvg_top = float(highs[t - 2]), float(lows[t])
        elif lows[t - 2] > highs[t]:
            fvg_direction = Direction.BEARISH
            fvg_bottom, fvg_top = float(highs[t]), float(lows[t - 2])

        if fvg_direction is not None:
            size_atr = (fvg_top - fvg_bottom) / atr_t
            if size_atr >= config.min_gap_atr:
                related_id = (
                    classic_gap.id
                    if classic_gap is not None and classic_gap.direction == fvg_direction
                    else None
                )
                gaps.append(Gap(
                    id=str(uuid.uuid4()), ticker=ticker, timeframe=timeframe,
                    kind=GapKind.FVG, direction=fvg_direction, created_at=created_at,
                    zone_top=fvg_top, zone_bottom=fvg_bottom, size_atr=float(size_atr),
                    related_id=related_id,
                ))

    return gaps


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: GapConfig,
    as_of: str | pd.Timestamp | date | None = None,
) -> tuple[list[Gap], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, detect
    gaps, and walk their lifecycle forward through the same as_of-truncated
    bars. Returns (gaps, quality_report, skip_reason) -- skip_reason is
    None on success, otherwise gaps is [] and quality_report still reflects
    what was loaded (so callers/CLI can report *why* a ticker was skipped,
    not just that it was).
    """
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        logger.warning("%s/%s: skipping gap detection -- %s", ticker, timeframe.value, reason)
        return [], report, reason

    gaps = detect_gaps(bars, ticker, timeframe, config)
    gaps = lifecycle.apply_lifecycle(bars, gaps, config)
    return gaps, report, None
