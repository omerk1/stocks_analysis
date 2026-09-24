"""M9 -- Regime-conditional lookback (DESIGN.md lines ~935-944;
PREREGISTRATION.md, 2026-09-24). Track B.

DESIGN's own three-stage design (descriptive -> predictive -> adaptive),
staging enforced by keeping each stage's own function separate rather than
one monolithic run -- see PREREGISTRATION.md for the full pre-registered
regime definition (ER/ADX fixed thresholds), lookback grid, and fit/test
split, committed before any real-panel number in this module was computed.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import distance, ma, regime
from src.signals.moving_averages.features.kernels import kama
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import cost_hurdle, signals_per_year
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
    block_bootstrap_group_diff,
)

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

LOOKBACKS = (10, 20, 50)
HORIZON = 21
ER_PERIOD = 10
ADX_PERIOD = 14
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

FIT_END = "2016-12-31"
TEST_START = "2017-01-01"

# PREREGISTRATION.md's own literal kill-criterion floor -- same 0.10%
# convention every other module in this study uses.
GAP_FLOOR = 0.001
KILL_THRESHOLD = 0.001


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds local `ema_10`/`above_ema_10` (same raw-then-lag convention
    `features/panel.py::build_panel` itself uses for every other MA/above
    pair -- computed on the same, un-lagged day, then lagged together with
    the regime features below), raw `er`/`adx` + their fixed-threshold
    regime buckets (also lagged before bucketing, since the regime label
    conditions a forward outcome the same way any other feature does --
    CLAUDE.md invariant #2), `fwd_ret_21`, and the C2 match buckets.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True).copy()

    working["ema_10"] = working.groupby("ticker")["close"].transform(
        lambda s: ma.compute_ma(s, "ema", 10)
    )
    working["above_ema_10"] = distance.above(working["close"], working["ema_10"])

    working["er_raw"] = working.groupby("ticker")["close"].transform(
        lambda s: regime.efficiency_ratio(s, ER_PERIOD)
    )

    # Manual per-group loop (not groupby.apply -- a multi-column input
    # combined with a single-ticker group hits a pandas edge case where
    # apply's result gets recombined as a wide frame instead of a flat,
    # index-aligned Series; the same reason M12's `volume_liquidity.py::
    # _is_reclaim` uses this pattern rather than `.apply`).
    adx_raw = pd.Series(index=working.index, dtype="float64")
    for _, g in working.groupby("ticker", sort=False):
        adx_raw.loc[g.index] = regime.average_directional_index(
            g["high"], g["low"], g["close"], ADX_PERIOD
        ).to_numpy()
    working["adx_raw"] = adx_raw
    working["kama"] = working.groupby("ticker")["close"].transform(lambda s: kama(s))
    working["above_kama"] = distance.above(working["close"], working["kama"])

    working = apply_lag(working, ["ema_10", "above_ema_10", "er_raw", "adx_raw", "kama", "above_kama"])

    working["er_regime"] = regime.er_regime(working["er_raw"])
    working["adx_regime"] = regime.adx_regime(working["adx_raw"])

    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    return working


def _above_col(lookback: int) -> str:
    return "above_ema_10" if lookback == 10 else f"above_{ma.ma_column_name('ema', lookback)}"


def _c2_cell(
    working: pd.DataFrame, group_col: str, match_cols: tuple[str, ...] = C2_MATCH_COLS,
    value_col: str = "fwd_ret_21",
) -> dict:
    """One C2 block-bootstrap delta cell, `working` already restricted to
    whatever row population makes sense (a regime bucket, a date range, or
    both) -- reused unchanged across all three stages.
    """
    subset = working.dropna(subset=[group_col, value_col, *match_cols])
    event_rows = subset[subset[group_col].astype("boolean").fillna(False)]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(subset, group_col, value_col, match_cols=list(match_cols))
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "point_estimate": float("nan"), "n_dates": 0}

    return {
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"], "c2_ci_low": boot["ci_low"], "c2_ci_high": boot["ci_high"],
    }


def descriptive_surface(fit_working: pd.DataFrame, regime_col: str = "er_regime") -> pd.DataFrame:
    """Stage 1: for each regime bucket (of `regime_col`) x lookback in
    `LOOKBACKS`, the C2 delta of `above_ema_{lb}` on `fwd_ret_21`,
    restricted to that regime bucket, on the FIT period only. `fit_working`
    must already be restricted to the fit-period date range by the caller.
    """
    rows = []
    for bucket in fit_working[regime_col].cat.categories:
        restricted = fit_working[fit_working[regime_col] == bucket]
        for lb in LOOKBACKS:
            row = _c2_cell(restricted, _above_col(lb))
            row.update({"regime_dimension": regime_col, "regime_bucket": bucket, "lookback": lb})
            rows.append(row)
    return pd.DataFrame(rows)


def best_lookback_per_regime(descriptive: pd.DataFrame) -> dict:
    """Stage 2 (part 1): for each regime bucket, the lookback with the
    largest-MAGNITUDE, CI-excluding-zero C2 delta -- **not** filtered by
    sign. Real-panel run (2026-09-24) found every `above_ema_k` cell in
    this study's entire construction is negatively signed (being above a
    short EMA predicts *lower* subsequent returns, consistent with every
    other above/below-state cell this study has produced elsewhere,
    e.g. M1's own `above_sma_*` cells) -- an earlier version of this
    function filtered for `c2 > 0` ("correctly signed" under a naive
    "above predicts continuation" assumption) and consequently selected
    nothing in any regime, since nothing in this data is positively
    signed. Magnitude, not an assumed sign, is what "best" means here;
    `evaluate_kill_criterion` below handles the sign-aware comparison
    against the fixed benchmark. A bucket with no eligible cell (CI spans
    zero at every lookback) is mapped to `None` (falls back to whatever
    the caller treats as "no regime-specific edge").
    """
    mapping: dict = {}
    for bucket, group in descriptive.groupby("regime_bucket", observed=True):
        ci_excludes_zero = (group["c2_ci_low"] > 0) | (group["c2_ci_high"] < 0)
        eligible = group[(~group["below_threshold"]) & ci_excludes_zero]
        if eligible.empty:
            mapping[bucket] = None
            continue
        best = eligible.loc[eligible["c2"].abs().idxmax()]
        mapping[bucket] = int(best["lookback"])
    return mapping


def regime_persistence(working: pd.DataFrame, regime_col: str = "er_regime", horizon: int = HORIZON) -> pd.DataFrame:
    """Stage 2 (part 2): per ticker, the fraction of rows where
    `regime_col`'s bucket at date t still holds at t+`horizon` trading
    days, vs. the base rate a memoryless (i.i.d.-regime) process would
    produce (each bucket's own unconditional frequency, squared-sum
    across buckets -- the chance two independent draws from the same
    marginal distribution match).
    """
    working = working.sort_values(["ticker", "date"])
    future_regime = working.groupby("ticker")[regime_col].shift(-horizon)
    valid = working[regime_col].notna() & future_regime.notna()
    persists = (working[regime_col] == future_regime) & valid

    empirical_rate = persists[valid].mean()
    base_rates = working.loc[valid, regime_col].value_counts(normalize=True)
    memoryless_rate = float((base_rates**2).sum())

    return pd.DataFrame([{
        "regime_dimension": regime_col, "n_valid": int(valid.sum()),
        "empirical_persistence_rate": empirical_rate, "memoryless_persistence_rate": memoryless_rate,
        "persistence_excess": empirical_rate - memoryless_rate,
    }])


def adaptive_signal(test_working: pd.DataFrame, mapping: dict, fallback_lookback: int) -> pd.Series:
    """Stage 3: on each test-period row, look up its *current* `er_regime`
    bucket, use `mapping` (learned on the fit period only) to pick that
    bucket's best lookback, and read that lookback's own `above_ema_{lb}`
    state for the row. A bucket mapped to `None` (no eligible fit-period
    cell) falls back to `fallback_lookback` -- the same fixed benchmark
    lookback used for the fixed-strategy comparison, so "no regime edge
    found" degrades gracefully to "just use the fixed lookback" rather
    than silently producing an undefined signal.
    """
    chosen_lookback = test_working["er_regime"].map(
        lambda bucket: mapping.get(bucket) or fallback_lookback
    )
    result = pd.Series(pd.NA, index=test_working.index, dtype="boolean")
    for lb in LOOKBACKS:
        mask = chosen_lookback == lb
        result.loc[mask] = test_working.loc[mask, _above_col(lb)]
    return result


def evaluate_adaptive_vs_fixed(test_working: pd.DataFrame, mapping: dict, fixed_lookback: int) -> dict:
    """Stage 3's own decisive test: does the adaptive (regime-switching)
    signal's C2 delta beat the fixed-lookback signal's, net of the
    incremental switching cost, on the TEST period only?
    `block_bootstrap_group_diff` gives a proper CI on the *difference*
    (not two separately-CI'd deltas eyeballed against each other) --
    PREREGISTRATION.md's own explicit requirement.
    """
    working = test_working.copy()
    working["adaptive_above"] = adaptive_signal(working, mapping, fixed_lookback)
    working["fixed_above"] = working[_above_col(fixed_lookback)]

    subset = working.dropna(subset=["adaptive_above", "fixed_above", "fwd_ret_21", *C2_MATCH_COLS])
    try:
        diff = block_bootstrap_group_diff(
            subset, "adaptive_above", "fixed_above", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)
        )
    except InsufficientBlocksError:
        diff = {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_dates": 0}

    adaptive_spy = signals_per_year(subset, "adaptive_above")
    fixed_spy = signals_per_year(subset, "fixed_above")
    incremental_spy = max(adaptive_spy - fixed_spy, 0.0)
    incremental_hurdle = cost_hurdle(incremental_spy, round_trip_cost=0.001)

    # Fixed lookback's own C2 delta on the test period -- needed to know
    # which *direction* counts as "adaptive is stronger" (this study's
    # `above_ema_k` cells are consistently negatively signed; "better"
    # means further from zero in whatever direction the fixed benchmark
    # itself already points, not naively "more positive").
    fixed_cell = _c2_cell(subset, "fixed_above")

    adaptive_kama_diff = None
    try:
        kama_subset = working.dropna(subset=["adaptive_above", "above_kama", "fwd_ret_21", *C2_MATCH_COLS])
        adaptive_kama_diff = block_bootstrap_group_diff(
            kama_subset, "adaptive_above", "above_kama", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)
        )
    except InsufficientBlocksError:
        pass

    return {
        "diff_point": diff["point_estimate"], "diff_ci_low": diff["ci_low"], "diff_ci_high": diff["ci_high"],
        "n_dates": diff["n_dates"], "adaptive_signals_per_year": adaptive_spy, "fixed_signals_per_year": fixed_spy,
        "incremental_signals_per_year": incremental_spy, "incremental_cost_hurdle_annual": incremental_hurdle,
        "vs_kama_diff": adaptive_kama_diff, "fixed_point": fixed_cell["c2"],
    }


def evaluate_kill_criterion(result: dict) -> dict:
    """PREREGISTRATION.md's own literal kill criterion: the adaptive-vs-
    fixed CI must exclude zero *in the direction that represents a
    stronger effect than the fixed benchmark* (sign-aware -- this study's
    `above_ema_k` construction is consistently negatively signed
    throughout, so "adaptive beats fixed" means further from zero in the
    fixed benchmark's own direction, not naively "more positive"; see
    `best_lookback_per_regime`'s own docstring for the same real-data
    finding that motivated this), and the near edge of that improvement
    must clear the incremental switching-cost hurdle. Everything else --
    CI spans zero (in either the naive or the sign-rotated sense), or
    clears CI but not cost -- is the honest null DESIGN's own ~70% prior
    expects.
    """
    ci_low, ci_high, fixed_point = result["diff_ci_low"], result["diff_ci_high"], result["fixed_point"]
    if pd.isna(ci_low) or pd.isna(ci_high) or pd.isna(fixed_point):
        return {"module_killed": None, "reason": "insufficient_blocks"}
    fixed_sign = 1.0 if fixed_point >= 0 else -1.0
    # Rotate the diff CI into "improvement" space: positive means adaptive
    # moved further from zero in the fixed benchmark's own direction.
    rotated_low = min(ci_low * fixed_sign, ci_high * fixed_sign)
    rotated_high = max(ci_low * fixed_sign, ci_high * fixed_sign)
    improvement_excludes_zero = rotated_low > 0
    if not improvement_excludes_zero:
        return {"module_killed": True, "reason": "ci_spans_zero_or_wrong_direction"}
    annualized_near_edge = rotated_low * 12
    clears_cost = annualized_near_edge >= result["incremental_cost_hurdle_annual"]
    return {
        "module_killed": not clears_cost,
        "reason": "clears_ci_and_cost" if clears_cost else "clears_ci_not_cost",
    }
