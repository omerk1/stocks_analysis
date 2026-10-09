import pytest
from llama_index.core import Document
from llama_index.core.base.embeddings.base import BaseEmbedding

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.index import build_index
from src.llm.research_docs.retrieve import cite, format_hits, search

VOCAB = ["slope", "baseline", "breadth", "chunking"]


class KeywordEmbedding(BaseEmbedding):
    """Counts of a few words: texts sharing a word point the same way, so ranking is
    meaningful without downloading a model."""

    def _vec(self, text: str) -> list[float]:
        words = text.lower().split()
        return [float(sum(w.startswith(v) for w in words)) + 0.01 for v in VOCAB]

    def _get_text_embedding(self, text):
        return self._vec(text)

    def _get_query_embedding(self, query):
        return self._vec(query)

    async def _aget_query_embedding(self, query):
        return self._vec(query)


def _index(tmp_path):
    md = Document(
        text="# Design\n\n## Slope\n\nslope slope tested\n\n## Baselines\n\nbaseline dropped\n",
        id_="docs/D.md", metadata={"path": "docs/D.md", "area": "ma_study", "format": "md", "title": "Design"})
    rows = "module,cell_id,notes\nM5,breadth_top,breadth regime\n"
    csv = Document(text=rows, id_="docs/E.csv",
                   metadata={"path": "docs/E.csv", "area": "ma_study", "format": "csv", "title": "E"})
    return build_index(chunk_documents([md, csv]), KeywordEmbedding(), tmp_path)


def test_search_ranks_the_matching_chunk_first_and_respects_k(tmp_path):
    index = _index(tmp_path)
    hits = search(index, "was the slope tested?", k=2)
    assert len(hits) == 2
    assert hits[0].node.metadata["section"] == "Design > Slope"
    assert hits[0].score > hits[1].score
    assert search(index, "breadth regimes", k=1)[0].node.metadata["cell_id"] == "breadth_top"
    with pytest.raises(ValueError):
        search(index, "slope", k=0)


def test_cite_uses_the_most_precise_id_available():
    def node(**meta):
        return Document(text="x", metadata={"path": "docs/p", "section": "S > T", **meta})
    assert cite(node(entry="#47")) == "docs/p > #47"
    assert cite(node(cell_id="sma20")) == "docs/p > sma20"
    assert cite(node(experiment_id="E1")) == "docs/p > E1"
    assert cite(node()) == "docs/p > S > T"
    assert cite(Document(text="x", metadata={"path": "docs/p"})) == "docs/p"


def test_format_hits_shortens_unless_full(tmp_path):
    hits = search(_index(tmp_path), "baseline", k=1)
    hits[0].node.text = "baseline " * 100
    short, full = format_hits(hits), format_hits(hits, full=True)
    assert short.startswith("1. ") and "docs/D.md > Design > Baselines" in short
    assert short.endswith("…") and len(full) > len(short)
