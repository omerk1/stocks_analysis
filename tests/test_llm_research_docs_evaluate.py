import pytest
from llama_index.core import Document

from src.llm.research_docs.chunk import chunk_documents
from src.llm.research_docs.evaluate import (
    METRICS, check_golds, first_hit, part_ranks, question_split, load_questions, matches, report, scores, stale_paths,
    unmatched_golds)
from src.llm.research_docs.load import load_documents


def _node(text="x", **meta):
    return Document(text=text, metadata={"path": "docs/a.md", "section": "S", **meta})


def test_matches_on_path_phrase_and_metadata():
    node = _node("B5 was  dropped\nas too fragile", entry="#47")
    assert matches(node, {"path": "docs/a.md"})
    assert matches(node, {"path": "docs/a.md", "contains": "b5 was dropped as too"})  # case, whitespace
    assert matches(node, {"path": "docs/a.md", "entry": "#47"})
    assert not matches(node, {"path": "docs/b.md"})
    assert not matches(node, {"path": "docs/a.md", "entry": "#48"})
    assert not matches(node, {"path": "docs/a.md", "contains": "kept"})
    combined = _node(entry="#16, #17")
    assert matches(combined, {"entry": "#17"}) and matches(combined, {"entry": "#16, #17"})
    assert not matches(combined, {"entry": "#1"})


def test_first_hit_is_the_rank_of_the_first_matching_node():
    nodes = [_node(entry="#1"), _node(entry="#2"), _node(entry="#3")]
    assert first_hit(nodes, [{"entry": "#2"}, {"entry": "#3"}]) == 2
    assert first_hit(nodes, [{"entry": "#9"}]) is None


def test_a_multi_part_question_ranks_where_its_last_part_is_found():
    nodes = [_node(entry="#1"), _node(entry="#2"), _node(entry="#3")]
    q = {"parts": [[{"entry": "#3"}], [{"entry": "#9"}, {"entry": "#1"}]]}
    assert part_ranks(nodes, q) == (3, 1)
    assert part_ranks(nodes, {"parts": [[{"entry": "#2"}], [{"entry": "#9"}]]}) == (None, 2)
    assert part_ranks(nodes, {"gold": [{"entry": "#2"}]}) == (2, 2)


def test_evaluate_records_a_miss_when_search_returns_nothing(monkeypatch):
    from src.llm.research_docs import evaluate as ev
    monkeypatch.setattr(ev, "search", lambda index, question, k: [])
    rows = ev.evaluate(None, [{"id": "q", "question": "?", "gold": [{"path": "docs/a.md"}]}])
    assert rows[0]["rank"] is None and rows[0]["top"] == "-" and rows[0]["score"] is None


def test_evaluate_records_the_top_hits_score(monkeypatch):
    from llama_index.core.schema import NodeWithScore
    from src.llm.research_docs import evaluate as ev
    hits = [NodeWithScore(node=_node(entry="#1"), score=0.9), NodeWithScore(node=_node(entry="#2"), score=0.6)]
    monkeypatch.setattr(ev, "search", lambda index, question, k: hits)
    rows = ev.evaluate(None, [{"id": "q", "question": "?", "gold": [{"path": "docs/a.md", "entry": "#2"}]}])
    assert rows[0]["rank"] == 2 and rows[0]["score"] == 0.9


def test_stale_paths_finds_edited_added_and_deleted_files():
    def n(path, text):
        return Document(text=text, metadata={"path": path})
    indexed = [n("a.md", "x"), n("a.md", "y"), n("b.md", "z"), n("c.md", "w")]
    assert stale_paths(indexed, list(reversed(indexed))) == []  # order doesn't matter
    current = [n("a.md", "x"), n("a.md", "y"), n("b.md", "z2"), n("d.md", "v")]
    assert stale_paths(indexed, current) == ["b.md", "c.md", "d.md"]
    # same text, changed metadata (e.g. a CSV row's outcome) is stale too
    retagged = Document(text="w", metadata={"path": "c.md", "outcome": "dead"})
    assert stale_paths(indexed, indexed[:3] + [retagged]) == ["c.md"]
    # same text and metadata, but a key moved out of the embedding: vectors differ, stale
    embedded = Document(text="w", metadata={"path": "c.md", "area": "x"})
    hidden = Document(text="w", metadata={"path": "c.md", "area": "x"}, excluded_embed_metadata_keys=["area"])
    assert stale_paths([embedded], [hidden]) == ["c.md"]


