"""Step 3 of the strategy agent (`docs/strategy-agent/idea.md`): the elicitation loop.

One-shot extraction (step 2c) fills what the idea states; everything still open comes
back from `find_gaps`. This loop turns those gaps into a conversation: one question per
open field, the trader answers in plain language, the answer is folded into that one
field, and the gap check runs again — until the spec is complete or the trader stops.

The roles are deliberately split. The *code* decides what to ask and when to stop:
questions are built from the gaps themselves (whose reasons are already phrased as
questions), so the LLM can't steer the trader toward values they never said — its
suggestions would carry what it has read about which patterns worked. The *LLM* only
parses each answer, one field at a time: it gets the question, the answer, the current
spec and that single field's schema, under the same no-inventing rules as extraction,
and returns just that section. A bad answer (min above max, say) simply fails the next
gap check and the field is asked about again.

Answering a question about a field refreshes that field completely: the returned value
(null means the answer settled nothing, so the field is left as it was) and the
returned `unsupported` entries replace the field's old ones. That's how an unsupported
request gets resolved: the question says what isn't supported and asks whether to
restate the idea without it or drop it, and the answer comes back with the field's new
value and whichever unsupported entries survive.

Every distinct unsupported request seen in the session — found at extraction or raised
by an answer — is appended once to the development log (`unsupported.py`) when the
session ends, so the backlog counts ideas, not loop turns.

Each session's transcript (idea, questions, answers, final spec, remaining gaps) is
rewritten to `data/llm/elicitation_sessions/<timestamp>.json` in the main checkout
(git-ignored) after every turn, so a killed session keeps what it had. Real transcripts
are raw material for growing the extraction answer key.

CLI: `python -m src.llm.strategy_spec.elicit "<idea>"` (or `--file <path>`). Tests
drive the loop with scripted answers and a stubbed client; only the CLI reaches the API.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model

from src.llm.gemini import GeminiClient, ReplyError
from src.llm.paths import llm_data_dir
from src.llm.strategy_spec import extract as extraction
from src.llm.strategy_spec import catalogue
from src.llm.strategy_spec.schema import (
    Gap, SpecField, StrategySpec, UnsupportedRequest, find_gaps, request_wording)
from src.llm.strategy_spec.unsupported import log_unsupported

PURPOSE = "strategy_spec.elicit"
SESSIONS_DIR_NAME = "elicitation_sessions"
MAX_TURNS = 25  # a session that long isn't converging; stop and hand back the gaps

ANSWER_RULES = """\
The trader was asked ONE question about ONE section of their strategy spec, and \
answered in plain language. Return that section only, under the extraction rules above: \
fill in only what this answer states, null rather than guess, numbers only where given, \
and nothing from your own market knowledge. A section's `min`/`max` bound ONE quantity: \
if the answer gives thresholds for two different things (a distance and a tolerance, \
say), the numbers take the one the section is about and the others stay in the \
description as words. If the answer asks for something outside \
the capability catalogue, put it in `unsupported` (in the trader's words, with the \
section's field and a reason) and leave the value null. If the answer resolves or drops \
one of the question's listed unsupported requests, repeat that request's wording in \
`resolved_requests`; a request not named there is kept as it was. If the answer settles \
nothing (the trader is unsure, or answered something else), return value null, \
`unsupported` empty and `resolved_requests` empty.

