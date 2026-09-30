"""M19 -- MA respect history (DESIGN.md M19; PREREGISTRATION.md,
2026-09-30). Post-termination module under DESIGN §1.5's porous-scope
rule.

Track B. Does an MA that has recently *acted as* support (or resistance)
-- a touch followed by a confirmed reversal -- keep acting that way on the
next touch, more than an unwatched MA does? M5 found the first touch of a
real MA holds no better than a synthetic neighbour's; M6.2 found a rising
MA holds no better than a falling one once short-term reversal is
controlled. Neither tested persistence of respect per ticker-MA.

Design: the same ex-ante touch events as M5 (`features/touch.py`), the
same focal-vs-synthetic-neighbour groups as §7.5/M5 plus SMA20, and one
new conditioning feature (`features/respect.py`: same-side confirmed
reversals in the trailing L days, dated by confirmation). Statistic per
cell: a difference-in-differences,

    [P(hold | >=2 respect, real MA) - P(hold | 0 respect, real MA)]
  - [P(hold | >=2 respect, neighbour) - P(hold | 0 respect, neighbour)]

each arm's delta date-and-C2-matched (`stats/inference.py::
block_bootstrap_delta_diff`, shared date blocks). The synthetic arm carries
its OWN respect history, computed identically on its own `dist_atr`, so a
generic "stocks that bounced keep bouncing" effect (vol, mean reversion)
appears in both arms and cancels; only a level-specific effect survives.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import respect
from src.signals.moving_averages.features.placebo_ma import GROUPS as PLACEBO_GROUPS, dist_atr_column
from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW, touch_events
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import annualize, ci_clears_cost, cost_hurdle, point_clears_cost
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
    block_bootstrap_delta_diff,
)
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

# §7.5/M5's three groups plus SMA20 (the task's fourth MA). SMA20's
# neighbours are +/-2 lookback days, the same absolute offset EMA21 uses
# (19/23); SMA19/21 would sit closer but 21 collides in name with the
# EMA21 group. `features/placebo_ma.py::GROUPS` itself is left unchanged
# so §7.5/M5's grids don't silently widen.
GROUPS = {
    **PLACEBO_GROUPS,
    "sma20": {"family": "sma", "focal": 20, "neighbors": (18, 22)},
}
GROUP_ORDER = ("sma20", "ema21", "sma50", "sma200")
DIRECTIONS = (FROM_ABOVE, FROM_BELOW)

# DESIGN §6.9 -- applied to the focal high-respect population per cell.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
HIGH_RESPECT_MIN = 2         # ">= 2 prior confirmed bounces"
BLOCK_LENGTH = 10            # M5/M6.2's touch-event convention (sparse, non-overlapping events)
ROUND_TRIP_COST = 0.0010     # 10 bps round trip, U1 (DESIGN §6.10, unchanged from M1 onward)
TRADING_DAYS_PER_YEAR = 252

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")
CONTROL_TIERS = {
    "c1": (),
    "c2": C2_MATCH_COLS,
    "c2_rev": C2_MATCH_COLS_WITH_REVERSAL,   # the tier the kill criterion is evaluated on
}
PRIMARY_TIER = "c2_rev"

HOLD_OUTCOME = "hold_flag"
RETURN_OUTCOME = "fwd_ret_21"

PRIMARY_PARAMS = {
    "confirm_window": respect.CONFIRM_WINDOW,
    "confirm_distance": respect.CONFIRM_DISTANCE,
    "history_window": respect.HISTORY_WINDOW,
}
# One-at-a-time +/-25% perturbations of K, R, L (DESIGN §6.7 / the task's
# own sensitivity clause). 5 -> 4/6, 1.0 -> 0.75/1.25, 126 -> 95/158.
SENSITIVITY_VARIANTS = {
    "K=4": {**PRIMARY_PARAMS, "confirm_window": 4},
    "K=6": {**PRIMARY_PARAMS, "confirm_window": 6},
    "R=0.75": {**PRIMARY_PARAMS, "confirm_distance": 0.75},
    "R=1.25": {**PRIMARY_PARAMS, "confirm_distance": 1.25},
    "L=95": {**PRIMARY_PARAMS, "history_window": 95},
    "L=158": {**PRIMARY_PARAMS, "history_window": 158},
}
SENSITIVITY_MIN_CI_EXCLUDING = 5   # of 6 perturbations
PLATEAU_MIN_AGREEING_MAS = 2       # of the other 3 MAs in the same direction


def configured_dist_atr_columns(panel: pd.DataFrame, groups: dict = GROUPS) -> list[str]:
    """Every focal + neighbour `dist_atr_*` column this module knows about
    that is actually present in `panel` (the main cached panel has only
    the focal SMA columns; the placebo panel has all of them).
    """
    wanted = []
    for spec in groups.values():
        for lookback in (spec["focal"], *spec["neighbors"]):
            col = dist_atr_column(spec["family"], lookback)
            if col in panel.columns and col not in wanted:
                wanted.append(col)
    return wanted


def add_context(panel: pd.DataFrame) -> pd.DataFrame:
    """`fwd_ret_21` plus the three C2 buckets (`mom_tercile`, `vol_tercile`,
    `rev_tercile`), exactly as `modules/slope_conditioner.py::prepare`
    builds them. Returns a new frame.
    """
    working = panel.copy()
    working[RETURN_OUTCOME] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    return working


def add_respect_columns(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS, groups: dict = GROUPS) -> pd.DataFrame:
    """`respect_support_<ma>` / `respect_resistance_<ma>` for every
    configured `dist_atr_*` column present in `panel`, under `params`
    (K/R/L). Existing respect columns are replaced, so a sensitivity
    variant can be layered onto an already-prepared panel. Returns a new
    frame; `panel` must be sorted by (ticker, date).
    """
    working = panel.drop(columns=[c for c in panel.columns if c.startswith("respect_")])
    pieces = [working]
    for col in configured_dist_atr_columns(working, groups):
        pieces.append(respect.respect_counts(
            working, col,
            confirm_window=params["confirm_window"],
            confirm_distance=params["confirm_distance"],
            history_window=params["history_window"],
        ))
    return pd.concat(pieces, axis=1)


def prepare(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS) -> pd.DataFrame:
    """Full single-argument preparation (the shape
    `tests/test_moving_averages_leakage.py` exercises on every module):
    context columns plus the primary-parameter respect columns.
    """
    return add_respect_columns(add_context(panel), params)


def group_touch_table(panel: pd.DataFrame, group_name: str, groups: dict = GROUPS) -> pd.DataFrame:
    """Pooled M5 touch events for one group -- focal (`is_focal=True`) and
    every neighbour (`is_focal=False`), each tagged with its own `ma_col`
    -- joined onto the touch row's own context columns. Respect is NOT
    attached here (see `attach_respect`) so the sensitivity variants can
    re-attach without re-detecting touches.
    """
    spec = groups[group_name]
    family = spec["family"]
    context_cols = ["ticker", "date", RETURN_OUTCOME, *C2_MATCH_COLS_WITH_REVERSAL]
    context = panel[context_cols].drop_duplicates(subset=["ticker", "date"])

    frames = []
    for lookback in (spec["focal"], *spec["neighbors"]):
        dist_col = dist_atr_column(family, lookback)
        events = touch_events(panel, dist_col)
        events["is_focal"] = lookback == spec["focal"]
        events["lookback"] = lookback
        events["ma_col"] = dist_col.removeprefix("dist_atr_")
        frames.append(events)

    pooled = pd.concat(frames, ignore_index=True)
    pooled = pooled.merge(context, on=["ticker", "date"], how="left")
    pooled[HOLD_OUTCOME] = pooled[HOLD_OUTCOME].astype(float)
    pooled["group"] = group_name
    return pooled


def attach_respect(events: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `respect` (same-side count at the touch row: `respect_support_
    <ma>` for a from-above touch, `respect_resistance_<ma>` for a
    from-below one), `respect_bucket` (0 / 1 / 2 meaning ">= 2") and
    `high_respect` (bool, NaN-masked where the count is undefined).
    Returns a new frame.
    """
    respect_cols = [c for c in panel.columns if c.startswith("respect_")]
    long = panel[["ticker", "date", *respect_cols]].melt(
        id_vars=["ticker", "date"], var_name="respect_col", value_name="respect"
    ).dropna(subset=["respect"])
    out = events.copy()
    side = np.where(out["direction"] == FROM_ABOVE, respect.SUPPORT, respect.RESISTANCE)
    out["respect_col"] = [respect.respect_column(ma, s) for ma, s in zip(out["ma_col"], side)]
    out = out.merge(long, on=["ticker", "date", "respect_col"], how="left")
    out["respect_bucket"] = out["respect"].clip(upper=HIGH_RESPECT_MIN)
    out["high_respect"] = (out["respect"] >= HIGH_RESPECT_MIN).astype("boolean").mask(out["respect"].isna())
    return out


