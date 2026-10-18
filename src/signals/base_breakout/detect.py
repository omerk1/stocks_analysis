"""Base-breakout-retest detection: a long flat base, a breakout close above its high,
then a later retest of that level from above that holds.

Built for the strategy agent's first live idea ("when a stock breaks out of a long base
and then comes back to retest the breakout level, the retest holding tends to be
followed by a rise") as the detector behind `detector:base_breakout.retest` — but it is
ordinary signal code, usable on its own like the sibling modules.

Point-in-time by construction, bar by bar on plain OHLC:

- **Base / level.** At a candidate breakout bar t, the level is the maximum high over
  the trailing `base_lookback_bars` bars before t, and the base starts at the *last*
  bar that set that high. The base must be at least `base_min_bars` long (time since
  the level was last touched — a high set three bars ago has no base under it), and its
  depth — (level − lowest low of the base) / level — must sit inside
  [`depth_min_pct`, `depth_max_pct`]. Too shallow is drift under a spike, not a base;
  too deep is a collapsed stock, not a consolidation.
- **Breakout.** The first close above the level. Closes above a still-rising running
  max during the subsequent rally don't start overlapping episodes: one episode per
  ticker at a time.
- **Retest.** Within `retest_window_bars` after the breakout, the first bar whose low
  comes back within `retest_tol_atr` ATRs of the level *and* whose close holds at or
  above it. That bar is the signal (`Episode.retest`).
- **Kill.** A close more than `kill_tol_atr` ATRs *below* the level before a holding
  retest ends the episode: the retest failed rather than held (the idea's before-entry
  invalidation). The hold/fail call is made on the retest bar's own close, so unlike a
  pattern throwback vs failed breakout (see `patterns/lifecycle.py`, which removed its
  fixed reclaim window for being undecidable mid-flight) it is decidable point-in-time.

A NaN in close/high/low/ATR inside an episode's walk ends the episode as EXPIRED at
that bar rather than letting a NaN comparison silently read as "nothing happened"
(CLAUDE.md invariant 9's failure mode, applied to detection).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RETEST_HELD = "retest_held"
KILLED = "killed"
EXPIRED = "expired"


@dataclass(frozen=True)
class BreakoutRetestConfig:
    base_min_bars: int = 30          # minimum bars since the level was last touched
    base_max_bars: int | None = None  # optional cap on base length
    depth_min_pct: float = 10.0      # base depth below the level, in percent of the level
    depth_max_pct: float = 40.0
    base_lookback_bars: int = 504    # how far back the level search reaches (caps base length)
    retest_window_bars: int = 40     # bars after the breakout a retest may arrive in
    retest_tol_atr: float = 0.5      # the retest low must come within this many ATRs of the level
    kill_tol_atr: float = 0.25       # a close this many ATRs below the level kills the episode

    def validate(self) -> None:
        if not 0 < self.depth_min_pct < self.depth_max_pct < 100:
            raise ValueError(
                f"depth bounds must satisfy 0 < min < max < 100 percent, got "
                f"[{self.depth_min_pct:g}, {self.depth_max_pct:g}]")
        if self.base_min_bars < 2:
            raise ValueError(f"base_min_bars must be at least 2, got {self.base_min_bars}")
        if self.base_max_bars is not None and self.base_max_bars > self.base_lookback_bars:
            raise ValueError(
                f"base_max_bars ({self.base_max_bars}) exceeds the level search lookback "
                f"({self.base_lookback_bars}); raise base_lookback_bars")
        if self.retest_window_bars < 1 or self.retest_tol_atr < 0 or self.kill_tol_atr < 0:
            raise ValueError("retest window must be >= 1 bar and tolerances non-negative")


@dataclass(frozen=True)
class Episode:
    """One base-breakout episode. `retest` is the signal bar (position into the
    ticker's bars) when the retest held; None when the episode was killed or expired.
    `end` is the bar the episode resolved on, whatever the outcome."""

    base_start: int
    breakout: int
    retest: int | None
    end: int
    level: float
    base_bars: int
    depth_pct: float
    outcome: str  # RETEST_HELD | KILLED | EXPIRED


def detect(bars: pd.DataFrame, atr: pd.Series, config: BreakoutRetestConfig) -> list[Episode]:
    """All episodes in one ticker's date-sorted `bars` (needs high/low/close), walked
    chronologically. `atr` is the same-length average true range used by the retest and
    kill tolerances. Positions in the returned episodes index into `bars`' rows."""
    config.validate()
    if len(atr) != len(bars):
        raise ValueError(f"atr has {len(atr)} rows, bars {len(bars)}")
    high = bars["high"].to_numpy(dtype="float64")
    low = bars["low"].to_numpy(dtype="float64")
    close = bars["close"].to_numpy(dtype="float64")
    atr_values = atr.to_numpy(dtype="float64")
    n = len(close)

    # The level at t is the max high over the `base_lookback_bars` bars BEFORE t —
    # nothing from t itself or later, so detection at t uses only history.
    prior_max = (pd.Series(high).rolling(config.base_lookback_bars, min_periods=1)
                 .max().shift(1).to_numpy())
    with np.errstate(invalid="ignore"):  # NaN close or prior_max simply never fires
        candidates = np.flatnonzero(close > prior_max)

    episodes: list[Episode] = []
    busy_until = -1  # one episode at a time: rally closes above a rising max don't re-trigger
    for t in candidates:
        t = int(t)
        if t <= busy_until:
            continue
        level = float(prior_max[t])
        if level <= 0:
            continue
        window_start = max(0, t - config.base_lookback_bars)
        segment = high[window_start:t]
        # Last bar that set the level: base length is time since the level was touched.
        base_start = window_start + int(np.flatnonzero(segment == level)[-1])
        base_bars = t - base_start
        if base_bars < config.base_min_bars:
            continue
        if config.base_max_bars is not None and base_bars > config.base_max_bars:
            continue
        base_lows = low[base_start:t]
        if np.isnan(base_lows).any():
            continue  # a base with holes can't have its depth measured honestly
        depth_pct = (level - float(base_lows.min())) / level * 100.0
        if not config.depth_min_pct <= depth_pct <= config.depth_max_pct:
            continue

        retest: int | None = None
        outcome = EXPIRED
        end = min(t + config.retest_window_bars, n - 1)
        for u in range(t + 1, t + config.retest_window_bars + 1):
            if u >= n:
                end = n - 1
                break
            if np.isnan(close[u]) or np.isnan(low[u]) or np.isnan(atr_values[u]):
                end = u  # undecidable bar: end the episode rather than read NaN as "held"
                break
            if close[u] < level - config.kill_tol_atr * atr_values[u]:
                outcome, end = KILLED, u
                break
            if low[u] <= level + config.retest_tol_atr * atr_values[u] and close[u] >= level:
                retest, outcome, end = u, RETEST_HELD, u
                break
        episodes.append(Episode(base_start=base_start, breakout=t, retest=retest, end=end,
                                level=level, base_bars=base_bars, depth_pct=depth_pct,
                                outcome=outcome))
        busy_until = end
    return episodes


def level_overlay(n: int, episodes: list[Episode]) -> np.ndarray:
    """The breakout level as a plottable series: NaN everywhere except each episode's
    span (base start through resolution), where it holds the episode's level. Episodes
    later in the list win any overlap."""
    overlay = np.full(n, np.nan)
    for episode in episodes:
        overlay[episode.base_start:episode.end + 1] = episode.level
    return overlay
