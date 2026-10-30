import json
from datetime import date, datetime, timezone

import httpx
import pytest
from llama_index.core.schema import NodeRelationship, NodeWithScore, RelatedNodeInfo, TextNode

from src.llm.gemini import BudgetExceeded, DailyCapExceeded, Reply, ReplyError, Usage
from src.llm.research_docs.answer import Answer
from src.llm.research_docs.ask import (FallbackRewriter, Staleness, append_log, ask, format_asked, format_staleness,
                                       log_entry, stale)
from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.load import load_documents

BUILT = date(2026, 10, 17)


def _node(nid: str, path: str, file_hash: str, text: str = "B5 was dropped.") -> TextNode:
    return TextNode(id_=nid, text=text, metadata={"path": path, "section": "Baselines"},
                    relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=path, hash=file_hash)})


SOURCES = [NodeWithScore(node=_node("a", "docs/a.md", "h1", "B5 was dropped as too fragile."), score=1.0),
           NodeWithScore(node=_node("b", "docs/b.md", "h2", "Entry #79 retired B1."), score=0.5)]


class FakeClient:
    def __init__(self, reply: Answer | None = None, fail: Exception | None = None):
        self.reply, self.fail, self.calls = reply, fail, []

    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        if self.fail:
            raise self.fail
        return Reply(text=self.reply.model_dump_json(), parsed=self.reply,
                     usage=Usage(100, 20, 0, 120), finish_reason="STOP")


def _search(q, k):
    return SOURCES[:k]


def test_stale_lists_changed_new_and_deleted_files():
    nodes = [_node("1", "docs/a.md", "h1"), _node("2", "docs/a.md", "h1"), _node("3", "docs/b.md", "h2"),
             _node("4", "docs/gone.md", "h3")]
    s = stale(nodes, {"docs/a.md": "h1", "docs/b.md": "NEW", "docs/c.md": "h4"}, BUILT)
    assert (s.changed, s.added, s.removed) == (["docs/b.md"], ["docs/c.md"], ["docs/gone.md"])
    assert s and not stale(nodes[:3], {"docs/a.md": "h1", "docs/b.md": "h2"}, BUILT)


def test_a_chunk_keeps_the_hash_load_documents_gives_its_file(tmp_path):
    # the staleness check rests on this: the hash stored at build time is the one the
    # loader computes now for the same file, and an edit changes it
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\n\n## One\n\nFirst section.\n\n## Two\n\nSecond section.\n")
    nodes = chunk_documents(load_documents(root))
    assert len(nodes) > 1
    current = {d.doc_id: d.hash for d in load_documents(root)}
    assert not stale(nodes, current, BUILT)
    (root / "a.md").write_text("# A\n\n## One\n\nEdited.\n")
    assert stale(nodes, {d.doc_id: d.hash for d in load_documents(root)}, BUILT).changed == ["docs/a.md"]


def test_the_warning_names_every_file_and_the_rebuild_command():
    text = format_staleness(Staleness(BUILT, ["docs/done.md"], ["docs/new.md"], []))
    assert "index built 2026-10-17; 2 doc files differ" in text
    assert "changed: docs/done.md" in text and "not in the index: docs/new.md" in text
    assert "index build" in text
    assert format_staleness(Staleness(BUILT, [], [], [])) == "index built 2026-10-17, up to date"


def test_ask_answers_from_the_searched_sources():
    client = FakeClient(Answer(in_docs=True, answer="It was too fragile [1]."))
    a = ask("Why was B5 dropped?", _search, client, k=2)
    assert a.sources == SOURCES and a.error is None
    assert a.answered.problems == [] and a.answered.usage.total_tokens == 120
    assert "B5 was dropped as too fragile." in client.calls[0]


def test_a_daily_cap_refusal_keeps_the_sources_and_says_when_it_resets():
    refusal = DailyCapExceeded("299000 tokens used today; this call could take 10000 more, over the daily cap of 300000")
    a = ask("Why was B5 dropped?", _search, FakeClient(fail=refusal), k=2)
    assert a.answered is None and a.sources == SOURCES
    text = format_asked(a, Staleness(BUILT, [], [], []), 299_000, 300_000, show_text=True)
    assert "Not answered: 299000 tokens used today" in text and "The call wasn't sent" in text
    assert "resets at 00:00 UTC" in text
    assert "[1]  docs/a.md > Baselines" in text and "B5 was dropped as too fragile." in text
    assert "today 299,000 of 300,000 tokens" in text


