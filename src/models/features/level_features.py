"""The LRP level features (`docs/modeling/LRP.md` §1.2, §2.1-2.3): per-date
summaries of the point-in-time levels (`levels.daily_levels`), in ATRs of the
close.

    values = ticker_features(bars, splits, ticker, root=levels_root)

Each level on date t gets a signed distance `d = (edge - C) / A` (the zone
edge nearest the close C, ATR(14) A; 0 when the zone contains C, which counts
on both sides) and a weight `w = strength_pctile x decay(age) x state_factor`
(LRP §1.2, `prior_factor` = 1):

- `strength_pctile`: the level's native strength as a mid-rank percentile among
  its source's levels over the trailing `STRENGTH_WINDOW` trading days, t
  included (invariant 3: trailing only). A level with no native strength yet
  (an AVWAP never touched) gets 0.5. The bar sources have no native strength:
  their fixed `levels.BAR_SOURCE_STRENGTH` is used as is.
- `decay(age) = 0.5 ** (age / 126)`, age in bars since the level formed (the
  bar sources: 0).
- `state_factor`: 0.8 flipped, 1.2 tested (an S/R line with two or more
  touches, a partly filled gap), 1.0 otherwise.

From those, three groups (LRP §2.1-2.3):

- **nearest** (§2.1): per source, the nearest level above and below
  (`near_up_<source>`, `near_dn_<source>`, capped at `CAP`), and for the
  sources with a native strength that level's `w`. NaN when the source has no
  level on that side. The 52-week high is never below the close and the low
  never above, so each has one side only.
- **aggregate** (§2.2): distance to the first point where cumulative `w` reaches
  0.5 / 1.5 (`clear_*`), `w` within h ATRs (`density_*`), `lrp_dir`,
  `lrp_pressure_*`, and the strongest two-source cluster within 5 ATRs
  (`confluence_*`).
- **barrier** (§2.3), on a fixed distance grid (LRP §2.3's option for a model
  that doesn't take the cell as an input): the strongest level at a target
  distance (`target_on_wall_<U>`), a floor just above a stop
  (`stop_below_floor_<D>`), and the share of the latest volume profile's volume
  between the close and the barrier (`vp_ease_up_<U>`, `vp_ease_dn_<D>`). §2.3's
  `obstacle_up(U)` and `cushion_dn(D)` are `density_up_h` / `density_dn_h` on
  the same grid, so they aren't repeated.

Every column is NaN where the close or ATR is undefined and on days that hold
no snapshot yet (`levels.held_snapshot`; the levels aren't known); a count or
sum is 0 only where it is
defined and nothing is there. All prices are on the traded basis, so every
column is a ratio within the past (a later split rescales both sides).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.models.features import level_cache, levels
from src.signals.volume_profile.detect import build_for

ATR_PERIOD = 14
STRENGTH_WINDOW = 252
HALF_LIFE = 126
CAP = 10.0
NATIVE = ("sr_line", "avwap", "vp", "gap")         # sources with a native strength
TWO_SIDED = (*NATIVE, "ma", "round")
TESTED = {"sr_line": None, "gap": ("partial", "soft_closed")}  # None: by touches >= 2
CLEAR_THETAS = (0.5, 1.5)
DENSITY_H = (1, 2, 3, 5, 7)
PRESSURE_H = (2, 3)
CONFLUENCE_WIDTH, CONFLUENCE_REACH = 0.5, 5.0
WALL_U, WALL_BAND = (2, 3, 5, 7), 0.25
FLOOR_D, FLOOR_BAND, FLOOR_MIN_W = (1, 2, 3), 0.5, 0.5
EASE_UP, EASE_DN = (2, 3, 5, 7), (1, 2, 3)
DIR_OFFSET = 0.25

DEFAULT_ROOT = Path("data/models/levels")  # build-levels' default --out
SNAPSHOT_START = levels.SNAPSHOT_START


def _num(x: float) -> str:
    return f"{x:g}".replace(".", "p")


NEAREST = (
    *[f"near_{side}_{s}" for s in TWO_SIDED for side in ("up", "dn")],
    "near_up_hi52", "near_dn_lo52",
    *[f"near_{side}_w_{s}" for s in NATIVE for side in ("up", "dn")],
)
AGGREGATE = (
    *[f"clear_{side}_{_num(t)}" for t in CLEAR_THETAS for side in ("up", "dn")],
    *[f"density_{side}_{h}" for h in DENSITY_H for side in ("up", "dn")],
    "lrp_dir",
    *[f"lrp_pressure_{h}" for h in PRESSURE_H],
    "confluence_up", "confluence_up_dist", "confluence_dn", "confluence_dn_dist",
)
BARRIER = (
    *[f"target_on_wall_{u}" for u in WALL_U],
    *[f"stop_below_floor_{d}" for d in FLOOR_D],
    *[f"vp_ease_up_{u}" for u in EASE_UP],
    *[f"vp_ease_dn_{d}" for d in EASE_DN],
)
COLUMNS = (*NEAREST, *AGGREGATE, *BARRIER)


def strength_percentile(day: np.ndarray, strength: np.ndarray, window: int = STRENGTH_WINDOW) -> np.ndarray:
    """Mid-rank percentile of each row's strength among the rows of days
    (day - window, day], `day` an integer trading-day position. NaN strength:
    0.5, and not counted in anyone's reference."""
    out = np.full(len(day), 0.5)
    order = np.argsort(day, kind="stable")
    d, s = day[order], strength[order]
    valid = ~np.isnan(s)
    res = np.full(len(d), 0.5)
    for u in np.unique(d):
        lo, hi = np.searchsorted(d, u - window, side="right"), np.searchsorted(d, u, side="right")
        ref = np.sort(s[lo:hi][valid[lo:hi]])
        if not len(ref):
            continue
        at = slice(np.searchsorted(d, u, side="left"), hi)
        x = s[at]
        pct = (np.searchsorted(ref, x, side="left") + np.searchsorted(ref, x, side="right")) / (2 * len(ref))
        res[at] = np.where(np.isnan(x), 0.5, pct)
    out[order] = res
    return out


