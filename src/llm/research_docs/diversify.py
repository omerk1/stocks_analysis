"""Step 7c of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
diversity in the top k, by **maximal marginal relevance** (MMR) over the re-ranked
candidates.

The re-ranker (`rerank.py`) scores each chunk on its own, so chunks that say nearly the
same thing score nearly the same and sit next to each other: several pieces of one
section, sibling rows of one experiment grid (`dist_pct_sma_20_h21`, `..._50_h21`), the
same result told by a done.md entry, the findings register and a CSV row. Each copy
after the first adds little to a top 5 an LLM will read, and takes a slot from a chunk
that might hold a different part of the answer.

MMR builds the top k one pick at a time. Each pick is the candidate with the best

    LAMBDA * relevance - (1 - LAMBDA) * (similarity to the closest chunk already picked)

so a chunk loses ground for every near-copy already in the list, not for being off-topic.
The first pick has nothing to be similar to: it is always the re-ranker's top chunk.

- **relevance**: the cross-encoder's score, min-max scaled to 0-1 over the candidates.
- **similarity**: cosine between the chunks' stored bge vectors (no new model, nothing
  embedded at question time), min-max scaled to 0-1 over the candidate pairs. Both terms
  are scaled because the two raw scores live on different ranges: a MiniLM logit spans
  about -10 to 10, a bge cosine about 0.6 to 1.

**LAMBDA = 0.75**, fixed before any run. A full near-copy of a picked chunk (scaled
similarity 1) gives way to a fresh chunk (similarity 0) whenever the fresh one is within
(1 - LAMBDA) / LAMBDA = 1/3 of the candidates' relevance range. The cross-encoder is the
best judge of relevance this pipeline has, so diversity should break near-ties and push
out copies, not override a clear relevance gap. The textbook 0.5 would let any candidate,
however weak, beat a full copy.

It runs after re-ranking, on the re-ranker's candidates, because MMR trades relevance
against redundancy and is only as good as its relevance term: the cross-encoder's is
the best available, and it only exists for the `rerank.DEPTH` chunks it scored.
Scores reported are the cross-encoder's, so they stay comparable with `--method rerank`.

Result on dev (41 answerable questions): no better than re-ranking alone. hit@5 drops by
1 question (0.85 to 0.83), hit@3 and hit@10 gain 1 each, and MRR moves by 0.01, all
within the one-question noise. Multi-part full answers stay 0/4. Their missing parts are
not crowded out of the top 5: they are not among the 30 candidates at all, so no
reordering can bring them in. That is a recall problem, for splitting the question into
one search per part. So re-ranking alone stays the method to beat, and MMR stays
available as `--method mmr`. It costs ~40 ms per question on top of the re-ranker.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore

from src.llm.research_docs.keyword import KeywordIndex, hybrid_search
from src.llm.research_docs.rerank import DEPTH, Scorer, rerank
from src.llm.research_docs.retrieve import TOP_K

LAMBDA = 0.75  # module docstring has why


def _scale(values: list[float]) -> list[float]:
    lo, hi = min(values, default=0.0), max(values, default=0.0)
    return [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in values]


def mmr(hits: Sequence[NodeWithScore], vectors: Mapping[str, Sequence[float]],
        k: int = TOP_K, lam: float = LAMBDA) -> list[NodeWithScore]:
    """`k` of `hits` (best first by their own scores) picked by maximal marginal
    relevance; `vectors` maps node id to its unit-length embedding."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    n = len(hits)
    rel = _scale([h.score for h in hits])
    vecs = [vectors[h.node.node_id] for h in hits]
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    scaled = _scale([sum(a * b for a, b in zip(vecs[i], vecs[j])) for i, j in pairs])
    sim = [[0.0] * n for _ in range(n)]
    for (i, j), s in zip(pairs, scaled):
        sim[i][j] = sim[j][i] = s
    closest = [0.0] * n  # similarity to the closest picked chunk
    picked: list[int] = []
    left = list(range(n))
    while left and len(picked) < k:
        # max() keeps the first of equal values: a tie goes to the re-ranker's order
        best = max(left, key=lambda i: lam * rel[i] - (1 - lam) * closest[i])
        picked.append(best)
        left.remove(best)
        closest = [max(c, sim[best][i]) for i, c in enumerate(closest)]
    return [hits[i] for i in picked]


def mmr_search(index: VectorStoreIndex, keywords: KeywordIndex, score: Scorer,
               vectors: Mapping[str, Sequence[float]], question: str, k: int = TOP_K,
               depth: int = DEPTH) -> list[NodeWithScore]:
    """Hybrid search's top `max(k, depth)`, re-ranked, then `k` picked by MMR."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    hits = hybrid_search(index, keywords, question, max(k, depth))
    return mmr(rerank(score, question, hits, len(hits) or 1), vectors, k)
