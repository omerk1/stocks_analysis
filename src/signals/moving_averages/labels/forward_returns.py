"""Forward-return labels (DESIGN.md §5). Just the raw-return case for now
(DESIGN §5.2's #1) -- excess/beta-adjusted/sector-relative variants need
the benchmark and factor joins Phase 2 builds; this is enough to validate
the pipeline mechanics in Phase 1.
"""

from __future__ import annotations

import pandas as pd


def forward_return(
    panel: pd.DataFrame, horizon: int, price_col: str = "close", ticker_col: str = "ticker"
) -> pd.Series:
    """Simple forward return over `horizon` trading days, per ticker:
    price[t+horizon] / price[t] - 1, computed independently within each
    ticker (never spanning a ticker boundary). NaN for the final `horizon`
    rows of each ticker's history, where no forward price exists yet.
    """
    future_price = panel.groupby(ticker_col)[price_col].shift(-horizon)
    return future_price / panel[price_col] - 1


def forward_realized_vol(
    panel: pd.DataFrame, horizon: int, price_col: str = "close", ticker_col: str = "ticker"
) -> pd.Series:
    """Forward realized volatility over `horizon` trading days: the
    standard deviation of the next `horizon` daily simple returns
    (`close.pct_change()`, matching `features/context.py::realized_vol_63`'s
    own convention -- simple returns, not log, non-annualized), computed
    independently within each ticker (added for M7, DESIGN.md's ribbon-
    compression module -- "compression precedes vol expansion" needs a
    forward vol label, which didn't exist yet).

    A forward-looking LABEL, not a lagged feature -- CLAUDE.md invariant #2
    (one-bar lag) constrains *features* used to condition on a forward
    outcome; a label is allowed to look forward by construction, same as
    `forward_return` above. NaN for the final `horizon` rows of each
    ticker's history, where fewer than `horizon` forward daily returns
    exist.
    """
    daily_ret = panel.groupby(ticker_col)[price_col].pct_change()
    grouped = pd.DataFrame({ticker_col: panel[ticker_col], "_r": daily_ret}).groupby(ticker_col)["_r"]
    shifted = pd.concat([grouped.shift(-k) for k in range(1, horizon + 1)], axis=1)
    # skipna=False (not the pandas default True): a row with fewer than
    # `horizon` forward daily returns available (the final `horizon` rows
    # of each ticker's history) must come out NaN, not a std computed
    # from whichever few forward returns happen to exist.
    return shifted.std(axis=1, skipna=False)