def test_unmatched_golds_say_whether_a_rebuild_would_fix_them():
    indexed = [_node("old wording")]
    current = [_node("new wording")]
    questions = [{"id": "ok", "gold": [{"path": "docs/a.md", "contains": "old"}]},
                 {"id": "moved", "gold": [{"path": "docs/a.md", "contains": "new"}]},
                 {"id": "typo", "gold": [{"path": "docs/a.md", "contains": "nwe"}]}]
    out = unmatched_golds(questions, indexed, current)
    assert len(out) == 2
    assert out[0].startswith("moved:") and out[0].endswith("(rebuild the index)")
    assert out[1].startswith("typo:") and out[1].endswith("(fix the gold)")


def test_scores_hit_at_k_and_mrr():
    rows = [{"rank": 1}, {"rank": 4}, {"rank": None}, {"rank": 2}]
    s = scores(rows + [{"rank": None, "answerable": False}])  # unanswerable: not a miss
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@5"] == 0.75 and s["hit@10"] == 0.75
    assert s["MRR"] == pytest.approx((1 + 1 / 4 + 0 + 1 / 2) / 4)
    assert tuple(s) == METRICS  # the report's header
    with pytest.raises(ValueError, match="no answerable"):
        scores([{"rank": None, "answerable": False}])


def test_report_breaks_scores_down_by_type_and_style():
    rows = [{"id": "q1", "type": "row", "style": "id", "rank": 1, "top": "docs/E.csv > a", "score": 0.81},
            {"id": "q2", "type": "entry", "style": "plain", "rank": None, "top": "docs/done.md > #1", "score": None}]
    out = report(rows)
    assert "q2" in out and "type=row" in out and "style=plain" in out
    assert "STALE" not in out
    assert report(rows, split="test (2 of 9 questions)").splitlines()[:2] == ["split: test (2 of 9 questions)", ""]
    stale_out = report(rows, ["docs/a.md"]).splitlines()
    assert stale_out[0].startswith("STALE INDEX: 1 file(s) differ from the index (docs/a.md)")
    assert stale_out[1] == "" and stale_out[2].startswith("question")
    assert out.splitlines()[1].split()[4] == "0.8100"
    assert out.splitlines()[2].split()[3:5] == ["-", "-"]  # q2 found nothing in the top 10


def test_report_shows_full_and_any_part_ranks_for_multi_part_questions():
    two = [[{"path": "a"}], [{"path": "b"}]]
    rows = [{"id": "q1", "type": "row", "style": "plain", "rank": None, "rank_any": 2, "parts": two,
             "top": "a", "score": 0.8},
            {"id": "q2", "type": "row", "style": "plain", "rank": 1, "rank_any": 1, "gold": [{"path": "a"}],
             "top": "a", "score": 0.8}]
    lines = report(rows).splitlines()
    assert lines[1].split()[3] == "-/2" and lines[2].split()[3] == "1"
    all_line = next(line for line in lines if line.startswith("all"))
    multi_line = next(line for line in lines if line.startswith("multi-part"))
    any_line = next(line for line in lines if line.startswith("  any part"))
    assert all_line.split()[2:4] == ["0.50", "0.50"]  # hit@1, hit@3: q1's full answer is never found
    assert multi_line.split()[1:4] == ["1", "0.00", "0.00"]
    assert any_line.split()[2:5] == ["1", "0.00", "1.00"]  # q1 alone: first part at rank 2


