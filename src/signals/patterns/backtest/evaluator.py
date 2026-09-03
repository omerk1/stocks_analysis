"""python -m src.signals.patterns.backtest.evaluator TICKER [TICKER ...] | --all
[--timeframe daily|weekly] [--horizons 10,20,60]

Design doc §7.3's outcome-based backtest: for patterns that actually broke
out, measure what happened next -- forward returns at fixed horizons
(reported three ways: mean, median and winsorized mean, see `summarize` for
why one number is not enough here), target-hit rate, failed-breakout rate,
and throwback rate -- using real historical price data. Deliberately covers
§7.3 only, not §7.2 (precision/recall against
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
plain failed-breakout: price revisits the breakout level after breaking
out but *without* reversing through it, then continues to target) is
computed by `_find_target_hit_bar`/`had_throwback` below -- a read-only
re-walk of `bars` from `match.breakout_bar`, deliberately not touching
`lifecycle._walk_post_breakout` itself (that function only resolves final
status, it has no reason to remember *which* bar first hit target).
`had_throwback` compares against the pattern's real per-bar breakout level,
reconstructed by `_reconstruct_trigger_at` from whatever each detector
already persists on `match.key_levels`/`match.trendlines` for plotting --
exact for sloped triggers (H&S neckline, triangle/wedge/flag boundaries),
not just the flat ones (double top/bottom, cup & handle, VCP) where
`entry_price` alone would've been indistinguishable from it anyway.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, Sequence

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Direction, Timeframe
from src.signals.patterns import lifecycle
from src.signals.patterns import store as pattern_store
from src.signals.patterns.config import PatternConfig, get_preset
from src.signals.patterns.models import PatternMatch, PatternStatus, PatternType
from src.signals.patterns.scanner import scan_bars

DEFAULT_HORIZONS: tuple[int, ...] = (10, 20, 60)

# Fraction clipped off each tail for `summarize`'s winsorized mean. 1% is the
# conventional default for financial returns and is deliberately gentle: the
# aim is to stop one observation owning the statistic, not to reshape the
# distribution. Measured on real output, dropping the top 1% alone moves
# falling_wedge's 60-bar mean from +0.61% to -2.47%, so even this much
# clipping changes the sign of the conclusion.
WINSOR_LIMIT: float = 0.01


def _return_stats(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """`(mean, median, winsorized mean)` for one horizon's resolved returns,
    or `(None, None, None)` when nothing resolved at that horizon (a
    right-censored horizon, not a zero return).

    Winsorizing clips each tail to its `WINSOR_LIMIT` percentile rather than
    discarding those observations, so the sample size reported alongside
    stays the real one. With very few values the two percentiles collapse
    toward the min/max and the clip becomes a no-op, leaving the winsorized
    mean equal to the plain mean -- which is the honest outcome: there is no
    tail to bound yet.
    """
    if not values:
        return None, None, None
    series = pd.Series(values, dtype=float)
    lower, upper = series.quantile(WINSOR_LIMIT), series.quantile(1 - WINSOR_LIMIT)
    return float(series.mean()), float(series.median()), float(series.clip(lower, upper).mean())


# breakout_bar is only ever set inside lifecycle._walk_post_breakout, i.e.
# once a breakout has actually happened -- PENDING/INVALIDATED/EXPIRED
# patterns that never broke out have no trade to measure and are excluded
# from outcome stats entirely (they're a detection-funnel question, not an
# outcome one).
_BREAKOUT_STATUSES = frozenset({
    PatternStatus.CONFIRMED, PatternStatus.ACTIVE,
    PatternStatus.HIT_TARGET, PatternStatus.INVALIDATED_FAILED_BREAKOUT,
    # Broke out and ran the full §7.3 resolution horizon without hitting
    # target or being reclaimed -- a decided non-hit, so it belongs in the
    # outcome denominator. Before the horizon existed these matches walked
    # to the end of history and landed in ACTIVE, which is why the pre-fix
    # baseline showed implausible still_open rates (0.416 for inverse cup &
    # handle against 0.095 for its bullish twin).
    PatternStatus.EXPIRED_UNRESOLVED,
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
    # Both None unless status is HIT_TARGET -- throwback is only a
    # meaningful question once we know a target was actually reached.
    target_hit_bar: int | None = None
    throwback: bool | None = None


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


def _find_target_hit_bar(bars: pd.DataFrame, match: PatternMatch, config: PatternConfig) -> int | None:
    """First bar index after `match.breakout_bar` whose high/low crosses
    `match.target_price`, mirroring the exact hit condition
    `lifecycle._walk_post_breakout` used to set HIT_TARGET in the first
    place. Only meaningful when `match.status` is already HIT_TARGET;
    returns None otherwise (or defensively, if no such bar is found --
    which shouldn't happen for a HIT_TARGET match)."""
    if match.status != PatternStatus.HIT_TARGET or match.breakout_bar is None or match.target_price is None:
        return None
    is_bearish = match.direction == Direction.BEARISH
    target = match.target_price
    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    # Same horizon bound `lifecycle._walk_post_breakout` used to set
    # HIT_TARGET in the first place -- searching further than the lifecycle
    # did could only find a bar the lifecycle never considered, which would
    # report a hit date for a match it never actually credited.
    formation_bars = match.pivots[-1].bar_index - match.pivots[0].bar_index if match.pivots else 0
    horizon_end = match.breakout_bar + lifecycle.resolution_horizon_bars(formation_bars, config)
    for i in range(match.breakout_bar + 1, min(len(bars), horizon_end + 1)):
        hit = lows[i] <= target if is_bearish else highs[i] >= target
        if hit:
            return i
    return None


# Every detector already persists its trigger level elsewhere on the match
# for plotting.py's benefit -- flat levels in `key_levels` (a plain float),
# sloped ones in `trendlines` (a (slope, intercept) pair evaluated as
# `slope * bar_index + intercept`, the same form every detector's own
# `trigger_at` closure computes internally before lifecycle.py discards
# it). Reusing that persisted data here means throwback detection can
# compare against the pattern's *actual* breakout level instead of the
# fixed `entry_price` approximation -- exact for a sloped neckline/
# boundary that keeps moving after the breakout bar, where `entry_price`
# and the true trigger level diverge over time.
#
# This table is a second place that has to agree with each detector's own
# key_levels/trendlines naming -- if a future detector doesn't follow the
# existing convention, reconstruction below silently falls through to the
# entry_price approximation (see `had_throwback`) rather than erroring.
_FLAT_TRIGGER_KEY: dict[PatternType, str] = {
    PatternType.DOUBLE_TOP: "neckline",
    PatternType.DOUBLE_BOTTOM: "neckline",
    PatternType.CUP_AND_HANDLE: "neckline",
    PatternType.INVERSE_CUP_AND_HANDLE: "neckline",
    PatternType.ROUNDING_BOTTOM: "neckline",
    PatternType.ROUNDING_TOP: "neckline",
    PatternType.VCP: "pivot_price",
}

_SLOPED_FIXED_TRIGGER_KEY: dict[PatternType, str] = {
    PatternType.HEAD_AND_SHOULDERS: "neckline",
    PatternType.INVERSE_HEAD_AND_SHOULDERS: "neckline",
}

# Triangles/wedges (bidirectional breakout, `lifecycle.apply_lifecycle_bidirectional`)
# and flags/pennants (fixed direction, but still an upper/lower boundary
# pair) both store their two trendlines as "upper"/"lower" and resolve
# `match.direction` to whichever side actually broke -- so direction alone
# picks the right one, post-resolution, for both families.
_SLOPED_DIRECTIONAL_TRIGGER_TYPES = frozenset({
    PatternType.ASCENDING_TRIANGLE, PatternType.DESCENDING_TRIANGLE, PatternType.SYMMETRIC_TRIANGLE,
    PatternType.RISING_WEDGE, PatternType.FALLING_WEDGE,
    PatternType.BULL_FLAG, PatternType.BEAR_FLAG, PatternType.PENNANT,
})


def _reconstruct_trigger_at(match: PatternMatch) -> Callable[[int], float] | None:
    """Rebuild the pattern's real `trigger_at(bar_index) -> float` from
    whatever the detector persisted on `match.key_levels`/`match.trendlines`
    at detection time. Returns None if `match.pattern_type` isn't in any of
    the three lookup tables above, or if the expected key is missing from
    the match (defensive only -- every current detector populates it)."""
    pattern_type = match.pattern_type

    flat_key = _FLAT_TRIGGER_KEY.get(pattern_type)
    if flat_key is not None:
        level = match.key_levels.get(flat_key)
        if level is None:
            return None
        return lambda _i: level

    sloped_key = _SLOPED_FIXED_TRIGGER_KEY.get(pattern_type)
    if pattern_type in _SLOPED_DIRECTIONAL_TRIGGER_TYPES:
        sloped_key = "upper" if match.direction == Direction.BULLISH else "lower"
    if sloped_key is not None:
        line = match.trendlines.get(sloped_key)
        if line is None:
            return None
        slope, intercept = line
        return lambda i: slope * i + intercept

    return None


def had_throwback(bars: pd.DataFrame, match: PatternMatch, target_hit_bar: int) -> bool:
    """True if, between `breakout_bar` (exclusive) and `target_hit_bar`
    (exclusive), price closed back through the pattern's breakout level --
    Bulkowski's throwback: a revisit of the breakout level that doesn't
    reverse the breakout (that case is already INVALIDATED_FAILED_BREAKOUT,
    not HIT_TARGET) but does retrace before continuing on to target.

    Uses `_reconstruct_trigger_at`'s real per-bar level when available
    (exact for sloped triggers, which keep moving after the breakout bar);
    falls back to the fixed `entry_price` when reconstruction can't find
    the data (only possible for a pattern_type outside the three lookup
    tables above, or a hand-built match in tests)."""
    is_bearish = match.direction == Direction.BEARISH
    trigger_at = _reconstruct_trigger_at(match)
    entry = match.entry_price
    closes = bars["close"].to_numpy()
    for i in range(match.breakout_bar + 1, target_hit_bar):
        level = trigger_at(i) if trigger_at is not None else entry
        close = float(closes[i])
        if (close >= level) if is_bearish else (close <= level):
            return True
    return False


def compute_outcomes(
    matches: list[PatternMatch], bars: pd.DataFrame, horizons: Sequence[int] = DEFAULT_HORIZONS,
    config: PatternConfig | None = None,
) -> list[PatternOutcome]:
    """One `PatternOutcome` per match that actually broke out; matches
    that never triggered (PENDING/INVALIDATED/EXPIRED-pre-breakout) are
    skipped, not represented as a zero/failed outcome.

    `config` supplies the §7.3 resolution horizon used to bound the
    target-hit search; it must be the same config the matches were detected
    under, or the search window won't match the one the lifecycle used.
    Defaults to the daily preset for callers (mostly tests) that build
    matches by hand."""
    config = config if config is not None else get_preset("daily")
    outcomes = []
    for match in matches:
        if match.status not in _BREAKOUT_STATUSES or match.breakout_bar is None:
            continue
        target_hit_bar = _find_target_hit_bar(bars, match, config)
        outcomes.append(PatternOutcome(
            match_id=match.id, ticker=match.ticker, pattern_type=match.pattern_type.value,
            direction=match.direction.value, status=match.status.value, breakout_bar=match.breakout_bar,
            forward_returns={h: forward_return_pct(bars, match, h) for h in horizons},
            target_hit_bar=target_hit_bar,
            throwback=had_throwback(bars, match, target_hit_bar) if target_hit_bar is not None else None,
        ))
    return outcomes


def summarize(outcomes: list[PatternOutcome], horizons: Sequence[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """One row per pattern_type: sample size, target-hit / failed-breakout
    / unresolved / still-open rates (of matches that broke out), throwback
    rate (of matches that hit target, how many first retraced through the
    breakout level), and **three** forward-return statistics per horizon --
    mean, median and winsorized mean -- over the matches with enough forward
    data to measure that horizon (`n_resolved` reported alongside, so a thin
    horizon isn't read as more solid than it is).

    Three return statistics rather than one because the plain mean is not
    trustworthy on this data, and that isn't a subtlety -- it is the
    difference between "this pattern makes 21%" and "this pattern loses
    money." Equity forward returns are unbounded above and floored at -100%,
    so a handful of low-priced names dominate any arithmetic mean:
    `falling_wedge` reported a +21% mean 60-bar return across the universe
    while its median was *negative*, and in a 5,553-outcome sample a single
    sub-dollar stock returning +3,080% supplied 90% of the entire mean. The
    same distribution shape applies to every pattern type here -- falling
    wedge was not special, it just drew the biggest ticket.

    `median_return` is the robust central tendency: what a typical instance
    of this pattern did. `wins_return` is the mean after clipping the
    outer `WINSOR_LIMIT` of each tail to that percentile's value -- it keeps
    the mean's sensitivity to the *shape* of the distribution (a genuinely
    fat right tail still lifts it) while bounding how far one observation can
    move it. Winsorizing rather than trimming so `n_resolved` stays the true
    sample size; no observation is discarded, only capped.

    The raw `mean_return` is deliberately kept alongside them rather than
    replaced: the gap between mean and median is itself the diagnostic, and
    hiding it would just make the distortion harder to notice next time.
    """
    if not outcomes:
        return pd.DataFrame(
            columns=[
                "n", "hit_target_rate", "failed_breakout_rate", "unresolved_rate",
                "still_open_rate", "throwback_rate",
            ]
            + [f"mean_return_{h}b" for h in horizons]
            + [f"median_return_{h}b" for h in horizons]
            + [f"wins_return_{h}b" for h in horizons]
            + [f"n_resolved_{h}b" for h in horizons]
        )

    rows = {}
    by_type: dict[str, list[PatternOutcome]] = {}
    for outcome in outcomes:
        by_type.setdefault(outcome.pattern_type, []).append(outcome)

    for pattern_type, group in sorted(by_type.items()):
        n = len(group)
        n_hit_target = sum(o.status == PatternStatus.HIT_TARGET.value for o in group)
        # Denominator is outcomes with a *resolved* throwback verdict, not
        # n_hit_target -- a HIT_TARGET outcome whose target_hit_bar came
        # back None (the "shouldn't happen" defensive branch in
        # _find_target_hit_bar) leaves throwback None too, and must be
        # excluded from both sides of the ratio, not silently counted as
        # "no throwback" by staying in the denominator alone.
        throwback_resolved = [o.throwback for o in group if o.throwback is not None]
        row = {
            "n": n,
            "hit_target_rate": n_hit_target / n,
            "failed_breakout_rate": sum(o.status == PatternStatus.INVALIDATED_FAILED_BREAKOUT.value for o in group) / n,
            # Broke out, ran its full resolution horizon, resolved to
            # nothing -- a decided non-hit, reported separately from
            # still_open (which is right-censored: the horizon hasn't
            # elapsed yet in the data we have). Keeping these apart is the
            # point of EXPIRED_UNRESOLVED; folding them together would
            # reproduce the pre-fix reading where "never resolved" and "not
            # resolved yet" were the same bucket.
            "unresolved_rate": sum(o.status == PatternStatus.EXPIRED_UNRESOLVED.value for o in group) / n,
            "still_open_rate": sum(o.status in (PatternStatus.CONFIRMED.value, PatternStatus.ACTIVE.value) for o in group) / n,
            "throwback_rate": (sum(throwback_resolved) / len(throwback_resolved)) if throwback_resolved else None,
        }
        for h in horizons:
            resolved = [o.forward_returns[h] for o in group if o.forward_returns[h] is not None]
            mean_return, median_return, wins_return = _return_stats(resolved)
            row[f"mean_return_{h}b"] = mean_return
            row[f"median_return_{h}b"] = median_return
            row[f"wins_return_{h}b"] = wins_return
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
            all_outcomes.extend(compute_outcomes(matches, bars, horizons, config))
        except Exception as exc:
            print(f"{ticker} [{timeframe.value}]: FAILED -- {exc}")
    return summarize(all_outcomes, horizons)


def main():
    parser = argparse.ArgumentParser(
        description="Outcome-based backtest (design doc §7.3): forward returns, target-hit rate, "
                     "failed-breakout rate, and throwback rate for patterns that broke out, "
                     "measured against real price data."
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
        # 4 columns per horizon (mean/median/winsorized/n) plus 6 rate
        # columns -- the old cap of 20 truncated the default 3 horizons.
        pd.set_option("display.max_columns", 60)
        print(summary.round(4).to_string())

    raw_conn.close()


if __name__ == "__main__":
    main()
