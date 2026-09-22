"""M6.3 -- Slope magnitude: monotonic or humped? (DESIGN.md, "M6.3 --
Slope magnitude: monotonic or humped?"; PREREGISTRATION.md, 2026-09-21).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion
/ scope statement, including two logged deviations from DESIGN's literal
text (also summarized here since they shape this module's whole design):

1. **`slope_atr_21` is not built.** DESIGN's method line asks for "decile
   buckets of `slope_atr_21` and `slope_pctile_21`" -- but `slope_atr_21`
   (an ATR-normalized, price-unit slope: `(ma_t - ma_{t-21}) / atr_14`)
   directly conflicts with CLAUDE.md invariant #7 ("Log scale for
   slopes. `slope_log_k` only. Percentage and price-unit slopes are not
   comparable across tickers.") `features/slope.py`'s own docstring
   confirms `slope_atr_k` was deliberately deferred out of Phase 2 for
   exactly this reason ("the only scale-invariant version" is
   `slope_log_k`). This module therefore uses `slope_pctile_21` only --
   a per-date cross-sectional percentile rank of the existing,
   already-lagged, log-scale `slope_log_21_sma_k` column -- DESIGN's own
   named alternative formulation in the same sentence, and fully
   invariant-#7-compliant since it never leaves log scale.
2. **The "earnings-excluded" companion DESIGN asks for is a proxy, not
   the real thing.** There is no earnings-date table anywhere in this
   repo's DB (checked: every table in the raw-data DB was enumerated
   before this module was built; none is earnings-related). Substituted
   with a `recent_large_move` exclusion flag: any event day preceded
   within the trailing `LARGE_MOVE_LOOKBACK_DAYS` trading days by a
   single-day |return| > `LARGE_MOVE_THRESHOLD` is treated as
   plausibly gap-contaminated. Not the same as a true earnings-proximity
   filter (a large move can be a buyout announcement, a guidance cut, a
   macro shock, etc., and a genuine post-earnings drift with no single
   outsized day would be missed) -- named as a proxy, not claimed as
   equivalent.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
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
LOOKBACKS = (20, 50, 200)
N_DECILES = 10
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Robustness-check-only match set (PREREGISTRATION.md, 2026-09-22 reversal-
# robustness addendum), same construction as `modules/slope_conditioner.py`'s/
# `modules/stack_minervini.py`'s/`modules/baseline_state.py`'s own
# `C2_MATCH_COLS_WITH_REVERSAL`: adds a prior-21-day-return tercile so a
# cell's C2 delta can be re-evaluated with short-term reversal explicitly
# matched out. Not this module's pre-registered default -- `humped_test`'s
# own `match_cols` stays `C2_MATCH_COLS` unless a caller explicitly opts
# into this one.
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# "Humped" operationalized as: do the middle deciles of slope_pctile_21
# outperform (or underperform) the pooled tail deciles? The tails are
# both extremes pooled together (not "top decile" alone, which is M6.2's
# own extension x slope question, not this one) -- this module asks
# about the *magnitude* of slope regardless of sign, not direction.
MIDDLE_DECILES = (4, 5)
TAIL_DECILES = (0, 1, 8, 9)

# Same 0.10% floor every return-valued cell in this study uses (M1/M2/M6.2).
KILL_THRESHOLD = 0.001

# Earnings-gap proxy (no real earnings-date table exists in this repo's
# DB -- see module docstring). 7% single-day move over a trailing 5-day
# window is a first-pass threshold, not DESIGN-derived; a genuine gap is
# typically larger than routine daily noise but well under
# `data.py::flag_large_moves`'s own 50% data-hygiene threshold, which
# flags likely data errors, not real gap days -- a different purpose,
# not reused here.
LARGE_MOVE_THRESHOLD = 0.07
LARGE_MOVE_LOOKBACK_DAYS = 5


def slope_pctile_column(lookback: int) -> str:
    return f"slope_pctile_21_sma_{lookback}"


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, `slope_pctile_21_sma_k`
    for every lookback in `LOOKBACKS` (per-date decile rank of the
    already-lagged, already-cached `slope_log_21_sma_k`), and the
    lagged `recent_large_move` earnings-gap proxy. Returns a new frame;
    `panel` itself is not mutated.

    `recent_large_move` is built from the panel's own raw (unlagged)
    `close` column -- unlike `slope_pctile_21` (a same-day transform of
    an already-lagged input, which inherits that lag for free), this is
    a genuinely new raw-derived feature and must go through `apply_lag`
    itself (CLAUDE.md invariant #2 -- reusing the one central lag
    function, not a hand-rolled shift) before it can be used to restrict
    an event population that will be paired with a forward return.

    Also adds `rev_tercile` (prior-21-day-return tercile, same
    construction as `modules/slope_conditioner.py`'s/`modules/
    stack_minervini.py`'s own robustness-check column), used only by the
    short-term-reversal check (`C2_MATCH_COLS_WITH_REVERSAL`), not by
    this module's default C2 spec.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    for lookback in LOOKBACKS:
        slope_col = f"slope_log_21_sma_{lookback}"
        working[slope_pctile_column(lookback)] = cross_sectional_bucket(working, slope_col, n_buckets=N_DECILES)

    daily_ret = working.groupby("ticker")["close"].transform(lambda s: s / s.shift(1) - 1)
    trailing_max_abs_move = (
        daily_ret.abs()
        .groupby(working["ticker"])
        .transform(lambda s: s.rolling(LARGE_MOVE_LOOKBACK_DAYS, min_periods=1).max())
    )
    working["_recent_large_move_raw"] = trailing_max_abs_move > LARGE_MOVE_THRESHOLD
    working = apply_lag(working, ["_recent_large_move_raw"])
    working["recent_large_move"] = working["_recent_large_move_raw"].astype("boolean")
    working = working.drop(columns=["_recent_large_move_raw"])
    return working


def shape_table(panel: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """One row per decile of `slope_pctile_21_sma_{lookback}`: C0/C1/C2
    point-estimate deltas on `fwd_ret_21` (no bootstrap CI -- this is the
    descriptive shape read, same convention and same reused primitives as
    M4's own `decile_table`), plus effective N. A decile below DESIGN
    §6.9's minimum sample threshold is flagged via `below_threshold`, not
    dropped. `panel` must already be `prepare()`'d.
    """
    decile_col = slope_pctile_column(lookback)
    working = panel.dropna(subset=[decile_col, "fwd_ret_21"]).copy()
    working[decile_col] = working[decile_col].astype(int)

    rows = []
    for decile in range(N_DECILES):
        subset = working.assign(is_event=working[decile_col] == decile)
        event_rows = subset[subset["is_event"]]
        n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()
        rows.append({
            "lookback": lookback, "decile": decile,
            "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
            "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
            "c0": c0_delta(subset, "is_event", "fwd_ret_21"),
            "c1": c1_delta(subset, "is_event", "fwd_ret_21"),
            "c2": c2_delta(subset, "is_event", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)),
        })
    return pd.DataFrame(rows)


def humped_test(
    panel: pd.DataFrame, lookback: int, exclude_recent_large_move: bool = False,
    match_cols: tuple[str, ...] = C2_MATCH_COLS, block_length: int = 42, n_boot: int = 500,
    ci: float = 0.90, seed: int = 0,
) -> dict:
    """The one CI-backed decisive test per lookback: middle deciles
    (`MIDDLE_DECILES`) vs. pooled tail deciles (`TAIL_DECILES`) of
    `slope_pctile_21_sma_{lookback}`, C2 block-bootstrap delta on
    `fwd_ret_21`. Positive and CI-excluding-zero => humped (middle beats
    the tails). Negative and CI-excluding-zero => U-shaped (tails beat
    the middle). CI spans zero, or edge < `KILL_THRESHOLD` => no humped/
    U-shaped structure detected at this control tier -- read
    `shape_table`'s per-decile point estimates for monotonic-vs-flat
    instead. `panel` must already be `prepare()`'d.

    `exclude_recent_large_move=True` restricts to the earnings-gap-proxy-
    excluded population (this module's substitute for DESIGN's
    "earnings-excluded companion" -- see module docstring).
    """
    decile_col = slope_pctile_column(lookback)
    working = panel.dropna(subset=[decile_col, "fwd_ret_21", *match_cols]).copy()
    working[decile_col] = working[decile_col].astype(int)
    if exclude_recent_large_move:
        working = working[~working["recent_large_move"].fillna(True)]

    restricted = working[working[decile_col].isin({*MIDDLE_DECILES, *TAIL_DECILES})].copy()
    restricted["is_middle"] = restricted[decile_col].isin(MIDDLE_DECILES)

    event_rows = restricted[restricted["is_middle"]]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(
            restricted, "is_middle", "fwd_ret_21", match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": restricted["date"].nunique() if len(restricted) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])

    return {
        "lookback": lookback,
        "exclude_recent_large_move": exclude_recent_large_move,
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "edge": edge, "kill_threshold": KILL_THRESHOLD,
        "killed": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
        # CLAUDE.md invariant #10 -- descriptive only, no CI/kill/N_tests
        # contribution of their own. `is_middle`'s own hit rate vs. the
        # C1/C2-matched tail control, plus the middle group's own raw
        # win/loss ratio and skew (DESIGN §6.11.1's exact fields).
        "shape": {
            **hit_rate_deltas(restricted, "is_middle", "fwd_ret_21", match_cols=list(match_cols)),
            **distribution_shape(event_rows["fwd_ret_21"]),
        },
    }


def cost_annotation(panel: pd.DataFrame, lookback: int, round_trip_cost: float = ROUND_TRIP_COST) -> dict:
    """CLAUDE.md invariant #8: turnover-based cost hurdle for the
    middle-vs-tail-deciles claim, if `humped_test` confirms one. Turnover
    is measured the same way M1's `above_sma_k` state-flip count is
    (`stats/costs.py::signals_per_year`, reused unchanged) on an
    `is_middle` state column (True while `slope_pctile_21_sma_{lookback}`
    sits in `MIDDLE_DECILES`, False elsewhere -- including the
    non-tail/non-middle deciles 2/3/6/7, which are outside `humped_test`'s
    own restricted population but still count as "not in the tails" for a
    turnover measure of how often the flag itself flips). `panel` must
    already be `prepare()`'d.
    """
    decile_col = slope_pctile_column(lookback)
    working = panel.copy()
    is_middle = working[decile_col].isin(MIDDLE_DECILES).astype("boolean")
    working["is_middle"] = is_middle.mask(working[decile_col].isna())

    turnover = signals_per_year(working, "is_middle")
    hurdle = cost_hurdle(turnover, round_trip_cost)
    return {"lookback": lookback, "signals_per_year": turnover, "hurdle_annual": hurdle}


def run_grid(panel: pd.DataFrame) -> dict:
    """Full pre-registered M6.3 grid: `shape_table` (descriptive, all 10
    deciles), `humped_test` (decisive, default population and the
    recent-large-move-excluded companion), and `cost_annotation` for
    every lookback in `LOOKBACKS`.
    """
    prepared = prepare(panel)
    shapes, humped, humped_excl, costs = {}, {}, {}, {}
    for lookback in LOOKBACKS:
        shapes[lookback] = shape_table(prepared, lookback)
        humped[lookback] = humped_test(prepared, lookback, exclude_recent_large_move=False)
        humped_excl[lookback] = humped_test(prepared, lookback, exclude_recent_large_move=True)
        costs[lookback] = cost_annotation(prepared, lookback)
    return {
        "shape_table": shapes, "humped_test": humped,
        "humped_test_excl_large_move": humped_excl, "cost": costs,
    }
