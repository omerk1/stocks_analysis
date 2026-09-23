"""M3 -- Crossovers: state vs transition (DESIGN.md, lines ~753-762;
PREREGISTRATION.md, 2026-09-23).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement. Skeptical hypothesis: a crossover (day 0 of the state
transition) carries little marginal information beyond "the stock is now
in a fast>slow state." DESIGN's own clean test: compare forward returns on
the event day against the *same state's* other days (a stock that has
already been fast>slow for a while), date+momentum(+vol+sector)-matched --
this is exactly this study's standard C2 block-bootstrap delta
(`stats/controls.py`/`stats/inference.py`), reused unchanged: `_is_event`
(day 0 of the transition, from `features/crossover.py::crossover_events`)
is just another boolean `group_col`, and the comparison population is
restricted to the event's own state (`state_<pair> == golden/death`) before
computing it -- the state-match DESIGN asks for is the row-restriction
itself, not a new inference layer.

5 fast/slow pairs (DESIGN's named facets): `sma_50/sma_200` (the classic
golden/death cross), `sma_20/sma_50`, `sma_50/sma_150` (all three already in
the cached panel, already one-bar-lagged), `ema_10/ema_20`, `ema_8/ema_21`
(new lookbacks, not in the cached panel -- added locally here via
`add_local_ema_columns`, lagged the same way `features/panel.py::apply_lag`
lags every other feature). 10 primary cells (5 pairs x 2 directions).

Quality facets (DESIGN's "Also test" bullet -- cross quality, cross angle,
price position) are run on `sma_50/sma_200`/golden only, to keep the grid
from spreading thin across every pair (documented scope cut, not silently
dropped -- see PREREGISTRATION.md): slope-sign of the long MA at the cross
(`slope_log_21_sma_200`, already in the cached panel) and price position
(above/below both MAs at the cross, `above_sma_50`/`above_sma_200`, already
in the cached panel). "Cross angle / spread velocity at crossing" and
drawdown/MAE metrics (DESIGN's other two "Also test" bullets) are scoped
out entirely -- the former has no coordinate-free definition (DESIGN's own
M6.7 note on "MA angle" applies identically to crossover angle), the latter
needs `labels/path_metrics.py`, which doesn't exist yet and is out of
scope for this module's build (PREREGISTRATION.md).
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import crossover, ma
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.costs import cost_hurdle, signals_per_year
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN Sec6.9, applied to the event population (same numbers as M5's own
# event-based cells -- PREREGISTRATION.md's own precedent for event-count
# rather than per-day-row thresholds).
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
GOLDEN = crossover.GOLDEN
DEATH = crossover.DEATH
DIRECTIONS = (GOLDEN, DEATH)

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# New EMA lookbacks not in the cached panel -- needed for the 10/20 and
# 8/21 EMA crossover facets (DESIGN's own named facets).
NEW_EMA_LOOKBACKS = (8, 10, 21)

PAIRS = {
    "sma_50_sma_200": ("sma_50", "sma_200"),
    "sma_20_sma_50": ("sma_20", "sma_50"),
    "sma_50_sma_150": ("sma_50", "sma_150"),
    "ema_10_ema_20": ("ema_10", "ema_20"),
    "ema_8_ema_21": ("ema_8", "ema_21"),
}

CLASSIC_PAIR = "sma_50_sma_200"

# DESIGN's own literal kill floor: "marginal information over state-matched
# controls is < 0.15% ... with CI spanning zero."
KILL_THRESHOLD = 0.0015


def add_local_ema_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `ema_8`/`ema_10`/`ema_21` to `panel`, one-bar-lagged the same
    way `features/panel.py::build_panel` lags every other feature (reuses
    `apply_lag` directly rather than a new lag convention). `panel` must
    already be sorted by (ticker, date) -- `read_panel`'s own output is;
    this function re-sorts defensively rather than assuming it.
    """
    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    new_cols = [ma.ma_column_name("ema", lb) for lb in NEW_EMA_LOOKBACKS]
    for lb, col in zip(NEW_EMA_LOOKBACKS, new_cols):
        working[col] = working.groupby("ticker")["close"].transform(lambda s, lb=lb: ma.compute_ma(s, "ema", lb))
    return apply_lag(working, columns=new_cols)


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds the local EMA columns, `fwd_ret_{5,21,63}`, the C2 match
    buckets, and each pair's fast-above-slow state column
    (`state_<pair_name>`) to `panel`. Returns a new frame; `panel` itself
    is not mutated.
    """
    working = add_local_ema_columns(panel)
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["fwd_ret_5"] = forward_return(working, horizon=5)
    working["fwd_ret_63"] = forward_return(working, horizon=63)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)
    for pair_name, (fast_col, slow_col) in PAIRS.items():
        working[f"state_{pair_name}"] = crossover.fast_above_slow_state(working, fast_col, slow_col)
    return working


def _cell_row(
    working: pd.DataFrame, pair_name: str, direction: str,
    match_cols: tuple[str, ...] = C2_MATCH_COLS, value_col: str = "fwd_ret_21",
    label_extra: dict | None = None,
) -> dict:
    """One (pair, direction) cell: the C2 delta between the crossover event
    day and the same state's other days, on `value_col`. `working` is the
    row population to restrict to (the full prepared panel for a primary
    cell, or an already-facet-restricted subset for a quality facet --
    both the event day and its control are drawn from the *same*
    restriction, so a facet like "slope rising" compares fresh crosses
    against seasoned same-state days that also have a rising long MA, not
    against the whole unrestricted state population).
    """
    state_col = f"state_{pair_name}"
    events = crossover.crossover_events(working, state_col)
    events = events[events["crossover_type"] == direction][["ticker", "date"]].drop_duplicates()

    state_bool = direction == GOLDEN
    population = working[working[state_col] == state_bool].copy()
    population = population.merge(events.assign(_is_event=True), on=["ticker", "date"], how="left")
    population["_is_event"] = population["_is_event"].astype("boolean").fillna(False)

    subset = population.dropna(subset=["_is_event", value_col, *match_cols])
    event_rows = subset[subset["_is_event"]]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(subset, "_is_event", value_col, match_cols=list(match_cols))
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": subset["date"].nunique() if len(subset) else 0}

    label = {"pair": pair_name, "direction": direction, "value_col": value_col}
    if label_extra:
        label.update(label_extra)

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(subset, "_is_event", value_col) if len(subset) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
    }


def primary_cell_table(working: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 10 primary cells: 5 pairs x 2 directions. `working` must already
    carry `fwd_ret_21` and every pair's state column (see `prepare`).
    """
    rows = []
    for pair_name in PAIRS:
        for direction in DIRECTIONS:
            rows.append(_cell_row(working, pair_name, direction, match_cols=match_cols))
    return pd.DataFrame(rows)


