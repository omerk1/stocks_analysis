"""Forward returns for Track-B events and control pairs -- pure functions,
nothing stored. The run script computes these at run time inside the dev
window; keeping them out of the derived DB avoids a second
holdout-boundary question and any temptation to peek.

Timing per repo invariant #2: an entity confirmed at bar t enters at the
OPEN of the first bar after t. The h-bar return holds through the CLOSE of
the h-th held bar (entry bar counts as bar 1). If the series ends first --
a delisting -- the return runs to the final close and is flagged
truncated, never dropped: terminal returns are exactly the information
delisted tickers carry (invariant #4)."""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (21, 63)


def compute_forward_returns(
    bars: pd.DataFrame, confirmed_at: pd.Series, horizons: tuple[int, ...] = HORIZONS
) -> pd.DataFrame:
    """One output row per input confirmation timestamp (index preserved):
    entry_date, entry_price, and per horizon h: fwd_log_ret_{h} plus
    truncated_{h}. Entries with no bar after their confirmation (confirmed
    on the data's last bar) get all-None returns and entry fields."""
    opens = bars["open"].to_numpy()
    closes = bars["close"].to_numpy()
    n = len(bars)

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
            if truncated:
                exit_pos = n - 1
            exit_price = closes[exit_pos]
            if np.isfinite(exit_price) and exit_price > 0:
                row[f"fwd_log_ret_{h}"] = float(np.log(exit_price / entry_price))
                row[f"truncated_{h}"] = bool(truncated)
        out.append(row)

    return pd.DataFrame(out, index=confirmed_at.index)
