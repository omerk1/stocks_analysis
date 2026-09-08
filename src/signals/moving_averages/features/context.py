"""Context features (DESIGN.md §4.3, "Context") -- specifically the momentum
and volatility controls the C2 matched control (§6.1) needs, added now
because M4 is the first module that needs C2 (see PREREGISTRATION.md).

Not the full §4.3 Context list: `dist_from_52w_high/low`, `days_to_next_earnings`,
`gap_pct`, `dollar_volume_pctile`, and the full IBD-style `rs_rank` (the
`relative_strength` module's rating, not this module's simpler `mom_12_1`)
are all later scope, not built here.
"""

from __future__ import annotations

import pandas as pd


def mom_12_1(close: pd.Series) -> pd.Series:
    """12-month return skipping the most recent month: close[t-21] /
    close[t-252] - 1 -- the momentum control DESIGN §7.1's regression
    names directly (`mom_12_1`). Computed here rather than via the fuller
    `relative_strength` module's rs_rating pipeline (index-membership-
    scoped, sector-ETF-benchmarked -- heavier machinery than a tercile
    bucket needs for C2; see PREREGISTRATION.md).
    """
    return close.shift(21) / close.shift(252) - 1


def realized_vol_63(close: pd.Series) -> pd.Series:
    """63-trading-day rolling standard deviation of daily returns -- the
    vol control for C2 matching (DESIGN §6.1: "same vol decile").
    """
    return close.pct_change().rolling(63).std()
