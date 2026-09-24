"""M10 -- Timeframe and sampling (DESIGN.md lines ~945-949;
PREREGISTRATION.md, 2026-09-24).

Track B. See PREREGISTRATION.md for the full hypothesis/kill-criterion/
scope statement. DESIGN's own three-way design, kept intact rather than
collapsed to two:
  (a) daily SMA{50,150,200}, evaluated on every daily row
  (b) weekly-native SMA{10,30,40} (built on genuinely weekly-aggregated
      bars, `features/panel.py::build_panel(timeframe=Timeframe.WEEKLY)`),
      evaluated on every weekly row (each already Friday-close-derived,
      `resample.to_weekly`'s own convention -- see that function and
      `build_panel`'s own updated docstring)
  (c) the same daily SMA{50,150,200} from (a), but the C2 comparison
      restricted to literal Friday calendar rows only -- DESIGN's own
      named "key control", isolating sampling frequency from lookback.

Lookback pairing (a)/(c) vs (b) is calendar-equivalent, not arbitrary:
50 daily bars ~= 10 weekly bars, 150 ~= 30, 200 ~= 40 (5 trading
days/week). This is DESIGN's own "lookback-equivalent" framing (M9's
section title), preserved here as the pairing the decomposition below
actually uses.

Decomposition (DESIGN's own ask -- "decompose any weekly advantage into
lag effect vs. sampling effect"), read as two separate, cleanly-isolated
comparisons rather than one confounded (a)-vs-(b) number:
  - **Sampling-frequency effect** = (c) - (a), same lookback, same
    underlying daily bars and MA construction, only the evaluation-date
    subset differs. This is the single-variable-isolated test DESIGN
    calls "the key control".
  - **Bar-aggregation ("lag") effect** = (b) - (c), matched
    calendar-equivalent lookback pairs, both evaluated at weekly cadence
    -- isolates whether *genuinely aggregating into weekly bars before
    computing the MA* (a different effective center-of-mass/lag than a
    daily MA of the same nominal calendar span) changes anything, holding
    sampling frequency fixed.
  - The naive, confounded (a)-vs-(b) comparison (what a practitioner means
    by "weekly vs. daily") is reported too, as context for the
    decomposition, not as a third independent test.

Statistical caveat, stated plainly rather than overclaimed: the
sampling-frequency and bar-aggregation "effects" above are **descriptive
point-estimate gaps between two independently-bootstrapped C2 deltas**,
not a single jointly-bootstrapped difference-of-deltas CI (that would need
new paired-bootstrap machinery `stats/inference.py` doesn't have yet, out
of scope to build for this module). Same rigor level as M6.3's own
rising-tail-vs-falling-tail decomposition (`FINDINGS.md`), which used the
identical "two separate CIs, read qualitatively" convention -- not a
weaker standard invented here.
"""

from __future__ import annotations

import pandas as pd

from src.signals.moving_averages.features import ma
from src.signals.moving_averages.features.panel import apply_lag
from src.signals.moving_averages.labels.forward_returns import forward_return
from src.signals.moving_averages.stats.controls import c2_eligible_mask, cross_sectional_bucket
from src.signals.moving_averages.stats.costs import cost_hurdle, signals_per_year
from src.signals.moving_averages.stats.inference import InsufficientBlocksError, block_bootstrap_delta

# DESIGN Sec6.9, same numbers as every other module.
MIN_EVENTS = 200
MIN_DATES = 30
MIN_TICKERS = 30

DAILY_HORIZON = 21
WEEKLY_HORIZON = 4  # ~1 month of weekly bars, the natural weekly analogue
                    # of the study's own 21-trading-day standard horizon --
                    # not an exact calendar match (21/5 = 4.2), a labeled
                    # approximation, same convention as costs.py's own
                    # linear-annualization disclaimer.

C2_MATCH_COLS = ("mom_tercile", "vol_tercile", "sector")

