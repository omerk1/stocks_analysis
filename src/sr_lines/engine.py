"""Public API: `detect(conn, ticker, config, as_of=None) -> DetectionResult`.

Orchestrates data -> pivots -> candidates -> events -> scoring -> lifecycle.
Diagonal candidates are not generated yet (milestone 5) -- only horizontal
lines are produced for now.

Lookahead note: `as_of` simply loads bars only up to that date, which
already gives pivot detection correct behavior for free (a pivot can only
appear in the output if its confirming reversal was observed within the
visible window) and lets a body-break correctly land as `pending` if there
aren't enough bars left to resolve fakeout vs. break. Full dedicated
lookahead test coverage is milestone 6 -- this is an honest interim
behavior, not a shortcut that milestone 6 needs to undo.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.sr_lines import candidates as candidates_mod
from src.sr_lines import data as data_mod
from src.sr_lines import events as events_mod
from src.sr_lines import lifecycle
from src.sr_lines import pivots as pivots_mod
from src.sr_lines import scoring as scoring_mod
from src.sr_lines.config import SRConfig
from src.sr_lines.models import DetectionResult


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    config: SRConfig,
    as_of: str | pd.Timestamp | None = None,
) -> DetectionResult:
    bars, quality = data_mod.load_and_validate(conn, ticker, config, end=as_of)

    as_of_str = pd.Timestamp(as_of).isoformat() if as_of is not None else (
        bars.index[-1].isoformat() if not bars.empty else None
    )

    if bars.empty:
        return DetectionResult(
            ticker=ticker,
            source=data_mod.REQUIRED_SOURCE,
            as_of=as_of_str,
            config_snapshot=config.to_dict(),
            data_quality=quality,
            lines=[],
        )

    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)

    horizontal_candidates = candidates_mod.generate_horizontal_candidates(pivot_list, config)
    diagonal_candidates = candidates_mod.generate_diagonal_candidates(pivot_list, config)

    lines = []
    for i, candidate in enumerate(horizontal_candidates):
        line_events, original_side = events_mod.classify_events(bars, candidate, atr, config)
        scores = scoring_mod.score_line(
            line_events, bars, atr, candidate.center, config, diagonal=False
        )
        lines.append(lifecycle.build_line(f"h{i}", candidate, line_events, original_side, scores))

    # Diagonal candidates are always empty until milestone 5; loop is a no-op
    # for now but keeps the shape stable once generate_diagonal_candidates
    # is implemented.
    for i, _candidate in enumerate(diagonal_candidates):
        raise NotImplementedError("Diagonal scoring/lifecycle wiring is milestone 5.")

    lines = lifecycle.dedup_lines(lines, config)
    lines = lifecycle.select_lines(lines, config)

    return DetectionResult(
        ticker=ticker,
        source=data_mod.REQUIRED_SOURCE,
        as_of=as_of_str,
        config_snapshot=config.to_dict(),
        data_quality=quality,
        lines=lines,
    )
