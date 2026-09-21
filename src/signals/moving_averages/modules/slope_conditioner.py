"""M6.2 -- Slope as conditioner (DESIGN.md §6.2; PREREGISTRATION.md,
2026-09-17).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement -- this module implements exactly that slice: 3 of
DESIGN's 4 named sub-questions (state x slope, extension x slope, touch x
slope), 12 primary cells (2 lookbacks x 2 facets each), all built by
restricting the panel to a row-subset first and then reusing existing
primitives unchanged (`stats.inference.block_bootstrap_delta`,
`features.touch.touch_events`) -- no new statistical machinery, only a
new `slope_sign_sma_k` column.

Golden-cross x slope (DESIGN's 4th named sub-question) is out of scope
for this slice -- it needs new crossover-event-detection machinery that
doesn't exist yet, unlike the three sub-questions here.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features.touch import FROM_ABOVE, FROM_BELOW, touch_events
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
LOOKBACKS = (50, 200)
N_DECILES = 10
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Robustness-check-only match set (PREREGISTRATION.md, 2026-09-21 reversal-
# robustness addendum), same construction as `modules/stack_minervini.py`'s/
# `modules/baseline_state.py`'s own `C2_MATCH_COLS_WITH_REVERSAL`: adds a
# prior-21-day-return tercile so a cell's C2 delta can be re-evaluated with
# short-term reversal explicitly matched out. Not this module's
# pre-registered default -- `_delta_cell`'s own `match_cols` stays
# `C2_MATCH_COLS` unless a caller explicitly opts into this one.
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# Return-based cells (sub-questions 1-2) use M1/M2's own 0.10% floor;
# hold-rate cells (sub-question 3) use M5's own 2pp floor -- the floor is
# keyed to the value type, not a new threshold invented for this module.
KILL_THRESHOLD_RETURN = 0.001
KILL_THRESHOLD_HOLD = 0.02


def slope_sign_column(lookback: int) -> str:
    return f"slope_sign_sma_{lookback}"


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, and `slope_sign_sma_{50,200}`
    (sign of the already-cached, already-lagged `slope_log_21_sma_k`) to
    the main cached panel (not the §7.5/M5 placebo panel -- no synthetic-
    neighbor comparison needed for this module). Returns a new frame;
    `panel` itself is not mutated.

    Also adds `rev_tercile` (prior-21-day-return tercile, same construction
    as `modules/stack_minervini.py`'s/`modules/baseline_state.py`'s own
    robustness-check column), used only by the short-term-reversal check
    (`C2_MATCH_COLS_WITH_REVERSAL`), not by this module's default C2 spec.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    for lookback in LOOKBACKS:
        slope_col = f"slope_log_21_sma_{lookback}"
        working[slope_sign_column(lookback)] = (
            (working[slope_col] > 0).astype("boolean").mask(working[slope_col].isna())
        )
    return working


def _delta_cell(
    restricted: pd.DataFrame, group_col: str, value_col: str, label: dict,
    kill_threshold: float, match_cols: tuple[str, ...] = C2_MATCH_COLS,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """One conditioning cell: C1/C2 delta of `value_col` between
    `group_col`'s two states, on an already-restricted row population
    (e.g. "above_sma_200 only", "top decile of dist_atr_sma_50 only",
    "from_above touch events only"). Same shape as every other module's
    `_cell_row`, generalized to an arbitrary pre-restriction rather than
    re-deriving the restriction logic per sub-question.
    """
    subset = restricted.dropna(subset=[group_col, value_col, *match_cols])
    event_rows = subset[subset[group_col].astype(bool)]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(
            subset, group_col, value_col, match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = (
        None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])
    )

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(subset, group_col, value_col) if len(subset) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "kill_threshold": kill_threshold,
        "edge": edge,
        # `killed` is exactly PREREGISTRATION.md's pre-registered rule
        # (max(|ci_low|,|ci_high|) < floor) -- it does NOT mean "no real
        # effect" when False. A cell can have `killed=False` and still
        # have a CI spanning zero (an inconclusive/underpowered read, not
        # a confirmed effect) -- `ci_excludes_zero` is the separate field
        # that actually answers "is there a distinguishable effect here."
        "killed": (edge < kill_threshold) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
    }


def state_slope_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Sub-question 1 (4 cells): "above a rising 200 vs above a falling
    200" -- and the same for 50, and for "below." `panel` must already
    carry `fwd_ret_21`/C2 match columns/`slope_sign_sma_k` (see `prepare`).
    """
    rows = []
    for lookback in LOOKBACKS:
        above_col = f"above_sma_{lookback}"
        sign_col = slope_sign_column(lookback)
        for state in ("above", "below"):
            is_state = panel[above_col] if state == "above" else ~panel[above_col]
            restricted = panel[is_state.fillna(False).to_numpy()]
            rows.append(_delta_cell(
                restricted, sign_col, "fwd_ret_21",
                {"sub_question": "state_x_slope", "lookback": lookback, "state": state},
                KILL_THRESHOLD_RETURN,
            ))
    return pd.DataFrame(rows)