# DESIGN's own calendar-equivalent pairing (5 trading days/week).
DAILY_LOOKBACKS = (50, 150, 200)
WEEKLY_LOOKBACKS = (10, 30, 40)
LOOKBACK_PAIRS = dict(zip(WEEKLY_LOOKBACKS, DAILY_LOOKBACKS))  # weekly -> matched daily

TRADING_DAYS_PER_YEAR = 252
WEEKS_PER_YEAR = 52

# This module's own kill criterion (DESIGN gives no literal numeric floor
# for M10, unlike M8/M9) -- same 0.10% magnitude floor this study's other
# modules use for "is this gap big enough to call detectable at all"
# (M1/M13's own KILL_THRESHOLD), applied here to the *gap* between two
# cells' point estimates, not to a single cell's own CI edge.
GAP_FLOOR = 0.001


def prepare_daily(daily_panel: pd.DataFrame) -> pd.DataFrame:
    """Adds `fwd_ret_21`, the C2 match buckets, and `is_friday` to the
    already-cached daily panel. Returns a new frame; `daily_panel` itself
    is not mutated.
    """
    working = daily_panel.copy()
    working["fwd_ret_21"] = forward_return(working, horizon=DAILY_HORIZON)
    working["mom_tercile"] = cross_sectional_bucket(working, "mom_12_1", n_buckets=3)
    working["vol_tercile"] = cross_sectional_bucket(working, "realized_vol_63", n_buckets=3)
    working["is_friday"] = pd.to_datetime(working["date"]).dt.weekday == 4
    return working


def prepare_weekly(weekly_panel: pd.DataFrame, daily_working: pd.DataFrame) -> pd.DataFrame:
    """Adds local (not shared-panel) SMA{10,30,40} -- `build_panel`'s own
    weekly output only has SMA at the shared {20,50,150,200} grid, in
    weekly bars, which is not DESIGN's named weekly lookback set -- built
    the same way M3/M6.6 added their own local, non-shared-grid lookbacks.
    One-week lag via `apply_lag` (row-order-based, timeframe-agnostic).
    `fwd_ret_4` (this module's weekly horizon).

    C2 match columns `mom_tercile`/`vol_tercile` are **joined from
    `daily_working`** (already correctly day-count-calibrated), via
    `merge_asof` per ticker (`direction="backward"`) rather than
    recomputed on weekly bars -- `build_panel`'s own docstring names this
    exact gap: `mom_12_1`/`realized_vol_63` are day-count-calibrated and
    silently wrong if naively recomputed on weekly-resampled bars. Each
    weekly row's own (already 1-week-lagged) features reflect information
    as of the prior week's Friday close; the nearest on-or-before daily
    row (itself 1-day-lagged) reflects the same effective information
    time, so the two align correctly without needing exact-date matches.
    `sector` is *not* part of this join -- `build_panel` already joins it
    independently onto the weekly panel itself (same current-state-only
    value either way), and including it here would collide with that
    existing column, which `merge_asof` resolves by silently renaming both
    to `sector_x`/`sector_y` rather than erroring at the merge call itself
    (found against the real panel, not caught by the synthetic fixture
    tests until one was added with its own `sector` column -- see
    `tests/test_moving_averages_timeframe_sampling.py`).
    """
    working = weekly_panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    new_cols = [ma.ma_column_name("sma", lb) for lb in WEEKLY_LOOKBACKS]
    for lb, col in zip(WEEKLY_LOOKBACKS, new_cols):
        working[col] = working.groupby("ticker")["close"].transform(lambda s, lb=lb: ma.compute_ma(s, "sma", lb))
        above = (working["close"] > working[col]).astype("boolean")
        working[f"above_{col}"] = above.mask(working[col].isna())
    working = apply_lag(working, columns=[*new_cols, *[f"above_{c}" for c in new_cols]])
    working["fwd_ret_4"] = forward_return(working, horizon=WEEKLY_HORIZON)

    # `sector` is deliberately NOT joined here -- `build_panel` already
    # joins it independently onto both the daily and weekly panels (it's
    # current-state-only, not time-varying, so either source is the same
    # value), and including it in this merge would collide with the
    # weekly panel's own `sector` column, silently renaming both to
    # `sector_x`/`sector_y` (confirmed against the real panel: this
    # exact collision raised `KeyError: 'sector' not in index` two frames
    # downstream, not at the merge call itself). The weekly panel's own
    # `sector` column is used as-is.
    controls = daily_working[["ticker", "date", "mom_tercile", "vol_tercile"]].dropna(
        subset=["date"]
    ).copy()
    # `merge_asof` requires both frames globally sorted by the `on` key
    # (date) -- sorting by (ticker, date) only leaves date non-monotonic
    # across ticker boundaries, which `merge_asof`'s `by="ticker"` grouping
    # does not relax (confirmed the hard way: it raises "left keys must be
    # sorted" on a >1-ticker frame sorted only within each ticker group).
    # It also requires *matching* datetime precision -- a real cached
    # (parquet-round-tripped) daily panel's `date` column comes back as
    # datetime64[us], while the freshly-resampled weekly panel's is
    # datetime64[ns]; `merge_asof` raises `MergeError` on that mismatch
    # rather than silently coercing (confirmed against the real panel, not
    # a synthetic-fixture-only assumption).
    working = working.copy()
    working["date"] = pd.to_datetime(working["date"]).astype("datetime64[ns]")
    controls["date"] = pd.to_datetime(controls["date"]).astype("datetime64[ns]")
    working_by_date = working.sort_values("date")
    controls_by_date = controls.sort_values("date")
    merged = pd.merge_asof(
        working_by_date, controls_by_date, on="date", by="ticker", direction="backward",
    )
    return merged.sort_values(["ticker", "date"]).reset_index(drop=True)


