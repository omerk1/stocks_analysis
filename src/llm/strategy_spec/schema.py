"""Step 1 of the strategy agent (`docs/strategy-agent/idea.md`): what a complete strategy
spec is, written down before any LLM is involved.

The agent's job is to turn a vague trading idea into a spec where every decision is
explicit. This module fixes the target shape (`StrategySpec`) and the check that says
what is still open (`find_gaps`). Later steps build on it:

- step 2: the LLM fills a `StrategySpec` from free text in one shot, scored field by
  field against the hand-written golden specs (`golden_specs.json`, next to this file);
- step 3: the elicitation loop asks one question per gap until `find_gaps` is empty.

Why pydantic: LLM APIs, Gemini included, can be told to answer in a JSON schema, and a
pydantic model produces one (`StrategySpec.model_json_schema()`). The same class then
validates the answer, so a malformed reply fails loudly instead of half-parsing. Whether
Gemini accepts this schema as is (`$defs`/`$ref`, nullable `anyOf`, `additionalProperties`)
or needs it flattened is step 2's to check; validation here doesn't depend on it.

Every section is optional on purpose. The LLM's output in step 2 will be partial, and
"not stated yet" (`None` or an empty list) has to be representable, distinct from a
wrong value. A blank string is rejected: it would otherwise pass as an answer. A section
that genuinely doesn't apply to an idea (a single-bar event has no formation length) says
so with `not_applicable=True`, which is an answer, not a gap.

`find_gaps` reports four kinds of gap:

- **missing**: a required section isn't stated at all;
- **unquantified**: it's described in words but has no numbers ("price coils tightly");
- **invalid**: it breaks one of the repo's guardrails (raw-price size, same-bar
  execution), is self-contradictory (min above max, values on a section marked not
  applicable), or names a capability id (`uses`) that isn't in the catalogue;
- **unsupported**: the idea asks for something the platform can't test yet (intraday
  bars, earnings surprises, an indicator that isn't built). The spec records it in
  `unsupported`, in the user's words with a reason, instead of swapping in the nearest
  thing that exists; `unsupported.py` logs it so the most-requested ones can be built.

`uses` names the capability catalogue entries (`catalogue.py`) the spec is built from.
The catalogue lists what can be computed, and goes into the extraction prompt (step 2c).

Visual examples (`examples`) are filled by the grounding session (step 4, `ground.py`):
real historical instances found by deterministic code (`finders.py`), judged by the
trader on charts, verdicts recorded here. They aren't checked by `find_gaps` — an
ungrounded spec is complete but unconfirmed, not gapped.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.llm.strategy_spec import catalogue

Direction = Literal["long", "short", "both"]
Timeframe = Literal["daily", "weekly"]
# How a size is made comparable across tickers. `raw_price` is allowed as a value so an
# idea stated in dollars can be recorded as such, then flagged by `find_gaps`.
Normalisation = Literal["atr", "log", "pct", "percentile", "raw_price"]
PriceBasis = Literal["close", "intraday"]
# The signal is known at the close of bar t; the repo executes at t+1, never t.
Execution = Literal["next_open", "same_close"]
GapKind = Literal["missing", "unquantified", "invalid", "unsupported"]
# The spec fields an unsupported request can belong to.
SpecField = Literal["direction", "timeframe", "duration", "size", "trigger", "horizons_bars",
                    "invalidation", "filters_needed", "supporting_signals", "secondary_metrics", "control"]
UnsupportedReason = Literal[
    "unknown_detector",       # a pattern or event the platform doesn't detect
    "unknown_indicator",      # an indicator or feature that isn't computed
    "unsupported_timeframe",  # e.g. intraday or monthly bars
    "unsupported_data",       # data that isn't loaded: options, earnings, news, ...
    "unsupported_execution",  # e.g. limit orders, intraday stops
    "unknown_control",        # a comparison the platform can't build
    "unknown_metric",         # an outcome measure that isn't built
    "other",
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Section(BaseModel):
    # extra="forbid": a misspelled field from the LLM is an error, not silently dropped.
    model_config = ConfigDict(extra="forbid")


class Duration(_Section):
    """How many bars the pattern takes to form."""

    description: Text | None = None
    min_bars: int | None = None
    max_bars: int | None = None
    not_applicable: bool = False


class Size(_Section):
    """The pattern's magnitude, in units comparable across tickers.

    `min`/`max` bound one quantity, as a magnitude (never negative); `pct` is in percent
    (5 means 5%) and a percentile is on a 0-100 scale. An idea with more thresholds keeps the others in the description or in
    the trigger, where they belong to the firing condition.
    """

    description: Text | None = None
    normalisation: Normalisation | None = None
    min: float | None = None
    max: float | None = None
    not_applicable: bool = False


class Proximity(_Section):
    """How close price must come to a level for the trigger to count it as reached: at
    most `max`, a distance in ATR, percent or log (a percentile isn't a distance), or
    `through`: price must trade through the level. `not_applicable`, as everywhere, means
    it doesn't apply: the trigger isn't about price reaching a level. Its own slot, not
    `Size`'s: an idea built on levels often has a size too (a stack of levels at most
    1 ATR wide), and one slot made the two numbers fight."""

    normalisation: Normalisation | None = None
    max: float | None = None
    through: bool = False
    not_applicable: bool = False


class Trigger(_Section):
    """The bar the signal fires on, and when the trade executes. `proximity` is asked
    only of an idea built on price levels (`catalogue.uses_levels`)."""

    description: Text | None = None
    price_basis: PriceBasis | None = None
    execution: Execution | None = None
    proximity: Proximity | None = None


class Rule(_Section):
    """One invalidation rule: what kills the setup, before or after entry."""

    description: Text
    phase: Literal["before_entry", "after_entry"]


class Setting(_Section):
    """One of a detector's settings (`catalogue.SETTINGS`), as the trader gave it. The
    value stays in the trader's words ("0.5 and 0.618", "8 ATR"): the finder that
    applies it parses it, and the grounding rubric shows what was applied."""

    name: Text
    value: Text


class Signal(_Section):
    """A supporting signal: a hard filter, or an input that only raises confidence.

    `uses` names the catalogue ids this one signal is built from (the spec's own `uses`
    covers the whole idea, so it can't say which detector belongs to which signal).
    A filter whose detector has settings in the catalogue is asked about them until
    `settings` holds at least one, or the trader accepts the defaults (`defaults_ok`).
    """

    name: Text
    description: Text
    role: Literal["filter", "score"]
    uses: list[Text] = Field(default_factory=list)
    settings: list[Setting] = Field(default_factory=list)
    defaults_ok: bool = False


class Control(_Section):
    """What the setup is compared against, so the result is a delta, not a bare mean."""

    description: Text


class Example(_Section):
    """A historical instance the user accepted or rejected (filled by `ground.py`)."""

    ticker: Text
    date: Text
    matches: bool


class UnsupportedRequest(_Section):
    """Something the idea asks for that the platform can't test yet, recorded instead of
    being swapped for the nearest thing it can. `requested` is in the user's words."""

    requested: Text
    field: SpecField
    reason: UnsupportedReason
    detail: Text | None = None

    def key(self) -> tuple[str, str]:
        """What makes two items one request: the wording (as `request_wording` folds it)
        and the reason. Not the field: one request can be filed under several
        (`group_unsupported`)."""
        return request_wording(self.requested), self.reason


# A hyphen that joins words is spelling; one next to a space or a digit's sign is not.
_WORD_HYPHEN = re.compile(r"(?<=[a-z0-9])-(?=[a-z0-9])")
# Punctuation that wraps a word without changing the ask. Not >, <, %, $, which do.
_EDGE_PUNCTUATION = ".,;:!?'\"()"


def request_wording(requested: str) -> str:
    """One wording for grouping and matching: lowercased, spacing collapsed, a hyphen
    joining words folded to a space ("15-minute bars" is "15 Minute bars"; the minus in
    "< -2" survives, it doesn't join two words), and wrapping punctuation stripped from
    each word ('unusual "options" flow.' is 'unusual options flow'). Meaning-bearing
    symbols stay: "VIX > 30" and "VIX < 30", or "10%" and "$10", are different asks and
    must not merge."""
    folded = _WORD_HYPHEN.sub(" ", requested.lower().replace("_", " "))
    words = [w for w in (t.strip(_EDGE_PUNCTUATION) for t in folded.split()) if w]
    # All punctuation ("...", "??") stays itself rather than everything becoming "".
    return " ".join(words) or " ".join(folded.split())


@dataclass(frozen=True)
class RequestGroup:
    """One distinct request: the first wording given, every field it was filed under, and
    the details given under each field (only fields that have one), in order, without
    repeats. `details` is `(field, details)` pairs rather than a dict, so a group stays
    hashable like the rest of its fields; read it with `details_for`."""

    requested: str
    reason: UnsupportedReason
    fields: tuple[SpecField, ...]
    details: tuple[tuple[SpecField, tuple[str, ...]], ...]

    def details_for(self, field: SpecField) -> tuple[str, ...]:
        return next((d for f, d in self.details if f == field), ())


def group_unsupported(items: list[UnsupportedRequest]) -> list[RequestGroup]:
    """`items` merged by `UnsupportedRequest.key`, in first-seen order; a field's details
    are merged on their `request_wording` folding. An LLM repeating a request shouldn't ask the
    user twice or count twice in the log, so every reader goes through this rather than
    reading `spec.unsupported` item by item."""
    groups: dict[tuple[str, str], tuple[UnsupportedRequest, dict]] = {}
    for item in items:
        first, fields = groups.setdefault(item.key(), (item, {}))
        details = fields.setdefault(item.field, {})  # dicts as ordered sets
        if item.detail:
            details.setdefault(request_wording(item.detail), item.detail)
    return [RequestGroup(first.requested, first.reason, tuple(fields),
                         tuple((f, tuple(d.values())) for f, d in fields.items() if d))
            for first, fields in groups.values()]


class StrategySpec(_Section):
    name: Text | None = None
    direction: Direction | None = None
    timeframe: Timeframe | None = None
    duration: Duration | None = None
    size: Size | None = None
    trigger: Trigger | None = None
    horizons_bars: list[int] = Field(default_factory=list)
    invalidation: list[Rule] = Field(default_factory=list)
    # How many of the filter signals must hold at once ("any 2 of these"; all of them is
    # their count). Not stated is None: with two or more filters the gap check asks,
    # since a plain list reads as "all required" whatever the trader meant. Before
    # `supporting_signals` so it's asked first: it's the idea's shape, the signals'
    # settings are details.
    filters_needed: int | None = None
    supporting_signals: list[Signal] = Field(default_factory=list)
    secondary_metrics: list[Text] = Field(default_factory=list)
    control: Control | None = None
    examples: list[Example] = Field(default_factory=list)
    # Capability catalogue ids the spec is built from (`catalogue.py`), e.g. "indicator:rsi".
    uses: list[Text] = Field(default_factory=list)
    # As the LLM wrote it, repeats included; read it through `group_unsupported`.
    unsupported: list[UnsupportedRequest] = Field(default_factory=list)


@dataclass(frozen=True)
class Gap:
    field: str
    kind: GapKind
    reason: str
    # The list item the gap is about (a supporting signal's name), so each item can be
    # asked about on its own; None for a gap about the field as a whole.
    item: str | None = None


# What the trader can say instead of a distance, in every proximity question.
_PROXIMITY_WAY_OUT = "or say it must trade through it, or that the trigger isn't about reaching a level"


# The only distances to a level, each as written after a number ("0.3 ATR", "2%").
PROXIMITY_UNITS = MappingProxyType({"atr": " ATR", "pct": "%", "log": " (log)"})


def proximity_gaps(p: Proximity) -> list[tuple[GapKind, str]]:
    """What's still open or wrong in a stated proximity, as (kind, reason); empty means
    it's settled. The one place its rules live: `find_gaps` asks these, and a finder
    words a proximity only when there are none."""
    if p.through and p.not_applicable:
        return [("invalid", "proximity says both that price must trade through the level and that the "
                 "trigger isn't about reaching one")]
    if p.through or p.not_applicable:
        if p.normalisation is None and p.max is None:
            return []
        said = "price must trade through the level" if p.through else "proximity doesn't apply"
        return [("invalid", f"{said}, but a distance is given too")]
    asks: list[tuple[GapKind, str]] = []
    if p.normalisation is None:
        asks.append(("unquantified", "how close price must come: in ATR, percent or log?"))
    elif p.normalisation == "raw_price":
        asks.append(("invalid", "a proximity in raw price isn't comparable across tickers; use ATR, percent or log"))
    elif p.normalisation == "percentile":
        asks.append(("invalid", "a percentile isn't a distance to a level; use ATR, percent or log"))
    # Not with rejected units: the question would ask for a number in them.
    if p.max is None:
        if p.normalisation is None or p.normalisation in PROXIMITY_UNITS:
            asks.append(("unquantified", "how close price must come: at most how far?"))
    elif not math.isfinite(p.max) or p.max < 0:
        asks.append(("invalid", "a proximity is a distance: a finite number, not negative"))
    # The follow-ups keep the first question's way out, once, on the last open question
    # (an invalid one only if nothing is open): a vague first answer mustn't force a distance.
    at = max((n for n, (kind, _) in enumerate(asks) if kind == "unquantified"), default=len(asks) - 1)
    return [(kind, reason + (f" ({_PROXIMITY_WAY_OUT})" if n == at else "")) for n, (kind, reason) in enumerate(asks)]


def find_gaps(spec: StrategySpec) -> list[Gap]:
    """Every decision still open in `spec`, in field order. Empty means complete.

    Supporting signals and secondary metrics are optional: an idea may have none, and the
    platform reports hit rate, win/loss ratio and skew for every test anyway.
    """
    gaps: list[Gap] = []

    def add(field: str, kind: GapKind, reason: str, item: str | None = None) -> None:
        gaps.append(Gap(field, kind, reason, item))

    # Each reason is shown to the trader as the question, so it says what the answer can
    # be. No example numbers: a number in the question is one the trader didn't say.
    if spec.direction is None:
        add("direction", "missing", "long, short, or both?")
    if spec.timeframe is None:
        add("timeframe", "missing", "daily or weekly bars? (intraday and monthly aren't supported)")

    d = spec.duration
    if d is None:
        add("duration", "missing", "how many bars does the pattern take to form? A minimum, a maximum or both; "
            "or say it's a single-bar event")
    elif d.not_applicable:
        if d.min_bars is not None or d.max_bars is not None:
            add("duration", "invalid", "marked not applicable but has bar counts")
    else:
        if d.min_bars is None and d.max_bars is None:
            add("duration", "unquantified", "how many bars does the pattern take to form: at least, at most, "
                "or both?")
        if (d.min_bars is not None and d.min_bars < 1) or (d.max_bars is not None and d.max_bars < 1):
            add("duration", "invalid", "bar counts must be at least 1")
        if d.min_bars is not None and d.max_bars is not None and d.min_bars > d.max_bars:
            add("duration", "invalid", f"min_bars {d.min_bars} > max_bars {d.max_bars}")

    s = spec.size
    if s is None:
        add("size", "missing", "how big must the pattern be? A bound (at least, at most, or both) in ATR, "
            "percent, log or a trailing percentile; or say size doesn't matter")
    elif s.not_applicable:
        if s.normalisation is not None or s.min is not None or s.max is not None:
            add("size", "invalid", "marked not applicable but has a normalisation or bounds")
    else:
        if s.normalisation is None:
            add("size", "unquantified", "how big must the pattern be, in what units: ATR, percent, log or a "
                "trailing percentile?")
        elif s.normalisation == "raw_price":
            add("size", "invalid", "raw price isn't comparable across tickers; use ATR, log, % or percentile")
        if s.min is None and s.max is None:
            add("size", "unquantified", "how big must the pattern be: at least, at most, or both?")
        given = [b for b in (s.min, s.max) if b is not None]
        if not all(math.isfinite(b) for b in given):
            add("size", "invalid", "bounds must be finite numbers")
        # The other checks see only the finite bounds: a NaN or infinite one is one defect,
        # reported once above, and a negative bound beside it is still a second.
        bounds = [b for b in given if math.isfinite(b)]
        if len(bounds) == 2 and s.min > s.max:
            add("size", "invalid", f"min {s.min} > max {s.max}")
        if any(b < 0 for b in bounds):
            add("size", "invalid", "bounds are magnitudes and can't be negative")
        if s.normalisation == "percentile" and any(b > 100 for b in bounds):
            add("size", "invalid", "a percentile is on a 0-100 scale")

    t = spec.trigger
    if t is None or t.description is None:
        # Basis and execution are asked about once there is a condition to attach them to.
        add("trigger", "missing", "what happens on the bar the signal fires on?")
    else:
        if t.price_basis is None:
            add("trigger", "unquantified", "does it fire on the bar's close, or when its intraday high or low "
                "gets there?")
        if t.execution is None:
            add("trigger", "unquantified", "the trade is entered at the next bar's open (never on the signal "
                "bar itself); is that right?")
        elif t.execution == "same_close":
            add("trigger", "invalid", "a signal known at the close of bar t executes at t+1, never on bar t")
        p = t.proximity
        if p is None:
            if catalogue.uses_levels(spec.uses + [i for sig in spec.supporting_signals for i in sig.uses]):
                add("trigger", "unquantified", "how close must price come to a level for it to count as reached? "
                    f"At most how far, in ATR, percent or log; {_PROXIMITY_WAY_OUT}")
        else:
            for kind, reason in proximity_gaps(p):
                add("trigger", kind, reason)

    if not spec.horizons_bars:
        add("horizons_bars", "missing", "how many bars after entry is the outcome measured? One or more")
    else:
        if any(h < 1 for h in spec.horizons_bars):
            add("horizons_bars", "invalid", "horizons must be at least 1 bar")
        if len(set(spec.horizons_bars)) < len(spec.horizons_bars):
            add("horizons_bars", "invalid", "a horizon is listed twice")

    if not spec.invalidation:
        add("invalidation", "missing", "what kills the setup? Before entry it cancels the setup, after entry "
            "it exits the trade; give either or both")

    filters = [sig.name for sig in spec.supporting_signals if sig.role == "filter"]
    n = spec.filters_needed
    if n is None:
        if len(filters) >= 2:
            add("filters_needed", "missing", f"must all {len(filters)} filters hold at once, or at least "
                f"how many of them? ({'; '.join(filters)})")
    elif not filters:
        add("filters_needed", "invalid", "a count of filters needed, but no supporting signal is a filter")
    elif not 1 <= n <= len(filters):
        add("filters_needed", "invalid", f"{n} filters needed, but there are {len(filters)}")

    # A signal is asked about, and its answer put back, by name, so names must be unique
    # (the elicitation loop makes them so; this catches a spec built any other way).
    names = [sig.name for sig in spec.supporting_signals]
    shared = [name for name in dict.fromkeys(names) if names.count(name) > 1]
    if shared:
        add("supporting_signals", "invalid", f"two signals share a name ({'; '.join(shared)}); "
            "each needs its own")
    for sig in spec.supporting_signals:
        # About the whole list, not this signal: a per-signal question only asks settings,
        # so its answer can't change the detector.
        for cap_id in dict.fromkeys(sig.uses):
            if cap_id not in catalogue.IDS:
                add("supporting_signals", "invalid",
                    f"{sig.name!r} uses {cap_id!r}, which isn't in the capability catalogue")
        known = catalogue.settings_for(sig.uses)
        for setting in sig.settings:
            if setting.name not in known:
                listed = ", ".join(known) or "its detector has none listed"
                add("supporting_signals", "invalid",
                    f"{setting.name!r} isn't one of its settings ({listed})", sig.name)
        # Only a filter decides which events exist, so only a filter is asked; a filter
        # with no detector mapped has nothing to ask about (an unmet one is `unsupported`).
        if sig.role == "filter" and known and not sig.settings and not sig.defaults_ok:
            asked = "; ".join(s.shown() for s in known.values())
            add("supporting_signals", "unquantified",
                f"what makes it count? {asked} (or say the detector's defaults are fine)", sig.name)

    if spec.control is None:
        add("control", "missing", "every test already compares against all stock-days, other stocks on the "
            "same dates, and matched stocks; what else must the setup beat to count? (say none if those are "
            "enough)")

    for cap_id in dict.fromkeys(spec.uses):
        if cap_id not in catalogue.IDS:
            add("uses", "invalid", f"{cap_id!r} isn't in the capability catalogue; "
                "if the idea needs it, it belongs in `unsupported`")

    # Blocking: the spec can't be tested as stated. A field may also be reported missing
    # (an intraday idea has no supported timeframe), so the user can pick a supported one.
    # One gap per field a request was filed under, worded as the request was first given,
    # with only that field's details; a repeat within a field is one gap.
    for group in group_unsupported(spec.unsupported):
        for field in group.fields:
            details = group.details_for(field)
            detail = f" ({'; '.join(details)})" if details else ""
            add(field, "unsupported", f"{group.requested!r}: {group.reason.replace('_', ' ')}{detail}")

    # Field order across every kind of gap, and within a field the gaps about the field as
    # a whole before those about one item (a stable sort keeps the rest in order).
    order = {name: n for n, name in enumerate(StrategySpec.model_fields)}
    return sorted(gaps, key=lambda g: (order.get(g.field, len(order)), g.item is not None))


GOLDEN_SPECS_PATH = Path(__file__).with_name("golden_specs.json")


@dataclass(frozen=True)
class GoldenSpec:
    """A spec written by hand for an idea this repo already built, used as an answer key.

    `description` is the idea as a user might first type it (written after the fact, from
    the source doc). `stated` names the fields that description mentions at all, in words
    or numbers; a list field counts as stated if any one item is mentioned. In step 2, an
    extractor that fills a field the description never mentions has invented it, a worse
    failure than leaving it for the elicitation loop to ask about. Finer, per-value
    scoring is step 2's to define.
    """

    id: str
    source: str
    description: str
    stated: tuple[str, ...]
    spec: StrategySpec


def load_golden_specs(path: Path = GOLDEN_SPECS_PATH) -> list[GoldenSpec]:
    with path.open() as f:
        raw = json.load(f)
    for item in raw:
        if not item["description"].strip():
            raise ValueError(f"golden spec {item['id']!r} has a blank description")
    return [
        GoldenSpec(
            id=item["id"],
            source=item["source"],
            description=item["description"],
            stated=tuple(item["stated"]),
            spec=StrategySpec.model_validate(item["spec"]),
        )
        for item in raw
    ]
