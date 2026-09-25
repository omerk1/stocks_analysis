"""Anchor-date discovery -- which dates qualify as ath/atl/52w_high/52w_low/
cycle_high/cycle_low anchors, deduped by date, capped, and reconciled
against whatever was previously stored (staleness). Always recomputed
fresh from the current bars frame -- never incremental.

Extracted from `avwap/anchors.py` once a second anchored feature
(`volume_profile`) needed the exact same anchors: one implementation, not
two independently-maintained copies that could drift (same reasoning as
this package's own `pivots`/`derived_db`). Pure -- no DB, no
feature-specific output type. Each consumer turns the returned
`DiscoveredAnchor`s into its own stored model and supplies its *own*
table's `previous_anchor_types` for staleness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.pivots import PivotKind, detect_pivots

logger = logging.getLogger(__name__)

__all__ = [
    "AnchorType", "AnchorStatus", "AnchorConfig", "DiscoveredAnchor",
    "CYCLE_ROLES", "SENIORITY", "is_pure_cycle", "primary_role", "discover_anchors",
]


class AnchorType(str, Enum):
    ATH = "ath"
    ATL = "atl"
    WEEK_52_HIGH = "52w_high"
    WEEK_52_LOW = "52w_low"
    CYCLE_HIGH = "cycle_high"
    CYCLE_LOW = "cycle_low"


class AnchorStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"


CYCLE_ROLES = frozenset({AnchorType.CYCLE_HIGH, AnchorType.CYCLE_LOW})

# Shared by discovery (cap-trimming only ever removes pure-cycle anchors,
# never ath/atl/52w_*) and each consumer's plotting (color/saturation keyed
# off the most senior role present) -- one ranking, not independently-
# maintained copies that could drift.
SENIORITY = {
    AnchorType.ATH: 0, AnchorType.ATL: 0,
    AnchorType.WEEK_52_HIGH: 1, AnchorType.WEEK_52_LOW: 1,
    AnchorType.CYCLE_HIGH: 2, AnchorType.CYCLE_LOW: 2,
}


def is_pure_cycle(types) -> bool:
    types = frozenset(types)
    return bool(types) and types <= CYCLE_ROLES


def primary_role(types) -> AnchorType:
    return min(types, key=lambda t: SENIORITY[t])


@dataclass
class AnchorConfig:
    """Every anchor-discovery knob. Consumer configs (`AvwapConfig`,
    `VolumeProfileConfig`) subclass this, so their flat keyword arguments
    and `runs.config_json` serialization are unchanged by the extraction.
    """

    # Trailing lookback (in bars of the running timeframe) used to find the
    # 52w_high/52w_low anchor candidates -- keyed by Timeframe.value so
    # daily and weekly each get their own window instead of one shared
    # bar-count that would mean very different calendar spans.
    trailing_window_bars: dict[str, int] = field(
        default_factory=lambda: {"daily": 252, "weekly": 52}
    )

    # ATR multiplier for market_common.pivots.detect_pivots when finding
    # cycle_high/cycle_low anchor candidates -- much wider than sr_lines'
    # own pivot detection (which looks for local S/R turning points): an
    # anchor should mark a genuine cycle swing, not routine noise.
    cycle_scale_mult: float = 8.0

    # ATR lookback period feeding cycle_scale_mult above -- same default
    # gaps.config.GapConfig.atr_period/fibonacci.config.FibConfig.atr_period
    # use, but exposed here too (rather than a fixed module constant) so
    # every module's ATR period is tunable the same way.
    cycle_atr_period: int = 14

    # Most recent N confirmed cycle pivots (highs+lows combined, ranked by
    # date) become cycle_high/cycle_low anchor candidates.
    max_cycle_anchors: int = 4

    # Hard cap on total active anchors per (ticker, timeframe) -- see
    # _apply_cap for the trim-oldest-pure-cycle-first rule.
    max_anchors_total: int = 8

    # Skip (ticker, timeframe) with fewer rows than this, log a warning, no
    # detection at all.
    min_bars: int = 150

    # Skip this many leading bars of each series for cycle-pivot detection
    # only -- guarantees the ATR feeding detect_pivots' reversal threshold
    # is fully formed. ath/atl/52w_high/52w_low don't depend on ATR and are
    # deliberately searched over the *full* available history regardless of
    # this setting.
    warmup_bars: int = 50


@dataclass(frozen=True)
class DiscoveredAnchor:
    anchor_date: str
    anchor_types: frozenset[AnchorType]
    status: AnchorStatus


def _extreme_dates(bars: pd.DataFrame) -> tuple[str, str]:
    # idxmax/idxmin both return the *first* occurrence of the extreme value,
    # which is exactly the "ties -> earliest" rule the spec asks for.
    ath_ts = bars["high"].idxmax()
    atl_ts = bars["low"].idxmin()
    return ath_ts.isoformat(), atl_ts.isoformat()


def _trailing_extreme_dates(bars: pd.DataFrame, window: int) -> tuple[str, str]:
    trailing = bars.tail(window)
    return trailing["high"].idxmax().isoformat(), trailing["low"].idxmin().isoformat()


def _cycle_pivot_dates(bars: pd.DataFrame, config: AnchorConfig) -> list[tuple[str, AnchorType]]:
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


def _current_role_map(bars: pd.DataFrame, timeframe: Timeframe, config: AnchorConfig) -> dict[str, set[AnchorType]]:
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
    still gets its snapshot refreshed by the consumer (like any other stale
    anchor) instead of being silently dropped from the upsert batch and left
    frozen in the DB with whatever status/value it happened to have from the
    run before it got capped. Already-STALE entries are left alone -- they're
    not competing for the cap, and re-demoting them would just be a no-op
    status write.
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
            "anchors: %d active anchors still exceed max_anchors_total=%d after demoting every "
            "demotable pure-cycle anchor -- exceeding the cap rather than touching a "
            "protected (ath/atl/52w_*) anchor",
            active_count, max_total,
        )
    return kept


def discover_anchors(
    bars: pd.DataFrame,
    timeframe: Timeframe,
    config: AnchorConfig,
    previous_anchor_types: dict[str, frozenset[AnchorType]] | None = None,
) -> list[DiscoveredAnchor]:
    """Pure (no DB): given an already as_of-truncated bars frame and
    whatever anchor_types the *caller's own table* previously stored for
    this (ticker, timeframe) (empty/None for a from-scratch run), returns
    the deduped, capped, staleness-resolved anchors sorted by date.
    """
    role_map = _current_role_map(bars, timeframe, config)
    previous_anchor_types = previous_anchor_types or {}

    merged: dict[str, tuple[frozenset[AnchorType], AnchorStatus]] = {
        d: (frozenset(roles), AnchorStatus.ACTIVE) for d, roles in role_map.items()
    }
    # A stored anchor dated after this frame's last bar can only come from a
    # run at a later as_of -- it didn't exist yet as of this frame, so it's
    # left out entirely (and its stored row untouched) rather than marked
    # stale and handed to the consumer, which would overwrite its snapshot
    # with an empty pre-anchor window.
    last_bar = bars.index[-1] if not bars.empty else None
    for d, prev_types in previous_anchor_types.items():
        if last_bar is not None and pd.Timestamp(d) > last_bar:
            continue
        if d not in merged:
            # Still stored, no longer qualifies for anything today -- kept,
            # marked stale, anchor_types frozen at its last known value
            # (not cleared) so a later re-qualifying run has something
            # meaningful to compare against / fall back to.
            merged[d] = (frozenset(prev_types), AnchorStatus.STALE)

    capped = _apply_cap(merged, config.max_anchors_total)

    return [
        DiscoveredAnchor(anchor_date=d, anchor_types=types, status=status)
        for d, (types, status) in sorted(capped.items())
    ]
