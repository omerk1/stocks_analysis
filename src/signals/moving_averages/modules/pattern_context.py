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
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS

MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
# Statuses the 2026-09-25 run filtered on. Kept for the record only: every one
# of them (and `expired_unresolved`) is assigned by `patterns/lifecycle.py`
# *after* the breakout bar, so filtering on status uses the pattern's outcome.
# The as-of-safe qualifier (2026-09-29) is `breakout_bar IS NOT NULL` alone --
# "a breakout has printed" -- with the window anchored at that bar's date.
BREAKOUT_STATUSES = ("confirmed", "active", "hit_target", "invalidated_failed_breakout")
CONFIDENCE_FLOOR = 0.7
POST_BREAKOUT_WINDOW_DAYS = 21
PATTERN_TIMEFRAME = "daily"
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")
KILL_THRESHOLD = 0.001


def load_qualifying_patterns(
    derived_conn: sqlite3.Connection, tickers: list[str], as_of: str,
) -> pd.DataFrame:
    """Confidence>=0.7, holdout-bounded (formation_end <= as_of) pattern
    matches with a breakout on record (`breakout_bar IS NOT NULL`) for
    `tickers`. Returns ticker/formation_start/formation_end (as Timestamp)/
    status/confidence/`pattern_type`/`breakout_bar`/`entry_price`, one row
    per qualifying pattern instance -- not deduplicated across overlapping
    patterns of different types on the same ticker.

    2026-09-29 (as-of-safe re-run, PREREGISTRATION.md M14 addendum): the
    2026-09-25 run additionally filtered on `status IN BREAKOUT_STATUSES`.
    Every status is assigned by the lifecycle *after* the breakout bar
    (`hit_target` after the target prints, `invalidated_failed_breakout`
    after the reclaim window closes), so that filter selected patterns by
    their outcome. Dropped; `breakout_bar IS NOT NULL` is the whole
    qualifier now, and `attach_breakout_dates` turns the bar index into
    the date the breakout became knowable.
    """
    placeholders = ",".join("?" * len(tickers))
    query = f"""
        SELECT ticker, formation_start, formation_end, status, confidence, pattern_type,
               breakout_bar, entry_price
        FROM pattern_matches
        WHERE ticker IN ({placeholders})
          AND timeframe = ?
          AND confidence >= ?
          AND breakout_bar IS NOT NULL
          AND formation_end <= ?
    """
    params = [*tickers, PATTERN_TIMEFRAME, CONFIDENCE_FLOOR, as_of]
    df = pd.read_sql(query, derived_conn, params=params)
    df["formation_start"] = pd.to_datetime(df["formation_start"])
    df["formation_end"] = pd.to_datetime(df["formation_end"])
    return df


def attach_breakout_dates(
    patterns: pd.DataFrame, raw_conn: sqlite3.Connection, as_of: str,
    price_tolerance: float = 1e-6,
) -> pd.DataFrame:
    """Adds `breakout_date`: the timestamp of `breakout_bar`, a positional
    index into the bars `patterns.scanner.detect` scanned -- i.e.
    `market_common.data.load_and_validate(conn, ticker, "1d", as_of=as_of)`
    in the same order. Verified per row: the bar's close must equal the
    stored `entry_price` (which the lifecycle sets to `closes[breakout_bar]`);
    rows that don't verify get `breakout_date = NaT` and are excluded by
    `add_pattern_context_flag` rather than guessed at. Holdout-safe: bars
    are loaded up to `as_of` only.
    """
    from src.foundation.market_common.data import load_and_validate

    working = patterns.copy()
    working["breakout_date"] = pd.NaT
    for ticker, group in working.groupby("ticker"):
        bars, _ = load_and_validate(raw_conn, ticker, "1d", as_of=as_of, basis=MODULE_PRICE_BASIS["moving_averages"])
        idx = group["breakout_bar"].astype(int).to_numpy()
        in_range = (idx >= 0) & (idx < len(bars))
        dates = pd.Series(pd.NaT, index=group.index, dtype="datetime64[ns]")
        closes = pd.Series(float("nan"), index=group.index)
        if in_range.any():
            dates.loc[group.index[in_range]] = pd.to_datetime(bars.index.to_numpy()[idx[in_range]])
            closes.loc[group.index[in_range]] = bars["close"].to_numpy()[idx[in_range]]
        verified = (closes - group["entry_price"]).abs() <= price_tolerance * group["entry_price"].abs().clip(lower=1.0)
        working.loc[group.index, "breakout_date"] = dates.where(verified)
    working["breakout_date"] = pd.to_datetime(working["breakout_date"])
    return working


def add_pattern_context_flag(panel: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    """Adds `in_pattern_context`: True if `date` falls within
    (`breakout_date`, `breakout_date` + POST_BREAKOUT_WINDOW_DAYS trading
    days] of any qualifying pattern for that ticker -- strictly *after* the
    breakout bar, so the flag on a date only uses a breakout that had
    already printed at the previous close (the same one-bar convention
    every lagged panel feature follows). Patterns with a missing
    `breakout_date` are ignored. Vectorised per ticker; returns a new
    frame, `panel` itself is not mutated.

    Before 2026-09-29 the window was anchored at `formation_end` and
    included dates before the breakout, so the flag encoded "this pattern
    *will* break out" (code review PR #118 C2, validation audit PR #120
    C.2). `breakout_date` is now required; see `attach_breakout_dates`.
    """
    if "breakout_date" not in patterns.columns:
        raise KeyError("patterns needs a `breakout_date` column -- run attach_breakout_dates first")
    working = panel.copy()
    working["in_pattern_context"] = False
    patterns = patterns.dropna(subset=["breakout_date"])
    if patterns.empty:
        return working

    window_end = patterns["breakout_date"] + pd.tseries.offsets.BDay(POST_BREAKOUT_WINDOW_DAYS)
    patterns = patterns.assign(window_end=window_end)

    flag = pd.Series(False, index=working.index)
    for ticker, group in patterns.groupby("ticker"):
        ticker_rows = working["ticker"] == ticker
        if not ticker_rows.any():
            continue
        dates = working.loc[ticker_rows, "date"]
        in_any = pd.Series(False, index=dates.index)
        for _, row in group.iterrows():
            in_any |= (dates > row["breakout_date"]) & (dates <= row["window_end"])
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
