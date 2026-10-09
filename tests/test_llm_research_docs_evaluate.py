import pytest
from llama_index.core import Document

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.evaluate import (
    check_golds, docs_newer_than, first_hit, load_questions, matches, report, scores)
from src.llm.research_docs.load import load_documents


def _node(text="x", **meta):
    return Document(text=text, metadata={"path": "docs/a.md", "section": "S", **meta})


def test_matches_on_path_phrase_and_metadata():
    node = _node("B5 was  dropped\nas too fragile", entry="#47")
    assert matches(node, {"path": "docs/a.md"})
    assert matches(node, {"path": "docs/a.md", "contains": "b5 was dropped as too"})  # case, whitespace
    assert matches(node, {"path": "docs/a.md", "entry": "#47"})
    assert not matches(node, {"path": "docs/b.md"})
    assert not matches(node, {"path": "docs/a.md", "entry": "#48"})
    assert not matches(node, {"path": "docs/a.md", "contains": "kept"})
    combined = _node(entry="#16, #17")
    assert matches(combined, {"entry": "#17"}) and matches(combined, {"entry": "#16, #17"})
    assert not matches(combined, {"entry": "#1"})


def test_first_hit_is_the_rank_of_the_first_matching_node():
    nodes = [_node(entry="#1"), _node(entry="#2"), _node(entry="#3")]
    assert first_hit(nodes, [{"entry": "#2"}, {"entry": "#3"}]) == 2
    assert first_hit(nodes, [{"entry": "#9"}]) is None


def test_evaluate_records_a_miss_when_search_returns_nothing(monkeypatch):
    from src.llm.research_docs import evaluate as ev
    monkeypatch.setattr(ev, "search", lambda index, question, k: [])
    rows = ev.evaluate(None, [{"id": "q", "question": "?", "gold": [{"path": "docs/a.md"}]}])
    assert rows[0]["rank"] is None and rows[0]["top"] == "-"


def test_docs_newer_than_the_index(tmp_path):
    import os
    index_file, old, new = tmp_path / "docstore.json", tmp_path / "old.md", tmp_path / "new.md"
    for p, t in ((old, 100), (index_file, 200), (new, 300)):
        p.write_text("x")
        os.utime(p, (t, t))
    assert docs_newer_than(index_file, tmp_path) == [new]


def test_scores_hit_at_k_and_mrr():
    rows = [{"rank": 1}, {"rank": 4}, {"rank": None}, {"rank": 2}]
    s = scores(rows)
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@5"] == 0.75 and s["hit@10"] == 0.75
    assert s["MRR"] == pytest.approx((1 + 1 / 4 + 0 + 1 / 2) / 4)


def test_report_breaks_scores_down_by_type_and_style():
    rows = [{"id": "q1", "type": "row", "style": "id", "rank": 1, "top": "docs/E.csv > a"},
            {"id": "q2", "type": "entry", "style": "plain", "rank": None, "top": "docs/done.md > #1"}]
    out = report(rows)
    assert "q2" in out and "type=row" in out and "style=plain" in out
    assert out.splitlines()[2].split()[3] == "-"  # q2 found nothing in the top 10


def test_check_golds_flags_a_gold_no_chunk_matches():
    questions = [{"id": "q", "gold": [{"path": "docs/a.md", "contains": "gone"}]}]
    assert check_golds(questions, [_node("still here")]) == ["q: {'path': 'docs/a.md', 'contains': 'gone'}"]


def test_every_question_in_the_set_still_matches_the_real_docs():
    """If this fails, a doc was edited under a question: fix the question's gold."""
    questions = load_questions()
    assert len({q["id"] for q in questions}) == len(questions)
    assert check_golds(questions, chunk_documents(load_documents())) == []
