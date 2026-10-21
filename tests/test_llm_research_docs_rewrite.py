import json

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, Usage
from src.llm.research_docs import rewrite
from src.llm.research_docs.rewrite import (N_REWRITES, PURPOSE, SYSTEM, Rewriter, Rewrites, clean, pool,
                                           pooled_search)


class FakeClient:
    def __init__(self, *rewrites: str):
        self.reply, self.calls = Rewrites(rewrites=list(rewrites)), []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return Reply(text=self.reply.model_dump_json(), parsed=self.reply, usage=Usage(300, 40, 0, 340),
                     finish_reason="STOP")


def _hits(*ids: str) -> list[NodeWithScore]:
    return [NodeWithScore(node=TextNode(id_=i, text=f"text {i}"), score=1.0) for i in ids]


def test_clean_drops_blanks_repeats_and_the_question_itself_and_keeps_at_most_n():
    assert clean("Q?", ["  a b ", "", "A B", "q?", "c"]) == ["a b", "c"]
    assert clean("Why was  B5\ndropped?", ["why was B5 dropped", "Why was B5 retired?"]) == ["Why was B5 retired?"]
    assert len(clean("Q?", [f"r{n}" for n in range(N_REWRITES + 2)])) == N_REWRITES
    assert f"Write {N_REWRITES} other wordings" in SYSTEM  # the count the model is told is the one kept


def test_every_question_gets_one_call_whose_rewordings_are_cached(tmp_path):
    cache, q = tmp_path / "rewrites.json", "Why was B5 dropped?"
    client = FakeClient("Why was baseline B5 removed?", "B5 retired reason")
    assert Rewriter(lambda: client, cache)(q) == ["Why was baseline B5 removed?", "B5 retired reason"]
    [(prompt, kwargs)] = client.calls
    assert prompt == q
    assert kwargs == {"purpose": PURPOSE, "system": SYSTEM, "response_schema": Rewrites, "temperature": 0.0}

    def no_client():  # all cached: no client made, so no API key needed
        raise AssertionError("no client is needed")

    assert Rewriter(no_client, cache)(q) == ["Why was baseline B5 removed?", "B5 retired reason"]
    assert json.loads(cache.read_text())[q]["rewrites"] == ["Why was baseline B5 removed?", "B5 retired reason"]


def test_the_pool_joins_each_querys_candidates_in_order_each_chunk_once(monkeypatch):
    results = {"q": _hits("a", "b"), "r1": _hits("b", "c"), "r2": _hits("d", "a")}
    seen = []

    def fake_hybrid(index, keywords, question, k):
        seen.append((question, k))
        return results[question]

    monkeypatch.setattr(rewrite, "hybrid_search", fake_hybrid)
    assert [h.node.node_id for h in pool(None, None, ["q", "r1", "r2"], depth=7)] == ["a", "b", "c", "d"]
    assert seen == [("q", 7), ("r1", 7), ("r2", 7)]


def test_the_pool_is_reranked_against_the_original_question_not_the_rewordings(monkeypatch):
    monkeypatch.setattr(rewrite, "hybrid_search", lambda index, keywords, question, k: _hits(f"{question}-hit"))
    scored = []

    def score(pairs):
        scored.extend(pairs)
        return [float(t.endswith("r1-hit")) for _, t in pairs]  # the rewording's find is the answer

    out = pooled_search(None, None, score, lambda q: ["r1", "r2"], "q", k=2)
    assert {question for question, _ in scored} == {"q"} and len(scored) == 3
    assert [h.node.node_id for h in out] == ["r1-hit", "q-hit"]  # ties keep the pool's order
    with pytest.raises(ValueError):
        pooled_search(None, None, score, lambda q: [], "q", k=0)
