"""M6.6 -- Slope agreement across the ribbon (DESIGN.md, "M6.6 -- Slope
agreement across the ribbon"; PREREGISTRATION.md, 2026-09-23).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion
/ scope statement, including the one logged deviation from DESIGN's
literal text (also summarized here since it shapes this module's design):
DESIGN's own lookback set is {10, 20, 50, 100, 200} -- not this study's
shared cached-panel set {20, 50, 150, 200}. `sma_10`/`sma_100` and their
`slope_log_21` are built here, module-local (not added to the shared
panel, so parallel Batch-2 modules don't collide on `features/panel.py`);
`sma_20`/`sma_50`/`sma_200`'s already-cached `slope_log_21_sma_k` columns
are reused unchanged.
"""

from __future__ import annotations

import itertools

import pandas as pd

from src.signals.moving_averages.feature_sweep import per_date_median_corr
from src.signals.moving_averages.features import slope as slope_features
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.labels.path_metrics import forward_max_drawdown
from src.signals.moving_averages.stats.controls import c0_delta, c1_delta, c2_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.costs import annualize, cost_hurdle, signals_per_year
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

ROUND_TRIP_COST = 0.001  # 10bps/rt, this study's U1 convention throughout

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
SLOPE_K = 21
RIBBON_LOOKBACKS = (10, 20, 50, 100, 200)
NEW_LOOKBACKS = (10, 100)  # not in the shared cached panel -- built here
CACHED_LOOKBACKS = (20, 50, 200)  # already have slope_log_21_sma_k cached
N_RUNGS = len(RIBBON_LOOKBACKS)
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Robustness-check-only match set (same construction as
# `modules/slope_magnitude.py`'s/`modules/slope_conditioner.py`'s own
# `C2_MATCH_COLS_WITH_REVERSAL`): adds a prior-21-day-return tercile so a
# confirmed cell's C2 delta can be re-evaluated with short-term reversal
# explicitly matched out. Not this module's pre-registered default --
# `extreme_state_test`'s own default `match_cols` stays `C2_MATCH_COLS`.
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# Same 0.10% floor every return-valued cell in this study uses
# (M1/M2/M6.2/M6.3).
KILL_THRESHOLD = 0.001

# The two extremes of the ordinal ribbon-agreement state: all five
# lookbacks falling (0) vs all five rising (5) -- the decisive test DESIGN
# actually motivates ("does agreement carry information beyond a single
# MA's own slope"), operationalized the same restrict-then-delta way
# M6.3's middle-vs-tails test is.
LOW_STATE = 0
HIGH_STATE = N_RUNGS


def slope_column(lookback: int) -> str:
    return f"slope_log_{SLOPE_K}_sma_{lookback}"


def _build_new_sma_slopes(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `slope_log_21_sma_{10,100}`, module-local: a rolling SMA off
    the panel's own raw (unlagged) `close`, then `slope_log_k` on that SMA,
    then lagged via the shared `apply_lag` (CLAUDE.md invariant #2) -- this
    is a genuinely new raw-derived feature (unlike `sma_20/50/200`, which
    arrive from the cached panel already lagged), so it must go through the
    one central lag function itself before being paired with a forward
    label. Only the final slope column is lagged -- the intermediate SMA
    level is never itself used downstream, same "lag only what's actually
    used as a feature" convention `modules/slope_magnitude.py::prepare`'s
    `recent_large_move` follows.
    """
    working = panel.copy()
    raw_cols = []
    for lookback in NEW_LOOKBACKS:
        sma_col = f"_sma_{lookback}_tmp"
        working[sma_col] = working.groupby("ticker")["close"].transform(
            lambda s, lb=lookback: s.rolling(lb, min_periods=lb).mean()
        )
        slope_raw_col = f"_slope_{lookback}_raw"
        working[slope_raw_col] = working.groupby("ticker")[sma_col].transform(
            lambda s: slope_features.slope_log_k(s, SLOPE_K)
        )
        raw_cols.append(slope_raw_col)

    working = working.drop(columns=[f"_sma_{lb}_tmp" for lb in NEW_LOOKBACKS])
    working = apply_lag(working, raw_cols)
    for lookback, raw_col in zip(NEW_LOOKBACKS, raw_cols):
        working[slope_column(lookback)] = working[raw_col]
    return working.drop(columns=raw_cols)


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, `fwd_mdd_21`, the C2 match buckets,
    `slope_log_21_sma_{10,100}` (module-local, see `_build_new_sma_slopes`),
    and `ribbon_agreement_state` (0-5: count of the five ribbon lookbacks
    with a positive `slope_log_21`). Returns a new frame; `panel` itself is
    not mutated.

    `ribbon_agreement_state` is NaN wherever *any* of the five lookbacks'
    slope is undefined (MA warmup, or the two new lookbacks' own longer
    rolling-window warmup) -- CLAUDE.md invariant #9: `> 0` returns False on
    NaN, which would silently read "undefined" as "falling" instead of
    undefined, the same defect the `above_sma_200` fix (invariant #9's own
    named example) corrects for a single-MA state. Masked explicitly here
    via `.where(all_defined)` rather than left to comparison-propagation,
    and asserted by this module's own test.
    """
    working = panel.copy()
    working = _build_new_sma_slopes(working)

    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["fwd_mdd_21"] = forward_max_drawdown(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    # Reversal-robustness-check-only column (see `C2_MATCH_COLS_WITH_REVERSAL`),
    # same construction as `modules/slope_magnitude.py`'s own `rev_tercile`.
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)

    slope_cols = [slope_column(lb) for lb in RIBBON_LOOKBACKS]
    all_defined = working[slope_cols].notna().all(axis=1)
    positive_count = sum((working[col] > 0).astype("int64") for col in slope_cols)
    working["ribbon_agreement_state"] = positive_count.where(all_defined).astype("Int64")

    return working


def slope_correlation_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Required output regardless of `extreme_state_test`'s outcome
    (DESIGN's own text: "report the correlation matrix rather than
    pretending it's five signals"). Per-date median Spearman correlation
    (`feature_sweep.py::per_date_median_corr`, this study's own established
    redundancy-check primitive -- M6.1/M11 precedent) between every pair of
    the five lookbacks' own `slope_log_21` values, plus each lookback vs.
    the ordinal `ribbon_agreement_state` itself. `panel` must already be
    `prepare()`'d.
    """
    rows = []
    for lb_a, lb_b in itertools.combinations(RIBBON_LOOKBACKS, 2):
        corr = per_date_median_corr(panel, slope_column(lb_a), slope_column(lb_b))
        rows.append({"pair": f"slope_{lb_a}_vs_slope_{lb_b}", "median_spearman": corr})
    for lb in RIBBON_LOOKBACKS:
        corr = per_date_median_corr(panel, slope_column(lb), "ribbon_agreement_state")
        rows.append({"pair": f"slope_{lb}_vs_ribbon_agreement_state", "median_spearman": corr})
    return pd.DataFrame(rows)


def shape_table(panel: pd.DataFrame) -> pd.DataFrame:
    """One row per ordinal state (0..5): C0/C1/C2 point-estimate deltas on
    both `fwd_ret_21` and `fwd_mdd_21` (no bootstrap CI -- descriptive shape
    read, same convention as M4's `decile_table`/M6.3's `shape_table`),
    plus effective N. The monotonicity read DESIGN asks for is descriptive
    off this table (consistency across adjacent states), not a battery of
    per-adjacent-pair CI tests -- kept out of `N_tests` for the same reason
    M4/M6.3's own decile tables never counted their per-bucket rows as
    independent tests each. `panel` must already be `prepare()`'d.
    """
    working = panel.dropna(subset=["ribbon_agreement_state", "fwd_ret_21", "fwd_mdd_21"]).copy()
    working["ribbon_agreement_state"] = working["ribbon_agreement_state"].astype(int)

    rows = []
    for state in range(N_RUNGS + 1):
        subset = working.assign(is_event=working["ribbon_agreement_state"] == state)
        event_rows = subset[subset["is_event"]]
        n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()
        rows.append({
            "state": state,
            "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
            "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
            "c0_return": c0_delta(subset, "is_event", "fwd_ret_21"),
            "c1_return": c1_delta(subset, "is_event", "fwd_ret_21"),
            "c2_return": c2_delta(subset, "is_event", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)),
            "c0_drawdown": c0_delta(subset, "is_event", "fwd_mdd_21"),
            "c1_drawdown": c1_delta(subset, "is_event", "fwd_mdd_21"),
            "c2_drawdown": c2_delta(subset, "is_event", "fwd_mdd_21", match_cols=list(C2_MATCH_COLS)),
        })
    return pd.DataFrame(rows)


def extreme_state_test(
    panel: pd.DataFrame, value_col: str, match_cols: tuple[str, ...] = C2_MATCH_COLS,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """The decisive test: full-agreement-high (state 5, all five lookbacks
    rising) vs full-agreement-low (state 0, all five falling), C2
    block-bootstrap delta on `value_col` (`fwd_ret_21` or `fwd_mdd_21`).
    `panel` must already be `prepare()`'d.

    Positive `c2` on `fwd_ret_21` (CI excluding zero, edge clearing
    `KILL_THRESHOLD`) => ribbon agreement carries incremental return
    information at its extremes. Positive `c2` on `fwd_mdd_21` (state 5's
    drawdown is *less negative*, i.e. shallower, than state 0's) =>
    agreement carries incremental drawdown-avoidance information. CI
    spanning zero, or edge under the floor => no detected effect at this
    control tier for that outcome.

    `match_cols` defaults to this module's pre-registered `C2_MATCH_COLS`;
    pass `C2_MATCH_COLS_WITH_REVERSAL` for the reversal-robustness
    companion check (not this module's default, not counted in `N_tests`
    on its own -- same convention as M6.3's/M2's own reversal addenda).
    """
    match_cols = list(match_cols)
    working = panel.dropna(subset=["ribbon_agreement_state", value_col, *match_cols]).copy()
    working["ribbon_agreement_state"] = working["ribbon_agreement_state"].astype(int)

    restricted = working[working["ribbon_agreement_state"].isin({LOW_STATE, HIGH_STATE})].copy()
    restricted["is_high"] = restricted["ribbon_agreement_state"] == HIGH_STATE

    event_rows = restricted[restricted["is_high"]]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(
            restricted, "is_high", value_col, match_cols=match_cols,
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": restricted["date"].nunique() if len(restricted) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])

    return {
        "value_col": value_col,
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "edge": edge, "kill_threshold": KILL_THRESHOLD,
        "killed": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
        # CLAUDE.md invariant #10 -- descriptive only.
        "shape": {
            **hit_rate_deltas(restricted, "is_high", value_col, match_cols=match_cols),
            **distribution_shape(event_rows[value_col]),
        },
    }


def cost_annotation(panel: pd.DataFrame, round_trip_cost: float = ROUND_TRIP_COST) -> dict:
    """CLAUDE.md invariant #8: turnover-based cost hurdle for the
    `ribbon_agreement_state == HIGH_STATE` ("fully agreeing bullish")
    tradeable flag, if `extreme_state_test` on `fwd_ret_21` confirms an
    effect -- the only side of the extreme-state test with an obvious
    long-only trading interpretation (state 0, "fully agreeing bearish", is
    a short-side or exit signal, not annotated separately here). Same
    turnover convention as every prior module
    (`stats/costs.py::signals_per_year` on a state-flip boolean).
    `panel` must already be `prepare()`'d.
    """
    working = panel.copy()
    is_high = (working["ribbon_agreement_state"] == HIGH_STATE).astype("boolean")
    working["is_high"] = is_high.mask(working["ribbon_agreement_state"].isna())

    turnover = signals_per_year(working, "is_high")
    hurdle = cost_hurdle(turnover, round_trip_cost)
    return {"signals_per_year": turnover, "hurdle_annual": hurdle}


def run_grid(panel: pd.DataFrame) -> dict:
    """Full pre-registered M6.6 grid: `slope_correlation_matrix` (required
    regardless of outcome), `shape_table` (descriptive, all 6 states),
    `extreme_state_test` on both `fwd_ret_21` and `fwd_mdd_21` (the 2
    decisive, `N_tests`-counted cells), and `cost_annotation`.
    """
    prepared = prepare(panel)
    return {
        "correlation_matrix": slope_correlation_matrix(prepared),
        "shape_table": shape_table(prepared),
        "extreme_state_test_return": extreme_state_test(prepared, "fwd_ret_21"),
        "extreme_state_test_drawdown": extreme_state_test(prepared, "fwd_mdd_21"),
        "cost": cost_annotation(prepared),
    }
