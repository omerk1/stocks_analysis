"""python -m src.patterns.backtest.evaluator TICKER [TICKER ...] | --all
[--timeframe daily|weekly] [--horizons 10,20,60]

Design doc §7.3's outcome-based backtest: for patterns that actually broke
out, measure what happened next -- forward returns at fixed horizons,
target-hit rate, and failed-breakout rate -- using real historical price
data. Deliberately covers §7.3 only, not §7.2 (precision/recall against
hand labels): `pattern_labels` (backtest/labeler.py's table) is empty --
the labeler is human-in-the-loop and nobody has run it against real charts
yet -- so precision/recall can't be verified against real data today, the
same discipline every phase in this module has followed (never ship a
metric you can't check against something real). Add a `precision_recall()`
here once that table actually has rows, not before.

The other harness capability `docs/backlog.md` flags as missing --
reconstructing "what did detection believe on day D" after day D+5's
re-run overwrote it in `pattern_matches` -- isn't needed for outcome
stats. `lifecycle.apply_lifecycle`'s post-breakout walk already resolves a
match's *final* status (HIT_TARGET / INVALIDATED_FAILED_BREAKOUT /
EXPIRED / still-open ACTIVE) by walking forward through every bar visible
to it -- so scanning with the full available history (no `as_of`, unlike
`scanner.detect`'s point-in-time mode) already gives the realized outcome
directly, no separate re-run infrastructure required. That gap only
matters for auditing detection quality at a specific past date against
labels (§7.2's concern) -- deferred alongside precision/recall above.

Throwback rate (design doc §7.3's other Bulkowski benchmark, distinct from
plain failed-breakout: price revisits the trigger level after breaking out
but *without* reversing through it, then continues to target) is left out
-- it needs the actual target-hit bar, not just final status, and nothing
here computes that yet. A real gap, not silently dropped: noted so it
isn't mistaken for "already covered by failed_breakout_rate."
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from src.data_processing import db
from src.market_common import data as data_mod
from src.market_common import derived_db
from src.market_common.models import Direction, Timeframe
from src.patterns import store as pattern_store
from src.patterns.config import PatternConfig, get_preset
from src.patterns.models import PatternMatch, PatternStatus
from src.patterns.scanner import scan_bars

DEFAULT_HORIZONS: tuple[int, ...] = (10, 20, 60)

# breakout_bar is only ever set inside lifecycle._walk_post_breakout, i.e.
# once a breakout has actually happened -- PENDING/INVALIDATED/EXPIRED
# patterns that never broke out have no trade to measure and are excluded
# from outcome stats entirely (they're a detection-funnel question, not an
# outcome one).
_BREAKOUT_STATUSES = frozenset({
    PatternStatus.CONFIRMED, PatternStatus.ACTIVE,
    PatternStatus.HIT_TARGET, PatternStatus.INVALIDATED_FAILED_BREAKOUT,
})


@dataclass
class PatternOutcome:
    match_id: str
    ticker: str
    pattern_type: str
    direction: str
    status: str
    breakout_bar: int
    # horizon (bars) -> signed forward return, or None if `bars` doesn't
    # extend far enough past breakout_bar yet to measure that horizon
    # (right-censored, not a zero return).
    forward_returns: dict[int, float | None]


def forward_return_pct(bars: pd.DataFrame, match: PatternMatch, horizon_bars: int) -> float | None:
    """Signed % return `horizon_bars` after breakout, positive meaning
    profitable in the pattern's traded direction (a BEARISH match profits
    from price falling, so its raw price return is negated). None if
    `bars` doesn't have a close that far past `match.breakout_bar` yet."""
    target_idx = match.breakout_bar + horizon_bars
    if target_idx >= len(bars) or match.entry_price is None or match.entry_price == 0:
        return None
    raw_return = (float(bars["close"].iloc[target_idx]) - match.entry_price) / match.entry_price
    return raw_return if match.direction != Direction.BEARISH else -raw_return


