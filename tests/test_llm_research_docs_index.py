import pytest
from llama_index.core import Document, MockEmbedding

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.index import (
    build_index, changed_sources, cosine, load_index, similarity_table, stored_vectors,
    truncated, write_sources)

DIM = 8


def _nodes():
    md = Document(text="# Done\n\n- **#1** [infra] — set up\n- **#2** [llm] — chunking\n",
                  id_="docs/done.md",
                  metadata={"path": "docs/done.md", "area": "project", "format": "md", "title": "Done"})
    rows = "module,cell_id,notes\nM4,a,first\nM4,b,second\n"
    csv = Document(text=rows, id_="docs/E.csv",
                   metadata={"path": "docs/E.csv", "area": "ma_study", "format": "csv", "title": "E"})
    return chunk_documents([md, csv])


def test_build_persists_and_reloads_every_chunk_with_its_vector(tmp_path):
    nodes = _nodes()
    build_index(nodes, MockEmbedding(embed_dim=DIM), tmp_path)
    assert {p.name for p in tmp_path.iterdir()} >= {
        "default__vector_store.json", "docstore.json", "index_store.json"}
    stored = stored_vectors(load_index(MockEmbedding(embed_dim=DIM), tmp_path))
    assert set(stored) == {n.node_id for n in nodes}
    assert all(len(v) == DIM for _, v in stored.values())
    node, _ = stored[nodes[-1].node_id]
    assert node.text == nodes[-1].text and node.metadata["cell_id"] == "b"


def test_every_chunk_keeps_its_source_file_for_per_file_refresh(tmp_path):
    build_index(_nodes(), MockEmbedding(embed_dim=DIM), tmp_path)
    stored = stored_vectors(load_index(MockEmbedding(embed_dim=DIM), tmp_path))
    assert {n.ref_doc_id for n, _ in stored.values()} == {"docs/done.md", "docs/E.csv"}


def test_rebuild_replaces_rather_than_appends(tmp_path):
    nodes = _nodes()
    build_index(nodes, MockEmbedding(embed_dim=DIM), tmp_path)
    build_index(nodes[:2], MockEmbedding(embed_dim=DIM), tmp_path)
    stored = stored_vectors(load_index(MockEmbedding(embed_dim=DIM), tmp_path))
    assert set(stored) == {n.node_id for n in nodes[:2]}


def test_load_without_a_build_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="repo root"):
        load_index(MockEmbedding(embed_dim=DIM), tmp_path / "missing")


def test_truncated_counts_embedded_metadata_too():
    nodes = _nodes()
    words = lambda text: len(text.split())
    longest = max(words(n.get_content(metadata_mode="embed")) for n in nodes)
    assert truncated(nodes, words, limit=longest) == []
    cut = truncated(nodes, words, limit=longest - 1)
    assert cut and all(k == longest for _, k in cut)


def test_cosine():
    assert cosine([1, 0], [2, 0]) == pytest.approx(1)
    assert cosine([1, 0], [0, 3]) == pytest.approx(0)
    assert cosine([1, 1], [-1, -1]) == pytest.approx(-1)


def test_similarity_table_reads_stored_vectors(tmp_path):
    index = build_index(_nodes(), MockEmbedding(embed_dim=DIM), tmp_path)
    demo = [("row a", "docs/E.csv", {"module": "M4"}, 0),
            ("row b", "docs/E.csv", {"module": "M4"}, 1),
            ("done", "docs/done.md", {}, 0)]
    table = similarity_table(index, demo)
    assert "row b" in table and "notes: second" in table
    # MockEmbedding gives every text the same vector: all cosines are 1.
    assert table.count("1.000") == 9
    with pytest.raises(LookupError):
        similarity_table(index, [("x", "docs/E.csv", {"module": "M4"}, 2)])


def test_changed_sources_reports_edits_additions_and_deletions(tmp_path):
    def doc(path, text):
        return Document(text=text, metadata={"path": path})
    assert changed_sources([doc("a.md", "x")], tmp_path) is None  # no record yet
    write_sources([doc("a.md", "x"), doc("b.md", "y"), doc("c.md", "z")], tmp_path)
    assert changed_sources([doc("a.md", "x"), doc("b.md", "y"), doc("c.md", "z")], tmp_path) == []
    now = [doc("a.md", "x"), doc("b.md", "y2"), doc("d.md", "w")]
    assert changed_sources(now, tmp_path) == ["b.md (edited)", "c.md (deleted)", "d.md (added)"]
