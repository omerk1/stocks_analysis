"""M6.1 -- Does slope add anything over momentum? (DESIGN.md SS6.0/SS6.1;
PREREGISTRATION.md, 2026-09-21).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement -- this module implements DESIGN's own named horse race:
`slope_log_21(SMA200)` vs raw 200-day return vs `mom_12_1` vs the
block-mean-difference form (DESIGN SS6.0's own k-day identity,
operationalized in log space for cross-ticker comparability, CLAUDE.md
invariant #7), IC and IC-decay across horizons, turnover, and the
decisive test: per-date cross-sectional partial correlation of slope
(residualized against `mom_12_1`) with forward return -- "incremental
IC," DESIGN's own named quantity, run at all four cached SMA lookbacks
per the kill criterion's own "across all lookbacks" wording.

New machinery: two small local features (`raw_return_k`,
`block_mean_diff_log_k`, computed here, not written to the shared panel
cache -- so a sibling M6.x module built in parallel never touches
`features/panel.py`) and one small per-date OLS-residualization helper
(`_daily_incremental_ic`). Everything else reuses
`modules/cross_sectional.py::daily_rank_ic` and
`stats/inference.py::block_bootstrap_series` exactly as M11 built them,
and `stats/costs.py::signals_per_year` for the turnover comparison.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.cross_sectional import daily_rank_ic
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import signals_per_year
from src.signals.moving_averages.stats.inference import block_bootstrap_series

# DESIGN SS6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZONS = (21, 63, 126)
SLOPE_K = 21
LOOKBACKS = (20, 50, 150, 200)
PRIMARY_LOOKBACK = 200
INCREMENTAL_IC_FLOOR = 0.005
N_DECILES = 10


def raw_return_k(close: pd.Series, k: int) -> pd.Series:
    """log(C_t / C_{t-k}) -- plain k-day momentum, no skip, no smoothing.
    Distinct from `mom_12_1` (which skips the most recent month). Caller
    must pass a single ticker's close series, already sorted by date --
    same convention as `features/slope.py::slope_log_k`.
    """
    return np.log(close) - np.log(close.shift(k))


def block_mean_diff_log(close: pd.Series, k: int = SLOPE_K, n: int = PRIMARY_LOOKBACK) -> pd.Series:
    """DESIGN SS6.0's k-day slope identity, in log space:
    SMAn(t) - SMAn(t-k) = (k/n) * [mean(C[t-k+1..t]) - mean(C[t-n-k+1..t-n])].
    Implemented as log(recent k-day mean) - log(prior k-day mean, ending n
    days back) rather than the raw linear difference, for the same
    cross-ticker comparability reason `slope_log_k` itself is logged
    (CLAUDE.md invariant #7) -- "momentum with smoothed endpoints,"
    DESIGN's own description of what the identity says slope can add over
    raw momentum. Caller must pass a single ticker's close series, already
    sorted by date.
    """
    recent_mean = close.rolling(k).mean()
    prior_mean = recent_mean.shift(n)
    return np.log(recent_mean) - np.log(prior_mean)


def prepare(panel: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Adds `fwd_ret_{h}` for every horizon, and, for every lookback in
    `LOOKBACKS`, `raw_return_{k}`/`block_mean_diff_log_{k}` (computed from
    the panel's own unlagged `close`, then passed through the same
    central one-bar lag every cached feature already went through --
    CLAUDE.md invariant #2). `slope_log_21_sma_{k}` and `mom_12_1` are
    already lagged (cached panel columns) -- not touched here. Returns a
    new frame; `panel` itself is not mutated.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True).copy()
    for h in horizons:
        working[f"fwd_ret_{h}"] = forward_return(working, horizon=h)

    grouped_close = working.groupby("ticker", sort=False)["close"]
    new_cols = []
    for k in LOOKBACKS:
        raw_col, bmd_col = f"raw_return_{k}", f"block_mean_diff_log_{k}"
        working[raw_col] = grouped_close.transform(lambda s, k=k: raw_return_k(s, k))
        working[bmd_col] = grouped_close.transform(lambda s, k=k: block_mean_diff_log(s, n=k))
        new_cols += [raw_col, bmd_col]

    working = apply_lag(working, new_cols)
    return working


def _daily_incremental_ic(
    panel: pd.DataFrame, feature_col: str, control_col: str, return_col: str, date_col: str = "date",
) -> pd.Series:
    """Per-date cross-sectional partial correlation: residualize
    `feature_col` against `control_col` via OLS (one date at a time -- no
    look-ahead, each date's regression uses only that date's own
    cross-section), then Spearman rank-IC of the residual against
    `return_col`. This is DESIGN SS6.1's "incremental IC" made concrete,
    reusing `daily_rank_ic`'s own per-date convention rather than a
    pooled full-sample regression (CLAUDE.md invariant #3 -- no
    full-sample statistics). Returns a Series indexed by date, NaN on
    dates with fewer than 3 valid rows.
    """
    def _one_date(group: pd.DataFrame) -> float:
        sub = group[[feature_col, control_col, return_col]].dropna()
        if len(sub) < 3:
            return float("nan")
        x = sub[control_col].to_numpy()
        y = sub[feature_col].to_numpy()
        design = np.column_stack([np.ones_like(x), x])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        resid = pd.Series(y - design @ coef, index=sub.index)
        return resid.corr(sub[return_col], method="spearman")

    return panel.groupby(date_col, sort=False).apply(_one_date, include_groups=False)


def horse_race_table(panel: pd.DataFrame, lookback: int = PRIMARY_LOOKBACK) -> pd.DataFrame:
    """Descriptive horse race (DESIGN SS6.1's own method paragraph, run at
    the primary lookback only): per-date Spearman rank-IC of each of the
    four candidate features against `fwd_ret_{h}`, block-bootstrapped,
    for every horizon in `HORIZONS`. Purely descriptive -- not the
    decisive/kill-criterion test (see `incremental_ic_table`).
    """
    features = {
        "slope_log_21": f"slope_log_21_sma_{lookback}",
        "raw_return_k": f"raw_return_{lookback}",
        "mom_12_1": "mom_12_1",
        "block_mean_diff_log": f"block_mean_diff_log_{lookback}",
    }
    rows = []
    for h in HORIZONS:
        return_col = f"fwd_ret_{h}"
        for label, col in features.items():
            ic_series = daily_rank_ic(panel, col, return_col)
            boot = block_bootstrap_series(ic_series, block_length=max(42, 2 * h), n_boot=500, ci=0.90, seed=0)
            rows.append({
                "lookback": lookback, "horizon": h, "feature": label,
                "ic": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
                "n_dates": boot["n_dates"],
            })
    return pd.DataFrame(rows)


def turnover_table(panel: pd.DataFrame, lookback: int = PRIMARY_LOOKBACK) -> pd.DataFrame:
    """Top-decile membership turnover (DESIGN SS6.1's own named
    comparison) for `slope_log_21_sma_{lookback}` vs `mom_12_1`, reusing
    `stats/costs.py::signals_per_year` on a boolean top-decile flag --
    the same primitive M4/M11's own cost annotations use, applied here as
    a pure descriptive comparison (no cost hurdle attached -- this is a
    redundancy/diagnostic question, not a tradeable claim; see
    PREREGISTRATION.md's cost-annotation note).
    """
    working = panel.copy()
    rows = []
    for label, col in (("slope_log_21", f"slope_log_21_sma_{lookback}"), ("mom_12_1", "mom_12_1")):
        working["_decile"] = cross_sectional_bucket(working, col, n_buckets=N_DECILES)
        working["_top_decile"] = (working["_decile"] == N_DECILES - 1).astype("boolean").mask(working["_decile"].isna())
        rows.append({
            "lookback": lookback, "feature": label,
            "signals_per_ticker_year": signals_per_year(working, "_top_decile"),
        })
    return pd.DataFrame(rows)


def incremental_ic_table(panel: pd.DataFrame, lookbacks: tuple[int, ...] = LOOKBACKS) -> pd.DataFrame:
    """The decisive test (DESIGN SS6.1): per-date partial correlation of
    `slope_log_21_sma_{k}` (residualized against `mom_12_1`) with
    `fwd_ret_21`, for every lookback in `lookbacks` -- the kill criterion
    is evaluated "across all lookbacks" (DESIGN's own wording), so this
    is the module's actual N_tests contribution, not `horse_race_table`
    above (which is descriptive only).
    """
    rows = []
    for k in lookbacks:
        feature_col = f"slope_log_21_sma_{k}"
        ic_series = _daily_incremental_ic(panel, feature_col, "mom_12_1", "fwd_ret_21")
        boot = block_bootstrap_series(ic_series, block_length=42, n_boot=500, ci=0.90, seed=0)
        n_events = panel.dropna(subset=[feature_col, "mom_12_1", "fwd_ret_21"]).shape[0]
        n_tickers = panel.dropna(subset=[feature_col, "mom_12_1", "fwd_ret_21"])["ticker"].nunique()
        edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
        rows.append({
            "lookback": k,
            "incremental_ic": boot["point_estimate"],
            "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
            "n_dates": boot["n_dates"], "n_events": n_events, "n_tickers": n_tickers,
            "edge": edge,
            "below_threshold": (
                n_events < MIN_EVENTS or boot["n_dates"] < MIN_DATES or n_tickers < MIN_TICKERS
                or pd.isna(edge)
            ),
        })
    return pd.DataFrame(rows)


def kill_verdict(incremental: pd.DataFrame, floor: float = INCREMENTAL_IC_FLOOR) -> bool:
    """DESIGN's own kill rule: killed iff EVERY lookback's incremental-IC
    edge (max(|ci_low|, |ci_high|)) is below `floor` -- "across all
    lookbacks," not just the primary one.
    """
    return bool((incremental["edge"] < floor).all())
