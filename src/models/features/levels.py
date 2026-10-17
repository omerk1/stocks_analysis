"""Point-in-time price levels for the LRP features (`docs/modeling/LRP.md` §1, §4).

The stored signal tables are current-state, so levels are regenerated as of each
date from one ticker's bars, never read from the DB:

- **Weekly snapshots** (`level_snapshots.snapshots`): S/R lines, AVWAP anchors and volume
  profiles, each detector run on the bars up to the week's last bar.
- **Gaps**: one detection over the whole frame, then each gap's exact state on
  every day (`gaps.relevance.gap_states`, tested equal to an `as_of` run).
- **Daily roll-forward** (`daily_levels`): every day takes the latest snapshot
  it can know of (`held_snapshot`: its own on a Friday, the one before
  otherwise -- whether another day ends its week depends on later bars). AVWAP
  prices are recomputed daily from their anchors; everything else in a
  snapshot is held until the next one (new levels are at most 4 days late on a
  normal week, never early). The sources that need no detector -- SMA
  20/50/200, the 52-week high/low and round numbers -- are computed daily.

All prices are on the traded basis (split-adjusted, as the detectors use), so a
level's distance from the close, in ATRs, is a ratio within the past: a later
split rescales both alike. Round numbers are the one exception -- they depend on
the price that traded -- so they are placed on the unadjusted close and mapped
back.

`strength_raw` is each source's native strength (LRP §1.1), not yet a
percentile: the trailing per-source percentile, decay and state factors are the
features' job. Pure functions of the bars and splits passed in; nothing here
reads a database.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.market_common.history_breaks import unadjusted_close
from src.models.features.level_snapshots import (  # noqa: F401 -- re-exported: the snapshot half of the levels
    DAILY, LEVEL_COLUMNS, SNAPSHOT_COLUMNS, SNAPSHOT_SOURCES, SNAPSHOT_START, avwap_snapshots, prepare,
    snapshot_dates, snapshots, sr_snapshots, vp_snapshots,
)
from src.signals.avwap.compute import anchored_vwap_std
from src.signals.avwap.config import AvwapConfig
from src.signals.gaps.config import GapConfig
from src.signals.gaps.detect import detect_on_bars as detect_gaps
from src.signals.gaps.relevance import gap_states
from src.signals.sr_lines.config import get_preset
from src.signals.volume_profile.config import VolumeProfileConfig

DAILY_COLUMNS = ["date", *LEVEL_COLUMNS]

# Fixed strengths for the sources with no native one (LRP §1.1).
BAR_SOURCE_STRENGTH = {"ma": 0.5, "hi52": 0.5, "lo52": 0.5, "round": 0.25}
MA_WINDOWS = (20, 50, 200)
HI_LO_WINDOW = 252
ROUND_PER_SIDE = 2  # nearest round numbers kept above and below the close


def default_configs() -> dict[str, object]:
    """Each detector's config as its own CLI runs it (LRP §1.1's sources)."""
    return {"sr_line": get_preset("medium_term"), "avwap": AvwapConfig(), "vp": VolumeProfileConfig(),
            "gaps": GapConfig()}


def gap_levels(bars: pd.DataFrame, days, config: GapConfig) -> pd.DataFrame:
    """Open, in-reach gaps on each day, from one detection over `bars`. Strength
    = size in ATRs x the unfilled share x the creation-day volume ratio when
    known (LRP §1.1). `gap_states`' `max_fill_pct` is a percentage (0-100)."""
    gaps, _ = detect_gaps(bars, "_", DAILY, config)
    states = gap_states(bars, gaps, days, config)
    states = states[states["in_reach"].astype(bool)]
    vol = pd.to_numeric(states["volume_ratio_at_creation"], errors="coerce").fillna(1.0)
    return pd.DataFrame({
        "date": pd.to_datetime(states["date"]), "source": "gap", "kind": states["kind"].astype(str),
        "lo": states["zone_bottom"].astype(float), "hi": states["zone_top"].astype(float),
        "strength_raw": states["size_atr"].astype(float) * (1 - states["max_fill_pct"].astype(float) / 100) * vol,
        "formed": pd.to_datetime(states["created_at"]), "touches": np.nan, "state": states["status"].astype(str),
    }, columns=DAILY_COLUMNS)


def round_step(price: np.ndarray) -> np.ndarray:
    """The round-number spacing for a traded price (LRP §1.1)."""
    return np.select([price < 20, price < 100, price < 500], [1.0, 5.0, 10.0], 50.0)


# Unadjusting a traded price through a float32 close or an inexact vendor split
# ratio (7.000007) leaves a traded $20.00 at 19.9999995: a price within this
# relative distance of a round number counts as on it, for the step and the level.
_SNAP = 1e-6


