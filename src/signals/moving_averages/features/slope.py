"""Slope features (DESIGN.md §4.3, Appendix A).

Phase 2's starting subset: `slope_log_k` only -- "the only scale-invariant
version" per DESIGN §4.3, and the only slope form CLAUDE.md's log-scale-
for-slopes invariant permits ("Log scale for slopes. `slope_log_k` only.
Percentage and price-unit slopes are not comparable across tickers."). `slope_pct_k`,
`slope_atr_k`, curvature, and the drop-off decomposition are M6's later
scope, not this phase's.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SLOPE_K = (5, 21, 63)


def slope_log_k(ma: pd.Series, k: int) -> pd.Series:
    """ln(ma_t) - ln(ma_{t-k}) -- DESIGN Appendix A's exact identity, the
    only scale-invariant slope definition. Caller must pass a single
    ticker's MA series, already sorted by date.
    """
    return np.log(ma) - np.log(ma.shift(k))