def compute_outcomes(
    matches: list[PatternMatch], bars: pd.DataFrame, horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> list[PatternOutcome]:
    """One `PatternOutcome` per match that actually broke out; matches
    that never triggered (PENDING/INVALIDATED/EXPIRED-pre-breakout) are
    skipped, not represented as a zero/failed outcome."""
    outcomes = []
    for match in matches:
        if match.status not in _BREAKOUT_STATUSES or match.breakout_bar is None:
            continue
        outcomes.append(PatternOutcome(
            match_id=match.id, ticker=match.ticker, pattern_type=match.pattern_type.value,
            direction=match.direction.value, status=match.status.value, breakout_bar=match.breakout_bar,
            forward_returns={h: forward_return_pct(bars, match, h) for h in horizons},
        ))
    return outcomes


def summarize(outcomes: list[PatternOutcome], horizons: Sequence[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """One row per pattern_type: sample size, target-hit / failed-breakout
    / still-open rates (of matches that broke out), and mean forward
    return per horizon (over only the matches with enough forward data to
    measure that horizon -- reported n_resolved alongside each so a thin
    horizon's mean isn't read as more solid than it is)."""
    if not outcomes:
        return pd.DataFrame(
            columns=["n", "hit_target_rate", "failed_breakout_rate", "still_open_rate"]
            + [f"mean_return_{h}b" for h in horizons] + [f"n_resolved_{h}b" for h in horizons]
        )

    rows = {}
    by_type: dict[str, list[PatternOutcome]] = {}
    for outcome in outcomes:
        by_type.setdefault(outcome.pattern_type, []).append(outcome)

    for pattern_type, group in sorted(by_type.items()):
        n = len(group)
        row = {
            "n": n,
            "hit_target_rate": sum(o.status == PatternStatus.HIT_TARGET.value for o in group) / n,
            "failed_breakout_rate": sum(o.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT.value for o in group) / n,
            "still_open_rate": sum(o.status in (PatternStatus.CONFIRMED.value, PatternStatus.ACTIVE.value) for o in group) / n,
        }
        for h in horizons:
            resolved = [o.forward_returns[h] for o in group if o.forward_returns[h] is not None]
            row[f"mean_return_{h}b"] = sum(resolved) / len(resolved) if resolved else None
            row[f"n_resolved_{h}b"] = len(resolved)
        rows[pattern_type] = row

    return pd.DataFrame.from_dict(rows, orient="index")


def run_backtest(
    raw_conn, tickers: list[str], timeframe: Timeframe, config: PatternConfig,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Fresh full-history scan per ticker (deliberately not reading
    `pattern_matches` -- that table may have been populated at a different
    `as_of`/config, and this needs the realized-outcome view, not
    whatever's currently stored). Continue-on-error per ticker, same as
    `cli.py main()`'s own per-ticker try/except -- one ticker's bad data
    (e.g. `validate_bars` raising on a corrupt row) shouldn't abort a
    `--all` run and lose every other ticker's already-computed outcomes."""
    all_outcomes: list[PatternOutcome] = []
    for ticker in tickers:
        try:
            bars, _report = data_mod.load_and_validate(raw_conn, ticker, timeframe)
            if len(bars) < config.min_bars:
                continue
            matches = scan_bars(bars, ticker, timeframe, config)
            all_outcomes.extend(compute_outcomes(matches, bars, horizons))
        except Exception as exc:
            print(f"{ticker} [{timeframe.value}]: FAILED -- {exc}")
    return summarize(all_outcomes, horizons)


def main():
    parser = argparse.ArgumentParser(
        description="Outcome-based backtest (design doc §7.3): forward returns, target-hit rate, "
                     "failed-breakout rate for patterns that broke out, measured against real price data."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("tickers", nargs="*", default=[], help="Tickers to backtest")
    target.add_argument("--all", action="store_true", help="Run for every distinct ticker in bars_1d")
    parser.add_argument("--timeframe", default="daily", choices=["daily", "weekly"])
    parser.add_argument(
        "--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS),
        help=f"Comma-separated forward-return horizons in bars (default: {DEFAULT_HORIZONS})",
    )
    args = parser.parse_args()

    timeframe = Timeframe(args.timeframe)
    horizons = tuple(int(h) for h in args.horizons.split(","))
    config = get_preset("daily" if timeframe == Timeframe.DAILY else "weekly")

    raw_conn, _derived_conn = derived_db.bootstrap_cli(pattern_store.create_pattern_matches_table)

    if args.all:
        tickers = [
            row[0] for row in raw_conn.execute(
                "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (db.YFINANCE,)
            ).fetchall()
        ]
    else:
        tickers = args.tickers

    summary = run_backtest(raw_conn, tickers, timeframe, config, horizons)
    if summary.empty:
        print("No breakout outcomes found (no matches broke out across the given tickers).")
    else:
        pd.set_option("display.width", 160)
        pd.set_option("display.max_columns", 20)
        print(summary.round(4).to_string())

    raw_conn.close()


if __name__ == "__main__":
    main()
