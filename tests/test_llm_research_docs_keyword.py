import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.research_docs import keyword
from src.llm.research_docs.keyword import KeywordIndex, fuse, hybrid_search, indexed_text, tokens


def _node(nid: str, text: str) -> TextNode:
    return TextNode(id_=nid, text=text, metadata={"path": f"docs/{nid}.md"})


NODES = [
    _node("a", "the sharpe ratio was used in the scorecard"),
    _node("b", "the the the slope of the moving average"),
    _node("c", "the slope slope slope tested on the moving average and the cost"),
    _node("d", "nothing relevant here at all, the end"),
]


def test_tokens_lowercase_and_split_snake_case():
    assert tokens("dist_pct_SMA_200 (h21)") == ["dist", "pct", "sma", "200", "h21"]


def test_a_rare_word_outranks_common_ones():
    index = KeywordIndex(NODES)
    assert index.search("was the sharpe ratio used?", k=4)[0].node.node_id == "a"
    # "the" is in every chunk, so its idf is far below a word only one chunk has
    assert index.idf["the"] < index.idf["sharpe"] / 10
    assert index.score("the")[0] < index.score("sharpe")[0] / 5


def test_indexed_text_keeps_headings_and_row_ids_but_not_path_keys_or_module():
    sec = TextNode(text="## Watch\nbody words", metadata={"path": "docs/STATUS.md", "section": "Status > Watch"})
    assert indexed_text(sec) == "Status > Watch\n## Watch\nbody words"  # own heading twice: a title boost
    row = TextNode(text="notes: slope", metadata={"path": "docs/E.csv", "section": "row 63", "module": "M5",
                                                  "cell_id": "breadth_top", "tier": "4", "outcome": "no_effect"})
    assert indexed_text(row) == "breadth_top\nnotes: slope"
    trial = TextNode(text="notes: x", metadata={"path": "docs/T.csv", "section": "row 2", "trial_id": "S1b_k20",
                                                "experiment_id": "S1b"})
    assert indexed_text(trial) == "S1b_k20\nS1b\nnotes: x"
    index = KeywordIndex([sec, row, trial])
    assert not index.search("docs status", k=3)[1:]  # "status" from the heading only, not the path
    assert not index.search("63 4 m5 effect", k=3)  # row placeholder, tier, module, outcome
    assert KeywordIndex([_node("p", "--- | ---")]).search("x", k=1) == []


def test_repeats_help_and_chunks_sharing_no_word_are_left_out():
    hits = KeywordIndex(NODES).search("slope", k=4)
    assert [h.node.node_id for h in hits] == ["c", "b"]
    with pytest.raises(ValueError):
        KeywordIndex(NODES).search("slope", k=0)


def test_fuse_rewards_agreement_and_keeps_one_sided_hits():
    a, b, c = (NodeWithScore(node=n, score=1.0) for n in NODES[:3])
    fused = fuse([[a, b], [b, c]], k=3)
    assert [h.node.node_id for h in fused] == ["b", "a", "c"]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert len(fuse([[a, b], [b, c]], k=1)) == 1


def test_hybrid_search_fuses_vector_and_keyword_lists(monkeypatch):
    vec = [NodeWithScore(node=NODES[3], score=0.9), NodeWithScore(node=NODES[0], score=0.8)]
    monkeypatch.setattr(keyword, "search", lambda index, question, k: vec[:k])
    hits = hybrid_search(None, KeywordIndex(NODES), "sharpe ratio", k=2)
    assert [h.node.node_id for h in hits] == ["a", "d"]  # in both lists beats top of one
