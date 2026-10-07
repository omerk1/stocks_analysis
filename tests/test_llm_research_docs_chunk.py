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


def _filler(word, n):
    return " ".join(f"{word}{i} detail." for i in range(n))


def test_numbered_log_entries_are_one_chunk_each_with_entry_and_tags():
    entries = "\n".join(
        f"- **#{i}** [data, breadth] — entry {i} {_filler('x', 30)}" for i in range(1, 6))
    md = _doc("docs/done.md", f"# Done\n\nIntro line.\n\n{entries}\n- **#14.5** — untagged\n", "md")
    nodes = [n for n in chunk_documents([md]) if "entry" in n.metadata]
    assert [n.metadata["entry"] for n in nodes] == ["#1", "#2", "#3", "#4", "#5", "#14.5"]
    assert nodes[0].metadata["tags"] == "data, breadth" and "tags" not in nodes[-1].metadata
    assert all(n.text.count("- **#") == 1 for n in nodes)  # never two entries in one chunk


def test_other_list_items_are_packed_but_never_cut_mid_item():
    items = "\n".join(f"- item {i}: {_filler('w', 12)}\n  - sub-point <{i}>" for i in range(12))
    nodes = chunk_documents([_doc("docs/backlog.md", f"# Backlog\n\n## Data\n\n{items}\n", "md")])
    assert 1 < len(nodes) < 12  # packed, not one per item
    for n in nodes:
        assert n_tokens(n) <= CHUNK_SIZE
        for i in range(12):  # an item and its sub-point land in the same chunk
            assert (f"- item {i}:" in n.text) == (f"sub-point <{i}>" in n.text)


def test_prose_section_with_a_few_bullets_is_not_list_split():
    prose = "\n\n".join(_filler("p", 25) for _ in range(6))
    md = _doc("docs/a.md", f"# Design\n\n{prose}\n\n- one bullet\n- two bullet\n", "md")
    nodes = chunk_documents([md])
    assert not any("entry" in n.metadata for n in nodes)
    assert "- one bullet\n- two bullet" in nodes[-1].text  # left to the size cap, untouched
