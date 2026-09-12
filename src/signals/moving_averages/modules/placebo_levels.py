"""§7.5 -- Level effects vs. trend effects (the placebo test)
(DESIGN.md §7.5; PREREGISTRATION.md, 2026-09-12).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement -- this module implements exactly that slice: 3
focal-vs-neighborhood groups (SMA200 vs {187,193,207,213}; SMA50 vs
{47,53}; EMA21 vs {19,23}), each scored on whether the focal lookback's
`dist_pct` decile spread is a distinguishable outlier from *every one* of
its neighbors' own spreads -- block-bootstrap CI on the focal-minus-
neighbor difference (`stats/inference.py::block_bootstrap_spread_diff`),
C2-controlled (mom_tercile/vol_tercile/sector, same match cols as
M1/M4/M11). Each group is scored independently: a group can be
'confirmed' (genuine level effect) while another is 'killed' (folklore --
indistinguishable from an untraded neighbor), per DESIGN's own framing
that either answer is informative.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features.placebo_ma import GROUPS, dist_pct_column
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.cross_sectional import decile_turnover_hurdle
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import annualize, cost_hurdle
from src.signals.moving_averages.stats.inference import block_bootstrap_spread, block_bootstrap_spread_diff

# DESIGN §6.9
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

N_DECILES = 10
HORIZON = 21
ROUND_TRIP_COST = 0.0010  # 10bps round-trip, DESIGN §6.10 / U1 (unchanged from M1/M4/M11)

# C2: date + momentum-tercile + vol-tercile + sector matched -- unchanged
# match columns from M1/M4/M11.
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21` and the C2 match buckets to a panel already built
    by `features/placebo_ma.py::build_placebo_panel` (which supplies
    `mom_12_1`/`realized_vol_63`/`sector`). Returns a new frame; `panel`
    itself is not mutated.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    return working


def lookback_cell(
    panel: pd.DataFrame, family: str, lookback: int,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """Effective N + C1/C2 `dist_pct` decile-spread bootstrap for one
    lookback (focal or neighbor) -- the shared building block for both the
    per-group headline cell and the `group_diff` computation below.
    `panel` must already carry `fwd_ret_21` and the C2 match columns (see
    `prepare`).
    """
    feature_col = dist_pct_column(family, lookback)
    defined = panel.dropna(subset=[feature_col, "fwd_ret_21"]).copy()
    working = defined.copy()
    working["decile"] = cross_sectional_bucket(working, feature_col, n_buckets=N_DECILES)
    working = working.dropna(subset=["decile"])
    working["decile"] = working["decile"].astype(int)

    n_events, n_dates, n_tickers = len(working), working["date"].nunique(), working["ticker"].nunique()

    spread_c1 = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col="fwd_ret_21", match_cols=[], block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    spread_c2 = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col="fwd_ret_21", match_cols=list(C2_MATCH_COLS),
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )

    return {
        "feature_col": feature_col,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
        "spread_c1": spread_c1,
        "spread_c2": spread_c2,
        "_defined": defined,
        "_working": working,
    }


def group_diff(
    panel: pd.DataFrame, family: str, focal: int, neighbor: int,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """C2 `diff_g,n = spread(focal) - spread(neighbor)`, computed within
    each bootstrap draw (never differenced from two independently
    bootstrapped CIs) -- PREREGISTRATION.md §7.5's kill/confirm rule
    input.
    """
    focal_col = dist_pct_column(family, focal)
    neighbor_col = dist_pct_column(family, neighbor)
    both = panel.dropna(subset=[focal_col, neighbor_col, "fwd_ret_21"]).copy()
    both["__decile_focal"] = cross_sectional_bucket(both, focal_col, n_buckets=N_DECILES)
    both["__decile_neighbor"] = cross_sectional_bucket(both, neighbor_col, n_buckets=N_DECILES)
    both = both.dropna(subset=["__decile_focal", "__decile_neighbor"])
    both["__decile_focal"] = both["__decile_focal"].astype(int)
    both["__decile_neighbor"] = both["__decile_neighbor"].astype(int)

    return block_bootstrap_spread_diff(
        both, focal_decile_col="__decile_focal", neighbor_decile_col="__decile_neighbor",
        decile_low=0, decile_high=N_DECILES - 1, value_col="fwd_ret_21",
        match_cols=list(C2_MATCH_COLS), block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )


def _ci_excludes_zero(ci_low: float, ci_high: float) -> bool:
    return not (ci_low <= 0 <= ci_high)


def group_verdict(focal_cell: dict, diffs: dict[int, dict]) -> str:
    """PREREGISTRATION.md §7.5's pre-registered rule, evaluated on C2:
    'confirmed' iff the focal lookback's own CI excludes zero AND every
    `diff_g,n`'s CI excludes zero (the focal is a distinguishable outlier
    from its whole matched neighborhood); 'killed' (folklore) iff the
    focal's own CI includes zero, or any `diff_g,n`'s CI includes zero
    (indistinguishable from at least one untraded neighbor).
    """
    focal_ci = focal_cell["spread_c2"]
    if not _ci_excludes_zero(focal_ci["ci_low"], focal_ci["ci_high"]):
        return "killed"
    for diff in diffs.values():
        if not _ci_excludes_zero(diff["ci_low"], diff["ci_high"]):
            return "killed"
    return "confirmed"


def cost_for_focal(focal_cell: dict, round_trip_cost: float = ROUND_TRIP_COST) -> dict:
    """Cost annotation for a 'confirmed' group only (CLAUDE.md invariant
    #8) -- reuses M11's `decile_turnover_hurdle` unchanged (same
    entry+exit turnover convention, same 10bps/round-trip U1 hurdle).
    """
    cost = decile_turnover_hurdle(focal_cell["_defined"], focal_cell["_working"], "decile")
    point_annual = annualize(focal_cell["spread_c2"]["point_estimate"])
    ci_low_annual = annualize(focal_cell["spread_c2"]["ci_low"])
    ci_high_annual = annualize(focal_cell["spread_c2"]["ci_high"])
    cost["point_annualized"] = point_annual
    cost["ci_low_annualized"] = ci_low_annual
    cost["ci_high_annualized"] = ci_high_annual
    near_zero_edge = ci_low_annual if abs(ci_low_annual) < abs(ci_high_annual) else ci_high_annual
    cost["point_clears_cost"] = abs(point_annual) > cost["cost_hurdle_annual"]
    cost["ci_clears_cost"] = abs(near_zero_edge) > cost["cost_hurdle_annual"]
    return cost


def _strip_internal(cell: dict) -> dict:
    return {k: v for k, v in cell.items() if not k.startswith("_")}


def run_group(
    panel: pd.DataFrame, group_name: str,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """Full result for one group: the focal cell, every neighbor cell, the
    focal-minus-neighbor diffs, the pre-registered verdict, and (only if
    'confirmed') a cost annotation. `panel` must already carry `fwd_ret_21`
    and the C2 match columns (see `prepare`).
    """
    spec = GROUPS[group_name]
    family, focal, neighbors = spec["family"], spec["focal"], spec["neighbors"]

    focal_cell = lookback_cell(panel, family, focal, block_length, n_boot, ci, seed)
    neighbor_cells = {n: lookback_cell(panel, family, n, block_length, n_boot, ci, seed) for n in neighbors}
    diffs = {n: group_diff(panel, family, focal, n, block_length, n_boot, ci, seed) for n in neighbors}
    verdict = group_verdict(focal_cell, diffs)

    result = {
        "group": group_name,
        "family": family,
        "focal": focal,
        "neighbors": neighbors,
        "focal_cell": _strip_internal(focal_cell),
        "neighbor_cells": {n: _strip_internal(c) for n, c in neighbor_cells.items()},
        "diffs": diffs,
        "verdict": verdict,
    }
    if verdict == "confirmed":
        result["cost"] = cost_for_focal(focal_cell)
    return result


def run_all_groups(
    panel: pd.DataFrame, block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict[str, dict]:
    """`run_group` for every group in `GROUPS`. `panel` must already carry
    `fwd_ret_21` and the C2 match columns -- callers typically pass
    `prepare(build_placebo_panel(...))`.
    """
    return {
        name: run_group(panel, name, block_length=block_length, n_boot=n_boot, ci=ci, seed=seed)
        for name in GROUPS
    }
