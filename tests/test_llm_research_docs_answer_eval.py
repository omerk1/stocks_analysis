import json

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, ShapeError, Usage
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


def test_the_prompt_id_names_the_clients_model(tmp_path):
    import src.llm.research_docs.answer_eval as answer_eval
    client = FakeClient(Answer(in_docs=True, answer="Too fragile [1]."))
    client.model = "another-model"
    [row] = run([Q], _find(GOLD), client, tmp_path / "run.json")
    assert row["prompt"] == answer_eval.prompt_id("another-model") != answer_eval.prompt_id()


def test_a_record_names_the_prompt_and_a_run_wont_mix_two(monkeypatch, tmp_path, capsys):
    import src.llm.research_docs.answer_eval as answer_eval
    out, client = tmp_path / "run.json", FakeClient(Answer(in_docs=True, answer="Too fragile [1]."))
    [row] = run([Q], _find(GOLD), client, out)
    assert row["prompt"] == answer_eval.prompt_id() and row["prompt"] == record(MULTI, _answered("x", GOLD))["prompt"]
    assert score([row], {"support": {}, "answers": {}}).startswith(f"prompt: {row['prompt']}\n")
    # only line breaks change: the model sees a different prompt, so the id changes
    monkeypatch.setattr(answer_eval, "SYSTEM", answer_eval.SYSTEM.replace("\n", " "))
    assert answer_eval.prompt_id() != row["prompt"]
    with pytest.raises(ValueError, match="another setup \\(prompt "):
        run([Q, MULTI], _find(GOLD), client, out)
    assert client.calls == 1
    assert run([Q], _find(GOLD), client, out) == [row]  # nothing left to answer: no calls, so no refusal
    assert client.calls == 1 and "nothing was re-run" in capsys.readouterr().err
    empty = {"support": {}, "answers": {}}
    assert "MIXED" in score([row, record(MULTI, _answered("x", GOLD))], empty)
    old = {k: v for k, v in row.items() if k != "prompt"}  # a row from before prompt ids
    assert score([old], empty).startswith("prompt: unrecorded\n")


def test_a_run_gives_k_sources_and_wont_mix_two_source_counts(tmp_path):
    out, client = tmp_path / "run.json", FakeClient(Answer(in_docs=True, answer="Too fragile [2]."))
    [row] = run([Q], _find(OTHER, GOLD, OTHER), client, out, k=2)
    assert [s["n"] for s in row["sources"]] == [1, 2] and row["retrieval"] == "full"
    with pytest.raises(ValueError, match=r"another setup \(k=2\)"):
        run([Q, MULTI], _find(OTHER, GOLD, OTHER), client, out, k=3)
    assert client.calls == 1
    assert run([Q, MULTI], _find(OTHER, GOLD, OTHER), client, out, k=2)[1]["id"] == "both"  # same k resumes
    assert "sources per answer: 2\n" in score([row], {"support": {}, "answers": {}})
    old = {k: v for k, v in row.items() if k != "k"}  # a row from before `k` was recorded
    assert "sources per answer: 5\n" in score([old], {"support": {}, "answers": {}})  # asked for 5, got 2


def test_a_split_run_records_what_it_searched_and_wont_mix_with_an_unsplit_one(tmp_path):
    out, client = tmp_path / "run.json", FakeClient(Answer(in_docs=True, answer="Too fragile [1]."))
    searched, splits = [], []

    def find(question, k):
        searched.append(question)
        return [NodeWithScore(node=GOLD if question == "B5?" else OTHER, score=1.0)]

    def splitter(q):
        splits.append(q)
        return ["B1?", "B5?"]

    [row] = run([MULTI], find, client, out, splitter=splitter)
    assert row["search"] == "split" and row["sub_questions"] == ["B1?", "B5?"] == searched  # what was searched
    assert splits == [MULTI["question"]]  # split once, not again to record it
    assert [s["cite"] for s in row["sources"]] == ["docs/x.md > #79", "docs/x.md > Baselines"]
    assert row["retrieval"] == "full"

    def failing(q):
        raise ShapeError("reply doesn't match Split: plain text")

    with pytest.raises(ShapeError):  # the split's failure, not the answer's: stops the run, nothing stored
        run([Q], find, client, tmp_path / "failed.json", splitter=failing)
    assert not (tmp_path / "failed.json").exists() and client.calls == 1
    with pytest.raises(ValueError, match=r"another setup \(search split\)"):
        run([MULTI, Q], _find(GOLD), client, out)
    assert "search: split\n" in score([row], {"support": {}, "answers": {}})
    [plain] = run([Q], _find(GOLD), client, tmp_path / "plain.json")
    assert "search" not in plain and "search: rerank\n" in score([plain], {"support": {}, "answers": {}})


