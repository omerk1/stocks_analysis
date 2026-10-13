"""Step 7b of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
re-rank hybrid search's candidates with a **cross-encoder**.

The embedding model (`index.embed_model`, a **bi-encoder**) reads the question and each
chunk *separately*, turns each into one vector, and compares the vectors. That's what
makes it fast: every chunk is embedded once, at build time, and a question costs one
embedding plus a dot product per chunk. The price is that the chunk's vector was made
without knowing the question, so everything the chunk says is squeezed into one point,
and the question can only be compared against that summary.

A cross-encoder reads the question and one chunk *together*, as a single input
("question [SEP] chunk"), and outputs one relevance score. Every word of the question can
attend to every word of the chunk, so it can see that "dropped" in the question matches
"removed" next to "B5" in the chunk, rather than two vectors being merely close. It is
usually the more accurate judge, but nothing can be precomputed: each (question, chunk)
pair is a full model run at question time. Over all ~3,500 chunks that's minutes per
question on this CPU.

Hence **retrieve, then re-rank**: a cheap search (hybrid, `keyword.hybrid_search`) narrows
the corpus to its top `DEPTH` candidates, the cross-encoder scores only those, and the `k`
best by its score are kept. The re-ranker can only reorder what retrieval found: a chunk
outside hybrid's top `DEPTH` stays out, so hybrid's hit@`DEPTH` is its ceiling.

Models (both run under the Intel Mac's torch 2.2 cap via sentence-transformers 3):

- `cross-encoder/ms-marco-MiniLM-L-6-v2` (default): 22M parameters, trained on MS MARCO
  web-search pairs; about 0.1 s per pair here.
- `BAAI/bge-reranker-base`: 278M parameters (XLM-RoBERTa), trained on a broader mix;
  about 10x slower.

The score is the model's own: a raw logit for MiniLM (any real number), a 0-1 sigmoid
for bge. Unlike a cosine similarity, it is meant to read as relevance on its own, not
only relative to the other chunks for the same question.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import MetadataMode, NodeWithScore

from src.llm.research_docs.keyword import KeywordIndex, hybrid_search
from src.llm.research_docs.retrieve import TOP_K

MODELS = ("cross-encoder/ms-marco-MiniLM-L-6-v2", "BAAI/bge-reranker-base")
DEPTH = 30  # hybrid candidates the cross-encoder scores
# Both models' limit, for question and chunk together. A longer pair loses the end of the
# chunk without a warning: with the longest dev question, 118 of 3,483 pairs for MiniLM and
# 22 for bge (their tokenizers differ from the one `chunk` caps chunks with).
MAX_TOKENS = 512

Scorer = Callable[[list[tuple[str, str]]], list[float]]


def cross_encoder(name: str = MODELS[0]) -> Scorer:
    """A scorer for (question, chunk text) pairs, downloaded once to the HF cache."""
    with warnings.catch_warnings():  # index.embed_model has why
        warnings.filterwarnings("ignore", message="Failed to initialize NumPy")
        from sentence_transformers import CrossEncoder

    model = CrossEncoder(name, max_length=MAX_TOKENS)
    # as a tensor, then a list: the default numpy output fails under torch 2.2 + numpy 2
    return lambda pairs: model.predict(pairs, convert_to_tensor=True).tolist()


def rerank(score: Scorer, question: str, hits: Sequence[NodeWithScore],
           k: int = TOP_K) -> list[NodeWithScore]:
    """`hits` reordered by the cross-encoder's score, the `k` best, best first. Each chunk
    is scored as the embedding model saw it (text plus heading trail and row ids)."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if not hits:
        return []
    texts = [h.node.get_content(metadata_mode=MetadataMode.EMBED) for h in hits]
    scored = list(zip(score([(question, t) for t in texts]), range(len(hits))))
    scored.sort(key=lambda x: (-x[0], x[1]))  # ties keep hybrid's order
    return [NodeWithScore(node=hits[i].node, score=s) for s, i in scored[:k]]


def rerank_search(index: VectorStoreIndex, keywords: KeywordIndex, score: Scorer,
                  question: str, k: int = TOP_K, depth: int = DEPTH) -> list[NodeWithScore]:
    """Hybrid search's top `max(k, depth)`, re-ranked; the `k` best, best first."""
    return rerank(score, question, hybrid_search(index, keywords, question, max(k, depth)), k)
