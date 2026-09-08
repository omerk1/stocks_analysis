"""M4 — Distance from MA (DESIGN.md §8; PREREGISTRATION.md, 2026-09-08).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement -- this module implements exactly that slice: decile
buckets of `dist_pct`/`dist_atr`/`dist_z` at SMA{20,50,200}, C0/C1/C2
deltas on `fwd_ret_21`, with effective-N reporting and DESIGN §6.9's
minimum-sample-threshold flagging. Nothing in this module decides
pass/fail on its own -- `decile_table`'s output is what a caller (the
driving notebook, or a human) reads against the pre-registered kill
criterion.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c0_delta, c1_delta, c2_delta, cross_sectional_bucket

# DESIGN §6.9
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

DISTANCE_FEATURES = ("dist_pct", "dist_atr", "dist_z")
LOOKBACKS = (20, 50, 200)
HORIZON = 21
N_DECILES = 10

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21` and the C2 match buckets (momentum/vol terciles --
    see PREREGISTRATION.md's "C2 note" on tercile vs. decile) to `panel`.
    Returns a new frame; `panel` itself is not mutated.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    return working


def decile_table(panel: pd.DataFrame, feature_col: str) -> pd.DataFrame:
    """One row per decile of `feature_col` (an already-lagged distance
    column, e.g. `dist_pct_sma_50`): C0/C1/C2 deltas on `fwd_ret_21`, plus
    effective N (row count + distinct dates + distinct tickers,
    CLAUDE.md invariant #6). A decile below DESIGN §6.9's minimum sample
    threshold is flagged via `below_threshold`, not dropped -- the caller
    decides how to render a flagged row (e.g. greyed out), it isn't
    silently excluded here.

    `panel` must already carry `fwd_ret_21` and the C2 match columns (see
    `prepare`).
    """
    working = panel.dropna(subset=[feature_col, "fwd_ret_21"]).copy()
    working["decile"] = cross_sectional_bucket(working, feature_col, n_buckets=N_DECILES)
    working = working.dropna(subset=["decile"])
    working["decile"] = working["decile"].astype(int)

    rows = []
    for decile in sorted(working["decile"].unique()):
        subset = working.assign(is_event=working["decile"] == decile)
        event_rows = subset[subset["is_event"]]
        n_events = len(event_rows)
        n_dates = event_rows["date"].nunique()
        n_tickers = event_rows["ticker"].nunique()

        rows.append(
            {
                "decile": decile,
                "n_events": n_events,
                "n_dates": n_dates,
                "n_tickers": n_tickers,
                "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
                "c0": c0_delta(subset, "is_event", "fwd_ret_21"),
                "c1": c1_delta(subset, "is_event", "fwd_ret_21"),
                "c2": c2_delta(subset, "is_event", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)),
            }
        )
    return pd.DataFrame(rows).sort_values("decile").reset_index(drop=True)


def run_grid(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """`decile_table` for every (normalisation, lookback) combination in
    this slice's pre-registered grid (`DISTANCE_FEATURES` x `LOOKBACKS`,
    9 combinations) -- keyed by e.g. `"dist_pct_sma_50"`.
    """
    prepared = prepare(panel)
    results = {}
    for feature in DISTANCE_FEATURES:
        for lookback in LOOKBACKS:
            col = f"{feature}_sma_{lookback}"
            results[col] = decile_table(prepared, col)
    return results
