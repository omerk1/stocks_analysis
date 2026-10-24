"""Step 4 of the strategy agent (`docs/strategy-agent/idea.md`, workflow step 2): the
instance finders — deterministic code that turns a complete spec into concrete historical
instances, so the trader can confirm "this is what you meant" on real charts before
anything is formalised or tested. No LLM is involved anywhere in this step: code finds
the instances, a human judges them.

A finder consumes **structured spec fields only — never a description**. That is the
backstop for the known weakness of the elicitation step (step 3): a spec can pass the gap
check while its real numbers hide in prose (even the hand-written golden first-touch spec
keeps its 0.25-ATR touch tolerance in `size.description`, because `Size.min`/`max` bound
one quantity). Every parameter a finder uses is therefore reported as a `RubricLine`
saying where the value came from — the spec, a default, or a run option — and the rubric
is shown to the trader next to the charts. A number hiding in prose now fails visibly:
either the rubric openly says a default was used where the trader stated a value, or the
charts show instances that violate what they said and get rejected.

Besides matches, a finder returns **near-misses**: instances that qualify when exactly
one constraint is relaxed by `RELAX_FACTOR` and fail under the spec as stated. They test
whether the thresholds sit where the trader means them, which approvals of clean matches
never probe — a trader who accepts a near-miss is saying a number in the spec is wrong,
the single most informative answer grounding can produce. The construction — run the same
detection once per single-relaxed parameter, subtract the strict set — guarantees exactly
this much: the instance qualifies under the spec with that one parameter relaxed, and not
under the spec as stated. Each `fails` label claims only what that guarantees. The
touch-window label can say precisely what the bar did (a run's first touch is unique, so
widening the window changes nothing else). A relaxed touch tolerance can pull a run's
first touch onto an earlier bar while the same run still fires strictly a few bars later
— that bar says nothing about the tolerance, so the touch ring drops anything with a
strict event close behind it. Relaxing the away distance moves the away-run boundaries
themselves, so interactions are possible and its label says "qualifies only when ... is
relaxed", no more. One instance can in principle appear in two rings; near-misses are
deduplicated on (ticker, date), first ring kept.

One finder per catalogue detector id, registered in `FINDERS`; this first slice covers
`detector:ma.first_touch` (the golden spec, and what the first live elicitation session
converged on). It runs on the cached MA feature panel (`features/panel.py`), whose
`dist_atr_*` columns are one-bar-lagged by the study's central convention. Grounding
shifts them back one bar (`groupby(ticker).shift(-1)`) so an instance's date is the
**signal bar itself** — the close the trader must judge on a chart. That is a display
alignment, not a bypass of the one-bar-lag invariant: grounding computes no forward
outcome and pairs no label, and the charts end on the trigger bar itself (`charts.py`)
precisely so no outcome information exists to leak.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, replace
from typing import Callable, Literal

import numpy as np
import pandas as pd

from src.llm.strategy_spec.schema import StrategySpec
from src.signals.base_breakout import detect as base_breakout
from src.signals.moving_averages.features import ma as ma_features
from src.signals.moving_averages.features import panel as panel_features
from src.signals.moving_averages.features import touch

RELAX_FACTOR = 1.5

# The MA columns the cached panel carries (family_lookback), from the panel's own grid
# so a grid change can't leave this list stale. The spec has no structured slot for the
# MA length — it lives in prose — so which MA to ground against is a run option,
# disclosed in the rubric.
MA_COLUMNS = tuple(f"{family}_{k}" for family in ma_features.FAMILIES for k in ma_features.LOOKBACKS)
DEFAULT_MA = "sma_200"

Source = Literal["spec", "default", "run option"]


class GroundingError(ValueError):
    """The spec (or run options) can't be grounded as stated — says why, so the trader
    can fix the spec rather than get silently-approximated instances."""


@dataclass(frozen=True)
class RubricLine:
    """One parameter the finder actually applied, and where its value came from. The
    rubric, not the spec text, is what the trader's approvals attach to."""

    parameter: str
    value: str
    source: Source
    detail: str | None = None


@dataclass(frozen=True)
class Candidate:
    """One instance: the bar the signal fired on. `fails` is None for a match, else the
    single spec constraint this near-miss fails, in words the trader can act on.

    `overlay_span` is this instance's own chart geometry: (first bar, last bar, value) —
    a constant line the chart draws across exactly that span, widening the chart window
    to show all of it. A shared overlay column can't carry it when episodes on one
    ticker overlap (later paints overwrite earlier ones, so a chart could show another
    episode's level — including one only knowable after the trigger bar). None (the MA
    finder, whose overlay is a property of the ticker, not the instance) keeps the
    shared panel-column overlay and the default window."""

    ticker: str
    date: pd.Timestamp
    fails: str | None = None
    overlay_span: tuple[pd.Timestamp, pd.Timestamp, float] | None = None


