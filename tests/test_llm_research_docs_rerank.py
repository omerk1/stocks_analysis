import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.research_docs import rerank as rr
from src.llm.research_docs.rerank import rerank, rerank_search


def _hit(nid: str, text: str, score: float = 0.0) -> NodeWithScore:
    node = TextNode(id_=nid, text=text, metadata={"path": f"docs/{nid}.md", "section": f"Sec {nid}"})
    return NodeWithScore(node=node, score=score)


HITS = [_hit("a", "alpha", 0.9), _hit("b", "beta answer", 0.8), _hit("c", "gamma", 0.7)]


def _by_word(word: str):
    """A fake cross-encoder: 1 if the chunk text contains `word`, else 0; records its input."""
    seen = []

    def score(pairs):
        seen.extend(pairs)
        return [float(word in text) for _, text in pairs]
    return score, seen


def test_rerank_orders_by_the_cross_encoders_score_not_the_retrievers():
    score, _ = _by_word("answer")
    out = rerank(score, "q?", HITS, k=3)
    assert [h.node.node_id for h in out] == ["b", "a", "c"]  # ties (a, c) keep hybrid's order
    assert [h.score for h in out] == [1.0, 0.0, 0.0]  # the score reported is the re-ranker's


def test_rerank_keeps_k_and_handles_no_hits():
    score, _ = _by_word("answer")
    assert [h.node.node_id for h in rerank(score, "q?", HITS, k=1)] == ["b"]
    assert rerank(score, "q?", [], k=5) == []
    with pytest.raises(ValueError):
        rerank(score, "q?", HITS, k=0)


def test_each_chunk_is_scored_with_the_question_and_its_heading_trail():
    score, seen = _by_word("answer")
    rerank(score, "which one?", HITS[:1], k=1)
    (question, text), = seen
    assert question == "which one?"
    assert "Sec a" in text and "alpha" in text  # embedded rendering: metadata + body


def test_rerank_search_scores_hybrids_top_depth(monkeypatch):
    calls = {}

    def fake_hybrid(index, keywords, question, k):
        calls["k"] = k
        return HITS
    monkeypatch.setattr(rr, "hybrid_search", fake_hybrid)
    score, seen = _by_word("gamma")
    out = rerank_search(None, None, score, "q?", k=2, depth=30)
    assert calls["k"] == 30 and len(seen) == 3
    assert [h.node.node_id for h in out] == ["c", "a"]
    rerank_search(None, None, score, "q?", k=40, depth=30)
    assert calls["k"] == 40  # never fewer candidates than asked for
