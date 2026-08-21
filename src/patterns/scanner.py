"""Top-level detect() entry point -- design doc §5's PatternScanner. Runs
every registered PatternDetector over one (ticker, timeframe)'s bars, as of
a given date, and returns the merged results.

Deliberately returns every detector's matches side by side rather than
picking one "the" classification per pivot window (§9's resolved overlap
handling: return all candidate matches with independent confidence scores,
never force mutual exclusivity -- same principle sr_lines already applies
to its own horizontal/diagonal lines coexisting).
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from src.market_common import data as data_mod
from src.market_common import indicators
from src.market_common.models import DataQualityReport, Timeframe
from src.market_common.pivots import detect_pivots
from src.patterns.base import PatternDetector
from src.patterns.config import PatternConfig
from src.patterns.detectors.double_top_bottom import DoubleTopBottomDetector
from src.patterns.detectors.head_shoulders import HeadShouldersDetector
from src.patterns.detectors.triangles import TriangleWedgeDetector
from src.patterns.models import PatternMatch

DEFAULT_DETECTORS: list[PatternDetector] = [
    DoubleTopBottomDetector(), HeadShouldersDetector(), TriangleWedgeDetector(),
]


def scan_bars(
    df: pd.DataFrame,
    ticker: str,
    timeframe: Timeframe,
    config: PatternConfig,
    detectors: list[PatternDetector] | None = None,
) -> list[PatternMatch]:
    """Pure function over an already-loaded bars frame -- extracts pivots
    once (config.pivot_atr_mult) and shares them across every registered
    detector. The fuller design wants different pivot granularity per
    pattern (§2c: VCP wants fine-grained pivots, H&S coarser) -- Phase 1's
    single detector doesn't need that yet, so this stays one shared pivot
    pass for now; per-detector granularity is a later-phase concern.

    No DB access, no as_of handling -- callers/tests wanting a specific
    pivot set can build it themselves and call a detector's own `scan`
    directly instead (see tests/test_patterns_double_top_bottom.py).
    """
    detectors = detectors if detectors is not None else DEFAULT_DETECTORS
    if len(df) < 3:
        return []

    atr = indicators.atr(df, config.atr_period)
    pivots = detect_pivots(df["high"], df["low"], threshold_fn=lambda i: config.pivot_atr_mult * atr.iloc[i])

    matches: list[PatternMatch] = []
    for detector in detectors:
        matches.extend(detector.scan(df, pivots, ticker, timeframe, config))
    return matches


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: PatternConfig,
    as_of: str | pd.Timestamp | date | None = None,
    detectors: list[PatternDetector] | None = None,
) -> tuple[list[PatternMatch], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, scan for
    patterns. Returns (matches, quality_report, skip_reason) -- skip_reason
    is None on success, otherwise matches is [] and quality_report still
    reflects what was loaded (so callers/CLI can report *why* a ticker was
    skipped), same contract as divergences.detect/gaps.detect.

    Bars are already truncated to `as_of` by `load_and_validate`, so every
    resulting match's defining pivots (and any breakout resolved via
    lifecycle.apply_lifecycle, which only ever walks rows within `df`) are
    already <= as_of by construction -- the explicit filter below is a
    defensive, spec-mandated belt-and-braces check (same discipline
    divergences.detect documents for its own equivalent filter), not dead
    weight covering a real gap in the truncation.
    """
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        return [], report, reason

    matches = scan_bars(bars, ticker, timeframe, config, detectors)

    if as_of is not None:
        as_of_ts = pd.Timestamp(as_of)
        matches = [m for m in matches if pd.Timestamp(m.formation_end) <= as_of_ts]

    return matches, report, None
