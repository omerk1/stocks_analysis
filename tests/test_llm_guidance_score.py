import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.llm.gemini import ReplyError, Usage
from src.llm.guidance import extract, prompt, score
from src.llm.guidance.schema import GuidanceItem, ReleaseLabel


def item(**kw) -> GuidanceItem:
    base = dict(metric="eps", metric_text="EPS", period="year", period_text="2015", shape="range",
                low=2.1, high=2.2, unit="USD per share", basis="adjusted", revision="raised", evidence="")
    return GuidanceItem(**{**base, **kw})


def label(*items) -> ReleaseLabel:
    return ReleaseLabel(guidance_present=bool(items), items=list(items))


def test_match_never_pairs_different_years():
    gold = [item(period_text="fiscal 2015"), item(period_text="fiscal 2016", low=2.5, high=2.6)]
    pred = [item(period_text="FY 2016")]  # gold 2015's values, but for 2016
    assert score.match_items(gold, pred) == [(1, 0)]
    assert score.match_items([item(period_text="full year")], [item(period_text="2015")]) == [(0, 0)]


def test_load_extractions_refuses_a_stale_fingerprint(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"accession": "a", "fingerprint": "old", "error": "x"}))
    with pytest.raises(ValueError):
        extract.load_extractions(tmp_path)


def test_run_one_records_a_refused_call(tmp_path):
    from src.llm.gemini import BudgetExceeded

    class Refusing(StubGemini):
        def generate(self, text, **kw):
            raise BudgetExceeded("prompt is 70000 tokens")

    row = extract.run_one(Refusing(), "big", "text", tmp_path)
    assert row["error"].startswith("BudgetExceeded") and extract.load_extractions(tmp_path)["big"] is None


def test_review_numbers_are_exact():
    from src.llm.guidance import review

    assert review._num(12345678.0) == "12,345,678" and review._num(2.1) == "2.1" and review._num(0.0) == "0"


def test_match_needs_same_metric_and_period_and_prefers_agreement():
    gold = [item(), item(basis="gaap", low=2.0, high=2.1)]
    pred = [item(basis="gaap", low=2.0, high=2.1), item(period="quarter"), item()]
    assert score.match_items(gold, pred) == [(0, 2), (1, 0)]
    assert score.match_items([item(metric="revenue")], [item()]) == []


def test_score_counts_presence_items_fields_and_revisions():
    gold = {
        "a": label(item(), item(metric="revenue", unit="USD billions", low=9.5, high=9.7, revision="not_stated")),
        "b": label(),
        "c": label(item(revision="maintained")),
        "d": label(item(revision="lowered")),
    }
    pred = {
        "a": label(item(low=2.1, high=2.25)),  # revenue missed; EPS values off
        "b": label(item()),  # false positive
        "c": label(item(revision="not_stated")),  # revision unread
        "d": None,  # unusable reply
    }
    r = score.score(gold, pred)
    assert r["presence"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 0, "precision": 2 / 3, "recall": 2 / 3}
    assert r["unusable_replies"] == 1
    assert r["items"] == {"gold": 4, "predicted": 3, "matched": 2, "recall": 0.5, "precision": 2 / 3}
    assert r["field_accuracy_on_matched"] == {"shape": 1.0, "values": 0.5, "unit": 1.0, "basis": 1.0, "revision": 0.5}
    assert r["revision"] == {"gold_items_readable": 3, "share_of_gold_items": 0.75, "model_right_on_readable": 1 / 3}
    with pytest.raises(ValueError):
        score.score(gold, {"a": None})


def test_headline_only_drops_other_metrics():
    labels = {"a": label(item(), item(metric="other")), "b": label(item(metric="other")), "c": None}
    h = score.headline_only(labels)
    assert [i.metric for i in h["a"].items] == ["eps"]
    assert not h["b"].guidance_present and h["c"] is None


def test_coverage_and_revision_by_release():
    gold = {"a": label(item()), "b": label(), "c": label(item(revision="initiated"))}
    sample = pd.DataFrame({"accession": ["a", "b", "c"], "year": [2010, 2010, 2011],
                           "sector": ["X", "Y", "X"], "size": ["large", "mid", "mid"]})
    cov = score.coverage(gold, sample)
    assert cov["year"].loc[2010].to_dict() == {"releases": 2, "with_guidance": 1, "share": 0.5}
    assert cov["sector"].loc["X", "with_guidance"] == 2
    assert score.revision_by_release(gold).to_dict() == {"a": True, "c": False}


class StubGemini:
    model, budget = prompt.MODEL, SimpleNamespace(max_output_tokens=prompt.MAX_OUTPUT_TOKENS,
                                                  thinking_budget=prompt.THINKING_BUDGET)

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def generate(self, text, **kw):
        self.calls += 1
        if self.fail:
            raise ReplyError("reply cut off")
        lab = label(item())
        return SimpleNamespace(parsed=lab, usage=Usage(prompt_tokens=8, output_tokens=2, thinking_tokens=0,
                                                       total_tokens=10))


def test_run_one_caches_by_fingerprint_and_text(tmp_path):
    g = StubGemini()
    row = extract.run_one(g, "acc", "text", tmp_path)
    assert row["fingerprint"] == prompt.fingerprint() and row["label"]["guidance_present"]
    extract.run_one(g, "acc", "text", tmp_path)
    assert g.calls == 1  # cached
    extract.run_one(g, "acc", "other text", tmp_path)
    assert g.calls == 2  # the text changed: asked again
    bad = StubGemini(fail=True)
    err = extract.run_one(bad, "acc2", "text", tmp_path)
    assert "cut off" in err["error"]
    loaded = extract.load_extractions(tmp_path)
    assert loaded["acc2"] is None and loaded["acc"].items[0].metric == "eps"
    assert json.loads((tmp_path / "acc.json").read_text())["text_sha256"] == extract.text_hash("other text")


def test_review_sheet_lists_items_and_notes():
    from src.llm.guidance import review

    sample = pd.DataFrame({"slot": [1, 0], "ticker": ["B", "A"], "accession": ["b", "a"], "year": [2011, 2010],
                           "sector": ["X", "Y"], "size": ["mid", "large"], "index_url": ["ib", "ia"]})
    drafts = {"a": {"label": label(item(shape="floor", high=None)).model_dump(), "uncertain": "check unit"},
              "b": {"label": ReleaseLabel(guidance_present=False, items=[], notes="call only").model_dump()}}
    text = review.sheet(drafts, sample, {"a": "ua"})
    assert "| 00 | A | 2010 | yes | 0 / 1 / 0 / 0 | 1 raised | yes |" in text
    assert "| 01 | B | 2011 | **no** |  |  |  |" in text
    a, b = text.index("**00 A**"), text.index("**01 B**")
    assert a < b and "[release](ua)" in text and "[release](ib)" in text
    assert 'eps (EPS), year "2015", adjusted: >= 2.1 USD per share; raised' in text
    assert "_note: check unit_" in text and "**no guidance**" in text and "_note: call only_" in text
