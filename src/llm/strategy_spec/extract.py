"""Step 2c of the strategy agent (`docs/strategy-agent/idea.md`): one-shot extraction.

One Gemini call turns a trading idea written in plain language into a `StrategySpec`
(step 1's schema), and an answer key scores the result field by field. That score is the
baseline every later prompt change has to beat. The prompt carries no worked examples:
the only worked examples that exist are the scored cases themselves, and putting them in
the prompt would leak the answers. Few-shot prompting belongs to the optimisation step,
which gets its own held-out split.

What "right" means comes from `extraction_cases.json`, not from the golden specs as
built: a golden spec records decisions made while building (the first-touch study's
"away" threshold is 1 ATR), while the idea text often only says "well away". An
extractor that writes 1.0 has invented a number the user never gave, and inventing is
worse than leaving the field blank — a blank field becomes a question in the elicitation
loop (step 3), an invented value becomes a silent assumption nobody confirmed. So each
case states, per spec field, one of:

- "blank": the text doesn't mention it, so the field must stay empty;
- "described": mentioned in words only, so there must be text but no numbers or choices;
- the exact values the text gives ({"value": "long"}, {"values": {"min": 1.5}});
- "either": genuinely ambiguous — recording the user's words and leaving the field empty
  are both defensible — so the field is left out of the score.

Each scored field comes back as `correct`, `left_blank` (empty when the text gave
something), `invented` (filled when the text gave nothing), or `wrong` (a different
value). Unsupported requests are scored separately: `missed` (expected flags that didn't
appear) and `unexpected` (flags matching no expected entry — on a fully supported idea,
a false alarm). An expected flag marked optional counts neither way: a careful extractor
may raise it but doesn't have to.

`python -m src.llm.strategy_spec.extract eval` runs the real calls (Gemini Flash,
thinking off, temperature 0 — more repeatable, not deterministic, so the baseline runs
twice and the runs are compared) and saves each reply under
`data/llm/extraction_runs/<timestamp>/` in the main checkout (git-ignored);
`... score <dir>` re-scores a saved run without spending anything. Only `eval` reaches
the API; the tests stub the client. Eval runs never write the unsupported-requests log:
test ideas aren't user demand.
"""

from __future__ import annotations

import argparse
import functools
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from src.llm.gemini import GeminiClient, Reply
from src.llm.paths import llm_data_dir
from src.llm.strategy_spec import catalogue
from src.llm.strategy_spec.schema import (
    SpecField, StrategySpec, UnsupportedReason, group_unsupported, load_golden_specs, request_wording)

PURPOSE = "strategy_spec.extract"
RUNS_DIR_NAME = "extraction_runs"
CASES_PATH = Path(__file__).with_name("extraction_cases.json")

RULES = """\
You turn a trader's idea, written in plain language, into the strategy-spec JSON schema \
you were given. The spec will be tested on historical data exactly as you fill it in, so:

- Fill in only what the idea states, in words or numbers. Leave a field null (or an \
empty list) rather than guess: every blank field becomes a question back to the trader, \
which is the point. No defaults, no conventions, no best practice — don't assume daily \
bars, a long side, close prices, next-open execution, a horizon, or standard metrics. \
Record a price basis or execution when the idea states one; otherwise the platform \
applies its own conventions, and filling them in from habit is not your job.
- Null means "the idea didn't say". A description holds the trader's own words, never \
your commentary — if the idea doesn't mention a section, the whole section stays null \
instead of a description that says it wasn't mentioned. `not_applicable` is true only \
when the idea itself rules the section out in so many words (say, "there's no pattern \
to measure here, it happens on one bar"); silence is null, never `not_applicable`. That holds \
even when your own market knowledge says a section obviously doesn't apply — if the \
idea didn't say it, leave it null and the trader confirms it in the follow-up, not you.
- The reverse too: when the idea does state something, in words alone, capture those \
words in that section's description — don't leave a mentioned section null just \
because it carries no numbers.
- Don't infer the timeframe: an indicator's lookback (a 30-day average, say) is not by \
itself the chart's bar size. Fill `timeframe` only when the idea says what bars it \
works on.
- Numbers only where the idea gives them. "Barely moving" goes in the description with \
the numeric bounds left null; "over the long run" is not a number of bars, so \
`horizons_bars` stays empty. If you catch yourself choosing among plausible figures, \
the answer is null.
- A comparison belongs in `control` only when the idea states one. Never design a \
control yourself, however obvious a good one would be — the catalogue's control entries \
describe what the platform could offer, they are not defaults to pick from.
- The capability catalogue below is everything the platform can compute. If the idea \
needs anything outside it — data, an indicator, a pattern, a timeframe, an execution \
style, a kind of control or metric — add an entry to `unsupported` (`requested` in the \
trader's own words, the spec `field` it belongs to, a `reason`) and leave that field \
empty. Never substitute the nearest supported thing, and never write the unsupported \
thing into the spec as if it existed: an indicator or pattern the catalogue doesn't \
list goes in `unsupported` (reason `unknown_indicator` / `unknown_detector`), not into \
a trigger description or `uses`. Pick the most specific reason; `other` is a last \
resort. But vague is not unsupported: something the platform can compute that the idea \
just hasn't quantified ("over the long run", "a decent-sized move") is a blank field \
to ask about, not an `unsupported` entry.
- `uses` lists the catalogue ids the spec is built from — ids that appear in the \
catalogue below, nothing else.
- `name` is a short name for the idea.

"""