def horizon_companion_table(working: pd.DataFrame, pair_name: str = CLASSIC_PAIR) -> pd.DataFrame:
    """Companion cells at h5/h63 for one pair (both directions) -- not part
    of the declared primary grid (only h21 is, matching this study's
    standard horizon), reported to speak to DESIGN's "at every horizon"
    kill-criterion wording for the classic pair specifically.
    """
    rows = []
    for direction in DIRECTIONS:
        for value_col in ("fwd_ret_5", "fwd_ret_63"):
            rows.append(_cell_row(working, pair_name, direction, value_col=value_col))
    return pd.DataFrame(rows)


def quality_facet_table(working: pd.DataFrame, pair_name: str = CLASSIC_PAIR) -> pd.DataFrame:
    """4 secondary cells on `pair_name`/golden only (DESIGN's "Also test"
    quality facets): slope-sign of the long MA (rising/falling) and price
    position at the cross (above both MAs / not above both). Both facets
    restrict the *entire* comparison population (event days and their
    same-state control days alike) before running the same C2 delta
    `_cell_row` computes for the primary cells -- see that function's
    docstring.
    """
    slow_col = PAIRS[pair_name][1]
    slope_col = f"slope_log_21_{slow_col}"
    slope_valid = working[slope_col].notna()
    slope_rising = slope_valid & (working[slope_col] > 0)
    slope_falling = slope_valid & (working[slope_col] <= 0)

    fast_col = PAIRS[pair_name][0]
    above_fast = working[f"above_{fast_col}"]
    above_slow = working[f"above_{slow_col}"]
    price_defined = above_fast.notna() & above_slow.notna()
    price_above_both = price_defined & above_fast.astype("boolean").fillna(False) & above_slow.astype(
        "boolean"
    ).fillna(False)
    price_not_above_both = price_defined & ~price_above_both

    rows = [
        _cell_row(working[slope_rising], pair_name, GOLDEN, label_extra={"facet": "slope_sign", "facet_value": "rising"}),
        _cell_row(working[slope_falling], pair_name, GOLDEN, label_extra={"facet": "slope_sign", "facet_value": "falling"}),
        _cell_row(working[price_above_both], pair_name, GOLDEN, label_extra={"facet": "price_position", "facet_value": "above_both"}),
        _cell_row(working[price_not_above_both], pair_name, GOLDEN, label_extra={"facet": "price_position", "facet_value": "not_above_both"}),
    ]
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M3 kill criterion, applied to the 10 primary
    cells: `kill_cell := max(|ci_low|, |ci_high|) < 0.15%` -- DESIGN's own
    literal wording, same CI-edge convention as every other module's kill
    rule (M1's `KILL_THRESHOLD`, M5's `KILL_THRESHOLD`, a different floor
    each time). Module-level kill fires iff every primary cell satisfies
    `kill_cell`.
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


def cost_row(working: pd.DataFrame, pair_name: str, round_trip_cost: float = 0.001) -> dict:
    """`signals_per_year`/hurdle for `pair_name`'s state column -- every
    crossover (golden or death) is one state flip, so this reuses
    `stats/costs.py::signals_per_year` directly on `state_<pair_name>`,
    same "flip = one signal" convention M1's above/below cells use, no new
    cost logic needed.
    """
    state_col = f"state_{pair_name}"
    spy = signals_per_year(working, state_col)
    return {"pair": pair_name, "signals_per_year": spy, "cost_hurdle_annual": cost_hurdle(spy, round_trip_cost)}
