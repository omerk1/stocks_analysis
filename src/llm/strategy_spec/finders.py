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

import math
from dataclasses import dataclass
from typing import Callable, Literal

import pandas as pd

from src.llm.strategy_spec.schema import StrategySpec
from src.signals.moving_averages.features import ma as ma_features
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
    single spec constraint this near-miss fails, in words the trader can act on."""

    ticker: str
    date: pd.Timestamp
    fails: str | None = None


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


def find_first_touch(spec: StrategySpec, panel: pd.DataFrame, ma: str = DEFAULT_MA) -> FinderResult:
    """Instances of "first touch of a moving average after being away" in `panel`
    (a `features/panel.py` panel, sorted by ticker and date).

    Structured-field mapping: `size.min` under ATR normalisation is the away distance
    (that's what the golden spec quantifies); everything else — touch tolerance, the
    window for the touch, the MA itself — has no structured slot today and falls back
    to the study's defaults, each disclosed in the rubric.
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

    def dated(by_ticker: dict[str, set[int]]) -> list[tuple[str, pd.Timestamp]]:
        return sorted((t, pd.Timestamp(dates_by_ticker[t][p])) for t, ps in by_ticker.items() for p in ps)

    matches = tuple(Candidate(t, d) for t, d in dated(strict))
    seen: dict[tuple[str, pd.Timestamp], str] = {}
    for ring, fails in rings:
        for key in dated(ring):
            seen.setdefault(key, fails)
    near_misses = tuple(Candidate(t, d, fails) for (t, d), fails in seen.items())
    return FinderResult(matches, near_misses, tuple(rubric),
                        overlay_column=ma, overlay_name=f"{family.upper()} {lookback}")


# Catalogue detector id -> finder. Grounding dispatches on the spec's `uses`; a spec
# whose detector isn't here yet gets a clear refusal, not an approximation.
FINDERS: dict[str, Callable[..., FinderResult]] = {
    "detector:ma.first_touch": find_first_touch,
}