# What a "described" section must leave empty: the sub-values an extractor could invent.
QUANT_ATTRS = {
    "duration": ("min_bars", "max_bars", "not_applicable"),
    "size": ("normalisation", "min", "max", "not_applicable"),
    "trigger": ("price_basis", "execution"),
}
_SCALARS = ("direction", "timeframe")
OUTCOMES = ("correct", "left_blank", "invented", "wrong", "unscored")


@functools.cache
def build_system() -> str:
    """The prompt's fixed part: the rules, then the capability catalogue."""
    return RULES + catalogue.render()


def extract(idea: str, client: GeminiClient) -> Reply:
    """One budgeted call; `Reply.parsed` is the StrategySpec. Logging the spec's
    unsupported requests is the caller's choice: evals never log, real use does."""
    return client.generate(idea, purpose=PURPOSE, system=build_system(),
                           response_schema=StrategySpec, temperature=0.0)


@dataclass(frozen=True)
class Expectation:
    form: str  # "blank" | "described" | "either" | "values"
    values: object = None  # for "values": a scalar, a list of horizons, or {attr: value}


@dataclass(frozen=True)
class ExpectedFlag:
    has: str  # tokens to find in the request's wording (case and hyphenation ignored); "" = any
    reason: UnsupportedReason
    optional: bool = False

    def matches(self, requested: str, reason: str) -> bool:
        """Reason equal, and the wording contains `has` as consecutive words. A word
        ending in a letter matches as a stem ("sweep" finds "sweeps"); anything else
        matches exactly, so "15" doesn't find "150" and "10%" matches neither "110%"
        nor a bare "10"."""
        if self.reason != reason:
            return False
        has, words = request_wording(self.has).split(), request_wording(requested).split()

        def word(h: str, w: str) -> bool:
            return w == h or (h[-1].isalpha() and w.startswith(h))

        return any(all(word(h, w) for h, w in zip(has, words[i:i + len(has)]))
                   for i in range(len(words) - len(has) + 1))


@dataclass(frozen=True)
class Case:
    id: str
    idea: str
    fields: dict[str, Expectation]
    flags: tuple[ExpectedFlag, ...]
    # True on an idea where nothing is testable, so any flag beyond the required ones is
    # acceptable whatever its wording or reason label: extras are shown but not penalised.
    extra_flags_ok: bool = False


def _validated(field: str, value):
    """Expected values must be ones the schema accepts, or the case is unwinnable — and
    what's stored is the schema's coerced form, since scoring compares with `==` and a
    "1.5" in the key would never equal the extractor's 1.5. A value that means "nothing
    stated" is a 'blank' spelled wrong."""
    try:
        got = getattr(StrategySpec(**{field: value}), field)
    except ValidationError as e:
        raise ValueError(f"bad expected value for {field}: {value!r}") from e
    if _empty(got):
        raise ValueError(f"the expected value for {field} means empty — use 'blank': {value!r}")
    return {a: getattr(got, a) for a in value} if isinstance(value, dict) else got


