"""M6.5 -- The SMA drop-off artefact (DESIGN.md, "M6.5 -- The SMA drop-off
artefact"; PREREGISTRATION.md, 2026-09-23).

Track B. DESIGN's own identity: SMAn(t) - SMAn(t-1) = (C_t - C_{t-n})/n. A
1-day sign flip in an SMA's own slope can therefore happen for two entirely
different reasons: today's close pushed the average past zero-slope (a real
price event), or an old bar rolled out of the trailing window (an artefact
of window composition, "nothing whatsoever happening in current price").
DESIGN's own example -- a 200-day SMA "rolling over" in March 2021,
substantially an artefact of March 2020 leaving the window -- sits inside
this study's own 2010-2021 dev window.

New machinery, module-local (not written to the shared panel cache or to
`features/slope.py`, same convention M6.1's `raw_return_k`/`block_mean_diff_log`
established for a sibling parallel module):
- A raw (unlagged) `n`-day SMA, recomputed directly from the panel's own
  raw `close` (the cached panel's own `sma_{n}` column is already lagged by
  `features/panel.py::apply_lag`, which is the wrong input for decomposing
  *this* day's own slope change -- that decomposition needs the exact,
  un-lagged day-over-day SMA difference).
- A day-over-day sign-flip event on that raw SMA's own 1-day slope
  (`raw_sma(t) - raw_sma(t-1)`) -- distinct from every other slope object
  in this study, which all use `slope_log_21` (a 21-day, log-scale slope).
  Only the *sign* of the 1-day raw slope is used here, never its magnitude
  as a cross-ticker-comparable quantity, so this does not conflict with
  CLAUDE.md invariant #7 ("Log scale for slopes... percentage and
  price-unit slopes are not comparable across tickers") -- the sign of
  `raw_sma(t) - raw_sma(t-1)` is identical to the sign of
  `ln(raw_sma(t)) - ln(raw_sma(t-1))` for any positive price series, so no
  information invariant #7 protects is actually being used.
- The entering/exiting decomposition itself, DESIGN's own algebraic split,
  referenced against the prior day's SMA value (the natural reference point
  for "how much did today's new bar push the average" vs. "how much did the
  bar leaving the window push it"):
  `entering = (C_t - raw_sma(t-1)) / n`, `exiting = (raw_sma(t-1) - C_{t-n}) / n`.
  `entering + exiting == raw_sma(t) - raw_sma(t-1)` exactly (verified in
  `tests/test_moving_averages_sma_dropoff.py`).
- A flip event is classified `price_driven` if `|entering| > |exiting|`,
  `dropoff_driven` otherwise (a tie is dropoff_driven by this module's own
  tie-break convention -- vanishingly rare on real float closes).

Every event/flip column here is a same-day (unlagged) construction and is
passed through `features/panel.py::apply_lag` before use, same as every
other module's newly-derived event flags (M6.3's `recent_large_move`,
M6.1's own local features) -- CLAUDE.md invariant #2, never bypassed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c2_delta, cross_sectional_bucket
from src.signals.moving_averages.stats.inference import (
    InsufficientBlocksError,
    block_bootstrap_delta,
)
from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas

# DESIGN §6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

HORIZON = 21
LOOKBACKS = (50, 200)
C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# Same 0.10% floor every return-valued cell in this study uses (M1/M2/M6.2/M6.3).
KILL_THRESHOLD = 0.001

TRADING_DAYS_PER_YEAR = 252


def _flip_event_col(lookback: int) -> str:
    return f"flip_event_sma_{lookback}"


def _flip_price_driven_col(lookback: int) -> str:
    return f"flip_price_driven_sma_{lookback}"


def _flip_dropoff_driven_col(lookback: int) -> str:
    return f"flip_dropoff_driven_sma_{lookback}"


def _flip_up_col(lookback: int) -> str:
    return f"flip_up_sma_{lookback}"


def _flip_down_col(lookback: int) -> str:
    return f"flip_down_sma_{lookback}"


def _raw_columns(lookback: int) -> list[str]:
    return [
        f"_flip_event_{lookback}",
        f"_flip_price_driven_{lookback}",
        f"_flip_dropoff_driven_{lookback}",
        f"_flip_up_{lookback}",
        f"_flip_down_{lookback}",
    ]


def _rename_map(lookback: int) -> dict[str, str]:
    return {
        f"_flip_event_{lookback}": _flip_event_col(lookback),
        f"_flip_price_driven_{lookback}": _flip_price_driven_col(lookback),
        f"_flip_dropoff_driven_{lookback}": _flip_dropoff_driven_col(lookback),
        f"_flip_up_{lookback}": _flip_up_col(lookback),
        f"_flip_down_{lookback}": _flip_down_col(lookback),
    }


def _add_raw_flip_columns(panel: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Adds this lookback's raw (unlagged, underscore-prefixed) flip/decomposition
    columns to `panel` (a copy is not made here -- `prepare` owns the single copy).
    Every quantity below is a same-day function of `close` alone (via a raw,
    locally-recomputed `n`-day SMA, never the cached panel's own lagged `sma_{n}`).
    """
    ticker = panel["ticker"]
    close = panel["close"]

    raw_sma = panel.groupby("ticker")["close"].transform(
        lambda s: s.rolling(lookback, min_periods=lookback).mean()
    )
    sma_prev = raw_sma.groupby(ticker).shift(1)
    close_exit = close.groupby(ticker).shift(lookback)

    sign = np.sign(raw_sma - sma_prev)
    prev_sign = sign.groupby(ticker).shift(1)

    # `valid` is the region where both this day's and the prior day's raw
    # slope sign are actually defined (past the MA's own warmup, plus one
    # more day for `prev_sign`). Every derived boolean below is computed on
    # the full (comparison-on-possibly-NaN) inputs first, then masked back
    # to NA outside `valid` via `.where` -- comparison operators return
    # False on NaN rather than propagating it (CLAUDE.md invariant #9), so
    # the mask step is required, not a defensive nicety.
    valid = sign.notna() & prev_sign.notna()
    flip_raw = (sign != 0) & (prev_sign != 0) & (sign != prev_sign)

    entering = (close - sma_prev) / lookback
    exiting = (sma_prev - close_exit) / lookback

    is_price_driven_raw = flip_raw & (entering.abs() > exiting.abs())
    is_dropoff_driven_raw = flip_raw & ~is_price_driven_raw

    panel[f"_flip_event_{lookback}"] = flip_raw.where(valid).astype("boolean")
    panel[f"_flip_price_driven_{lookback}"] = is_price_driven_raw.where(valid).astype("boolean")
    panel[f"_flip_dropoff_driven_{lookback}"] = is_dropoff_driven_raw.where(valid).astype("boolean")
    panel[f"_flip_up_{lookback}"] = (flip_raw & (sign > 0)).where(valid).astype("boolean")
    panel[f"_flip_down_{lookback}"] = (flip_raw & (sign < 0)).where(valid).astype("boolean")
    return panel


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, and every lookback's
    (already-lagged) flip/decomposition columns. Returns a new frame;
    `panel` itself is not mutated.
    """
    working = panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)

    all_raw_cols: list[str] = []
    for lookback in LOOKBACKS:
        working = _add_raw_flip_columns(working, lookback)
        all_raw_cols.extend(_raw_columns(lookback))

    working = apply_lag(working, all_raw_cols)
    for lookback in LOOKBACKS:
        working = working.rename(columns=_rename_map(lookback))
    return working


def event_frequency_per_ticker_year(
    panel: pd.DataFrame, event_col: str, ticker_col: str = "ticker",
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Descriptive-only event rate: total `event_col` True rows / total
    ticker-years of valid (non-NA) rows. Not a `signals_per_year`-style
    state-flip-turnover measure (`event_col` is already a point event, not
    a persistent state) -- reported for context, not as a cost hurdle input
    (this module makes no standalone tradeable claim -- see module result
    docstrings and `PREREGISTRATION.md`'s cost-tier note).
    """
    valid = panel[event_col].notna()
    ticker_years = valid.groupby(panel[ticker_col]).sum().sum() / trading_days_per_year
    if not ticker_years:
        return float("nan")
    n_events = panel.loc[valid, event_col].astype(bool).sum()
    return float(n_events) / ticker_years


