"""M1 -- Baseline state conditioning (DESIGN.md §8; PREREGISTRATION.md, 2026-09-09).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement -- this module implements exactly that slice: SMA-only
above/below state (primary, 6 cells) and run-length age buckets (secondary,
24 cells) at SMA{20,50,200}, C0/C1/C2 deltas on `fwd_ret_21`, block-
bootstrap CIs, effective-N reporting, and a row-loss diagnostic. Nothing in
this module decides pass/fail on its own except `evaluate_kill_criterion`,
which implements the pre-registered magnitude/CI-edge rule exactly --
everything else is reporting.

C0/C1/C2 are computed on the *same* C2-eligible row set, not each control's
own wider natural set (PREREGISTRATION.md's M1 entry, "Waterfall row set")
-- `c0_unrestricted` is reported alongside as the sanity-check comparison
number, not as part of the waterfall itself.

`pooled` (`stats/controls.py::pooled_delta`) is the actual C0 leg of the
shrinkage waterfall (PREREGISTRATION.md, 2026-09-09 "waterfall re-rendered"
addendum) -- `c0` (`c0_delta`) is reported alongside only as DESIGN §6.1's
literal definition, labeled diluted; it is not scale-comparable to C1/C2
(its baseline includes the event rows themselves) and must not be read as
the first rung of the shrinkage story.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import ma
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import (
    c0_delta,
    c1_delta,
    c2_delta,
    c2_eligible_mask,
    cross_sectional_bucket,
    pooled_delta,
)
from src.signals.moving_averages.stats.inference import block_bootstrap_delta

# DESIGN §6.9, applied to the row-restricted (C2-eligible) population per
# PREREGISTRATION.md's M1 entry, "Minimum sample threshold".
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

LOOKBACKS = (20, 50, 200)
HORIZON = 21
DIRECTIONS = ("above", "below")
RUN_LENGTH_LABELS = ("1-5", "6-21", "22-63", "64+")

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Robustness-check-only match set (PREREGISTRATION.md, 2026-09-09 short-term-
# reversal confound check): adds a prior-21-day-return tercile. Not the
# module's pre-registered default -- `state_table`'s own C2 spec stays
# C2_MATCH_COLS unless a caller explicitly opts into this one.
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# PREREGISTRATION.md's M1 kill criterion: even the most-favorable-to-
# survival CI edge must clear this magnitude for a primary cell to survive.
KILL_THRESHOLD = 0.001  # 0.10%


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21` and the C2 match buckets (momentum/vol terciles --
    same tercile-not-decile convention as M4, referenced not re-derived --
    see PREREGISTRATION.md) to `panel`. Also adds `rev_tercile` (prior-
    21-day-return tercile), used only by the short-term-reversal
    robustness check (`C2_MATCH_COLS_WITH_REVERSAL`), not by the module's
    default C2 spec. Returns a new frame; `panel` itself is not mutated.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    return working


def _cell_row(working: pd.DataFrame, group_col: str, label: dict, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> dict:
    """One cell's full report. `working` is this cell's own natural row
    population -- already restricted to the state/direction/bucket that
    defines the cell, but *not yet* restricted to C2-eligible rows. That
    C2 restriction happens here, once, and C0/C1/C2 all read from the
    resulting `restricted` frame (the waterfall-row-set fix) -- `c0` in
    the output is therefore on the *restricted* set, and `c0_unrestricted`
    (computed on `working` directly) is reported alongside as the sanity-
    check comparison DESIGN's own shrinkage-waterfall framing needs.
    """
    unrestricted = working.dropna(subset=[group_col, "fwd_ret_21"])
    mask = c2_eligible_mask(working, group_col, "fwd_ret_21", match_cols=list(match_cols))
    restricted = working[mask]

    event_rows = restricted[restricted[group_col].astype(bool)]
    n_events = len(event_rows)
    n_dates = event_rows["date"].nunique()
    n_tickers = event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(restricted, group_col, "fwd_ret_21", match_cols=list(match_cols))
    except ValueError:
        # Too few distinct dates for the block bootstrap's minimum-blocks
        # requirement (stats/inference.py) -- happens on thin secondary
        # cells (e.g. a rare run-length bucket), not the 6 primary cells.
        # Flagged via below_threshold below, not silently zero-filled.
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "n_dates": restricted["date"].nunique() if len(restricted) else 0}

    # Split within `unrestricted` (not `working`) -- `working` also
    # contains rows missing group_col/fwd_ret_21 entirely (e.g. each
    # ticker's trailing 21 days, no forward return yet), which are already
    # outside the "unrestricted" baseline and must not be double-counted
    # into "missing C2 inputs" against a different denominator.
    has_c2_inputs = unrestricted[list(match_cols)].notna().all(axis=1)
    n_unrestricted = len(unrestricted)
    n_eligible = len(restricted)

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS
            or pd.isna(boot["ci_low"])
        ),
        "c0_unrestricted": c0_delta(unrestricted, group_col, "fwd_ret_21") if n_unrestricted else float("nan"),
        # `c0` is DESIGN §6.1's literal definition, kept for reference --
        # its baseline is diluted by the event group's own rows and is NOT
        # scale-comparable to c1/c2. `pooled` is the actual C0 leg of the
        # shrinkage waterfall (see module docstring).
        "c0": c0_delta(restricted, group_col, "fwd_ret_21") if n_eligible else float("nan"),
        "pooled": pooled_delta(restricted, group_col, "fwd_ret_21") if n_eligible else float("nan"),
        "c1": c1_delta(restricted, group_col, "fwd_ret_21") if n_eligible else float("nan"),
        "c2": c2_delta(restricted, group_col, "fwd_ret_21", match_cols=list(match_cols)) if n_eligible else float("nan"),
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_boot_std": boot["boot_std"],
        "c2_n_dates_boot": boot["n_dates"],
        "row_loss_n_unrestricted": n_unrestricted,
        "row_loss_n_eligible": n_eligible,
        "row_loss_n_lost": n_unrestricted - n_eligible,
        "row_loss_pct_lost": (n_unrestricted - n_eligible) / n_unrestricted if n_unrestricted else float("nan"),
        "row_loss_n_missing_c2_inputs": int((~has_c2_inputs).sum()),
        "row_loss_n_singleton_stratum": int(has_c2_inputs.sum()) - n_eligible,
        # By construction: n_missing_c2_inputs + n_singleton_stratum == n_lost.
    }


def state_table(panel: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 6 primary cells: above/below SMA state at {20, 50, 200}. One row
    per (lookback, direction). `panel` must already carry `fwd_ret_21` and
    the C2 match columns (see `prepare`). `match_cols` defaults to the
    module's pre-registered C2 spec; pass `C2_MATCH_COLS_WITH_REVERSAL` for
    the short-term-reversal robustness check (PREREGISTRATION.md,
    2026-09-09) -- same cell definitions, different C2 matching.
    """
    rows = []
    for lookback in LOOKBACKS:
        ma_col = ma.ma_column_name("sma", lookback)
        above_col = f"above_{ma_col}"
        for direction in DIRECTIONS:
            working = panel.dropna(subset=[above_col]).copy()
            is_event = working[above_col].astype(bool)
            working["_is_event"] = is_event if direction == "above" else ~is_event
            rows.append(
                _cell_row(
                    working, "_is_event", {"lookback": lookback, "direction": direction}, match_cols=match_cols
                )
            )
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M1 kill criterion, applied to the 6 primary
    cells only: `kill_cell := max(|ci_low|, |ci_high|) < 0.10%` -- even the
    interval's most extreme point, in either direction, fails to clear the
    economic-significance floor. Module-level kill fires iff every primary
    cell satisfies `kill_cell`.
    """
    edge = primary[["c2_ci_low", "c2_ci_high"]].abs().max(axis=1)
    cell_killed = edge < KILL_THRESHOLD

    return {
        "kill_threshold": KILL_THRESHOLD,
        "cell_killed": cell_killed.tolist(),
        "n_primary_cells": len(primary),
        "n_cells_killed": int(cell_killed.sum()),
        "module_killed": bool(cell_killed.all()),
    }


def run_length_table(panel: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 24 secondary cells: run-length bucket within each direction at
    each SMA lookback. One row per (lookback, direction, bucket). `panel`
    must already carry `fwd_ret_21` and the C2 match columns (see
    `prepare`). Secondary per PREREGISTRATION.md -- does not feed the kill
    criterion, reported for the "does age matter" sub-question only. The
    control population for a bucket cell is the *same direction's* other,
    non-censored run-length buckets (censored first-run rows are dropped
    from this analysis entirely, per PREREGISTRATION.md's "Run-length
    censoring" -- they are neither event nor control here). `match_cols`
    defaults to the module's pre-registered C2 spec, same as `state_table`.
    """
    rows = []
    for lookback in LOOKBACKS:
        ma_col = ma.ma_column_name("sma", lookback)
        above_col = f"above_{ma_col}"
        bucket_col = f"run_length_bucket_{ma_col}"
        for direction in DIRECTIONS:
            state_mask = panel[above_col] if direction == "above" else ~panel[above_col]
            direction_pool = panel.dropna(subset=[above_col, bucket_col]).copy()
            direction_pool = direction_pool[state_mask.reindex(direction_pool.index).fillna(False)]
            for run_bucket in RUN_LENGTH_LABELS:
                working = direction_pool.copy()
                working["_is_event"] = working[bucket_col] == run_bucket
                rows.append(
                    _cell_row(
                        working, "_is_event",
                        {"lookback": lookback, "direction": direction, "run_length_bucket": run_bucket},
                        match_cols=match_cols,
                    )
                )
    return pd.DataFrame(rows)
