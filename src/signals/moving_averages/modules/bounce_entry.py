"""M20 -- Confirmed bounce as an entry signal (DESIGN.md M20;
PREREGISTRATION.md, 2026-09-30). Post-termination module under DESIGN §1.5's
porous-scope rule.

Track B. Price touches the MA from above on day d and is back >= R ATR above
it within K days without closing through (M19's *confirmed reversal*,
`features/respect.py`). Is that, on the day it confirms, a signal for the
next X days? M19 used the confirmed reversal as a *past feature* of the next
touch; M5 used the bounce as an *outcome*. Neither measured forward return
from the confirmation day itself.

Event: the confirmation row c (`features/respect.py::bounce_flags`), known
on its own tradeable day. Outcome: `fwd_ret_h`, h in HORIZONS, from row c.

Two controls, because "up >= 1 ATR in <= 5 days" is by itself a short-term
move regardless of any MA:
- **Generic same-size move, no MA involved** (the primary placebo arm):
  rows on the same side of the focal MA whose lagged close rose (fell) by
  >= R ATR over some j <= K prior rows, and whose focal-MA |dist_atr| stayed
  > TOUCH_THRESHOLD over the previous K+1 rows (no recent touch). The
  primary statistic is the difference-in-differences
  `delta_focal - delta_generic`, each a date + C2 + rev_tercile matched
  delta against the same base-control rows.
- **§7.5 synthetic neighbours** (secondary, descriptive): a confirmed bounce
  off SMA47/53 etc. Reported with the share of focal event rows that are
  also neighbour event rows -- near-identical MAs confirm on the same day
  most of the time, so this DiD is near zero by construction and cannot
  carry the kill criterion (recorded in PREREGISTRATION.md before running).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import respect, touch
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.features.placebo_ma import dist_atr_column
from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.respect_history import (
    C2_MATCH_COLS,
    C2_MATCH_COLS_WITH_REVERSAL,
    CONTROL_TIERS,
    GROUP_ORDER,
    GROUPS,
    PRIMARY_TIER,
    ROUND_TRIP_COST,
    configured_dist_atr_columns,
)
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import annualize, ci_clears_cost, cost_hurdle, point_clears_cost
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
    block_bootstrap_delta_diff,
)
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

HORIZONS = (5, 10, 21, 63)
DIRECTIONS = (FROM_ABOVE, FROM_BELOW)
# Hypothesised sign of the forward return: continuation of the bounce.
HYPOTHESISED_SIGN = {FROM_ABOVE: 1, FROM_BELOW: -1}

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

PRIMARY_PARAMS = {"confirm_window": respect.CONFIRM_WINDOW, "confirm_distance": respect.CONFIRM_DISTANCE}
SENSITIVITY_VARIANTS = {
    "K=4": {**PRIMARY_PARAMS, "confirm_window": 4},
    "K=6": {**PRIMARY_PARAMS, "confirm_window": 6},
    "R=0.75": {**PRIMARY_PARAMS, "confirm_distance": 0.75},
    "R=1.25": {**PRIMARY_PARAMS, "confirm_distance": 1.25},
}
SENSITIVITY_MIN_CI_EXCLUDING = 3   # of 4
PLATEAU_MIN_AGREEING_MAS = 2       # of the other 3 MAs, same direction and horizon
N_BOOT = 500


def fwd_col(horizon: int) -> str:
    return f"fwd_ret_{horizon}"


def bounce_col(ma_col: str, direction: str) -> str:
    return f"bounce_{ma_col}_{direction}"


def generic_col(ma_col: str, direction: str) -> str:
    return f"generic_move_{ma_col}_{direction}"


def block_length_for(horizon: int) -> int:
    """DESIGN §6.2: block length >= 2x horizon (M11/M18's convention), never
    below M5's 10-row floor for sparse events.
    """
    return max(10, 2 * horizon)


def add_context(panel: pd.DataFrame) -> pd.DataFrame:
    """Forward returns at every horizon plus the C2 buckets. Returns a new
    frame."""
    working = panel.copy()
    for h in HORIZONS:
        working[fwd_col(h)] = forward_return(working, horizon=h)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    return working


def generic_move_flags(
    panel: pd.DataFrame, dist_atr_col: str, params: dict = PRIMARY_PARAMS,
    ticker_col: str = "ticker",
) -> pd.DataFrame:
    """The no-MA placebo: on row c, the lagged close moved >= R ATR in the
    direction of a bounce over some j <= K prior rows, price sits on the
    bounce's side of the focal MA now, and |dist_atr| of that MA stayed
    above the touch band over the previous K+1 rows (so no touch, hence no
    bounce, was possible). Everything is lagged one bar via `apply_lag`,
    same footing as the features. NaN where `dist_atr` is NaN.
    """
    k, r = params["confirm_window"], params["confirm_distance"]
    ma_col = dist_atr_col.removeprefix("dist_atr_")
    lagged = apply_lag(panel[[ticker_col, "close"]], ["close"])["close"]
    atr = panel["atr_14"]   # already lagged in the placebo/main panel
    by_ticker = pd.DataFrame({ticker_col: panel[ticker_col], "_c": lagged}).groupby(ticker_col)["_c"]
    up = np.zeros(len(panel), dtype=bool)
    down = np.zeros(len(panel), dtype=bool)
    for j in range(1, k + 1):
        move = ((lagged - by_ticker.shift(j)) / atr).to_numpy()
        up |= move >= r
        down |= move <= -r
    dist = panel[dist_atr_col]
    no_recent_touch = (
        dist.abs().groupby(panel[ticker_col]).transform(lambda s: s.rolling(k + 1, min_periods=k + 1).min())
        > touch.TOUCH_THRESHOLD
    ).to_numpy()
    defined = dist.notna().to_numpy() & atr.notna().to_numpy() & lagged.notna().to_numpy()
    above_side = (dist > 0).to_numpy()
    out = pd.DataFrame({
        generic_col(ma_col, FROM_ABOVE): pd.array(up & above_side & no_recent_touch, dtype="boolean"),
        generic_col(ma_col, FROM_BELOW): pd.array(down & ~above_side & no_recent_touch, dtype="boolean"),
    }, index=panel.index)
    return out.mask(np.repeat((~defined)[:, None], out.shape[1], axis=1))


def add_event_flags(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS, groups: dict = GROUPS) -> pd.DataFrame:
    """Bounce flags for every configured `dist_atr_*` column present, and
    generic-move flags for the focal columns. Existing flag columns are
    replaced so a sensitivity variant can be layered on. Returns a new frame.
    """
    working = panel.drop(columns=[c for c in panel.columns if c.startswith(("bounce_", "generic_move_"))])
    pieces = [working]
    focal_cols = {dist_atr_column(spec["family"], spec["focal"]) for spec in groups.values()}
    for col in configured_dist_atr_columns(working, groups):
        pieces.append(respect.bounce_flags(working, col, confirm_window=params["confirm_window"],
                                           confirm_distance=params["confirm_distance"]))
        if col in focal_cols and "atr_14" in working.columns and "close" in working.columns:
            pieces.append(generic_move_flags(working, col, params))
    return pd.concat(pieces, axis=1)


def prepare(panel: pd.DataFrame, params: dict = PRIMARY_PARAMS) -> pd.DataFrame:
    """Single-argument preparation (the shape the leakage test exercises)."""
    return add_event_flags(add_context(panel), params)


def _bootstrap_or_nan(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except InsufficientBlocksError:
        return {"point_estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "boot_std": float("nan"), "n_dates": 0, "n_boot": 0,
                "point_a": float("nan"), "point_b": float("nan"), "n_dates_a": 0, "n_dates_b": 0}


def _arm_panels(panel: pd.DataFrame, group_name: str, direction: str, groups: dict = GROUPS):
    """Row populations for one (group, direction): focal bounce flag,
    generic-move flag, pooled neighbour bounce flag, and the base controls
    (rows that are none of the three). Each arm's test panel is base
    controls plus that arm's events."""
    spec = groups[group_name]
    focal_ma = dist_atr_column(spec["family"], spec["focal"]).removeprefix("dist_atr_")
    focal = panel[bounce_col(focal_ma, direction)].fillna(False).astype(bool)
    generic = panel[generic_col(focal_ma, direction)].fillna(False).astype(bool)
    synth = np.zeros(len(panel), dtype=bool)
    for nb in spec["neighbors"]:
        nb_ma = dist_atr_column(spec["family"], nb).removeprefix("dist_atr_")
        synth |= panel[bounce_col(nb_ma, direction)].fillna(False).astype(bool).to_numpy()
    synth = pd.Series(synth, index=panel.index)
    base = ~(focal | generic | synth)
    return focal, generic, synth, base


def did_cell(
    panel: pd.DataFrame, group_name: str, direction: str, horizon: int, label: dict,
    tiers: dict = CONTROL_TIERS, n_boot: int = N_BOOT, ci: float = 0.90, seed: int = 0,
    panel_years: float | None = None, panel_tickers: int | None = None,
    with_synth: bool = True,
) -> dict:
    """One (group, direction, horizon) cell. `panel` must already carry the
    event flags for the params in play plus the context columns."""
    value_col = fwd_col(horizon)
    focal, generic, synth, base = _arm_panels(panel, group_name, direction)
    primary_cols = list(tiers[PRIMARY_TIER])
    block_length = block_length_for(horizon)

    needed = ["ticker", "date", value_col, *C2_MATCH_COLS_WITH_REVERSAL]
    events = panel.loc[focal, needed].dropna(subset=[value_col])
    row = {
        **label, "group": group_name, "direction": direction, "horizon": horizon,
        "n_events": len(events), "n_dates": events["date"].nunique(), "n_tickers": events["ticker"].nunique(),
        "n_generic": int((generic & panel[value_col].notna()).sum()),
        "n_synth": int((synth & panel[value_col].notna()).sum()),
        "focal_also_synth_share": float((focal & synth).sum() / focal.sum()) if focal.sum() else float("nan"),
    }

    for tier, match_cols in tiers.items():
        pa = panel.loc[base | focal, needed].assign(__event=focal[base | focal].to_numpy())
        pb = panel.loc[base | generic, needed].assign(__event=generic[base | generic].to_numpy())
        boot = _bootstrap_or_nan(
            block_bootstrap_delta_diff, pa, pb, "__event", value_col, list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
        row[f"did_{tier}"] = boot["point_estimate"]
        row[f"did_{tier}_ci_low"] = boot["ci_low"]
        row[f"did_{tier}_ci_high"] = boot["ci_high"]
        row[f"did_{tier}_n_dates"] = boot["n_dates"]
        row[f"delta_focal_{tier}"] = boot["point_a"]
        row[f"delta_generic_{tier}"] = boot["point_b"]
        row[f"delta_focal_{tier}_n_dates"] = boot["n_dates_a"]
        row[f"delta_generic_{tier}_n_dates"] = boot["n_dates_b"]

    pa = panel.loc[base | focal, needed].assign(__event=focal[base | focal].to_numpy())
    focal_boot = _bootstrap_or_nan(
        block_bootstrap_delta, pa, "__event", value_col, primary_cols,
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    row["delta_focal_ci_low"] = focal_boot["ci_low"]
    row["delta_focal_ci_high"] = focal_boot["ci_high"]

    if with_synth:
        ps = panel.loc[base | synth, needed].assign(__event=synth[base | synth].to_numpy())
        synth_boot = _bootstrap_or_nan(
            block_bootstrap_delta_diff, pa, ps, "__event", value_col, primary_cols,
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
        row["did_synth"] = synth_boot["point_estimate"]
        row["did_synth_ci_low"] = synth_boot["ci_low"]
        row["did_synth_ci_high"] = synth_boot["ci_high"]
        row["delta_synth_c2_rev"] = synth_boot["point_b"]

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
    row["did_hypothesised_direction"] = (
        None if pd.isna(did_low) else bool(np.sign(row[f"did_{PRIMARY_TIER}"]) == sign)
    )
    row["focal_hypothesised_direction"] = (
        None if pd.isna(focal_boot["point_estimate"]) else bool(np.sign(focal_boot["point_estimate"]) == sign)
    )

    # Descriptive: raw means, shape (invariant #10) and cost (invariant #8).
    row["mean_focal"] = events[value_col].mean() if len(events) else float("nan")
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
    """All 32 primary cells: 4 groups x 2 directions x 4 horizons, on the
    primary K/R. `panel` must be `prepare()`'d."""
    years = (panel["date"].max() - panel["date"].min()).days / 365.25
    n_tickers = panel["ticker"].nunique()
    rows = []
    for group_name in GROUP_ORDER:
        for direction in DIRECTIONS:
            for horizon in HORIZONS:
                rows.append(did_cell(panel, group_name, direction, horizon, {"variant": "primary"},
                                     panel_years=years, panel_tickers=n_tickers, **kwargs))
    return pd.DataFrame(rows)


def sensitivity_cell_table(context_panel: pd.DataFrame, variants: dict = SENSITIVITY_VARIANTS, **kwargs) -> pd.DataFrame:
    """4 one-at-a-time K/R perturbations x 32 cells, primary tier only, no
    synthetic arm. `context_panel` is `add_context(...)`'s output."""
    rows = []
    for variant_name, params in variants.items():
        panel = add_event_flags(context_panel, params)
        for group_name in GROUP_ORDER:
            for direction in DIRECTIONS:
                for horizon in HORIZONS:
                    rows.append(did_cell(panel, group_name, direction, horizon, {"variant": variant_name},
                                         tiers={PRIMARY_TIER: CONTROL_TIERS[PRIMARY_TIER]}, with_synth=False, **kwargs))
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame, sensitivity: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M20 kill criterion. A cell is confirmed iff (1)
    the focal delta's C2+rev CI excludes zero in the hypothesised direction,
    (2) the DiD vs the generic move does too, (3) term-structure plateau:
    every adjacent horizon's DiD has the same sign, (4) MA plateau: >= 2 of
    the other 3 MAs same-signed at that direction/horizon, (5) sensitivity:
    all 4 K/R perturbations keep the DiD sign and >= 3 keep its CI off
    zero, (6) not below the effective-N floor. Module killed iff no cell is
    confirmed. A verdict on the construction, not a tier (DESIGN §9.2)."""
    did_col, low_col, high_col = f"did_{PRIMARY_TIER}", f"did_{PRIMARY_TIER}_ci_low", f"did_{PRIMARY_TIER}_ci_high"
    cells = []
    for _, cell in primary.iterrows():
        sign = HYPOTHESISED_SIGN[cell["direction"]]
        gate_focal = bool(cell["focal_ci_excludes_zero"]) and bool(cell["focal_hypothesised_direction"])
        gate_did = bool(cell["did_ci_excludes_zero"]) and bool(cell["did_hypothesised_direction"])
        same = primary[(primary["group"] == cell["group"]) & (primary["direction"] == cell["direction"])]
        idx = HORIZONS.index(int(cell["horizon"]))
        adjacent = [HORIZONS[i] for i in (idx - 1, idx + 1) if 0 <= i < len(HORIZONS)]
        adj_signs = same[same["horizon"].isin(adjacent)][did_col]
        term_pass = bool((np.sign(adj_signs) == np.sign(cell[did_col])).all()) if len(adj_signs) else False
        others = primary[(primary["direction"] == cell["direction"]) & (primary["horizon"] == cell["horizon"])
                         & (primary["group"] != cell["group"])]
        agreeing = int((np.sign(others[did_col]) == np.sign(cell[did_col])).sum())
        variants = sensitivity[(sensitivity["group"] == cell["group"]) & (sensitivity["direction"] == cell["direction"])
                               & (sensitivity["horizon"] == cell["horizon"])]
        same_sign = bool((np.sign(variants[did_col]) == np.sign(cell[did_col])).all()) if len(variants) else False
        n_excl = int(((np.sign(variants[low_col]) == np.sign(variants[high_col]))
                      & (np.sign(variants[did_col]) == np.sign(cell[did_col]))).sum()) if len(variants) else 0
        sens_pass = same_sign and n_excl >= SENSITIVITY_MIN_CI_EXCLUDING and len(variants) == len(SENSITIVITY_VARIANTS)
        cells.append({
            "group": cell["group"], "direction": cell["direction"], "horizon": int(cell["horizon"]),
            "delta_focal": cell[f"delta_focal_{PRIMARY_TIER}"], "did": cell[did_col],
            "did_ci_low": cell[low_col], "did_ci_high": cell[high_col],
            "below_threshold": bool(cell["below_threshold"]),
            "focal_gate": gate_focal, "did_gate": gate_did, "term_structure_pass": term_pass,
            "n_other_mas_agreeing": agreeing, "ma_plateau_pass": agreeing >= PLATEAU_MIN_AGREEING_MAS,
            "sensitivity_same_sign": same_sign, "sensitivity_n_ci_excluding": n_excl, "sensitivity_pass": sens_pass,
            "confirmed": gate_focal and gate_did and term_pass and agreeing >= PLATEAU_MIN_AGREEING_MAS
                         and sens_pass and not bool(cell["below_threshold"]),
        })
    table = pd.DataFrame(cells)
    return {"cells": table, "n_cells": len(table),
            "n_confirmed": int(table["confirmed"].sum()) if len(table) else 0,
            "module_killed": bool(not table["confirmed"].any()) if len(table) else True}
