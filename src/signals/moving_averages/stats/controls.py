"""C0/C1/C2 matched-control deltas (DESIGN.md §6.1).

C2 (date + momentum + vol + sector matched) is added here for M4 -- the
first module that needs it (see PREREGISTRATION.md) -- as generic,
reusable infrastructure, not M4-specific code: `cross_sectional_bucket`
works on any value column, and `c2_delta` takes an arbitrary list of
already-bucketed match columns rather than hardcoding momentum/vol/sector.

`stratum_deltas` is the shared primitive behind `c1_delta` (one date-only
stratum), `c2_delta` (date + match_cols strata), and the block-bootstrap
inference layer (`stats/inference.py`), which needs the per-stratum table
itself, not just its mean -- keeping one implementation rather than three
avoids the point estimates silently drifting apart if the matching logic
ever changes.

All functions here drop rows with a missing group/value/stratum column
first -- an event can't be scored against a control using data it doesn't
have.
"""

from __future__ import annotations

import pandas as pd


def c0_delta(panel: pd.DataFrame, group_col: str, value_col: str) -> float:
    """Unconditional control (C0): the event group's mean minus the whole
    panel's mean. Cheapest, weakest control -- see DESIGN.md §6.1. Note
    the baseline here includes the event rows themselves (diluted by the
    event group's own population share `p`) -- see `pooled_delta` for the
    event-excluded variant this dilutes, algebraically, by exactly
    `c0_delta = (1 - p) * pooled_delta` (verified in
    `tests/test_moving_averages_stats_controls.py`,
    PREREGISTRATION.md's M1 entry, "C1 > C0 investigation").
    """
    valid = panel[[group_col, value_col]].dropna()
    overall_mean = valid[value_col].mean()
    group_mean = valid.loc[valid[group_col].astype(bool), value_col].mean()
    return group_mean - overall_mean


def pooled_delta(panel: pd.DataFrame, group_col: str, value_col: str) -> float:
    """Event mean minus control mean, pooled across the whole panel with
    *no* date stratification -- i.e. `c1_delta`'s event/control exclusion
    (the baseline is non-event rows only, not the whole population) without
    `c1_delta`'s per-date-equal-weighting. Isolates the "C0's baseline is
    diluted by the event group's own rows" mechanism from the "C1 weights
    dates equally, C0 implicitly weights rows equally" mechanism -- added
    to test PREREGISTRATION.md's M1 "C1 > C0" investigation directly rather
    than only algebraically.
    """
    valid = panel[[group_col, value_col]].dropna()
    is_event = valid[group_col].astype(bool)
    event_mean = valid.loc[is_event, value_col].mean()
    control_mean = valid.loc[~is_event, value_col].mean()
    return event_mean - control_mean


def stratum_deltas(
    panel: pd.DataFrame, group_col: str, value_col: str, strata_cols: list[str]
) -> pd.DataFrame:
    """Per-stratum (event_mean - control_mean), for arbitrary `strata_cols`
    -- e.g. `[date_col]` for C1, `[date_col, *match_cols]` for C2. The
    control is the non-event rows *within* each stratum, never the whole
    stratum including the event rows -- comparing against the whole
    stratum would dilute the true delta by roughly the event group's own
    population share (a diluted-by-half result on an otherwise-correct
    50/50 split is what first caught this, in `c1_delta`'s original,
    since-fixed implementation). A stratum with only event rows or only
    control rows contributes nothing (no counterpart to compare against)
    -- dropped, not treated as a zero delta.

    Returns a frame with `strata_cols` plus a `delta` column; `X_delta(...)
    == stratum_deltas(...)["delta"].mean()` for the corresponding strata.
    """
    required = [*strata_cols, group_col, value_col]
    valid = panel[required].dropna(subset=[group_col, value_col, *strata_cols])
    is_event = valid[group_col].astype(bool)

    event_mean = valid[is_event].groupby(strata_cols, observed=True)[value_col].mean()
    control_mean = valid[~is_event].groupby(strata_cols, observed=True)[value_col].mean()
    delta = (event_mean - control_mean).dropna().rename("delta")
    return delta.reset_index()


