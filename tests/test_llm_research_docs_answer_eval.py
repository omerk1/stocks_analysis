import json

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, Usage
from src.llm.research_docs.answer import Answer
from src.llm.research_docs.answer_eval import (answer_key, claims, load_ledger, miss, packets, record, retrieval,
                                               run, score)


def _node(nid: str, text: str, **meta) -> TextNode:
    return TextNode(id_=nid, text=text, metadata={"path": "docs/x.md", **meta})


GOLD = _node("g", "B5 was dropped as too fragile.", section="Baselines")
OTHER = _node("o", "Entry #79 retired B1.", entry="#79")
Q = {"id": "b5", "type": "section", "question": "Why was B5 dropped?",
     "gold": [{"path": "docs/x.md", "contains": "too fragile"}]}
MULTI = {"id": "both", "type": "section", "question": "B1 and B5?",
         "parts": [[{"path": "docs/x.md", "contains": "too fragile"}], [{"path": "docs/x.md", "entry": "#79"}]]}
NONE = {"id": "ichimoku", "type": "none", "question": "Ichimoku?", "gold": [], "answerable": False}


class FakeClient:
    def __init__(self, reply: Answer):
        self.reply, self.calls = reply, 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return Reply(text=self.reply.model_dump_json(), parsed=self.reply,
                     usage=Usage(100, 20, 0, 120), finish_reason="STOP")


def _find(*nodes):
    return lambda question, k: [NodeWithScore(node=n, score=1.0) for n in nodes][:k]


def test_retrieval_says_whether_the_sources_shown_hold_the_answer():
    assert retrieval(Q, [OTHER, GOLD]) == "full"
    assert retrieval(Q, [OTHER]) == "none"
    assert retrieval(MULTI, [GOLD]) == "partial"
    assert retrieval(MULTI, [GOLD, OTHER]) == "full"
    assert retrieval(NONE, [GOLD]) == "n/a"


def test_run_records_each_answer_and_resumes_without_paying_again(tmp_path):
    out, client = tmp_path / "run.json", FakeClient(Answer(in_docs=True, answer="Too fragile [2]."))
    rows = run([Q, MULTI], _find(OTHER, GOLD), client, out)
    assert client.calls == 2 and json.loads(out.read_text()) == rows
    assert rows[0]["retrieval"] == "full" and rows[0]["sources"][1]["gold_parts"] == [1]
    assert rows[1]["sources"][0]["gold_parts"] == [2] and rows[1]["n_parts"] == 2
    run([Q, MULTI, NONE], _find(OTHER, GOLD), client, out)
    assert client.calls == 3  # only the new question


def test_a_claim_key_follows_the_sentence_and_the_cited_text_not_the_source_number():
    a = record(Q, _answered("Too fragile [2]. Retired [1].", OTHER, GOLD))
    b = record(Q, _answered("Too fragile [1].", GOLD, OTHER))
    assert [c["sentence"] for c in claims(a)] == ["Too fragile [2].", "Retired [1]."]
    assert claims(a)[0]["key"] != claims(b)[0]["key"]  # "[2]" vs "[1]" in the sentence itself
    c = record(Q, _answered("Too fragile [1].", GOLD, OTHER))
    d = record(Q, _answered("Too fragile [1].", GOLD))
    assert claims(c)[0]["key"] == claims(d)[0]["key"]  # same sentence, same cited text
    e = record(Q, _answered("Too fragile [1].", OTHER))
    assert claims(e)[0]["key"] != claims(d)[0]["key"]  # same sentence, different source behind [1]


def test_a_citation_to_a_missing_source_is_left_to_check():
    r = record(Q, _answered("Too fragile [7].", GOLD))
    assert claims(r) == [] and r["problems"]


def test_packets_hide_the_golds_from_the_support_judge_and_skip_what_is_judged():
    r = record(Q, _answered("Too fragile [2].", OTHER, GOLD))
    p = packets([r], load_ledger(_missing()), {"b5": Q}, [GOLD, OTHER])
    assert "gold" not in json.dumps(p["support"]) and p["support"][0]["claims"][0]["cites"] == [2]
    [[gold]] = p["correctness"][0]["gold_parts"]  # one part, one matching chunk
    assert gold["cite"] == "docs/x.md > Baselines" and gold["text"].endswith("B5 was dropped as too fragile.")
    judged = {"support": {claims(r)[0]["key"]: {"verdict": "supported"}},
              "answers": {answer_key(r): {"verdict": "correct"}}}
    assert packets([r], judged, {"b5": Q}, [GOLD, OTHER]) == {"support": [], "correctness": []}


@pytest.mark.parametrize("q, nodes, verdict, want", [
    (Q, [GOLD], "correct", None),
    (Q, [GOLD], "wrong", "generation"),       # the answer was in front of it
    (Q, [OTHER], "wrong", "retrieval"),       # it wasn't
    (MULTI, [GOLD], "partial", "retrieval"),  # one part never retrieved
    (NONE, [GOLD], "wrong", "generation"),    # answered an unanswerable question
])
def test_miss_separates_retrieval_from_generation(q, nodes, verdict, want):
    assert miss(record(q, _answered("x [1].", *nodes)), verdict) == want


def test_a_hand_checked_miss_overrides_the_mechanical_split():
    r = record(Q, _answered("Too fragile [1].", GOLD))
    assert miss(r, "partial") == "generation" and miss(r, "partial", "retrieval") == "retrieval"
    assert miss(r, "correct", "retrieval") is None
    out = score([r], {"support": {}, "answers": {answer_key(r): {"verdict": "partial", "miss": "retrieval"}}})
    assert "1 retrieval, 0 generation" in out


def test_score_counts_unjudged_as_unjudged_not_as_passes():
    r = record(Q, _answered("Too fragile [1].", GOLD))
    out = score([r], {"support": {}, "answers": {}})
    assert "UNJUDGED answers: b5" in out and "1 unjudged" in out
    out = score([r], {"support": {claims(r)[0]["key"]: {"verdict": "supported"}},
                      "answers": {answer_key(r): {"verdict": "correct"}}})
    assert "answerable      1 questions: 1 correct" in out and "every cited sentence supported: 1 of 1" in out


def test_the_ledger_refuses_a_verdict_outside_the_scale(tmp_path):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"support": {"k": {"verdict": "yes"}}, "answers": {}}))
    with pytest.raises(ValueError, match="k"):
        load_ledger(path)
    path.write_text(json.dumps({"support": {}, "answers": {"a": {"verdict": "partial", "miss": "breadth"}}}))
    with pytest.raises(ValueError, match="a"):
        load_ledger(path)


def _missing():
    from pathlib import Path
    return Path("/nonexistent/answers.json")


def _answered(text: str, *nodes):
    from src.llm.research_docs.answer import answer
    return answer("q", _find(*nodes), FakeClient(Answer(in_docs=True, answer=text)))
