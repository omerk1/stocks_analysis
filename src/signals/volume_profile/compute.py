"""Anchored volume profile -- pure functions over an OHLCV frame and an
anchor date. No DB/store coupling, so it can be unit-tested directly and
reused by the intraday validation (validate_intraday.py), which feeds the
exact same `build_profile` hourly bars instead of daily ones.

Zero look-ahead by construction: the profile at a bar only ever sees bars
from `anchor_date` through the last bar of the frame it's handed, and the
row grid itself is sized from that same window's own [lowest low, highest
high] -- the caller truncates `bars` to as_of first (market_common.data.
load_and_validate does), exactly as avwap.compute.anchored_vwap relies on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ROW_SCALES = ("linear", "log")
VOLUME_DISTRIBUTIONS = ("uniform_hl",)


@dataclass(frozen=True)
class Profile:
    """Per-row volume histogram plus the POC/value-area rows it implies.
    Row i spans [edges[i], edges[i+1]); the last row also includes its
    upper edge."""

    edges: np.ndarray  # row_count + 1, ascending
    mids: np.ndarray  # row_count -- arithmetic mid (linear rows), geometric mid (log rows)
    up: np.ndarray  # row_count -- volume from bars with close >= open
    down: np.ndarray  # row_count -- volume from bars with close < open
    poc_row: int
    va_low_row: int
    va_high_row: int
    n_bars: int

    @property
    def total(self) -> np.ndarray:
        return self.up + self.down

    @property
    def poc(self) -> float:
        return float(self.mids[self.poc_row])

    @property
    def vah(self) -> float:
        return float(self.edges[self.va_high_row + 1])

    @property
    def val(self) -> float:
        return float(self.edges[self.va_low_row])


def row_edges(low: float, high: float, row_count: int, row_scale: str = "linear") -> np.ndarray:
    """`row_count + 1` ascending edges spanning [low, high]. A zero-width
    range (every bar in the window traded at one price) gets a tiny
    symmetric pad so the single price still lands in a real row rather
    than dividing by zero."""
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")
    if row_scale not in ROW_SCALES:
        raise ValueError(f"Unknown row_scale: {row_scale!r}")
    if high <= low:
        pad = max(abs(low) * 1e-6, 1e-9)
        low, high = low - pad, high + pad
    if row_scale == "log":
        if low <= 0:
            raise ValueError(f"log row_scale needs a positive price range, got low={low}")
        return np.geomspace(low, high, row_count + 1)
    return np.linspace(low, high, row_count + 1)


def _row_mids(edges: np.ndarray, row_scale: str) -> np.ndarray:
    if row_scale == "log":
        return np.sqrt(edges[:-1] * edges[1:])
    return (edges[:-1] + edges[1:]) / 2.0


def distribute_uniform_hl(high: np.ndarray, low: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """(n_bars, n_rows) fraction of each bar's volume landing in each row,
    each bar's volume spread evenly across its [low, high] range. A
    zero-range bar (high == low) puts its whole volume in the single row
    containing that price (the upper row when it sits exactly on an
    interior edge). Every bar is assumed to lie inside [edges[0],
    edges[-1]] -- true by construction when `edges` came from the same
    window's own min low / max high.

    Built as the difference of each bar's cumulative fraction-below-edge,
    so every row gets exactly its overlap share and each bar's fractions
    sum to 1 without any per-bar loop.
    """
    high = high[:, None]
    low = low[:, None]
    span = high - low
    with np.errstate(divide="ignore", invalid="ignore"):
        cdf = np.clip((edges[None, :] - low) / span, 0.0, 1.0)
    point = (span <= 0).ravel()
    if point.any():
        cdf[point] = (edges[None, :] > low[point]).astype(float)
    # The outer edges bound every bar in the window -- pin them so a bar
    # touching the very top/bottom (including a zero-range bar sitting
    # exactly on edges[-1]) can't leak volume out of the grid.
    cdf[:, 0] = 0.0
    cdf[:, -1] = 1.0
    return np.diff(cdf, axis=1)


def _poc_row(total: np.ndarray, mids: np.ndarray) -> int:
    """Max-volume row. Ties (exactly equal volume -- realistic only on
    synthetic data) go to the row closest to the profile's own
    volume-weighted mean price, then to the lower row: the most "central"
    of several equally-traded prices, deterministically."""
    peak = total.max()
    tied = np.flatnonzero(total >= peak)
    if len(tied) == 1:
        return int(tied[0])
    vwap = float((total * mids).sum() / total.sum())
    return int(min(tied, key=lambda i: (abs(mids[i] - vwap), i)))


def value_area_rows(total: np.ndarray, poc_row: int, value_area_pct: float) -> tuple[int, int]:
    """Classic Market Profile / TradingView value-area expansion: start at
    the POC row, repeatedly compare the volume of the next two rows above
    against the next two rows below and add the larger pair (both, if
    equal), until the area holds at least `value_area_pct` of total volume
    or the whole profile is covered. Adding a pair at a time means the
    area can overshoot the target slightly -- that's the convention, not
    an off-by-one. Returns (low_row, high_row), inclusive."""
    n = len(total)
    target = value_area_pct * total.sum()
    lo = hi = poc_row
    acc = total[poc_row]
    while acc < target and (lo > 0 or hi < n - 1):
        above = total[hi + 1 : hi + 3].sum() if hi < n - 1 else -1.0
        below = total[max(lo - 2, 0) : lo].sum() if lo > 0 else -1.0
        if above >= below:
            acc += above
            hi = min(hi + 2, n - 1)
        if below >= above:
            acc += below
            lo = max(lo - 2, 0)
    return lo, hi


def build_profile(
    bars: pd.DataFrame,
    anchor_date,
    row_count: int = 100,
    row_scale: str = "linear",
    value_area_pct: float = 0.70,
    volume_distribution: str = "uniform_hl",
) -> Profile | None:
    """Volume profile of `bars` from `anchor_date` (inclusive) through the
    frame's last bar. `bars` needs open/high/low/close/volume and a
    DatetimeIndex; it can be any resolution (daily, weekly, hourly -- an
    hourly frame's intraday timestamps on the anchor date are all included).
    Returns None when the window has no bars or no volume.

    Up/down split by the bar's own close >= open (TradingView's bar-level
    rule). POC/value area always use total volume."""
    if volume_distribution not in VOLUME_DISTRIBUTIONS:
        raise ValueError(f"Unknown volume_distribution: {volume_distribution!r}")

    anchor_ts = pd.Timestamp(anchor_date).normalize()
    window = bars.loc[bars.index >= anchor_ts, ["open", "high", "low", "close", "volume"]].dropna()
    if window.empty:
        return None
    volume = window["volume"].to_numpy(dtype=float)
    if volume.sum() <= 0:
        return None

    high = window["high"].to_numpy(dtype=float)
    low = window["low"].to_numpy(dtype=float)
    edges = row_edges(float(low.min()), float(high.max()), row_count, row_scale)
    mids = _row_mids(edges, row_scale)

    weights = distribute_uniform_hl(high, low, edges)
    is_up = (window["close"] >= window["open"]).to_numpy()
    up = (weights * (volume * is_up)[:, None]).sum(axis=0)
    down = (weights * (volume * ~is_up)[:, None]).sum(axis=0)

    total = up + down
    poc = _poc_row(total, mids)
    va_low, va_high = value_area_rows(total, poc, value_area_pct)
    return Profile(
        edges=edges, mids=mids, up=up, down=down,
        poc_row=poc, va_low_row=va_low, va_high_row=va_high, n_bars=len(window),
    )
