"""python -m src.signals.patterns.backtest.evaluator TICKER [TICKER ...] | --all
[--timeframe daily|weekly] [--horizons 10,20,60]

Design doc §7.3's outcome-based backtest: for patterns that actually broke
out, measure what happened next -- forward returns at fixed horizons
(reported three ways: mean, median and winsorized mean, see `summarize` for
why one number is not enough here), each horizon also reported as an excess
over a matched same-ticker control (see `control_forward_returns` for the
matching), target-hit rate, failed-breakout rate,
and throwback rate -- using real historical price data. Returns are
measured from the executable entry -- the open of the bar after the
breakout bar (the repo's one-bar lag: signal on the close of t, fill at
the open of t+1) -- never from the breakout bar's own close, which is a
signal level a trader acting on that close cannot obtain. Deliberately covers
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
not just the flat ones (double top/bottom, cup & handle, VCP) where the
stored level is a constant. (The last-resort fallback is the breakout
bar's own close, which sits within the breakout buffer of the trigger --
not `entry_price`, which is now the next bar's open fill -- see
`had_throwback`.)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import data as data_mod
from src.foundation.market_common import derived_db
from src.foundation.market_common.models import Direction, Timeframe
from src.foundation.market_common.stats import DEFAULT_PERCENTILES, distribution_stats
from src.signals.patterns import lifecycle
from src.signals.patterns import store as pattern_store
from src.signals.patterns.config import PatternConfig, get_preset
from src.signals.patterns.models import PatternMatch, PatternStatus, PatternType
from src.signals.patterns.scanner import scan_bars
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS, source_for

DEFAULT_HORIZONS: tuple[int, ...] = (10, 20, 60)


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
    # (right-censored, not a zero return), or if the breakout bar was the
    # last visible bar (no next open exists, so there was no entry).
    forward_returns: dict[int, float | None]
    # horizon (bars) -> matched-control forward return for this outcome
    # (see control_forward_returns), or None when the control couldn't be
    # computed. summarize() reports the per-outcome delta against this.
    control_returns: dict[int, float | None] = field(default_factory=dict)
    # The breakout bar's date, for effective-N reporting (CLAUDE.md
    # invariant #6: events cluster on market-wide dates, so distinct dates
    # are the real observation count). None when `bars` has no datetime
    # index (hand-built positional test frames).
    breakout_date: pd.Timestamp | None = None
    # The detector's own scoring.py confidence at match time -- carried
    # through so summarize() can eventually bucket outcomes by confidence
    # and check whether the score actually predicts anything, which
    # nothing in this repo could do before this field existed.
    confidence: float | None = None
    # Both None unless status is HIT_TARGET -- throwback is only a
    # meaningful question once we know a target was actually reached.
    target_hit_bar: int | None = None
    throwback: bool | None = None


def forward_return_pct(bars: pd.DataFrame, match: PatternMatch, horizon_bars: int) -> float | None:
    """Signed % return `horizon_bars` after breakout, positive meaning
    profitable in the pattern's traded direction (a BEARISH match profits
    from price falling, so its raw price return is negated). Measured from
    `match.entry_price` -- the open of the bar after the breakout bar (the
    one-bar lag, set in lifecycle._walk_post_breakout) -- to the close of
    `breakout_bar + horizon_bars`. None if `bars` doesn't have a close that
    far past `match.breakout_bar` yet, or if the match has no entry at all
    (breakout on the last visible bar)."""
    target_idx = match.breakout_bar + horizon_bars
    # The finiteness/positivity guard mirrors control_forward_returns' --
    # a NaN entry (bars that never went through validate_bars) must come
    # back None, not a NaN that slips past summarize's `is not None`
    # filters and poisons every stat in the row.
    if (
        target_idx >= len(bars)
        or match.entry_price is None
        or not np.isfinite(match.entry_price)
        or match.entry_price <= 0
    ):
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
# fixed breakout-close approximation -- exact for a sloped neckline/
# boundary that keeps moving after the breakout bar, where any frozen
# level and the true trigger diverge over time.
#
# This table is a second place that has to agree with each detector's own
# key_levels/trendlines naming -- if a future detector doesn't follow the
# existing convention, reconstruction below silently falls through to the
# breakout-close approximation (see `had_throwback`) rather than erroring.
_FLAT_TRIGGER_KEY: dict[PatternType, str] = {
    PatternType.DOUBLE_TOP: "neckline",
    PatternType.DOUBLE_BOTTOM: "neckline",
    PatternType.CUP_AND_HANDLE: "neckline",
    PatternType.INVERSE_CUP_AND_HANDLE: "neckline",
    PatternType.ROUNDING_BOTTOM: "neckline",
    PatternType.ROUNDING_TOP: "neckline",
    PatternType.VCP: "pivot_price",
    PatternType.TRIPLE_TOP: "neckline",
    PatternType.TRIPLE_BOTTOM: "neckline",
    PatternType.REVERSAL_123: "point2",
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
    falls back to the breakout bar's own close when reconstruction can't
    find the data (only possible for a pattern_type outside the three
    lookup tables above, or a hand-built match in tests). The breakout
    close -- not `entry_price`, which is now the next bar's open fill --
    is the right stand-in: it sits within `breakout_buffer_pct` of the
    trigger by construction, where the next open can gap arbitrarily far
    from the level and misread every close between the two as a revisit."""
    is_bearish = match.direction == Direction.BEARISH
    trigger_at = _reconstruct_trigger_at(match)
    closes = bars["close"].to_numpy()
    fallback_level = float(closes[match.breakout_bar])
    for i in range(match.breakout_bar + 1, target_hit_bar):
        level = trigger_at(i) if trigger_at is not None else fallback_level
        close = float(closes[i])
        if (close >= level) if is_bearish else (close <= level):
            return True
    return False


