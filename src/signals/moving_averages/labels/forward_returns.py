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
