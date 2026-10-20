"""Step 7e of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
split a question that asks for several things into one search per thing.

A question like "what windows and horizons do we use in the analysis and the modeling?"
has an answer in several places. One search embeds and re-ranks it as a whole, and the
re-ranker's top 30 tends to fill up with one part's passages, so the other parts are
never retrieved at all: a recall problem that more sources or reordering can't fix
(`docs/done.md` #134, #160). Searching each part on its own gives each its own top 30.

1. **Is there anything to split?** A question with no joining word (and, or, vs, a
   comma, a slash, a semicolon) asks for one thing, so it is searched as it is, with no
   call (`may_have_parts`).
2. **The split.** Otherwise one small Gemini call (`SYSTEM`; about 400-500 tokens)
   rewrites it as 1-`MAX_PARTS` standalone questions, as JSON. The model decides from
   the question's text alone. When it returns one question, the *original* is searched,
   not the model's rewording, so a question judged single gets exactly the sources it
   got before.
3. **The merge** (`merge`), round-robin: each sub-question's best chunk, then each one's
   second best, and so on, skipping a chunk already taken, until `k`. Every part's best
   chunk is then in the top p (p parts). Re-ranking the union against the original
   question was the alternative, and the wrong one here: the original question's
   scores are what favoured one part's chunks in the first place. A chunk keeps the
   score its own sub-question gave it, so scores compare only within one sub-question.

Splits are cached in a JSON file (`Splitter(cache=...)`; the eval's is `SPLITS`,
committed), keyed by the question and the split prompt's id: temperature 0 isn't
repeatable, and the retrieval eval and the answer run must search the same sub-questions.

    python -m src.llm.research_docs.split "Do we use stop losses and position sizing?"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from llama_index.core.schema import NodeWithScore
from pydantic import BaseModel, ConfigDict

from src.llm.gemini import DEFAULT_MODEL, Budget, GeminiClient
from src.llm.research_docs.retrieve import TOP_K

PURPOSE = "research_docs.split"
BUDGET = Budget(max_input_tokens=2_000, max_output_tokens=400)
MAX_PARTS = 4
SPLITS = Path(__file__).with_name("judged") / "splits.json"  # the eval's split cache, committed
JOINER = re.compile(r"\b(?:and|or|vs|versus)\b|[,/;]", re.IGNORECASE)

SYSTEM = f"""\
You prepare questions for a search over one trading-research project's docs. Each search
finds the passages about one thing, so a question that asks for several things, answered
in different places, needs one search per thing.

Return the question as a list of standalone questions:
- Split when the question asks about two or more separate things that each need their own
  answer: separate topics, settings or items asked about one by one, or one question asked
  of two different places. "Do we use stop losses and position sizing?" becomes "Do we use
  stop losses?" and "Do we use position sizing?". "Is volume used in the screener and in
  the backtest?" becomes one question for the screener and one for the backtest.
- When it asks two things of each of two places, write one question per pair.
- Don't split several aspects of one thing that one passage would give together: "which
  data vendor did we pick and why", "how is the score computed and where in the code".
  Keep those as one question.
- Don't split examples that only illustrate the one thing asked about, or alternative
  names for it.
- Each question must stand on its own: repeat the subject, keep the asker's words, names
  and ids exactly, and add nothing the question doesn't say.
- At most {MAX_PARTS} questions. If the question asks for one thing, return it unchanged as the
  only item.
"""


class Split(BaseModel):
    """The model's structured reply."""
    model_config = ConfigDict(extra="forbid")
    sub_questions: list[str]


def may_have_parts(question: str) -> bool:
    """Whether the question has a joining word, the only way to ask for two things."""
    return bool(JOINER.search(question))


