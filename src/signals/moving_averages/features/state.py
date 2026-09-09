"""State run-length features (DESIGN.md §8, M1's "does the age of the state
matter?" sub-question).

Left-censoring: the first observed run of a boolean state series -- the run
already in progress when the series begins (right after an MA's warmup
window) -- has an unknown true start, so its age can't be labeled. Every
subsequent run's start is directly observed (a state flip is visible in the
data), so only the first run per (ticker, MA column) is censored --
`state_run_id` gives it id 0, and `run_length_bucket` drops those rows
rather than mislabeling them by their observed-so-far length (see
PREREGISTRATION.md's M1 entry, "Run-length censoring").

Must be called on a single ticker's series, already sorted by date --
`features/panel.py` computes this per-ticker, pre-lag, same as every other
raw feature (the panel-level lag is applied once, centrally, afterwards).
"""

from __future__ import annotations

import pandas as pd

RUN_LENGTH_BUCKETS = (
    ("1-5", 1, 5),
    ("6-21", 6, 21),
    ("22-63", 22, 63),
    ("64+", 64, None),
)


def state_run_id(state: pd.Series) -> pd.Series:
    """Integer id of the contiguous run of equal values in `state`: 0 for
    the first (left-censored) run, 1, 2, ... for each subsequent run. NaN
    where `state` itself is NaN (e.g. an MA's warmup region).
    """
    valid = state.notna()
    changed = valid & (state != state.shift(1))
    if valid.any():
        # The first valid observation looks like a "change" from NaN, but
        # it isn't an observed transition -- it's just where the
        # observation window starts. It belongs to the censored run 0,
        # like everything before the next real flip.
        changed.loc[valid.idxmax()] = False
    run_id = changed.cumsum()
    return run_id.where(valid)


def days_in_run(state: pd.Series) -> pd.Series:
    """1-indexed count of consecutive days in the current run -- the raw
    quantity `run_length_bucket` buckets. NaN where `state` is NaN.
    """
    run_id = state_run_id(state)
    valid = run_id.notna()
    valid_run_id = run_id[valid]
    counts = valid_run_id.groupby(valid_run_id).cumcount() + 1

    result = pd.Series(index=state.index, dtype="float64")
    result[valid] = counts.to_numpy()
    return result


def run_length_bucket(days: pd.Series, run_id: pd.Series) -> pd.Series:
    """Categorical bucket label ('1-5', '6-21', '22-63', '64+') for
    `days_in_run`'s output. `pd.NA` for rows in the left-censored first run
    (`run_id == 0`) -- dropped regardless of how short the observed
    remainder looks, since its true age is unknown, not short -- or where
    `state` was itself undefined.
    """
    censored_or_undefined = run_id.isna() | (run_id == 0) | days.isna()
    result = pd.Series(pd.NA, index=days.index, dtype="string")
    for label, lo, hi in RUN_LENGTH_BUCKETS:
        upper_ok = pd.Series(True, index=days.index) if hi is None else days <= hi
        in_bucket = ~censored_or_undefined & (days >= lo) & upper_ok
        result[in_bucket] = label
    return result