def _bootstrap_or_nan(panel: pd.DataFrame, group_col: str, match_cols: tuple[str, ...],
                       block_length: int, n_boot: int, ci: float, seed: int) -> dict:
    try:
        return block_bootstrap_delta(
            panel, group_col, "fwd_ret_21", match_cols=list(match_cols),
            block_length=block_length, n_boot=n_boot, ci=ci, seed=seed,
        )
    except InsufficientBlocksError:
        return {"ci_low": float("nan"), "ci_high": float("nan"), "boot_std": float("nan"),
                "point_estimate": float("nan"), "n_dates": panel["date"].nunique() if len(panel) else 0}


def decisive_test(
    panel: pd.DataFrame, lookback: int, direction: str | None = None,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """The primary M6.5 decisive test: within slope-sign-flip events only,
    does `fwd_ret_21` differ between `price_driven` and `dropoff_driven`
    flips, C2-matched (date + momentum tercile + vol tercile + sector)?
    `panel` must already be `prepare()`'d.

    `direction` (None, `"up"`, `"down"`) optionally restricts to flips in
    one direction only (DESIGN's own literal example -- a 200-day SMA
    "rolling over" -- is a flip *down*); `None` pools both directions,
    this module's primary declared cell.
    """
    event_col = _flip_event_col(lookback)
    price_col = _flip_price_driven_col(lookback)
    dropoff_col = _flip_dropoff_driven_col(lookback)

    working = panel.dropna(subset=[event_col, "fwd_ret_21", *C2_MATCH_COLS]).copy()
    flips = working[working[event_col].astype(bool)].copy()
    if direction == "up":
        flips = flips[flips[_flip_up_col(lookback)].fillna(False).astype(bool)]
    elif direction == "down":
        flips = flips[flips[_flip_down_col(lookback)].fillna(False).astype(bool)]
    elif direction is not None:
        raise ValueError(f"direction must be None, 'up', or 'down' (got {direction!r})")

    flips["is_price_driven"] = flips[price_col].astype(bool)
    price_rows = flips[flips["is_price_driven"]]
    dropoff_rows = flips[~flips["is_price_driven"]]
    n_events = len(flips)
    n_dates = flips["date"].nunique()
    n_tickers = flips["ticker"].nunique()

    boot = _bootstrap_or_nan(flips, "is_price_driven", C2_MATCH_COLS, block_length, n_boot, ci, seed)
    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])

    return {
        "lookback": lookback,
        "direction": direction,
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "n_price_driven": len(price_rows), "n_dropoff_driven": len(dropoff_rows),
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "edge": edge, "kill_threshold": KILL_THRESHOLD,
        "killed": (edge < KILL_THRESHOLD) if not pd.isna(edge) else None,
        "ci_excludes_zero": ci_excludes_zero,
        # CLAUDE.md invariant #10 -- descriptive only.
        "shape": {
            **hit_rate_deltas(flips, "is_price_driven", "fwd_ret_21", match_cols=list(C2_MATCH_COLS)),
            **distribution_shape(price_rows["fwd_ret_21"]),
        },
    }


