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

A question whose answer has several pieces (say, the lookback windows *and* the horizons)
lists `parts` instead of `gold`: one gold list per piece, each a set of alternatives as
above. Its rank is the position by which every part has been hit, so hit@5 means the full
answer is in the top 5. The report scores the multi-part questions on their own twice, on
the full answer and on the first part found: the gap is what they lose to partial retrieval.

Some questions are **unanswerable** (`"answerable": false`, `"gold": []`): the docs don't
cover them. They have no rank and stay out of hit@k and MRR; they're there for step 6, where
the LLM should say "not in the docs" instead of answering from the nearest chunk. The report
shows every question's top similarity score and the range for each kind: if unanswerable
questions score as high as answerable ones, a score cutoff alone can't tell them apart.

Metrics, over the answerable questions and per question type:

- **hit@k**: share of questions with a hit in the top k. hit@1 asks "is the best chunk
  right?"; hit@5 asks "would an LLM shown the top 5 have the answer in front of it?",
  which is what step 6 needs.
- **MRR** (mean reciprocal rank): the average of 1/rank (0 if no hit in the top 10,
  the deepest `KS` cut).
  One number that rewards ranking the answer higher, not only finding it.

16 questions are held out as a final **test** split (`"split": "test"`: 2 entry, 2 row,
9 section, 2 status and 1 unanswerable, drawn after `random.seed(20261011)` by
`random.sample(sorted(ids), n)` per type, in that order). Day-to-day runs score only the **dev** split (43): tuning
step 7 on the questions it is judged on would overfit them. Run `--split test` once, at
the end.

With ~40 answerable dev questions, one question moves hit@k by ~2.5 points: compare
configurations on the per-question table, not on a 1-point difference.

The questions were written before any retrieval run, the way they'd be asked, mostly in
different words from the passage (questions copied from a passage's own wording would
overrate an embedding model, and keyword search more): 22 from the docs, 20 more covering
rows, ids, status and out-of-scope questions, 10 by an agent shown only the doc file
names, and 7 by the user. The golds were then completed by **pooling**: every chunk in
the top 5 of vector search or of BM25 keyword search was judged once, and 25 that answer
were added. Golds are only as complete as the pool, which favours those two searches: a
step-7 method that surfaces chunks nobody judged (a re-ranker, deduplication) would score
a correct unjudged chunk as a miss. So before comparing a new method, judge its top 5's
unjudged chunks, on both splits, and add the ones that answer.

    python -m src.llm.research_docs.evaluate           # run the dev questions against the index
    python -m src.llm.research_docs.evaluate --split test   # the held-out questions, once
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
METRICS = (*(f"hit@{k}" for k in KS), "MRR")


def answerable(q: dict) -> bool:
    a = q.get("answerable", True)
    if not isinstance(a, bool):  # "false" as a string would read as true
        raise ValueError(f"{q.get('id')}: answerable must be true or false, not {a!r}")
    return a


def parts(q: dict) -> list[list[dict]]:
    """The question's answer as a list of parts, each a list of alternative golds."""
    return q["parts"] if "parts" in q else [q["gold"]] if q.get("gold") else []


def question_split(q: dict) -> str:
    return q.get("split", "dev")


def _golds_ok(golds) -> bool:
    return isinstance(golds, list) and all(isinstance(g, dict) and g.get("path") for g in golds)


def _shape_ok(q: dict) -> bool:
    if "parts" in q:  # multi-part: answerable, no `gold` beside it, every part non-empty
        ps = q["parts"]
        return ("gold" not in q and answerable(q) and isinstance(ps, list) and len(ps) > 1
                and all(_golds_ok(p) and p for p in ps))
    return _golds_ok(q.get("gold")) and bool(q["gold"]) == answerable(q)


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    questions = json.loads(path.read_text(encoding="utf-8"))
    # No gold would score as a silent miss; a gold without a path ({} matches every chunk)
    # as a silent hit. An unanswerable question has no gold, and a gold on one is a typo.
    # A multi-part question's `parts` follow the same rules per part.
    bad = [q["id"] for q in questions if not _shape_ok(q) or question_split(q) not in ("dev", "test")]
    if bad:
        raise ValueError("questions whose gold doesn't fit: none on an answerable question, "
                         "some on an unanswerable one, a gold without a path, `parts` that aren't two or "
                         f"more non-empty gold lists, or a split other than dev/test: {', '.join(bad)}")
    return questions


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


