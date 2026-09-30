"""Walk-forward folds with purging and embargo (`docs/modeling/VALIDATION_HARNESS.md` §4).

Dates are the unit, never rows: every row on a date lands on the same side of a
split. A label is a window `[date, label_end_date]` (from
`labels/barriers.py`), so a training row is **purged** whenever its window
overlaps the test period -- otherwise the model trains on outcomes that happen
inside the test fold. Training rows that start within `embargo_days` trading
days after the test period are **embargoed** too; that only matters for schemes
where training data follows test data (nested inner folds may), not for plain
walk-forward, where training always precedes the test.

Rows without a label (NaN `label_end_date`: warm-up, or a window running into
the dataset end) are in neither mask.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EXPANDING = "expanding"
SLIDING = "sliding"

# v1 defaults from the design: yearly test folds 2014-2021, first training
# window 2011-2013 (2010 is feature warm-up), sliding scheme uses 3 years.
V1_TEST_YEARS = tuple(range(2014, 2022))
V1_FIRST_TRAIN_START = "2011-01-01"
V1_SLIDING_YEARS = 3


@dataclass(frozen=True)
class Fold:
    name: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def walk_forward_folds(
    test_years: tuple[int, ...] = V1_TEST_YEARS,
    first_train_start: str = V1_FIRST_TRAIN_START,
    scheme: str = EXPANDING,
    sliding_years: int = V1_SLIDING_YEARS,
) -> list[Fold]:
    """One fold per test year. Expanding: train from `first_train_start` to the
    end of the previous year. Sliding: only the last `sliding_years` years."""
    if scheme not in (EXPANDING, SLIDING):
        raise ValueError(f"scheme must be {EXPANDING!r} or {SLIDING!r}, got {scheme!r}")
    first = pd.Timestamp(first_train_start)
    folds = []
    for year in test_years:
        train_end = pd.Timestamp(year=year - 1, month=12, day=31)
        start = first if scheme == EXPANDING else max(first, pd.Timestamp(year=year - sliding_years, month=1, day=1))
        if start > train_end:
            raise ValueError(f"test year {year} has no training window after {first.date()}")
        folds.append(Fold(
            name=f"{scheme}_{year}",
            train_start=start,
            train_end=train_end,
            test_start=pd.Timestamp(year=year, month=1, day=1),
            test_end=pd.Timestamp(year=year, month=12, day=31),
        ))
    return folds


def inner_folds(outer: Fold, n_inner: int = 2, scheme: str = EXPANDING, sliding_years: int = V1_SLIDING_YEARS) -> list[Fold]:
    """Walk-forward folds *inside* an outer fold's training window: its last
    `n_inner` years are the inner test years. For tuning and stacking, so the
    outer test fold never sees anything fitted on it."""
    last = outer.train_end.year
    years = tuple(range(last - n_inner + 1, last + 1))
    folds = walk_forward_folds(years, outer.train_start.strftime("%Y-%m-%d"), scheme, sliding_years)
    return [Fold(f"{outer.name}/inner_{f.test_start.year}", f.train_start, f.train_end, f.test_start, f.test_end) for f in folds]


def fold_masks(
    frame: pd.DataFrame,
    fold: Fold,
    embargo_days: int = 0,
    date_col: str = "date",
    label_end_col: str = "label_end_date",
) -> tuple[np.ndarray, np.ndarray]:
    """(train_mask, test_mask) over `frame`'s rows for `fold`."""
    dates = pd.to_datetime(frame[date_col])
    ends = pd.to_datetime(frame[label_end_col])
    labelled = ends.notna().to_numpy()
    d = dates.to_numpy()
    e = ends.to_numpy()

    test = labelled & (d >= np.datetime64(fold.test_start)) & (d <= np.datetime64(fold.test_end))

    in_train_window = labelled & (d >= np.datetime64(fold.train_start)) & (d <= np.datetime64(fold.train_end))
    # Purge: the label window [date, label_end] overlaps [test_start, test_end].
    overlaps_test = (d <= np.datetime64(fold.test_end)) & (e >= np.datetime64(fold.test_start))
    train = in_train_window & ~overlaps_test

    if embargo_days > 0:
        calendar = np.unique(d)
        after = calendar[calendar > np.datetime64(fold.test_end)]
        if len(after):
            embargo_end = after[min(embargo_days, len(after)) - 1]
            train &= ~((d > np.datetime64(fold.test_end)) & (d <= embargo_end))
    return train, test