def _on_grid(price: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(step, price / step snapped onto a whole number when within `_SNAP`)."""
    price = np.asarray(price, dtype=float)
    step = round_step(price * (1 + _SNAP))
    q = price / step
    near = np.round(q)
    return step, np.where(np.abs(q - near) <= _SNAP * q, near, q)


def round_below(price: np.ndarray) -> np.ndarray:
    """The largest round number at or below `price`, on its own bracket's step."""
    step, q = _on_grid(price)
    return np.floor(q) * step


def round_above(price: np.ndarray) -> np.ndarray:
    """The smallest round number strictly above `price`. The bracket edges (20,
    100, 500) are multiples of every smaller step, so stepping from a bracket
    edge onto the next bracket's step stays round."""
    step, q = _on_grid(price)
    return (np.floor(q) + 1) * step


def bar_levels(bars: pd.DataFrame, splits: pd.DataFrame | None, days) -> pd.DataFrame:
    """SMA 20/50/200, the trailing 252-day high and low (of highs and lows), and
    the nearest round numbers above and below the close, on each day. Undefined
    until their windows fill (no row, not a zero)."""
    days = pd.DatetimeIndex(days)
    close = bars["close"]
    parts = []
    for w in MA_WINDOWS:
        sma = close.rolling(w, min_periods=w).mean()
        parts.append(pd.DataFrame({"date": sma.index, "source": "ma", "kind": f"sma_{w}", "lo": sma.values,
                                   "hi": sma.values, "strength_raw": BAR_SOURCE_STRENGTH["ma"]}))
    for source, series in (("hi52", bars["high"].rolling(HI_LO_WINDOW, min_periods=HI_LO_WINDOW).max()),
                           ("lo52", bars["low"].rolling(HI_LO_WINDOW, min_periods=HI_LO_WINDOW).min())):
        parts.append(pd.DataFrame({"date": series.index, "source": source, "kind": source, "lo": series.values,
                                   "hi": series.values, "strength_raw": BAR_SOURCE_STRENGTH[source]}))
    raw = unadjusted_close(bars, splits).to_numpy()
    factor = close.to_numpy() / raw  # traded -> adjusted, as of each day
    up, dn = raw, raw
    for k in range(ROUND_PER_SIDE):
        # Each next level on the step of the bracket it lands in.
        up = round_above(up)
        dn = round_below(dn if k == 0 else dn * (1 - 10 * _SNAP))  # then strictly below the last one
        for kind, level in ((f"round_up_{k + 1}", up), (f"round_dn_{k + 1}", dn)):
            adj = level * factor
            parts.append(pd.DataFrame({"date": bars.index, "source": "round", "kind": kind, "lo": adj, "hi": adj,
                                       "strength_raw": BAR_SOURCE_STRENGTH["round"]}))
    out = pd.concat(parts, ignore_index=True)
    out = out[out["date"].isin(days) & out["lo"].notna() & (out["lo"] > 0)]
    out = out.assign(formed=pd.NaT, touches=np.nan, state="active")
    return out[DAILY_COLUMNS]


def held_snapshot(taken: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Per day, the position in sorted `taken` of the snapshot it holds (-1:
    none): its own on a Friday, else the latest taken before it. A Friday ends
    its week whatever follows; any other day is its week's last bar only if
    no bar follows that week (a ticker delisted on a Wednesday has a snapshot
    there, the same bars running on to Friday don't, and a Thursday before a
    Friday holiday is one only from the calendar), so its own snapshot would be
    a peek at the future. New levels are at most 4 days late on a normal week,
    a week after a short one, never early."""
    days = np.asarray(days, dtype="datetime64[ns]")
    pos = np.searchsorted(taken, days, side="right") - 1
    own = (pos >= 0) & (taken[np.maximum(pos, 0)] == days)
    friday = pd.DatetimeIndex(days).dayofweek == 4
    return np.where(own & ~friday, pos - 1, pos)


def daily_levels(
    bars: pd.DataFrame, splits: pd.DataFrame | None, snaps: pd.DataFrame, days, taken, configs: dict,
) -> pd.DataFrame:
    """Every level on each of `days` (long: date, source, kind, lo, hi,
    strength_raw, formed, touches, state). `bars` already `prepare`d; `snaps`
    is the snapshot sources' rows concatenated; `taken` every date a snapshot
    was taken on (the calendar, including weeks a source had nothing: a week
    whose lines all broke must not fall back to the week before). A day holds
    `held_snapshot`'s snapshot (its own only on a Friday); a day holding none
    gets no snapshot levels. Stale anchors are dropped (LRP
    §1.1: "anchor inactive"). `configs`: `default_configs()`'s shape."""
    days = pd.DatetimeIndex(days)
    parts = []
    taken = np.sort(pd.DatetimeIndex(taken).to_numpy())
    if len(taken):
        pos = held_snapshot(taken, days.to_numpy())
        has = pos >= 0
        which = pd.DataFrame({"date": days[has], "snapshot": taken[pos[has]]})
        held = which.merge(snaps, on="snapshot", how="inner")
        held = held[held["state"] != "stale"]
        # AVWAP moves every day: its price comes from the anchor, through that day.
        is_avwap = held["source"] == "avwap"
        if is_avwap.any():
            vals = []
            for anchor, g in held[is_avwap].groupby("anchor_date"):
                band = anchored_vwap_std(bars, anchor, configs["avwap"].price_source)
                at = band.reindex(pd.DatetimeIndex(g["date"]))
                half = 0.5 * at["std"].fillna(0.0).to_numpy()
                vals.append(pd.DataFrame({"lo": at["vwap"].to_numpy() - half, "hi": at["vwap"].to_numpy() + half},
                                         index=g.index))
            moved = pd.concat(vals)
            held.loc[moved.index, ["lo", "hi"]] = moved[["lo", "hi"]].to_numpy()
        parts.append(held[DAILY_COLUMNS])
    parts.append(gap_levels(bars, days, configs["gaps"]))
    parts.append(bar_levels(bars, splits, days))
    # All-empty columns (no `formed` for the bar sources) are left out of the
    # concat, which would otherwise decide dtypes from them, and restored after.
    parts = [p.dropna(axis=1, how="all") for p in parts if len(p)]
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=DAILY_COLUMNS)
    out = out.reindex(columns=DAILY_COLUMNS)
    out["formed"] = pd.to_datetime(out["formed"])
    out["touches"] = out["touches"].astype("float64")
    out = out[out["lo"].notna()]
    return out.sort_values(["date", "source", "lo"], ignore_index=True)