def part_ranks(nodes: list[BaseNode], q: dict) -> tuple[int | None, int | None]:
    """(full, any): the rank by which every part has been hit (None if one never is),
    and the rank of the first part hit. The same number for a one-part question."""
    ranks = [first_hit(nodes, p) for p in parts(q)]
    found = [r for r in ranks if r is not None]
    return (max(ranks) if ranks and len(found) == len(ranks) else None,
            min(found) if found else None)


def stale_paths(indexed: list[BaseNode], current: list[BaseNode]) -> list[str]:
    """Files whose chunks (text and metadata) in the index differ from chunking the docs
    now: a doc edited, added or deleted since the build, or a change to the chunking."""
    def by_path(nodes):
        out: dict[str, list[tuple]] = {}
        for n in nodes:  # embedded rendering (catches embed-key changes) + all metadata
            out.setdefault(n.metadata["path"], []).append(
                (n.get_content(MetadataMode.EMBED), sorted((k, str(v)) for k, v in n.metadata.items())))
        return {p: sorted(chunks) for p, chunks in out.items()}
    old, new = by_path(indexed), by_path(current)
    return sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))


def check_golds(questions: list[dict], nodes: list[BaseNode]) -> list[str]:
    """Golds that match no chunk (a doc was edited or re-chunked under the question), and
    chunks that satisfy two parts of one question (its full answer would then be one chunk)."""
    problems = [f"{q['id']}: {g}" for q in questions for p in parts(q) for g in p
                if not any(matches(n, g) for n in nodes)]
    for q in questions:
        for n in nodes if len(parts(q)) > 1 else ():
            hit = [i for i, p in enumerate(parts(q), 1) if any(matches(n, g) for g in p)]
            if len(hit) > 1:
                problems.append(f"{q['id']}: one chunk satisfies parts {hit} ({cite(n)})")
    return problems


def unmatched_golds(questions: list[dict], indexed: list[BaseNode],
                    current: list[BaseNode]) -> list[str]:
    """Golds no indexed chunk matches, each labelled with its fix: a gold the current docs
    do match needs an index rebuild; one they don't match is wrong as written."""
    out = []
    for q in questions:
        for g in (g for p in parts(q) for g in p):
            if not any(matches(n, g) for n in indexed):
                fix = "rebuild the index" if any(matches(n, g) for n in current) else "fix the gold"
                out.append(f"{q['id']}: {g}  ({fix})")
    return out


def evaluate(index: VectorStoreIndex, questions: list[dict]) -> list[dict]:
    """Each question's rank in the top `max(KS)` (`part_ranks`: full answer, and first part
    found), its top chunk and that chunk's similarity score."""
    rows = []
    for q in questions:
        hits = search(index, q["question"], max(KS))
        rank, rank_any = part_ranks([h.node for h in hits], q)
        rows.append({**q, "rank": rank, "rank_any": rank_any,
                     "top": cite(hits[0].node) if hits else "-",
                     "score": hits[0].score if hits else None})
    return rows


def scores(rows: list[dict], key: str = "rank") -> dict[str, float]:
    """hit@k and MRR over the answerable rows (an unanswerable one has no rank to score),
    on the full-answer `rank` or, with key="rank_any", the first part found."""
    ranks = [r[key] for r in rows if answerable(r)]
    if not ranks:
        raise ValueError("no answerable questions to score")
    out = {f"hit@{k}": statistics.mean(r is not None and r <= k for r in ranks) for k in KS}
    out["MRR"] = statistics.mean(1 / r if r else 0 for r in ranks)
    return out


def _rank(rank: int | None) -> str:
    return str(rank) if rank else "-"


def _stale_summary(stale: Sequence[str]) -> str:
    return f"{len(stale)} file(s) differ from the index ({', '.join(stale[:3])}{', …' if len(stale) > 3 else ''})"


