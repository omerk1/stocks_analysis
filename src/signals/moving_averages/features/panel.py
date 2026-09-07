"""Central lag application (DESIGN.md §7.2 / CLAUDE.md invariant #2).

Every feature that will be used to condition on a forward outcome must pass
through here before being paired with a label. Applying the lag once,
centrally, rather than per-analysis, is what CLAUDE.md invariant #2
requires -- an analysis module that hand-rolls its own `.shift()` is
exactly the kind of bypass that invariant exists to prevent.
"""

from __future__ import annotations

import pandas as pd


def apply_lag(
    panel: pd.DataFrame, columns: list[str], ticker_col: str = "ticker", lag: int = 1
) -> pd.DataFrame:
    """Shift `columns` forward by `lag` row(s) *within each ticker* (never
    across ticker boundaries) -- a signal computed on the close of day t is
    only available for use starting day t+1 (DESIGN.md §7.2's one-bar lag),
    so the value on day t+1's row must be what was true as of day t's
    close, not day t+1's own close.

    `panel` must already be sorted by (ticker, date) within each ticker
    group (grouped shift respects the panel's existing row order, it
    doesn't re-sort). A naive global `.shift()` without grouping by ticker
    would bleed one ticker's trailing row(s) into the next ticker's
    leading `lag` row(s) -- the specific bug this guards against.
    """
    result = panel.copy()
    result[columns] = panel.groupby(ticker_col)[columns].shift(lag)
    return result