def _expectation(field: str, raw) -> Expectation:
    if raw in ("blank", "described", "either"):
        if raw == "described" and field in _SCALARS + ("horizons_bars",):
            raise ValueError(f"{field} has no description to check")
        return Expectation(raw)
    if isinstance(raw, dict) and set(raw) == {"value"} and field in _SCALARS:
        return Expectation("values", _validated(field, raw["value"]))
    if isinstance(raw, dict) and set(raw) == {"values"}:
        if field == "horizons_bars" and isinstance(raw["values"], list):
            return Expectation("values", _validated(field, raw["values"]))
        if field in QUANT_ATTRS and isinstance(raw["values"], dict) and raw["values"]:
            unknown = set(raw["values"]) - set(QUANT_ATTRS[field])
            if not unknown:
                return Expectation("values", _validated(field, raw["values"]))
    raise ValueError(f"bad expectation for {field}: {raw!r}")


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    golden = {g.id: g.description for g in load_golden_specs()}
    cases = []
    with path.open() as f:
        raw = json.load(f)
    for n, item in enumerate(raw, 1):
        if not isinstance(item, dict) or "id" not in item:
            raise ValueError(f"case #{n} needs to be an object with an 'id'")
        cid = item["id"]
        try:
            unknown_keys = set(item) - {"id", "golden", "idea", "fields", "unsupported", "notes",
                                        "extra_flags_ok"}
            if unknown_keys:  # a misspelled key would otherwise silently do nothing
                raise ValueError(f"unknown keys {sorted(unknown_keys)}")
            if ("golden" in item) == ("idea" in item):
                raise ValueError("needs exactly one of 'golden' or 'idea'")
            if "golden" in item and item["golden"] not in golden:
                raise ValueError(f"no golden spec named {item['golden']!r}")
            idea = golden[item["golden"]] if "golden" in item else item["idea"]
            if set(item["fields"]) != set(get_args(SpecField)):
                raise ValueError("must cover every spec field exactly once")
            fields = {f: _expectation(f, v) for f, v in item["fields"].items()}
            flags = tuple(ExpectedFlag(f["has"], f["reason"], f.get("optional", False))
                          for f in item["unsupported"])
            if any(f.reason not in get_args(UnsupportedReason) for f in flags):
                raise ValueError("has an unknown reason")
            if any(f.has and not request_wording(f.has) for f in flags):
                # "_" folds to nothing, and an empty wording means "match any".
                raise ValueError("has a flag wording that folds to nothing")
            extra_ok = item.get("extra_flags_ok", False)
            if not isinstance(extra_ok, bool):
                raise ValueError(f"extra_flags_ok must be true or false, not {extra_ok!r}")
        except ValueError as e:
            raise ValueError(f"case {cid!r}: {e}") from e
        except (KeyError, TypeError, AttributeError) as e:  # an authoring mistake names its case
            raise ValueError(f"case {cid!r}: {type(e).__name__}: {e}") from e
        cases.append(Case(cid, idea, fields, flags, extra_ok))
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("case ids must be unique")
    return cases


def _set(value) -> bool:
    """A sub-value the extractor chose. 0 and 0.0 count (`0 == False`, so a membership
    test against False would hide an invented zero); None and False don't."""
    return value is not None and value is not False


def _empty(got) -> bool:
    """Nothing recorded: null, an empty list, or a section with every sub-value at its
    default — Gemini's structured output often writes {"description": null, ...} where
    it means "nothing", and that validates into a default section, not None."""
    if got is None or got == []:
        return True
    # Every sub-value at its default. (Not `got == type(got)()`: a section with a
    # required field, like Control, has no default instance to compare against.)
    return isinstance(got, BaseModel) and not got.model_dump(exclude_defaults=True)


def score_field(field: str, spec: StrategySpec, exp: Expectation) -> str:
    """One scored field -> an outcome from OUTCOMES."""
    got = getattr(spec, field)
    if exp.form == "either":
        return "unscored"
    if exp.form == "blank":
        return "correct" if _empty(got) else "invented"
    if _empty(got):
        return "left_blank"
    if exp.form == "described":
        # Words were given, numbers and choices weren't: any set here was invented. What
        # remains is words alone (an all-default section already counted as empty).
        if any(_set(getattr(got, a)) for a in QUANT_ATTRS.get(field, ())):
            return "invented"
        return "correct"
    if field in _SCALARS:
        return "correct" if got == exp.values else "wrong"
    if field == "horizons_bars":
        return "correct" if sorted(got) == sorted(exp.values) else "wrong"
    # A section: the listed sub-values must match; the rest isn't checked.
    ok = all(getattr(got, a) == want for a, want in exp.values.items())
    return "correct" if ok else "wrong"


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    outcomes: dict[str, str]  # scored field -> outcome
    missed: tuple[str, ...]  # required flags that didn't appear
    caught: int  # required flags that did
    unexpected: tuple[str, ...]  # flagged requests matching no expected entry
    waived: bool = False  # the case accepts extras: `unexpected` is shown, not penalised

    def count(self, outcome: str) -> int:
        return sum(1 for o in self.outcomes.values() if o == outcome)


def score_case(spec: StrategySpec, case: Case) -> CaseScore:
    outcomes = {f: score_field(f, spec, exp) for f, exp in case.fields.items()}
    groups = group_unsupported(spec.unsupported)
    required = [f for f in case.flags if not f.optional]
    missed = tuple(f.has for f in required
                   if not any(f.matches(g.requested, g.reason) for g in groups))
    unexpected = tuple(g.requested for g in groups
                       if not any(f.matches(g.requested, g.reason) for f in case.flags))
    return CaseScore(case.id, outcomes, missed, len(required) - len(missed), unexpected,
                     waived=case.extra_flags_ok)


