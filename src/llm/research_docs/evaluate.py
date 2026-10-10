"""Step 5 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
measure retrieval on a fixed set of questions with known answers, so step 7's changes
(keyword search, re-ranking, deduplication) can be judged by a number instead of by
eyeballing a couple of queries.

The question set (`eval_questions.json`, next to this file and deliberately outside
`docs/`: inside it, the answer key would be indexed and retrieved too) gives each question
one or more **gold** sources. A gold is a file path plus, optionally, what pins the
passage down: `contains` (a phrase the chunk's text must include, whitespace- and
case-insensitive), or a metadata value (`entry`, `cell_id`, `experiment_id`) that every
chunk of that done.md entry or CSV row carries. A retrieved chunk that matches any gold is
a hit; a question's **rank** is the position of its first hit.

Metrics, over all questions and per question type:

- **hit@k**: share of questions with a hit in the top k. hit@1 asks "is the best chunk
  right?"; hit@5 asks "would an LLM shown the top 5 have the answer in front of it?",
  which is what step 6 needs.
- **MRR** (mean reciprocal rank): the average of 1/rank (0 if no hit in the top 10,
  the deepest `KS` cut).
  One number that rewards ranking the answer higher, not only finding it.

With ~20 questions, one question moves hit@k by ~5 points: compare configurations on the
per-question table, not on a 1-point difference.

The questions were written from the docs before any retrieval run, the way they'd be
asked, mostly in different words from the passage. Questions copied from a passage's own
wording would overrate an embedding model (and overrate keyword search more).

    python -m src.llm.research_docs.evaluate           # run all questions against the index
    python -m src.llm.research_docs.evaluate --check   # every gold still matches a chunk? (no model)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode, MetadataMode

from src.llm.research_docs.retrieve import cite, search

QUESTIONS = Path(__file__).with_name("eval_questions.json")
KS = (1, 3, 5, 10)


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def matches(node: BaseNode, gold: dict) -> bool:
    m = node.metadata
    for key, want in gold.items():
        if key == "contains":
            if _norm(want) not in _norm(node.get_content()):
                return False
        elif key == "entry":  # a combined done.md entry "#16, #17" matches either number
            have = m.get("entry", "")
            if want != have and want not in have.split(", "):
                return False
        elif m.get(key) != want:
            return False
    return True


def first_hit(nodes: list[BaseNode], golds: list[dict]) -> int | None:
    """1-based rank of the first node matching any gold, None if none does."""
    for rank, n in enumerate(nodes, 1):
        if any(matches(n, g) for g in golds):
            return rank
    return None


def stale_paths(indexed: list[BaseNode], current: list[BaseNode]) -> list[str]:
    """Files whose chunks (text and metadata) in the index differ from chunking the docs
    now: a doc edited, added or deleted since the build, or a change to the chunking."""
    def by_path(nodes):
        out: dict[str, list[tuple]] = {}
        for n in nodes:  # embedded rendering (catches embed-key changes) + all metadata
            out.setdefault(n.metadata["path"], []).append(
                (n.get_content(MetadataMode.EMBED), sorted(n.metadata.items())))
        return {p: sorted(chunks) for p, chunks in out.items()}
    old, new = by_path(indexed), by_path(current)
    return sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))


def check_golds(questions: list[dict], nodes: list[BaseNode]) -> list[str]:
    """Golds that match no chunk: a doc was edited or re-chunked under the question."""
    return [f"{q['id']}: {g}" for q in questions for g in q["gold"]
            if not any(matches(n, g) for n in nodes)]


def unmatched_golds(questions: list[dict], indexed: list[BaseNode],
                    current: list[BaseNode]) -> list[str]:
    """Golds no indexed chunk matches, each labelled with its fix: a gold the current docs
    do match needs an index rebuild; one they don't match is wrong as written."""
    out = []
    for q in questions:
        for g in q["gold"]:
            if not any(matches(n, g) for n in indexed):
                fix = "rebuild the index" if any(matches(n, g) for n in current) else "fix the gold"
                out.append(f"{q['id']}: {g}  ({fix})")
    return out


