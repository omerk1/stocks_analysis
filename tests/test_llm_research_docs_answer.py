import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, Usage
from src.llm.research_docs.answer import (PURPOSE, SYSTEM, Answer, answer, build_prompt, check, cited,
                                          format_answered, sentences)


def _hit(nid: str, text: str, meta: dict) -> NodeWithScore:
    return NodeWithScore(node=TextNode(id_=nid, text=text, metadata={"path": "docs/x.md", **meta}), score=1.0)


SOURCES = [_hit("a", "B5 was dropped as too fragile.", {"section": "Baselines"}),
           _hit("b", "Entry #79 retired B1.", {"entry": "#79"})]


class FakeClient:
    def __init__(self, reply: Answer):
        self.reply, self.calls = reply, []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return Reply(text=self.reply.model_dump_json(), parsed=self.reply,
                     usage=Usage(100, 20, 0, 120), finish_reason="STOP")


def test_the_prompt_numbers_each_source_with_where_it_comes_from():
    prompt = build_prompt("Why was B5 dropped?", SOURCES)
    assert prompt.startswith("Question: Why was B5 dropped?")
    assert "[1] docs/x.md > Baselines\n" in prompt and "B5 was dropped as too fragile." in prompt
    assert "[2] docs/x.md > #79\n" in prompt and "Entry #79 retired B1." in prompt


def test_the_prompt_keeps_an_experiment_rows_ids_that_live_in_metadata():
    row = _hit("r", "point_estimate: -0.004", {"cell_id": "dist_h21", "tier": "3", "outcome": "weak"})
    prompt = build_prompt("What tier did dist_h21 get?", [row])
    assert "tier: 3" in prompt and "outcome: weak" in prompt and "point_estimate: -0.004" in prompt


@pytest.mark.parametrize("text, want", [
    ("Fragile [1]. Retired [2].", [1, 2]),
    ("Both [2][1], again [1].", [2, 1]),
    ("Listed [1, 3].", [1, 3]),
    ("A range [1-3], another [4\u20135].", [1, 2, 3, 4, 5]),
    ("Reversed [3-2], a span [2010-2021], huge [1-10000000].", [2, 3, 2010, 2021, 1, 10000000]),
    ("No citation, and a year [2021 is not one] nor is [a].", []),
])
def test_cited_reads_every_citation_form(text, want):
    assert cited(text) == want


def test_check_flags_a_made_up_source_and_an_uncited_in_docs_answer():
    assert check(Answer(in_docs=True, answer="Fragile [1]."), 2) == []
    assert check(Answer(in_docs=True, answer="Fragile [3]."), 2) == ["cites [3], but only [1]-[2] were given"]
    assert check(Answer(in_docs=True, answer="Fragile."), 2) == ["says the docs answer it but cites no source"]
    assert check(Answer(in_docs=False, answer="The docs don't say."), 2) == []  # no citation needed


@pytest.mark.parametrize("text, want", [
    ("One [1]. Two [2].", ["One [1].", "Two [2]."]),
    ("One. [1] Two.[2][1] Three!", ["One [1].", "Two[2][1].", "Three!"]),
    ("Sharpe 0.18, e.g. the picks [1]. Next [2].", ["Sharpe 0.18, e.g. the picks [1].", "Next [2]."]),
])
def test_sentences_keep_citations_written_after_the_full_stop(text, want):
    assert sentences(text) == want


def test_check_flags_each_uncited_sentence_of_an_in_docs_answer():
    # the real reply that stretched a source on short selling into one on short interest
    stretched = ("The sources do not explicitly state whether short interest has been tested. "
                 "However, they mention that shorting needs a borrow check [2].")
    assert check(Answer(in_docs=True, answer=stretched), 5) == [
        "sentence 1 cites no source: 'The sources do not explicitly state whether short interest has been tested.'"]
    assert check(Answer(in_docs=False, answer=stretched), 5) == []


def test_answer_sends_sources_with_the_rules_as_structured_temperature_zero_call():
    client = FakeClient(Answer(in_docs=True, answer="It was too fragile [1]."))
    out = answer("Why was B5 dropped?", lambda q, k: SOURCES[:k], client, k=2)
    [(prompt, kwargs)] = client.calls
    assert "[2] docs/x.md > #79" in prompt
    assert kwargs == {"purpose": PURPOSE, "system": SYSTEM, "response_schema": Answer, "temperature": 0.0}
    assert out.answer.answer == "It was too fragile [1]." and out.problems == []
    shown = format_answered(out)
    assert "[1]* docs/x.md > Baselines" in shown and "[2]  docs/x.md > #79" in shown


def test_a_not_in_the_docs_reply_is_shown_as_such_and_no_sources_is_an_error():
    out = answer("Ichimoku?", lambda q, k: SOURCES, FakeClient(Answer(in_docs=False, answer="Not covered.")))
    assert format_answered(out).startswith("(not in the docs)\nNot covered.")
    with pytest.raises(ValueError):
        answer("q", lambda q, k: [], FakeClient(Answer(in_docs=False, answer="x")))