def weights(daily: pd.DataFrame, index: pd.DatetimeIndex) -> np.ndarray:
    """LRP §1.2's `w` for every row of `daily` (`levels.daily_levels` output,
    on the trading days of `index`)."""
    day = index.get_indexer(pd.DatetimeIndex(daily["date"]))
    strength = daily["strength_raw"].to_numpy(dtype=float)
    pct = np.empty(len(daily))
    source = daily["source"].to_numpy()
    for s in np.unique(source):
        rows = source == s
        pct[rows] = (strength_percentile(day[rows], strength[rows]) if s in NATIVE
                     else levels.BAR_SOURCE_STRENGTH[s])
    formed = pd.DatetimeIndex(daily["formed"])
    born = np.where(formed.isna(), day, index.searchsorted(formed.fillna(index[0]), side="left"))
    age = np.clip(day - born, 0, None)
    state = daily["state"].to_numpy()
    touches = daily["touches"].to_numpy(dtype=float)
    tested = ((source == "sr_line") & (touches >= 2)) | ((source == "gap") & np.isin(state, TESTED["gap"]))
    factor = np.where(state == "flipped", 0.8, np.where(tested, 1.2, 1.0))
    return pct * 0.5 ** (age / HALF_LIFE) * factor


def _first_reach(d: np.ndarray, w: np.ndarray, theta: float) -> float:
    """Distance (ascending `d`) where cumulative `w` first reaches theta, capped."""
    hit = np.flatnonzero(np.cumsum(w) >= theta)
    return min(float(d[hit[0]]), CAP) if len(hit) else CAP


def _confluence(d: np.ndarray, w: np.ndarray, src: np.ndarray) -> tuple[float, float]:
    """Largest sum of `w` in a CONFLUENCE_WIDTH window (starting at a level,
    ascending `d` within CONFLUENCE_REACH) holding two or more sources, and
    that window's near edge; (0, NaN) when no window qualifies."""
    keep = d <= CONFLUENCE_REACH
    d, w, src = d[keep], w[keep], src[keep]
    if len(d) < 2:
        return 0.0, np.nan
    inside = (d[None, :] >= d[:, None]) & (d[None, :] <= d[:, None] + CONFLUENCE_WIDTH)
    sums = inside @ w
    first = np.where(inside, src[None, :], -1).max(axis=1)
    mixed = (inside & (src[None, :] != first[:, None])).any(axis=1)
    if not mixed.any():
        return 0.0, np.nan
    best = int(np.argmax(np.where(mixed, sums, -np.inf)))
    return float(sums[best]), float(d[best])