def prompt_id(model: str = DEFAULT_MODEL) -> str:
    """Which instructions made a split: the system prompt (with the `MAX_PARTS` cap in
    it), the reply schema and the model."""
    parts = (SYSTEM, json.dumps(Split.model_json_schema(), sort_keys=True), model)
    return hashlib.sha256("\n\x00\n".join(parts).encode()).hexdigest()[:16]


def clean(question: str, subs: Sequence[str]) -> list[str]:
    """The model's sub-questions, stripped, without blanks or repeats, at most
    `MAX_PARTS` (a warning says what was cut); the original question when fewer than two
    are left."""
    out: list[str] = []
    for s in (" ".join(s.split()) for s in subs):
        if s and s.lower() not in (o.lower() for o in out):
            out.append(s)
    if len(out) > MAX_PARTS:
        print(f"warning: split into {len(out)}, searching the first {MAX_PARTS}: {question!r}", file=sys.stderr)
    return out[:MAX_PARTS] if len(out) > 1 else [question]


class Splitter:
    """`splitter(question)` -> the questions to search: `[question]` itself, or 2 to
    `MAX_PARTS` sub-questions. `cache` (a JSON file) keeps every split made, so the same
    question always gets the same split; it's written after each new one. The cap is in
    the prompt, so changing `MAX_PARTS` changes `prompt_id` and every split is made again;
    a change to `clean` needs a new cache. `client` makes the `GeminiClient` for `model`
    (the cache's key), called on the first question not in the cache, so a fully cached
    run needs no API key."""

    def __init__(self, client: Callable[[], GeminiClient], cache: Path | None = None, model: str = DEFAULT_MODEL):
        self.make_client, self.client, self.cache, self.model = client, None, cache, model
        self.pid = prompt_id(model)
        self.known: dict[str, dict] = json.loads(cache.read_text()) if cache and cache.exists() else {}

    def __call__(self, question: str) -> list[str]:
        if not may_have_parts(question):
            return [question]
        hit = self.known.get(question)
        if hit and hit["prompt"] == self.pid:
            return hit["sub_questions"]
        if self.client is None:
            client = self.make_client()
            if getattr(client, "model", self.model) != self.model:  # its splits would be cached under `model`
                raise ValueError(f"the client runs {client.model}, the cache is keyed by {self.model}")
            self.client = client
        reply = self.client.generate(question, purpose=PURPOSE, system=SYSTEM, response_schema=Split,
                                     temperature=0.0)
        subs = clean(question, reply.parsed.sub_questions)
        self.known[question] = {"prompt": self.pid, "sub_questions": subs}
        if self.cache:
            tmp = self.cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.known, indent=1, ensure_ascii=False))
            os.replace(tmp, self.cache)
        return subs


def merge(results: Sequence[Sequence[NodeWithScore]], k: int) -> list[NodeWithScore]:
    """Round-robin over the result lists, best first, skipping chunks already taken."""
    out: list[NodeWithScore] = []
    seen: set[str] = set()
    for rank in range(max(map(len, results), default=0)):
        for hits in results:
            if rank < len(hits) and hits[rank].node.node_id not in seen:
                seen.add(hits[rank].node.node_id)
                out.append(hits[rank])
                if len(out) == k:
                    return out
    return out


def split_search(find: Callable[[str, int], list[NodeWithScore]], splitter: Callable[[str], list[str]],
                 question: str, k: int = TOP_K) -> list[NodeWithScore]:
    """`find` (the re-ranker in practice) once per sub-question, `k` each, merged to `k`.
    A question that isn't split is one plain `find` call."""
    subs = splitter(question)
    if len(subs) == 1:
        return find(subs[0], k)
    return merge([find(s, k) for s in subs], k)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.llm.research_docs.split")
    ap.add_argument("question")
    args = ap.parse_args()
    subs = Splitter(lambda: GeminiClient(budget=BUDGET))(args.question)
    print("\n".join(subs) if len(subs) > 1 else f"(one question, searched as it is)\n{subs[0]}")


if __name__ == "__main__":
    main()
