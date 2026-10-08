"""Step 3 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
embed every chunk and persist the index to disk.

An **embedding** is a fixed-length list of numbers (here 384) that a model computes from a
piece of text. The model (`BAAI/bge-small-en-v1.5`, a small BERT run locally) was trained
on pairs of texts known to belong together -- a question and its answer, a title and its
paragraph -- to put each pair's vectors close and unrelated texts far apart. So text about
the same thing lands nearby even with different wording, and "close" is measured as
**cosine similarity**: the cosine of the angle between two vectors, 1 for the same
direction. bge returns unit-length vectors, so the cosine is just the dot product. bge's
scores sit in a narrow band (unrelated chunks here still score ~0.65), so only the
ordering means anything, not the value. Retrieval (step 4) is: embed the question, return
the closest chunks.

The **index** on disk (`data/llm/research_docs_index/`, LlamaIndex's default local store,
plain JSON) is three files that matter, plus two empty ones (`graph_store.json`,
`image__vector_store.json`) the default storage always writes:

- `default__vector_store.json` -- chunk id -> its 384 floats. The only part the model made.
- `docstore.json` -- chunk id -> the chunk itself (text, metadata, link to its source file),
  so a retrieved id can be turned back into text to show and cite.
- `index_store.json` -- which chunk ids belong to this index.

Rebuilding embeds everything again (~13 minutes for 2,328 chunks on an Intel Mac CPU). Each chunk keeps its source
file as `ref_doc_id`, which a later per-file refresh can use instead.

bge reads at most 512 tokens and silently drops the rest. `chunk.py` caps chunks at 384
tokens counted with a different tokenizer, which is not always enough headroom: lists of
snake_case cell ids split into many more bge tokens. `build` counts with bge's own
tokenizer and reports any chunk that gets truncated.

    python -m src.llm.research_docs.index build        # embed all chunks, persist, report
    python -m src.llm.research_docs.index similarity   # cosine between a few stored chunks
"""

from __future__ import annotations

import argparse
import math
import time
import warnings
from collections.abc import Callable
from pathlib import Path

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import BaseNode, MetadataMode

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.load import load_documents

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MAX_TOKENS = 512  # bge's limit; tokens past it are dropped without an error
PERSIST_DIR = Path("data/llm/research_docs_index")

# Chunks for the similarity demo, as (label, path, metadata filter, n-th match). Two
# experiment rows of the same module, one of another module, and two unrelated done.md
# entries; each pick is the first chunk of its row/entry.
EXPERIMENTS = "docs/features/moving-averages/EXPERIMENTS.csv"
DEMO = [
    ("M20 row A", EXPERIMENTS, {"module": "M20"}, 0),
    ("M20 row B", EXPERIMENTS, {"module": "M20"}, 1),
    ("M4 row", EXPERIMENTS, {"module": "M4"}, 0),
    ("done #100 (infra)", "docs/done.md", {"entry": "#100"}, 0),
    ("done #102 (llm)", "docs/done.md", {"entry": "#102"}, 0),
]


def embed_model() -> BaseEmbedding:
    """bge-small via sentence-transformers, downloaded once to the HF cache (~130 MB)."""
    # Torch for Intel Macs stops at 2.2, built against numpy 1.x, and the venv has numpy 2:
    # the stock class's tensor -> numpy -> list conversion fails ("Numpy is not available").
    # Asking sentence-transformers for a tensor and converting that to a list skips numpy.
    warnings.filterwarnings("ignore", message="Failed to initialize NumPy")
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    class TensorHuggingFaceEmbedding(HuggingFaceEmbedding):
        def _embed(self, inputs, prompt_name=None):
            return self._model.encode(
                inputs, batch_size=self.embed_batch_size, prompt_name=prompt_name,
                normalize_embeddings=self.normalize, convert_to_tensor=True,
            ).tolist()

    return TensorHuggingFaceEmbedding(model_name=MODEL_NAME, embed_batch_size=32)


def build_index(nodes: list[BaseNode], embed: BaseEmbedding,
                persist_dir: Path = PERSIST_DIR) -> VectorStoreIndex:
    """Embed `nodes` and write the index to `persist_dir`, replacing what was there."""
    index = VectorStoreIndex(nodes, embed_model=embed, show_progress=True)
    index.storage_context.persist(persist_dir=str(persist_dir))
    return index