def type_vs_background(
    panel: pd.DataFrame, lookback: int, flip_type: str,
    block_length: int = 42, n_boot: int = 500, ci: float = 0.90, seed: int = 0,
) -> dict:
    """Secondary diagnostic: this flip type's own C2 delta vs. an
    ordinary, non-flip day (the *other* flip type is excluded from the
    comparison population entirely, not folded into the control -- a
    dropoff-driven flip's own background must be "no flip today," not "no
    flip today, plus every price-driven flip," or a real price-driven
    effect would leak into the dropoff-driven reading through a shared
    control group with a mixed composition). Not the decisive test (that's
    `decisive_test`, the direct price-driven-vs-dropoff-driven comparison
    this module's kill criterion is written against) -- this answers "does
    this type show a detectable effect at all," which DESIGN's own
    hypothesis needs both halves of ("price-driven carries information;
    drop-off-driven carries none") checked, not just their difference.
    `panel` must already be `prepare()`'d. `flip_type` is `"price"` or
    `"dropoff"`.
    """
    if flip_type == "price":
        group_col, other_col = _flip_price_driven_col(lookback), _flip_dropoff_driven_col(lookback)
    elif flip_type == "dropoff":
        group_col, other_col = _flip_dropoff_driven_col(lookback), _flip_price_driven_col(lookback)
    else:
        raise ValueError(f"flip_type must be 'price' or 'dropoff' (got {flip_type!r})")

    working = panel.dropna(subset=[group_col, other_col, "fwd_ret_21", *C2_MATCH_COLS]).copy()
    working = working[~working[other_col].astype(bool)]
    event_rows = working[working[group_col].astype(bool)]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    boot = _bootstrap_or_nan(working, group_col, C2_MATCH_COLS, block_length, n_boot, ci, seed)
    edge = max(abs(boot["ci_low"]), abs(boot["ci_high"])) if not pd.isna(boot["ci_low"]) else float("nan")
    ci_excludes_zero = None if pd.isna(boot["ci_low"]) else not (boot["ci_low"] <= 0 <= boot["ci_high"])

    return {
        "lookback": lookback, "flip_type": flip_type,
        "n_events": n_events, "n_dates": n_dates, "n_tickers": n_tickers,
        "below_threshold": (
            n_events < MIN_EVENTS or n_dates < MIN_DATES or n_tickers < MIN_TICKERS or pd.isna(boot["ci_low"])
        ),
        "c2": boot["point_estimate"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "edge": edge, "ci_excludes_zero": ci_excludes_zero,
    }


def run_grid(panel: pd.DataFrame) -> dict:
    """Full pre-registered M6.5 grid: the primary pooled `decisive_test`
    per lookback, the `up`/`down` direction-split companions, each type's
    own `type_vs_background` diagnostic, and descriptive event frequencies.
    """
    prepared = prepare(panel)
    result: dict = {"decisive": {}, "decisive_by_direction": {}, "vs_background": {}, "event_frequency": {}}
    for lookback in LOOKBACKS:
        result["decisive"][lookback] = decisive_test(prepared, lookback)
        result["decisive_by_direction"][(lookback, "up")] = decisive_test(prepared, lookback, direction="up")
        result["decisive_by_direction"][(lookback, "down")] = decisive_test(prepared, lookback, direction="down")
        result["vs_background"][(lookback, "price")] = type_vs_background(prepared, lookback, "price")
        result["vs_background"][(lookback, "dropoff")] = type_vs_background(prepared, lookback, "dropoff")
        result["event_frequency"][lookback] = {
            "price_driven": event_frequency_per_ticker_year(prepared, _flip_price_driven_col(lookback)),
            "dropoff_driven": event_frequency_per_ticker_year(prepared, _flip_dropoff_driven_col(lookback)),
        }
    return result
