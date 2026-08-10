"""Top-level detection pipeline -- wires swings.py/levels.py/lifecycle.py
together against real bar data, mirroring sr_lines.engine's precedent.
Kept separate from cli.py so tests (and store.py callers in general) can
drive a full detection run without going through argparse/DB-path setup.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field

import pandas as pd

from src.fibonacci.config import FibConfig
from src.fibonacci.levels import compute_levels, compute_weight
from src.fibonacci.lifecycle import evaluate_lifecycle
from src.fibonacci.models import FibSet
from src.fibonacci.swings import detect_swings
from src.market_common import data as data_mod
from src.market_common.indicators import atr as atr_indicator
from src.market_common.models import DataQualityReport, Timeframe

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    ticker: str
    timeframe: str
    as_of: str | None
    # Every qualifying swing, weighted and lifecycle-evaluated -- including
    # ones ranked below max_sets. Kept around for correctness/testing (spec
    # milestone 8) even though only `selected_sets` gets persisted.
    all_sets: list[FibSet] = field(default_factory=list)
    # Top `config.max_sets` of `all_sets` by weight -- what store.py
    # actually writes.
    selected_sets: list[FibSet] = field(default_factory=list)
    quality: DataQualityReport | None = None


def _as_of_str(as_of: str | pd.Timestamp | None) -> str | None:
    if as_of is None:
        return None
    return pd.Timestamp(as_of).strftime("%Y-%m-%d")


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: FibConfig,
    as_of: str | pd.Timestamp | None = None,
) -> DetectionResult:
    """`as_of` is non-negotiable no-lookahead: `load_and_validate` already
    restricts every bar this run ever sees to <= as_of, so every downstream
    guarantee (a set only "exists" if its swing's confirmed_at <= as_of,
    invalidation walked forward only through bars <= as_of) falls out of
    that single upstream cutoff rather than needing separate enforcement
    in swings/levels/lifecycle.
    """
    bars, quality = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)
    tf_str = timeframe.value if isinstance(timeframe, Timeframe) else str(timeframe)

    if len(bars) < config.min_bars:
        logger.warning(
            "%s/%s: %d bars available, below min_bars=%d -- skipping detection",
            ticker, tf_str, len(bars), config.min_bars,
        )
        return DetectionResult(ticker=ticker, timeframe=tf_str, as_of=_as_of_str(as_of), quality=quality)

    close = bars["close"]
    atr = atr_indicator(bars, config.atr_period)

    trimmed_close = close.iloc[config.warmup_bars:]
    trimmed_atr = atr.iloc[config.warmup_bars:]

    swings = detect_swings(trimmed_close, trimmed_atr, config)
    last_bar_index = len(trimmed_close) - 1

    all_sets: list[FibSet] = []
    for swing in swings:
        bars_since_end = last_bar_index - swing.end_bar_index
        weight = compute_weight(swing, bars_since_end, config)
        status, invalidated_date = evaluate_lifecycle(swing, close)
        levels = compute_levels(swing, config)
        all_sets.append(
            FibSet(
                id=str(uuid.uuid4()),
                ticker=ticker,
                timeframe=Timeframe(tf_str),
                swing=swing,
                levels=levels,
                weight=weight,
                status=status,
                invalidated_date=invalidated_date,
            )
        )

    # Invalidated sets still count toward max_sets ranking -- invalidation
    # is a status field, not removal from contention (see lifecycle.py /
    # spec). Ranking purely by weight, computed above independent of
    # status, already achieves this without extra handling.
    all_sets.sort(key=lambda s: s.weight, reverse=True)
    selected_sets = all_sets[: config.max_sets]

    return DetectionResult(
        ticker=ticker, timeframe=tf_str, as_of=_as_of_str(as_of),
        all_sets=all_sets, selected_sets=selected_sets, quality=quality,
    )
