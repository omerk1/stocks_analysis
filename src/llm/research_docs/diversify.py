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

The scaling is relative to each question's own candidates: similarity 1 is the most alike
pair among them (often a near-copy, but not necessarily), and relevance 0 is the weakest
candidate, so one very low score stretches the range and narrows the gaps between the
rest. Both are the usual MMR simplification, accepted here rather than calibrated.

**LAMBDA = 0.75**, fixed before any run. The candidate most like a picked chunk (scaled
similarity 1) gives way to one unlike any (similarity 0) whenever the second is within
(1 - LAMBDA) / LAMBDA = 1/3 of the candidates' relevance range. The cross-encoder is the
best judge of relevance this pipeline has, so diversity should break near-ties and push
out copies, not override a clear relevance gap. The textbook 0.5 would let any candidate,
however weak, beat the most redundant one.

It runs after re-ranking, on the re-ranker's candidates, because MMR trades relevance
against redundancy and is only as good as its relevance term: the cross-encoder's is
the best available, and it only exists for the `rerank.DEPTH` chunks it scored.
Scores reported are the cross-encoder's, so they stay comparable with `--method rerank`.

When written, it scored no better than re-ranking alone (`docs/done.md` #134 has the
numbers): the multi-part questions it was meant to help miss parts that aren't among the
candidates at all, which no reordering can fix.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore

from src.llm.research_docs.keyword import KeywordIndex, hybrid_search
from src.llm.research_docs.rerank import DEPTH, Scorer, rerank
from src.llm.research_docs.retrieve import TOP_K

LAMBDA = 0.75  # module docstring has why


def _scale(values: np.ndarray) -> np.ndarray:
    span = np.ptp(values) if values.size else 0.0
    return (values - values.min()) / span if span > 0 else np.zeros_like(values)


def mmr(hits: Sequence[NodeWithScore], vectors: Mapping[str, Sequence[float]],
        k: int = TOP_K, lam: float = LAMBDA) -> list[NodeWithScore]:
    """`k` of `hits` (best first by their own scores) picked by maximal marginal
    relevance; `vectors` maps node id to its stored embedding."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if not hits:
        return []
    if missing := [h.node.node_id for h in hits if h.node.node_id not in vectors]:
        raise LookupError(f"no stored vector for {len(missing)} candidate(s), e.g. {missing[0]}: "
                          "the docstore and vector store disagree, rebuild the index")
    n = len(hits)
    try:  # a None score or a ragged vector would otherwise become a silent NaN
        scores = np.array([h.score for h in hits], dtype=float)
        vecs = np.array([vectors[h.node.node_id] for h in hits], dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError(f"candidates need a score and same-length vectors: {e}") from None
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    if not (np.isfinite(scores).all() and np.isfinite(vecs).all() and (norms > 0).all()):
        raise ValueError("a candidate has a missing score or an empty vector; rebuild the index")
    rel = _scale(scores)
    vecs /= norms  # so the dot product is the cosine
    upper = np.triu_indices(n, 1)  # each pair once; a chunk's similarity to itself doesn't count
    sim = np.zeros((n, n))
    sim[upper] = _scale((vecs @ vecs.T)[upper])
    sim += sim.T
    closest = np.zeros(n)  # similarity to the closest picked chunk
    taken = np.zeros(n, dtype=bool)
    picked: list[int] = []
    for _ in range(min(k, n)):
        # argmax returns the first of equal values: a tie goes to the re-ranker's order
        best = int(np.argmax(np.where(taken, -np.inf, lam * rel - (1 - lam) * closest)))
        picked.append(best)
        taken[best] = True
        closest = np.maximum(closest, sim[best])
    return [hits[i] for i in picked]


def mmr_search(index: VectorStoreIndex, keywords: KeywordIndex, score: Scorer,
               vectors: Mapping[str, Sequence[float]], question: str, k: int = TOP_K,
               depth: int = DEPTH) -> list[NodeWithScore]:
    """Hybrid search's top `max(k, depth)`, re-ranked, then `k` picked by MMR."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    hits = hybrid_search(index, keywords, question, max(k, depth))
    return mmr(rerank(score, question, hits, len(hits) or 1), vectors, k)
