import json

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, Usage
from src.llm.research_docs.split import (MAX_PARTS, PURPOSE, SYSTEM, Split, Splitter, clean, may_have_parts, merge,
                                         split_search)


class FakeClient:
    def __init__(self, *subs: str):
        self.reply, self.calls = Split(sub_questions=list(subs)), []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return Reply(text=self.reply.model_dump_json(), parsed=self.reply, usage=Usage(300, 40, 0, 340),
                     finish_reason="STOP")


def _hits(*ids: str) -> list[NodeWithScore]:
    return [NodeWithScore(node=TextNode(id_=i, text=i), score=1.0) for i in ids]


@pytest.mark.parametrize("question, want", [
    ("dist_pct_sma_200_h21 result?", False),
    ("Why does the holdout start in 2022?", False),
    ("Do we use stops and sizing?", True),
    ("Did we look at crypto or futures?", True),
    ("Is it used in the model and/or analysis?", True),
    ("adjusted vs raw?", True),
    ("Was it tested, and what happened?", True),
    ("Does the brand matter?", False),  # "and" inside a word isn't a joiner
])
def test_only_a_question_with_a_joining_word_may_have_parts(question, want):
    assert may_have_parts(question) is want


def test_a_question_with_nothing_to_split_is_searched_as_it_is_with_no_call():
    def no_client():
        raise AssertionError("no client is needed")

    assert Splitter(no_client)("Why does the holdout start in 2022?") == ["Why does the holdout start in 2022?"]


def test_a_question_judged_single_is_searched_in_its_own_words_not_the_models():
    client = FakeClient("What did we pick, adjusted or raw prices, and why?")
    q = "which price basis did we pick (adjusted vs raw) and why?"
    assert Splitter(lambda: client)(q) == [q]
    [(prompt, kwargs)] = client.calls
    assert prompt == q
    assert kwargs == {"purpose": PURPOSE, "system": SYSTEM, "response_schema": Split, "temperature": 0.0}


def test_a_split_is_cached_so_the_same_question_gets_the_same_split_without_a_call(tmp_path):
    cache = tmp_path / "splits.json"
    q = "Do we use stops and sizing?"
    first = FakeClient("Do we use stops?", "Do we use sizing?")
    assert Splitter(lambda: first, cache)(q) == ["Do we use stops?", "Do we use sizing?"]

    def no_client():  # all cached: no client made, so no API key needed
        raise AssertionError("no client is needed")

    assert Splitter(no_client, cache)(q) == ["Do we use stops?", "Do we use sizing?"]
    stored = json.loads(cache.read_text())[q]
    stored["prompt"] = "an older prompt"  # a split made by other instructions is made again
    cache.write_text(json.dumps({q: stored}))
    again = FakeClient("something else", "entirely")
    assert Splitter(lambda: again, cache)(q) == ["something else", "entirely"]


def test_a_cached_split_is_cleaned_like_a_fresh_reply(tmp_path):
    import src.llm.research_docs.split as split
    cache = tmp_path / "splits.json"
    cache.write_text(json.dumps({q: {"prompt": split.prompt_id(), "sub_questions": subs} for q, subs in
                                 (("A and B?", []), ("C or D?", ["C or D, reworded?"]), ("E, F?", [" E? ", "F?"]))}))
    splitter = Splitter(lambda: None, cache)
    assert [splitter(q) for q in ("A and B?", "C or D?", "E, F?")] == [["A and B?"], ["C or D?"], ["E?", "F?"]]
    splitter("E, F?").append("G?")  # a copy: the cache keeps what was stored
    assert splitter("E, F?") == ["E?", "F?"]


def test_the_cap_the_model_is_told_is_the_one_clean_keeps():
    # so changing MAX_PARTS changes the prompt, hence `prompt_id`, and the cache is made again
    assert f"At most {MAX_PARTS} questions." in SYSTEM


def test_the_client_must_run_the_model_the_cache_is_keyed_by():
    client = FakeClient("A?", "B?")
    client.model = "another-model"
    splitter = Splitter(lambda: client)
    for _ in range(2):  # and still on the next question: a caught error doesn't let it through
        with pytest.raises(ValueError, match="another-model"):
            splitter("A and B?")
    assert client.calls == []


def test_clean_drops_blanks_and_repeats_and_keeps_at_most_max_parts(capsys):
    assert clean("q?", ["  A? ", "", "a?", "B?"]) == ["A?", "B?"]
    assert clean("q?", ["A?", " a? "]) == ["q?"]  # one left: the original
    assert capsys.readouterr().err == ""
    assert clean("q?", [f"{n}?" for n in range(MAX_PARTS + 2)]) == [f"{n}?" for n in range(MAX_PARTS)]
    assert f"searching the first {MAX_PARTS}" in capsys.readouterr().err  # what was cut is said


def test_merge_takes_each_lists_best_in_turn_skipping_chunks_already_taken():
    merged = merge([_hits("a1", "a2", "a3"), _hits("b1", "a1", "b3"), _hits("c1")], k=5)
    assert [h.node.node_id for h in merged] == ["a1", "b1", "c1", "a2", "a3"]
    assert [h.node.node_id for h in merge([_hits("a"), _hits("a")], k=5)] == ["a"]


def test_split_search_searches_each_part_and_an_unsplit_question_once():
    searched = []

    def find(q, k):
        searched.append((q, k))
        return _hits(*(f"{q}{n}" for n in range(k)))

    out = split_search(find, lambda q: ["x", "y"], "x and y?", 3)
    assert searched == [("x", 3), ("y", 3)] and [h.node.node_id for h in out] == ["x0", "y0", "x1"]
    searched.clear()
    assert [h.node.node_id for h in split_search(find, lambda q: [q], "z?", 2)] == ["z?0", "z?1"]
    assert searched == [("z?", 2)]