def _vp_share(edges: np.ndarray, total: np.ndarray, lo: float, hi: float) -> float:
    """Share of the profile's volume in [lo, hi], each row's volume spread
    evenly across it."""
    vol = total.sum()
    if vol <= 0:
        return np.nan
    left, right = edges[:-1], edges[1:]
    width = np.where(right > left, right - left, np.nan)
    overlap = np.clip(np.minimum(right, hi) - np.maximum(left, lo), 0, None)
    frac = np.where(np.isnan(width), ((left >= lo) & (left <= hi)).astype(float), overlap / width)
    return float((np.nan_to_num(frac) * total).sum() / vol)


def _profiles(clean: pd.DataFrame, daily: pd.DataFrame, taken: np.ndarray, config) -> dict:
    """Per day, the latest-anchored volume profile it holds, as (edges, total)
    built on the bars up to the snapshot that day holds."""
    vp = daily[daily["source"] == "vp"]
    if vp.empty:
        return {}
    latest = vp.groupby("date")["formed"].max()
    days = latest.index.to_numpy()
    pos = levels.held_snapshot(taken, days)
    if (pos < 0).any():  # -1 would wrap to the last, future, snapshot
        raise ValueError("volume-profile rows on a day that holds no snapshot")
    held = taken[pos]
    built, out = {}, {}
    for day, snap, anchor in zip(days, held, latest.to_numpy()):
        key = (snap, anchor)
        if key not in built:
            p = build_for(clean.loc[:snap], pd.Timestamp(anchor), config)
            built[key] = None if p is None else (np.asarray(p.edges, dtype=float), np.asarray(p.total, dtype=float))
        out[pd.Timestamp(day)] = built[key]
    return out


