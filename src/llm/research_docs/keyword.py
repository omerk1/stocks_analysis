"""Step 7a of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
keyword search, and its fusion with vector search into one **hybrid** ranking.

Vector search (`retrieve.search`) matches meaning: it finds a paraphrase, but a small
embedding model blurs a rare exact term (a feature name, an indicator, a number) into its
neighbours. Keyword search is the opposite: it only sees shared words, so it misses a
paraphrase but ranks a chunk containing the question's rare word near the top.

**BM25** scores a chunk by the question words it contains:

- a word's weight is its **idf**, high when few chunks contain it ("sharpe") and near zero
  when most do ("the"), so common words barely count;
- repeats help with diminishing returns: `k1` caps how much a word's tenth occurrence adds
  over its first;
- long chunks are discounted (`b`): a long chunk contains more words by chance.

Text is lowercased and split on anything that isn't a letter or digit, so a snake_case
name matches its plain words too. What's indexed is the chunk's body plus its heading trail
(`section`), not the rest of its metadata: the file path and keys like `entry:` or
`cell_id:` would make a question word such as "status" or "design" match every chunk of a
file with that name. No stemming: "retest" and "retesting" are different words.

**Reciprocal rank fusion** merges the two rankings by position, not score (cosine
similarity and BM25 aren't on the same scale): each chunk gets `1 / (RRF_K + rank)` from
each list it appears in, summed. A chunk near the top of both lists wins; one that only
one list ranks high still gets in. `RRF_K = 60` is the usual constant: it flattens the gap
between rank 1 and rank 2, so neither list's top spot dominates. Equal fused scores keep
the order chunks were first seen in, vector list first: a tie goes to vector search.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode, NodeWithScore

from src.llm.research_docs.retrieve import TOP_K, search

RRF_K = 60
POOL = 20  # how deep each list goes before fusing


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def indexed_text(node: BaseNode) -> str:
    """What BM25 sees: the heading trail, if any, and the body."""
    section = node.metadata.get("section")
    return f"{section}\n{node.get_content()}" if section else node.get_content()


class KeywordIndex:
    """BM25 over a fixed set of chunks, built in memory (a few seconds for the corpus)."""

    def __init__(self, nodes: list[BaseNode], k1: float = 1.5, b: float = 0.75):
        self.nodes = nodes
        self.k1, self.b = k1, b
        docs = [tokens(indexed_text(n)) for n in nodes]
        self.lens = [len(d) for d in docs]
        self.avg_len = (sum(self.lens) / len(docs) if docs else 0.0) or 1.0  # no words: avoid /0
        # word -> [(chunk, count)]: a question only touches the chunks containing its words
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for t, c in Counter(d).items():
                self.postings.setdefault(t, []).append((i, c))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def score(self, question: str) -> dict[int, float]:
        """BM25 score per chunk position, for the chunks sharing a word with `question`."""
        out: dict[int, float] = {}
        for t in set(tokens(question)) & self.postings.keys():
            for i, tf in self.postings[t]:
                norm = self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg_len)
                out[i] = out.get(i, 0.0) + self.idf[t] * tf * (self.k1 + 1) / (tf + norm)
        return out

    def search(self, question: str, k: int = TOP_K) -> list[NodeWithScore]:
        """The `k` best-scoring chunks, best first; chunks sharing no word are left out."""
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        scored = sorted(((s, i) for i, s in self.score(question).items() if s > 0),
                        key=lambda x: (-x[0], x[1]))
        return [NodeWithScore(node=self.nodes[i], score=s) for s, i in scored[:k]]


def fuse(rankings: list[list[NodeWithScore]], k: int = TOP_K) -> list[NodeWithScore]:
    """Reciprocal rank fusion: the score is the sum of 1 / (RRF_K + rank) over the lists."""
    total: dict[str, float] = {}
    first: dict[str, BaseNode] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            nid = hit.node.node_id
            total[nid] = total.get(nid, 0.0) + 1 / (RRF_K + rank)
            first.setdefault(nid, hit.node)
    best = sorted(total, key=lambda nid: -total[nid])  # stable: ties keep first-seen order
    return [NodeWithScore(node=first[nid], score=total[nid]) for nid in best[:k]]


def hybrid_search(index: VectorStoreIndex, keywords: KeywordIndex, question: str,
                  k: int = TOP_K) -> list[NodeWithScore]:
    """Vector and keyword top `max(k, POOL)`, fused; the `k` best, best first."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    depth = max(k, POOL)
    return fuse([search(index, question, depth), keywords.search(question, depth)], k)