def load_index(embed: BaseEmbedding, persist_dir: Path = PERSIST_DIR) -> VectorStoreIndex:
    """The persisted index. `embed` must be the model it was built with: questions are
    embedded with it, and vectors from two different models aren't comparable."""
    if not persist_dir.is_dir():
        raise FileNotFoundError(f"{persist_dir} not found: run `index build` first")
    storage = StorageContext.from_defaults(persist_dir=str(persist_dir))
    return load_index_from_storage(storage, embed_model=embed)


def truncated(nodes: list[BaseNode], count: Callable[[str], int],
              limit: int = MAX_TOKENS) -> list[tuple[BaseNode, int]]:
    """Chunks the model will cut short: (node, tokens) where text plus embedded metadata,
    counted by `count`, exceeds `limit`."""
    sizes = ((n, count(n.get_content(metadata_mode=MetadataMode.EMBED))) for n in nodes)
    return [(n, k) for n, k in sizes if k > limit]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def stored_vectors(index: VectorStoreIndex) -> dict[str, tuple[BaseNode, list[float]]]:
    """Chunk id -> (chunk, vector), read back from the index, no model involved."""
    store = index.vector_store
    return {i: (index.docstore.get_node(i), store.get(i))
            for i in index.index_struct.nodes_dict}


def _pick(nodes: list[BaseNode], path: str, meta: dict[str, str], nth: int) -> BaseNode:
    """The first chunk of the `nth` row/entry in `path` whose metadata matches `meta`."""
    firsts: dict[str, BaseNode] = {}
    for n in nodes:
        m = n.metadata
        if m["path"] == path and all(m.get(k) == v for k, v in meta.items()):
            firsts.setdefault(m.get("entry") or m["section"], n)
    if len(firsts) <= nth:
        raise LookupError(f"no match #{nth} for {meta} in {path}")
    return list(firsts.values())[nth]


def similarity_table(index: VectorStoreIndex, demo=DEMO) -> str:
    stored = stored_vectors(index)
    nodes = [n for n, _ in stored.values()]
    picked = [(label, _pick(nodes, path, meta, nth)) for label, path, meta, nth in demo]
    lines = [f"{i + 1}. {label}: {n.get_content()[:90]!r}" for i, (label, n) in enumerate(picked)]
    lines += ["", " " * 20 + "".join(f"{i + 1:>7}" for i in range(len(picked)))]
    for label, a in picked:
        va = stored[a.node_id][1]
        row = "".join(f"{cosine(va, stored[b.node_id][1]):>7.3f}" for _, b in picked)
        lines.append(f"{label:<20}{row}")
    return "\n".join(lines)


def _disk_report(persist_dir: Path) -> str:
    files = sorted(p for p in persist_dir.iterdir() if p.is_file())
    total = sum(p.stat().st_size for p in files)
    rows = [f"  {p.name:<28} {p.stat().st_size / 1e6:>7.1f} MB" for p in files]
    return "\n".join([f"on disk: {persist_dir}/  {total / 1e6:.1f} MB", *rows])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "similarity"])
    args = ap.parse_args()
    if args.command == "similarity":  # reads stored vectors only; MockEmbedding never runs
        from llama_index.core import MockEmbedding
        print(similarity_table(load_index(MockEmbedding(embed_dim=1))))
        return
    nodes = chunk_documents(load_documents())
    embed = embed_model()
    tokenizer = embed._model.tokenizer
    cut = truncated(nodes, lambda t: len(tokenizer(t)["input_ids"]))
    start = time.perf_counter()
    index = build_index(nodes, embed)
    took = time.perf_counter() - start
    dim = len(next(iter(stored_vectors(index).values()))[1])
    print(f"embedded {len(nodes)} chunks with {MODEL_NAME}: {dim}-dim vectors, {took:.0f}s "
          f"({len(nodes) / took:.1f} chunks/s)")
    print(f"over the {MAX_TOKENS}-token limit (tail dropped): {len(cut)}")
    for n, k in cut:
        print(f"  {k} tokens  {n.metadata['path']} > {n.metadata['section'][:70]}")
    print(_disk_report(PERSIST_DIR))


if __name__ == "__main__":
    main()
