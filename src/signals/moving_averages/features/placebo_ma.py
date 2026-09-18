"""Ad hoc MA + `dist_pct`/`dist_atr` build for the §7.5 placebo test and M5
(PREREGISTRATION.md, 2026-09-12 / 2026-09-17): SMA{187,193,207,213} vs
SMA200, SMA{47,53} vs SMA50, EMA{19,23} vs EMA21 -- none of these lookbacks
are in the cached panel's default grid (`features/ma.py::LOOKBACKS = (20,
50, 200)`), so this is new, slice-specific plumbing, not a re-read of the
cache. It still reuses `features/ma.py::compute_ma` (already accepts an
arbitrary lookback), `market_common.indicators.atr` (same ATR(14)
convention as `features/panel.py`'s own `atr_14`), and
`features/panel.py::apply_lag` (never a hand-rolled shift -- CLAUDE.md
invariant #2), so the new lookbacks are on the same lag footing as every
other feature in this study.

`dist_atr` was added for M5 (PREREGISTRATION.md, 2026-09-17): the
touch/test/bounce event definition needs an ATR-normalised distance at
every focal + neighbor lookback, not just `dist_pct` (which §7.5's own
spread statistic used).
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import indicators
from src.foundation.market_common.data import load_bars, validate_bars
from src.foundation.market_common.models import Timeframe
from src.signals.moving_averages.features import context, distance, ma
from src.signals.moving_averages.features.panel import ATR_PERIOD, apply_lag

# PREREGISTRATION.md §7.5: focal lookback + its statistically
# near-identical, unwatched neighbors, per group.
GROUPS = {
    "sma200": {"family": "sma", "focal": 200, "neighbors": (187, 193, 207, 213)},
    "sma50": {"family": "sma", "focal": 50, "neighbors": (47, 53)},
    "ema21": {"family": "ema", "focal": 21, "neighbors": (19, 23)},
}

_NON_FEATURE_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume")


def dist_pct_column(family: str, lookback: int) -> str:
    return f"dist_pct_{ma.ma_column_name(family, lookback)}"


def dist_atr_column(family: str, lookback: int) -> str:
    return f"dist_atr_{ma.ma_column_name(family, lookback)}"


def _lookbacks_by_family() -> dict[str, tuple[int, ...]]:
    out: dict[str, set[int]] = {}
    for spec in GROUPS.values():
        family = spec["family"]
        out.setdefault(family, set()).add(spec["focal"])
        out[family].update(spec["neighbors"])
    return {family: tuple(sorted(lookbacks)) for family, lookbacks in out.items()}


def _build_ticker_features(clean: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Raw (un-lagged) `dist_pct` for every group's focal+neighbor lookback,
    for one already-validated ticker frame -- same "known as of that day's
    close" convention as `features/panel.py::_build_ticker_features`; the
    lag that makes it usable starting the next day is applied once,
    centrally, in `build_placebo_panel`, not here.
    """
    frame = clean.copy()
    frame["ticker"] = ticker
    frame["atr_14"] = indicators.atr(frame, ATR_PERIOD)

    for family, lookbacks in _lookbacks_by_family().items():
        for lookback in lookbacks:
            ma_series = ma.compute_ma(frame["close"], family, lookback)
            frame[dist_pct_column(family, lookback)] = distance.dist_pct(frame["close"], ma_series)
            frame[dist_atr_column(family, lookback)] = distance.dist_atr(
                frame["close"], ma_series, frame["atr_14"]
            )

    # Same C2 match inputs M1/M4/M11 already use -- reused unchanged, not
    # recomputed with different parameters.
    frame["mom_12_1"] = context.mom_12_1(frame["close"])
    frame["realized_vol_63"] = context.realized_vol_63(frame["close"])

    return frame.reset_index().rename(columns={"timestamp": "date"})


def build_placebo_panel(
    conn: sqlite3.Connection,
    tickers: list[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """One row per (ticker, date): `dist_pct_{sma,ema}_{lookback}` for
    every focal + neighbor lookback in `GROUPS`, plus `mom_12_1`/
    `realized_vol_63`/`sector` (the same C2 match inputs M1/M4/M11 use) --
    already one-bar-lagged via `features/panel.py::apply_lag`, so it's
    ready to pair with a forward return with no extra lag bookkeeping.

    `end` is the holdout boundary (CLAUDE.md's holdout-lock invariant) --
    passed through to `load_bars` as `as_of`, same as
    `features/panel.py::build_panel`. Callers building anything for the
    development window MUST pass `end` explicitly.
    """
    frames = []
    for ticker in tickers:
        bars = load_bars(conn, ticker, Timeframe.DAILY, as_of=end, start=start)
        if bars.empty:
            continue
        clean, _ = validate_bars(bars, ticker)
        if clean.empty:
            continue
        frames.append(_build_ticker_features(clean, ticker))

    if not frames:
        return pd.DataFrame()

    panel = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    feature_cols = [c for c in panel.columns if c not in _NON_FEATURE_COLUMNS]
    panel = apply_lag(panel, columns=feature_cols)
    panel[feature_cols] = panel[feature_cols].astype("float32")

    sectors = db.read_ticker_sector(conn)
    panel = panel.merge(sectors[["ticker", "sector"]], on="ticker", how="left")
    panel["sector"] = panel["sector"].astype("string")

    return panel