def test_each_failure_gets_its_own_hint():
    per_call = ask("q", _search, FakeClient(fail=BudgetExceeded("prompt is 9000 tokens, over the per-call cap of 8000")))
    assert "try a lower -k" in format_asked(per_call, Staleness(BUILT, [], [], []), 0, 300_000)
    cut = ask("q", _search, FakeClient(fail=ReplyError("reply cut off at max_output_tokens=2000")), k=2)
    text = format_asked(cut, Staleness(BUILT, [], [], []), 0, 300_000)
    assert "Not answered: ReplyError: reply cut off" in text and "in the ledger" in text
    assert "[2]  docs/b.md > Baselines" in text


def test_a_bug_after_the_call_is_not_reported_as_a_failed_call():
    with pytest.raises(TypeError):
        ask("q", _search, FakeClient(fail=TypeError("a bug")))


def test_a_failed_rewording_call_leaves_the_question_alone(capsys):
    def rewriter(q):
        raise httpx.ConnectError("offline")
    fallback = FallbackRewriter(rewriter)
    assert fallback("q") == [] and fallback.error == "ConnectError: offline"
    assert "rewording failed (ConnectError: offline)" in capsys.readouterr().err
    def unwritable_cache(q):
        raise PermissionError("data/llm/ask_rewrites.json")
    with pytest.raises(PermissionError):  # a local error, not a failed call: don't hide it
        FallbackRewriter(unwritable_cache)("q")


def test_ask_rejects_a_bad_k_before_searching():
    def search(q, k):
        raise AssertionError("searched")
    with pytest.raises(ValueError):
        ask("q", search, FakeClient(), k=0)


def test_a_source_from_a_changed_file_is_marked_and_its_text_shown_on_request():
    a = ask("q", _search, FakeClient(Answer(in_docs=True, answer="Fragile [1]. Retired [2].")), k=2)
    s = Staleness(BUILT, ["docs/b.md"], [], [])
    text = format_asked(a, s, 1_000, 300_000, show_text=True)
    assert "[2]* docs/b.md > Baselines  (file changed since the build)" in text
    assert "[1]* docs/a.md > Baselines\n" in text and "      Entry #79 retired B1." in text
    assert "Entry #79 retired B1." not in format_asked(a, s, 1_000, 300_000)
    deleted = format_asked(a, Staleness(BUILT, [], [], ["docs/a.md"]), 1_000, 300_000)
    assert "[1]* docs/a.md > Baselines  (file deleted since the build)" in deleted


def test_the_log_gets_one_line_per_question(tmp_path):
    now = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
    s = Staleness(BUILT, ["docs/b.md"], ["docs/c.md"], [])
    answered = ask("q", _search, FakeClient(Answer(in_docs=True, answer="Fragile [1].")), k=2)
    refused = ask("q2", _search, FakeClient(fail=BudgetExceeded("cap")), k=1)
    path = tmp_path / "ask_log.jsonl"
    append_log(path, log_entry(answered, s, 2, False, now))
    append_log(path, log_entry(refused, s, 1, True, now, rewrite_error="ConnectError: offline"))
    first, second = [json.loads(line) for line in path.read_text().splitlines()]
    assert first["question"] == "q" and first["index_built"] == "2026-10-17" and first["stale_files"] == 2
    assert first["sources"][0]["outdated"] is None
    assert first["sources"][1] == {"cite": "docs/b.md > Baselines", "id": "b", "outdated": "changed"}
    assert (first["in_docs"], first["cited"], first["total_tokens"]) == (True, [1], 120)
    assert "rewrite_error" not in first and second["rewrite_error"] == "ConnectError: offline"
    assert second["error"].startswith("cap. The call wasn't sent") and second["rewrite"] and "answer" not in second
