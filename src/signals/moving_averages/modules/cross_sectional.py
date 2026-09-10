"""M11 -- Cross-sectional formulation (DESIGN.md §8, M11; PREREGISTRATION.md,
2026-09-09).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement. Per that entry: the primary cell is `dist_pct_sma_20` at a
21-day horizon, decided by two joint tests (Spearman rank-IC vs. a 0.02
floor, and the long-short decile spread vs. a turnover-measured cost
hurdle), both CI-based via `stats/costs.py::ci_clears_cost`. Secondary
cells (other lookbacks/horizons on `dist_pct`) and companion readouts
(`dist_atr`/`dist_z` at SMA20) are reported but don't individually trigger
the module's kill/no-kill verdict -- see PREREGISTRATION.md's "Primary vs.
secondary cells."

Two control layers per cell, both reported, neither privileged over the
other by this module -- the caller reads both against the pre-registered
decisive test:
- **C1 (primary)**: pure per-date cross-sectional statistic -- already
  date-matched by construction, no additional stratification, no row loss
  beyond a feature's own NaN warmup.
- **Neutralized (the C2-equivalent robustness layer)**: `sector`,
  `vol_tercile`, and `mom_tercile` matched via
  `stats.inference.block_bootstrap_spread`'s existing stratified-match
  machinery (the same tool M1/M4 use for their own C2, reused rather than
  reimplemented). Momentum matching is not optional here -- DESIGN.md
  §6.1 calls C2 "the one that separates real MA information from momentum
  re-encoding," the central confound this whole study is built around
  (§7.1); a "neutralized" layer that drops momentum isn't testing that.
  PREREGISTRATION.md describes this conceptually as demeaning/
  neutralization; in this implementation it is the same stratify-and-
  average mechanism M1/M4 already use, applied to a cross-sectional
  decile assignment computed once per date -- reused because it's the
  tested tool already in this repo, not a separate demeaning
  implementation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.costs import cost_hurdle, signals_per_year
from src.signals.moving_averages.stats.inference import block_bootstrap_series, block_bootstrap_spread

# DESIGN §6.9
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

N_DECILES = 10
IC_FLOOR = 0.02
ROUND_TRIP_COST = 0.0010  # 10bps, DESIGN §6.10's illustrative convention

NEUTRALIZATION_MATCH_COLS = ("sector", "vol_tercile", "mom_tercile")

# The pre-registered grid (PREREGISTRATION.md, M11): 1 primary + 4 secondary
# cells, plus 2 companion readouts excluded from N_tests (found highly
# correlated with the primary's normalisation at SMA20).
PRIMARY_CELL = ("dist_pct", 20, 21)
SECONDARY_CELLS = (
    ("dist_pct", 50, 21),
    ("dist_pct", 200, 21),
    ("dist_pct", 20, 5),
    ("dist_pct", 20, 63),
)
COMPANION_CELLS = (
    ("dist_atr", 20, 21),
    ("dist_z", 20, 21),
)


def prepare(panel: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    """Adds `fwd_ret_{h}` for every horizon this grid needs and the
    neutralization match columns (`vol_tercile`, `mom_tercile` -- same
    tercile-not-decile convention as M1/M4, referenced not re-derived;
    `sector` is already on the panel). Returns a new frame; `panel` itself
    is not mutated.
    """
    working = panel.copy()
    for h in horizons:
        working[f"fwd_ret_{h}"] = forward_return(working, horizon=h)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    return working


def daily_rank_ic(panel: pd.DataFrame, feature_col: str, return_col: str, date_col: str = "date") -> pd.Series:
    """Per-date cross-sectional Spearman rank-IC between `feature_col` and
    `return_col` -- one value per date. A date with fewer than `MIN_TICKERS`
    valid (feature, return) pairs is dropped (NaN) rather than computing a
    correlation on too few names to be meaningful.
    """

    def _corr(g: pd.DataFrame) -> float:
        sub = g.dropna()
        if len(sub) < MIN_TICKERS:
            return float("nan")
        return sub[feature_col].corr(sub[return_col], method="spearman")

    # Grouping on the index (not a column) rather than passing
    # `include_groups=False` to `.apply` -- that kwarg only exists on
    # pandas>=2.2, and this repo's floor is 2.0.0 (requirements.txt).
    # Indexing by date_col first means there's no grouping column for a
    # pandas version's `apply` to decide whether to include, so behavior
    # is identical across 2.0-3.x without a version-specific argument.
    indexed = panel.set_index(date_col)[[feature_col, return_col]]
    return indexed.groupby(level=0).apply(_corr)


def decile_turnover_hurdle(
    full_panel: pd.DataFrame,
    working: pd.DataFrame,
    decile_col: str,
    ticker_col: str = "ticker",
    date_col: str = "date",
    round_trip_cost: float = ROUND_TRIP_COST,
) -> dict:
    """Combined-legs annualized cost hurdle for a long-top/short-bottom
    decile portfolio, measured via `stats.costs.signals_per_year`
    (entry+exit flip count -- the repo standard per PREREGISTRATION.md's
    2026-09-09 M4 turnover-reconciliation addendum, not the entries-only
    convention M4 originally used).

    `working` (the caller's decile-assigned frame) is reindexed onto
    `full_panel` before computing decile membership, rather than passed to
    `signals_per_year` directly -- `cross_sectional_bucket`'s
    `qcut(duplicates="drop")` can silently thin a date's coverage, and if
    that ever drops a ticker's row from the *middle* of its history, an
    un-reindexed `working` would present adjacent-in-dataframe rows as
    adjacent-in-time to `state_run_id`, silently mis-counting a flip.

    `full_panel` must be the feature/return-*defined* population (i.e.
    `panel.dropna(subset=[feature_col, return_col])`, before decile
    assignment's own dropna) -- not the raw panel. The raw panel's own
    trailing NaN region (the last `horizon` days per ticker, where no
    forward return exists yet) is expected and structural, present on
    every cell; reindexing onto it would misreport that ordinary shape as
    a suspicious gap. Reindexing onto the feature/return-defined
    population instead isolates exactly the gap this guards against: one
    introduced by decile assignment itself, not by forward-return warmup.
    On that skeleton, a genuine interior gap from decile assignment is an
    explicit NaN, which `state_run_id` either reconstructs correctly (if
    it happens to land at the very start, the ordinary MA-warmup shape) or
    raises loudly on (a true interior gap) -- failing loudly here instead
    of silently corrupting `cost_hurdle_annual`.
    """
    skeleton = full_panel[[ticker_col, date_col]]
    merged = skeleton.merge(working[[ticker_col, date_col, decile_col]], on=[ticker_col, date_col], how="left")
    merged = merged.sort_values([ticker_col, date_col]).reset_index(drop=True)

    is_top = merged[decile_col] == (N_DECILES - 1)
    is_bottom = merged[decile_col] == 0
    top = pd.array(is_top.where(merged[decile_col].notna(), pd.NA), dtype="boolean")
    bottom = pd.array(is_bottom.where(merged[decile_col].notna(), pd.NA), dtype="boolean")
    turnover_frame = merged[[ticker_col]].copy()
    turnover_frame["top_decile"] = top
    turnover_frame["bottom_decile"] = bottom

    spy_top = signals_per_year(turnover_frame, "top_decile", ticker_col=ticker_col)
    spy_bottom = signals_per_year(turnover_frame, "bottom_decile", ticker_col=ticker_col)
    spy_combined = spy_top + spy_bottom
    return {
        "signals_per_year_top": spy_top,
        "signals_per_year_bottom": spy_bottom,
        "signals_per_year_combined": spy_combined,
        "cost_hurdle_annual": cost_hurdle(spy_combined, round_trip_cost),
    }


def cell_result(
    panel: pd.DataFrame,
    feature: str,
    lookback: int,
    horizon: int,
    block_length: int = 42,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Full result for one (feature, lookback, horizon) cell: effective N,
    the C1 rank-IC bootstrap, the C1 long-short decile-spread bootstrap,
    the neutralized (sector/vol_tercile) spread bootstrap, and the
    turnover-based cost hurdle. `panel` must already carry
    `fwd_ret_{horizon}` and `vol_tercile` (see `prepare`).
    """
    feature_col = f"{feature}_sma_{lookback}"
    return_col = f"fwd_ret_{horizon}"

    defined = panel.dropna(subset=[feature_col, return_col]).copy()
    working = defined.copy()
    working["decile"] = cross_sectional_bucket(working, feature_col, n_buckets=N_DECILES)
    working = working.dropna(subset=["decile"])
    working["decile"] = working["decile"].astype(int)

    n_events = len(working)
    n_dates = working["date"].nunique()
    n_tickers = working["ticker"].nunique()

    ic_series = daily_rank_ic(working, feature_col, return_col)
    ic_boot = block_bootstrap_series(ic_series, block_length=block_length, n_boot=n_boot, ci=ci, seed=seed)

    spread_c1 = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col=return_col, match_cols=[], block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    spread_neutralized = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col=return_col, match_cols=list(NEUTRALIZATION_MATCH_COLS),
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )

    cost = decile_turnover_hurdle(defined, working, "decile")

    return {
        "feature_col": feature_col,
        "horizon": horizon,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
        "ic": ic_boot,
        "spread_c1": spread_c1,
        "spread_neutralized": spread_neutralized,
        "cost": cost,
    }


def run_grid(
    panel: pd.DataFrame, block_length: int = 42, n_boot: int = 500, seed: int = 0
) -> dict[str, dict]:
    """`cell_result` for the full pre-registered M11 grid: the primary
    cell, the 4 secondary cells, and the 2 companion readouts -- keyed by
    `"{feature}_sma_{lookback}_h{horizon}"`.
    """
    cells = (PRIMARY_CELL, *SECONDARY_CELLS, *COMPANION_CELLS)
    horizons = tuple(sorted({h for _, _, h in cells}))
    prepared = prepare(panel, horizons)

    results = {}
    for feature, lookback, horizon in cells:
        key = f"{feature}_sma_{lookback}_h{horizon}"
        results[key] = cell_result(
            prepared, feature, lookback, horizon, block_length=block_length, n_boot=n_boot, seed=seed
        )
    return results
