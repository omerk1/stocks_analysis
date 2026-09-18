"""M5 -- Touch/test/bounce behaviour (DESIGN.md §5; PREREGISTRATION.md,
2026-09-17).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement -- this module implements exactly that slice: 3
focal-vs-synthetic-neighborhood groups (reusing §7.5's own groups,
`features/placebo_ma.py::GROUPS`), each scored in both directions
(`from_above`/`from_below`, DESIGN's own support-vs-resistance framing),
6 primary cells total.

The event table itself (`features/touch.py::touch_events`) is the only new
machinery -- once it exists, the test statistic reuses this study's
existing C1/C2 block-bootstrap infrastructure unchanged: a hold/no-hold
flag is just another `value_col`, `is_focal` (real MA vs. synthetic
neighbor) is just another boolean `group_col`.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features.placebo_ma import GROUPS, dist_atr_column
from src.signals.moving_averages.features.touch import CHOP, FROM_ABOVE, FROM_BELOW, HOLD, SLICE_THROUGH, touch_events
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN §6.9, same numbers as every other module -- a live constraint
# here (event counts, not per-day rows).
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

DIRECTIONS = (FROM_ABOVE, FROM_BELOW)

# PREREGISTRATION.md's kill floor: 2 percentage points, DESIGN's own
# literal wording ("within 2pp of synthetic levels is folklore").
KILL_THRESHOLD = 0.02

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds the C2 match buckets to a panel already built by
    `features/placebo_ma.py::build_placebo_panel` (which supplies
    `mom_12_1`/`realized_vol_63`/`sector`, plus every group's focal +
    neighbor `dist_atr_*` columns -- see that module's 2026-09-17
    addendum). Returns a new frame; `panel` itself is not mutated.
    """
    working = panel.copy()
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    return working


def group_event_table(panel: pd.DataFrame, group_name: str) -> pd.DataFrame:
    """Pooled touch-event table for one group: every focal-lookback event
    (`is_focal=True`) plus every neighbor-lookback event (`is_focal=False`,
    one row per neighbor, pooled together), each joined back onto its own
    (ticker, date)'s C2 match columns -- the touch day's own context, not
    the panel's full row set (a touch event is a sparse subset of dates
    per ticker).
    """
    spec = GROUPS[group_name]
    family = spec["family"]
    context_cols = ["ticker", "date", *C2_MATCH_COLS]
    context = panel[context_cols].drop_duplicates(subset=["ticker", "date"])

    frames = []
    focal_col = dist_atr_column(family, spec["focal"])
    focal_events = touch_events(panel, focal_col)
    focal_events["is_focal"] = True
    frames.append(focal_events)

    for neighbor in spec["neighbors"]:
        neighbor_col = dist_atr_column(family, neighbor)
        neighbor_events = touch_events(panel, neighbor_col)
        neighbor_events["is_focal"] = False
        frames.append(neighbor_events)

    pooled = pd.concat(frames, ignore_index=True)
    pooled = pooled.merge(context, on=["ticker", "date"], how="left")
    pooled["hold_flag"] = pooled["hold_flag"].astype(float)
    return pooled


def _cell_row(
    events: pd.DataFrame, direction: str, label: dict,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
    block_length: int = 10, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """One (group, direction) cell: P(hold) delta between focal-lookback
    touches and pooled synthetic-neighbor touches, C1 and C2 (block-
    bootstrap), plus the descriptive full outcome distribution (hold/
    slice_through/chop) for the focal population, per DESIGN's "measure
    the full distribution" instruction. `events` is one group's pooled
    event table (see `group_event_table`); `block_length` defaults to 10
    (much shorter than the return-based modules' 42 -- these are sparse,
    non-overlapping touch events, not daily overlapping 21-day return
    windows, so the overlap-driven inflation `stats/inference.py`'s
    docstring motivates its own default against doesn't apply the same
    way here).
    """
    subset = events[events["direction"] == direction].dropna(subset=["hold_flag", *match_cols])
    focal = subset[subset["is_focal"]]

    n_events, n_dates, n_tickers = len(focal), focal["date"].nunique(), focal["ticker"].nunique()

    try:
        c2_boot = block_bootstrap_delta(
            subset, "is_focal", "hold_flag", match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        c2_boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                   "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    outcome_counts = focal["outcome"].value_counts()
    n_focal = len(focal)
    outcome_rates = {
        f"p_{name}": (outcome_counts.get(name, 0) / n_focal if n_focal else float("nan"))
        for name in (HOLD, SLICE_THROUGH, CHOP)
    }

    return {
        **label,
        "direction": direction,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(c2_boot["ci_low"])
        ),
        "c1": c1_delta(subset, "is_focal", "hold_flag") if len(subset) else float("nan"),
        "c2": c2_boot["point_estimate"],
        "c2_ci_low": c2_boot["ci_low"],
        "c2_ci_high": c2_boot["ci_high"],
        "c2_n_dates_boot": c2_boot["n_dates"],
        **outcome_rates,
    }


def primary_cell_table(panel: pd.DataFrame) -> pd.DataFrame:
    """All 6 primary cells: 3 groups x 2 directions. `panel` must already
    carry the C2 match columns (see `prepare`).
    """
    rows = []
    for group_name in GROUPS:
        events = group_event_table(panel, group_name)
        for direction in DIRECTIONS:
            rows.append(_cell_row(events, direction, {"group": group_name}))
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M5 kill criterion, applied to the 6 primary
    cells: `kill_cell := max(|ci_low|, |ci_high|) < 0.02` (2pp) -- DESIGN's
    own literal "within 2pp of synthetic levels is folklore" wording,
    translated into this study's standard CI-edge convention (same shape
    as M1/M2's `KILL_THRESHOLD`, a different floor). Module-level kill
    fires iff every primary cell satisfies `kill_cell`.
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
