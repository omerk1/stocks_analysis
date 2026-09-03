"""Anchor discovery: which dates qualify as ath/atl/52w_high/52w_low/
cycle_high/cycle_low anchors, deduped by date, capped, and reconciled
against whatever was previously stored (staleness). Always recomputed
fresh from the current bars frame -- never incremental.

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
from src.signals.avwap.models import AnchoredVwap, AnchorStatus, AnchorType, is_pure_cycle
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import indicators
from src.foundation.market_common.models import DataQualityReport, Timeframe
from src.foundation.market_common.pivots import PivotKind, detect_pivots

logger = logging.getLogger(__name__)


def _extreme_dates(bars: pd.DataFrame) -> tuple[str, str]:
    # idxmax/idxmin both return the *first* occurrence of the extreme value,
    # which is exactly the "ties -> earliest" rule the spec asks for.
    ath_ts = bars["high"].idxmax()
    atl_ts = bars["low"].idxmin()
    return ath_ts.isoformat(), atl_ts.isoformat()


def _trailing_extreme_dates(bars: pd.DataFrame, window: int) -> tuple[str, str]:
    trailing = bars.tail(window)
    return trailing["high"].idxmax().isoformat(), trailing["low"].idxmin().isoformat()


def _cycle_pivot_dates(bars: pd.DataFrame, config: AvwapConfig) -> list[tuple[str, AnchorType]]:
    """Most recent `max_cycle_anchors` confirmed pivots (highs+lows
    combined, ranked by date) on `close`, using an ATR-scaled reversal
    threshold. `confirmed_at <= as_of` is automatically satisfied without
    an explicit filter: `bars` is already truncated to as_of by the caller,
    and detect_pivots can never confirm a pivot beyond the last bar it was
    given.
    """
    start = min(config.warmup_bars, max(len(bars) - 1, 0))
    close = bars["close"].iloc[start:]
    if len(close) < 2:
        return []
    atr_series = indicators.atr(bars, config.cycle_atr_period).iloc[start:]

    pivots = detect_pivots(close, threshold_fn=lambda i: config.cycle_scale_mult * atr_series.iloc[i])
    pivots = sorted(pivots, key=lambda p: p.timestamp, reverse=True)[: config.max_cycle_anchors]

    return [
        (p.timestamp, AnchorType.CYCLE_HIGH if p.kind == PivotKind.HIGH else AnchorType.CYCLE_LOW)
        for p in pivots
    ]


def _current_role_map(bars: pd.DataFrame, timeframe: Timeframe, config: AvwapConfig) -> dict[str, set[AnchorType]]:
    role_map: dict[str, set[AnchorType]] = {}

    def _add(anchor_date: str, role: AnchorType) -> None:
        role_map.setdefault(anchor_date, set()).add(role)

    ath_date, atl_date = _extreme_dates(bars)
    _add(ath_date, AnchorType.ATH)
    _add(atl_date, AnchorType.ATL)

    window = config.trailing_window_bars[timeframe.value]
    w52_high_date, w52_low_date = _trailing_extreme_dates(bars, window)
    _add(w52_high_date, AnchorType.WEEK_52_HIGH)
    _add(w52_low_date, AnchorType.WEEK_52_LOW)

    for pivot_date, role in _cycle_pivot_dates(bars, config):
        _add(pivot_date, role)

    return role_map


def _apply_cap(
    entries: dict[str, tuple[frozenset[AnchorType], AnchorStatus]], max_total: int
) -> dict[str, tuple[frozenset[AnchorType], AnchorStatus]]:
    """Demote the oldest ACTIVE pure-cycle anchors to STALE once ACTIVE count
    exceeds `max_total` -- demote, not delete, so every capped-out anchor
    still gets its `current_value`/`updated_through` refreshed by `detect()`
    below (like any other stale anchor) instead of being silently dropped
    from the upsert batch and left frozen in the DB with whatever
    status/value it happened to have from the run before it got capped.
    Already-STALE entries are left alone -- they're not competing for the
    cap, and re-demoting them would just be a no-op status write.
    """
    active_count = sum(1 for _, status in entries.values() if status == AnchorStatus.ACTIVE)
    if active_count <= max_total:
        return entries

    # ISO date strings sort chronologically, so a plain sorted() gives
    # oldest-first without parsing back to Timestamp.
    demotable = sorted(
        d for d, (types, status) in entries.items()
        if status == AnchorStatus.ACTIVE and is_pure_cycle(types)
    )

    kept = dict(entries)
    for d in demotable:
        if active_count <= max_total:
            break
        types, _status = kept[d]
        kept[d] = (types, AnchorStatus.STALE)
        active_count -= 1

    if active_count > max_total:
        logger.warning(
            "avwap: %d active anchors still exceed max_anchors_total=%d after demoting every "
            "demotable pure-cycle anchor -- exceeding the cap rather than touching a "
            "protected (ath/atl/52w_*) anchor",
            active_count, max_total,
        )
    return kept


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
    role_map = _current_role_map(bars, timeframe, config)
    previous_anchor_types = previous_anchor_types or {}

    merged: dict[str, tuple[frozenset[AnchorType], AnchorStatus]] = {
        d: (frozenset(roles), AnchorStatus.ACTIVE) for d, roles in role_map.items()
    }
    for d, prev_types in previous_anchor_types.items():
        if d not in merged:
            # Still stored, no longer qualifies for anything today -- kept,
            # marked stale, anchor_types frozen at its last known value
            # (not cleared) so a later re-qualifying run has something
            # meaningful to compare against / fall back to.
            merged[d] = (frozenset(prev_types), AnchorStatus.STALE)

    capped = _apply_cap(merged, config.max_anchors_total)

    return [
        AnchoredVwap(
            id=str(uuid.uuid4()), ticker=ticker, timeframe=timeframe,
            anchor_date=d, anchor_types=types, status=status,
        )
        for d, (types, status) in sorted(capped.items())
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