@dataclass(frozen=True)
class FinderResult:
    matches: tuple[Candidate, ...]
    near_misses: tuple[Candidate, ...]
    rubric: tuple[RubricLine, ...]
    # The finder owns its chart geometry: the panel column (one-bar-lagged, like every
    # panel feature — `ground.py` shifts it to the signal bar for display) drawn as the
    # chart overlay, and its display name. The session runner draws what the finder
    # declares; it doesn't assume every detector is about a moving average.
    overlay_column: str
    overlay_name: str


def shift_to_signal_bar(panel: pd.DataFrame, column: str) -> pd.Series:
    """The panel's one-bar-lagged `column` shifted back onto its own bar, for grounding
    display and detection ONLY (see module docstring: instance dates must be the signal
    bar the trader judges, and grounding computes no outcome). **Never pair the result
    with a forward return or label** — that reintroduces same-bar execution, the exact
    silent failure the repo's central one-bar lag (`features/panel.py::apply_lag`,
    CLAUDE.md invariant #2) exists to prevent."""
    return panel.groupby("ticker", sort=False)[column].shift(-1)


def find_first_touch(spec: StrategySpec, panel: pd.DataFrame, ma: str = DEFAULT_MA,
                     near_misses: bool = True) -> FinderResult:
    """Instances of "first touch of a moving average after being away" in `panel`
    (a `features/panel.py` panel, sorted by ticker and date).

    Structured-field mapping: `size.min` under ATR normalisation is the away distance
    (that's what the golden spec quantifies); everything else — touch tolerance, the
    window for the touch, the MA itself — has no structured slot today and falls back
    to the study's defaults, each disclosed in the rubric.

    `near_misses=False` skips the three relaxed ring passes (most of the detection
    cost) for callers that only consume matches, like the exploratory look. Matches,
    the rubric and the refusals — the degeneracy guard included, so grounding and the
    look refuse the same specs — are identical either way.
    """
    if ma not in MA_COLUMNS:
        raise GroundingError(f"unknown moving average {ma!r}; one of {', '.join(MA_COLUMNS)}")
    dist_col = f"dist_atr_{ma}"
    for needed in (dist_col, ma):  # the distance drives detection, the MA itself the chart overlay
        if needed not in panel.columns:
            raise GroundingError(f"panel has no {needed!r} column — not a feature panel?")

    if spec.timeframe is None:
        raise GroundingError("the spec doesn't state a timeframe — finish elicitation before "
                             "grounding (the panel here is daily; a weekly idea must not be "
                             "silently grounded as a daily one)")
    if spec.timeframe == "weekly":
        raise GroundingError("the feature panel is daily; grounding a weekly idea isn't built yet")
    size = spec.size
    if size is not None and size.normalisation not in (None, "atr"):
        raise GroundingError(
            f"this finder measures distance from the MA in ATR; the spec's size is in "
            f"{size.normalisation!r} — restate the size in ATR or ground by hand")
    if size is not None and size.normalisation is None and (size.min is not None or size.max is not None):
        raise GroundingError(
            "the spec's size has numbers but no units (normalisation is unset) — "
            "finish elicitation before grounding")
    if spec.trigger is not None and spec.trigger.price_basis == "intraday":
        raise GroundingError("the feature panel is close-based; an intraday trigger can't be grounded here")

    rubric: list[RubricLine] = []
    rubric.append(RubricLine("timeframe", "daily bars", "spec"))
    if spec.trigger is not None and spec.trigger.price_basis == "close":
        rubric.append(RubricLine("price basis", "close", "spec"))
    else:  # None (intraday was refused above): applied as a default, so say so
        rubric.append(RubricLine("price basis", "close", "default",
                                 "your spec didn't state one — detection and charts use closes"))
    rubric.append(RubricLine("search window", "ends one bar before each ticker's last panel row",
                             "default", "the cached panel carries a bar's state on the next row, "
                             "so the final bar's own signal is undefined"))
    family, _, lookback = ma.partition("_")
    rubric.append(RubricLine("moving average", f"{family.upper()} {lookback}", "run option",
                             "the spec has no structured slot for the MA; pick with --ma"))

    if size is not None and size.normalisation == "atr" and size.min is not None:
        away = size.min
        rubric.append(RubricLine("away distance", f">= {away:g} ATR from the MA", "spec"))
    else:
        away = touch.AWAY_THRESHOLD
        rubric.append(RubricLine("away distance", f">= {away:g} ATR from the MA", "default",
                                 "your spec didn't state this as a number"))
    if size is not None and size.max is not None:
        # A stated structured bound the detector can't apply is disclosed, never dropped.
        rubric.append(RubricLine("away distance upper bound", "NOT APPLIED", "default",
                                 f"your spec caps the size at {size.max:g}, but the detector "
                                 "has no away-distance cap — instances may exceed it"))
    touch_tol = touch.TOUCH_THRESHOLD
    if away <= touch_tol * RELAX_FACTOR:
        # Headroom is needed for the near-miss rings too: the away ring runs at
        # away/RELAX_FACTOR and the touch ring at touch_tol*RELAX_FACTOR, and whenever
        # an away threshold doesn't exceed the touch threshold in play, the first bar
        # after every away run already counts as a touch and detection degenerates —
        # the near-miss pool floods with bogus instances.
        raise GroundingError(
            f"the away distance ({away:g} ATR) must exceed {touch_tol * RELAX_FACTOR:g} ATR — "
            f"the touch tolerance ({touch_tol:g}) times the near-miss relaxation ({RELAX_FACTOR:g}) — "
            "or detection degenerates in the spec or in a near-miss ring; restate the size")
    rubric.append(RubricLine("touch tolerance", f"within {touch_tol:g} ATR of the MA", "default",
                             "no structured slot yet — if your idea states one, check the charts against it"))
    max_days = touch.MAX_DAYS_TO_TOUCH
    rubric.append(RubricLine("touch window", f"within {max_days} bars of the away run ending", "default",
                             "no structured slot yet"))

    # From above = price falls to the MA (a support test, the long side); from below =
    # rises to it (resistance, the short side). touch_positions reports the sign of the
    # distance at the end of the away run: +1 is from above.
    signs = {"long": (1.0,), "short": (-1.0,), "both": (1.0, -1.0), None: (1.0, -1.0)}[spec.direction]
    sides = {1.0: "from above (support test)", -1.0: "from below (resistance test)"}
    shown_sides = " and ".join(sides[s] for s in signs)
    if spec.direction is not None:
        rubric.append(RubricLine("direction", shown_sides, "spec"))
    else:
        # Grounding both sides is itself an applied choice — a long-only trader must
        # see it, or their from-below rejections get misread as a trigger problem.
        rubric.append(RubricLine("direction", shown_sides, "default",
                                 "your spec didn't state a direction — both sides are shown"))

    for signal in spec.supporting_signals:
        if signal.role == "filter":
            rubric.append(RubricLine(f"filter: {signal.name}", "NOT APPLIED", "default",
                                     "no structured mapping yet — instances ignore this filter"))
    for rule in spec.invalidation:
        # An after-entry rule is about the trade, not the setup; a before-entry rule
        # excludes setups, so not acting on it must be said out loud or rejections get
        # misattributed to the trigger definition. "NOT READ", not "not applied": the
        # finder can't know whether the rule's prose restates a parameter above (the
        # golden spec's does — its rule is the touch window) or adds a real exclusion.
        if rule.phase == "before_entry":
            rubric.append(RubricLine(f"invalidation (before entry): {rule.description}",
                                     "NOT READ", "default",
                                     "rule text isn't read — if it restates a parameter above "
                                     "it is already applied; anything else is ignored"))

    working = panel[["ticker", "date"]].copy()
    working["dist"] = shift_to_signal_bar(panel, dist_col)
    # One grouping pass for all four detection runs (strict + three rings): the per-ticker
    # trimmed series and dates don't change between runs, only the thresholds do. The
    # unlag shift leaves each ticker's last row NaN (and warmup NaNs stay leading, which
    # `state_run_id` supports); the tail is trimmed — a bar with no distance can't host
    # an event, and positions into the kept rows don't move.
    dates_by_ticker: dict[str, pd.api.extensions.ExtensionArray] = {}
    dist_by_ticker: dict[str, pd.Series] = {}
    for ticker, frame in working.groupby("ticker", sort=False):
        if not frame["date"].is_monotonic_increasing:
            # The unlag shift and the run detection both assume chronological rows per
            # ticker; an unsorted panel would yield confidently wrong instances.
            raise GroundingError(f"panel rows for {ticker!r} aren't date-sorted — "
                                 "pass a (ticker, date)-sorted feature panel")
        dates_by_ticker[ticker] = frame["date"].to_numpy()
        dist = frame["dist"].reset_index(drop=True)
        last_valid = dist.last_valid_index()
        if last_valid is not None:
            dist_by_ticker[ticker] = dist.iloc[:last_valid + 1]

    def events(away_threshold: float, touch_threshold: float, max_days_to_touch: int) -> dict[str, set[int]]:
        """Qualifying bar positions per ticker (positions, not dates, so rings can
        reason about how far apart two events on one ticker are)."""
        found: dict[str, set[int]] = {}
        for ticker, dist in dist_by_ticker.items():
            positions, direction = touch.touch_positions(
                dist, away_threshold, touch_threshold, max_days_to_touch)
            kept = {int(p) for p, s in zip(positions, direction) if s in signs}
            if kept:
                found[ticker] = kept
        return found

    strict = events(away, touch_tol, max_days)

    def dated(by_ticker: dict[str, set[int]]) -> list[tuple[str, pd.Timestamp]]:
        return sorted((t, pd.Timestamp(dates_by_ticker[t][p])) for t, ps in by_ticker.items() for p in ps)

    matches = tuple(Candidate(t, d) for t, d in dated(strict))
    if not near_misses:
        return FinderResult(matches, (), tuple(rubric),
                            overlay_column=ma, overlay_name=f"{family.upper()} {lookback}")

    def minus_strict(ring: dict[str, set[int]]) -> dict[str, set[int]]:
        return {t: kept for t, ps in ring.items() if (kept := ps - strict.get(t, set()))}

    touch_ring = minus_strict(events(away, touch_tol * RELAX_FACTOR, max_days))
    # A relaxed tolerance can pull a run's first touch onto an earlier bar while the
    # same run still fires strictly a few bars later — that bar is not evidence the
    # tolerance is misplaced, so anything with a strict event close behind it (within
    # the touch window, which bounds how far apart two touches of one run can be) is
    # dropped rather than shown as a near-miss. Keyed on the ticker, not the run (run
    # ids don't leave `touch_positions`), so a strict event from a neighbouring run
    # also suppresses — deliberately conservative: it occasionally hides a genuine
    # near-miss, it never presents a mislabelled one.
    touch_ring = {t: kept for t, ps in touch_ring.items()
                  if (kept := {p for p in ps
                               if not any(p < s <= p + max_days for s in strict.get(t, ()))})}
    away_ring = minus_strict(events(away / RELAX_FACTOR, touch_tol, max_days))
    relaxed_days = math.ceil(max_days * RELAX_FACTOR)  # ceil: never a sub-×1.5 ring mislabelled as the standard one
    days_ring = minus_strict(events(away, touch_tol, relaxed_days))

    rings = [
        (touch_ring,
         f"touch tolerance: comes within {touch_tol * RELAX_FACTOR:g} ATR of the MA, not within {touch_tol:g}"),
        (away_ring,
         f"away distance: qualifies only when 'away' is relaxed to >= {away / RELAX_FACTOR:g} ATR "
         f"(your spec: >= {away:g})"),
        (days_ring,
         f"touch window: touches {max_days + 1}-{relaxed_days} bars after the away run ends, not within {max_days}"),
    ]

    seen: dict[tuple[str, pd.Timestamp], str] = {}
    for ring, fails in rings:
        for key in dated(ring):
            seen.setdefault(key, fails)
    near_misses = tuple(Candidate(t, d, fails) for (t, d), fails in seen.items())
    return FinderResult(matches, near_misses, tuple(rubric),
                        overlay_column=ma, overlay_name=f"{family.upper()} {lookback}")