def primary_population(events: pd.DataFrame, direction: str, value_col: str, match_cols: Iterable[str]) -> pd.DataFrame:
    """The rows one cell's contrast is computed on: this direction's
    touches with a defined outcome, defined respect, defined match
    columns, and a respect count of exactly 0 or >= 2 (the 1-bounce middle
    is excluded from the 0-vs->=2 contrast, per PREREGISTRATION.md).
    """
    subset = events[events["direction"] == direction].dropna(subset=[value_col, "respect", *match_cols])
    return subset[subset["respect_bucket"] != 1]


def _bootstrap_or_nan(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except InsufficientBlocksError:
        return {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "boot_std": float("nan"), "n_dates": 0, "n_boot": 0,
                "point_a": float("nan"), "point_b": float("nan"), "n_dates_a": 0, "n_dates_b": 0}


def did_cell(
    events: pd.DataFrame, direction: str, value_col: str, label: dict,
    tiers: dict = CONTROL_TIERS, block_length: int = BLOCK_LENGTH,
    n_boot: int = 500, ci: float = 0.90, seed: int = 0,
    panel_years: float | None = None, panel_tickers: int | None = None,
) -> dict:
    """One (group, direction, outcome) cell. Reports, per control tier, the
    real-minus-synthetic DiD (`did_<tier>`, CI, contributing dates) and
    each arm's own delta; the focal arm's own C2+rev delta with a CI (the
    tradeable quantity a cost annotation attaches to); effective N of the
    focal high-respect population; raw outcome means by arm x bucket
    (descriptive); and for the return outcome, DESIGN §6.11.1's shape
    fields plus the cost annotation (invariants #8, #10).
    """
    primary_cols = tiers[PRIMARY_TIER]
    population = primary_population(events, direction, value_col, primary_cols)
    focal = population[population["is_focal"]]
    synth = population[~population["is_focal"]]
    focal_high = focal[focal["high_respect"].astype(bool)]
    focal_low = focal[~focal["high_respect"].astype(bool)]

    row = {
        **label,
        "direction": direction,
        "outcome": value_col,
        "n_events": len(focal_high),
        "n_dates": focal_high["date"].nunique(),
        "n_tickers": focal_high["ticker"].nunique(),
        "n_focal_low": len(focal_low),
        "n_synth_high": int(synth["high_respect"].astype(bool).sum()),
        "n_synth_low": int((~synth["high_respect"].astype(bool)).sum()),
    }

    for tier, match_cols in tiers.items():
        pop = primary_population(events, direction, value_col, match_cols)
        boot = _bootstrap_or_nan(
            block_bootstrap_delta_diff,
            pop[pop["is_focal"]], pop[~pop["is_focal"]], "high_respect", value_col, list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
        row[f"did_{tier}"] = boot["point_estimate"]
        row[f"did_{tier}_ci_low"] = boot["ci_low"]
        row[f"did_{tier}_ci_high"] = boot["ci_high"]
        row[f"did_{tier}_n_dates"] = boot["n_dates"]
        row[f"delta_focal_{tier}"] = boot["point_a"]
        row[f"delta_synth_{tier}"] = boot["point_b"]
        row[f"delta_focal_{tier}_n_dates"] = boot["n_dates_a"]
        row[f"delta_synth_{tier}_n_dates"] = boot["n_dates_b"]

    focal_boot = _bootstrap_or_nan(
        block_bootstrap_delta, focal, "high_respect", value_col, list(primary_cols),
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    row["delta_focal_ci_low"] = focal_boot["ci_low"]
    row["delta_focal_ci_high"] = focal_boot["ci_high"]

    did_low, did_high = row[f"did_{PRIMARY_TIER}_ci_low"], row[f"did_{PRIMARY_TIER}_ci_high"]
    # Effective N is the number of dates that actually contribute a
    # matched focal high-vs-low contrast at the primary tier, not the raw
    # count of high-respect event dates (PREREGISTRATION.md: the sma200
    # cells were expected to sit at this floor from the feasibility count).
    row["below_threshold"] = bool(
        row["n_events"] < MIN_EVENTS or row["n_dates"] < MIN_DATES or row["n_tickers"] < MIN_TICKERS
        or row[f"delta_focal_{PRIMARY_TIER}_n_dates"] < MIN_DATES or pd.isna(did_low)
    )
    row["ci_excludes_zero"] = None if pd.isna(did_low) else not (did_low <= 0 <= did_high)
    row["sign"] = None if pd.isna(did_low) else int(np.sign(row[f"did_{PRIMARY_TIER}"]))

    # Descriptive raw means by arm x bucket (0 / 1 / >=2), all of this
    # direction's touches with a defined outcome and respect.
    everything = events[events["direction"] == direction].dropna(subset=[value_col, "respect"])
    means = everything.groupby(["is_focal", "respect_bucket"])[value_col].mean()
    for is_focal, arm in ((True, "focal"), (False, "synth")):
        for bucket in (0, 1, 2):
            row[f"mean_{arm}_r{bucket}"] = means.get((is_focal, float(bucket)), float("nan"))

    if value_col == RETURN_OUTCOME:
        shape = distribution_shape(focal_high[value_col]) if len(focal_high) else {}
        hits = hit_rate_deltas(focal, "high_respect", value_col, match_cols=list(primary_cols)) if len(focal) else {}
        row["hit_rate"] = hits.get("hit_rate", float("nan"))
        row["hit_rate_delta_c1"] = hits.get("hit_rate_delta_c1", float("nan"))
        row["hit_rate_delta_c2"] = hits.get("hit_rate_delta_c2", float("nan"))
        row["win_loss_ratio"] = shape.get("win_loss_ratio", float("nan"))
        row["skew"] = shape.get("skew", float("nan"))
        if panel_years and panel_tickers:
            # Tradeable signal = "touch of the real MA with >= 2 recent
            # confirmed bounces", one round trip per event.
            spy = len(focal_high) / (panel_years * panel_tickers)
            hurdle = cost_hurdle(spy, ROUND_TRIP_COST)
            point_ann = annualize(focal_boot["point_estimate"], horizon=HORIZON)
            low_ann = annualize(focal_boot["ci_low"], horizon=HORIZON)
            high_ann = annualize(focal_boot["ci_high"], horizon=HORIZON)
            row["signals_per_year"] = spy
            row["cost_hurdle_annual"] = hurdle
            row["delta_focal_annualized"] = point_ann
            row["delta_focal_ci_low_annualized"] = low_ann
            row["delta_focal_ci_high_annualized"] = high_ann
            row["point_clears_cost"] = point_clears_cost(point_ann, hurdle) if not pd.isna(point_ann) else None
            row["ci_clears_cost"] = ci_clears_cost(low_ann, high_ann, hurdle) if not pd.isna(low_ann) else None
    return row


def primary_cell_table(
    touch_tables: dict[str, pd.DataFrame], panel: pd.DataFrame,
    outcomes: tuple[str, ...] = (HOLD_OUTCOME, RETURN_OUTCOME), **kwargs,
) -> pd.DataFrame:
    """All primary cells: 4 groups x 2 directions x `outcomes`, on the
    primary K/R/L. `touch_tables` is `{group: group_touch_table(...)}`;
    `panel` must carry the primary-parameter respect columns.
    """
    years = (panel["date"].max() - panel["date"].min()).days / 365.25
    n_tickers = panel["ticker"].nunique()
    rows = []
    for group_name in GROUP_ORDER:
        events = attach_respect(touch_tables[group_name], panel)
        for outcome in outcomes:
            for direction in DIRECTIONS:
                rows.append(did_cell(
                    events, direction, outcome, {"group": group_name, "variant": "primary"},
                    panel_years=years, panel_tickers=n_tickers, **kwargs,
                ))
    return pd.DataFrame(rows)


def sensitivity_cell_table(
    touch_tables: dict[str, pd.DataFrame], context_panel: pd.DataFrame,
    variants: dict = SENSITIVITY_VARIANTS, **kwargs,
) -> pd.DataFrame:
    """The 6 one-at-a-time K/R/L perturbations x 8 hold cells, primary
    control tier only. `context_panel` is `add_context(...)`'s output (no
    respect columns needed -- each variant adds its own).
    """
    rows = []
    for variant_name, params in variants.items():
        panel = add_respect_columns(context_panel, params)
        for group_name in GROUP_ORDER:
            events = attach_respect(touch_tables[group_name], panel)
            for direction in DIRECTIONS:
                rows.append(did_cell(
                    events, direction, HOLD_OUTCOME, {"group": group_name, "variant": variant_name},
                    tiers={PRIMARY_TIER: CONTROL_TIERS[PRIMARY_TIER]}, **kwargs,
                ))
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame, sensitivity: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M19 kill criterion on the 8 primary hold cells.
    A cell is *confirmed* iff (i) its primary-tier DiD CI excludes zero and
    is positive, (ii) plateau: at least `PLATEAU_MIN_AGREEING_MAS` of the
    other 3 MAs in the same direction have a same-signed DiD point
    estimate, (iii) sensitivity: all 6 perturbations keep the sign and at
    least `SENSITIVITY_MIN_CI_EXCLUDING` of them keep the CI excluding
    zero. Module killed iff no cell is confirmed. A verdict on the
    construction, not a tier (DESIGN §9.2's 2026-09-10 rule).
    """
    hold = primary[primary["outcome"] == HOLD_OUTCOME].copy()
    did_col, low_col, high_col = f"did_{PRIMARY_TIER}", f"did_{PRIMARY_TIER}_ci_low", f"did_{PRIMARY_TIER}_ci_high"
    cells = []
    for _, cell in hold.iterrows():
        positive_and_clear = bool(cell["ci_excludes_zero"]) and cell[did_col] > 0
        others = hold[(hold["direction"] == cell["direction"]) & (hold["group"] != cell["group"])]
        agreeing = int((np.sign(others[did_col]) == np.sign(cell[did_col])).sum())
        plateau_pass = agreeing >= PLATEAU_MIN_AGREEING_MAS

        variants = sensitivity[(sensitivity["group"] == cell["group"]) & (sensitivity["direction"] == cell["direction"])]
        same_sign = bool((np.sign(variants[did_col]) == np.sign(cell[did_col])).all()) if len(variants) else False
        n_excluding = int((
            (np.sign(variants[low_col]) == np.sign(variants[high_col]))
            & (np.sign(variants[did_col]) == np.sign(cell[did_col]))
        ).sum()) if len(variants) else 0
        sensitivity_pass = same_sign and n_excluding >= SENSITIVITY_MIN_CI_EXCLUDING and len(variants) == len(SENSITIVITY_VARIANTS)

        cells.append({
            "group": cell["group"], "direction": cell["direction"],
            "did": cell[did_col], "ci_low": cell[low_col], "ci_high": cell[high_col],
            "below_threshold": bool(cell["below_threshold"]),
            "positive_and_ci_excludes_zero": positive_and_clear,
            "n_other_mas_agreeing": agreeing, "plateau_pass": plateau_pass,
            "sensitivity_same_sign": same_sign, "sensitivity_n_ci_excluding": n_excluding,
            "sensitivity_pass": sensitivity_pass,
            "confirmed": positive_and_clear and plateau_pass and sensitivity_pass and not bool(cell["below_threshold"]),
        })
    table = pd.DataFrame(cells)
    return {
        "cells": table,
        "n_cells": len(table),
        "n_confirmed": int(table["confirmed"].sum()) if len(table) else 0,
        "module_killed": bool(not table["confirmed"].any()) if len(table) else True,
    }
