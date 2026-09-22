"""M7 -- Ribbon compression / expansion (DESIGN.md M7; PREREGISTRATION.md,
2026-09-22).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement -- this module tests whether low `ribbon_width_pctile`
(a compressed SMA ribbon) precedes volatility expansion, and separately
whether it predicts *direction*, unconditionally and conditional on prior
trend (DESIGN's own explicit "vol prediction works, direction doesn't
except conditional on trend" prior).

Reuses this study's existing decile-spread (`stats/inference.py
::block_bootstrap_spread`, M4/M11/M18's own primitive) and within-
restriction group-delta (`block_bootstrap_delta`, M6.2's own primitive)
machinery unchanged -- the only new pieces are the `ribbon_width`/
`ribbon_width_pctile` feature (`features/ribbon.py`) and the
`forward_realized_vol` label (`labels/forward_returns.py`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.ribbon import ribbon_width, ribbon_width_pctile
from src.signals.moving_averages.labels.forward_returns import forward_realized_vol, forward_return
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
    block_bootstrap_spread,
)
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
N_DECILES = 10
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
# For the vol-outcome cells only: dropping `vol_tercile` avoids matching
# away the very thing the vol-expansion hypothesis is about (see
# PREREGISTRATION.md's "Control tier and why" -- this study's usual
# vol_tercile match is in tension with a hypothesis that's partly *about*
# vol itself).
C2_MATCH_COLS_NO_VOL = ("mom_tercile", "sector")

KILL_THRESHOLD_RETURN = 0.001  # M1/M2/M6.2's own 0.10% floor
# Absolute floor on the vol-spread cells' block-bootstrap CI, in daily-
# return-std units. Calibrated against this panel's own realized_vol_63
# distribution (median ~0.0146, IQR [0.0113, 0.0194]) -- 0.001 is ~7% of
# the median level, a floor chosen to rule out a trivially small but
# CI-excluding-zero shift, not derived from any formula DESIGN states
# (DESIGN doesn't give one for this module).
KILL_THRESHOLD_VOL = 0.001


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`/`fwd_absret_21`/`fwd_vol_21`, the C2 match
    buckets, `ribbon_width`/`ribbon_width_pctile`/`ribbon_decile`, and
    `prior_trend_up` to the main cached panel. Returns a new frame;
    `panel` itself is not mutated.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["fwd_absret_21"] = working["fwd_ret_21"].abs()
    working["fwd_vol_21"] = forward_realized_vol(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    working["ribbon_width"] = ribbon_width(working)
    working["ribbon_width_pctile"] = ribbon_width_pctile(working["ribbon_width"], working["ticker"])
    decile = np.floor(working["ribbon_width_pctile"] * N_DECILES)
    working["ribbon_decile"] = decile.clip(upper=N_DECILES - 1)

    working["prior_trend_up"] = (
        (working["mom_12_1"] > 0).astype("boolean").mask(working["mom_12_1"].isna())
    )
    return working


def _spread_cell(
    panel: pd.DataFrame, value_col: str, label: dict, kill_threshold: float,
    match_cols: tuple[str, ...] = C2_MATCH_COLS, block_length: int = 42,
    n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """Decile-9-minus-decile-0 `ribbon_decile` spread on `value_col` --
    M4/M11/M18's own decile-spread primitive, applied to the ribbon-width
    decile instead of a distance decile. Reports the compressed
    (decile-0) group's own effective N and, for the two directional-
    return cells, its hit-rate/win-loss/skew shape stats (CLAUDE.md
    invariant #10 -- new, forward-looking work).
    """
    subset = panel.dropna(subset=["ribbon_decile", value_col, *match_cols])
    compressed = subset[subset["ribbon_decile"] == 0]
    n_events, n_dates, n_tickers = (
        len(compressed), compressed["date"].nunique(), compressed["ticker"].nunique(),
    )

    try:
        boot = block_bootstrap_spread(
            subset, decile_col="ribbon_decile", decile_low=0, decile_high=N_DECILES - 1,
            value_col=value_col, match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = (
        None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])
    )

    result = {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "kill_threshold": kill_threshold,
        "edge": edge,
        "killed": (edge < kill_threshold) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
    }

    # Shape stats (hit rate / win-loss ratio / skew, CLAUDE.md invariant
    # #10) only make sense on a genuinely signed return -- `fwd_absret_21`
    # is >= 0 by construction, so "hit rate" (P(value>0)) and win/loss
    # split would be a trivially-~100%/degenerate read, not a real
    # descriptive statistic. Restricted to the signed outcome only.
    if value_col == "fwd_ret_21" and n_events:
        is_compressed = (subset["ribbon_decile"] == 0).astype(bool)
        result["hit_rate"] = hit_rate_deltas(
            subset.assign(_is_compressed=is_compressed), "_is_compressed", value_col,
            match_cols=list(match_cols),
        )
        result["shape"] = distribution_shape(compressed[value_col])

    return result


def vol_expansion_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Does ribbon compression (decile 0) predict *higher* forward
    realized vol than ribbon expansion (decile 9)? Two readings: standard
    C2 (mom/vol/sector-matched -- matches away part of the very thing
    being tested) and C2 without the vol_tercile match column (the more
    literal reading of the hypothesis).
    """
    return pd.DataFrame([
        _spread_cell(panel, "fwd_vol_21", {"outcome": "vol_expansion", "match": "c2_standard"},
                     KILL_THRESHOLD_VOL, match_cols=C2_MATCH_COLS),
        _spread_cell(panel, "fwd_vol_21", {"outcome": "vol_expansion", "match": "c2_no_vol_match"},
                     KILL_THRESHOLD_VOL, match_cols=C2_MATCH_COLS_NO_VOL),
    ])


def direction_unconditional_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Does ribbon compression predict forward *direction* (signed return)
    or *magnitude* (|return|) on its own, unconditional on trend? DESIGN's
    own prior: no.
    """
    return pd.DataFrame([
        _spread_cell(panel, "fwd_ret_21", {"outcome": "direction_signed"}, KILL_THRESHOLD_RETURN),
        _spread_cell(panel, "fwd_absret_21", {"outcome": "direction_magnitude"}, KILL_THRESHOLD_RETURN),
    ])


def direction_conditional_on_trend_table(panel: pd.DataFrame) -> dict:
    """Within the compressed (decile-0) population only, does prior trend
    direction (`mom_12_1` sign) determine which way price breaks out?
    DESIGN's own prior: yes, weakly -- this is the one cell where
    direction should show up, conditional on trend.
    """
    restricted = panel[panel["ribbon_decile"] == 0]
    subset = restricted.dropna(subset=["prior_trend_up", "fwd_ret_21", *C2_MATCH_COLS])
    event_rows = subset[subset["prior_trend_up"].astype(bool)]
    n_events, n_dates, n_tickers = (
        len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique(),
    )

    try:
        boot = block_bootstrap_delta(
            subset, "prior_trend_up", "fwd_ret_21", match_cols=list(C2_MATCH_COLS),
            block_length=42, n_boot=500, ci=0.90, seed=0,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = (
        None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])
    )

    result = {
        "outcome": "direction_conditional_on_trend",
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(subset, "prior_trend_up", "fwd_ret_21") if len(subset) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "kill_threshold": KILL_THRESHOLD_RETURN,
        "edge": edge,
        "killed": (edge < KILL_THRESHOLD_RETURN) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
    }
    if n_events:
        result["hit_rate"] = hit_rate_deltas(subset, "prior_trend_up", "fwd_ret_21", match_cols=list(C2_MATCH_COLS))
        result["shape"] = distribution_shape(event_rows["fwd_ret_21"])
    return result


def primary_cell_table(panel: pd.DataFrame) -> pd.DataFrame:
    """All 5 primary cells: 2 vol-expansion readings, 2 unconditional
    direction/magnitude cells, 1 trend-conditional direction cell.
    `panel` must already be `prepare()`'d.
    """
    rows = pd.concat([
        vol_expansion_table(panel),
        direction_unconditional_table(panel),
    ], ignore_index=True)
    rows = pd.concat([rows, pd.DataFrame([direction_conditional_on_trend_table(panel)])], ignore_index=True)
    return rows
