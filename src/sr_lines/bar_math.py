"""Tiny shared bar-index arithmetic -- extracted once a second module
(flip_status.py) needed the identical private helper `scoring.py` already
had, same "extract before it drifts into two copies" reasoning
`flip_status.py` itself was originally split out for.
"""

from __future__ import annotations

import pandas as pd


def bars_between(bars: pd.DataFrame, start: str, end: str) -> int:
    return int(bars.index.get_loc(pd.Timestamp(end)) - bars.index.get_loc(pd.Timestamp(start)))
