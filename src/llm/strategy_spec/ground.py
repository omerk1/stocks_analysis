"""Step 4 of the strategy agent (`docs/strategy-agent/idea.md`, workflow step 2): the
grounding session. Once a spec is complete, show the trader real historical instances of
it — "is this what you meant?" — before anything is formalised or tested.

What one session does: dispatch the spec's detector (`spec.uses`) to a finder
(`finders.py`), report the search rubric (every parameter actually applied and where it
came from) and the population size (how often the definition fires, on how many distinct
dates — 40,000 firings on 55 dates means the definition is a regime, not a setup), sample
a handful of matches plus near-misses, chart each one (`charts.py`, ending on the trigger
bar), collect accept/reject verdicts **blind** — near-misses are interleaved
unlabelled, or the trader would know to reject them — then reveal, and record verdicts in
`spec.examples` (the slot waiting in the schema since step 1).

Why so few examples: grounding is disagreement detection, not estimation, and the two
directions are asymmetric. One rejection is immediately useful — it localises a wrong
constraint and sends that field back to the elicitation loop. Approvals only *fail to
find* disagreement, governed by the rule of three: after n clean approvals, all you can
say (~95%) is the trader would reject fewer than ~3/n of the definition's matches. Six
matches and three near-misses per round is enough to catch gross definition mismatches
cheaply, which is the goal; certifying fine agreement is what the honest test later is
for. Examples define the idea; they never validate it.

Sampling is random (never curated — a gallery of "best" examples is the outcome-selection
bias through the back door), stratified across years, on distinct dates (events cluster;
five instances from March 2020 are one observation about the definition), seeded and
recorded so a session is reproducible.

No LLM is involved: deterministic code finds instances, a human judges them, zero tokens.
A rejection's free-text reason is kept in the transcript; acting on it means re-running
the elicitation loop on the named field and grounding again. Two consecutive clean rounds
(all matches accepted, all near-misses rejected) and the spec is grounded.

Transcripts live under `data/llm/grounding_sessions/<timestamp>/` in the main checkout
(git-ignored, same convention as elicitation sessions): the charts, `session.json`
(rewritten after every verdict, so a killed session keeps what it had — and **blind**
while verdicts are being collected, since it sits next to the charts; see
`Session.save`), and the spec with its examples filled in.

CLI: `python -m src.llm.strategy_spec.ground <spec-or-elicitation-transcript.json>`.
Tests drive the loop with scripted answers and a synthetic panel; nothing here calls an
API or needs the network.
"""

from __future__ import annotations

import argparse
import inspect
import json
import random
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.llm.paths import llm_data_dir
from src.llm.strategy_spec import charts
from src.llm.strategy_spec.finders import (
    DEFAULT_MA, FINDERS, Candidate, FinderResult, GroundingError, MA_COLUMNS, shift_to_signal_bar)
from src.llm.strategy_spec.schema import Example, StrategySpec
from src.models.dataset import check_holdout

SESSIONS_DIR_NAME = "grounding_sessions"
MATCHES_SHOWN = 6
NEAR_MISSES_SHOWN = 3
INVALID_ANSWER_LIMIT = 3  # unparseable answers in a row before the session stops


def load_spec(path: Path) -> StrategySpec:
    """A spec from a bare spec JSON or an elicitation transcript (its `spec` key)."""
    raw = json.loads(path.read_text())
    return StrategySpec.model_validate(raw["spec"] if "idea" in raw and "spec" in raw else raw)


