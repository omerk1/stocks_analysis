"""Step 4 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
retrieval only -- a question in, the closest chunks out. No LLM writes an answer yet
(that's step 6); this step is about whether the right chunks come back at all.

How a question is matched:

1. The question is embedded with the same model as the chunks (vectors from two models
   live in different spaces and can't be compared). bge is trained **asymmetrically**:
   questions get a prefix ("Represent this question for searching relevant passages: ")
   and passages don't, because a short question and the paragraph answering it don't look
   alike. LlamaIndex adds the prefix to queries only, through the model's `query` prompt.
2. Its cosine similarity is computed against every stored chunk vector -- a plain scan
   of all ~2,300 vectors, fast enough at this size that no approximate search structure
   is needed.
3. The `k` highest-scoring chunks come back with their scores, text and metadata.

The score only ranks chunks for one question: it isn't comparable across questions and
has no "relevant" cutoff (bge puts unrelated text at ~0.65, the index docstring has why).

    python -m src.llm.research_docs.retrieve "Why were baselines B1 and B5 dropped?"
    python -m src.llm.research_docs.retrieve "..." -k 10 --full    # whole chunk texts
"""

from __future__ import annotations

import argparse
import textwrap

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode, NodeWithScore

from src.llm.research_docs.index import embed_model, load_index

TOP_K = 5


def search(index: VectorStoreIndex, question: str, k: int = TOP_K) -> list[NodeWithScore]:
    """The `k` chunks closest to `question`, best first."""
    return index.as_retriever(similarity_top_k=k).retrieve(question)


def cite(node: BaseNode) -> str:
    """Where a chunk comes from, as precisely as its metadata allows: a done.md entry
    number, an experiment row's cell id, or a markdown section's heading trail."""
    m = node.metadata
    where = m.get("entry") or m.get("cell_id") or m.get("trial_id") or m["section"]
    return f"{m['path']} > {where}"


def format_hits(hits: list[NodeWithScore], full: bool = False) -> str:
    out = []
    for rank, h in enumerate(hits, 1):
        text = h.node.get_content()
        if not full:
            text = textwrap.shorten(text, 240, placeholder=" …")
        out.append(f"{rank}. {h.score:.3f}  {cite(h.node)}\n{textwrap.indent(text, '     ')}")
    return "\n\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=TOP_K)
    ap.add_argument("--full", action="store_true", help="print whole chunks, not a snippet")
    args = ap.parse_args()
    index = load_index(embed_model())
    print(format_hits(search(index, args.question, args.k), args.full))


if __name__ == "__main__":
    main()
