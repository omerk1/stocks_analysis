"""Anchored volume profiles: the shared anchor discovery
(`market_common.anchors.discover_anchors` -- the exact same ath/atl/52w/
cycle anchors avwap uses) wrapped into this module's
`AnchoredVolumeProfile` model, each anchor's profile snapshot, and the
DB-facing `detect()` (same shape as avwap.anchors.detect / gaps.detect.
detect).

Staleness is resolved against *this* module's own `volume_profiles` table
(the caller passes `previous_anchor_types` from store.get_anchor_types),
not avwap's -- the two tables are independent consumers of one discovery
function, so neither run order nor either table's history affects the
other.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date

import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import indicators
from src.foundation.market_common.anchors import AnchorType, discover_anchors
from src.foundation.market_common.models import DataQualityReport, Timeframe
from src.signals.volume_profile import compute
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.models import AnchoredVolumeProfile

logger = logging.getLogger(__name__)


def build_for(bars: pd.DataFrame, anchor_date: str, config: VolumeProfileConfig) -> compute.Profile | None:
    """`compute.build_profile` with this config's row/value-area knobs --
    the one call site snapshot and plotting both go through, so a chart
    always shows exactly the profile that was stored."""
    return compute.build_profile(
        bars, anchor_date,
        row_count=config.row_count, row_scale=config.row_scale,
        value_area_pct=config.value_area_pct, volume_distribution=config.volume_distribution,
    )


def discover_profiles(
    bars: pd.DataFrame,
    ticker: str,
    timeframe: Timeframe,
    config: VolumeProfileConfig,
    previous_anchor_types: dict[str, frozenset[AnchorType]] | None = None,
) -> list[AnchoredVolumeProfile]:
    """Pure (no DB): deduped, capped, staleness-resolved anchors as
    `AnchoredVolumeProfile`s, snapshot fields left unset (see
    `apply_snapshot`)."""
    return [
        AnchoredVolumeProfile(
            id=str(uuid.uuid4()), ticker=ticker, timeframe=timeframe,
            anchor_date=a.anchor_date, anchor_types=a.anchor_types, status=a.status,
        )
        for a in discover_anchors(bars, timeframe, config, previous_anchor_types)
    ]


def apply_snapshot(
    bars: pd.DataFrame, atr: pd.Series, profile: AnchoredVolumeProfile, config: VolumeProfileConfig,
) -> AnchoredVolumeProfile:
    """Mutates and returns `profile` with the anchor-to-last-bar profile's
    POC/VAH/VAL, volumes, and where the last close sits against them.
    Stale anchors get refreshed too (same as avwap) -- stale means "no
    longer qualifies as an anchor", not "stop tracking what price did"."""
    built = build_for(bars, profile.anchor_date, config)
    profile.updated_through = bars.index[-1].isoformat() if not bars.empty else None
    if built is None:
        return profile

    close = float(bars["close"].iloc[-1])
    now_atr = atr.iloc[-1] if not atr.empty else float("nan")

    profile.poc, profile.vah, profile.val = built.poc, built.vah, built.val
    profile.total_volume = float(built.total.sum())
    profile.up_volume = float(built.up.sum())
    profile.down_volume = float(built.down.sum())
    profile.poc_up_volume = float(built.up[built.poc_row])
    profile.poc_down_volume = float(built.down[built.poc_row])
    profile.n_bars = built.n_bars
    profile.current_close = close
    profile.distance_to_poc_atr = (
        float((close - built.poc) / now_atr) if pd.notna(now_atr) and now_atr > 0 else None
    )
    if close > built.vah:
        profile.value_area_position = "above"
    elif close < built.val:
        profile.value_area_position = "below"
    else:
        profile.value_area_position = "inside"
    return profile


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: VolumeProfileConfig,
    as_of: str | pd.Timestamp | date | None = None,
    previous_anchor_types: dict[str, frozenset[AnchorType]] | None = None,
) -> tuple[list[AnchoredVolumeProfile], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, discover
    anchors, and snapshot each one's profile. Returns (profiles,
    quality_report, skip_reason) -- skip_reason is None on success,
    otherwise profiles is [] (mirrors avwap.anchors.detect)."""
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        logger.warning("%s/%s: skipping volume profile -- %s", ticker, timeframe.value, reason)
        return [], report, reason

    profiles = discover_profiles(bars, ticker, timeframe, config, previous_anchor_types)
    atr = indicators.atr(bars, config.atr_period)
    for profile in profiles:
        apply_snapshot(bars, atr, profile, config)
    return profiles, report, None