# Matched-control parameters: how far (in bars) around the breakout the
# control entry bars are drawn from, and the minimum number of control
# entries required before a control value is reported at all -- below it
# the control is None rather than a noisy handful of bars pretending to
# be a baseline.
CONTROL_WINDOW_BARS = 126
CONTROL_MIN_N = 20


def control_forward_returns(
    bars: pd.DataFrame, match: PatternMatch, horizons: Sequence[int], config: PatternConfig,
) -> dict[int, float | None]:
    """Matched-control forward return per horizon, for reporting each
    outcome as a delta rather than a bare conditional mean (the repo-wide
    control discipline -- a number without its control is not a result).

    The control matches ticker, direction and trade mechanics, and differs
    only in the conditioning on the pattern: the *same ticker's* signed
    forward return (enter at the open of bar j+1, exit at the close of bar
    j+h -- identical to the pattern trade's one-bar-lag mechanics, signed
    by the pattern's traded direction) over the `CONTROL_WINDOW_BARS` bars
    immediately *before* the pattern's formation started, summarized as
    the median. Median, not mean, for the same fat-tail reason `summarize`
    documents. So the delta answers: did entering on this breakout beat
    entering on an ordinary recent day of the same stock, traded the same
    way? That controls for the ticker's own drift -- the confound that
    makes a bare "pattern X returned +2%" unreadable.

    Pre-formation bars only -- every control trade (entry AND exit) fully
    completes before the formation's first pivot -- never post-breakout
    ones: a control drawn from after the breakout contains the very move
    being measured (a breakout that launches a rally would lift its own
    baseline and attenuate the delta toward zero), and near the end of
    loaded history it would silently fall back to pre-breakout bars
    anyway, benchmarking different outcomes against structurally different
    windows. The cost is a regime gap between the control window and the
    trade window (the formation sits between them); accepted -- a
    mechanical bias is worse than extra noise. Deliberately simple beyond
    that: no cross-sectional matching on volatility or liquidity (a
    C1-style refinement if this ever graduates beyond a descriptive
    diagnostic).

    None for a horizon when fewer than `CONTROL_MIN_N` control trades fit
    (short pre-pattern history, or a horizon close to the window length),
    when the horizon isn't a positive bar count, or when `bars` carries no
    "open" column (hand-built test frames)."""
    if "open" not in bars.columns or match.breakout_bar is None:
        return {h: None for h in horizons}
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    footprint_start = match.pivots[0].bar_index if match.pivots else match.breakout_bar
    j = np.arange(max(0, footprint_start - CONTROL_WINDOW_BARS), footprint_start)
    sign = -1.0 if match.direction == Direction.BEARISH else 1.0

    out: dict[int, float | None] = {}
    for h in horizons:
        if h < 1:  # a CLI-supplied 0/negative horizon must not index off the array or wrap
            out[h] = None
            continue
        # Exit strictly before the formation's first pivot (which is <= n),
        # so the whole control trade -- entry at jj+1 included -- predates
        # the pattern.
        jj = j[j + h < footprint_start]
        entries = opens[jj + 1]
        exits = closes[jj + h]
        valid = np.isfinite(entries) & np.isfinite(exits) & (entries > 0)
        rets = sign * (exits[valid] - entries[valid]) / entries[valid]
        out[h] = float(np.median(rets)) if len(rets) >= CONTROL_MIN_N else None
    return out


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
    has_dates = isinstance(bars.index, pd.DatetimeIndex)
    outcomes = []
    for match in matches:
        if match.status not in _BREAKOUT_STATUSES or match.breakout_bar is None:
            continue
        target_hit_bar = _find_target_hit_bar(bars, match, config)
        forward_returns = {h: forward_return_pct(bars, match, h) for h in horizons}
        # A control is only ever consumed as the other side of a delta, so
        # an outcome with no measurable pattern leg at all (no entry, or
        # every horizon right-censored) skips the window scan entirely.
        control_returns = (
            control_forward_returns(bars, match, horizons, config)
            if any(r is not None for r in forward_returns.values())
            else {h: None for h in horizons}
        )
        outcomes.append(PatternOutcome(
            match_id=match.id, ticker=match.ticker, pattern_type=match.pattern_type.value,
            direction=match.direction.value, status=match.status.value, breakout_bar=match.breakout_bar,
            forward_returns=forward_returns,
            control_returns=control_returns,
            breakout_date=bars.index[match.breakout_bar] if has_dates and match.breakout_bar < len(bars) else None,
            confidence=match.confidence,
            target_hit_bar=target_hit_bar,
            throwback=had_throwback(bars, match, target_hit_bar) if target_hit_bar is not None else None,
        ))
    return outcomes


