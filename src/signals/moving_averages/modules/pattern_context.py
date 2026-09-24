"""M14 -- Integration with existing detectors (DESIGN.md lines ~977-979;
PREREGISTRATION.md, 2026-09-25).

Track B. DESIGN's own framing: "does an MA event fired *inside* one of
your existing detected patterns behave differently?" This module joins
M1's own `above_sma_50` reclaim-event construction (state-transition into
`above`, reused unchanged from `features/state.py`'s run-length
primitives) against `src/signals/patterns/` (a separate repo subsystem:
double-top/bottom, head & shoulders, triangles/wedges, cup & handle, VCP,
rounding, flags/pennants), asking whether a reclaim that occurs shortly
after a high-confidence pattern breakout differs from one that doesn't.

**"Inside a detected pattern" needed a real definition, not the literal
DESIGN wording taken naively** -- checked directly (not assumed) before
building the decisive test: the patterns subsystem's own scanner emits a
very large, heavily-overlapping candidate set (119,140 matches across 405
tickers in the 2010-2021 dev window alone, all statuses/types/confidence
levels included). Using the literal "MA event date falls inside ANY
detected pattern's own formation window" produces 99%+ single-ticker
coverage of all trading days (AAPL: 99.5%) -- an unusable, non-selective
flag by construction, not a result. Restricting to breakout-confirmed
statuses only (confirmed/active/hit_target/invalidated_failed_breakout)
barely moves this (99.2%). Restricting further to a 21-trading-day window
after `formation_end` (this study's own standard forward horizon, not a
new one invented for this check) still leaves 79% coverage. **Only
adding a confidence floor (`confidence >= 0.7`, the scanner's own top ~19%
of all candidates by its own continuous score, a round pre-specified cut
not tuned to this test's own outcome) produces a genuinely selective flag
(36% coverage for AAPL)** -- this is the definition actually used below,
named here in full so the choice is auditable, not silently arrived at.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.signals.moving_averages.features import state
from src.signals.moving_averages.stats.controls import c2_eligible_mask, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
BREAKOUT_STATUSES = ("confirmed", "active", "hit_target", "invalidated_failed_breakout")
CONFIDENCE_FLOOR = 0.7
POST_BREAKOUT_WINDOW_DAYS = 21
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
KILL_THRESHOLD = 0.001


def load_qualifying_patterns(
    derived_conn: sqlite3.Connection, tickers: list[str], as_of: str,
) -> pd.DataFrame:
    """Breakout-confirmed, confidence>=0.7, holdout-bounded (formation_end
    <= as_of) pattern matches for `tickers`. Returns
    ticker/formation_end (as Timestamp), one row per qualifying pattern
    instance -- not deduplicated across overlapping patterns of different
    types on the same ticker (a ticker legitimately can have more than one
    qualifying breakout in a year).
    """
    placeholders = ",".join("?" * len(tickers))
    query = f"""
        SELECT ticker, formation_start, formation_end, status, confidence
        FROM pattern_matches
        WHERE ticker IN ({placeholders})
          AND status IN ({','.join('?' * len(BREAKOUT_STATUSES))})
          AND confidence >= ?
          AND breakout_bar IS NOT NULL
          AND formation_end <= ?
    """
    params = [*tickers, *BREAKOUT_STATUSES, CONFIDENCE_FLOOR, as_of]
    df = pd.read_sql(query, derived_conn, params=params)
    df["formation_start"] = pd.to_datetime(df["formation_start"])
    df["formation_end"] = pd.to_datetime(df["formation_end"])
    return df


def add_pattern_context_flag(panel: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    """Adds `in_pattern_context`: True if `date` falls within
    [formation_end, formation_end + POST_BREAKOUT_WINDOW_DAYS trading
    days] of any qualifying pattern for that ticker. Vectorised per
    ticker (not a Python double-loop over the whole panel) -- `patterns`
    is small enough per ticker (tens, not thousands) that a per-ticker
    interval scan is cheap. Returns a new frame; `panel` itself is not
    mutated.
    """
    working = panel.copy()
    working["in_pattern_context"] = False
    if patterns.empty:
        return working

    window_end = patterns["formation_end"] + pd.tseries.offsets.BDay(POST_BREAKOUT_WINDOW_DAYS)
    patterns = patterns.assign(window_end=window_end)

    flag = pd.Series(False, index=working.index)
    for ticker, group in patterns.groupby("ticker"):
        ticker_rows = working["ticker"] == ticker
        if not ticker_rows.any():
            continue
        dates = working.loc[ticker_rows, "date"]
        in_any = pd.Series(False, index=dates.index)
        for _, row in group.iterrows():
            in_any |= (dates >= row["formation_end"]) & (dates <= row["window_end"])
        flag.loc[in_any.index] = in_any

    working["in_pattern_context"] = flag
    return working


def prepare(panel: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    """Adds `is_reclaim_50` (M1's own above_sma_50 reclaim construction,
    reused unchanged), the C2 match buckets, `fwd_ret_21`, and
    `in_pattern_context`. Returns a new frame; `panel` itself is not
    mutated.
    """
    from src.signals.moving_averages.labels.forward_returns import forward_return

    working = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    result = pd.Series(False, index=working.index)
    for _, group in working.groupby("ticker", sort=False):
        run_id = state.state_run_id(group["above_sma_50"])
        days = state.days_in_run(group["above_sma_50"], run_id=run_id)
        is_reclaim = (
            (days == 1) & (run_id != 0) & group["above_sma_50"].astype("boolean").fillna(False)
        )
        result.loc[group.index] = is_reclaim.reindex(group.index).fillna(False)
    working["is_reclaim_50"] = result

    working = add_pattern_context_flag(working, patterns)
    return working


def decisive_test(working: pd.DataFrame) -> dict:
    """The module's one pre-registered decisive cell: among `above_sma_50`
    reclaim events, does `fwd_ret_21` differ between reclaims that occur
    `in_pattern_context` (True) vs. not (False)? C2-matched
    (`mom_tercile`/`vol_tercile`/`sector`), block-bootstrap delta.
    """
    events = working[working["is_reclaim_50"]].copy()
    subset = events.dropna(subset=["fwd_ret_21", *C2_MATCH_COLS])
    n_events = len(subset)
    n_dates = subset["date"].nunique()
    n_tickers = subset["ticker"].nunique()
    n_in_context = int(subset["in_pattern_context"].sum())
    n_out_context = int((~subset["in_pattern_context"]).sum())

    below_threshold = (
        n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS
        or n_in_context < MIN_EVENTS or n_out_context < MIN_EVENTS
    )

    try:
        boot = block_bootstrap_delta(
            subset, "in_pattern_context", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)
        )
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "point_estimate": float("nan"),
                "n_dates": subset["date"].nunique() if len(subset) else 0}

    return {
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "n_in_context": n_in_context, "n_out_context": n_out_context,
        "below_threshold": below_threshold,
        "c2": boot["point_estimate"], "c2_ci_low": boot["ci_low"], "c2_ci_high": boot["ci_high"],
    }


def evaluate_kill_criterion(result: dict) -> dict:
    """PREREGISTRATION.md's M14 kill criterion: `module_killed := CI
    includes zero OR max(|ci_low|,|ci_high|) < 0.10%`.
    """
    ci_low, ci_high = result["c2_ci_low"], result["c2_ci_high"]
    if ci_low != ci_low or ci_high != ci_high:  # NaN check without importing math/numpy here
        return {"module_killed": True, "reason": "insufficient_blocks_or_data"}
    ci_excludes_zero = ci_low > 0 or ci_high < 0
    edge = max(abs(ci_low), abs(ci_high))
    module_killed = (not ci_excludes_zero) or edge < KILL_THRESHOLD
    return {"module_killed": module_killed, "ci_excludes_zero": ci_excludes_zero, "edge": edge}