def test_unanswerable_questions_show_but_stay_out_of_the_scores():
    rows = [{"id": "q1", "type": "row", "style": "plain", "rank": 1, "top": "a", "score": 0.8},
            {"id": "q2", "type": "none", "style": "plain", "rank": None, "top": "b", "score": 0.7,
             "answerable": False}]
    lines = report(rows).splitlines()
    assert lines[2].split()[3:5] == ["n/a", "0.7000"]
    all_line = next(line for line in lines if line.startswith("all"))
    assert all_line.split()[1:3] == ["1", "1.00"]  # n=1, hit@1 1.00: q2 isn't a miss
    assert not any(line.startswith("type=none") for line in lines)
    assert lines[-2:] == ["(+1 unanswerable, not scored)",
                          "top score range: answerable 0.8000-0.8000, unanswerable 0.7000-0.7000"]
    assert report(rows[1:]).splitlines()[-2:] == ["no answerable questions to score",
                                                  "(+1 unanswerable, not scored)"]


def test_check_golds_flags_a_gold_no_chunk_matches():
    questions = [{"id": "q", "gold": [{"path": "docs/a.md", "contains": "gone"}]},
                 {"id": "p", "parts": [[{"path": "docs/a.md"}], [{"path": "docs/a.md", "contains": "lost"}]]}]
    assert check_golds(questions, [_node("still here")]) == [
        "q: {'path': 'docs/a.md', 'contains': 'gone'}", "p: {'path': 'docs/a.md', 'contains': 'lost'}"]
    overlap = [{"id": "o", "parts": [[{"path": "docs/a.md"}], [{"path": "docs/a.md", "contains": "here"}]]}]
    assert check_golds(overlap, [_node("still here")]) == ["o: one chunk satisfies parts [1, 2] (docs/a.md > S)"]


def test_a_gold_that_doesnt_fit_the_question_is_rejected(tmp_path):
    path = tmp_path / "q.json"
    bad = ['"gold": []', '"gold": [{}]', '"gold": {"path": "docs/a.md"}',
           '"gold": [{"path": "docs/a.md"}], "answerable": false']
    for fields in bad:
        path.write_text(f'[{{"id": "q", "question": "?", {fields}}}]')
        with pytest.raises(ValueError, match="dev/test: q$"):
            load_questions(path)
    path.write_text('[{"id": "q", "question": "?", "gold": [], "answerable": "false"}]')
    with pytest.raises(ValueError, match="q: answerable must be true or false"):
        load_questions(path)
    path.write_text('[{"id": "q", "question": "?", "gold": [], "answerable": false}]')
    assert load_questions(path)[0]["id"] == "q"
    one = '[{"path": "docs/a.md"}]'
    for fields in (f'"parts": [{one}]', f'"parts": [{one}, []]', f'"parts": [{one}, [{{}}]]',
                   f'"parts": [{one}, {one}], "gold": {one}',
                   f'"parts": [{one}, {one}], "answerable": false'):
        path.write_text(f'[{{"id": "q", "question": "?", {fields}}}]')
        with pytest.raises(ValueError, match="dev/test: q$"):
            load_questions(path)
    path.write_text(f'[{{"id": "q", "question": "?", "gold": {one}, "split": "train"}}]')
    with pytest.raises(ValueError, match="dev/test: q$"):
        load_questions(path)
    path.write_text(f'[{{"id": "q", "question": "?", "parts": [{one}, [{{"path": "docs/b.md"}}]]}}]')
    assert load_questions(path)[0]["id"] == "q"


def test_every_question_in_the_set_still_matches_the_real_docs():
    """If this fails, a doc was edited under a question: fix the question's gold."""
    questions = load_questions()
    assert len({q["id"] for q in questions}) == len(questions)
    test = [q for q in questions if question_split(q) == "test"]
    assert 12 <= len(test) <= 20
    types = {q["type"] for q in questions}
    assert types == {q["type"] for q in test}  # every type held out, unanswerable included
    assert check_golds(questions, chunk_documents(load_documents())) == []


def test_evaluate_scores_the_search_it_is_given(monkeypatch):
    from llama_index.core.schema import NodeWithScore
    from src.llm.research_docs import evaluate as ev
    monkeypatch.setattr(ev, "search", lambda index, question, k: [])  # the default, unused here
    asked = []

    def find(question, k):
        asked.append((question, k))
        return [NodeWithScore(node=_node(entry="#1"), score=0.03)]
    rows = ev.evaluate(None, [{"id": "q", "question": "?", "gold": [{"path": "docs/a.md", "entry": "#1"}]}], find)
    assert rows[0]["rank"] == 1 and asked == [("?", max(ev.KS))]