The current spec, for context only — change nothing outside the asked section:
"""


@dataclass(frozen=True)
class Question:
    field: str
    text: str
    gaps: tuple[Gap, ...]


# One response schema per spec field: the field's own type as `value`, new unsupported
# entries for the field, and the wordings of previously listed requests this answer
# resolves. Dropping an entry takes an explicit `resolved_requests` naming — an entry the
# model merely fails to repeat is kept by the code, so an unresolved request can't vanish
# because the model forgot it. extra="forbid" like every spec section, so a stray key
# from the model is an error, not silently dropped.
_ANSWER_MODELS = {
    f: create_model(
        f"Answer_{f}",
        __config__=ConfigDict(extra="forbid"),
        value=(StrategySpec.model_fields[f].annotation | None, None),
        unsupported=(list[UnsupportedRequest], Field(default_factory=list)),
        resolved_requests=(list[str], Field(default_factory=list)),
    )
    for f in get_args(SpecField)
}


def next_question(spec: StrategySpec, skip: frozenset[str] = frozenset()) -> Question | None:
    """The first open field's gaps as one question, or None when the spec is complete
    (fields in `skip` — ones the loop gave up on — don't count). One question per field
    per turn: a field's gaps (an unsupported request plus the field standing empty, say)
    read better asked together than one at a time."""
    gaps = [g for g in find_gaps(spec) if g.field in get_args(SpecField) and g.field not in skip]
    if not gaps:
        return None
    field = gaps[0].field
    own = tuple(g for g in gaps if g.field == field)
    lines = [f"About `{field}`:"]
    for g in own:
        if g.kind == "unsupported":
            lines.append(f"- {g.reason} — this isn't supported (it's been noted for development)."
                         " Restate this part without it, or say to drop it.")
        elif g.kind == "invalid":
            lines.append(f"- as stated it can't be right: {g.reason}. What should it be?")
        else:
            lines.append(f"- {g.reason}")
    current = getattr(spec, field)
    if current not in (None, []):
        lines.append(f"(currently: {json.dumps(_shown(current), default=str)})")
    return Question(field, "\n".join(lines), own)


def _shown(value):
    """A field value as the trader should see it: models without their default noise."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_defaults=True)
    if isinstance(value, list):
        return [_shown(v) for v in value]
    return value


def apply_answer(spec: StrategySpec, question: Question, answer: str,
                 client: GeminiClient) -> StrategySpec:
    """One budgeted call parses `answer` into the asked field; returns the new spec.
    The field's value is set only if the answer settled it. The field keeps every
    unsupported entry the answer didn't explicitly resolve, plus the new ones the model
    returns; other fields are untouched."""
    others = [u for u in spec.unsupported if u.field != question.field]
    own = [u for u in spec.unsupported if u.field == question.field]
    context = spec.model_dump_json(exclude_none=True)
    prompt = f"Question:\n{question.text}\n\nThe trader's answer:\n{answer}"
    reply = client.generate(
        prompt, purpose=PURPOSE,
        system=extraction.build_system() + "\n" + ANSWER_RULES + context,
        response_schema=_ANSWER_MODELS[question.field], temperature=0.0)
    parsed = reply.parsed
    wrong_field = [u for u in parsed.unsupported if u.field != question.field]
    if wrong_field:  # the model may only speak for the asked field
        raise ReplyError(f"unsupported entries for other fields: {[u.field for u in wrong_field]}")
    # Each naming resolves the entry it best matches: the longest wording it contains.
    # That lets the model echo the question's whole displayed line ("'15-minute bars':
    # unsupported timeframe") without the naming also sweeping away a shorter unrelated
    # ask ("news" must survive "news sentiment score" being dropped). One wording filed
    # under two reasons is one ask and drops together: the trader resolves by their
    # words, not by the model's reason classification.
    wordings = {request_wording(u.requested) for u in own}
    resolved = set()
    for naming in (request_wording(r) for r in parsed.resolved_requests):
        contained = [w for w in wordings if w in naming]
        if contained:
            resolved.add(max(contained, key=len))
    kept = [u for u in own if request_wording(u.requested) not in resolved]
    # A resolved ask the model confusedly also re-returns (often as the echoed display
    # line) doesn't come back under a mangled wording.
    new = [u for u in parsed.unsupported
           if u.key() not in {k.key() for k in kept}
           and not any(r in request_wording(u.requested) for r in resolved)]
    updates: dict = {"unsupported": others + kept + new}
    if parsed.value is not None:
        updates[question.field] = parsed.value
    return spec.model_copy(update=updates)


def sessions_dir() -> Path:
    return llm_data_dir() / SESSIONS_DIR_NAME


@dataclass
class Session:
    idea: str
    spec: StrategySpec
    turns: list[dict] = dataclass_field(default_factory=list)
    # Every unsupported request seen, as is: the log's own grouping merges repeats and
    # keeps every field and detail, so nothing is deduplicated away here.
    seen: list[UnsupportedRequest] = dataclass_field(default_factory=list)

    def note_unsupported(self) -> None:
        for item in self.spec.unsupported:
            if item not in self.seen:
                self.seen.append(item)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        gaps = find_gaps(self.spec)
        path.write_text(json.dumps({
            "idea": self.idea,
            "turns": self.turns,
            "spec": json.loads(self.spec.model_dump_json(exclude_none=True)),
            "gaps_remaining": [f"{g.field}: {g.reason}" for g in gaps],
            "complete": not gaps,
        }, indent=1) + "\n")


def elicit(idea: str, client: GeminiClient | None = None, *,
           ask: Callable[[str], str | None], say: Callable[[str], None] = print,
           session_path: Path | None = None, log_path: Path | None = None,
           max_turns: int = MAX_TURNS) -> StrategySpec:
    """Extract, then ask until complete. `ask` returns the trader's answer, or None to
    stop the session; `say` reports progress. The transcript is rewritten after every
    turn, and every distinct unsupported request seen is logged once at the end."""
    client = client or GeminiClient()
    path = session_path or sessions_dir() / (
        # Microseconds, so two sessions started together can't share a transcript file.
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + ".json")
    session = Session(idea, extraction.extract(idea, client).parsed)
    skip: set[str] = set()
    stalls: dict[str, int] = {}
    answered = 0
    stopped = False

    def stalled(field: str) -> None:
        # Twice in a row without movement (an identical re-parse, or a reply refused
        # both times) means asking again won't help — the first live session burned 75k
        # tokens re-asking one size question before this guard existed.
        stalls[field] = stalls.get(field, 0) + 1
        if stalls[field] >= 2:
            skip.add(field)
            say(f"`{field}` isn't converging; skipping it — it stays an open gap.")

    try:
        session.note_unsupported()
        # `uses` came from the model, not the trader: an uncatalogued id in it is the
        # model's slip, dropped rather than asked about (a genuine ask lives in
        # `unsupported`).
        bad_ids = [u for u in dict.fromkeys(session.spec.uses) if u not in catalogue.IDS]
        if bad_ids:
            say(f"Dropped from `uses`, not in the catalogue: {', '.join(bad_ids)}")
            session.spec = session.spec.model_copy(
                update={"uses": [u for u in session.spec.uses if u in catalogue.IDS]})
        session.save(path)
        for _ in range(max_turns):
            question = next_question(session.spec, frozenset(skip))
            if question is None:
                break
            answer = ask(question.text)
            if answer is None or not answer.strip():
                stopped = True
                say("Stopping here; the open questions are kept in the transcript.")
                break
            try:
                session.spec = apply_answer(session.spec, question, answer, client)
            except ReplyError as e:
                say(f"That answer couldn't be read into the spec ({e}); asking again.")
                session.turns.append({"field": question.field, "question": question.text,
                                      "answer": answer, "error": str(e)})
                session.save(path)
                stalled(question.field)
                continue
            answered += 1
            session.note_unsupported()
            session.turns.append({"field": question.field, "question": question.text, "answer": answer})
            session.save(path)
            after = next_question(session.spec, frozenset(skip))
            if after is not None and after.field == question.field and after.gaps == question.gaps:
                stalled(question.field)
            else:
                stalls.pop(question.field, None)
        remaining = find_gaps(session.spec)
        if not remaining:
            say("The spec is complete.")
        elif stopped:
            pass  # the stop already said it; the transcript carries the open questions
        elif next_question(session.spec, frozenset(skip)) is not None:
            say(f"Stopping after {answered} answer{'s' if answered != 1 else ''}; "
                "the open questions are kept in the transcript.")
        else:
            say("Done with the questions; still open: "
                + "; ".join(f"{g.field}: {g.reason}" for g in remaining))
    finally:
        try:
            session.save(path)
        finally:  # the pointer, then the log line, survive even a failing save
            say(f"Transcript: {path}")
            if session.seen:
                logged = StrategySpec(name=session.spec.name, unsupported=list(session.seen))
                log_unsupported(logged, idea=idea, path=log_path)
    return session.spec


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.strategy_spec.elicit")
    parser.add_argument("idea", nargs="?", help="the trading idea, in plain language")
    parser.add_argument("--file", type=Path, help="read the idea from a file instead")
    args = parser.parse_args(argv)
    if (args.idea is None) == (args.file is None):
        parser.error("give the idea as an argument or with --file, not both")
    idea = (args.file.read_text() if args.file else args.idea).strip()
    if not idea:
        parser.error("the idea is empty")

    def ask(text: str) -> str | None:
        print(f"\n{text}")
        try:
            return input("> ")
        except EOFError:
            return None

    spec = elicit(idea, ask=ask)
    print(spec.model_dump_json(exclude_none=True, indent=1))


if __name__ == "__main__":
    main()
