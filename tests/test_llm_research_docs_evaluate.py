import pytest
from llama_index.core import Document

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.evaluate import (
    check_golds, first_hit, load_questions, matches, report, scores, stale_paths,
    unmatched_golds)
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


def test_stale_paths_finds_edited_added_and_deleted_files():
    def n(path, text):
        return Document(text=text, metadata={"path": path})
    indexed = [n("a.md", "x"), n("a.md", "y"), n("b.md", "z"), n("c.md", "w")]
    assert stale_paths(indexed, list(reversed(indexed))) == []  # order doesn't matter
    current = [n("a.md", "x"), n("a.md", "y"), n("b.md", "z2"), n("d.md", "v")]
    assert stale_paths(indexed, current) == ["b.md", "c.md", "d.md"]
    # same text, changed metadata (e.g. a CSV row's outcome) is stale too
    retagged = Document(text="w", metadata={"path": "c.md", "outcome": "dead"})
    assert stale_paths(indexed, indexed[:3] + [retagged]) == ["c.md"]
    # same text and metadata, but a key moved out of the embedding: vectors differ, stale
    embedded = Document(text="w", metadata={"path": "c.md", "area": "x"})
    hidden = Document(text="w", metadata={"path": "c.md", "area": "x"}, excluded_embed_metadata_keys=["area"])
    assert stale_paths([embedded], [hidden]) == ["c.md"]


def test_unmatched_golds_say_whether_a_rebuild_would_fix_them():
    indexed = [_node("old wording")]
    current = [_node("new wording")]
    questions = [{"id": "ok", "gold": [{"path": "docs/a.md", "contains": "old"}]},
                 {"id": "moved", "gold": [{"path": "docs/a.md", "contains": "new"}]},
                 {"id": "typo", "gold": [{"path": "docs/a.md", "contains": "nwe"}]}]
    out = unmatched_golds(questions, indexed, current)
    assert len(out) == 2
    assert out[0].startswith("moved:") and out[0].endswith("(rebuild the index)")
    assert out[1].startswith("typo:") and out[1].endswith("(fix the gold)")


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
    assert "STALE" not in out
    stale_out = report(rows, ["docs/a.md"]).splitlines()
    assert stale_out[0].startswith("STALE INDEX: 1 file(s) differ from the index (docs/a.md)")
    assert stale_out[1] == "" and stale_out[2].startswith("question")
    assert out.splitlines()[2].split()[3] == "-"  # q2 found nothing in the top 10


def test_check_golds_flags_a_gold_no_chunk_matches():
    questions = [{"id": "q", "gold": [{"path": "docs/a.md", "contains": "gone"}]}]
    assert check_golds(questions, [_node("still here")]) == ["q: {'path': 'docs/a.md', 'contains': 'gone'}"]


def test_every_question_in_the_set_still_matches_the_real_docs():
    """If this fails, a doc was edited under a question: fix the question's gold."""
    questions = load_questions()
    assert len({q["id"] for q in questions}) == len(questions)
    assert check_golds(questions, chunk_documents(load_documents())) == []
