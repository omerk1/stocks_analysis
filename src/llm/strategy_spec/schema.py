"""Step 1 of the strategy agent (`docs/strategy-agent/idea.md`): what a complete strategy
spec is, written down before any LLM is involved.

The agent's job is to turn a vague trading idea into a spec where every decision is
explicit. This module fixes the target shape (`StrategySpec`) and the check that says
what is still open (`find_gaps`). Later steps build on it:

- step 2: the LLM fills a `StrategySpec` from free text in one shot, scored field by
  field against the hand-written golden specs (`golden_specs.json`, next to this file);
- step 3: the elicitation loop asks one question per gap until `find_gaps` is empty.

Why pydantic: Gemini (and most LLM APIs) can be told to answer in a JSON schema, and a
pydantic model *is* that schema (`StrategySpec.model_json_schema()`). The same class then
validates the answer, so a malformed reply fails loudly instead of half-parsing.

Every section is optional on purpose. The LLM's output in step 2 will be partial, and
"not stated yet" (`None` or an empty list) has to be representable, distinct from a
wrong value. A section that genuinely doesn't apply to an idea (a single-bar event has
no formation length) says so with `not_applicable=True`, which is an answer, not a gap.

`find_gaps` reports three kinds of gap:

- **missing**: a required section isn't stated at all;
- **unquantified**: it's described in words but has no numbers ("price coils tightly");
- **invalid**: it breaks one of the repo's guardrails (raw-price size, same-bar
  execution) or is self-contradictory (min above max).

Visual examples (`examples`) are part of the spec but not checked yet: grounding in
historical instances is step 4, and it needs the data tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["long", "short", "both"]
Timeframe = Literal["daily", "weekly"]
# How a size is made comparable across tickers. `raw_price` is allowed as a value so an
# idea stated in dollars can be recorded as such, then flagged by `find_gaps`.
Normalisation = Literal["atr", "log", "pct", "percentile", "raw_price"]
GapKind = Literal["missing", "unquantified", "invalid"]


class _Section(BaseModel):
    # extra="forbid": a misspelled field from the LLM is an error, not silently dropped.
    model_config = ConfigDict(extra="forbid")


class Duration(_Section):
    """How many bars the pattern takes to form."""

    description: str | None = None
    min_bars: int | None = None
    max_bars: int | None = None
    not_applicable: bool = False


class Size(_Section):
    """The pattern's magnitude, in units comparable across tickers."""

    description: str | None = None
    normalisation: Normalisation | None = None
    min: float | None = None
    max: float | None = None
    not_applicable: bool = False


class Trigger(_Section):
    """The bar the signal fires on, and when the trade executes."""

    description: str | None = None
    price_basis: Literal["close", "intraday"] | None = None
    # The signal is known at the close of bar t; the repo executes at t+1, never t.
    execution: Literal["next_open", "same_close"] | None = None


class Rule(_Section):
    """One invalidation rule: what kills the setup, before or after entry."""

    description: str
    phase: Literal["before_entry", "after_entry"]


class Signal(_Section):
    """A supporting signal: a hard filter, or an input that only raises confidence."""

    name: str
    description: str
    role: Literal["filter", "score"]


class Control(_Section):
    """What the setup is compared against, so the result is a delta, not a bare mean."""

    description: str


class Example(_Section):
    """A historical instance the user accepted or rejected (step 4; not checked yet)."""

    ticker: str
    date: str
    matches: bool


class StrategySpec(_Section):
    name: str | None = None
    direction: Direction | None = None
    timeframe: Timeframe | None = None
    duration: Duration | None = None
    size: Size | None = None
    trigger: Trigger | None = None
    horizons_bars: list[int] = Field(default_factory=list)
    invalidation: list[Rule] = Field(default_factory=list)
    supporting_signals: list[Signal] = Field(default_factory=list)
    secondary_metrics: list[str] = Field(default_factory=list)
    control: Control | None = None
    examples: list[Example] = Field(default_factory=list)


@dataclass(frozen=True)
class Gap:
    field: str
    kind: GapKind
    reason: str


def find_gaps(spec: StrategySpec) -> list[Gap]:
    """Every decision still open in `spec`, in field order. Empty means complete.

    Supporting signals and secondary metrics are optional: an idea may have none, and the
    platform reports hit rate, win/loss ratio and skew for every test anyway.
    """
    gaps: list[Gap] = []

    def add(field: str, kind: GapKind, reason: str) -> None:
        gaps.append(Gap(field, kind, reason))

    if spec.direction is None:
        add("direction", "missing", "long, short, or both?")
    if spec.timeframe is None:
        add("timeframe", "missing", "which bar resolution does the pattern live on?")

    d = spec.duration
    if d is None:
        add("duration", "missing", "how many bars does the pattern take to form?")
    elif not d.not_applicable:
        if d.min_bars is None and d.max_bars is None:
            add("duration", "unquantified", "no minimum or maximum bar count")
        if (d.min_bars is not None and d.min_bars < 1) or (d.max_bars is not None and d.max_bars < 1):
            add("duration", "invalid", "bar counts must be at least 1")
        if d.min_bars is not None and d.max_bars is not None and d.min_bars > d.max_bars:
            add("duration", "invalid", f"min_bars {d.min_bars} > max_bars {d.max_bars}")

    s = spec.size
    if s is None:
        add("size", "missing", "how big must the pattern be, and in what units?")
    elif not s.not_applicable:
        if s.normalisation is None:
            add("size", "unquantified", "no normalisation (ATR, log, %, percentile)")
        elif s.normalisation == "raw_price":
            add("size", "invalid", "raw price isn't comparable across tickers; use ATR, log, % or percentile")
        if s.min is None and s.max is None:
            add("size", "unquantified", "no threshold")
        if s.min is not None and s.max is not None and s.min > s.max:
            add("size", "invalid", f"min {s.min} > max {s.max}")

    t = spec.trigger
    if t is None:
        add("trigger", "missing", "which bar does the signal fire on?")
    else:
        if t.description is None:
            add("trigger", "missing", "no trigger condition")
        if t.price_basis is None:
            add("trigger", "unquantified", "on the close or on an intraday high/low?")
        if t.execution == "same_close":
            add("trigger", "invalid", "a signal known at the close of bar t executes at t+1, never on bar t")

    if not spec.horizons_bars:
        add("horizons_bars", "missing", "how many bars after entry is the outcome measured?")
    elif any(h < 1 for h in spec.horizons_bars):
        add("horizons_bars", "invalid", "horizons must be at least 1 bar")

    if not spec.invalidation:
        add("invalidation", "missing", "what kills the setup, before or after entry?")

    if spec.control is None:
        add("control", "missing", "what is the setup compared against?")

    return gaps


GOLDEN_SPECS_PATH = Path(__file__).with_name("golden_specs.json")


@dataclass(frozen=True)
class GoldenSpec:
    """A spec written by hand for an idea this repo already built, used as an answer key.

    `description` is the idea as a user might first type it (written after the fact, from
    the source doc). `stated` names the fields that description mentions at all: in
    step 2, an extractor that fills a field the description never mentions has invented
    it, a worse failure than leaving it for the elicitation loop to ask about.
    """

    id: str
    source: str
    description: str
    stated: tuple[str, ...]
    spec: StrategySpec


def load_golden_specs(path: Path = GOLDEN_SPECS_PATH) -> list[GoldenSpec]:
    with path.open() as f:
        raw = json.load(f)
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