def pick_finder(spec: StrategySpec, override: str | None = None) -> str:
    """The detector id to ground with: the override, else the first entry of the spec's
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


def sample(candidates: tuple[Candidate, ...], k: int, rng: random.Random,
           taken_dates: set[pd.Timestamp] | None = None,
           taken_tickers: set[str] | None = None) -> list[Candidate]:
    """Up to `k` of `candidates`: random within each year, round-robin across years (so
    one loud regime can't fill the whole sample), never two on the same date (events
    cluster), and preferring unseen tickers while any remain — anywhere: a round falls
    back to a repeated ticker only after a whole pass over every year found no new one,
    not year by year (a year whose only candidates are seen tickers must not pre-empt
    another year's unseen one)."""
    taken_dates = set(taken_dates or ())
    taken_tickers = set(taken_tickers or ())
    pools: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        pools.setdefault(candidate.date.year, []).append(candidate)
    for pool in pools.values():
        rng.shuffle(pool)
    years = sorted(pools)
    rng.shuffle(years)

    def take(pool: list[Candidate], require_new_ticker: bool) -> Candidate | None:
        for i, candidate in enumerate(pool):
            if candidate.date in taken_dates:
                continue
            if require_new_ticker and candidate.ticker in taken_tickers:
                continue
            return pool.pop(i)
        return None

    picked: list[Candidate] = []
    while len(picked) < k:
        progressed = False
        for require_new_ticker in (True, False):
            for year in years:
                if len(picked) >= k:
                    break
                candidate = take(pools[year], require_new_ticker)
                if candidate is not None:
                    picked.append(candidate)
                    taken_dates.add(candidate.date)
                    taken_tickers.add(candidate.ticker)
                    progressed = True
            if progressed:
                break
        if not progressed:
            break
    return picked


@dataclass
class Shown:
    """One instance as presented: its truth (`fails`), the chart, and the verdict."""

    candidate: Candidate
    chart: str
    verdict: bool | None = None  # None: not answered (session stopped early)
    comment: str | None = None


@dataclass
class Session:
    detector: str
    rubric: list[dict]
    population: dict
    seed: int
    shown: list[Shown] = dataclass_field(default_factory=list)

    def save(self, path: Path, blind: bool = True) -> None:
        """An instance's truth — match or near-miss, and which constraint fails — is
        written to disk only for instances the trader has already judged, and only once
        the loop is over (`blind=False`): the file sits in the same directory as the
        charts the trader is told to open, and one glance at an unblinded row would tell
        them to reject that instance, making the near-miss probe measure nothing. An
        instance never judged keeps its truth off disk even in the final save, so a
        session stopped early (or killed) doesn't pre-burn the sample for a later blind
        round; the reveal only speaks about answered instances anyway."""
        answered = [s for s in self.shown if s.verdict is not None]
        path.write_text(json.dumps({
            "detector": self.detector,
            "rubric": self.rubric,
            "population": self.population,
            "seed": self.seed,
            "shown": [{
                "ticker": s.candidate.ticker, "date": str(s.candidate.date.date()),
                **({} if blind or s.verdict is None
                   else {"kind": "near_miss" if s.candidate.fails else "match",
                         "fails": s.candidate.fails}),
                "chart": s.chart, "verdict": s.verdict, "comment": s.comment,
            } for s in self.shown],
            **({} if blind else {"clean_round": (
                bool(answered) and len(answered) == len(self.shown)
                and all(s.verdict is (s.candidate.fails is None) for s in answered))}),
        }, indent=1) + "\n")


def sessions_dir() -> Path:
    return llm_data_dir() / SESSIONS_DIR_NAME


def ground(spec: StrategySpec, panel: pd.DataFrame, *, ask, say=print,
           out_dir: Path | None = None, ma: str = DEFAULT_MA, seed: int | None = None,
           detector: str | None = None, matches_shown: int = MATCHES_SHOWN,
           near_misses_shown: int = NEAR_MISSES_SHOWN) -> StrategySpec:
    """One grounding round over `panel` (a `features/panel.py` panel, development window
    only — a panel reaching past the holdout boundary is refused). `ask` returns the
    trader's answer to one instance ("y"/"n", an optional reason after a comma) or None
    to stop; `say` reports the rubric, population and the final reveal. Returns the spec
    with the verdicts appended to `examples`."""
    if panel.empty:
        raise GroundingError("the panel is empty — nothing to ground against")
    check_holdout(panel["date"].max())
    finder_id = pick_finder(spec, detector)
    finder = FINDERS[finder_id]
    # A run option goes only to a finder that declares it: `ma` means nothing to a
    # future pattern or divergence finder, and each finder's rubric states what it
    # actually applied, so an undeclared option isn't silently influential either way.
    declared = inspect.signature(finder).parameters
    options = {name: value for name, value in {"ma": ma}.items() if name in declared}
    result: FinderResult = finder(spec, panel, **options)
    if detector is not None and finder_id not in spec.uses:
        say(f"Note: {finder_id} isn't among the spec's own detectors "
            f"({', '.join(spec.uses) or 'none listed'}) — grounding it anyway, as asked.")

    say("Search rubric — what was actually applied:")
    for line in result.rubric:
        detail = f" — {line.detail}" if line.detail else ""
        say(f"  - {line.parameter}: {line.value}  [{line.source}]{detail}")
    dates = {c.date for c in result.matches}
    window = (str(panel['date'].min().date()), str(panel['date'].max().date()))
    say(f"Population: the definition fires {len(result.matches)} times on {len(dates)} "
        f"distinct dates, {window[0]} to {window[1]}.")

    seed = random.randrange(2**32) if seed is None else seed
    rng = random.Random(seed)
    picked = sample(result.matches, matches_shown, rng)
    near = sample(result.near_misses, near_misses_shown, rng,
                  taken_dates={c.date for c in picked},
                  taken_tickers={c.ticker for c in picked})
    shown_candidates = picked + near
    rng.shuffle(shown_candidates)  # blind: the trader must not know which is which
    if not shown_candidates:
        say("No instances found — the definition as stated never fires in the development window.")

    out_dir = out_dir or sessions_dir() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    session = Session(
        detector=finder_id,
        rubric=[{"parameter": r.parameter, "value": r.value, "source": r.source, "detail": r.detail}
                for r in result.rubric],
        population={"matches": len(result.matches), "distinct_dates": len(dates),
                    "near_misses_found": len(result.near_misses), "window": window},
        seed=seed)

    # Only the shown tickers' rows, grouped once — not a full-panel scan per chart.
    # The overlay is whatever the finder declared, not an assumption that every
    # detector is about a moving average.
    shown_tickers = {c.ticker for c in shown_candidates}
    display = panel.loc[panel["ticker"].isin(shown_tickers),
                        ["ticker", "date", "open", "high", "low", "close", result.overlay_column]].copy()
    display["overlay_display"] = shift_to_signal_bar(display, result.overlay_column)
    bars_by_ticker = {ticker: frame.reset_index(drop=True)
                      for ticker, frame in display.groupby("ticker", sort=False)}
    for n, candidate in enumerate(shown_candidates, start=1):
        bars = bars_by_ticker[candidate.ticker]
        figure = charts.instance_chart(
            charts.chart_window(bars, candidate.date), "overlay_display", result.overlay_name,
            candidate.date, f"{candidate.ticker} — {candidate.date.date()}")
        name = f"{n:02d}_{candidate.ticker}_{candidate.date.date()}.html"
        charts.write_chart(figure, out_dir / name)
        session.shown.append(Shown(candidate, name))
    session.save(out_dir / "session.json")

    stopped = False
    for n, shown in enumerate(session.shown, start=1):
        invalid = 0
        while True:
            answer = ask(f"[{n}/{len(session.shown)}] {shown.candidate.ticker} "
                         f"{shown.candidate.date.date()} — chart: {out_dir / shown.chart}\n"
                         "Does this match your idea? (y / n, optional reason after a comma)")
            if answer is None or not answer.strip():
                stopped = True
                break
            head, _, comment = answer.strip().partition(",")
            # Exactly y/yes or n/no: a hedge like "not sure" must not be recorded as a
            # rejection — a misread verdict would send a correct constraint back to the
            # elicitation loop.
            token = head.strip().lower()
            if token in ("y", "yes", "n", "no"):
                shown.verdict = token in ("y", "yes")
                shown.comment = comment.strip() or None
                break
            invalid += 1
            if invalid >= INVALID_ANSWER_LIMIT:
                stopped = True
                break
            say("Answer y or n (a reason can follow after a comma).")
        session.save(out_dir / "session.json")
        if stopped:
            say("Stopping here; verdicts so far are kept in the session file.")
            break

    session.save(out_dir / "session.json", blind=False)  # answered instances' truth can land on disk
    _reveal(session, say)
    answered = [s for s in session.shown if s.verdict is not None]
    spec = spec.model_copy(update={"examples": [
        *spec.examples,
        *(Example(ticker=s.candidate.ticker, date=str(s.candidate.date.date()), matches=s.verdict)
          for s in answered),
    ]})
    (out_dir / "spec.json").write_text(spec.model_dump_json(exclude_none=True, indent=1) + "\n")
    say(f"Session: {out_dir}")
    return spec


def _reveal(session: Session, say) -> None:
    """The end-of-round unblinding: which instances were near-misses, and where the
    trader and the definition disagree — each disagreement names the constraint to take
    back to the elicitation loop."""
    answered = [s for s in session.shown if s.verdict is not None]
    if not answered:
        return
    rejected_matches = [s for s in answered if s.candidate.fails is None and not s.verdict]
    accepted_near = [s for s in answered if s.candidate.fails and s.verdict]
    say("\nReveal:")
    for s in rejected_matches:
        comment = f' — your reason: "{s.comment}"' if s.comment else ""
        say(f"  - {s.candidate.ticker} {s.candidate.date.date()}: a match you rejected — the "
            f"definition fires on something you don't mean{comment}")
    for s in accepted_near:
        say(f"  - {s.candidate.ticker} {s.candidate.date.date()}: a near-miss you accepted — "
            f"it fails the spec as stated ({s.candidate.fails}); that constraint may be "
            "too strict or misplaced")
    if not rejected_matches and not accepted_near and len(answered) == len(session.shown):
        say("  Clean round: every match accepted, every near-miss rejected. A second clean "
            "round on a fresh sample and the spec is grounded.")
    elif rejected_matches or accepted_near:
        say("  Revisit the named constraints with the elicitation loop, then ground again.")


def main(argv: list[str] | None = None) -> None:
    from src.foundation.utils.config_loader import load_config
    from src.models.dataset import HOLDOUT_END
    from src.signals.moving_averages.features.panel import read_panel

    parser = argparse.ArgumentParser(prog="python -m src.llm.strategy_spec.ground")
    parser.add_argument("spec", type=Path, help="a spec JSON, or an elicitation transcript")
    parser.add_argument("--panel-dir", type=Path, default=None,
                        help="feature panel cache (default: the configured features dir)")
    parser.add_argument("--ma", default=DEFAULT_MA, choices=list(MA_COLUMNS),
                        help="which moving average to ground against (the spec has no structured slot)")
    parser.add_argument("--detector", default=None, help="finder to use (default: from the spec's `uses`)")
    parser.add_argument("--seed", type=int, default=None, help="sampling seed (recorded either way)")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD (default: the whole cached window)")
    parser.add_argument("--end", default=None, help=f"YYYY-MM-DD, at most {HOLDOUT_END.date()} (the default)")
    args = parser.parse_args(argv)

    end = args.end or str(HOLDOUT_END.date())
    check_holdout(end)
    panel_dir = args.panel_dir or (
        Path(load_config().data_paths.features) / "moving_averages" / "ma_panel")
    panel = read_panel(panel_dir, start=args.start, end=end)
    if panel.empty:
        if not any(panel_dir.glob("year=*")):
            raise SystemExit(f"no panel at {panel_dir} — run the moving_averages build-panel command first")
        raise SystemExit(f"the cached panel at {panel_dir} has no rows between "
                         f"{args.start or 'its start'} and {end} — check --start/--end")

    def ask(text: str) -> str | None:
        print(f"\n{text}")
        try:
            return input("> ")
        except EOFError:
            return None

    ground(load_spec(args.spec), panel, ask=ask, ma=args.ma, seed=args.seed, detector=args.detector)


if __name__ == "__main__":
    main()