def report(rows: list[dict], stale: Sequence[str] = (), split: str | None = None) -> str:
    """The per-question table and the scores, headed by the split scored and by a STALE
    line when the index no longer matches the docs (`stale_paths`), so a saved copy
    carries both."""
    lines = [f"split: {split}", ""] if split else []
    if stale:
        lines += [f"STALE INDEX: {_stale_summary(stale)}; rebuild for current numbers", ""]
    lines.append(f"{'question':<22} {'type':<8} {'style':<6} {'rank':>5} {'score':>5}  top hit")
    for r in rows:
        rank = "n/a" if not answerable(r) else _rank(r["rank"])
        if len(parts(r)) > 1:  # full/any part
            rank = f"{rank}/{_rank(r['rank_any'])}"
        score = f"{r['score']:.2f}" if r["score"] is not None else "-"
        lines.append(f"{r['id']:<22} {r['type']:<8} {r['style']:<6} {rank:>5} {score:>5}  {r['top'][:70]}")
    scored = [r for r in rows if answerable(r)]
    groups = {"all": scored}
    for key in ("type", "style"):
        for value in sorted({r[key] for r in scored}):
            groups[f"{key}={value}"] = [r for r in scored if r[key] == value]
    if scored:
        lines += ["", f"{'':<14} {'n':>3}" + "".join(f"{name:>8}" for name in METRICS)]
        for name, group in groups.items():
            lines.append(f"{name:<14} {len(group):>3}" + "".join(f"{v:>8.2f}" for v in scores(group).values()))
        if multi := [r for r in scored if len(parts(r)) > 1]:
            lines.append("of which, multi-part (full answer, then first part found):")
            for name, key in (("multi-part", "rank"), ("  any part", "rank_any")):
                lines.append(f"{name:<14} {len(multi):>3}"
                             + "".join(f"{v:>8.2f}" for v in scores(multi, key).values()))
    else:
        lines += ["", "no answerable questions to score"]
    if unscored := len(rows) - len(scored):
        lines.append(f"(+{unscored} unanswerable, not scored)")
    ranges = []
    for kind, keep in (("answerable", True), ("unanswerable", False)):
        top = [r["score"] for r in rows if answerable(r) == keep and r["score"] is not None]
        if top:
            ranges.append(f"{kind} {min(top):.2f}-{max(top):.2f}")
    if len(ranges) == 2:
        lines.append(f"top score range: {', '.join(ranges)}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only check golds against the chunks (all splits)")
    ap.add_argument("--split", choices=("dev", "test"), default="dev",
                    help="which questions to score (default dev; test is the held-out set)")
    args = ap.parse_args()
    questions = load_questions()
    from src.llm.research_docs.chunk import chunk_documents
    from src.llm.research_docs.load import load_documents
    if args.check:
        problems = check_golds(questions, chunk_documents(load_documents()))
        n = sum(map(answerable, questions))
        print("\n".join(problems)
              or f"all {n} answerable questions' golds match a chunk ({len(questions) - n} unanswerable)")
        raise SystemExit(1 if problems else 0)
    from src.llm.research_docs.index import embed_model, load_index
    index = load_index(embed_model())  # first, so a missing index fails before re-chunking
    current = chunk_documents(load_documents())
    indexed = list(index.docstore.docs.values())
    # The index is rebuilt by hand. Any gold no indexed chunk matches means the index or
    # the answer key is out of date, so refuse to score until one is fixed. Other drift since the build is flagged in the
    # report itself, so a saved copy can't pass for current numbers.
    stale = stale_paths(indexed, current)
    unmatched = unmatched_golds(questions, indexed, current)
    if unmatched:
        head = f"golds that match no indexed chunk ({_stale_summary(stale) if stale else 'index current'}):"
        print(head, *unmatched, sep="\n  ", file=sys.stderr)
        raise SystemExit(1)
    chosen = [q for q in questions if question_split(q) == args.split]
    print(report(evaluate(index, chosen), stale, f"{args.split} ({len(chosen)} of {len(questions)} questions)"))


if __name__ == "__main__":
    main()
