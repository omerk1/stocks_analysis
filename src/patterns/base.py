"""PatternDetector ABC -- design doc §5. Each detectors/*.py module
implements one (or a closely related family of) pattern as a `scan` over an
already-loaded bars frame plus an already-extracted pivot sequence, pure and
DB-free -- same shape as divergences.detect_for_indicator/gaps.detect_gaps,
so synthetic tests can call `scan` directly on hand-built fixtures without
touching the DB or as_of machinery (that's scanner.py's job, one layer up).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.market_common.models import Pivot, Timeframe
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch


class PatternDetector(ABC):
    @abstractmethod
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        """`df`: OHLCV bars (DatetimeIndex, open/high/low/close/volume
        columns) already loaded/validated/as_of-truncated by the caller.
        `pivots`: already extracted via market_common.pivots.detect_pivots
        against `df` -- detectors never call detect_pivots themselves, so
        the same pivot sequence (and its bar_index alignment with `df`) is
        shared across every registered detector in one scan (see
        scanner.py)."""
        ...