def summarise(scores: list[CaseScore], cases: list[Case]) -> list[str]:
    """One line per case plus totals, then every miss spelled out."""
    by_id = {c.id: c for c in cases}
    lines = [f"{'case':<32} {'correct':>7} {'blank':>6} {'invented':>8} {'wrong':>5} "
             f"{'unscored':>8}  flags"]
    totals = dict.fromkeys(OUTCOMES, 0)
    caught = required = 0
    misses: list[str] = []
    waived: list[str] = []
    for s in scores:
        n_required = s.caught + len(s.missed)
        caught, required = caught + s.caught, required + n_required
        # "+N!" is a penalty; "+N" alone means the case waives extras but they stay visible.
        extra = f" +{len(s.unexpected)}" + ("" if s.waived else "!") if s.unexpected else ""
        flag_note = f"{s.caught}/{n_required}" + extra
        lines.append(f"{s.case_id:<32} {s.count('correct'):>7} {s.count('left_blank'):>6} "
                     f"{s.count('invented'):>8} {s.count('wrong'):>5} {s.count('unscored'):>8}  {flag_note}")
        for outcome in OUTCOMES:
            totals[outcome] += s.count(outcome)
        for f, o in s.outcomes.items():
            if o not in ("correct", "unscored"):
                exp = by_id[s.case_id].fields[f]
                want = exp.values if exp.form == "values" else exp.form
                misses.append(f"  {s.case_id} {f}: {o} (expected {want!r})")
        misses.extend(f"  {s.case_id} flag missed: {m!r}" for m in s.missed)
        if s.waived:  # not penalties, so not under "misses:", but a spray stays visible
            waived.extend(f"  {s.case_id}: {u!r}" for u in s.unexpected)
        else:
            misses.extend(f"  {s.case_id} unexpected flag: {u!r}" for u in s.unexpected)
    lines.append(f"{'totals':<32} {totals['correct']:>7} {totals['left_blank']:>6} "
                 f"{totals['invented']:>8} {totals['wrong']:>5} {totals['unscored']:>8}  "
                 f"{caught}/{required}")
    if misses:
        lines.append("misses:")
        lines.extend(misses)
    if waived:
        lines.append("waived extras:")
        lines.extend(waived)
    return lines


def default_runs_dir() -> Path:
    return llm_data_dir() / RUNS_DIR_NAME


def run_eval(client: GeminiClient | None = None, cases: list[Case] | None = None,
             out_dir: Path | None = None, now: datetime | None = None) -> tuple[list[CaseScore], Path]:
    """Extract every case, save the raw replies, and score them. One Gemini call per
    case; the replies land under a per-run timestamped directory."""
    cases = cases if cases is not None else load_cases()
    client = client or GeminiClient()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    out = (out_dir or default_runs_dir()) / stamp
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()  # two runs in the same second must not silently overwrite each other
    scores = []
    for case in cases:
        reply = extract(case.idea, client)
        (out / f"{case.id}.json").write_text(json.dumps(
            {"case": case.id, "idea": case.idea, "spec": json.loads(reply.text),
             "usage": asdict(reply.usage)}, indent=1) + "\n")
        scores.append(score_case(reply.parsed, case))
    return scores, out


def score_dir(run_dir: Path, cases: list[Case] | None = None) -> list[CaseScore]:
    """Re-score a saved run, free: the replies are already on disk. A partial run (an
    eval that died mid-way) is refused — its totals would look like an improvement."""
    cases = cases if cases is not None else load_cases()
    if not run_dir.is_dir():
        raise ValueError(f"{run_dir} isn't a directory")
    by_id = {c.id: c for c in cases}
    specs: dict[str, StrategySpec] = {}
    for file in sorted(run_dir.glob("*.json")):
        data = json.loads(file.read_text())
        if data.get("case") not in by_id:
            raise ValueError(f"{file}: no case named {data.get('case')!r}")
        if data["case"] in specs:
            raise ValueError(f"{run_dir} has two replies for {data['case']!r}")
        specs[data["case"]] = StrategySpec.model_validate(data["spec"])
    missing = [c.id for c in cases if c.id not in specs]
    if missing:
        raise ValueError(f"{run_dir} is missing replies for: {', '.join(missing)}")
    return [score_case(specs[c.id], c) for c in cases]  # answer-key order, like eval


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.strategy_spec.extract")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("eval", help="extract every case with real Gemini calls, save and score")
    score = sub.add_parser("score", help="re-score a saved run (no API calls)")
    score.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    cases = load_cases()
    if args.command == "eval":
        scores, out = run_eval(cases=cases)
        print(f"replies: {out}")
    else:
        scores = score_dir(args.run_dir, cases=cases)
    for line in summarise(scores, cases):
        print(line)


if __name__ == "__main__":
    main()