def _cell(
    working: pd.DataFrame, group_col: str, value_col: str, label: dict,
    match_cols: tuple[str, ...] = C2_MATCH_COLS,
) -> dict:
    """One (construction, lookback) cell's C2 delta -- reuses this
    study's standard `c2_eligible_mask`/`block_bootstrap_delta` machinery
    unchanged, same pattern `modules/baseline_state.py::_cell_row` and
    every sibling module's own `_cell_row` use.
    """
    unrestricted = working.dropna(subset=[group_col, value_col])
    mask = c2_eligible_mask(working, group_col, value_col, match_cols=list(match_cols))
    restricted = working[mask]

    event_rows = restricted[restricted[group_col].astype(bool)]
    n_events, n_dates, n_tickers = len(event_rows), event_rows["date"].nunique(), event_rows["ticker"].nunique()

    try:
        boot = block_bootstrap_delta(restricted, group_col, value_col, match_cols=list(match_cols))
    except InsufficientBlocksError:
        boot = {"ci_low": float("nan"), "ci_high": float("nan"), "point_estimate": float("nan"),
                "n_dates": restricted["date"].nunique() if len(restricted) else 0}

    return {
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
    }


def primary_cell_table(daily_working: pd.DataFrame, weekly_working: pd.DataFrame) -> pd.DataFrame:
    """9 primary cells: (a) all-days + (c) Fridays-only at each of
    DAILY_LOOKBACKS (6 cells), plus (b) weekly-native at each of
    WEEKLY_LOOKBACKS (3 cells).
    """
    rows = []
    for lb in DAILY_LOOKBACKS:
        col = f"above_sma_{lb}"
        rows.append(_cell(daily_working, col, "fwd_ret_21", {"construction": "a_daily_alldays", "lookback": lb}))
        friday_rows = daily_working[daily_working["is_friday"]]
        rows.append(_cell(friday_rows, col, "fwd_ret_21", {"construction": "c_daily_fridays_only", "lookback": lb}))
    for lb in WEEKLY_LOOKBACKS:
        col = f"above_sma_{lb}"
        rows.append(_cell(weekly_working, col, "fwd_ret_4", {"construction": "b_weekly_native", "lookback": lb}))
    return pd.DataFrame(rows)


