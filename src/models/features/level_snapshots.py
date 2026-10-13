"""The weekly snapshot sources of the LRP levels (`docs/modeling/LRP.md` §4):
S/R lines, AVWAP anchors and volume profiles, each detector run on the bars up
to each week's last bar. Separate from `levels` (the daily roll-forward, gaps
and bar sources) because the snapshot cache's code hash covers this file: a
change to the cheap daily sources mustn't invalidate a 10-hour cache. Pure
functions of the bars and splits passed in; nothing here reads a database.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common.history_breaks import anchor_start_date
from src.foundation.market_common.models import Timeframe
from src.signals.avwap.anchors import detect_on_bars as detect_avwap
from src.signals.avwap.config import AvwapConfig
from src.signals.sr_lines.config import SRConfig
from src.signals.sr_lines.engine import detect_lines
from src.signals.sr_lines.models import LineKind, LineState
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.detect import build_for, discover_profiles

DAILY = Timeframe.DAILY
# The first week a snapshot is taken (the development window's start). A
# snapshot's dates depend only on the bars, so the snapshot cache and a
# registered source computing from the same bars agree on them.
SNAPSHOT_START = pd.Timestamp("2010-01-01")
SNAPSHOT_SOURCES = ("sr_line", "avwap", "vp")
LEVEL_COLUMNS = ["source", "kind", "lo", "hi", "strength_raw", "formed", "touches", "state"]
SNAPSHOT_COLUMNS = ["snapshot", *LEVEL_COLUMNS, "anchor_date"]


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    """The detectors' own validation (`market_common.data.validate_bars`): rows
    failing a row-local check are dropped, so validating once and truncating
    later equals validating each truncated frame."""
    clean, _ = data_mod.validate_bars(bars[["open", "high", "low", "close", "volume"]], "_")
    return clean


def snapshot_dates(index: pd.DatetimeIndex, start: pd.Timestamp = SNAPSHOT_START) -> pd.DatetimeIndex:
    """The last bar of each Friday-ending week on or after `start` (a Friday
    holiday moves the snapshot to Thursday)."""
    days = index[index >= start]
    if not len(days):
        return pd.DatetimeIndex([])
    last = pd.Series(days, index=days).groupby(days.to_period("W-FRI")).max()
    return pd.DatetimeIndex(last.to_numpy())


def _rows(snapshot, source, kind, lo, hi, strength, formed, touches, state, anchor_date=None) -> dict:
    return {"snapshot": snapshot, "source": source, "kind": kind, "lo": lo, "hi": hi, "strength_raw": strength,
            "formed": pd.Timestamp(formed) if formed is not None else pd.NaT,
            "touches": touches, "state": state,
            "anchor_date": pd.Timestamp(anchor_date) if anchor_date is not None else pd.NaT}


def _frame(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)
    out["touches"] = out["touches"].astype("float64")
    return out


def sr_snapshots(bars: pd.DataFrame, dates, config: SRConfig) -> pd.DataFrame:
    """Each S/R line as of each date: `sr_lines.engine.detect` on the
    `window_years` of bars ending there. Broken lines are dropped, flipped ones
    kept (LRP §1.1)."""
    if config.diagonal_enabled:
        raise ValueError("diagonal S/R lines need a daily price; v1 uses horizontal lines only")
    if config.bar_interval != "1d":
        raise ValueError(f"snapshots run on daily bars; got bar_interval={config.bar_interval!r}")
    rows = []
    for t in dates:
        window = bars.loc[t - pd.DateOffset(years=config.window_years):t]
        if window.empty:  # as `detect` does: any non-empty window is scanned
            continue
        for line in detect_lines(window, config):
            if line.state == LineState.BROKEN or line.kind != LineKind.HORIZONTAL:
                continue
            rows.append(_rows(t, "sr_line", "line", line.center - line.half_width, line.center + line.half_width,
                              line.strength, line.first_touch, line.touch_counts.total, line.state.value))
    return _frame(rows)


def _history_start(bars, splits, config, ticker) -> pd.Timestamp | None:
    """`history_breaks.anchor_start_for` on the splits passed in (the bars' own
    vendor's), with the per-ticker overrides."""
    if not config.history_breaks.enabled:
        return None
    return anchor_start_date(bars, splits, config.history_breaks, ticker=ticker)


def avwap_snapshots(
    bars: pd.DataFrame, splits: pd.DataFrame | None, dates, config: AvwapConfig, ticker: str,
) -> pd.DataFrame:
    """Each AVWAP anchor as of each date (`avwap.anchors.detect`'s steps, from
    scratch: no previously stored anchor types). Zone = value ± 0.5 std;
    strength = average reaction on a touch, in ATRs, over (1 + crosses) -- a
    level crossed often is weak (LRP §1.1; the discount's form is a prior)."""
    rows = []
    for t in dates:
        b = bars.loc[:t]
        if len(b) < config.min_bars:
            continue
        for a in detect_avwap(b, ticker, DAILY, config, None, _history_start(b, splits, config, ticker)):
            if a.current_value is None:
                continue
            half = 0.5 * (a.current_std or 0.0)
            strength = (a.avg_reaction_atr_on_touch / (1 + a.n_crosses)
                        if a.avg_reaction_atr_on_touch is not None else np.nan)
            rows.append(_rows(t, "avwap", "avwap", a.current_value - half, a.current_value + half, strength,
                              a.anchor_date, np.nan, a.status.value, anchor_date=a.anchor_date))
    return _frame(rows)


def vp_snapshots(
    bars: pd.DataFrame, splits: pd.DataFrame | None, dates, config: VolumeProfileConfig, ticker: str,
) -> pd.DataFrame:
    """POC, VAH and VAL of each anchored volume profile as of each date. The
    POC is its row's price band; VAH and VAL are the value area's edges.
    Strength = the share of the profile's volume in the level's row."""
    rows = []
    for t in dates:
        b = bars.loc[:t]
        if len(b) < config.min_bars:
            continue
        start = _history_start(b, splits, config, ticker)
        for p in discover_profiles(b, ticker, DAILY, config, None, history_start=start):
            built = build_for(b, p.anchor_date, config)
            if built is None:
                continue
            total = built.total
            vol = float(total.sum())
            if vol <= 0:
                continue
            share = lambda row: float(total[row]) / vol  # noqa: E731
            poc_lo, poc_hi = float(built.edges[built.poc_row]), float(built.edges[built.poc_row + 1])
            for kind, lo, hi, row in (("poc", poc_lo, poc_hi, built.poc_row),
                                      ("vah", built.vah, built.vah, built.va_high_row),
                                      ("val", built.val, built.val, built.va_low_row)):
                rows.append(_rows(t, "vp", kind, lo, hi, share(row), p.anchor_date, np.nan, p.status.value,
                                  anchor_date=p.anchor_date))
    return _frame(rows)


def snapshots(source: str, bars: pd.DataFrame, splits: pd.DataFrame | None, dates, config, ticker: str) -> pd.DataFrame:
    """One snapshot source's levels on each of `dates`; `bars` already `prepare`d."""
    if source == "sr_line":
        return sr_snapshots(bars, dates, config)
    if source == "avwap":
        return avwap_snapshots(bars, splits, dates, config, ticker)
    if source == "vp":
        return vp_snapshots(bars, splits, dates, config, ticker)
    raise ValueError(f"unknown snapshot source {source!r}")