def test_an_unusable_reply_is_stored_counted_wrong_and_the_run_goes_on(tmp_path):
    from src.llm.gemini import ShapeError

    class Flaky(FakeClient):
        def generate(self, prompt, **kwargs):
            if "Why was B5 dropped?" in prompt:
                self.calls += 1
                raise ShapeError("reply doesn't match Answer: plain text")
            return super().generate(prompt, **kwargs)

    searches = []

    def find(question, k):
        searches.append(question)
        return _find(GOLD, OTHER)(question, k)

    out, client = tmp_path / "run.json", Flaky(Answer(in_docs=True, answer="Too fragile [1]."))
    bad, good = run([Q, MULTI], find, client, out)
    assert len(searches) == 2  # the failed reply's sources are the ones retrieved, not a second search
    assert client.calls == 2 and bad["error"].startswith("reply doesn't match") and bad["answer"] == ""
    assert bad["retrieval"] == "full" and [s["n"] for s in bad["sources"]] == [1, 2]  # what it was shown
    assert run([Q, MULTI], _find(GOLD, OTHER), client, out) == [bad, good] and client.calls == 2  # not retried
    empty = {"support": {}, "answers": {}}
    assert packets([bad], empty, {"b5": Q}, [GOLD]) == {"support": [], "correctness": []}
    table = score([bad, good], empty)
    assert "b5" in table.splitlines()[4] and " wrong " in table.splitlines()[4] and "generation" in table.splitlines()[4]
    assert "NO USABLE REPLY (counted wrong, generation): b5" in table and "UNJUDGED answers: both" in table
    assert "mechanical citation problems (check): 0 answers" in table


def test_a_cut_off_reply_stops_the_run_so_a_resume_retries_it(tmp_path):
    from src.llm.gemini import ReplyError

    class CutOff(FakeClient):
        def generate(self, prompt, **kwargs):
            if "Why was B5 dropped?" in prompt and not self.calls:
                self.calls += 1
                raise ReplyError("reply cut off at max_output_tokens=2000")
            return super().generate(prompt, **kwargs)

    out, client = tmp_path / "run.json", CutOff(Answer(in_docs=True, answer="Too fragile [1]."))
    with pytest.raises(ReplyError, match="cut off"):
        run([Q, MULTI], _find(GOLD, OTHER), client, out)
    assert not out.exists()  # nothing stored for it
    rows = run([Q, MULTI], _find(GOLD, OTHER), client, out)
    assert [r["id"] for r in rows] == ["b5", "both"] and not any("error" in r for r in rows)


def test_the_prompt_id_follows_what_the_model_sees_not_the_code(monkeypatch):
    import src.llm.research_docs.answer_eval as answer_eval
    before = answer_eval.prompt_id()
    real = answer_eval.build_prompt

    def same_message(question, sources):
        """A reworded docstring the model never sees."""
        return real(question, sources)

    monkeypatch.setattr(answer_eval, "build_prompt", same_message)
    assert answer_eval.prompt_id() == before
    monkeypatch.setattr(answer_eval, "build_prompt", lambda q, s: real(q, s).replace("Sources:", "Excerpts:"))
    assert answer_eval.prompt_id() != before


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
    from src.llm.research_docs.answer_eval import sources_key
    out = score([r], {"support": {}, "answers": {answer_key(r): {"verdict": "partial", "miss": "retrieval",
                                                                 "miss_sources": sources_key(r)}}})
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
    path.write_text(json.dumps({"support": {}, "answers": {"b": {"verdict": "partial", "miss": "retrieval"}}}))
    with pytest.raises(ValueError, match="b"):  # an override not pinned to its sources
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


def test_a_chunk_cut_under_one_gold_still_shows_under_another():
    from src.llm.research_docs.answer_eval import gold_texts
    rows = [_node(f"r{i}", f"row {i}", cell_id="c") for i in range(3)]
    q = {"id": "x", "question": "?", "gold": [{"path": "docs/x.md", "cell_id": "c"},
                                               {"path": "docs/x.md", "contains": "row 2"}]}
    [shown] = gold_texts(q, rows, per_gold=1)
    assert len(shown) == 3
    assert shown[0]["text"].endswith("row 0") and "+2 more" in shown[1]["text"]
    assert shown[2]["text"].endswith("row 2")


def test_a_hand_set_miss_applies_only_to_the_sources_it_was_made_for():
    from src.llm.research_docs.answer_eval import sources_key
    r = record(Q, _answered("Too fragile [1].", GOLD))
    other = record(Q, _answered("Too fragile [1].", GOLD, OTHER))
    assert answer_key(r) == answer_key(other)  # the correctness verdict carries over
    ledger = {"support": {}, "answers": {answer_key(r): {"verdict": "partial", "miss": "retrieval",
                                                         "miss_sources": sources_key(r)}}}
    assert "1 retrieval, 0 generation" in score([r], ledger)
    assert "0 retrieval, 1 generation" in score([other], ledger)


def test_only_answers_that_cite_something_count_toward_clean():
    uncited = record(Q, _answered("Too fragile.", GOLD))
    r = record(Q, _answered("Too fragile [1].", GOLD))
    ledger = {"support": {claims(r)[0]["key"]: {"verdict": "supported"}}, "answers": {}}
    assert "every cited sentence supported: 1 of 1 that cite" in score([uncited, r], ledger)


def test_packets_refuse_a_row_whose_question_left_the_dev_split():
    r = record(Q, _answered("Too fragile [1].", GOLD))
    with pytest.raises(ValueError, match="b5"):
        packets([r], {"support": {}, "answers": {}}, {}, [GOLD])


def test_the_ledger_refuses_a_miss_on_a_correct_answer(tmp_path):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"support": {}, "answers": {"a": {"verdict": "correct", "miss": "retrieval"}}}))
    with pytest.raises(ValueError, match="a"):
        load_ledger(path)
