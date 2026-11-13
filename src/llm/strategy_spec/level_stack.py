"""The level-stack finder (step (b) of the strategy agent, `docs/backlog.md`): a support
stack, several kinds of price level close together below price, touched from above.

    result = find_level_stack(spec, panel)          # inputs loaded from the DB and the level cache
    result = find_level_stack(spec, panel, inputs)  # tests and repeat runs pass them in

**Prices.** Every level detector works on traded prices (split-adjusted only), the MA
panel on total-return prices. A stack found or drawn on the panel's OHLC would put each
level off by the dividends paid since, so detection and charts both use the traded bars
the levels come from (`TickerInputs.bars`, handed to grounding as `FinderResult.chart_bars`).
The panel sets the universe (a ticker's instances fall on its own panel dates) and the first
day levels are built for. Dates are the same on both bases, so the
exploratory look pairs an instance with the panel's lagged rows as for any finder.

**What is one instance** (each rule in the rubric, with its source):

- Levels: S/R lines (their zone), Fibonacci retracements, AVWAPs (the VWAP line, not its
  band) and bullish gaps (their unfilled part), each from its detector's defaults through
  the point-in-time levels (`models.features.levels`, the S/R and AVWAP snapshots from the
  level cache). A level counts on bar t as it stood at bar t-1's close, so a level formed
  by the touch bar itself can't be touched by it.
- A level is support when it sits wholly below the previous close, and in the stack when
  its age at the touch (bars since it formed) is within the spec's duration.
- The touch: bar t's low (or close, under a close basis) comes within the proximity of a
  level's top, and bar t-1's didn't (the first bar of a touch run). The stack on that level
  is every support level whose zone lies within the width (the spec's size) below its top;
  its kinds are counted once each (two S/R lines are one kind), plus one for a bullish
  divergence confirmed within the reach and not invalidated by bar t. Of the stacks on the
  touched levels, the one with the most kinds is the instance (then the highest top).
- The zone bottom is the lowest edge of the stack's levels; a touch bar closing below it
  doesn't fire (the before-entry invalidation).
- A match has at least `filters_needed` kinds; the control (`control=True`, the spec's
  "retests of a single level") has exactly one, with no divergence.

**Near-misses** relax one constraint ×1.5, as the other finders do: the width, the
proximity, each age bound, the divergence's reach, and the count (2 → 1, which is the
control: shown blind, it tests whether "stacked" matters to the trader's eye).
"""

from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Mapping

import numpy as np
import pandas as pd

from src.foundation.market_common.indicators import atr as atr_indicator
from src.llm.strategy_spec.finders import (
    RELAX_FACTOR, Candidate, FinderResult, GroundingError, RubricLine)
from src.llm.strategy_spec.schema import PROXIMITY_UNITS, StrategySpec, find_gaps
from src.models.features import level_cache, level_features, levels
from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.detect import detect_on_bars as detect_divergences
from src.signals.divergences.models import Direction as DivergenceDirection
from src.signals.fibonacci.config import FibConfig
from src.signals.gaps.detect import detect_on_bars as detect_gaps
from src.signals.gaps.models import Direction as GapDirection
from src.signals.gaps.relevance import gap_states

LEVEL_STACK = "level_stack"  # not a catalogue detector: a stack is built from several of them

# Catalogue id prefix -> the stack kind a filter built from it counts as.
KIND_OF = (("detector:sr_line.", "sr_line"), ("detector:fibonacci.retracement", "fib"),
           ("detector:avwap", "avwap"), ("detector:gap.", "gap"), ("detector:divergence.", "divergence"))
PRICE_KINDS = ("sr_line", "fib", "avwap", "gap")
KIND_NAMES = {"sr_line": "S/R line", "fib": "Fibonacci retracement", "avwap": "AVWAP",
              "gap": "bullish gap", "divergence": "bullish divergence"}
DIVERGENCE_NAMES = {"rsi": "RSI", "macd_hist": "MACD histogram", "obv": "OBV", "volume": "volume"}
# The S/R and AVWAP levels come from the level cache, built on these sources' defaults.
CACHED_SOURCES = ("sr_line", "avwap")

DIVERGENCE_REACH_BARS = 40  # the chart UI's reach for a daily divergence (done.md #181)
DEFAULT_WIDTH_ATR = 1.0
DEFAULT_PROXIMITY_ATR = 0.25
CHART_CONTEXT_BARS = 250  # at most this much history before the touch on a chart