def summarize(outcomes: list[PatternOutcome], horizons: Sequence[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """One row per pattern_type: sample size, target-hit / failed-breakout
    / unresolved / still-open rates (of matches that broke out), throwback
    rate (of matches that hit target, how many first retraced through the
    breakout level), and per-horizon forward-return statistics from
    `market_common.stats.distribution_stats` -- mean, median, winsorized
    mean, std, a risk-adjusted-return ratio, and the p10/p25/p75/p90
    percentiles -- over the matches with enough forward data to measure
    that horizon (`n_resolved` reported alongside, so a thin horizon isn't
    read as more solid than it is).

    Multiple return statistics rather than one because the plain mean is
    not trustworthy on this data, and that isn't a subtlety -- it is the
    difference between "this pattern makes 21%" and "this pattern loses
    money." Equity forward returns are unbounded above and floored at -100%,
    so a handful of low-priced names dominate any arithmetic mean:
    `falling_wedge` reported a +21% mean 60-bar return across the universe
    while its median was *negative*, and in a 5,553-outcome sample a single
    sub-dollar stock returning +3,080% supplied 90% of the entire mean. The
    same distribution shape applies to every pattern type here -- falling
    wedge was not special, it just drew the biggest ticket.

    `median_return` is the robust central tendency: what a typical instance
    of this pattern did. `wins_return` is the mean after clipping the outer
    tail (`market_common.stats.DEFAULT_WINSOR_LIMIT`) to that percentile's
    value -- it keeps the mean's sensitivity to the *shape* of the
    distribution (a genuinely fat right tail still lifts it) while bounding
    how far one observation can move it. Winsorizing rather than trimming
    so `n_resolved` stays the true sample size; no observation is discarded,
    only capped. `p10`/`p25`/`p75`/`p90` give the spread the median alone
    can't: p25/p75 an IQR-style typical range, p10/p90 tail behavior
    without raw min/max's instability on a small sample.

    `risk_adj_return` is `mean / std` -- a per-event analog of Sharpe's
    ratio of return to volatility, answering "how big is this pattern's
    edge relative to its own noise." Deliberately not called Sharpe: these
    are independent per-event outcomes at a fixed horizon, not a
    compounding equity curve, so there's no risk-free rate or annualization
    to apply. None whenever a horizon has fewer than 2 resolved outcomes
    (no variance to divide by).

    The raw `mean_return` is deliberately kept alongside the rest rather
    than replaced: the gap between mean and median is itself the
    diagnostic, and hiding it would just make the distortion harder to
    notice next time.

    `excess_median_{h}b` is the headline number per horizon: the median of
    per-outcome (pattern return - matched control return) deltas, over the
    outcomes where both sides resolved (`n_excess_{h}b` alongside). The raw
    return columns are the pattern leg alone -- a bare conditional mean --
    and must not be read as evidence without the excess next to them; see
    `control_forward_returns` for what the control matches. The rate
    columns (hit/failed/unresolved/throwback) stay uncontrolled: they
    describe the pattern's own mechanics (did its target print), not a
    return claim, and have no meaningful no-pattern counterpart.

    `n_dates` is the effective N: distinct breakout *dates* in the group
    (None when outcomes carry no dates -- hand-built frames). Breakouts
    cluster on market-wide days, so n alone overstates the evidence; read
    every count against it.
    """
    percentile_labels = [f"p{int(p * 100)}" for p in DEFAULT_PERCENTILES]
    if not outcomes:
        return pd.DataFrame(
            columns=[
                "n", "n_dates", "hit_target_rate", "failed_breakout_rate", "unresolved_rate",
                "still_open_rate", "throwback_rate",
            ]
            + [f"mean_return_{h}b" for h in horizons]
            + [f"median_return_{h}b" for h in horizons]
            + [f"wins_return_{h}b" for h in horizons]
            + [f"std_return_{h}b" for h in horizons]
            + [f"risk_adj_return_{h}b" for h in horizons]
            + [f"{label}_return_{h}b" for h in horizons for label in percentile_labels]
            + [f"excess_median_{h}b" for h in horizons]
            + [f"n_excess_{h}b" for h in horizons]
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
        dates = {o.breakout_date for o in group if o.breakout_date is not None}
        row = {
            "n": n,
            "n_dates": len(dates) if dates else None,
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
            stats = distribution_stats(resolved)
            row[f"mean_return_{h}b"] = stats.mean
            row[f"median_return_{h}b"] = stats.median
            row[f"wins_return_{h}b"] = stats.winsorized_mean
            row[f"std_return_{h}b"] = stats.std
            row[f"risk_adj_return_{h}b"] = stats.risk_adjusted_return
            for p, label in zip(DEFAULT_PERCENTILES, percentile_labels):
                row[f"{label}_return_{h}b"] = stats.percentiles[p]
            deltas = [
                o.forward_returns[h] - o.control_returns.get(h)
                for o in group
                if o.forward_returns[h] is not None and o.control_returns.get(h) is not None
            ]
            row[f"excess_median_{h}b"] = float(np.median(deltas)) if deltas else None
            row[f"n_excess_{h}b"] = len(deltas)
            row[f"n_resolved_{h}b"] = stats.n
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
            bars, _report = data_mod.load_and_validate(raw_conn, ticker, timeframe, basis=config.price_basis)
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
                "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?",
                (source_for(MODULE_PRICE_BASIS["patterns"]),)
            ).fetchall()
        ]
    else:
        tickers = args.tickers

    summary = run_backtest(raw_conn, tickers, timeframe, config, horizons)
    if summary.empty:
        print("No breakout outcomes found (no matches broke out across the given tickers).")
    else:
        pd.set_option("display.width", 220)
        # 12 columns per horizon (mean/median/winsorized/std/risk_adj/4
        # percentiles/excess_median/n_excess/n_resolved) plus 7 count/rate
        # columns -- the old cap of 20 truncated the default 3 horizons
        # even before the percentile/std columns were added.
        pd.set_option("display.max_columns", 100)
        print(summary.round(4).to_string())

    raw_conn.close()


if __name__ == "__main__":
    main()
