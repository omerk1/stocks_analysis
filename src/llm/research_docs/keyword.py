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
name matches its plain words too. No stemming: "retest" and "retesting" are different words.

What's indexed (`indexed_text`) is the chunk's body, its heading trail (`section`) and, for
an experiment-table row, the id values `chunk` moved out of the row's text into metadata
(`cell_id`, `trial_id`, `experiment_id`, and `outcome`, a verdict label or result
sentence), so an id or verdict typed into a question still finds its row. Left out: the file path and metadata key names, which would make a question word such
as "status" or "design" match every chunk of a file with that name; a CSV row's "row N"
placeholder section and its `tier` column, a lone number that would match any question
with that number in it; and its `module` column. (Numbers still get in through row bodies
and TRIALS.csv's `outcome`, a result sentence with its statistics: a number there sits
among words that also have to match, not alone.) Every other `chunk.ROW_ID_COLUMNS` entry
is indexed, including any added later. Module codes
(M1-M22) still reach the index through headings and prose, which use them throughout.

A section's own heading is in the trail and, on the section's first piece, on the body's
first line too, so there its words count twice: kept on purpose, the usual title boost (a
heading says what a passage is about more than any body sentence). Later pieces of a split
section get the trail once. Dev hit@5 0.76 with it, 0.73 without: 1 question, within
noise, so it's kept as the conventional choice, not as a measured win.

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

from src.llm.research_docs.chunk import ROW_ID_COLUMNS
from src.llm.research_docs.retrieve import TOP_K, search

RRF_K = 60
POOL = 20  # how deep each list goes before fusing
ROW_IDS = tuple(c for c in ROW_ID_COLUMNS if c not in ("module", "tier"))  # module docstring has why


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def indexed_text(node: BaseNode) -> str:
    """What BM25 sees: heading trail, row ids and body (module docstring has what's left out)."""
    m, body = node.metadata, node.get_content()
    trail = m.get("section", "")
    if re.fullmatch(r"row \d+", trail):
        trail = ""
    ids = [str(m[c]) for c in ROW_IDS if m.get(c)]
    return "\n".join([*filter(None, [trail]), *ids, body])


class KeywordIndex:
    """BM25 over a fixed set of chunks, built in memory (a few seconds for the corpus)."""

    def __init__(self, nodes: list[BaseNode], k1: float = 1.5, b: float = 0.75):
        self.nodes = nodes
        self.k1, self.b = k1, b
        docs = [tokens(indexed_text(n)) for n in nodes]
        self.lens = [len(d) for d in docs]
        self.avg_len = sum(self.lens) / len(docs) if docs else 0.0  # only divides for chunks with words
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
