"""Forward returns for Track-B events and control pairs -- pure functions,
nothing stored. The run script computes these at run time inside the dev
window; keeping them out of the derived DB avoids a second
holdout-boundary question and any temptation to peek.

Timing per repo invariant #2: an entity confirmed at bar t enters at the
OPEN of the first bar after t. The h-bar return holds through the CLOSE of
the h-th held bar (entry bar counts as bar 1).

A series can end before the horizon for two reasons that must never be
conflated:

- **Delisting** (the series ends while data continues past it, i.e. well
  before `data_end`): the return runs to the final close and is flagged
  truncated, never dropped -- terminal returns are exactly the
  information delisted tickers carry (invariant #4).
- **Right-censoring at the loaded boundary** (the series runs up to
  `data_end`, e.g. bars loaded as_of the holdout edge): that horizon's
  return is None -- a shortened hold disguised as a complete one would
  bias every late-window cell, and under the holdout lock the real exit
  bar may not legally be read at all. Operationally this means each
  horizon has its own effective confirmation cutoff (confirmed early
  enough for h bars to fit inside the lock)."""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (21, 63)

# A live ticker's last bar can sit a few sessions shy of the as_of used
# to load (holidays, loading lag): within this many calendar days of
# data_end still reads as censored, not delisted.
CENSOR_TOLERANCE_DAYS = 7


def compute_forward_returns(
    bars: pd.DataFrame,
    confirmed_at: pd.Series,
    horizons: tuple[int, ...] = HORIZONS,
    data_end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """One output row per input confirmation timestamp (index preserved):
    entry_date, entry_price, and per horizon h: fwd_log_ret_{h} plus
    truncated_{h}. Entries with no bar after their confirmation (confirmed
    on the data's last bar) get all-None returns and entry fields.

    `data_end` is the boundary the bars were loaded to (the run passes its
    as_of). With it set, a series ending at that boundary is CENSORED --
    unfinished horizons return None -- while a series ending earlier is a
    delisting whose terminal return is kept and flagged truncated. Without
    it (data_end=None), every early end is treated as a delisting --
    only correct when the caller knows the data runs past every horizon."""
    opens = bars["open"].to_numpy()
    closes = bars["close"].to_numpy()
    n = len(bars)
    censored_at_end = False
    if data_end is not None and n > 0:
        censored_at_end = bars.index[-1] >= pd.Timestamp(data_end) - pd.Timedelta(
            days=CENSOR_TOLERANCE_DAYS
        )

    out: list[dict] = []
    conf_ts = pd.to_datetime(confirmed_at)
    entry_pos = bars.index.searchsorted(conf_ts, side="right")
    for pos in entry_pos:
        row: dict = {"entry_date": None, "entry_price": None}
        for h in horizons:
            row[f"fwd_log_ret_{h}"] = None
            row[f"truncated_{h}"] = None
        if pos >= n:
            out.append(row)
            continue
        entry_price = opens[pos]
        row["entry_date"] = bars.index[pos].isoformat()
        row["entry_price"] = float(entry_price)
        if not np.isfinite(entry_price) or entry_price <= 0:
            out.append(row)
            continue
        for h in horizons:
            exit_pos = pos + h - 1  # entry bar is held bar 1
            truncated = exit_pos >= n
            if truncated and censored_at_end:
                # The window runs into the loaded boundary, not a
                # delisting: no return for this horizon.
                continue
            if truncated:
                exit_pos = n - 1
            exit_price = closes[exit_pos]
            if np.isfinite(exit_price) and exit_price > 0:
                row[f"fwd_log_ret_{h}"] = float(np.log(exit_price / entry_price))
                row[f"truncated_{h}"] = bool(truncated)
        out.append(row)

    return pd.DataFrame(out, index=confirmed_at.index)