def features(clean: pd.DataFrame, daily: pd.DataFrame, taken, configs: dict) -> pd.DataFrame:
    """Every column of `COLUMNS` on each day of `clean` (bars `prepare`d);
    `daily` and `taken` as `levels.daily_levels` takes and returns them."""
    index = clean.index
    close = clean["close"].to_numpy(dtype=float)
    atr = indicators.atr(clean, ATR_PERIOD).to_numpy(dtype=float)
    taken = np.sort(pd.DatetimeIndex(taken).to_numpy())
    values = np.full((len(index), len(COLUMNS)), np.nan, dtype="float32")
    if not len(taken):  # no day holds a snapshot: nothing is defined
        return pd.DataFrame(values, index=index, columns=list(COLUMNS))
    pos = index.get_indexer(pd.DatetimeIndex(daily["date"]))
    w = weights(daily, index)
    c, a = close[pos], atr[pos]
    lo, hi = daily["lo"].to_numpy(dtype=float), daily["hi"].to_numpy(dtype=float)
    d = np.where(lo > c, (lo - c) / a, np.where(hi < c, (hi - c) / a, 0.0))
    sources = daily["source"].to_numpy()
    codes = {s: i for i, s in enumerate(sorted(set(sources)))}
    src = np.array([codes[s] for s in sources])
    profiles = _profiles(clean, daily, taken, configs["vp"])

    defined = ~np.isnan(close) & ~np.isnan(atr) & (atr > 0) & (levels.held_snapshot(taken, index.to_numpy()) >= 0)
    order = np.lexsort((d, pos))
    pos, d, w, src, sources = pos[order], d[order], w[order], src[order], sources[order]
    ok = ~np.isnan(d)
    pos, d, w, src, sources = pos[ok], d[ok], w[ok], src[ok], sources[ok]
    starts = np.searchsorted(pos, np.arange(len(index)), side="left")
    ends = np.searchsorted(pos, np.arange(len(index)), side="right")
    col ={name: j for j, name in enumerate(COLUMNS)}
    for i in np.flatnonzero(defined):
        sl = slice(starts[i], ends[i])
        di, wi, si, names = d[sl], w[sl], src[sl], sources[sl]
        row = values[i]
        up, dn = di >= 0, di <= 0
        for s in (*TWO_SIDED, "hi52", "lo52"):
            mine = names == s
            for side, mask, sign in (("up", up, 1), ("dn", dn, -1)):
                name = f"near_{side}_{s}"
                if name not in col:
                    continue
                m = np.flatnonzero(mine & mask)
                if not len(m):
                    continue
                j = m[np.argmin(sign * di[m])]
                row[col[name]] = min(abs(di[j]), CAP)
                if s in NATIVE:
                    row[col[f"near_{side}_w_{s}"]] = wi[j]
        ud, uw, us = di[up], wi[up], si[up]
        dd, dw, ds = -di[dn][::-1], wi[dn][::-1], si[dn][::-1]  # ascending distance below
        clear = {}
        for t in CLEAR_THETAS:
            clear[("up", t)] = row[col[f"clear_up_{_num(t)}"]] = _first_reach(ud, uw, t)
            clear[("dn", t)] = row[col[f"clear_dn_{_num(t)}"]] = _first_reach(dd, dw, t)
        density = {}
        for h in DENSITY_H:
            density[("up", h)] = row[col[f"density_up_{h}"]] = uw[ud <= h].sum()
            density[("dn", h)] = row[col[f"density_dn_{h}"]] = dw[dd <= h].sum()
        row[col["lrp_dir"]] = np.log((clear[("up", 1.5)] + DIR_OFFSET) / (clear[("dn", 1.5)] + DIR_OFFSET))
        for h in PRESSURE_H:
            row[col[f"lrp_pressure_{h}"]] = density[("dn", h)] - density[("up", h)]
        for side, (sd, sw, ss) in (("up", (ud, uw, us)), ("dn", (dd, dw, ds))):
            row[col[f"confluence_{side}"]], row[col[f"confluence_{side}_dist"]] = _confluence(sd, sw, ss)
        for u in WALL_U:
            near = np.abs(ud - u) <= WALL_BAND
            row[col[f"target_on_wall_{u}"]] = uw[near].max() if near.any() else 0.0
        for k in FLOOR_D:
            row[col[f"stop_below_floor_{k}"]] = float(((dd >= k - FLOOR_BAND) & (dd <= k) & (dw >= FLOOR_MIN_W)).any())
        prof = profiles.get(index[i])
        if prof is not None:
            edges, total = prof
            ci, ai = close[i], atr[i]
            for u in EASE_UP:
                row[col[f"vp_ease_up_{u}"]] = _vp_share(edges, total, ci, ci + u * ai)
            for k in EASE_DN:
                row[col[f"vp_ease_dn_{k}"]] = _vp_share(edges, total, ci - k * ai, ci)
    return pd.DataFrame(values, index=index, columns=list(COLUMNS))  # float32, like every model feature


def ticker_features(
    bars: pd.DataFrame, splits: pd.DataFrame | None, ticker: str, root: Path | None = DEFAULT_ROOT,
    snapshot_start: pd.Timestamp = SNAPSHOT_START,
) -> pd.DataFrame:
    """`COLUMNS` for one ticker on the dates of `bars` (traded basis, by date).
    Snapshots come from the snapshot cache under `root` when its fingerprint
    matches these bars (the full history the cache was built from), else are
    computed (and not stored). `snapshot_start`: the first snapshot week; the
    leakage gate starts near its cut to keep the detector runs few."""
    clean = levels.prepare(bars)
    taken = levels.snapshot_dates(clean.index, snapshot_start)
    configs = levels.default_configs()
    digest = level_cache.inputs_digest(ticker, clean, splits, taken)
    snaps = [level_cache.cached_snapshots(root, s, ticker, clean, splits, taken, configs[s],
                                          key=level_cache.fingerprint(s, ticker, clean, splits, taken, configs[s],
                                                                      digest))
             for s in levels.SNAPSHOT_SOURCES]
    snaps = pd.concat([s for s in snaps if len(s)], ignore_index=True) if any(len(s) for s in snaps) \
        else pd.DataFrame(columns=levels.SNAPSHOT_COLUMNS)
    days = clean.index[levels.held_snapshot(taken.to_numpy(), clean.index.to_numpy()) >= 0] if len(taken) \
        else clean.index[:0]
    daily = levels.daily_levels(clean, splits, snaps, days, taken, configs)
    return features(clean, daily, taken, configs).reindex(pd.DatetimeIndex(bars.index))
