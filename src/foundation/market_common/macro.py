"""Point-in-time-safe join of a macro/meta-financial series (see
`data_processing.db.read_macro_series`) onto per-ticker bar dates.

A macro observation's `date` column is the *period* it describes (e.g. a
GDP row dated for Q2's start), not when it actually became known --
`published_at` is (`data_processing.fred_client.get_series_first_release`,
or a same-day construction for series that don't carry real ALFRED vintage
data, see `SAME_DAY_PUBLISHED_SERIES`). Joining on `date` instead of
`published_at` would leak future information into a bar that predates the
value's real publication -- the same zero-lookahead concern `as_of`
truncation already guards elsewhere in this codebase (gaps/divergences/
sr_lines), just for a different axis (macro release lag, not price-bar
truncation).
"""

from __future__ import annotations

import pandas as pd


def as_of_join(bar_dates: pd.DatetimeIndex, macro: pd.DataFrame) -> pd.Series:
    """For each date in `bar_dates`, the most recently *published* macro
    observation as of that date -- forward-filled, never a value that
    wasn't yet knowable. `macro` is whatever `db.read_macro_series` returns
    (must have `published_at`/`first_published_value` columns); rows with a
    null `published_at` (not yet backfilled, or a series FRED couldn't
    serve first-release data for at all) are dropped rather than joined.

    Returns a float Series indexed by `bar_dates`, NaN before the first
    known publication.

    Sorted by `published_at`, not `date` -- publication order isn't
    guaranteed to match period order (a delayed catch-up revision can be
    published well after a later period's own on-time release). Ties (two
    different periods published the same day, a real if rare case) keep the
    later `date`'s value -- a deliberate, simple tie-break: whichever
    reading a market participant checking macro data that day would
    actually see as "the latest," not an arbitrary one.
    """
    known = macro.dropna(subset=["published_at"]).copy()
    if known.empty:
        return pd.Series(float("nan"), index=bar_dates, dtype=float)

    known["published_at"] = pd.to_datetime(known["published_at"])
    known["date"] = pd.to_datetime(known["date"])
    known = known.sort_values(["published_at", "date"])

    bars = pd.DataFrame({"published_at": pd.DatetimeIndex(bar_dates).sort_values()})
    merged = pd.merge_asof(
        bars, known[["published_at", "first_published_value"]],
        on="published_at", direction="backward",
    )
    result = pd.Series(
        merged["first_published_value"].to_numpy(), index=merged["published_at"], dtype=float
    )
    return result.reindex(bar_dates)
