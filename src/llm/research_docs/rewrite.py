"""Step 7f of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
search a question in several wordings, so a passage worded differently from the
question can still be found.

Keyword search matches words, and the embedding matches meaning only so far: when the
asker says one word and the doc another, the answering chunk can miss hybrid search's top
`rerank.DEPTH`, and the re-ranker can only reorder what it is given (`docs/done.md` #161:
three multi-part misses that splitting couldn't fix were of this kind).

1. **Rewordings.** One Gemini call (`SYSTEM`, about 290 tokens on the dev questions) writes `N_REWRITES`
   other wordings of the question, using other terms for its key words and keeping every
   name, id and number. Every question gets the call: no rule on the text alone can tell
   which questions are worded unlike their answer.
2. **A wider pool** (`pool`): hybrid search's top `DEPTH` for the question and for each
   rewording, joined (the question's first, a repeated chunk kept once).
3. **One judge** (`pooled_search`): the re-ranker scores the whole pool against the
   *original* question and keeps the `k` best. The rewordings ask the same question, so
   they only add candidates; which candidate answers is still decided by the best
   relevance judge here, against what the asker wrote. A chunk the original question
   found is still in the pool, but can be out-scored by a new candidate.

The re-ranker scores up to (1 + `N_REWRITES`) x `DEPTH` pairs instead of `DEPTH`, so a
question costs up to four times the re-ranking time. Rewordings are cached like splits
(`cached.ReplyCache`; the eval's is `REWRITES`, committed).

    python -m src.llm.research_docs.rewrite "How big is each trade?"
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from pydantic import BaseModel, ConfigDict

from src.llm.gemini import DEFAULT_MODEL, Budget, GeminiClient
from src.llm.research_docs import cached
from src.llm.research_docs.cached import ReplyCache
from src.llm.research_docs.keyword import KeywordIndex, hybrid_search
from src.llm.research_docs.rerank import DEPTH, Scorer, rerank
from src.llm.research_docs.retrieve import TOP_K

PURPOSE = "research_docs.rewrite"
BUDGET = Budget(max_input_tokens=2_000, max_output_tokens=400)
N_REWRITES = 3
REWRITES = Path(__file__).with_name("judged") / "rewrites.json"  # the eval's cache, committed

SYSTEM = f"""\
You help search one trading-research project's docs: design docs, pre-registrations,
result logs and a log of finished work. The search matches words and meaning, so a
question worded differently from the passage that answers it can miss it.

Write {N_REWRITES} other wordings of the question, each a question or search phrase that a
passage answering it might use:
- Use other words for its key terms: the technical name a quant researcher or trader
  would write, a common synonym, or a longer or shorter form. "How big is each trade?"
  could become "position sizing rule", "how much capital is allocated per position" and
  "risk per trade".
- Keep every name, id, number and code in the question exactly as written.
- Ask the same thing: don't narrow it, widen it into another question, or add facts or
  guesses about the answer.
- Each wording should differ from the question and from the others in its words, not
  only in their order.
"""


class Rewrites(BaseModel):
    """The model's structured reply."""
    model_config = ConfigDict(extra="forbid")
    rewrites: list[str]


def prompt_id(model: str = DEFAULT_MODEL) -> str:
    """Which instructions made the rewordings: the system prompt (with `N_REWRITES` in
    it), the reply schema and the model."""
    return cached.prompt_id(SYSTEM, Rewrites, model)


def clean(question: str, rewrites: Sequence[str]) -> list[str]:
    """The model's rewordings, stripped, without blanks, repeats or the question itself
    (compared with whitespace collapsed and case and a trailing "?" ignored), at most
    `N_REWRITES`."""
    def key(text: str) -> str:
        return " ".join(text.split()).lower().rstrip("?").rstrip()

    out: list[str] = []
    for r in (" ".join(r.split()) for r in rewrites):
        if r and key(r) not in {key(question), *map(key, out)}:
            out.append(r)
    return out[:N_REWRITES]


class Rewriter:
    """`rewriter(question)` -> its rewordings (not the question itself), made once per
    question and kept in `cache` (`cached.ReplyCache`, which has the details)."""

    def __init__(self, client: Callable[[], GeminiClient], cache: Path | None = None, model: str = DEFAULT_MODEL):
        self.replies = ReplyCache(client, cache, prompt_id(model), model)

    def __call__(self, question: str) -> list[str]:
        return self.replies.fetch(question, "rewrites", clean, purpose=PURPOSE, system=SYSTEM, schema=Rewrites)


def pool(index: VectorStoreIndex, keywords: KeywordIndex, queries: Sequence[str],
         depth: int = DEPTH) -> list[NodeWithScore]:
    """Hybrid search's top `depth` for each query, joined in order, each chunk once."""
    out, seen = [], set()
    for q in queries:
        for h in hybrid_search(index, keywords, q, depth):
            if h.node.node_id not in seen:
                seen.add(h.node.node_id)
                out.append(h)
    return out


def pooled_search(index: VectorStoreIndex, keywords: KeywordIndex, score: Scorer,
                  rewriter: Callable[[str], list[str]], question: str, k: int = TOP_K,
                  depth: int = DEPTH) -> list[NodeWithScore]:
    """The pool of the question and its rewordings, re-ranked against the question; the
    `k` best, best first."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    return rerank(score, question, pool(index, keywords, [question, *rewriter(question)], max(k, depth)), k)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.llm.research_docs.rewrite")
    ap.add_argument("question")
    args = ap.parse_args()
    print("\n".join(Rewriter(lambda: GeminiClient(budget=BUDGET))(args.question)))


if __name__ == "__main__":
    main()