BASE_BREAKOUT_OVERLAY = "base_breakout_level"


def same_bar_atr(frame: pd.DataFrame) -> pd.Series:
    """Bar t's own ATR(14) for one ticker's date-sorted panel rows, from the panel's
    one-bar-lagged `atr_14` (row t holds ATR(t-1), built on the full loaded history) and
    bar t's true range, by Wilder's one-step update: ATR(t) = ((n-1)·ATR(t-1) + TR(t)) / n.
    Every row gets its value — the last included — with no warmup restarting where the
    panel was cut. Matches the panel's next-row value to float32 precision. A ticker's
    first panel row has no previous close for the true range, so it takes the next row's
    stored value instead (that is ATR(t) itself)."""
    n = panel_features.ATR_PERIOD
    stored = frame["atr_14"].astype("float64")
    previous_close = frame["close"].shift(1)
    true_range = pd.concat([frame["high"] - frame["low"],
                            (frame["high"] - previous_close).abs(),
                            (frame["low"] - previous_close).abs()], axis=1).max(axis=1, skipna=False)
    rolled = (stored * (n - 1) + true_range) / n
    rolled.iloc[:1] = stored.shift(-1).iloc[:1]
    return rolled


def find_base_breakout_retest(spec: StrategySpec, panel: pd.DataFrame,
                              near_misses: bool = True) -> FinderResult:
    """Instances of "breakout above the high of a long flat base, then a holding retest
    of that level" in `panel` (a `features/panel.py` panel, sorted by ticker and date).
    Long side only — a breakdown-and-retest mirror isn't built.

    Structured-field mapping: `duration.min_bars`/`max_bars` bound the base length and
    `size.min`/`max` under pct normalisation bound the base depth below its high (that's
    what this spec quantifies); the retest tolerance, retest window, the kill threshold
    behind "decisively below", the level-search lookback, and the three constraints the
    2026-10-19 grounding round added (level touch count, breakout decisiveness margin,
    minimum rally before the retest) have no structured slot and fall back to defaults,
    each disclosed in the rubric.

    Detection runs on the panel's **unlagged** OHLC columns, so an instance's date is the
    retest (signal) bar itself. Every ATR threshold on bar u uses bar u's own ATR
    (`same_bar_atr`): the panel's `atr_14` is stored one-bar-lagged, so it's rolled one
    Wilder step forward with bar u's true range rather than shifted back (which would
    leave each ticker's last bar without an ATR) or recomputed from the panel slice
    (whose warmup would restart wherever the panel was cut). The
    chart overlay (the breakout level) travels on each candidate as its `overlay_span`
    — episodes on one ticker can overlap, so a shared column can't be trusted per chart.
    The finder still **adds the column to `panel` in place** as `base_breakout_level`
    (one-bar-lagged like every panel feature) to satisfy the FinderResult contract the
    session runner reads, but the presented charts draw each candidate's own span.

    `near_misses=False` skips the ten relaxed ring passes (most of the detection
    cost); matches, rubric and refusals are identical either way.
    """
    for needed in ("ticker", "date", "high", "low", "close", "atr_14"):
        if needed not in panel.columns:
            raise GroundingError(f"panel has no {needed!r} column — not a feature panel?")
    if spec.timeframe is None:
        raise GroundingError("the spec doesn't state a timeframe — finish elicitation before "
                             "grounding (the panel here is daily; a weekly idea must not be "
                             "silently grounded as a daily one)")
    if spec.timeframe == "weekly":
        raise GroundingError("the feature panel is daily; grounding a weekly idea isn't built yet")
    if spec.direction in ("short", "both"):
        raise GroundingError("the base-breakout detector covers the long side only — a "
                             "breakdown-and-retest mirror isn't built yet")
    size = spec.size
    if size is not None and size.normalisation not in (None, "pct"):
        raise GroundingError(
            f"this finder measures base depth in percent of the base high; the spec's size "
            f"is in {size.normalisation!r} — restate the size in percent or ground by hand")
    if size is not None and size.normalisation is None and (size.min is not None or size.max is not None):
        raise GroundingError(
            "the spec's size has numbers but no units (normalisation is unset) — "
            "finish elicitation before grounding")
    if spec.trigger is not None and spec.trigger.price_basis == "intraday":
        raise GroundingError("the feature panel is close-based; an intraday trigger can't be grounded here")

    rubric: list[RubricLine] = []
    rubric.append(RubricLine("timeframe", "daily bars", "spec"))
    if spec.trigger is not None and spec.trigger.price_basis == "close":
        rubric.append(RubricLine("price basis", "close", "spec"))
    else:
        rubric.append(RubricLine("price basis", "close", "default",
                                 "your spec didn't state one — detection and charts use closes"))
    if spec.direction == "long":
        rubric.append(RubricLine("direction", "long (breakout up, retest from above)", "spec"))
    else:  # None (short/both were refused above): grounding long is itself an applied choice
        rubric.append(RubricLine("direction", "long (breakout up, retest from above)", "default",
                                 "your spec didn't state a direction — only the long side is built"))

    duration = spec.duration
    stated_duration = duration is not None and not duration.not_applicable
    if stated_duration and duration.max_bars is not None and duration.max_bars < 2:
        raise GroundingError(f"the spec caps the base at {duration.max_bars} bar(s) — a base "
                             "needs at least 2 bars; restate the duration")
    if stated_duration and duration.min_bars is not None:
        base_min = duration.min_bars
        rubric.append(RubricLine("base length floor", f">= {base_min} bars since the base "
                                 "high was set", "spec"))
    else:
        base_min = base_breakout.BreakoutRetestConfig.base_min_bars
        detail = "your spec didn't state this as a number"
        stated_max = duration.max_bars if stated_duration else None
        if stated_max is not None and base_min > stated_max:
            # An unstated floor must not contradict the stated cap ("a base of at most 20 bars").
            base_min = max(2, stated_max // 2)
            detail += f" — lowered from the usual default to sit under your {stated_max}-bar cap"
        rubric.append(RubricLine("base length floor", f">= {base_min} bars since the base "
                                 "high was set", "default", detail))
    lookback = base_breakout.BreakoutRetestConfig.base_lookback_bars
    if stated_duration and duration.max_bars is not None:
        base_max = duration.max_bars
        rubric.append(RubricLine("base length cap", f"<= {base_max} bars", "spec"))
    else:
        base_max = None
        rubric.append(RubricLine("base length cap", f"none stated — the level search reaches "
                                 f"back {lookback} bars, so longer bases aren't found", "default"))

    if size is not None and size.min is not None:
        depth_min = size.min
        rubric.append(RubricLine("base depth floor", f">= {depth_min:g}% below the base high", "spec"))
    else:
        depth_min = base_breakout.BreakoutRetestConfig.depth_min_pct
        stated_max = size.max if size is not None else None
        detail = "your spec didn't state this as a number"
        if stated_max is not None and depth_min >= stated_max:
            # An unstated floor must not contradict the stated cap ("no more than 8% deep").
            depth_min = stated_max / 2
            detail += f" — halved from the usual default to sit under your {stated_max:g}% cap"
        rubric.append(RubricLine("base depth floor", f">= {depth_min:g}% below the base high",
                                 "default", detail))
    if size is not None and size.max is not None:
        depth_max = size.max
        rubric.append(RubricLine("base depth cap", f"<= {depth_max:g}% below the base high", "spec"))
    else:
        depth_max = base_breakout.BreakoutRetestConfig.depth_max_pct
        detail = "your spec didn't state this as a number"
        if depth_min >= depth_max:
            # An unstated cap must not contradict the stated floor ("at least 50% deep").
            if depth_min >= 99.0:
                raise GroundingError(f"the spec's depth floor ({depth_min:g}%) leaves no room "
                                     "under 100% for a cap; restate the size")
            depth_max = min(99.0, depth_min * 1.5)
            detail += f" — raised from the usual default to sit above your {depth_min:g}% floor"
        rubric.append(RubricLine("base depth cap", f"<= {depth_max:g}% below the base high",
                                 "default", detail))

    config = base_breakout.BreakoutRetestConfig(
        base_min_bars=base_min, base_max_bars=base_max,
        depth_min_pct=depth_min, depth_max_pct=depth_max)
    try:
        config.validate()
    except ValueError as e:
        raise GroundingError(f"the spec's numbers don't make a detectable definition: {e}")
    tol, window, kill = config.retest_tol_atr, config.retest_window_bars, config.kill_tol_atr
    touches, margin, rally = config.min_extra_touches, config.breakout_min_atr, config.min_rally_atr
    exclude, gap = config.touch_exclude_bars, config.min_retest_gap_bars
    rubric.append(RubricLine("level touches", f">= {touches} later base bars re-touch the level "
                             f"(high within {tol:g} ATR(14) of it), not counting the last "
                             f"{exclude} bars before the breakout", "default",
                             "added from the 2026-10-19 grounding round: a single spike high "
                             "isn't a tested ceiling; the ramp exclusion from the 2026-10-20 "
                             "round: the run-up into the breakout isn't a touch"))
    rubric.append(RubricLine("breakout decisiveness", f"the breakout close clears the level by "
                             f"more than {margin:g} ATR(14)", "default",
                             "added from the 2026-10-19 grounding round"))
    rubric.append(RubricLine("trigger", "the first bar whose low comes within the retest "
                             "tolerance of the level and whose close holds at or above it",
                             "default", 'your trigger says "the retest holds" — this is the applied reading'))
    rubric.append(RubricLine("retest tolerance", f"low within {tol:g} ATR(14) of the level",
                             "default", "no structured slot yet — if your idea states one, "
                             "check the charts against it"))
    rubric.append(RubricLine("retest window", f"within {window} bars of the breakout", "default",
                             "no structured slot yet"))
    rubric.append(RubricLine('failed-retest kill ("decisively below")',
                             f"a close more than {kill:g} ATR(14) below the level ends the episode",
                             "default", 'your rule says "decisively" without a number'))
    rubric.append(RubricLine("minimum rally", f"a bar before the retest (the breakout bar counts) "
                             f"must reach {rally:g} ATR(14) above the level", "default",
                             "added from the 2026-10-19 grounding round: a next-bar graze "
                             "isn't a round-trip"))
    rubric.append(RubricLine("retest gap", f"the retest can't arrive sooner than {gap} bars "
                             f"after the breakout", "default",
                             "added from the 2026-10-20 grounding round: a 3-bar wobble at "
                             "the level isn't a round trip"))

    for signal in spec.supporting_signals:
        if signal.role == "filter":
            rubric.append(RubricLine(f"filter: {signal.name}", "NOT APPLIED", "default",
                                     "no structured mapping yet — instances ignore this filter"))
    for rule in spec.invalidation:
        if rule.phase == "before_entry":
            rubric.append(RubricLine(f"invalidation (before entry): {rule.description}",
                                     "NOT READ", "default",
                                     "rule text isn't read — if it restates a parameter above "
                                     "it is already applied; anything else is ignored"))

    frames: dict[str, pd.DataFrame] = {}
    atrs: dict[str, pd.Series] = {}
    for ticker, frame in panel.groupby("ticker", sort=False):
        if not frame["date"].is_monotonic_increasing:
            raise GroundingError(f"panel rows for {ticker!r} aren't date-sorted — "
                                 "pass a (ticker, date)-sorted feature panel")
        frames[ticker] = frame
        atrs[ticker] = same_bar_atr(frame)

    def episodes_for(run_config) -> dict[str, list[base_breakout.Episode]]:
        return {ticker: base_breakout.detect(frame, atrs[ticker], run_config)
                for ticker, frame in frames.items()}

    def held(episodes: dict[str, list[base_breakout.Episode]]) -> dict[str, dict[int, base_breakout.Episode]]:
        """Holding-retest episodes per ticker, keyed by the retest (signal) position."""
        kept = {ticker: {e.retest: e for e in eps if e.outcome == base_breakout.RETEST_HELD}
                for ticker, eps in episodes.items()}
        return {ticker: by_position for ticker, by_position in kept.items() if by_position}

    def dated(by_ticker: dict[str, dict[int, base_breakout.Episode]]
              ) -> list[tuple[str, pd.Timestamp, base_breakout.Episode]]:
        return sorted(((ticker, pd.Timestamp(frames[ticker]["date"].iloc[position]), episode)
                       for ticker, by_position in by_ticker.items()
                       for position, episode in by_position.items()),
                      key=lambda item: item[:2])

    def span(ticker: str, episode: base_breakout.Episode) -> tuple[pd.Timestamp, pd.Timestamp, float]:
        dates = frames[ticker]["date"]
        return (pd.Timestamp(dates.iloc[episode.base_start]),
                pd.Timestamp(dates.iloc[episode.end]), episode.level)

    strict = held(episodes_for(config))
    matches = tuple(Candidate(ticker, date, overlay_span=span(ticker, episode))
                    for ticker, date, episode in dated(strict))
    shown_episodes: list[tuple[str, base_breakout.Episode]] = []  # painted last wins overlaps

    def minus_strict(ring: dict[str, dict[int, base_breakout.Episode]]):
        return {ticker: kept for ticker, by_position in ring.items()
                if (kept := {p: e for p, e in by_position.items()
                             if p not in strict.get(ticker, {})})}

    near: tuple[Candidate, ...] = ()
    if near_misses:
        relaxed_min_bars = max(2, math.floor(base_min / RELAX_FACTOR))
        relaxed_depth_min = depth_min / RELAX_FACTOR
        relaxed_depth_max = depth_max * RELAX_FACTOR
        relaxed_window = math.ceil(window * RELAX_FACTOR)
        relaxed_tol = tol * RELAX_FACTOR

        relaxed_touches = max(0, math.floor(touches / RELAX_FACTOR))
        relaxed_margin = margin / RELAX_FACTOR
        relaxed_rally = rally / RELAX_FACTOR
        relaxed_exclude = math.floor(exclude / RELAX_FACTOR)
        relaxed_gap = max(1, math.floor(gap / RELAX_FACTOR))

        length_ring = minus_strict(held(episodes_for(replace(config, base_min_bars=relaxed_min_bars))))
        floor_ring = minus_strict(held(episodes_for(replace(config, depth_min_pct=relaxed_depth_min))))
        # Relaxing the cap past 100% would admit non-positive prices, not deeper bases.
        cap_ring = (minus_strict(held(episodes_for(replace(config, depth_max_pct=relaxed_depth_max))))
                    if relaxed_depth_max < 100 else {})
        window_ring = minus_strict(held(episodes_for(replace(config, retest_window_bars=relaxed_window))))
        touches_ring = (minus_strict(held(episodes_for(replace(config, min_extra_touches=relaxed_touches))))
                        if relaxed_touches < touches else {})
        exclude_ring = (minus_strict(held(episodes_for(replace(config, touch_exclude_bars=relaxed_exclude))))
                        if relaxed_exclude < exclude else {})
        margin_ring = (minus_strict(held(episodes_for(replace(config, breakout_min_atr=relaxed_margin))))
                       if margin > 0 else {})
        # A looser tolerance (or an earlier-armed rally) can pull the retest onto an
        # earlier bar of an episode that also fires strictly a few bars later — that bar
        # says nothing about where the constraint sits, so episodes whose breakout also
        # fired strictly are dropped from those rings.
        strict_breakouts = {ticker: {e.breakout for e in by_position.values()}
                            for ticker, by_position in strict.items()}

        def drop_strictly_firing(ring: dict[str, dict[int, base_breakout.Episode]]):
            return {ticker: kept for ticker, by_position in ring.items()
                    if (kept := {p: e for p, e in by_position.items()
                                 if e.breakout not in strict_breakouts.get(ticker, set())})}

        tol_ring = drop_strictly_firing(
            minus_strict(held(episodes_for(replace(config, retest_tol_atr=relaxed_tol)))))
        rally_ring = (drop_strictly_firing(
            minus_strict(held(episodes_for(replace(config, min_rally_atr=relaxed_rally)))))
            if rally > 0 else {})
        gap_ring = (drop_strictly_firing(
            minus_strict(held(episodes_for(replace(config, min_retest_gap_bars=relaxed_gap)))))
            if relaxed_gap < gap else {})

        rings = [
            (length_ring, f"base length: fires only when the {base_min}-bar floor is relaxed "
             f"to >= {relaxed_min_bars} bars"),
            (floor_ring, f"base depth floor: fires only when the {depth_min:g}% floor is "
             f"relaxed to >= {relaxed_depth_min:g}%"),
            (cap_ring, f"base depth cap: fires only when the {depth_max:g}% cap is relaxed "
             f"to <= {relaxed_depth_max:g}%"),
            (window_ring, f"retest window: the retest arrives {window + 1}-{relaxed_window} "
             f"bars after the breakout, not within {window}"),
            (touches_ring, f"level touches: fires only when the {touches}-touch requirement "
             f"is relaxed to >= {relaxed_touches}"),
            (exclude_ring, f"level touch timing: fires only when the {exclude}-bar ramp "
             f"exclusion before the breakout is relaxed to {relaxed_exclude}"),
            (margin_ring, f"breakout decisiveness: fires only when the {margin:g}-ATR margin "
             f"is relaxed to {relaxed_margin:.3g}"),
            (rally_ring, f"minimum rally: fires only when the {rally:g}-ATR rally requirement "
             f"is relaxed to {relaxed_rally:.3g}"),
            (gap_ring, f"retest gap: the retest arrives {relaxed_gap}-{gap - 1} bars after "
             f"the breakout, not >= {gap}"),
            (tol_ring, f"retest tolerance: the low comes within {relaxed_tol:g} ATR of the "
             f"level, not within {tol:g}"),
        ]
        seen: dict[tuple[str, pd.Timestamp], tuple[str, base_breakout.Episode]] = {}
        for ring, fails in rings:
            for ticker, date, episode in dated(ring):
                seen.setdefault((ticker, date), (fails, episode))
            shown_episodes.extend((ticker, e) for ticker, by_position in ring.items()
                                  for e in by_position.values())
        near = tuple(Candidate(ticker, date, fails, overlay_span=span(ticker, episode))
                     for (ticker, date), (fails, episode) in seen.items())

    # The overlay: each presented episode's level across its span, strict episodes
    # painted last so they win any overlap with a ring variant of the same base.
    shown_episodes.extend((ticker, e) for ticker, by_position in strict.items()
                          for e in by_position.values())
    overlay = pd.Series(np.nan, index=panel.index, dtype="float64")
    by_ticker: dict[str, list[base_breakout.Episode]] = {}
    for ticker, episode in shown_episodes:
        by_ticker.setdefault(ticker, []).append(episode)
    for ticker, episodes in by_ticker.items():
        rows = frames[ticker].index
        overlay.loc[rows] = base_breakout.level_overlay(len(rows), episodes)
    # Stored one-bar-lagged like every panel feature; the session runner shifts it back.
    panel[BASE_BREAKOUT_OVERLAY] = overlay.groupby(panel["ticker"]).shift(1)

    return FinderResult(matches, near, tuple(rubric),
                        overlay_column=BASE_BREAKOUT_OVERLAY, overlay_name="breakout level")


# Catalogue detector id -> finder. Grounding dispatches on the spec's `uses`; a spec
# whose detector isn't here yet gets a clear refusal, not an approximation.
FINDERS: dict[str, Callable[..., FinderResult]] = {
    "detector:ma.first_touch": find_first_touch,
    "detector:base_breakout.retest": find_base_breakout_retest,
}


def pick_finder(spec: StrategySpec, override: str | None = None) -> str:
    """The detector id to run: the override, else the first entry of the spec's
    `uses` that has a finder. Refuses clearly rather than approximating."""
    if override is not None:
        if override not in FINDERS:
            raise GroundingError(f"no finder for {override!r}; built so far: {', '.join(FINDERS)}")
        return override
    found = next((u for u in spec.uses if u in FINDERS), None)
    if found is None:
        raise GroundingError(
            f"none of the spec's detectors ({', '.join(spec.uses) or 'none listed'}) has a "
            f"finder yet; built so far: {', '.join(FINDERS)}")
    return found


def dispatch(spec: StrategySpec, panel: pd.DataFrame, *, detector: str | None = None,
             ma: str | None = None, near_misses: bool = True, note=print) -> tuple[str, FinderResult]:
    """Pick the finder and run it — shared by grounding (`ground.py`) and the exploratory
    look (`look.py`), so the two steps can't drift on what a spec dispatches to. A run
    option goes only to a finder that declares it (`ma` means nothing to a future pattern
    or divergence finder); an option the user explicitly passed to a finder that doesn't
    take it is said out loud via `note`, never silently dropped, as is a `detector`
    override that isn't among the spec's own detectors."""
    finder_id = pick_finder(spec, detector)
    finder = FINDERS[finder_id]
    declared = inspect.signature(finder).parameters
    options = {}
    if ma is not None:
        if "ma" in declared:
            options["ma"] = ma  # only an explicit choice is passed: None means the finder's own default
        else:
            note(f"Note: {finder_id} takes no moving-average option; --ma {ma} is ignored.")
    if not near_misses and "near_misses" in declared:
        # Purely a cost switch for callers that only consume matches; a finder without
        # the parameter simply does the full work.
        options["near_misses"] = False
    result = finder(spec, panel, **options)
    if detector is not None and finder_id not in spec.uses:
        note(f"Note: {finder_id} isn't among the spec's own detectors "
             f"({', '.join(spec.uses) or 'none listed'}) — running it anyway, as asked.")
    return finder_id, result
