"""AVWAP anchors: the shared, pure anchor-date discovery
(`market_common.anchors.discover_anchors` -- ath/atl/52w_high/52w_low/
cycle_high/cycle_low, deduped by date, capped, staleness-resolved) wrapped
into this module's `AnchoredVwap` model, plus the DB-facing `detect()`.

`discover_anchor_dates` is the pure core (no DB) and is what the staleness
tests drive directly, feeding one call's output back in as the next call's
`previous_anchor_types`. `detect()` is the DB-facing entry point (loads
bars, fills in each anchor's current AVWAP snapshot value) that
gaps.detect.detect's cli.py callers will recognize the shape of.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date

import pandas as pd

from src.signals.avwap.config import AvwapConfig
from src.signals.avwap.lifecycle import apply_interaction_tracking
from src.signals.avwap.models import AnchoredVwap, AnchorType
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import indicators
from src.foundation.market_common.anchors import discover_anchors
from src.foundation.market_common.models import DataQualityReport, Timeframe

logger = logging.getLogger(__name__)


def discover_anchor_dates(
    bars: pd.DataFrame,
    ticker: str,
    timeframe: Timeframe,
    config: AvwapConfig,
    previous_anchor_types: dict[str, frozenset[AnchorType]] | None = None,
) -> list[AnchoredVwap]:
    """Pure (no DB): given an already as_of-truncated bars frame and
    whatever anchor_types were previously stored for this (ticker,
    timeframe) (empty/None for a from-scratch run), returns the deduped,
    capped, staleness-resolved anchor list -- with `current_value`/
    `updated_through` left unset (that needs compute.anchored_vwap, done by
    `detect()`).
    """
    return [
        AnchoredVwap(
            id=str(uuid.uuid4()), ticker=ticker, timeframe=timeframe,
            anchor_date=a.anchor_date, anchor_types=a.anchor_types, status=a.status,
        )
        for a in discover_anchors(bars, timeframe, config, previous_anchor_types)
    ]


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: AvwapConfig,
    as_of: str | pd.Timestamp | date | None = None,
    previous_anchor_types: dict[str, frozenset[AnchorType]] | None = None,
) -> tuple[list[AnchoredVwap], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, discover
    anchors, and snapshot each one's current AVWAP value. Returns (anchors,
    quality_report, skip_reason) -- skip_reason is None on success,
    otherwise anchors is [] and quality_report still reflects what was
    loaded (mirrors gaps.detect.detect's return shape).
    """
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        logger.warning("%s/%s: skipping avwap anchor discovery -- %s", ticker, timeframe.value, reason)
        return [], report, reason

    anchors = discover_anchor_dates(bars, ticker, timeframe, config, previous_anchor_types)

    # Same ATR series/period cycle-pivot detection above already uses
    # (config.cycle_atr_period) -- reused here rather than adding a second
    # ATR knob just for interaction tracking.
    atr = indicators.atr(bars, config.cycle_atr_period)
    for anchor in anchors:
        apply_interaction_tracking(bars, atr, anchor, config)

    return anchors, report, None
