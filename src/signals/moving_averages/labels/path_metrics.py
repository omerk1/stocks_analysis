"""Forward path-based labels (DESIGN.md's M6.4 framing of "path metrics" --
MFE/MAE -- reused here in minimal form for M6.6, which needs a forward
*drawdown* outcome, not M6.4's full Kaplan-Meier survival machinery).

Only the one label M6.6 needs is built here: the maximum adverse excursion
(MAE) over a forward horizon, using the path's own low prices, not just the
horizon's closing price the way `forward_returns.py::forward_return` does.
Nothing else from DESIGN's path-metrics scope (MFE, barrier hits) is built
-- narrower than DESIGN's own M6.4 ask, a minimal label for a different
module's needs, not a first slice of M6.4 itself.
"""

from __future__ import annotations

import pandas as pd


def forward_max_drawdown(
    panel: pd.DataFrame, horizon: int, low_col: str = "low", price_col: str = "close",
    ticker_col: str = "ticker",
) -> pd.Series:
    """Maximum adverse excursion over the next `horizon` trading days: the
    most negative `low[t+k] / close[t] - 1` for k in 1..horizon -- the
    worst point *touched* within the window, not just the horizon's own
    closing return (`forward_return`'s outcome). A negative number (0 in
    the impossible case the low never dips below the entry close); more
    negative = a worse drawdown.

    Vectorized the same way `forward_realized_vol` is (concat of per-offset
    shifted columns, one row-wise reduction) -- never a per-ticker loop.
    NaN for the final `horizon` rows of each ticker's history, where fewer
    than `horizon` forward lows exist yet, same convention as
    `forward_return`/`forward_realized_vol`.

    A forward-looking LABEL, not a lagged feature -- CLAUDE.md invariant #2
    (one-bar lag) constrains features used to condition on a forward
    outcome; a label is allowed to look forward by construction, same as
    `forward_return`/`forward_realized_vol`.
    """
    shifted = pd.concat(
        [panel.groupby(ticker_col)[low_col].shift(-k) for k in range(1, horizon + 1)], axis=1
    )
    # skipna=False (not the pandas default True): a row with fewer than
    # `horizon` forward lows available (the final `horizon` rows of each
    # ticker's history) must come out NaN, not a min computed from whichever
    # few forward lows happen to exist -- same reasoning as
    # `forward_realized_vol`'s own skipna=False.
    worst_low = shifted.min(axis=1, skipna=False)
    return worst_low / panel[price_col] - 1
