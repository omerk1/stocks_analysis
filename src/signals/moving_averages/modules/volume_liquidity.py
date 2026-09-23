"""M12 -- Volume and liquidity interaction (DESIGN.md line ~971;
PREREGISTRATION.md, 2026-09-23).

Track B. See PREREGISTRATION.md for the full hypothesis / kill-criterion /
scope statement -- this module implements exactly that slice: reclaim
(state-transition-into-`above`) durability at SMA{20,50,200}, conditioned
on three volume/liquidity facets (relative volume, dollar-volume
percentile, VWMA-vs-SMA divergence), each split top-vs-bottom tercile,
C1/C2 deltas via `block_bootstrap_delta`, effective-N reporting. Nothing
here decides pass/fail on its own except `evaluate_kill_criterion`, which
implements the pre-registered magnitude/CI-edge rule exactly over the 9
counted primary cells -- everything else is reporting.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import ma, state
from src.signals.moving_averages.features.liquidity import dollar_volume, relative_volume, vwma
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c1_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

LOOKBACKS = (20, 50, 200)
HORIZON = 21
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Robustness-check-only match set (same short-term-reversal confound check
# M1/M2/M6.3/M18 each ran once a cell survived): adds a prior-21-day-return
# tercile. Not the module's pre-registered default.
C2_MATCH_COLS_WITH_REVERSAL = (*C2_MATCH_COLS, "rev_tercile")

# PREREGISTRATION.md's M12 kill criterion: same 0.10% floor M1/M13 use.
KILL_THRESHOLD = 0.001

SUB_QUESTIONS = ("relative_volume", "dollar_volume", "vwma_divergence")


def future_state(panel: pd.DataFrame, state_col: str, horizon: int, ticker_col: str = "ticker") -> pd.Series:
    """What `state_col` will read `horizon` trading days from now, per
    ticker -- a forward-looking LABEL (parallel to
    `labels/forward_returns.py::forward_return`), not a lagged feature.
    CLAUDE.md invariant #2 (one-bar lag) constrains features used to
    *condition* on a forward outcome; a label is allowed to look forward
    by construction, same status as `forward_return`/`forward_realized_vol`.
    NaN for the final `horizon` rows of each ticker's history, where no
    future state value exists yet.
    """
    return panel.groupby(ticker_col)[state_col].shift(-horizon)


def _is_reclaim(panel: pd.DataFrame, above_col: str, ticker_col: str = "ticker") -> pd.Series:
    """Boolean mask: the first day of an `above_col` run (a state-transition
    from below to above), excluding the left-censored first run per ticker
    (PREREGISTRATION.md's "Event population" -- reuses `features/state.py`'s
    run-length primitives directly on the cached panel's already-lagged
    `above_col`, safe because a uniform one-day shift doesn't change run
    structure). NaN (treated as not-a-reclaim) where `state_run_id` itself
    is NaN (the MA's own warmup region).
    """
    result = pd.Series(False, index=panel.index)
    for _, group in panel.groupby(ticker_col, sort=False):
        run_id = state.state_run_id(group[above_col])
        days = state.days_in_run(group[above_col], run_id=run_id)
        is_reclaim = (days == 1) & (run_id != 0) & group[above_col].astype("boolean").fillna(False)
        result.loc[group.index] = is_reclaim.reindex(group.index).fillna(False)
    return result


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, the three raw
    volume/liquidity features (lagged), their whole-panel per-date
    terciles, the reclaim-event flags at each lookback, and the
    reclaim-hold labels to `panel`. Returns a new frame; `panel` itself is
    not mutated.

    The three new raw features are computed from `panel`'s own un-lagged
    `close`/`volume` columns (`_NON_FEATURE_COLUMNS` in `features/panel.py`
    -- never lagged by `build_panel` itself), then passed through
    `apply_lag` here, the same division of labor `modules/
    context_conditioning.py`'s `vix_tercile` join uses for a feature added
    outside `_build_ticker_features`.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["rev_tercile"] = cross_sectional_bucket(working, "mom_1_0", n_buckets=3)

    # Row-wise (no grouping needed) and per-ticker rolling features, both
    # via `.groupby("ticker").transform`/`.apply` -- vectorised across the
    # panel via pandas' own grouped engine (CLAUDE.md's Style section, same
    # per-group-callback idiom `stats.controls.cross_sectional_bucket`
    # already uses), not a hand-rolled per-ticker Python loop. `panel` is
    # already sorted by (ticker, date) (`read_panel`'s own contract), so a
    # grouped rolling transform respects each ticker's own chronological
    # order.
    working["dollar_volume_raw"] = dollar_volume(working["close"], working["volume"])
    working["relative_volume_raw"] = working.groupby("ticker")["volume"].transform(relative_volume)
    for lookback in LOOKBACKS:
        working[f"vwma_{lookback}_raw"] = working.groupby("ticker", group_keys=False).apply(
            lambda g, w=lookback: vwma(g["close"], g["volume"], w), include_groups=False
        )

    raw_cols = ["relative_volume_raw", "dollar_volume_raw"] + [f"vwma_{lb}_raw" for lb in LOOKBACKS]
    working = apply_lag(working, raw_cols)

    for lookback in LOOKBACKS:
        sma_col = ma.ma_column_name("sma", lookback)
        vwma_col = f"vwma_{lookback}_raw"
        working[f"vwma_divergence_{lookback}"] = working[vwma_col] / working[sma_col] - 1

    working["relative_volume"] = working["relative_volume_raw"]
    working["dollar_volume"] = working["dollar_volume_raw"]

    working["relative_volume_tercile"] = cross_sectional_bucket(working, "relative_volume", n_buckets=3)
    working["dollar_volume_tercile"] = cross_sectional_bucket(working, "dollar_volume", n_buckets=3)
    for lookback in LOOKBACKS:
        working[f"vwma_divergence_{lookback}_tercile"] = cross_sectional_bucket(
            working, f"vwma_divergence_{lookback}", n_buckets=3
        )

    for lookback in LOOKBACKS:
        ma_col = ma.ma_column_name("sma", lookback)
        above_col = f"above_{ma_col}"
        working[f"is_reclaim_{lookback}"] = _is_reclaim(working, above_col)
        working[f"hold_{lookback}"] = future_state(working, above_col, HORIZON).astype("boolean")

    return working


def _facet_col(sub_question: str, lookback: int) -> str:
    if sub_question == "relative_volume":
        return "relative_volume_tercile"
    if sub_question == "dollar_volume":
        return "dollar_volume_tercile"
    if sub_question == "vwma_divergence":
        return f"vwma_divergence_{lookback}_tercile"
    raise ValueError(f"Unknown sub_question: {sub_question!r} (expected one of {SUB_QUESTIONS})")


def _cell(
    reclaim_pop: pd.DataFrame,
    facet_col: str,
    value_col: str,
    label: dict,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
) -> dict:
    """One (sub_question, lookback) cell: restrict the reclaim-event
    population to top+bottom facet tercile, then C1/C2 delta of
    `value_col` between the two halves. Same "restrict-then-delta" shape
    as `modules/context_conditioning.py::_cell`, specialized to a
    top-vs-bottom-tercile group column instead of a boolean state column.
    """
    restricted = reclaim_pop[reclaim_pop[facet_col].isin([0, 2])].dropna(
        subset=[facet_col, value_col, *match_cols]
    )
    restricted = restricted.assign(_is_top=restricted[facet_col] == 2)
    event_rows = restricted[restricted["_is_top"]]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(restricted, "_is_top", value_col, match_cols=list(match_cols))
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"),
                "n_dates": restricted["date"].nunique() if len(restricted) else 0}

    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])

    return {
        **label,
        "n_events": n_events,
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c1": c1_delta(restricted, "_is_top", value_col) if len(restricted) else float("nan"),
        "c2": boot["point_estimate"],
        "c2_ci_low": boot["ci_low"],
        "c2_ci_high": boot["ci_high"],
        "c2_n_dates_boot": boot["n_dates"],
        "kill_threshold": KILL_THRESHOLD,
        "edge": edge,
        "killed": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
    }


def reclaim_durability_table(panel: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 9 counted primary cells: 3 sub-questions x 3 lookbacks, each on
    `fwd_ret_21`, restricted to that lookback's reclaim-event population
    and that sub-question's facet's top/bottom tercile. `panel` must
    already be `prepare()`'d.
    """
    rows = []
    for lookback in LOOKBACKS:
        reclaim_pop = panel[panel[f"is_reclaim_{lookback}"]]
        for sub_question in SUB_QUESTIONS:
            facet_col = _facet_col(sub_question, lookback)
            rows.append(
                _cell(
                    reclaim_pop, facet_col, "fwd_ret_21",
                    {"sub_question": sub_question, "lookback": lookback},
                    match_cols=match_cols,
                )
            )
    return pd.DataFrame(rows)


def reclaim_hold_rate_table(panel: pd.DataFrame, match_cols: tuple[str, ...] = C2_MATCH_COLS) -> pd.DataFrame:
    """The 3 hold-rate companion cells (sub-question 1, relative volume,
    only -- PREREGISTRATION.md's "Durability's secondary facet"): does a
    high-relative-volume reclaim more often still hold 21 trading days
    later than a low-relative-volume reclaim? Secondary -- no kill
    authority of its own, same status as M1's run-length layer.
    """
    rows = []
    for lookback in LOOKBACKS:
        reclaim_pop = panel[panel[f"is_reclaim_{lookback}"]]
        working = reclaim_pop.copy()
        working["_hold_float"] = working[f"hold_{lookback}"].astype("float64")
        rows.append(
            _cell(
                working, "relative_volume_tercile", "_hold_float",
                {"sub_question": "relative_volume", "lookback": lookback},
                match_cols=match_cols,
            )
        )
    return pd.DataFrame(rows)


def evaluate_kill_criterion(primary: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M12 kill criterion, applied to the 9 counted
    primary cells: `kill_cell := max(|ci_low|, |ci_high|) < 0.10%`.
    Module-level kill fires iff every primary cell satisfies `kill_cell`
    (any one surviving sub-question/lookback keeps the module alive, the
    same "any primary cell survives" logic as M1's own
    `evaluate_kill_criterion`, generalized from 6 cells to 9).
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
