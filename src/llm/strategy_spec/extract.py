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
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

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
which is the point. No defaults — don't assume daily bars, a long side, or a horizon.
- Numbers only where the idea gives them. "A tight range" goes in the description with \
the numeric bounds left null.
- The capability catalogue below is everything the platform can compute. If the idea \
needs anything outside it — data, an indicator, a pattern, a timeframe, an execution \
style, a kind of control or metric — add an entry to `unsupported` (`requested` in the \
trader's own words, the spec `field` it belongs to, a `reason`) and leave that field \
empty. Never substitute the nearest supported thing.
- `uses` lists the catalogue ids the spec is built from, and nothing else.
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
    has: str  # a substring of the request's wording (case and spacing ignored); "" = any
    reason: UnsupportedReason
    optional: bool = False

    def matches(self, requested: str, reason: str) -> bool:
        return self.reason == reason and request_wording(self.has) in request_wording(requested)


@dataclass(frozen=True)
class Case:
    id: str
    idea: str
    fields: dict[str, Expectation]
    flags: tuple[ExpectedFlag, ...]


def _expectation(field: str, raw) -> Expectation:
    if raw in ("blank", "described", "either"):
        if raw == "described" and field in _SCALARS + ("horizons_bars",):
            raise ValueError(f"{field} has no description to check")
        return Expectation(raw)
    if isinstance(raw, dict) and set(raw) == {"value"} and field in _SCALARS:
        return Expectation("values", raw["value"])
    if isinstance(raw, dict) and set(raw) == {"values"}:
        if field == "horizons_bars" and isinstance(raw["values"], list):
            return Expectation("values", raw["values"])
        if field in QUANT_ATTRS and isinstance(raw["values"], dict) and raw["values"]:
            unknown = set(raw["values"]) - set(QUANT_ATTRS[field])
            if not unknown:
                return Expectation("values", raw["values"])
    raise ValueError(f"bad expectation for {field}: {raw!r}")


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    golden = {g.id: g.description for g in load_golden_specs()}
    cases = []
    with path.open() as f:
        raw = json.load(f)
    for item in raw:
        idea = golden[item["golden"]] if "golden" in item else item["idea"]
        if set(item["fields"]) != set(get_args(SpecField)):
            raise ValueError(f"case {item['id']!r} must cover every spec field exactly once")
        fields = {f: _expectation(f, v) for f, v in item["fields"].items()}
        flags = tuple(ExpectedFlag(f["has"], f["reason"], f.get("optional", False))
                      for f in item["unsupported"])
        if any(f.reason not in get_args(UnsupportedReason) for f in flags):
            raise ValueError(f"case {item['id']!r} has an unknown reason")
        cases.append(Case(item["id"], idea, fields, flags))
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("case ids must be unique")
    return cases


def score_field(field: str, spec: StrategySpec, exp: Expectation) -> str:
    """One scored field -> an outcome from OUTCOMES."""
    got = getattr(spec, field)
    empty = got is None or got == []
    if exp.form == "either":
        return "unscored"
    if exp.form == "blank":
        return "correct" if empty else "invented"
    if empty:
        return "left_blank"
    if exp.form == "described":
        # Words were given, numbers and choices weren't: any set here was invented.
        if any(getattr(got, a) not in (None, False) for a in QUANT_ATTRS.get(field, ())):
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
    return CaseScore(case.id, outcomes, missed, len(required) - len(missed), unexpected)


def summarise(scores: list[CaseScore], cases: list[Case]) -> list[str]:
    """One line per case plus totals, then every miss spelled out."""
    by_id = {c.id: c for c in cases}
    lines = [f"{'case':<32} {'correct':>7} {'blank':>6} {'invented':>8} {'wrong':>5} "
             f"{'unscored':>8}  flags"]
    totals = dict.fromkeys(OUTCOMES, 0)
    caught = required = 0
    misses: list[str] = []
    for s in scores:
        n_required = s.caught + len(s.missed)
        caught, required = caught + s.caught, required + n_required
        flag_note = f"{s.caught}/{n_required}" + (f" +{len(s.unexpected)}!" if s.unexpected else "")
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
        misses.extend(f"  {s.case_id} unexpected flag: {u!r}" for u in s.unexpected)
    lines.append(f"{'totals':<32} {totals['correct']:>7} {totals['left_blank']:>6} "
                 f"{totals['invented']:>8} {totals['wrong']:>5} {totals['unscored']:>8}  "
                 f"{caught}/{required}")
    if misses:
        lines.append("misses:")
        lines.extend(misses)
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
    out.mkdir(parents=True, exist_ok=True)
    scores = []
    for case in cases:
        reply = extract(case.idea, client)
        (out / f"{case.id}.json").write_text(json.dumps(
            {"case": case.id, "idea": case.idea, "spec": json.loads(reply.text),
             "usage": asdict(reply.usage)}, indent=1) + "\n")
        scores.append(score_case(reply.parsed, case))
    return scores, out


def score_dir(run_dir: Path, cases: list[Case] | None = None) -> list[CaseScore]:
    """Re-score a saved run, free: the replies are already on disk."""
    cases = cases if cases is not None else load_cases()
    by_id = {c.id: c for c in cases}
    scores = []
    for file in sorted(run_dir.glob("*.json")):
        data = json.loads(file.read_text())
        case = by_id.get(data.get("case"))
        if case is None:
            raise ValueError(f"{file}: no case named {data.get('case')!r}")
        scores.append(score_case(StrategySpec.model_validate(data["spec"]), case))
    if not scores:
        raise ValueError(f"no saved replies in {run_dir}")
    return scores


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
