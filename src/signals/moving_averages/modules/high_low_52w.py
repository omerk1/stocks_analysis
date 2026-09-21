"""M18 -- 52-week high/low range as a standalone predictor (DESIGN.md M18;
PREREGISTRATION.md, 2026-09-20).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement -- this module implements exactly that slice: `dist_from_
52w_high`/`dist_from_52w_low` decile spreads at {63, 126}-day horizons,
IC + C1 + C2 block-bootstrap CIs, and the turnover-based cost hurdle.
Generalizes `modules/cross_sectional.py`'s exact machinery (reused
unchanged, not reimplemented) from a `{feature}_sma_{lookback}` column to
a plain single-column feature -- no (family, lookback) grid here.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.modules.cross_sectional import daily_rank_ic, decile_turnover_hurdle
from src.signals.moving_averages.stats.controls import cross_sectional_bucket
from src.signals.moving_averages.stats.inference import block_bootstrap_series, block_bootstrap_spread

# DESIGN §6.9
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

FEATURES = ("dist_from_52w_high", "dist_from_52w_low")
HORIZONS = (63, 126)
N_DECILES = 10

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")


def prepare(panel: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Adds `fwd_ret_{h}` for every horizon this grid needs, and the C2 (+
    reversal-robustness) match columns -- same tercile-not-decile
    convention, same source columns (`mom_12_1`/`realized_vol_63`/
    `mom_1_0`) as every prior module. Returns a new frame; `panel` itself
    is not mutated.
    """
    working = panel.copy()
    for h in horizons:
        working[f"fwd_ret_{h}"] = forward_return(working, horizon=h)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    return working


def cell_result(
    panel: pd.DataFrame,
    feature: str,
    horizon: int,
    block_length: int,
    n_boot: int = 500,
    ci: float = 0.90,
    seed: int = 0,
) -> dict:
    """Full result for one (feature, horizon) cell: effective N, the C1
    rank-IC bootstrap, the C1 long-short decile-spread bootstrap, the C2
    (momentum/vol/sector-matched) spread bootstrap, the C2+reversal
    robustness-check spread bootstrap, and the turnover-based cost hurdle.
    `panel` must already carry `fwd_ret_{horizon}` and the C2(+reversal)
    match columns (see `prepare`). `block_length` must be supplied by the
    caller (>= 2x horizon, DESIGN §6.2 -- 63d and 126d need different
    block lengths, unlike every prior module's uniform 21d horizon).
    """
    return_col = f"fwd_ret_{horizon}"
    defined = panel.dropna(subset=[feature, return_col]).copy()
    working = defined.copy()
    working["decile"] = cross_sectional_bucket(working, feature, n_buckets=N_DECILES)
    working = working.dropna(subset=["decile"])
    working["decile"] = working["decile"].astype(int)

    n_events = len(working)
    n_dates = working["date"].nunique()
    n_tickers = working["ticker"].nunique()

    ic_series = daily_rank_ic(working, feature, return_col)
    ic_boot = block_bootstrap_series(ic_series, block_length=block_length, n_boot=n_boot, ci=ci, seed=seed)

    spread_c1 = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col=return_col, match_cols=[], block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    spread_c2 = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col=return_col, match_cols=list(C2_MATCH_COLS),
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )
    spread_c2_reversal = block_bootstrap_spread(
        working, decile_col="decile", decile_low=0, decile_high=N_DECILES - 1,
        value_col=return_col, match_cols=list(C2_MATCH_COLS_WITH_REVERSAL),
        block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
    )

    cost = decile_turnover_hurdle(defined, working, "decile")

    return {
        "feature": feature,
        "horizon": horizon,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS,
        "ic": ic_boot,
        "spread_c1": spread_c1,
        "spread_c2": spread_c2,
        "spread_c2_reversal": spread_c2_reversal,
        "cost": cost,
    }


def run_grid(
    panel: pd.DataFrame, n_boot: int = 500, seed: int = 0
) -> dict[str, dict]:
    """`cell_result` for the full pre-registered M18 grid: `FEATURES` x
    `HORIZONS`, keyed by e.g. `"dist_from_52w_high_h63"`. Block length is
    2x each horizon (DESIGN §6.2), not a single shared constant, since
    this module (unlike every prior one) tests two different horizons.
    """
    prepared = prepare(panel, HORIZONS)
    results = {}
    for feature in FEATURES:
        for horizon in HORIZONS:
            key = f"{feature}_h{horizon}"
            results[key] = cell_result(
                prepared, feature, horizon, block_length=2 * horizon, n_boot=n_boot, seed=seed
            )
    return results
