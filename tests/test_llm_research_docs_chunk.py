from llama_index.core import Document
from llama_index.core.schema import MetadataMode

from src.llm.research_docs.chunk import CHUNK_SIZE, chunk_documents, n_tokens


def _doc(path, text, fmt):
    return Document(text=text, id_=path, metadata={
        "path": path, "area": "ma_study", "format": fmt, "title": "T"})


def test_markdown_splits_on_headings_and_keeps_the_heading_trail():
    md = _doc("docs/a.md", "# Top\n\nintro\n\n## M1 — State\n\nbody one\n\n## M4\n\nbody four\n", "md")
    nodes = chunk_documents([md])
    assert [n.metadata["section"] for n in nodes] == ["Top", "Top > M1 — State", "Top > M4"]
    assert "body one" in nodes[1].text and "body four" not in nodes[1].text


def test_csv_is_one_chunk_per_row_with_ids_in_metadata_and_empty_cells_dropped():
    rows = "module,cell_id,hypothesis,ci_low,outcome\nM4,sma20,displacement matters,,no_effect\nM1,ab,state,0.1,weak\n"
    nodes = chunk_documents([_doc("docs/E.csv", rows, "csv")])
    assert len(nodes) == 2
    first = nodes[0]
    assert first.text == "hypothesis: displacement matters"  # ci_low empty -> dropped
    assert first.metadata["cell_id"] == "sma20" and first.metadata["outcome"] == "no_effect"
    assert "cell_id: sma20" in first.get_content(metadata_mode=MetadataMode.EMBED)


def test_oversized_pieces_are_capped_and_every_piece_keeps_its_identity():
    long_notes = " ".join(f"Sentence number {i} about the effect." for i in range(400))
    rows = f"module,cell_id,notes\nM6,persist,{long_notes}\n"
    nodes = chunk_documents([_doc("docs/E.csv", rows, "csv")])
    assert len(nodes) > 1
    assert all(n.metadata["cell_id"] == "persist" for n in nodes)
    assert all(n_tokens(n) <= CHUNK_SIZE for n in nodes)


def test_area_and_format_are_carried_but_not_embedded():
    node = chunk_documents([_doc("docs/a.md", "# Top\n\ntext\n", "md")])[0]
    embedded = node.get_content(metadata_mode=MetadataMode.EMBED)
    assert node.metadata["area"] == "ma_study"
    assert "area:" not in embedded and "format:" not in embedded
    assert "section: Top" in embedded
