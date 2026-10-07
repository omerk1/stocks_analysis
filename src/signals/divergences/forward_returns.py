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
    delisted: bool | None = None,
) -> pd.DataFrame:
    """One output row per input confirmation timestamp (index preserved):
    entry_date, entry_price, and per horizon h: fwd_log_ret_{h},
    truncated_{h} (delisting-shortened, return kept), censored_{h}
    (window hit the data boundary, return absent). The three missingness
    cases stay distinguishable: censored (censored=True), corrupt exit
    bar (flags False, return absent), never entered (everything None).

    `data_end` is the study boundary and is enforced FAIL-CLOSED: no
    entry or exit past it produces anything, however far the caller's
    loaded bars extend. `delisted` (e.g. from the tickers table's active
    status) overrides the end-of-series classification; without it a
    calendar tolerance infers censoring, with documented misclassification
    at >tolerance halts and boundary-adjacent delistings. Without
    data_end, every early series end is treated as a delisting -- only
    correct when the caller knows the data runs past every horizon."""
    opens = bars["open"].to_numpy()
    closes = bars["close"].to_numpy()
    n = len(bars)

    # The hard boundary, enforced FAIL-CLOSED: no exit (or entry) bar past
    # data_end ever produces a return, regardless of how far the caller's
    # loaded bars extend -- relying on every caller to slice with as_of
    # would make a holdout read one forgotten argument away. last_legal is
    # the last bar position whose timestamp is <= data_end.
    last_legal = n - 1
    if data_end is not None and n > 0:
        last_legal = int(bars.index.searchsorted(pd.Timestamp(data_end), side="right")) - 1

    # Is the (legal part of the) series ending because the DATA ends
    # (censoring) or because the TICKER did (delisting)? An explicit
    # `delisted` flag from the caller (e.g. the tickers table's active
    # status) wins; the calendar-tolerance inference is only the
    # no-information fallback, and misclassifies both a >tolerance halt at
    # the boundary and a genuine delisting inside the tolerance.
    if delisted is not None:
        censored_at_end = not delisted
    elif data_end is not None and n > 0:
        censored_at_end = bars.index[min(last_legal, n - 1)] >= pd.Timestamp(data_end) - pd.Timedelta(
            days=CENSOR_TOLERANCE_DAYS
        )
    else:
        censored_at_end = False

    out: list[dict] = []
    conf_ts = pd.to_datetime(confirmed_at)
    entry_pos = bars.index.searchsorted(conf_ts, side="right")
    for pos in entry_pos:
        row: dict = {"entry_date": None, "entry_price": None}
        for h in horizons:
            row[f"fwd_log_ret_{h}"] = None
            row[f"truncated_{h}"] = None
            row[f"censored_{h}"] = None
        if pos > last_legal or pos >= n:
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
            short = exit_pos > last_legal
            if short and (censored_at_end or last_legal < n - 1):
                # The window runs into the loaded/legal boundary (either
                # the series is censored at its end, or data_end cut the
                # loaded bars short): no return, flagged censored --
                # distinct from both delisting truncation and a bad bar.
                row[f"censored_{h}"] = True
                continue
            if short:
                exit_pos = last_legal  # delisting: terminal return, kept
            exit_price = closes[exit_pos]
            if np.isfinite(exit_price) and exit_price > 0:
                row[f"fwd_log_ret_{h}"] = float(np.log(exit_price / entry_price))
                row[f"truncated_{h}"] = bool(short)
                row[f"censored_{h}"] = False
            else:
                # Corrupt/NaN exit bar: a DATA-QUALITY hole, marked
                # distinctly (flags set, return absent) so per-horizon
                # exclusion accounting can tell it from censoring.
                row[f"truncated_{h}"] = False
                row[f"censored_{h}"] = False
        out.append(row)

    return pd.DataFrame(out, index=confirmed_at.index)