def c1_delta(panel: pd.DataFrame, group_col: str, value_col: str, date_col: str = "date") -> float:
    """Date-matched control (C1): for each date, the event group's mean
    minus that same date's *non-event* names' mean (DESIGN.md §6.1: "sample
    non-event names from the same universe on the same date"), then
    averaged across dates (each date weighted equally) -- removes the
    shared market-return confound a plain C0 delta does not. This is the
    default control tier. See `stratum_deltas` for the matching logic.
    """
    return stratum_deltas(panel, group_col, value_col, [date_col])["delta"].mean()


def cross_sectional_bucket(
    panel: pd.DataFrame, value_col: str, date_col: str = "date", n_buckets: int = 10
) -> pd.Series:
    """Per-date cross-sectional bucket rank (0 = lowest ... n_buckets-1 =
    highest) of `value_col`, via `pd.qcut` within each date -- reusable for
    any decile/tercile/etc. cut (momentum, vol, dollar volume, eventually
    market cap), not specific to any one caller.

    NaN where `value_col` is NaN, or where a date has too few distinct
    values to actually form `n_buckets` groups (`qcut`'s
    `duplicates="drop"` can silently return fewer buckets than requested
    on a thin date -- passed through as-is here, not padded or treated as
    an error).
    """
    return panel.groupby(date_col)[value_col].transform(
        lambda x: pd.qcut(x, n_buckets, labels=False, duplicates="drop")
    )


def c2_eligible_mask(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
) -> pd.Series:
    """Boolean mask, aligned to `panel`'s index, of rows eligible for a C2
    matched stratum -- i.e. the exact row population `c2_delta` actually
    uses. Computing C0/C1/C2 on this same restricted set (rather than
    letting C0/C1 additionally run on their own wider natural row sets via
    their own independent `dropna`) is required before reading a
    C0->C1->C2 waterfall as a shrinkage story (PREREGISTRATION.md's M1
    entry, "Waterfall row set"): otherwise the shrinkage is confounded
    with a change in sample composition, not just a change in control
    strictness.

    A row is eligible iff `group_col`/`value_col`/`date_col`/`match_cols`
    are all non-null, AND the row's (date, *match_cols) stratum contains
    at least one event row and at least one control row -- the same
    non-dilution requirement `stratum_deltas` applies internally (a
    stratum with only one side has no counterpart to compare against, so
    C2 silently drops it; a row in such a stratum must not be counted as
    "eligible" by C0/C1 either, or the row sets diverge again).
    """
    strata_cols = [date_col, *match_cols]
    required = [*strata_cols, group_col, value_col]
    valid = panel[required].notna().all(axis=1)

    working = panel.loc[valid, strata_cols].copy()
    working["_is_event"] = panel.loc[valid, group_col].astype(bool)

    grouped = working.groupby(strata_cols, observed=True)["_is_event"]
    event_count = grouped.transform("sum")
    total_count = grouped.transform("size")
    stratum_ok = (event_count > 0) & ((total_count - event_count) > 0)

    eligible = pd.Series(False, index=panel.index)
    eligible.loc[valid] = stratum_ok.to_numpy()
    return eligible


def c2_delta(
    panel: pd.DataFrame,
    group_col: str,
    value_col: str,
    match_cols: list[str],
    date_col: str = "date",
) -> float:
    """C2: same-date, same-`match_cols`-stratum matched control (DESIGN
    §6.1: "date + momentum + vol + sector matched") -- the tier that
    separates real MA information from momentum re-encoding. `match_cols`
    must already be categorical/bucketed columns (e.g. from
    `cross_sectional_bucket`), computed on the same point-in-time basis as
    everything else in the panel -- this function only matches and
    differences, it doesn't compute or lag the match columns itself.

    Same non-dilution logic as `c1_delta` (see `stratum_deltas`), extended
    to (date, *match_cols) strata. Each populated stratum is weighted
    equally in the final average, same convention as `c1_delta` weighting
    each date equally.
    """
    return stratum_deltas(panel, group_col, value_col, [date_col, *match_cols])["delta"].mean()
