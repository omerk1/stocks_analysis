"""python -m src.signals.market_structure.backtest TICKER [TICKER ...] | --all
[--timeframe daily|weekly] [--horizons 10,20,60] [--whipsaw-bars 60]

Outcome-based backtest for BOS/CHoCH (`docs/features/pivot_breakout_validation_backtest_design.md`
§3): does market-structure tracking carry real information, or is it
correctly-detected geometry with no edge? Modeled directly on
`patterns/backtest/evaluator.py`'s shape, not reinvented -- same fresh
full-history scan (not reading stored `market_structure_events`, which may
be stale/differently-configured), same `market_common.stats.distribution_stats`
statistical treatment for forward returns.

`TrendState` has no target/stop/lifecycle the way `PatternMatch` does --
BOS/CHoCH is an open-ended regime tracker, not a bounded formation -- so
outcomes here are grouped by `(event, direction)` (four buckets: CHoCH-
bullish, CHoCH-bearish, BOS-bullish, BOS-bearish) rather than by
`pattern_type`, and a second metric answers a question a resolved
lifecycle doesn't need to ask: does the regime whipsaw? A CHoCH can show a
solidly positive N-bar forward return while having already flipped back
before that horizon elapsed -- `whipsaw_rate` reports, for each CHoCH, how
often an opposite-direction CHoCH fires within `whipsaw_bars`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common import indicators
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.foundation.market_common.stats import DEFAULT_PERCENTILES, distribution_stats
from src.signals.market_structure import store
from src.signals.market_structure.config import MarketStructureConfig, get_preset
from src.signals.market_structure.detect import track_market_structure
from src.signals.market_structure.models import Direction, StructureEvent, TrendState

DEFAULT_HORIZONS: tuple[int, ...] = (10, 20, 60)

# How far past a CHoCH to look for an opposite-direction CHoCH before
# calling the regime "survived" -- matches the longest default forward-
# return horizon, so whipsaw_rate covers the same window the return
# statistics are already measuring.
DEFAULT_WHIPSAW_BARS: int = 60


@dataclass
class StructureOutcome:
    event_id: str
    ticker: str
    timeframe: str
    event: str
    direction: str
    broken_at: str
    break_bar: int
    # horizon (bars) -> signed forward return, or None if `bars` doesn't
    # extend far enough past break_bar yet to measure that horizon
    # (right-censored, not a zero return).
    forward_returns: dict[int, float | None]
    # None for a BOS (the question doesn't apply -- a BOS doesn't flip the
    # regime, there's nothing to "survive"). For a CHoCH: True if an
    # opposite-direction CHoCH fires within `whipsaw_bars`; False if the
    # full window elapsed without one; None if `bars` doesn't extend
    # `whipsaw_bars` past the break yet (right-censored, same discipline
    # as `forward_returns` -- not yet knowable is not the same as "no").
    whipsawed: bool | None
    # BOS/CHoCH has no confidence score yet (see
    # docs/features/shared_outcome_statistics_design.md §4) -- carried as
    # None so this schema doesn't need a second migration once that lands.
    confidence: float | None = None


def _bar_index(bars: pd.DataFrame, timestamp: str) -> int:
    return bars.index.get_loc(pd.Timestamp(timestamp))


def forward_return_pct(bars: pd.DataFrame, event: TrendState, horizon_bars: int) -> float | None:
    """Signed % return `horizon_bars` after `event`'s break bar, positive
    meaning the event's own direction played out (a bearish CHoCH profits
    from price falling, so its raw price return is negated). `TrendState`
    has no `entry_price` the way `PatternMatch` does -- `event.close` (the
    break bar's own close) is the entry basis. None if `bars` doesn't have
    a close that far past the break bar yet."""
    break_idx = _bar_index(bars, event.broken_at)
    target_idx = break_idx + horizon_bars
    if target_idx >= len(bars) or event.close == 0:
        return None
    raw_return = (float(bars["close"].iloc[target_idx]) - event.close) / event.close
    return raw_return if event.direction != Direction.BEARISH else -raw_return


def _had_whipsaw(
    indexed_events: list[tuple[int, TrendState]], break_idx: int, event: TrendState, whipsaw_bars: int,
    n_bars: int,
) -> bool | None:
    """True if an opposite-direction CHoCH for the same ticker fires
    strictly after `event` and within `whipsaw_bars` of it -- the regime
    this CHoCH just established didn't survive that window.

    A found reversal is reported as soon as it's found, censoring or not.
    But absence of one is only a genuine False once `whipsaw_bars` has
    actually elapsed within `bars` -- a CHoCH near the end of available
    history hasn't had its full window observed yet, and reporting False
    there would silently read as "regime survived" when the honest answer
    is "don't know yet" (the same right-censoring `forward_return_pct`
    already applies to forward returns)."""
    opposite = Direction.BEARISH if event.direction == Direction.BULLISH else Direction.BULLISH
    for other_idx, other in indexed_events:
        if other is event or other.event != StructureEvent.CHOCH:
            continue
        if break_idx < other_idx <= break_idx + whipsaw_bars and other.direction == opposite:
            return True
    if break_idx + whipsaw_bars >= n_bars:
        return None
    return False


def compute_outcomes(
    events: list[TrendState], bars: pd.DataFrame, horizons: Sequence[int] = DEFAULT_HORIZONS,
    whipsaw_bars: int = DEFAULT_WHIPSAW_BARS,
) -> list[StructureOutcome]:
    """One `StructureOutcome` per event -- unlike `patterns.compute_outcomes`,
    there's no PENDING/INVALIDATED funnel to filter here: every emitted
    `TrendState` is already a realized break."""
    indexed = [(_bar_index(bars, e.broken_at), e) for e in events]
    outcomes = []
    for break_idx, event in indexed:
        whipsawed = (
            _had_whipsaw(indexed, break_idx, event, whipsaw_bars, len(bars))
            if event.event == StructureEvent.CHOCH else None
        )
        outcomes.append(StructureOutcome(
            event_id=event.id, ticker=event.ticker, timeframe=event.timeframe.value,
            event=event.event.value, direction=event.direction.value, broken_at=event.broken_at,
            break_bar=break_idx,
            forward_returns={h: forward_return_pct(bars, event, h) for h in horizons},
            whipsawed=whipsawed,
        ))
    return outcomes


def summarize(outcomes: list[StructureOutcome], horizons: Sequence[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """One row per `(event, direction)` bucket -- `choch_bullish`,
    `choch_bearish`, `bos_bullish`, `bos_bearish` -- rather than per
    `pattern_type`, since market structure doesn't have one. This is the
    natural split: does a CHoCH's implied reversal actually hold,
    separately from whether a BOS's implied continuation holds.

    `whipsaw_rate` is only meaningful for the two CHoCH buckets (None for
    BOS, which never flips the regime) -- of CHoCH events in this bucket,
    how many saw an opposite-direction CHoCH within the whipsaw window
    `compute_outcomes` was called with.

    Per-horizon return statistics are `market_common.stats.distribution_stats`
    unchanged -- see `patterns/backtest/evaluator.py::summarize` for why a
    plain mean isn't trustworthy on this kind of data; the same reasoning
    applies here without modification.
    """
    percentile_labels = [f"p{int(p * 100)}" for p in DEFAULT_PERCENTILES]
    stat_columns = (
        [f"mean_return_{h}b" for h in horizons]
        + [f"median_return_{h}b" for h in horizons]
        + [f"wins_return_{h}b" for h in horizons]
        + [f"std_return_{h}b" for h in horizons]
        + [f"risk_adj_return_{h}b" for h in horizons]
        + [f"{label}_return_{h}b" for h in horizons for label in percentile_labels]
        + [f"n_resolved_{h}b" for h in horizons]
    )
    if not outcomes:
        return pd.DataFrame(columns=["n", "whipsaw_rate"] + stat_columns)

    rows = {}
    by_bucket: dict[str, list[StructureOutcome]] = {}
    for outcome in outcomes:
        by_bucket.setdefault(f"{outcome.event}_{outcome.direction}", []).append(outcome)

    for bucket, group in sorted(by_bucket.items()):
        whipsaw_resolved = [o.whipsawed for o in group if o.whipsawed is not None]
        row = {
            "n": len(group),
            "whipsaw_rate": (sum(whipsaw_resolved) / len(whipsaw_resolved)) if whipsaw_resolved else None,
        }
        for h in horizons:
            resolved = [o.forward_returns[h] for o in group if o.forward_returns[h] is not None]
            stats = distribution_stats(resolved)
            row[f"mean_return_{h}b"] = stats.mean
            row[f"median_return_{h}b"] = stats.median
            row[f"wins_return_{h}b"] = stats.winsorized_mean
            row[f"std_return_{h}b"] = stats.std
            row[f"risk_adj_return_{h}b"] = stats.risk_adjusted_return
            for p, label in zip(DEFAULT_PERCENTILES, percentile_labels):
                row[f"{label}_return_{h}b"] = stats.percentiles[p]
            row[f"n_resolved_{h}b"] = stats.n
        rows[bucket] = row

    return pd.DataFrame.from_dict(rows, orient="index")


def run_backtest(
    raw_conn, tickers: list[str], timeframe: Timeframe, config: MarketStructureConfig,
    horizons: Sequence[int] = DEFAULT_HORIZONS, whipsaw_bars: int = DEFAULT_WHIPSAW_BARS,
) -> pd.DataFrame:
    """Fresh full-history scan per ticker, mirroring
    `patterns.backtest.evaluator.run_backtest`'s reasoning exactly:
    `market_structure_events` may have been populated at a different
    `as_of`/config, and this needs the realized-outcome view. Continue-on-
    error per ticker so one ticker's bad data doesn't lose every other
    ticker's already-computed outcomes."""
    all_outcomes: list[StructureOutcome] = []
    for ticker in tickers:
        try:
            bars, _report = data_mod.load_and_validate(raw_conn, ticker, timeframe)
            if len(bars) < config.min_bars:
                continue
            atr = indicators.atr(bars, config.atr_period)
            pivots = detect_pivots(
                bars["high"], bars["low"], threshold_fn=lambda i: config.pivot_atr_mult * atr.iloc[i],
            )
            events = track_market_structure(bars, pivots, config, ticker, timeframe)
            all_outcomes.extend(compute_outcomes(events, bars, horizons, whipsaw_bars))
        except Exception as exc:
            print(f"{ticker} [{timeframe.value}]: FAILED -- {exc}")
    return summarize(all_outcomes, horizons)


def main():
    parser = argparse.ArgumentParser(
        description="Outcome-based backtest for BOS/CHoCH: forward returns and whipsaw rate, "
                     "split by (event, direction), measured against real price data."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("tickers", nargs="*", default=[], help="Tickers to backtest")
    target.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument("--timeframe", default="daily", choices=["daily", "weekly"])
    parser.add_argument(
        "--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS),
        help=f"Comma-separated forward-return horizons in bars (default: {DEFAULT_HORIZONS})",
    )
    parser.add_argument(
        "--whipsaw-bars", type=int, default=DEFAULT_WHIPSAW_BARS,
        help=f"Bars to look ahead of a CHoCH for an opposite-direction CHoCH (default: {DEFAULT_WHIPSAW_BARS})",
    )
    args = parser.parse_args()

    timeframe = Timeframe(args.timeframe)
    horizons = tuple(int(h) for h in args.horizons.split(","))
    config = get_preset("daily" if timeframe == Timeframe.DAILY else "weekly")

    raw_conn, _derived_conn = derived_db.bootstrap_cli(store.create_market_structure_table)

    if args.all:
        tickers = [
            row[0] for row in raw_conn.execute(
                "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (db.YFINANCE,)
            ).fetchall()
        ]
    else:
        tickers = args.tickers

    summary = run_backtest(raw_conn, tickers, timeframe, config, horizons, args.whipsaw_bars)
    if summary.empty:
        print("No market-structure outcomes found (no BOS/CHoCH events across the given tickers).")
    else:
        pd.set_option("display.width", 220)
        pd.set_option("display.max_columns", 100)
        print(summary.round(4).to_string())

    raw_conn.close()


if __name__ == "__main__":
    main()