@dataclass(frozen=True)
class TickerInputs:
    """One ticker's traded bars and what the finder reads off them. `levels`: one row per
    level per day it stands at that day's close (date, kind, lo, hi, formed, key: one
    level's identity across days, label: its name on a chart); `divergences`: bullish ones
    (confirmed, invalidated or NaT, indicator, form, p1_date, p1_price, p2_date, p2_price)."""

    bars: pd.DataFrame
    atr: pd.Series
    levels: pd.DataFrame
    divergences: pd.DataFrame


@dataclass(frozen=True)
class StackLine:
    """One level as drawn: its name and its value on each bar up to the touch."""

    label: str
    dates: tuple[pd.Timestamp, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class StackGeometry:
    """An instance's chart: the zone band from `start` to the touch, its levels, and the
    divergence as a line between its two price pivots."""

    start: pd.Timestamp
    zone: tuple[float, float]
    lines: tuple[StackLine, ...]
    divergence: tuple[pd.Timestamp, float, pd.Timestamp, float] | None = None
    kinds: tuple[str, ...] = ()
    divergence_label: str | None = None
    touch_price: str = "low"  # the bar price the touch was measured on, where the trigger marker sits


@dataclass(frozen=True)
class Params:
    width: float           # ATR: the stack's span below its top
    proximity: float       # ATR: how close the low must come to the top
    age_min: int           # bars
    age_max: int | None    # bars
    reach: int             # bars a divergence stays counted after it confirms
    count: int             # kinds needed
    exact: bool = False    # the control: exactly `count` (= 1) kinds


# ---------------------------------------------------------------- the spec


@dataclass(frozen=True)
class Plan:
    """What the spec asks for, read from its structured fields only."""

    kinds: dict[str, str]                  # stack kind -> the filter's name
    gap_kinds: tuple[str, ...]             # classic / fvg
    divergence_indicators: tuple[str, ...]
    params: Params
    touch_price: str  # the bar column the touch is measured on: "low" (intraday) or "close"
    rubric: tuple[RubricLine, ...]


def _kind(use: str) -> str | None:
    return next((kind for prefix, kind in KIND_OF if use.startswith(prefix)), None)


def is_level_stack(spec: StrategySpec) -> bool:
    """A spec whose filters are all levels or divergences this finder knows, at least one
    of them a price level: what `pick_finder` sends here."""
    filters = [s for s in spec.supporting_signals if s.role == "filter"]
    kinds = [{_kind(u) for u in s.uses} for s in filters]
    return bool(filters) and all(k and None not in k for k in kinds) and any(
        k & set(PRICE_KINDS) for k in kinds)


def plan(spec: StrategySpec) -> Plan:
    """The spec's stack, or a refusal saying why. A spec the gap check finds open is
    refused whole: the gap check is the one place a field's validity is decided, so this
    finder never re-derives (or contradicts) it."""
    gaps = find_gaps(spec)
    if gaps:
        open_ = "; ".join(f"{g.field}: {g.reason}" for g in gaps[:3])
        raise GroundingError(f"the spec isn't complete — finish elicitation first ({open_})")
    if not is_level_stack(spec):
        raise GroundingError("not a level stack: every filter must be an S/R line, Fibonacci retracement, "
                             "AVWAP, gap or divergence, and at least one a price level")
    if spec.timeframe != "daily":
        raise GroundingError("the levels are daily; grounding a weekly stack isn't built yet")
    if spec.direction != "long":
        raise GroundingError("only a support stack (long side) is built")

    rubric = [RubricLine("timeframe", "daily bars", "spec"),
              RubricLine("direction", "long: a support stack touched from above", "spec"),
              RubricLine("prices", "traded (split-adjusted) bars, detection and charts", "default",
                         "the levels' own basis; the MA panel's total-return prices would shift every level")]
    kinds: dict[str, str] = {}
    gap_kinds: list[str] = []
    indicators: list[str] = []
    for signal in spec.supporting_signals:
        if signal.role != "filter":
            rubric.append(RubricLine(f"confidence input: {signal.name}", "NOT APPLIED", "default",
                                     "only filters decide which instances exist"))
            continue
        found = {_kind(u) for u in signal.uses}
        if len(found) != 1:
            raise GroundingError(f"filter {signal.name!r} mixes kinds ({', '.join(sorted(found))}); "
                                 "a stack counts one kind per filter")
        kind = found.pop()
        if kind in kinds:
            raise GroundingError(f"filters {kinds[kind]!r} and {signal.name!r} are the same kind "
                                 f"({KIND_NAMES[kind]}); a stack counts each kind once")
        if signal.settings:
            # The S/R and AVWAP levels come from a cache built on the defaults; the others
            # could take settings, but one rule for all keeps the rubric honest.
            raise GroundingError(f"filter {signal.name!r} has its own settings; the finder runs every "
                                 "detector on its defaults — settings aren't built yet")
        kinds[kind] = signal.name
        if kind == "gap":
            gap_kinds = sorted(u.removeprefix("detector:gap.") for u in signal.uses)
        if kind == "divergence":
            indicators = sorted(u.removeprefix("detector:divergence.") for u in signal.uses)
        rubric.append(RubricLine(f"filter: {signal.name}", _kind_rule(kind, gap_kinds, indicators), "spec",
                                 "on the detector's defaults (you accepted them)"))

    count = spec.filters_needed or len(kinds)
    rubric.append(RubricLine("kinds needed", f"at least {count} of the {len(kinds)} filters, each kind counted "
                             "once, at least one a touched price level", "spec" if spec.filters_needed else "default"))

    size = spec.size
    if size is not None and not size.not_applicable and size.normalisation not in ("atr", None):
        raise GroundingError(f"the stack's width is measured in ATR; the spec's size is in {size.normalisation!r}")
    if size is not None and not size.not_applicable and size.max is not None:
        width = size.max
        rubric.append(RubricLine("stack width", f"the levels lie within {width:g} ATR(14) below the stack's top",
                                 "spec"))
    else:
        width = DEFAULT_WIDTH_ATR
        rubric.append(RubricLine("stack width", f"the levels lie within {width:g} ATR(14) below the stack's top",
                                 "default", "your spec doesn't cap the width"))
    if size is not None and size.min is not None:
        rubric.append(RubricLine("stack width floor", "NOT APPLIED", "default",
                                 f"your spec says at least {size.min:g}; a stack has no minimum width here"))

    p = spec.trigger.proximity if spec.trigger is not None else None
    if p is None or p.not_applicable:
        proximity = DEFAULT_PROXIMITY_ATR
        rubric.append(RubricLine("how close price must come", f"within {proximity:g} ATR(14) of the stack's top",
                                 "default", "your spec doesn't say"))
    elif p.through:
        proximity = 0.0
        rubric.append(RubricLine("how close price must come", "reaches the stack's top", "spec",
                                 "you said it must trade through the level"))
    elif p.normalisation != "atr":
        raise GroundingError(f"the touch is measured in ATR; the spec's proximity is in {PROXIMITY_UNITS[p.normalisation].strip()}")
    else:
        proximity = p.max
        rubric.append(RubricLine("how close price must come", f"within {proximity:g} ATR(14) of the stack's top",
                                 "spec"))
    touch_price = "close" if spec.trigger is not None and spec.trigger.price_basis == "close" else "low"
    rubric.append(RubricLine("touch", f"the touch bar's {touch_price} comes that close and "
                             "the bar before's didn't (the first bar of a touch run), with the previous close "
                             "above every level in the stack", "spec" if spec.trigger is not None else "default",
                             "price basis from your trigger; the first-bar rule is the finder's"))
    rubric.append(RubricLine("entry", "the next bar's open", "spec"))

    d = spec.duration
    if d is not None and not d.not_applicable:
        age_min, age_max = d.min_bars or 0, d.max_bars
        rubric.append(RubricLine("level age", f"every level in the stack formed {age_min}"
                                 f"{f'–{age_max}' if age_max else '+'} bars before the touch", "spec",
                                 "formed: an S/R line's first touch, an AVWAP's anchor, a gap's bar, a "
                                 "Fibonacci swing's start"))
    else:
        age_min, age_max = 0, None
        rubric.append(RubricLine("level age", "any", "default", "your spec has no duration"))
    rubric.append(RubricLine("levels known", "as they stood at the previous bar's close", "default",
                             "a level formed by the touch bar itself can't be touched by it"))
    if "divergence" in kinds:
        rubric.append(RubricLine("divergence reach", f"bullish, confirmed within the {DIVERGENCE_REACH_BARS} bars "
                                 "up to the touch and not invalidated by it", "default", "the chart UI's reach"))
    rubric.append(RubricLine("zone bottom", "the lowest edge of the stack's levels; a touch bar closing below "
                             "it doesn't fire", "default",
                             "your before-entry rule's text isn't read — this is the finder's own rule"))
    for rule in spec.invalidation:
        if rule.phase == "after_entry":
            rubric.append(RubricLine(f"invalidation (after entry): {rule.description}", "NOT APPLIED", "default",
                                     "an exit rule: the charts end on the touch, the look uses fixed horizons"))
    return Plan(kinds, tuple(gap_kinds), tuple(indicators),
                Params(width, proximity, age_min, age_max, DIVERGENCE_REACH_BARS, count),
                touch_price, tuple(rubric))


def _kind_rule(kind: str, gap_kinds, indicators) -> str:
    return {"sr_line": "an S/R line (medium-term preset), its zone",
            "fib": "a Fibonacci retracement level of an active top-6 swing",
            "avwap": "an AVWAP line (its value, not its band)",
            "gap": f"the unfilled part of a bullish gap ({' or '.join(gap_kinds)})",
            "divergence": f"a bullish divergence ({', '.join(indicators)}; regular or hidden)"}[kind]


# ---------------------------------------------------------------- the inputs


def ticker_inputs(ticker: str, bars: pd.DataFrame, splits: pd.DataFrame | None, start: pd.Timestamp,
                  root: Path | None, gap_kinds=("classic", "fvg"),
                  divergence_indicators=("rsi", "macd_hist", "obv")) -> TickerInputs:
    """`bars`: the ticker's whole traded history (as the level cache was built from, so
    its snapshots hit). Levels on every day from the day before `start`."""
    clean = levels.prepare(bars)
    configs = levels.default_configs()
    taken = levels.snapshot_dates(clean.index)
    first = max(int(clean.index.searchsorted(start)) - 1, 0)
    days = clean.index[first:]
    digest = level_cache.inputs_digest(ticker, clean, splits, taken)
    snaps = [level_cache.cached_snapshots(root, s, ticker, clean, splits, taken, configs[s],
                                          key=level_cache.fingerprint(s, ticker, clean, splits, taken, configs[s],
                                                                      digest))
             for s in CACHED_SOURCES]
    snaps = [s for s in snaps if len(s)]
    parts = []
    if snaps and len(taken):
        daily = levels.daily_levels(clean, splits, pd.concat(snaps, ignore_index=True), days, taken, configs)
        daily = daily[daily["source"].isin(CACHED_SOURCES)]
        mid = (daily["lo"] + daily["hi"]) / 2
        is_avwap = daily["source"] == "avwap"
        parts.append(pd.DataFrame({
            "date": daily["date"], "kind": daily["source"],
            "lo": np.where(is_avwap, mid, daily["lo"]), "hi": np.where(is_avwap, mid, daily["hi"]),
            "formed": daily["formed"],
            # One level's identity across days: an AVWAP's anchor; an S/R line's first touch (its
            # zone drifts a hair from one weekly snapshot to the next, so it can't be the key).
            "key": np.where(is_avwap, "avwap@", "sr@") + daily["formed"].astype(str),
            "label": np.where(is_avwap, "AVWAP from " + daily["formed"].dt.strftime("%Y-%m-%d"), "S/R line")}))
    fib = levels.fib_levels(clean, days, FibConfig())
    fib = fib[fib["kind"].str.startswith("retracement_")]
    ratio = fib["kind"].str.removeprefix("retracement_").astype(float)
    parts.append(pd.DataFrame({"date": fib["date"], "kind": "fib", "lo": fib["lo"], "hi": fib["hi"],
                               "formed": fib["formed"],
                               # Swings of two scales can share an origin and a ratio: the price tells them apart.
                               "key": "fib@" + fib["formed"].astype(str) + ":" + fib["kind"] + ":"
                                      + fib["lo"].round(6).astype(str),
                               "label": pd.Series([f"Fibonacci {r * 100:g}%" for r in ratio], index=fib.index,
                                                  dtype=object)}))
    gap_config = configs["gaps"]
    gaps, _ = detect_gaps(clean, ticker, levels.DAILY, gap_config)
    states = gap_states(clean, gaps, days, gap_config)
    if len(states):
        states = states[(states["direction"] == GapDirection.BULLISH.value) & states["kind"].isin(gap_kinds)]
        height = states["zone_top"] - states["zone_bottom"]
        parts.append(pd.DataFrame({
            "date": pd.to_datetime(states["date"]), "kind": "gap", "lo": states["zone_bottom"].astype(float),
            # A bullish gap fills from its top down: what's left is the bottom part.
            "hi": (states["zone_top"] - height * states["max_fill_pct"].astype(float) / 100).astype(float),
            "formed": pd.to_datetime(states["created_at"]), "key": "gap@" + states["gap_id"].astype(str),
            "label": np.where(states["kind"] == "fvg", "bullish FVG", "bullish gap")}))
    parts = [p.astype({"formed": "datetime64[ns]", "date": "datetime64[ns]"}) for p in parts if len(p)]
    out = (pd.concat(parts, ignore_index=True) if parts
           else pd.DataFrame(columns=["date", "kind", "lo", "hi", "formed", "key", "label"]))

    config = DivergenceConfig(indicators=list(divergence_indicators))
    found = detect_divergences(clean, ticker, levels.DAILY, config) if len(clean) >= config.min_bars else []
    bullish = [d for d in found if d.direction == DivergenceDirection.BULLISH]
    divergences = pd.DataFrame({
        "confirmed": pd.to_datetime([d.confirmed_at for d in bullish]),
        "invalidated": pd.to_datetime([d.invalidated_at for d in bullish]),
        "indicator": [d.indicator.value for d in bullish], "form": [d.form.value for d in bullish],
        "p1_date": pd.to_datetime([d.p1_date for d in bullish]), "p1_price": [d.p1_price for d in bullish],
        "p2_date": pd.to_datetime([d.p2_date for d in bullish]), "p2_price": [d.p2_price for d in bullish]})
    out = out.drop_duplicates(["date", "key", "lo", "hi"])  # one level reported twice is one level
    return TickerInputs(clean, atr_indicator(clean, 14), out.sort_values(["date", "kind"], ignore_index=True),
                        divergences)


def _inputs_job(args):
    ticker, bars, splits, start, root, gap_kinds, indicators = args
    try:
        return ticker, ticker_inputs(ticker, bars, splits, start, root, gap_kinds, indicators)
    except Exception as e:  # noqa: BLE001 -- one bad ticker is reported, not fatal
        return ticker, e


def load_inputs(tickers, start: pd.Timestamp, plan_: Plan, root: Path = level_features.DEFAULT_ROOT,
                workers: int = 4, progress=print) -> dict[str, TickerInputs]:
    """`ticker_inputs` for every ticker the level cache holds, from the DB's traded bars to
    the holdout boundary, read as the cache build read them (`level_cache.load_bars`), so
    its snapshots hit. Tickers not in the cache are left out (computing their snapshots
    takes about a minute each)."""
    import json

    from src.foundation.data_processing import db as raw_db
    from src.foundation.utils.config_loader import load_config
    from src.models import dataset

    manifest = json.loads((Path(root) / level_cache.MANIFEST).read_text())
    dataset.check_holdout(manifest["end"])
    cached = sorted(set(tickers) & set(manifest["tickers"]))
    conn = raw_db.get_connection(raw_db.default_db_path(load_config().data_paths.raw))
    try:
        _, by_ticker, splits = level_cache.load_bars(conn, cached, manifest["end"])
    finally:
        conn.close()
    jobs = [(t, bars, splits.get(t), start, root,
             plan_.gap_kinds or ("classic", "fvg"), plan_.divergence_indicators or ("rsi", "macd_hist", "obv"))
            for t, bars in by_ticker.items()]
    out, failed = {}, {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, (ticker, result) in enumerate(pool.map(_inputs_job, jobs, chunksize=4), 1):
            if isinstance(result, Exception):
                failed[ticker] = f"{type(result).__name__}: {result}"
            else:
                out[ticker] = result
            if progress and (i % 50 == 0 or i == len(jobs)):
                progress(f"  level inputs: {i}/{len(jobs)} tickers, {len(failed)} failed")
    if failed:
        progress(f"  {len(failed)} tickers failed: " + "; ".join(f"{t}: {e}" for t, e in list(failed.items())[:5]))
    return out


# ---------------------------------------------------------------- detection


@dataclass
class _Day:
    """Bar t's candidate levels (as of t-1's close), with what every run needs."""

    p: int
    kind: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    age: np.ndarray
    key: np.ndarray
    label: np.ndarray
    reach: np.ndarray       # how far the touch price stayed above each level's top, in ATR(t)
    prev_reach: np.ndarray  # the same for bar t-1, in ATR(t-1)
    divergence_age: np.ndarray  # bars since each live bullish divergence confirmed
    divergence_rows: np.ndarray


@dataclass
class _Stack:
    p: int
    kinds: tuple[str, ...]
    rows: np.ndarray        # indices into the day's arrays
    lo: float
    hi: float
    divergence: int | None  # row in TickerInputs.divergences


def _prepare_days(inputs: TickerInputs, dates, kinds: set[str], touch_price: str, loosest: Params) -> list[_Day]:
    """Every bar on one of `dates` (the ticker's panel rows: the point-in-time universe,
    as the other finders fire only on panel rows) where some support level could be
    touched under the loosest params any run uses, its levels' numbers precomputed once."""
    bars, atr = inputs.bars, inputs.atr.to_numpy(dtype=float)
    index = bars.index
    low = bars[touch_price].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    lv = inputs.levels[inputs.levels["kind"].isin(kinds - {"divergence"})]
    by_date = {d: g for d, g in lv.groupby("date", sort=False)}
    div = inputs.divergences
    div_confirmed = index.searchsorted(div["confirmed"]) if len(div) else np.array([], dtype=int)
    div_invalidated = (np.where(div["invalidated"].isna(), len(index), index.searchsorted(div["invalidated"]))
                       if len(div) else np.array([], dtype=int))
    positions = index.get_indexer(pd.DatetimeIndex(dates))
    days = []
    for p in np.unique(positions[positions >= 1]):  # a panel date with no traded bar can't host a touch
        g = by_date.get(index[p - 1])
        if g is None or not (atr[p] > 0) or not (atr[p - 1] > 0):
            continue
        hi = g["hi"].to_numpy(dtype=float)
        support = hi < close[p - 1]
        if not support.any():
            continue
        reach = (low[p] - hi) / atr[p]
        if not (support & (reach <= loosest.proximity)).any():
            continue
        g = g[support]
        formed = index.searchsorted(g["formed"].to_numpy())
        live = (div_confirmed <= p) & (div_invalidated > p) & (div_confirmed >= p - loosest.reach)
        days.append(_Day(p, g["kind"].to_numpy(), g["lo"].to_numpy(dtype=float), hi[support], p - formed,
                         g["key"].to_numpy(), g["label"].to_numpy(), reach[support], ((low[p - 1] - hi) / atr[p - 1])[support],
                         p - div_confirmed[live], np.flatnonzero(live)))
    return days


def _stack_on(day: _Day, close: float, atr: float, params: Params, use_divergence: bool) -> _Stack | None:
    """The instance on one bar under `params`, or None."""
    aged = (day.age >= params.age_min) & ((day.age <= params.age_max) if params.age_max is not None else True)
    touched = aged & (day.reach <= params.proximity) & (day.prev_reach > params.proximity)
    divergence = None
    if use_divergence:
        recent = np.flatnonzero(day.divergence_age <= params.reach)
        if len(recent):
            divergence = int(day.divergence_rows[recent[np.argmin(day.divergence_age[recent])]])
    best = None
    for j in np.flatnonzero(touched):
        top = day.hi[j]
        rows = np.flatnonzero(aged & (day.hi <= top) & (day.lo >= top - params.width * atr))
        if j not in rows:
            continue  # a level deeper than the width can't fit in a stack of that width
        bottom = float(day.lo[rows].min())
        if close < bottom:
            continue  # the before-entry invalidation: the touch bar closes below the zone
        kinds = tuple(sorted(set(day.kind[rows])))
        score = (len(kinds), top)
        if best is None or score > best[0]:
            best = (score, _Stack(day.p, kinds, rows, bottom, float(top), divergence))
    if best is None:
        return None
    stack = best[1]
    total = len(stack.kinds) + (stack.divergence is not None)
    if params.exact:
        return stack if total == params.count and stack.divergence is None else None
    return stack if total >= params.count else None


def _run(days_by_ticker: dict[str, list[_Day]], inputs: Mapping[str, TickerInputs], params: Params,
         use_divergence: bool) -> dict[str, dict[int, _Stack]]:
    out = {}
    for ticker, days in days_by_ticker.items():
        close, atr = inputs[ticker].bars["close"].to_numpy(dtype=float), inputs[ticker].atr.to_numpy(dtype=float)
        found = {d.p: s for d in days if (s := _stack_on(d, close[d.p], atr[d.p], params, use_divergence))}
        if found:
            out[ticker] = found
    return out


def _geometry(inputs: TickerInputs, rows_of: Mapping[str, np.ndarray], day: _Day, stack: _Stack,
              touch_price: str) -> StackGeometry:
    """`rows_of`: each level key's rows in `inputs.levels` (date-sorted), indexed once per ticker."""
    index = inputs.bars.index
    start_p = max(stack.p - CHART_CONTEXT_BARS, int(min(stack.p - day.age[stack.rows])), 0)
    start = index[start_p]
    level_dates = inputs.levels["date"].to_numpy()
    level_tops = inputs.levels["hi"].to_numpy(dtype=float)
    lines = []
    for r in stack.rows:
        rows = rows_of[day.key[r]]
        # Each level's value on every bar it stood on, as known at the previous close.
        d = level_dates[rows]
        keep = rows[(d >= index[max(start_p - 1, 0)].to_datetime64()) & (d < index[stack.p].to_datetime64())]
        dates = tuple(index[index.searchsorted(level_dates[keep]) + 1])
        values = tuple(float(v) for v in level_tops[keep])  # the level's top: the edge a touch from above meets
        lines.append(StackLine(f"{day.label[r]} ({day.lo[r]:.2f}–{day.hi[r]:.2f})"
                               if day.lo[r] != day.hi[r] else f"{day.label[r]} {day.hi[r]:.2f}", dates, values))
    div, div_label = None, None
    if stack.divergence is not None:
        row = inputs.divergences.iloc[stack.divergence]
        div = (pd.Timestamp(row["p1_date"]), float(row["p1_price"]), pd.Timestamp(row["p2_date"]),
               float(row["p2_price"]))
        div_label = f"bullish {row['form']} divergence ({DIVERGENCE_NAMES.get(row['indicator'], row['indicator'])})"
    kinds = stack.kinds + (("divergence",) if stack.divergence is not None else ())
    return StackGeometry(start, (stack.lo, stack.hi), tuple(lines), div, kinds, div_label, touch_price)


def find_level_stack(spec: StrategySpec, panel: pd.DataFrame, inputs: Mapping[str, TickerInputs] | None = None,
                     near_misses: bool = True, control: bool = False, progress=print) -> FinderResult:
    """Instances of the spec's support stack over `panel`'s tickers and window (see the
    module docstring). `control=True` finds the spec's control instead: touches of exactly
    one kind (no near-misses for it). `inputs` left None are loaded (`load_inputs`, a few
    minutes over a process pool)."""
    p = plan(spec)
    for needed in ("ticker", "date"):
        if needed not in panel.columns:
            raise GroundingError(f"panel has no {needed!r} column — not a feature panel?")
    window = (pd.Timestamp(panel["date"].min()), pd.Timestamp(panel["date"].max()))
    tickers = sorted(panel["ticker"].unique())
    if inputs is None:
        inputs = load_inputs(tickers, window[0], p, progress=progress)
    cached = [t for t in tickers if t in inputs]
    panel_dates = panel.groupby("ticker", sort=False)["date"].unique()
    # A ticker none of whose panel dates is a bar that can host a touch (not its first) yields
    # nothing; all of them so means the panel and the bars disagree on what a date is.
    unmatched = [t for t in cached
                 if not pd.DatetimeIndex(panel_dates[t]).isin(inputs[t].bars.index[1:]).any()]
    if cached and len(unmatched) == len(cached):
        raise GroundingError("no ticker's panel dates are its traded bars' dates — a time zone or "
                             "time-of-day mismatch between the panel and the DB bars?")
    # A key names one level across days (charts draw a line per key); no two levels share
    # one on a day in the cache (5.7M S/R and AVWAP rows checked). A ticker whose inputs
    # ever break that is left out and named, rather than drawn with two levels as one line.
    shared_keys = [t for t in cached if t not in unmatched and inputs[t].levels.duplicated(["date", "key"]).any()]
    used = [t for t in cached if t not in unmatched and t not in shared_keys]
    rubric = [*p.rubric, RubricLine("universe", f"{len(used)} of the panel's {len(tickers)} tickers", "default",
                                    "the tickers the level cache holds"
                                    + (", with bars on their panel dates" if unmatched else ""))]
    if unmatched:
        rubric.append(RubricLine("left out: no bars on their panel dates", ", ".join(unmatched), "default"))
    if shared_keys:
        rubric.append(RubricLine("left out: two levels share a key on one day", ", ".join(shared_keys), "default",
                                 "their lines can't be told apart on a chart"))
    params = replace(p.params, count=1, exact=True) if control else p.params
    if control:
        rubric.append(RubricLine("control", "touches of exactly one kind, no divergence", "spec",
                                 "your control: retests of a single level, not stacked"))
    relaxed = {
        "width": replace(params, width=params.width * RELAX_FACTOR),
        "proximity": replace(params, proximity=params.proximity * RELAX_FACTOR),
        "age_min": replace(params, age_min=math.floor(params.age_min / RELAX_FACTOR)),
        "age_max": replace(params, age_max=math.ceil(params.age_max * RELAX_FACTOR) if params.age_max else None),
        "reach": replace(params, reach=math.ceil(params.reach * RELAX_FACTOR)),
        "count": replace(params, count=max(1, math.floor(params.count / RELAX_FACTOR))),
    }
    loosest = replace(params, proximity=relaxed["proximity"].proximity, reach=relaxed["reach"].reach)
    use_divergence = "divergence" in p.kinds
    days = {t: _prepare_days(inputs[t], panel_dates[t], set(p.kinds), p.touch_price, loosest) for t in used}
    day_at = {t: {d.p: d for d in ds} for t, ds in days.items()}
    rows_of: dict[str, Mapping[str, np.ndarray]] = {}  # per ticker, built on its first instance

    def candidates(found: dict[str, dict[int, _Stack]], fails: str | None = None) -> list[Candidate]:
        out = []
        for ticker, by_p in found.items():
            if ticker not in rows_of:
                rows_of[ticker] = inputs[ticker].levels.groupby("key", sort=False).indices
            for pos, stack in by_p.items():
                out.append(Candidate(ticker, pd.Timestamp(inputs[ticker].bars.index[pos]), fails,
                                     stack=_geometry(inputs[ticker], rows_of[ticker], day_at[ticker][pos], stack,
                                                     p.touch_price)))
        return sorted(out, key=lambda c: (c.ticker, c.date))

    strict = _run(days, inputs, params, use_divergence)
    matches = tuple(candidates(strict))
    near: list[Candidate] = []
    if near_misses and not control:
        def minus_strict(ring):
            return {t: kept for t, by_p in ring.items() if (kept := {q: s for q, s in by_p.items()
                                                                       if q not in strict.get(t, {})})}
        labels = {
            "width": f"stack width: the levels span up to {relaxed['width'].width:g} ATR, not {params.width:g}",
            "proximity": f"how close: the {p.touch_price} comes within "
                         f"{relaxed['proximity'].proximity:g} ATR of the top, "
                         f"not {params.proximity:g}",
            "age_min": f"level age: a level is {relaxed['age_min'].age_min}–{params.age_min - 1} bars old, "
                       f"under your {params.age_min}",
            "age_max": f"level age: a level is {params.age_max and params.age_max + 1}–{relaxed['age_max'].age_max} "
                       f"bars old, over your {params.age_max}",
            "reach": f"divergence: confirmed {params.reach + 1}–{relaxed['reach'].reach} bars before the touch, "
                     f"not within {params.reach}",
            "count": f"kinds: only {relaxed['count'].count} kind, not {params.count}",
        }
        skip = {"age_min": params.age_min == 0, "age_max": params.age_max is None, "reach": not use_divergence,
                "count": relaxed["count"].count >= params.count}
        seen: set[tuple[str, pd.Timestamp]] = set()
        for name, ring_params in relaxed.items():
            if skip.get(name):
                continue
            ring = minus_strict(_run(days, inputs, ring_params, use_divergence))
            if name == "proximity":
                # A looser touch can fire a bar early on an approach that fires strictly a
                # bar or two later: that bar says nothing about the threshold.
                ring = {t: kept for t, by_p in ring.items()
                        if (kept := {q: s for q, s in by_p.items()
                                     if not any(q < r <= q + 10 for r in strict.get(t, {}))})}
            for c in candidates(ring, labels[name]):
                if (c.ticker, c.date) not in seen:
                    seen.add((c.ticker, c.date))
                    near.append(c)
    charted = {c.ticker for c in matches} | {c.ticker for c in near}  # only these can be charted
    return FinderResult(matches, tuple(near), tuple(rubric), overlay_column=None, overlay_name="level stack",
                        chart_bars={t: inputs[t].bars.rename_axis("date").reset_index() for t in sorted(charted)})
