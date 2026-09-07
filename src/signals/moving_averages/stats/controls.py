"""C0/C1 matched-control deltas (DESIGN.md §6.1).

C2 (date + momentum + vol + sector matched) needs the full feature set
Phase 2 builds (rs_rank, vol decile, sector) and is added then. C0/C1 need
only a boolean group column, a value column, and (for C1) a date column --
enough to validate the pipeline mechanics in Phase 1, and already the
correct shape for every later module to build on.

Both functions drop rows with a missing group or value first -- an event
can't be scored against a control using data it doesn't have.
"""

from __future__ import annotations

import pandas as pd


def c0_delta(panel: pd.DataFrame, group_col: str, value_col: str) -> float:
    """Unconditional control (C0): the event group's mean minus the whole
    panel's mean. Cheapest, weakest control -- see DESIGN.md §6.1.
    """
    valid = panel[[group_col, value_col]].dropna()
    overall_mean = valid[value_col].mean()
    group_mean = valid.loc[valid[group_col].astype(bool), value_col].mean()
    return group_mean - overall_mean


def c1_delta(panel: pd.DataFrame, group_col: str, value_col: str, date_col: str = "date") -> float:
    """Date-matched control (C1): for each date, the event group's mean
    minus that same date's *non-event* names' mean (DESIGN.md §6.1: "sample
    non-event names from the same universe on the same date"), then
    averaged across dates (each date weighted equally) -- removes the
    shared market-return confound a plain C0 delta does not. This is the
    default control tier.

    The control deliberately excludes the event rows themselves, not just
    matches on date -- comparing against the *whole* date-universe mean
    (event rows included) would dilute the true delta by roughly the
    event group's population share on that date (a diluted-by-half result
    on an otherwise-correct 50/50 split is what first caught this).
    """
    valid = panel[[date_col, group_col, value_col]].dropna(subset=[group_col, value_col])
    is_event = valid[group_col].astype(bool)
    event_mean_by_date = valid[is_event].groupby(date_col)[value_col].mean()
    control_mean_by_date = valid[~is_event].groupby(date_col)[value_col].mean()
    delta_by_date = (event_mean_by_date - control_mean_by_date).dropna()
    return delta_by_date.mean()
