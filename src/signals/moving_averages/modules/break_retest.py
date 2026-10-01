"""M22 -- Break and retest (DESIGN.md M22; PREREGISTRATION.md, 2026-10-01).
Post-termination module under DESIGN §1.5's porous-scope rule.

Track B. The practitioner pattern: price breaks through the MA (M21's
confirmed break), comes back to it from the new side within W days (the
retest), and bounces (M20's confirmed bounce) -- "old resistance became
support". The entry is the retest bounce's confirmation row.

M20 found an ordinary confirmed bounce carries the forward return of any
same-size move. M22's question is whether a bounce that is a *retest* of a
fresh break behaves differently from an ordinary bounce. Primary statistic
per cell:

    DiD = delta_retest - delta_plain_bounce

each a date + C2 + rev_tercile matched delta on `fwd_ret_h` against the same
base controls, shared date blocks. "Plain bounce" = M20's bounce flag, same
MA and direction, minus the retest rows. The M20/M21 generic-move DiD is
reported as a secondary, uncounted column.

The synthetic-neighbour arm is not run: M20/M21 showed 74-96% of focal
events coincide with a neighbour event, making it uninformative by
construction (PREREGISTRATION.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import respect
from src.signals.moving_averages.features.placebo_ma import dist_atr_column
from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW
from src.signals.moving_averages.modules import bounce_entry as be
from src.signals.moving_averages.modules.respect_history import (
    C2_MATCH_COLS_WITH_REVERSAL,
    CONTROL_TIERS,
    GROUP_ORDER,
    GROUPS,
    PRIMARY_TIER,
    ROUND_TRIP_COST,
)
from src.signals.moving_averages.stats.costs import annualize, ci_clears_cost, cost_hurdle, point_clears_cost
from src.signals.moving_averages.stats.inference import block_bootstrap_delta, block_bootstrap_delta_diff
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

HORIZONS = be.HORIZONS
DIRECTIONS = (respect.BREAK_ABOVE, respect.BREAK_BELOW)
HYPOTHESISED_SIGN = {respect.BREAK_ABOVE: 1, respect.BREAK_BELOW: -1}
BOUNCE_DIRECTION = {respect.BREAK_ABOVE: FROM_ABOVE, respect.BREAK_BELOW: FROM_BELOW}

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30
N_BOOT = 500

PRIMARY_PARAMS = {
    "confirm_window": respect.CONFIRM_WINDOW,
    "confirm_distance": respect.CONFIRM_DISTANCE,
    "retest_window": respect.RETEST_WINDOW,
}
SENSITIVITY_VARIANTS = {
    "K=4": {**PRIMARY_PARAMS, "confirm_window": 4},
    "K=6": {**PRIMARY_PARAMS, "confirm_window": 6},
    "R=0.75": {**PRIMARY_PARAMS, "confirm_distance": 0.75},
    "R=1.25": {**PRIMARY_PARAMS, "confirm_distance": 1.25},
    "W=16": {**PRIMARY_PARAMS, "retest_window": 16},
    "W=26": {**PRIMARY_PARAMS, "retest_window": 26},
}
SENSITIVITY_MIN_CI_EXCLUDING = 5   # of 6, M19's rule for six variants
PLATEAU_MIN_AGREEING_MAS = 2


def retest_col(ma_col: str, direction: str) -> str:
    return f"retest_{ma_col}_{direction}"


def plain_bounce_col(ma_col: str, direction: str) -> str:
    return f"plain_bounce_{ma_col}_{direction}"


def _focal_columns(panel: pd.DataFrame, groups: dict = GROUPS) -> list[str]:
    cols = [dist_atr_column(spec["family"], spec["focal"]) for spec in groups.values()]
    return [c for c in cols if c in panel.columns]


def add_event_flags(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS, groups: dict = GROUPS) -> pd.DataFrame:
    """Retest, plain-bounce and generic-move flags for every focal MA column
    present (neighbours are not needed). Existing flag columns are replaced.
    Returns a new frame; `panel` must be sorted by (ticker, date)."""
    working = panel.drop(columns=[c for c in panel.columns
                                  if c.startswith(("retest_", "plain_bounce_", "generic_move_"))])
    pieces = [working]
    k, r, w = params["confirm_window"], params["confirm_distance"], params["retest_window"]
    for col in _focal_columns(working, groups):
        ma_col = col.removeprefix("dist_atr_")
        bounces = respect.bounce_flags(working, col, confirm_window=k, confirm_distance=r)
        retests = respect.retest_flags(working, col, confirm_window=k, confirm_distance=r, retest_window=w)
        plain = {}
        for direction in DIRECTIONS:
            bounce = bounces[f"bounce_{ma_col}_{BOUNCE_DIRECTION[direction]}"]
            retest = retests[retest_col(ma_col, direction)]
            plain[plain_bounce_col(ma_col, direction)] = (bounce & ~retest.fillna(False)).astype("boolean")
        pieces += [retests, pd.DataFrame(plain, index=working.index)]
        if "atr_14" in working.columns and "close" in working.columns:
            pieces.append(be.generic_move_flags(working, col, {"confirm_window": k, "confirm_distance": r}))
    return pd.concat(pieces, axis=1)


def prepare(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS) -> pd.DataFrame:
    """Single-argument preparation (the shape the leakage test exercises)."""
    return add_event_flags(be.add_context(panel), params)


def _arms(panel: pd.DataFrame, group_name: str, direction: str, groups: dict = GROUPS):
    spec = groups[group_name]
    ma_col = dist_atr_column(spec["family"], spec["focal"]).removeprefix("dist_atr_")
    retest = panel[retest_col(ma_col, direction)].fillna(False).astype(bool)
    plain = panel[plain_bounce_col(ma_col, direction)].fillna(False).astype(bool)
    generic = panel[be.generic_col(ma_col, BOUNCE_DIRECTION[direction])].fillna(False).astype(bool)
    base = ~(retest | plain | generic)
    return retest, plain, generic, base


def did_cell(
    panel: pd.DataFrame, group_name: str, direction: str, horizon: int, label: dict,
    tiers: dict = CONTROL_TIERS, n_boot: int = N_BOOT, ci: float = 0.90, seed: int = 0,
    panel_years: float | None = None, panel_tickers: int | None = None, with_generic: bool = True,
) -> dict:
    """One (group, direction, horizon) cell. `panel` must carry the event
    flags for the params in play plus the context columns."""
    value_col = be.fwd_col(horizon)
    retest, plain, generic, base = _arms(panel, group_name, direction)
    block_length = be.block_length_for(horizon)
    needed = ["ticker", "date", value_col, *C2_MATCH_COLS_WITH_REVERSAL]
    events = panel.loc[retest, needed].dropna(subset=[value_col])
    pa = panel.loc[base | retest, needed].assign(__event=retest[base | retest].to_numpy())
    pp = panel.loc[base | plain, needed].assign(__event=plain[base | plain].to_numpy())

    row = {
        **label, "group": group_name, "direction": direction, "horizon": horizon,
        "n_events": len(events), "n_dates": events["date"].nunique(), "n_tickers": events["ticker"].nunique(),
        "n_plain": int((plain & panel[value_col].notna()).sum()),
        "n_generic": int((generic & panel[value_col].notna()).sum()),
        "retest_share_of_bounces": float(retest.sum() / (retest.sum() + plain.sum())) if (retest.sum() + plain.sum()) else float("nan"),
    }
    for tier, match_cols in tiers.items():
        boot = be._bootstrap_or_nan(
            block_bootstrap_delta_diff, pa, pp, "__event", value_col, list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
        row[f"did_{tier}"] = boot["point_estimate"]
        row[f"did_{tier}_ci_low"] = boot["ci_low"]
        row[f"did_{tier}_ci_high"] = boot["ci_high"]
        row[f"did_{tier}_n_dates"] = boot["n_dates"]
        row[f"delta_focal_{tier}"] = boot["point_a"]
        row[f"delta_plain_{tier}"] = boot["point_b"]
        row[f"delta_focal_{tier}_n_dates"] = boot["n_dates_a"]
        row[f"delta_plain_{tier}_n_dates"] = boot["n_dates_b"]

    primary_cols = list(tiers[PRIMARY_TIER])
    focal_boot = be._bootstrap_or_nan(
        block_bootstrap_delta, pa, "__event", value_col, primary_cols,
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    row["delta_focal_ci_low"] = focal_boot["ci_low"]
    row["delta_focal_ci_high"] = focal_boot["ci_high"]

    if with_generic:
        pg = panel.loc[base | generic, needed].assign(__event=generic[base | generic].to_numpy())
        gboot = be._bootstrap_or_nan(
            block_bootstrap_delta_diff, pa, pg, "__event", value_col, primary_cols,
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
        row["did_generic"] = gboot["point_estimate"]
        row["did_generic_ci_low"] = gboot["ci_low"]
        row["did_generic_ci_high"] = gboot["ci_high"]
        row["delta_generic"] = gboot["point_b"]

    sign = HYPOTHESISED_SIGN[direction]
    did_low, did_high = row[f"did_{PRIMARY_TIER}_ci_low"], row[f"did_{PRIMARY_TIER}_ci_high"]
    row["below_threshold"] = bool(
        row["n_events"] < MIN_EVENTS or row["n_dates"] < MIN_DATES or row["n_tickers"] < MIN_TICKERS
        or row[f"delta_focal_{PRIMARY_TIER}_n_dates"] < MIN_DATES or pd.isna(did_low)
    )
    row["did_ci_excludes_zero"] = None if pd.isna(did_low) else not (did_low <= 0 <= did_high)
    row["focal_ci_excludes_zero"] = (
        None if pd.isna(focal_boot["ci_low"]) else not (focal_boot["ci_low"] <= 0 <= focal_boot["ci_high"])
    )
    row["did_hypothesised_direction"] = None if pd.isna(did_low) else bool(np.sign(row[f"did_{PRIMARY_TIER}"]) == sign)
    row["focal_hypothesised_direction"] = (
        None if pd.isna(focal_boot["point_estimate"]) else bool(np.sign(focal_boot["point_estimate"]) == sign)
    )

    row["mean_focal"] = events[value_col].mean() if len(events) else float("nan")
    row["mean_plain"] = panel.loc[plain, value_col].mean()
    row["mean_generic"] = panel.loc[generic, value_col].mean()
    row["mean_base"] = panel.loc[base, value_col].mean()
    shape = distribution_shape(events[value_col]) if len(events) else {}
    hits = hit_rate_deltas(pa, "__event", value_col, match_cols=primary_cols) if len(events) else {}
    row["hit_rate"] = hits.get("hit_rate", float("nan"))
    row["hit_rate_delta_c1"] = hits.get("hit_rate_delta_c1", float("nan"))
    row["hit_rate_delta_c2"] = hits.get("hit_rate_delta_c2", float("nan"))
    row["win_loss_ratio"] = shape.get("win_loss_ratio", float("nan"))
    row["skew"] = shape.get("skew", float("nan"))
    if panel_years and panel_tickers:
        spy = len(events) / (panel_years * panel_tickers)
        hurdle = cost_hurdle(spy, ROUND_TRIP_COST)
        point_ann = annualize(focal_boot["point_estimate"], horizon=horizon)
        low_ann = annualize(focal_boot["ci_low"], horizon=horizon)
        high_ann = annualize(focal_boot["ci_high"], horizon=horizon)
        row["signals_per_year"] = spy
        row["cost_hurdle_annual"] = hurdle
        row["delta_focal_annualized"] = point_ann
        row["delta_focal_ci_low_annualized"] = low_ann
        row["delta_focal_ci_high_annualized"] = high_ann
        row["point_clears_cost"] = point_clears_cost(point_ann, hurdle) if not pd.isna(point_ann) else None
        row["ci_clears_cost"] = ci_clears_cost(low_ann, high_ann, hurdle) if not pd.isna(low_ann) else None
    return row


def primary_cell_table(panel: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """32 primary cells: 4 MAs x 2 directions x 4 horizons."""
    years = (panel["date"].max() - panel["date"].min()).days / 365.25
    n_tickers = panel["ticker"].nunique()
    return pd.DataFrame([
        did_cell(panel, g, d, h, {"variant": "primary"}, panel_years=years, panel_tickers=n_tickers, **kwargs)
        for g in GROUP_ORDER for d in DIRECTIONS for h in HORIZONS
    ])


def sensitivity_cell_table(context_panel: pd.DataFrame, variants: dict = SENSITIVITY_VARIANTS, **kwargs) -> pd.DataFrame:
    """6 one-at-a-time K/R/W perturbations x 32 cells, primary tier only, no
    generic arm. `context_panel` is `bounce_entry.add_context(...)`'s output."""
    rows = []
    for variant_name, params in variants.items():
        panel = add_event_flags(context_panel, params)
        for g in GROUP_ORDER:
            for d in DIRECTIONS:
                for h in HORIZONS:
                    rows.append(did_cell(panel, g, d, h, {"variant": variant_name},
                                         tiers={PRIMARY_TIER: CONTROL_TIERS[PRIMARY_TIER]}, with_generic=False, **kwargs))
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame, sensitivity: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M22 kill criterion. Confirmed iff (1) the retest
    delta's C2+rev CI excludes zero in the hypothesised direction, (2) the
    DiD vs plain bounce does too, (3) adjacent horizons' DiDs share its sign,
    (4) >= 2 of the other 3 MAs share its sign at that direction/horizon,
    (5) all 6 K/R/W perturbations keep the sign and >= 5 keep the CI off
    zero, (6) not below the effective-N floor. Module killed iff no cell is
    confirmed."""
    did_col, low_col, high_col = f"did_{PRIMARY_TIER}", f"did_{PRIMARY_TIER}_ci_low", f"did_{PRIMARY_TIER}_ci_high"
    cells = []
    for _, cell in primary.iterrows():
        gate_focal = bool(cell["focal_ci_excludes_zero"]) and bool(cell["focal_hypothesised_direction"])
        gate_did = bool(cell["did_ci_excludes_zero"]) and bool(cell["did_hypothesised_direction"])
        same = primary[(primary["group"] == cell["group"]) & (primary["direction"] == cell["direction"])]
        idx = HORIZONS.index(int(cell["horizon"]))
        adjacent = [HORIZONS[i] for i in (idx - 1, idx + 1) if 0 <= i < len(HORIZONS)]
        adj = same[same["horizon"].isin(adjacent)][did_col]
        term_pass = bool((np.sign(adj) == np.sign(cell[did_col])).all()) if len(adj) else False
        others = primary[(primary["direction"] == cell["direction"]) & (primary["horizon"] == cell["horizon"])
                         & (primary["group"] != cell["group"])]
        agreeing = int((np.sign(others[did_col]) == np.sign(cell[did_col])).sum())
        variants = sensitivity[(sensitivity["group"] == cell["group"]) & (sensitivity["direction"] == cell["direction"])
                               & (sensitivity["horizon"] == cell["horizon"])]
        same_sign = bool((np.sign(variants[did_col]) == np.sign(cell[did_col])).all()) if len(variants) else False
        n_excl = int(((np.sign(variants[low_col]) == np.sign(variants[high_col]))
                      & (np.sign(variants[did_col]) == np.sign(cell[did_col]))).sum()) if len(variants) else 0
        sens_pass = same_sign and n_excl >= SENSITIVITY_MIN_CI_EXCLUDING and len(variants) == len(SENSITIVITY_VARIANTS)
        below = bool(cell["below_threshold"])
        cells.append({
            "group": cell["group"], "direction": cell["direction"], "horizon": int(cell["horizon"]),
            "delta_focal": cell[f"delta_focal_{PRIMARY_TIER}"], "did": cell[did_col],
            "did_ci_low": cell[low_col], "did_ci_high": cell[high_col], "below_threshold": below,
            "focal_gate": gate_focal, "did_gate": gate_did, "term_structure_pass": term_pass,
            "n_other_mas_agreeing": agreeing, "ma_plateau_pass": agreeing >= PLATEAU_MIN_AGREEING_MAS,
            "sensitivity_same_sign": same_sign, "sensitivity_n_ci_excluding": n_excl, "sensitivity_pass": sens_pass,
            "confirmed": gate_focal and gate_did and term_pass and agreeing >= PLATEAU_MIN_AGREEING_MAS
                         and sens_pass and not below,
        })
    table = pd.DataFrame(cells)
    return {"cells": table, "n_cells": len(table),
            "n_confirmed": int(table["confirmed"].sum()) if len(table) else 0,
            "module_killed": bool(not table["confirmed"].any()) if len(table) else True}
