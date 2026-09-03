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

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import indicators
from src.foundation.market_common.models import DataQualityReport, Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.signals.patterns.base import PatternDetector
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.detectors.cup_and_handle import CupAndHandleDetector
from src.signals.patterns.detectors.double_top_bottom import DoubleTopBottomDetector
from src.signals.patterns.detectors.flags_pennants import FlagPennantDetector
from src.signals.patterns.detectors.head_shoulders import HeadShouldersDetector
from src.signals.patterns.detectors.triangles import TriangleWedgeDetector
from src.signals.patterns.detectors.vcp import VCPDetector
from src.signals.patterns.models import PatternMatch

DEFAULT_DETECTORS: list[PatternDetector] = [
    DoubleTopBottomDetector(), HeadShouldersDetector(), TriangleWedgeDetector(), CupAndHandleDetector(), VCPDetector(),
    FlagPennantDetector(),
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
    return dedupe_matches(matches)


def dedupe_matches(matches: list[PatternMatch]) -> list[PatternMatch]:
    """§5's "merges/dedupes overlapping matches" -- collapse candidates that
    are the *same structure found from different starting pivots* down to
    one representative each.

    The duplicates this exists for are not merely "overlapping": a cup
    detector scanning (rim1, rim2) pairs emits one match per left-rim
    candidate, so a single base with three plausible left rims becomes
    three matches sharing one right rim, one breakout bar, and near-
    identical outcomes. Left unmerged they inflate every `n` in the §7.3
    backtest and count one real trade three times (measured on five
    tickers: 2832 -> 2040 matches, 28.0% of output, max group size 6).

    Identity key is `(pattern_type, direction, last pivot's bar_index)` --
    the pattern's terminal pivot is what fixes its trigger level and
    breakout, so two matches ending on the same pivot are the same
    structure regardless of how far back their first pivot reaches.
    Deliberately *not* a formation-window overlap ratio: measured against
    real output, window overlap fails to separate at any threshold (at
    Jaccard >= 0.7 it merges 153 of 178 true duplicates while wrongly
    merging 1145 genuinely distinct pairs, because distinct patterns on
    the same ticker routinely share most of their window).

    Group members can differ in `target_price`/`stop_price` (a different
    left rim means a different cup depth, hence a different measured
    move), so this picks rather than blends: highest `confidence` wins,
    ties broken toward the longer formation (the candidate resting on more
    structure). Never merges across `pattern_type` -- §9's resolved
    overlap decision keeps every type's read on the same swing points as
    an independent candidate with its own score, and that stays true here.

    This terminal-pivot identity is exact for detectors with a fixed,
    single-pivot trigger (cup/rounding's rim2, double top/bottom's
    neckline pivot) but incomplete for sloped-trigger detectors
    (triangle/wedge/H&S), which fit a trendline over the *whole* window --
    a window sliding by one pivot can resolve to the same real breakout
    while ending on a genuinely different terminal pivot, invisible to this
    key. See `_dedupe_by_breakout_bar` below for that second identity, run
    as a separate pass rather than folded in here.
    """
    best: dict[tuple, PatternMatch] = {}
    for match in matches:
        if not match.pivots:
            continue
        key = (match.pattern_type, match.direction, match.pivots[-1].bar_index)
        incumbent = best.get(key)
        if incumbent is None or _dedupe_rank(match) > _dedupe_rank(incumbent):
            best[key] = match
    # Preserve first-seen detector order rather than dict/key order, so
    # output ordering stays stable for callers that don't re-sort.
    kept = [m for m in matches if id(m) in set(id(x) for x in best.values())]
    return _dedupe_by_breakout_bar(kept)


def _dedupe_rank(match: PatternMatch) -> tuple[float, int]:
    formation_bars = match.pivots[-1].bar_index - match.pivots[0].bar_index
    return (match.confidence, formation_bars)


# Second identity: sloped-trigger detectors (triangle/wedge/H&S) fit a
# trendline over the WHOLE pivot window, not one fixed pivot, so a window
# sliding by one pivot can still resolve to the same real breakout while
# ending on a genuinely different terminal pivot -- invisible to the key
# above. Measured (QUCY/REKR/MPU and others): these pairs share 4-5 of 6
# pivots, i.e. high overlap, not just an overlapping window in the earlier
# Jaccard-dedup sense (that failed because it had no outcome constraint at
# all; this only ever compares candidates that already share both
# pattern_type/direction AND the exact bar their breakout happened on).
_PIVOT_JACCARD_MIN = 0.5


def _pivot_jaccard(a: PatternMatch, b: PatternMatch) -> float:
    sa = {p.bar_index for p in a.pivots}
    sb = {p.bar_index for p in b.pivots}
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0


def _dedupe_by_breakout_bar(matches: list[PatternMatch]) -> list[PatternMatch]:
    """Second, separate pass, over what the terminal-pivot pass already
    kept -- one representative per (pattern_type, direction, breakout_bar),
    among representatives whose pivot windows overlap enough to plausibly
    be the same structure.

    Deliberately kept as its OWN pass rather than folded into one bigger
    graph with the terminal-pivot criterion above: measured on real data,
    mixing the two into a single connected-components merge lets a
    same-terminal-pivot edge bridge into a same-breakout_bar-but-different-
    ticker-context chain and merge matches with *different* breakout_bar
    values (in one 400-ticker sample, 229 such bridged pairs, 101 of them
    between candidates with <0.3 pivot overlap -- including matches that
    never broke out at all (`breakout_bar is None`) absorbed into resolved
    ones). Grouping by exact `breakout_bar` equality first makes that
    impossible by construction: equality is transitive, so a chain built
    from it can never cross into a different breakout_bar. `None` (never
    broke out) is excluded from this pass entirely, not grouped as its own
    key -- those matches have no shared trigger event to identify by.

    Within one (pattern_type, direction, breakout_bar) group, matches still
    only merge if directly or transitively connected by pairwise pivot
    overlap >= `_PIVOT_JACCARD_MIN` -- this is what stops two *independent*
    matches that coincidentally triggered on the same calendar day (real,
    measured: a double_top pair on the same ticker sharing only their
    common boundary pivot, overlap 0.2) from being treated as one.
    """
    groups: dict[tuple, list[PatternMatch]] = {}
    for match in matches:
        if match.breakout_bar is None:
            continue
        groups.setdefault((match.pattern_type, match.direction, match.breakout_bar), []).append(match)

    to_drop: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        parent = {id(m): id(m) for m in group}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if _pivot_jaccard(group[i], group[j]) >= _PIVOT_JACCARD_MIN:
                    ra, rb = find(id(group[i])), find(id(group[j]))
                    if ra != rb:
                        parent[ra] = rb

        clusters: dict[int, list[PatternMatch]] = {}
        for m in group:
            clusters.setdefault(find(id(m)), []).append(m)
        for cluster in clusters.values():
            if len(cluster) < 2:
                continue
            winner = max(cluster, key=_dedupe_rank)
            to_drop.update(id(m) for m in cluster if m is not winner)

    return [m for m in matches if id(m) not in to_drop]


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
