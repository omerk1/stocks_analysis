"""M2 -- Stack states and Minervini ablation (DESIGN.md §8, M2;
PREREGISTRATION.md, 2026-09-12).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement -- this module implements exactly that slice.

**Part (a)** -- `stack_fully_bullish`/`stack_fully_bearish` (the 2 primary
cells: price and all four SMAs {20,50,150,200} in perfect bullish/bearish
order) plus `stack_perm` (secondary/descriptive, the 4 SMAs' relative rank
order regardless of price). Question: does the *full* stack carry
information beyond a single MA's above/below state (M1)? Answered via
`block_bootstrap_group_diff` between a primary cell's C2 delta and M1's
`above_sma_50` state's own C2 delta (`REFERENCE_SINGLE_MA_COL` -- M1's
Tier-3 lb50 cell), both computed on the same intersected C2-eligible row
population. Kill rule mirrors M1's own `evaluate_kill_criterion` exactly
(`max(|ci_low|, |ci_high|) < 0.10%`, `stats/inference.py::block_bootstrap_*`)
-- see this module's docstring note below on a wording slip in
PREREGISTRATION.md's kill-criterion paragraph.

**Part (b)** -- the full 2**8 = 256-subset boolean ablation of the 8
Trend Template criteria (`ablation_subset_table`), plus a linear (OLS)
per-criterion attribution (`linear_attribution`) as DESIGN's own
alternative to a full Shapley decomposition. Per DESIGN's explicit "kill:
none -- the ablation is informative regardless of outcome," this part has
no kill criterion; the 8 attribution coefficients are descriptive, not a
battery of 256 hypothesis tests.

**Pre-registration wording note (found while implementing, not a scope
change):** PREREGISTRATION.md's M2 kill-criterion paragraph describes
"the same CI-based rule M1 established (2026-09-09 correction: spans-zero
auto-fails...)" -- this conflates two *different* M1 rules. M1's
2026-09-09 "spans-zero auto-fails" correction was applied only to
`stats/costs.py::ci_clears_cost` (the cost-clearance test). M1's actual
`evaluate_kill_criterion` (the rule this module's part (a) is supposed to
mirror) was, from the start, exactly `max(|ci_low|, |ci_high|) < 0.10%`
with no separate spans-zero short-circuit -- that formula already handles
a zero-spanning interval correctly on its own terms (both endpoints are
compared regardless of sign), it just isn't the *same* mechanism as the
cost test's fix. This module implements the literal, unambiguous formula
PREREGISTRATION.md also states in the same sentence (`max(|ci_low|,
|ci_high|) < 0.10%`), i.e. M1's real rule -- the parenthetical is a
mislabel to fix in PREREGISTRATION.md, not a reason to invent a different
rule here.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import distance
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import (
    c1_delta,
    c2_eligible_mask,
    cross_sectional_bucket,
)
from src.signals.moving_averages.stats.costs import (
    ci_clears_cost,
    cost_hurdle,
    point_clears_cost,
    signals_per_year,
)
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
    block_bootstrap_group_diff,
)
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas
from src.signals.relative_strength.compute import compute_stock_vs_market
from src.signals.relative_strength.config import RelativeStrengthConfig

# DESIGN §6.9, same numbers as M1/M4/M11.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# M1's kill-criterion floor (PREREGISTRATION.md's M1 entry, `KILL_THRESHOLD`
# in `modules/baseline_state.py`) -- reused unchanged, see module docstring.
KILL_THRESHOLD = 0.001  # 0.10%

# The 8 Trend Template criteria, in PREREGISTRATION.md's stated order.
CRITERIA_COLS = ("tt_c1", "tt_c2", "tt_c3", "tt_c4", "tt_c5", "tt_c6", "tt_c7", "tt_c8")

RS_RANK_FLOOR = 70.0
PCT_ABOVE_52W_LOW = 0.30  # criterion 6: >= 30% above the 52-week low
PCT_WITHIN_52W_HIGH = 0.25  # criterion 7: within 25% of the 52-week high

# M1's single-lookback reference for part (a)'s incremental test -- SMA50
# is the middle lookback in the {20,50,150,200} stack and the one M1's own
# lb50 primary cell tiered Tier-3 on (survives CI, fails cost), rather than
# lb200 (CI touches/spans zero at both control sets) or lb20 (also Tier 3
# but the shortest, least "trend-like" of the three).
REFERENCE_SINGLE_MA_COL = "above_sma_50"


def prepare(panel: pd.DataFrame, conn: sqlite3.Connection, index_name: str = "sp500") -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets (`mom_tercile`/`vol_tercile`,
    same tercile-not-decile convention as M1/M4/M11, referenced not
    re-derived), `rs_rating` (joined from `relative_strength.compute
    .compute_stock_vs_market` -- reused, not rebuilt, per this repo's own
    reuse pointer), the 8 Trend Template criteria, and the stack features.
    Returns a new frame; `panel` itself is not mutated.

    `rs_rating` is cross-sectional (index-membership-scoped) and isn't in
    the shared panel cache (`features/panel.py`'s own docstring explains
    why) -- joined here, then passed through the *same* central
    `features.panel.apply_lag` function M1/M4/M11's cached columns already
    went through, not a hand-rolled shift (CLAUDE.md invariant #2).

    `conn` must be the same raw-data connection `compute_stock_vs_market`
    reads bars/index-membership from (i.e. the same connection `panel` was
    built against), not the derived-results DB `relative_strength`'s own
    CLI writes to -- this calls the compute function directly rather than
    reading a pre-populated `relative_strength` table, so no separate CLI
    run is required first.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    start = working["date"].min()
    end = working["date"].max()
    rs = compute_stock_vs_market(
        conn, index_name, RelativeStrengthConfig(), start=str(start.date()), end=str(end.date())
    )
    if not rs.empty:
        working = working.merge(rs[["ticker", "date", "rs_rating"]], on=["ticker", "date"], how="left")
    else:
        working["rs_rating"] = np.nan
    working = apply_lag(working, columns=["rs_rating"])

    working = _add_trend_template_criteria(working)
    working = _add_stack_features(working)
    return working


def _add_trend_template_criteria(working: pd.DataFrame) -> pd.DataFrame:
    """The 8 Trend Template criteria as lagged booleans. Every criterion
    built from a comparison (not arithmetic) gets an explicit NaN mask
    (CLAUDE.md invariant #9) -- `distance.above` already does this for the
    pairwise MA/price comparisons; the three new comparisons here
    (slope sign, 52-week proximity, RS rank) are masked the same way,
    inline, rather than reusing `above` (which is specifically a > b, not
    a threshold test).
    """
    close = working["close"]
    sma50, sma150, sma200 = working["sma_50"], working["sma_150"], working["sma_200"]

    working["tt_c1"] = distance.above(close, sma150) & distance.above(close, sma200)
    working["tt_c2"] = distance.above(sma150, sma200)

    slope200 = working["slope_log_21_sma_200"]
    working["tt_c3"] = (slope200 > 0).astype("boolean").mask(slope200.isna())

    working["tt_c4"] = distance.above(sma50, sma150) & distance.above(sma50, sma200)
    working["tt_c5"] = distance.above(close, sma50)

    low52 = working["dist_from_52w_low"]
    working["tt_c6"] = (low52 >= PCT_ABOVE_52W_LOW).astype("boolean").mask(low52.isna())

    high52 = working["dist_from_52w_high"]
    working["tt_c7"] = (high52 >= -PCT_WITHIN_52W_HIGH).astype("boolean").mask(high52.isna())

    rsr = working["rs_rating"]
    working["tt_c8"] = (rsr >= RS_RANK_FLOOR).astype("boolean").mask(rsr.isna())

    return working


def _add_stack_features(working: pd.DataFrame) -> pd.DataFrame:
    """`stack_perm` (secondary): a categorical label of the 4 SMAs'
    relative rank order (24 possible orderings), NaN wherever any of the 4
    is NaN -- not derived from `.rank()`'s own NaN handling (which only
    guarantees the *NaN cell itself* comes back NaN, not that the whole
    row's label is invalidated), masked explicitly instead.

    `stack_fully_bullish`/`stack_fully_bearish` (primary): built entirely
    from `distance.above` chains, whose NaN propagation via Kleene-logic
    `&` is Kleene-safe in the sense `features/panel.py`'s `stacked_sma`/
    `stacked_ema` already rely on -- but Kleene AND is *not* enough on its
    own for a 4-term chain across MAs with different warmup lengths, found
    while validating this module against real data: a short-warmup link
    (e.g. `close > sma_20`) can resolve to a determinate `False` while a
    longer-warmup link later in the chain (`sma_150 > sma_200`) is still
    NaN, and Kleene `False & NaN = False` short-circuits the *whole* chain
    to `False` -- correct Boolean logic, but it produces a column that
    goes False-then-NaN-then-settled over calendar time as each MA's own
    warmup ends at a different point, not a single leading NaN block like
    every other MA-derived state column in this codebase (`above_sma_k`,
    and -- unexercised until now -- `stacked_sma`/`stacked_ema` are
    logically exposed to the same shape, just never fed into
    `state_run_id` before this module). `state.state_run_id` (which
    `stats/costs.py::signals_per_year` needs for turnover) explicitly
    rejects exactly this shape rather than silently mis-measuring it
    (invariant #9's own guard doing its job) -- confirmed against real
    sp500 panel data (`AAPL`, 2010-02: `close > sma_20` false for 3 days
    while `sma_50/150/200` are still NaN, then flips true while they're
    still NaN, producing False,False,False,NaN,NaN,...). Masked here
    instead: `stack_fully_bullish`/`stack_fully_bearish` are undefined
    until all 4 SMAs exist simultaneously, regardless of what any single
    already-warmed-up link could determine on its own -- a single leading
    gap, matching every other state column's shape.
    """
    close = working["close"]
    sma20, sma50, sma150, sma200 = working["sma_20"], working["sma_50"], working["sma_150"], working["sma_200"]

    ma_cols = ["sma_20", "sma_50", "sma_150", "sma_200"]
    any_ma_na = working[ma_cols].isna().any(axis=1)
    ranks = working[ma_cols].rank(axis=1, method="first").fillna(0).astype(int)
    stack_perm = ranks["sma_20"].astype(str) + ranks["sma_50"].astype(str) + ranks["sma_150"].astype(str) + ranks["sma_200"].astype(str)
    working["stack_perm"] = pd.Series(stack_perm, index=working.index, dtype="string").mask(any_ma_na)

    fully_bullish = (
        distance.above(close, sma20)
        & distance.above(sma20, sma50)
        & distance.above(sma50, sma150)
        & distance.above(sma150, sma200)
    )
    fully_bearish = (
        distance.above(sma20, close)
        & distance.above(sma50, sma20)
        & distance.above(sma150, sma50)
        & distance.above(sma200, sma150)
    )
    working["stack_fully_bullish"] = fully_bullish.mask(any_ma_na)
    working["stack_fully_bearish"] = fully_bearish.mask(any_ma_na)
    return working


def _cell_row(working: pd.DataFrame, group_col: str, label: dict, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> dict:
    """One cell's C0/C1/C2-style report -- leaner than M1's own `_cell_row`
    (`modules/baseline_state.py`; no row-loss waterfall diagnostic, this
    module doesn't re-litigate that question), same C2-eligible-restriction
    and block-bootstrap shape.

    Also reports DESIGN §6.11.1's three shape fields (hit rate vs. the
    same C1/C2 control already computed above, win/loss magnitude ratio,
    skew -- `stats/shape.py`, CLAUDE.md invariant #10). Descriptive only:
    no CI, no kill criterion, no `N_tests` contribution of their own.
    """
    mask = c2_eligible_mask(working, group_col, "fwd_ret_21", match_cols=list(match_cols))
    restricted = working[mask]

    event_rows = restricted[restricted[group_col].astype(bool)]
    n_events = len(event_rows)
    n_dates = event_rows["date"].nunique()
    n_tickers = event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(restricted, group_col, "fwd_ret_21", match_cols=list(match_cols))
    except InsufficientBlocksError:
        boot = {
            "ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
            "point_estimate": float("nan"), "n_dates": restricted["date"].nunique() if len(restricted) else 0,
        }

    if len(restricted):
        hit_rates = hit_rate_deltas(restricted, group_col, "fwd_ret_21", match_cols=list(match_cols))
        shape = distribution_shape(event_rows["fwd_ret_21"])
    else:
        hit_rates = {"hit_rate": float("nan"), "hit_rate_delta_c1": float("nan"), "hit_rate_delta_c2": float("nan")}
        shape = {"win_loss_ratio": float("nan"), "skew": float("nan"), "n_wins": 0, "n_losses": 0,
                 "mean_win": float("nan"), "mean_loss": float("nan")}

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "n_eligible": len(restricted),
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(restricted, group_col, "fwd_ret_21") if len(restricted) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "hit_rate": hit_rates["hit_rate"],
        "hit_rate_delta_c1": hit_rates["hit_rate_delta_c1"],
        "hit_rate_delta_c2": hit_rates.get("hit_rate_delta_c2", float("nan")),
        "win_loss_ratio": shape["win_loss_ratio"],
        "skew": shape["skew"],
        "n_wins": shape["n_wins"],
        "n_losses": shape["n_losses"],
    }


def primary_stack_table(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 2 primary cells: `stack_fully_bullish`, `stack_fully_bearish`
    vs. the rest of the C2-eligible population. Same shape as M1's
    `state_table` (`modules/baseline_state.py`), 2 cells instead of 6.
    """
    rows = []
    for label, col in (("fully_bullish", "stack_fully_bullish"), ("fully_bearish", "stack_fully_bearish")):
        cell = working.dropna(subset=[col]).copy()
        cell["_is_event"] = cell[col].astype(bool)
        rows.append(_cell_row(cell, "_is_event", {"cell": label}, match_cols=match_cols))
    return pd.DataFrame(rows)


def incremental_vs_single_ma_table(
    working: pd.DataFrame,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
    reference_col: str = REFERENCE_SINGLE_MA_COL,
) -> pd.DataFrame:
    """PREREGISTRATION.md's actual part-(a) test: for each primary stack
    cell, `block_bootstrap_group_diff(stack_cell, reference_col)` on the
    row population where *both* the stack cell and `reference_col` are
    C2-eligible (the intersection of each definition's own eligibility
    mask, not either one's wider natural row set) -- the specific
    incremental question is whether the full stack adds anything over
    M1's single-lookback state, not merely whether the stack cell itself
    is nonzero in isolation.
    """
    rows = []
    for label, col in (("fully_bullish", "stack_fully_bullish"), ("fully_bearish", "stack_fully_bearish")):
        base = working.dropna(subset=[col, reference_col, "fwd_ret_21"]).copy()
        stack_mask = c2_eligible_mask(base, col, "fwd_ret_21", match_cols=list(match_cols))
        ref_mask = c2_eligible_mask(base, reference_col, "fwd_ret_21", match_cols=list(match_cols))
        shared = base[stack_mask.to_numpy() & ref_mask.to_numpy()].copy()
        shared["_stack_event"] = shared[col].astype(bool)
        shared["_ref_event"] = shared[reference_col].astype(bool)

        try:
            diff = block_bootstrap_group_diff(
                shared, "_stack_event", "_ref_event", "fwd_ret_21", match_cols=list(match_cols)
            )
        except InsufficientBlocksError:
            diff = {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_dates": 0}

        edge = max(abs(diff["ci_low"]), abs(diff["ci_high"])) if not pd.isna(diff["ci_low"]) else float("nan")
        rows.append({
            "cell": label,
            "reference": reference_col,
            "n_shared_rows": len(shared),
            "diff_point": diff["point_estimate"],
            "diff_ci_low": diff["ci_low"],
            "diff_ci_high": diff["ci_high"],
            "n_dates": diff["n_dates"],
            "kill_cell": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        })
    return pd.DataFrame(rows)


def evaluate_part_a_kill_criterion(incremental: pd.DataFrame) -> dict:
    """Module-level verdict for part (a) only: kill fires iff every
    primary cell's `kill_cell` is True (mirrors M1's
    `evaluate_kill_criterion` exactly -- see this module's own docstring
    note on the PREREGISTRATION.md wording slip). A cell whose CI couldn't
    be computed (`kill_cell is None`, `InsufficientBlocksError`) counts as
    *not* killed here (unresolved, not evidence of survival) rather than
    silently treated as a pass either way -- surfaced via `n_unresolved`.
    """
    resolved = incremental["kill_cell"].dropna()
    return {
        "kill_threshold": KILL_THRESHOLD,
        "cell_killed": incremental["kill_cell"].tolist(),
        "n_primary_cells": len(incremental),
        "n_cells_killed": int(resolved.sum()),
        "n_unresolved": int(incremental["kill_cell"].isna().sum()),
        "module_killed": bool(len(resolved) == len(incremental) and resolved.all()),
    }


def stack_perm_table(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """Secondary/descriptive: C0/C1/C2 per non-empty `stack_perm` category
    vs. the rest of the C2-eligible population. Does not feed the part-(a)
    kill criterion (PREREGISTRATION.md) -- reported for the "does the
    specific ordering matter beyond fully-bullish/fully-bearish" question.
    """
    rows = []
    categories = sorted(working["stack_perm"].dropna().unique())
    for category in categories:
        cell = working.dropna(subset=["stack_perm"]).copy()
        cell["_is_event"] = cell["stack_perm"] == category
        rows.append(_cell_row(cell, "_is_event", {"stack_perm": category}, match_cols=match_cols))
    return pd.DataFrame(rows)


def plateau_check_vs_single_ma(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """DESIGN §6.7's plateau rule, applied per PREREGISTRATION.md's M2
    entry as directional (sign) consistency rather than a lookback-
    neighborhood test: `stack_fully_bullish`'s C2 point estimate compared
    against each individual `above_sma_{20,50,150,200}` cell's own C2
    point estimate, recomputed here directly (not read back from M1's
    logged output) so this check is self-contained and reproducible from
    this module alone.
    """
    rows = []
    stack_cell = working.dropna(subset=["stack_fully_bullish"]).copy()
    stack_cell["_is_event"] = stack_cell["stack_fully_bullish"].astype(bool)
    rows.append(_cell_row(stack_cell, "_is_event", {"cell": "stack_fully_bullish"}, match_cols=match_cols))

    for lookback in (20, 50, 150, 200):
        col = f"above_sma_{lookback}"
        cell = working.dropna(subset=[col]).copy()
        cell["_is_event"] = cell[col].astype(bool)
        rows.append(_cell_row(cell, "_is_event", {"cell": col}, match_cols=match_cols))

    table = pd.DataFrame(rows)
    stack_sign = np.sign(table.loc[table["cell"] == "stack_fully_bullish", "c2"].iloc[0])
    table["agrees_with_stack_sign"] = np.sign(table["c2"]) == stack_sign
    return table


def cost_annotation(panel: pd.DataFrame, state_col: str = "stack_fully_bullish", round_trip_cost: float = 0.0010) -> dict:
    """DESIGN §6.10 / CLAUDE.md invariant #8, for `state_col`'s turnover --
    reuses `stats/costs.py` unchanged (already generic over any boolean
    state column via `features/state.py::state_run_id`, the same tool
    M1's own state-flip turnover uses).
    """
    per_year = signals_per_year(panel, state_col)
    hurdle = cost_hurdle(per_year, round_trip_cost)
    return {"state_col": state_col, "signals_per_year": per_year, "round_trip_cost": round_trip_cost, "cost_hurdle_annual": hurdle}


def ablation_subset_table(working: pd.DataFrame) -> pd.DataFrame:
    """All 2**8 = 256 boolean-criterion subsets (PREREGISTRATION.md M2,
    part b) -- one row per bitmask (bit i = `CRITERIA_COLS[i]` satisfied),
    reporting n_events/n_dates/n_tickers, mean `fwd_ret_21`, and the C1
    (date-matched) delta of that subset vs. the rest of the criteria-
    eligible population. Attribution inputs, not 256 independent
    hypothesis tests (DESIGN's own framing, PREREGISTRATION.md) -- most
    subsets will be below DESIGN §6.9's minimum-sample threshold by
    construction (e.g. RS rank >= 70 co-occurring with price below SMA200
    is rare); flagged via `below_threshold`, not dropped.
    """
    eligible = working.dropna(subset=[*CRITERIA_COLS, "fwd_ret_21"]).copy()
    bitmask = np.zeros(len(eligible), dtype=np.int64)
    for i, col in enumerate(CRITERIA_COLS):
        bitmask += eligible[col].astype(bool).to_numpy().astype(np.int64) << i
    eligible["_bitmask"] = bitmask

    rows = []
    for mask_value, group in eligible.groupby("_bitmask"):
        n_events = len(group)
        n_dates = group["date"].nunique()
        n_tickers = group["ticker"].nunique()
        is_event = (eligible["_bitmask"] == mask_value)
        c1 = c1_delta(eligible.assign(_is_event=is_event), "_is_event", "fwd_ret_21") if n_events else float("nan")
        criteria_true = [col for i, col in enumerate(CRITERIA_COLS) if (mask_value >> i) & 1]
        rows.append({
            "bitmask": int(mask_value),
            "criteria_true": ",".join(criteria_true),
            "n_events": n_events,
            "n_dates": n_dates,
            "n_tickers": n_tickers,
            "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
            "mean_fwd_ret_21": group["fwd_ret_21"].mean(),
            "c1_delta": c1,
        })
    return pd.DataFrame(rows).sort_values("bitmask").reset_index(drop=True)


def linear_attribution(working: pd.DataFrame) -> pd.DataFrame:
    """Linear (OLS) per-criterion attribution: `fwd_ret_21` regressed on
    the 8 Trend Template boolean criteria jointly (plus intercept) --
    DESIGN's own "linear ... attribution" alternative to a full Shapley
    decomposition (§8, M2). Each coefficient is that criterion's marginal
    contribution holding the other 7 fixed.

    Descriptive only, per PREREGISTRATION.md: no CI, no kill criterion --
    `N_tests` for part (b) is these 8 coefficients, not the 256 subsets in
    `ablation_subset_table`. Plain OLS via `np.linalg.lstsq`, not a new
    statistics dependency.
    """
    eligible = working.dropna(subset=[*CRITERIA_COLS, "fwd_ret_21"]).copy()
    design = eligible[list(CRITERIA_COLS)].astype(float).to_numpy()
    design = np.column_stack([np.ones(len(design)), design])
    target = eligible["fwd_ret_21"].to_numpy()
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    return pd.DataFrame({
        "criterion": ["intercept", *CRITERIA_COLS],
        "coefficient": coefficients,
        "n_events": len(eligible),
        "n_dates": eligible["date"].nunique(),
    })