def decomposition_table(primary: pd.DataFrame) -> pd.DataFrame:
    """Descriptive point-estimate gaps -- NOT a jointly-bootstrapped
    difference CI (see module docstring's statistical caveat). One row
    per lookback pair: sampling-frequency gap (c - a) and bar-aggregation
    gap (b - c), both in the same fwd-return units (b's gap is 4-week vs.
    21-trading-day, not rescaled -- reported as-is, not annualized to a
    false precision).
    """
    by_key = {(r["construction"], r["lookback"]): r for r in primary.to_dict("records")}
    rows = []
    for weekly_lb, daily_lb in LOOKBACK_PAIRS.items():
        a = by_key[("a_daily_alldays", daily_lb)]
        c = by_key[("c_daily_fridays_only", daily_lb)]
        b = by_key[("b_weekly_native", weekly_lb)]
        rows.append({
            "daily_lookback": daily_lb,
            "weekly_lookback": weekly_lb,
            "sampling_frequency_gap_c_minus_a": c["c2"] - a["c2"],
            "a_ci": (a["c2_ci_low"], a["c2_ci_high"]),
            "c_ci": (c["c2_ci_low"], c["c2_ci_high"]),
            "bar_aggregation_gap_b_minus_c": b["c2"] - c["c2"],
            "b_ci": (b["c2_ci_low"], b["c2_ci_high"]),
            "naive_gap_b_minus_a": b["c2"] - a["c2"],
        })
    return pd.DataFrame(rows)


def evaluate_kill_criterion(decomposition: pd.DataFrame) -> dict:
    """PREREGISTRATION.md's M10 kill criterion: the sampling-frequency
    gap (c - a) is read as detectable at a lookback only if it exceeds
    `GAP_FLOOR` in magnitude AND the two cells' CIs don't comfortably
    contain each other's point estimate (a cheap, honest stand-in for a
    real difference test -- see module docstring). If NONE of the 3
    lookbacks shows a detectable sampling-frequency gap, declare "no
    advantage from evaluating on a reduced/weekly cadence per se -- any
    apparent weekly-vs-daily advantage in the naive comparison must come
    from the lookback/bar-aggregation choice, not sampling frequency."
    """
    def _detectable(row) -> bool:
        gap = row["sampling_frequency_gap_c_minus_a"]
        a_lo, a_hi = row["a_ci"]
        c_lo, c_hi = row["c_ci"]
        a_contains_c_point = a_lo <= (c_lo + c_hi) / 2 <= a_hi
        c_contains_a_point = c_lo <= (a_lo + a_hi) / 2 <= c_hi
        return abs(gap) >= GAP_FLOOR and not (a_contains_c_point and c_contains_a_point)

    detectable = decomposition.apply(_detectable, axis=1)
    return {
        "n_lookbacks": len(decomposition),
        "n_detectable_sampling_effect": int(detectable.sum()),
        "module_killed": bool(not detectable.any()),
    }


def cost_row(daily_working: pd.DataFrame, weekly_working: pd.DataFrame, round_trip_cost: float = 0.001) -> list[dict]:
    """`signals_per_year` for each construction's own state-flip column --
    daily constructions use the study's standard 252 trading-days/year,
    the weekly construction uses 52 weeks/year (both already-parameterized
    arguments on `stats/costs.py`'s own functions, no new cost logic).
    """
    rows = []
    for lb in DAILY_LOOKBACKS:
        col = f"above_sma_{lb}"
        spy = signals_per_year(daily_working, col, trading_days_per_year=TRADING_DAYS_PER_YEAR)
        rows.append({"construction": "daily", "lookback": lb, "signals_per_year": spy,
                      "cost_hurdle_annual": cost_hurdle(spy, round_trip_cost)})
    for lb in WEEKLY_LOOKBACKS:
        col = f"above_sma_{lb}"
        spy = signals_per_year(weekly_working, col, trading_days_per_year=WEEKS_PER_YEAR)
        rows.append({"construction": "weekly", "lookback": lb, "signals_per_year": spy,
                      "cost_hurdle_annual": cost_hurdle(spy, round_trip_cost)})
    return rows
