"""Step 6 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
an LLM writes the answer, from the retrieved chunks only, citing them.

Steps 1-5 and 7 are the "R" of RAG, retrieval-augmented generation: they find the chunks.
This is the "G": the question and the re-ranker's top 5 (`rerank.rerank_search`) go to
Gemini (`src/llm/gemini.py`, with its token budget), numbered [1]-[5], and the model is told
to answer from those sources alone.

- **Grounding.** The model knows a lot about trading in general, and that's the danger: a
  fluent answer from general knowledge looks the same as one from this project's docs. So
  the instructions forbid outside knowledge, and every factual sentence has to cite the
  source it came from as [n]. A citation makes a claim checkable: open source n and see.
- **Saying "not in the docs".** Step 7 showed that no score cutoff separates questions
  the docs answer from ones they don't (`docs/done.md` #139): retrieval always returns 5
  chunks, related or not. Reading the chunks is what can tell, so the reply is structured
  (`Answer`): `in_docs` is the model's verdict, `answer` the text. When the sources don't
  answer, it says so and what they do cover, instead of stretching them. Silence isn't an
  answer either: "it wasn't tested", concluded from sources that don't mention it, was
  one of the baseline's misses (step 6c, `docs/done.md` #152).
- **Keeping the verdict.** A number without the verdict that qualifies it (weak, not
  robust, fails costs) reads as a finding. The baseline kept the numbers and dropped the
  verdict twice, so the prompt says the verdict belongs next to the number.
- **What's checked here, and what isn't.** `check` is mechanical: every [n] must name one
  of the sources shown, and in an answer that claims to be in the docs, every sentence must
  cite something. (A "not in the docs" reply may open with an uncited "the sources don't
  say", so its sentences aren't checked.)
  Whether source n actually *supports* the sentence citing it, and whether the answer is
  right, takes a judge reading both: that's the evaluation step, not this one.

Temperature 0 (more repeatable, not deterministic) and thinking off, as in the strategy
agent. A call is about 3,000 tokens in (5 chunks of at most 384 tokens plus their
headings and the instructions) and a few hundred out.

    python -m src.llm.research_docs.answer "Why were baselines B1 and B5 dropped?"
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from llama_index.core.schema import BaseNode, MetadataMode, NodeWithScore
from pydantic import BaseModel, ConfigDict

from src.llm.gemini import Budget, GeminiClient, Usage
from src.llm.research_docs.retrieve import TOP_K, cite

PURPOSE = "research_docs.answer"
BUDGET = Budget(max_input_tokens=8_000, max_output_tokens=2_000)
MAX_K = 10  # the most sources one answer is given: 10 chunks still fit under BUDGET's input cap

SYSTEM = """\
You answer questions about one trading-research project, using only the numbered sources
given with the question: excerpts from the project's own docs.

Rules:
- Use only the sources. Don't add anything from general knowledge, even when you are sure
  it is true: a reader can't tell it apart from what the project actually decided.
- End every sentence that states a fact with the source(s) it comes from: [2], or [1][4].
  Use only the numbers given.
- Set in_docs to true only when a source, or several read together, answers the question
  itself. A source on a neighbouring topic doesn't count, and neither does silence: that no
  source mentions something doesn't mean the project didn't do it. If you can't cite a
  source for the sentence that answers the question, the sources don't answer it.
- If the sources answer the question, set in_docs to true and answer it directly and
  briefly: the answer first, then the reasons or numbers that support it. If they answer
  only part of it, answer that part and say which part they don't cover.
- Keep a result's verdict with its number. When a source qualifies a result (weak, not
  robust, inconclusive, exploratory, fails costs, misses the multiple-testing bar, a tier),
  that is part of the answer: say it next to the number, and let it shape your first
  sentence ("weakly, and it isn't confirmed" rather than a flat "yes").
- If the sources don't answer the question, set in_docs to false. Say so in one sentence,
  then say in one more sentence what the sources do cover, with citations. Don't stretch
  a related source into an answer.
- Quote names, numbers and ids exactly as the sources write them.
"""


class Answer(BaseModel):
    """The model's structured reply."""
    model_config = ConfigDict(extra="forbid")
    in_docs: bool
    answer: str


@dataclass(frozen=True)
class Answered:
    question: str
    answer: Answer
    sources: list[NodeWithScore]
    problems: list[str]  # from `check`
    usage: Usage


def source_text(node: BaseNode) -> str:
    """A source's text as the model is shown it."""
    return node.get_content(metadata_mode=MetadataMode.EMBED).strip()


def build_prompt(question: str, sources: Sequence[NodeWithScore]) -> str:
    """The question, then each source as `[n] where it's from` and its text. The text is
    what the embedding model and re-ranker saw: an experiment row's `tier` and `outcome`
    live in its metadata (`chunk.ROW_ID_COLUMNS`), not its plain text."""
    blocks = [f"[{n}] {cite(h.node)}\n{source_text(h.node)}" for n, h in enumerate(sources, 1)]
    return f"Question: {question}\n\nSources:\n\n" + "\n\n".join(blocks)


