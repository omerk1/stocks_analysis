import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.research_docs import diversify as dv
from src.llm.research_docs.diversify import mmr, mmr_search


def _hit(nid: str, score: float) -> NodeWithScore:
    return NodeWithScore(node=TextNode(id_=nid, text=nid, metadata={"path": f"docs/{nid}.md"}), score=score)


# a and a2 are near-copies; b and c point elsewhere. Unit vectors, so dot = cosine.
VECTORS = {"a": [1.0, 0.0, 0.0], "a2": [0.99, 0.141, 0.0], "b": [0.0, 1.0, 0.0], "c": [0.0, 0.0, 1.0]}
HITS = [_hit("a", 9.0), _hit("a2", 8.5), _hit("b", 8.0), _hit("c", 0.0)]


def _ids(hits):
    return [h.node.node_id for h in hits]


def test_a_near_copy_gives_way_to_a_close_runner_up():
    out = mmr(HITS, VECTORS, k=3)
    assert _ids(out) == ["a", "b", "a2"]  # a2 trails a by little, but repeats it
    assert [h.score for h in out] == [9.0, 8.0, 8.5]  # the re-ranker's scores are kept


def test_a_clear_relevance_gap_beats_diversity():
    # c is the most different chunk but far less relevant: it never jumps the queue
    assert _ids(mmr(HITS, VECTORS, k=4))[-1] == "c"


def test_the_top_chunk_is_always_first_and_lambda_one_is_plain_reranking():
    assert _ids(mmr(HITS, VECTORS, k=1)) == ["a"]
    assert _ids(mmr(HITS, VECTORS, k=4, lam=1.0)) == ["a", "a2", "b", "c"]


def test_mmr_handles_few_hits_equal_scores_and_bad_k():
    assert mmr([], VECTORS, k=5) == []
    assert _ids(mmr(HITS[:1], VECTORS, k=5)) == ["a"]
    flat = [_hit("b", 1.0), _hit("c", 1.0)]  # no spread to scale: order kept
    assert _ids(mmr(flat, VECTORS, k=2)) == ["b", "c"]
    with pytest.raises(ValueError):
        mmr(HITS, VECTORS, k=0)


def test_mmr_search_diversifies_the_reranked_candidates(monkeypatch):
    calls = {}

    def fake_hybrid(index, keywords, question, k):
        calls["k"] = k
        return [_hit(h.node.node_id, 0.0) for h in reversed(HITS)]  # hybrid's order is wrong
    monkeypatch.setattr(dv, "hybrid_search", fake_hybrid)
    scores = {h.node.node_id: h.score for h in HITS}

    def score(pairs):  # a fake cross-encoder that recovers HITS' scores from the chunk text
        return [next(s for nid, s in scores.items() if text.endswith(nid)) for _, text in pairs]
    out = mmr_search(None, None, score, VECTORS, "q?", k=3, depth=30)
    assert calls["k"] == 30
    assert _ids(out) == ["a", "b", "a2"]
    calls.clear()
    with pytest.raises(ValueError):
        mmr_search(None, None, score, VECTORS, "q?", k=0)
    assert calls == {}
