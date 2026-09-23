"""M13 -- Context conditioning (DESIGN.md, line 974; PREREGISTRATION.md,
2026-09-21).

Track B, first slice. DESIGN's own text for this module is short --
"Earnings proximity, index membership changes, sector momentum, market
breadth (pct_above_200d), VIX percentile. Mostly interaction terms on top
of M1-M6 rather than standalone analysis." -- so this slice picks a
concrete, testable interaction rather than attempting all four facets at
once (same "first slice, not full spec" precedent M1/M4/M5/M6.2 all used):
does M1's `above_sma_200` conditional effect on `fwd_ret_21` hold equally
across a VIX regime (top vs bottom trailing tercile) and a market-breadth
regime (top vs bottom trailing tercile of `pct_above_sma_200`)?

Earnings proximity is out of scope entirely -- this repo's DB has no
earnings-date table (checked: bars_1d/1h/1mo/1w, fetch_jobs,
index_membership, macro_series, shares_outstanding, splits,
ticker_metadata, ticker_sector, tickers -- nothing earnings-related).
Index-membership changes and sector momentum are explicitly deferred, not
attempted this slice, same "explicitly deferred" precedent M6.2 used for
golden-cross x slope.

New machinery: none beyond one small helper (`_rolling_tercile`, a
trailing/rolling percentile-rank bucket -- CLAUDE.md invariant #3 forbids
a full-sample quantile here, so this is *not* built as a plain `pd.qcut`
over the whole 2010-2021 window). Everything else reuses this study's
existing primitives: `block_bootstrap_delta` (restrict-then-delta,
sub-question 1's exact pattern from `modules/slope_conditioner.py`),
`features.panel.apply_lag` (the one central lag function, not a
hand-rolled shift), `db.read_macro_series` (VIXCLS).
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
LOOKBACK = 200  # above_sma_200 -- the lookback DESIGN's own regime-conditioning language (M9) centers on
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Trailing window for the regime bucket -- same 252-trading-day convention
# this study already uses for rolling self-normalisation (dist_z).
REGIME_WINDOW = 252

# M1's own 0.10% floor -- this cell's statistic (above/below delta on
# fwd_ret_21, restricted to a regime bucket) is the exact same shape as
# M1's primary cells, just row-restricted first, so it inherits M1's own
# kill threshold rather than inventing a new one.
KILL_THRESHOLD = 0.001

HOLDOUT_BOUNDARY = "2021-12-31"


def _rolling_tercile(series: pd.Series, window: int = REGIME_WINDOW) -> pd.Series:
    """Trailing (not full-sample -- CLAUDE.md invariant #3) tercile bucket
    (0 = bottom third ... 2 = top third) of a date-indexed series, based on
    each date's percentile rank within its own trailing `window`-length
    history (inclusive of the date itself). NaN until `window`
    observations have accumulated -- an early-history warmup, same shape
    as every other rolling feature in this study.
    """
    pct_rank = series.rolling(window, min_periods=window).apply(
        lambda x: (x <= x.iloc[-1]).mean(), raw=False
    )
    bucket = pd.cut(pct_rank, bins=[-0.01, 1 / 3, 2 / 3, 1.01], labels=[0, 1, 2])
    return bucket.astype("Int64")


def prepare(panel: pd.DataFrame, conn: sqlite3.Connection) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, and the two regime facets
    (`vix_tercile`, `breadth_tercile`) to `panel`. Returns a new frame;
    `panel` itself is not mutated.

    `breadth_tercile` is derived from `above_sma_200`, which is already
    lagged in the cached panel -- no further shift needed for the raw
    per-date aggregate. `vix_tercile` is derived from a fresh DB read of
    `VIXCLS` (FRED), which is NOT part of the cached, already-lagged panel
    -- it is holdout-filtered (<= 2021-12-31) and then passed through
    `features.panel.apply_lag` exactly like every other feature in this
    study (CLAUDE.md invariant #2): a VIX close on day t is not tradable
    information until day t+1. Since every ticker has exactly one row per
    date, shifting this date-level column forward one row *within each
    ticker* (apply_lag's own grouping) is exactly a one-trading-day lag of
    the underlying date-level series.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    breadth_by_date = (
        working.groupby("date")["above_sma_200"].apply(lambda s: s.astype(float).mean())
    )
    breadth_bucket = _rolling_tercile(breadth_by_date).rename("breadth_tercile")

    vix = db.read_macro_series(conn, "VIXCLS")
    vix["date"] = pd.to_datetime(vix["date"])
    vix = vix[vix["date"] <= HOLDOUT_BOUNDARY].set_index("date")["value"].sort_index()
    vix_bucket_raw = _rolling_tercile(vix).rename("vix_tercile_raw")

    regime = pd.concat([breadth_bucket, vix_bucket_raw], axis=1).reset_index()
    regime.columns = ["date", "breadth_tercile", "vix_tercile_raw"]
    working = working.merge(regime, on="date", how="left")

    working = apply_lag(working, ["vix_tercile_raw"])
    working = working.rename(columns={"vix_tercile_raw": "vix_tercile"})
    return working


def _cell(
    restricted: pd.DataFrame,
    label: dict,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """One regime-bucket cell: C1/C2 delta of `fwd_ret_21` between
    `above_sma_200`'s two states, on an already-restricted row population
    (a single regime-tercile bucket). Same shape as
    `modules/slope_conditioner.py::_delta_cell`, specialized to this
    module's one group_col/value_col pair rather than generalized to an
    arbitrary one -- this module has exactly one conditioning question,
    not three sub-questions like M6.2.
    """
    group_col = "above_sma_200"
    value_col = "fwd_ret_21"
    subset = restricted.dropna(subset=[group_col, value_col, *match_cols])
    event_rows = subset[subset[group_col].astype(bool)]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(
            subset, group_col, value_col, match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = (
        None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])
    )

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(subset, group_col, value_col) if len(subset) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "kill_threshold": KILL_THRESHOLD,
        "edge": edge,
        "killed": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
    }


def regime_table(panel: pd.DataFrame) -> pd.DataFrame:
    """The 4 primary cells: {vix, breadth} regime x {top, bottom} trailing
    tercile. `panel` must already be `prepare()`'d. Middle terciles are
    dropped (not tested) -- a clean two-sided top-vs-bottom comparison,
    same "drop the middle tercile" convention the 2026-09-18 distance x
    slope generalization script used to match M6.2's own binary
    construction.
    """
    rows = []
    for regime_col, regime_name in (("vix_tercile", "vix"), ("breadth_tercile", "breadth")):
        for bucket, bucket_name in ((2, "top"), (0, "bottom")):
            restricted = panel[panel[regime_col] == bucket]
            rows.append(_cell(restricted, {"regime": regime_name, "bucket": bucket_name}))
    return pd.DataFrame(rows)