def cited(text: str) -> list[int]:
    """Source numbers cited in `text`, in order of first appearance: [2], [1][4], [1, 3],
    [1-3]."""
    out: list[int] = []
    item = r"\d+(?:\s*[-\u2013]\s*\d+)?"
    for group in re.findall(rf"\[({item}(?:\s*,\s*{item})*)\]", text):
        for part in group.split(","):
            lo, _, hi = re.sub(r"\s", "", part).replace("\u2013", "-").partition("-")
            lo, hi = sorted((int(lo), int(hi or lo)))
            # a short span is a citation range; a long one ([2010-2021]) keeps just its ends
            for n in range(lo, hi + 1) if hi - lo < MAX_K else (lo, hi):
                if n not in out:
                    out.append(n)
    return out


LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
SENTENCE_END = re.compile(  # a stop, maybe a closing quote, then space; not after an abbreviation
    r"(?<!e\.g\.)(?<!i\.e\.)(?<!vs\.)(?<!etc\.)(?<!cf\.)(?<=[.!?])\s+(?=[^a-z])|(?<=[.!?][\"')])\s+(?=[^a-z])")


def sentences(text: str) -> list[str]:
    """`text` split into sentences: every line (a list item, say) on its own, then at full
    stops. Citations written after a stop ("Fact. [1]", '"locked." [1]') are moved in front
    of it so they stay with their sentence. List markers are dropped, and so are pieces that
    state nothing: no letters, or a lead-in ending in a colon ("Findings:"). Bold markers
    (**) are dropped, and a line of citations alone joins the line before it."""
    text = re.sub(r"\s*\n(?=\s*(?:\[[^\]]*\]\s*)+(?:\n|$))", " ", text.replace("**", ""))
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"([.!?][\"')]*)((?:\s*\[[^\]]*\])+)", r"\2\1", LIST_MARKER.sub("", line).strip())
        out += [s for s in SENTENCE_END.split(line) if re.search(r"[A-Za-z]", s) and not s.endswith(":")]
    return out


def check(answer: Answer, n_sources: int) -> list[str]:
    """Mechanical problems with the citations: numbers that name no source, and, in an
    in-docs answer, a sentence without a citation (or no citation at all)."""
    nums = cited(answer.answer)
    problems = [f"cites [{n}], but only [1]-[{n_sources}] were given" for n in nums if not 1 <= n <= n_sources]
    if answer.in_docs and not nums:
        problems.append("says the docs answer it but cites no source")
    elif answer.in_docs:
        problems += [f"sentence {i} cites no source: {s!r}"
                     for i, s in enumerate(sentences(answer.answer), 1) if not cited(s)]
    return problems


def answer(question: str, find: Callable[[str, int], list[NodeWithScore]],
           client: GeminiClient, k: int = TOP_K) -> Answered:
    """Retrieve `k` sources with `find` (the re-ranker in practice), then ask the model."""
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be 1-{MAX_K}, got {k}")
    sources = find(question, k)
    if not sources:
        raise ValueError("retrieval returned no chunks")
    reply = client.generate(build_prompt(question, sources), purpose=PURPOSE, system=SYSTEM,
                            response_schema=Answer, temperature=0.0)
    return Answered(question, reply.parsed, list(sources), check(reply.parsed, len(sources)), reply.usage)


def format_answered(a: Answered) -> str:
    verdict = "" if a.answer.in_docs else "(not in the docs)\n"
    lines = [verdict + a.answer.answer, "", "Sources:"]
    used = set(cited(a.answer.answer))
    for n, h in enumerate(a.sources, 1):
        lines.append(f"  [{n}]{'*' if n in used else ' '} {cite(h.node)}")
    lines.append("  (* cited)")
    lines += [f"CITATION PROBLEM: {p}" for p in a.problems]
    lines.append(f"tokens: {a.usage.prompt_tokens} in, {a.usage.output_tokens} out")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.llm.research_docs.answer")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=TOP_K, help=f"sources given to the model (default {TOP_K}, at most {MAX_K})")
    args = ap.parse_args()
    if not 1 <= args.k <= MAX_K:
        ap.error(f"-k must be 1-{MAX_K}")
    from src.llm.research_docs.index import embed_model, load_index
    from src.llm.research_docs.keyword import KeywordIndex
    from src.llm.research_docs.rerank import cross_encoder, rerank_search
    index = load_index(embed_model())
    keywords = KeywordIndex(list(index.docstore.docs.values()))
    score = cross_encoder()
    find = lambda q, k: rerank_search(index, keywords, score, q, k)  # noqa: E731
    print(format_answered(answer(args.question, find, GeminiClient(budget=BUDGET), args.k)))


if __name__ == "__main__":
    main()