def extension_slope_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Sub-question 2 (4 cells): "is +5 ATR above a flat 50-day a
    different object from +5 ATR above a steeply rising one" -- top and
    bottom `dist_atr_sma_k` decile, each faceted by slope sign.
    """
    rows = []
    for lookback in LOOKBACKS:
        dist_col = f"dist_atr_sma_{lookback}"
        sign_col = slope_sign_column(lookback)
        working = panel.copy()
        working["_decile"] = cross_sectional_bucket(working, dist_col, n_buckets=N_DECILES)
        for extension, decile_value in (("top", N_DECILES - 1), ("bottom", 0)):
            restricted = working[working["_decile"] == decile_value]
            rows.append(_delta_cell(
                restricted, sign_col, "fwd_ret_21",
                {"sub_question": "extension_x_slope", "lookback": lookback, "extension": extension},
                KILL_THRESHOLD_RETURN,
            ))
    return pd.DataFrame(rows)


def touch_slope_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Sub-question 3 (4 cells): "MA touch with rising vs falling MA" --
    M5's own touch-event extraction, applied to the real MA only (no
    synthetic-neighbor comparison, unlike M5 itself), faceted by the
    slope sign at the touch day. `panel` must already carry
    `slope_sign_sma_k`/C2 match columns (see `prepare`); `touch_events`
    itself only needs `ticker`/`date`/the `dist_atr` column.
    """
    rows = []
    context_cols = ["ticker", "date", *C2_MATCH_COLS]
    context = panel[context_cols].drop_duplicates(subset=["ticker", "date"])
    for lookback in LOOKBACKS:
        dist_col = f"dist_atr_sma_{lookback}"
        sign_col = slope_sign_column(lookback)
        slope_context = panel[["ticker", "date", sign_col]].drop_duplicates(subset=["ticker", "date"])

        events = touch_events(panel, dist_col)
        events = events.merge(slope_context, on=["ticker", "date"], how="left")
        events = events.merge(context, on=["ticker", "date"], how="left")
        events["hold_flag"] = events["hold_flag"].astype(float)

        for direction in (FROM_ABOVE, FROM_BELOW):
            subset = events[events["direction"] == direction]
            rows.append(_delta_cell(
                subset, sign_col, "hold_flag",
                {"sub_question": "touch_x_slope", "lookback": lookback, "direction": direction},
                KILL_THRESHOLD_HOLD, block_length=10,
            ))
    return pd.DataFrame(rows)


def primary_cell_table(panel: pd.DataFrame) -> pd.DataFrame:
    """All 12 primary cells across the 3 sub-questions. `panel` must
    already be `prepare()`'d.
    """
    return pd.concat([
        state_slope_table(panel),
        extension_slope_table(panel),
        touch_slope_table(panel),
    ], ignore_index=True)
