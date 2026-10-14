import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.llm.gemini import Reply, Usage
from src.llm.research_docs.answer import (PURPOSE, SYSTEM, Answer, answer, build_prompt, check, cited,
                                          format_answered)


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
    assert "[1] docs/x.md > Baselines\nB5 was dropped as too fragile." in prompt
    assert "[2] docs/x.md > #79\nEntry #79 retired B1." in prompt


@pytest.mark.parametrize("text, want", [
    ("Fragile [1]. Retired [2].", [1, 2]),
    ("Both [2][1], again [1].", [2, 1]),
    ("Listed [1, 3].", [1, 3]),
    ("No citation, and a year [2021 is not one] nor is [a].", []),
])
def test_cited_reads_every_citation_form(text, want):
    assert cited(text) == want


def test_check_flags_a_made_up_source_and_an_uncited_in_docs_answer():
    assert check(Answer(in_docs=True, answer="Fragile [1]."), 2) == []
    assert check(Answer(in_docs=True, answer="Fragile [3]."), 2) == ["cites [3], but only [1]-[2] were given"]
    assert check(Answer(in_docs=True, answer="Fragile."), 2) == ["says the docs answer it but cites no source"]
    assert check(Answer(in_docs=False, answer="The docs don't say."), 2) == []  # no citation needed


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