def evaluate(index: VectorStoreIndex, questions: list[dict]) -> list[dict]:
    """Each question's rank of first hit in the top `max(KS)` and its top chunk."""
    rows = []
    for q in questions:
        hits = search(index, q["question"], max(KS))
        rows.append({**q, "rank": first_hit([h.node for h in hits], q["gold"]),
                     "top": cite(hits[0].node) if hits else "-"})
    return rows


def scores(rows: list[dict]) -> dict[str, float]:
    ranks = [r["rank"] for r in rows]
    out = {f"hit@{k}": statistics.mean(r is not None and r <= k for r in ranks) for k in KS}
    out["MRR"] = statistics.mean(1 / r if r else 0 for r in ranks)
    return out


def _stale_summary(stale: Sequence[str]) -> str:
    return f"{len(stale)} file(s) differ from the index ({', '.join(stale[:3])}{', …' if len(stale) > 3 else ''})"


def report(rows: list[dict], stale: Sequence[str] = ()) -> str:
    """The per-question table and the scores, headed by a STALE line when the index
    no longer matches the docs (`stale_paths`), so a saved copy carries the flag."""
    lines = []
    if stale:
        lines += [f"STALE INDEX: {_stale_summary(stale)}; rebuild for current numbers", ""]
    lines.append(f"{'question':<22} {'type':<8} {'style':<6} {'rank':>4}  top hit")
    for r in rows:
        rank = str(r["rank"]) if r["rank"] else "-"
        lines.append(f"{r['id']:<22} {r['type']:<8} {r['style']:<6} {rank:>4}  {r['top'][:70]}")
    groups = {"all": rows}
    for key in ("type", "style"):
        for value in sorted({r[key] for r in rows}):
            groups[f"{key}={value}"] = [r for r in rows if r[key] == value]
    lines += ["", f"{'':<14} {'n':>3}" + "".join(f"{name:>8}" for name in scores(rows))]
    for name, group in groups.items():
        s = scores(group)
        lines.append(f"{name:<14} {len(group):>3}" + "".join(f"{v:>8.2f}" for v in s.values()))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only check golds against the chunks")
    args = ap.parse_args()
    questions = load_questions()
    from src.llm.research_docs.chunk import chunk_documents
    from src.llm.research_docs.load import load_documents
    if args.check:
        problems = check_golds(questions, chunk_documents(load_documents()))
        print("\n".join(problems) or f"all {len(questions)} questions' golds match a chunk")
        raise SystemExit(1 if problems else 0)
    from src.llm.research_docs.index import embed_model, load_index
    index = load_index(embed_model())  # first, so a missing index fails before re-chunking
    current = chunk_documents(load_documents())
    indexed = list(index.docstore.docs.values())
    # The index is rebuilt by hand. A gold no indexed chunk matches would score as a
    # retrieval miss, so refuse to score. Other drift since the build is flagged in the
    # report itself, so a saved copy can't pass for current numbers.
    stale = stale_paths(indexed, current)
    # A question none of whose golds the index can match would score as a miss: refuse.
    # One with only some golds unmatched still scores, with a warning.
    unmatched = unmatched_golds(questions, indexed, current)
    if unmatched:
        dead = [q["id"] for q in questions
                if q["gold"] and not any(matches(n, g) for g in q["gold"] for n in indexed)]
        head = f"golds that match no indexed chunk ({_stale_summary(stale) if stale else 'index current'}):"
        print(head, *unmatched, sep="\n  ", file=sys.stderr)
        if dead:
            print(f"not scoring: no gold of {', '.join(dead)} matches the index", file=sys.stderr)
            raise SystemExit(1)
    print(report(evaluate(index, questions), stale))


if __name__ == "__main__":
    main()
