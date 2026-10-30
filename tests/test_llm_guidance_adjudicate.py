import pandas as pd
import pytest

from src.llm.guidance import adjudicate
from src.llm.guidance.schema import GuidanceItem, ReleaseLabel


def item(**kw) -> GuidanceItem:
    base = dict(metric="eps", metric_text="EPS", period="year", period_text="2015", shape="range",
                low=2.1, high=2.2, unit="USD per share", basis="adjusted", revision="not_stated", evidence="q")
    return GuidanceItem(**{**base, **kw})


def label(*items) -> ReleaseLabel:
    return ReleaseLabel(guidance_present=bool(items), items=list(items))


SAMPLE = pd.DataFrame({"slot": [0, 1, 2, 3], "ticker": ["A", "B", "C", "D"], "accession": ["a", "b", "c", "d"],
                       "year": [2015] * 4})
PAIRS = {
    "a": (label(item(revision="raised")), label(item())),  # differ on revision
    "b": (label(item(metric="revenue", unit="USD billions")), label(item(metric="other", metric_text="capex"))),
    "c": (label(item()), label(item(revision="initiated"))),  # agree: initiated reads as not stated
    "d": (label(), label()),
}


def by_kind(qs):
    return {(q["accession"], q["kind"]): q for q in qs}


def test_questions_cover_differences_and_a_spot_check():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    assert sorted(by_kind(qs)) == [("a", "fields"), ("b", "only"), ("b", "other"), ("c", "check"), ("d", "check")]
    f = by_kind(qs)[("a", "fields")]
    assert f["diff"] == ["revision"]
    draft = f["a"] if f["a_from"] == "draft" else f["b"]
    assert draft["revision"] == "raised"
    assert [q["id"] for q in qs] == [f"Q{n:02d}" for n in range(1, 6)]
    assert adjudicate.questions(PAIRS, SAMPLE, n_check=2) == qs  # seeded


def answers_for(qs, **by):
    return {q["id"]: by[f"{q['accession']}_{q['kind']}"] for q in qs}


def test_gold_from_answers():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    f = by_kind(qs)[("a", "fields")]
    draft_letter = "A" if f["a_from"] == "draft" else "B"
    ans = answers_for(qs, a_fields=draft_letter + ".", b_only="no", b_other="Yes", c_check="ok", d_check="none found")
    gold, presence, meta = adjudicate.build_gold(PAIRS, qs, ans, {})
    assert gold["a"].items[0].revision == "raised"
    assert not gold["b"].guidance_present and presence["b"]  # capex counts, revenue item rejected
    assert gold["c"].items[0].revision == "not_stated" and not presence["d"]
    assert meta["disagreements_won"] == {"draft": 1, "model": 1, "split": 0, "neither": 0}
    assert meta["spot_check"] == {"asked": 2, "right": 2}


def test_gold_refuses_missing_or_free_text_answers_until_overridden():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    ans = answers_for(qs, a_fields="", b_only="no", b_other="no", c_check="ok", d_check="EPS 1.0 for 2015")
    with pytest.raises(ValueError, match="no answer"):
        adjudicate.build_gold(PAIRS, qs, ans, {})
    ans[by_kind(qs)[("a", "fields")]["id"]] = "A"
    d_id = by_kind(qs)[("d", "check")]["id"]
    with pytest.raises(ValueError, match="needs an override"):
        adjudicate.build_gold(PAIRS, qs, ans, {})
    found = item(low=1.0, high=1.0, shape="point").model_dump()
    gold, presence, meta = adjudicate.build_gold(PAIRS, qs, ans, {d_id: {"accession": "d", "items": [found]}})
    assert gold["d"].items[0].low == 1.0 and presence["d"]
    assert meta["spot_check"] == {"asked": 2, "right": 1}


def test_overrides_are_checked_against_their_question():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    ids = {(q["accession"], q["kind"]): q["id"] for q in qs}
    bad = {"Q99": {"accession": "a"},
           ids[("a", "fields")]: {"accession": "b", "items": []},  # renumbered: another release's question
           ids[("b", "other")]: {"accession": "b", "items": []},  # an other question needs 'present'
           ids[("c", "check")]: {"accession": "c", "winner": "me"},
           ids[("b", "only")]: {"accession": "b", "items": [], "winner": "me"}}
    problems = adjudicate.override_problems(qs, bad)
    assert len(problems) == 6 and any("doesn't exist" in p for p in problems)
    assert any("counts only on" in p for p in problems)  # a winner on a check
    assert any("winner must be one of" in p for p in problems)  # an unknown winner where it counts


def test_a_check_override_without_items_keeps_the_agreed_items():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    ids = {(q["accession"], q["kind"]): q["id"] for q in qs}
    ans = answers_for(qs, a_fields="", b_only="no", b_other="no", c_check="fine, wording only", d_check="ok")
    ov = {ids[("c", "check")]: {"accession": "c", "agrees": True},
          ids[("a", "fields")]: {"accession": "a", "winner": "draft", "items": [item(revision="raised").model_dump()]}}
    gold, _, meta = adjudicate.build_gold(PAIRS, qs, ans, ov)
    assert len(gold["c"].items) == 1 and meta["spot_check"] == {"asked": 2, "right": 2}
    # the override's winner, and b's draft-only item rejected: a win for the model
    assert meta["disagreements_won"] == {"draft": 1, "model": 1, "split": 0, "neither": 0}



def test_unsure_leaves_the_release_out():
    qs = adjudicate.questions(PAIRS, SAMPLE, n_check=2)
    ans = answers_for(qs, a_fields="A", b_only="?", b_other="yes", c_check="ok", d_check="none found")
    gold, presence, meta = adjudicate.build_gold(PAIRS, qs, ans, {})
    assert "b" not in gold and "b" not in presence and meta["unresolved_releases"] == ["b"]


def test_a_letter_per_row():
    q = {"a": item(basis="gaap").model_dump(), "b": item(revision="maintained", low=2.0).model_dump(),
         "diff": ["values", "basis", "revision"]}
    assert adjudicate.rows(q) == ["forecast", "adjusted or GAAP", "change vs earlier guidance"]
    assert adjudicate.picks(q, "b") == ["b", "b", "b"] and adjudicate.picks(q, "a b") is None
    mixed = adjudicate.combined(q, adjudicate.picks(q, "b, a, b"))
    assert (mixed["low"], mixed["basis"], mixed["revision"]) == (2.0, "gaap", "maintained")


def test_snapshot_round_trips():
    snap = adjudicate.snapshot({"b": label(item()), "a": None})
    assert list(snap) == ["a", "b"] and snap["a"] is None
    assert ReleaseLabel.model_validate(snap["b"]) == label(item())


def test_numbers_are_exact():
    assert adjudicate._num(12345678.0) == "12,345,678" and adjudicate._num(2.1) == "2.1" and adjudicate._num(0.0) == "0"


def test_parse_answers():
    md = "intro\n### Q01 · x\ntext\n**Answer:** A\n\n### Q02 · y\n**Answer:**\nthe range is\n2.0 to 2.1\n"
    assert adjudicate.parse_answers(md) == {"Q01": "A", "Q02": "the range is 2.0 to 2.1"}
