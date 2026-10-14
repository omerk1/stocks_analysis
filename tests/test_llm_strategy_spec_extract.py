import json
from datetime import datetime, timezone
from typing import get_args

import pytest

from src.llm.gemini import Reply, Usage
from src.llm.strategy_spec import extract
from src.llm.strategy_spec.extract import (
    Case, Expectation, ExpectedFlag, load_cases, run_eval, score_case, score_dir, score_field, summarise)
from src.llm.strategy_spec.schema import (
    Duration, Size, SpecField, StrategySpec, Trigger, UnsupportedRequest, load_golden_specs)


# --- the answer key ---------------------------------------------------------------


def test_cases_load_and_cover_every_spec_field():
    cases = load_cases()
    assert len(cases) == 9
    assert len({c.id for c in cases}) == len(cases)
    for case in cases:
        assert set(case.fields) == set(get_args(SpecField)), case.id
        assert case.idea.strip(), case.id
    # The golden ideas are scored on their original description text, not the built spec.
    golden = {g.id: g.description for g in load_golden_specs()}
    by_id = {c.id: c for c in cases}
    for gid, description in golden.items():
        assert by_id[gid].idea == description
    # At least one fully supported idea, to catch false flags.
    assert any(not c.flags for c in cases)
    # Most new ideas carry a required flag.
    assert sum(1 for c in cases if any(not f.optional for f in c.flags)) >= 4


def test_a_case_missing_a_field_or_with_a_bad_expectation_is_rejected(tmp_path):
    path = tmp_path / "cases.json"
    ok = {"id": "x", "idea": "an idea",
          "fields": {f: "blank" for f in get_args(SpecField)}, "unsupported": []}
    path.write_text(json.dumps([ok]))
    assert load_cases(path)[0].fields["trigger"] == Expectation("blank")
    # Expected values are stored as the schema coerces them: a "1.5" written in the key
    # must still equal the extractor's 1.5.
    quoted = {**ok, "fields": {**ok["fields"], "size": {"values": {"min": "1.5"}},
                               "horizons_bars": {"values": ["5", 20]}}}
    path.write_text(json.dumps([quoted]))
    fields = load_cases(path)[0].fields
    assert fields["size"] == Expectation("values", {"min": 1.5})
    assert fields["horizons_bars"] == Expectation("values", [5, 20])
    for broken in ({**ok, "fields": {k: v for k, v in ok["fields"].items() if k != "control"}},
                   {**ok, "fields": {**ok["fields"], "direction": "described"}},
                   {**ok, "fields": {**ok["fields"], "size": {"values": {"min_bars": 3}}}},
                   {**ok, "fields": {**ok["fields"], "size": {"values": {}}}},
                   {**ok, "unsupported": [{"has": "x", "reason": "too hard"}]},
                   # Expected values the schema would reject make a case unwinnable.
                   {**ok, "fields": {**ok["fields"], "direction": {"value": "lonh"}}},
                   {**ok, "fields": {**ok["fields"], "size": {"values": {"normalisation": "ATR"}}}},
                   # An expected value that means "nothing stated" is a 'blank' spelled wrong.
                   {**ok, "fields": {**ok["fields"], "size": {"values": {"not_applicable": False}}}},
                   # Malformed shapes name the case instead of a bare KeyError/TypeError.
                   {**ok, "unsupported": [{"reason": "other"}]},
                   {**ok, "unsupported": ["earnings"]},
                   {**ok, "fields": sorted(ok["fields"])},
                   # Exactly one idea text per case, an id, and a real golden reference.
                   {**ok, "golden": "ma_touch_bounce"},
                   {k: v for k, v in ok.items() if k != "id"},
                   {k: v for k, v in {**ok, "golden": "no_such_idea"}.items() if k != "idea"}):
        path.write_text(json.dumps([broken]))
        with pytest.raises(ValueError):
            load_cases(path)
    # An authoring mistake names its case.
    path.write_text(json.dumps([{**ok, "fields": {**ok["fields"], "direction": {"value": "lonh"}}}]))
    with pytest.raises(ValueError, match="case 'x'"):
        load_cases(path)
    path.write_text(json.dumps([ok, ok]))
    with pytest.raises(ValueError, match="unique"):
        load_cases(path)


# --- scoring one field ------------------------------------------------------------


def _spec(**kw):
    return StrategySpec(**kw)


def test_blank_expected():
    assert score_field("duration", _spec(), Expectation("blank")) == "correct"
    # Gemini often writes {"description": null, ...} for "nothing": that's empty, not invented.
    assert score_field("duration", _spec(duration=Duration()), Expectation("blank")) == "correct"
    assert score_field("duration", _spec(duration=Duration(not_applicable=True)),
                       Expectation("blank")) == "invented"
    assert score_field("direction", _spec(direction="long"), Expectation("blank")) == "invented"


def test_described_expected():
    exp = Expectation("described")
    assert score_field("size", _spec(), exp) == "left_blank"
    assert score_field("size", _spec(size=Size()), exp) == "left_blank"  # all-null section
    assert score_field("size", _spec(size=Size(description="a tight coil")), exp) == "correct"
    # Words were given, numbers weren't: a number here was invented — zero included
    # (0.0 == False, so a careless check would read an invented 0 as unset).
    assert score_field("size", _spec(size=Size(description="a tight coil", min=1.0)), exp) == "invented"
    assert score_field("size", _spec(size=Size(description="a tight coil", min=0.0)), exp) == "invented"
    assert score_field("trigger", _spec(trigger=Trigger(description="breaks out", execution="next_open")),
                       exp) == "invented"


def test_exact_values_expected():
    assert score_field("direction", _spec(direction="long"), Expectation("values", "long")) == "correct"
    assert score_field("direction", _spec(direction="short"), Expectation("values", "long")) == "wrong"
    assert score_field("direction", _spec(), Expectation("values", "long")) == "left_blank"
    # Horizons compare as a set: the order carries no meaning.
    assert score_field("horizons_bars", _spec(horizons_bars=[20, 5]),
                       Expectation("values", [5, 20])) == "correct"
    assert score_field("horizons_bars", _spec(horizons_bars=[5]),
                       Expectation("values", [5, 20])) == "wrong"
    exp = Expectation("values", {"normalisation": "atr", "min": 1.5})
    assert score_field("size", _spec(size=Size(description="x", normalisation="atr", min=1.5)), exp) == "correct"
    assert score_field("size", _spec(size=Size(normalisation="pct", min=1.5)), exp) == "wrong"
    # Only the listed sub-values are checked; a defensible extra isn't scored.
    assert score_field("trigger", _spec(trigger=Trigger(description="gap", price_basis="close",
                                                        execution="next_open")),
                       Expectation("values", {"execution": "next_open"})) == "correct"


def test_either_is_not_scored():
    assert score_field("control", _spec(), Expectation("either")) == "unscored"


# --- scoring flags ----------------------------------------------------------------


def _flagged(*requests):
    return _spec(unsupported=[UnsupportedRequest(**r) for r in requests])


EARNINGS = dict(requested="Earnings  Surprise filter", field="supporting_signals", reason="unsupported_data")
CASE = Case("c", "idea", {f: Expectation("either") for f in get_args(SpecField)},
            (ExpectedFlag("earnings", "unsupported_data"),
             ExpectedFlag("", "unsupported_execution", optional=True)))


def test_flags_matched_by_wording_substring_and_reason():
    score = score_case(_flagged(EARNINGS), CASE)
    assert score.caught == 1 and score.missed == () and score.unexpected == ()
    # Hyphenation doesn't break the match: "15-minute" finds "the 15 minute chart".
    flag = ExpectedFlag("15-minute", "unsupported_timeframe")
    assert flag.matches("the 15 minute chart", "unsupported_timeframe")
    assert not flag.matches("the 5 minute chart", "unsupported_timeframe")
    # Matching is by whole words: a stem extends ("sweep" finds "sweeps", quotes don't
    # hide it), a number or symbol matches exactly in either direction.
    assert ExpectedFlag("sweep", "other").matches('big "sweeps" on the tape', "other")
    assert not ExpectedFlag("10%", "other").matches("the top 10 names", "other")
    assert not ExpectedFlag("10%", "other").matches("a 110% move", "other")
    assert not ExpectedFlag("15 minute", "other").matches("a 415 minute window", "other")
    assert not ExpectedFlag("15-minute", "other").matches("the 150 minute chart", "other")
    assert ExpectedFlag("10%", "other").matches("a move of 10% or more", "other")
    # The same words under the wrong reason don't count.
    score = score_case(_flagged({**EARNINGS, "reason": "unknown_metric"}), CASE)
    assert score.missed == ("earnings",) and score.unexpected == ("Earnings  Surprise filter",)


def test_optional_flags_count_neither_way():
    extra = dict(requested="an intraday stop", field="invalidation", reason="unsupported_execution")
    score = score_case(_flagged(EARNINGS, extra), CASE)
    assert score.caught == 1 and score.missed == () and score.unexpected == ()
    assert score_case(_spec(), CASE).missed == ("earnings",)


def test_an_unexpected_flag_on_a_supported_idea_is_reported():
    clean = Case("clean", "idea", CASE.fields, ())
    score = score_case(_flagged(EARNINGS), clean)
    assert score.unexpected == ("Earnings  Surprise filter",)


# --- the prompt and the call ------------------------------------------------------


def test_system_prompt_has_the_rules_and_the_catalogue():
    system = extract.build_system()
    for needle in ("Leave a field null", "unsupported", "Never substitute",
                   "indicator:rsi", "control:matched", "detector:gap.classic"):
        assert needle in system
    assert len(system.split()) < 3000  # it must stay well under the input cap


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        spec = self.replies[len(self.calls) - 1]
        return Reply(text=spec.model_dump_json(), parsed=spec,
                     usage=Usage(10, 5, 0, 15), finish_reason="STOP")


def test_extract_sends_the_idea_with_schema_and_temperature_zero():
    client = FakeClient([_spec(direction="long")])
    reply = extract.extract("buy the dip", client)
    assert reply.parsed.direction == "long"
    [(prompt, kwargs)] = client.calls
    assert prompt == "buy the dip"
    assert kwargs["response_schema"] is StrategySpec
    assert kwargs["temperature"] == 0.0
    assert kwargs["purpose"] == "strategy_spec.extract"
    assert "indicator:rsi" in kwargs["system"]


# --- the runner -------------------------------------------------------------------


def _two_cases():
    fields = {f: Expectation("blank") for f in get_args(SpecField)}
    return [Case("a", "idea a", {**fields, "direction": Expectation("values", "long")}, ()),
            Case("b", "idea b", fields, (ExpectedFlag("news", "unsupported_data"),))]


def test_eval_saves_replies_and_score_rereads_them(tmp_path):
    cases = _two_cases()
    replies = [_spec(direction="long"),
               _spec(unsupported=[UnsupportedRequest(requested="news sentiment", field="trigger",
                                                     reason="unsupported_data")])]
    client = FakeClient(replies)
    scores, out = run_eval(client=client, cases=cases, out_dir=tmp_path,
                           now=datetime(2026, 10, 14, 12, tzinfo=timezone.utc))
    assert out == tmp_path / "20261014T120000Z"
    assert [s.case_id for s in scores] == ["a", "b"]
    assert scores[0].count("correct") == 10 and scores[1].caught == 1
    saved = json.loads((out / "a.json").read_text())
    assert saved["idea"] == "idea a" and saved["usage"]["total_tokens"] == 15
    # Re-scoring the saved run gives the same result, with no client at all.
    assert score_dir(out, cases=cases) == scores


def test_score_dir_rejects_an_unknown_case_or_a_partial_run(tmp_path):
    with pytest.raises(ValueError, match="isn't a directory"):
        score_dir(tmp_path / "no_such_run", cases=_two_cases())
    (tmp_path / "x.json").write_text(json.dumps({"case": "mystery", "spec": {}}))
    with pytest.raises(ValueError, match="mystery"):
        score_dir(tmp_path, cases=_two_cases())
    # Two files answering the same case can't silently shadow each other.
    (tmp_path / "x.json").write_text(json.dumps({"case": "a", "spec": {}}))
    (tmp_path / "x_retry.json").write_text(json.dumps({"case": "a", "spec": {}}))
    (tmp_path / "b.json").write_text(json.dumps({"case": "b", "spec": {}}))
    with pytest.raises(ValueError, match="two replies for 'a'"):
        score_dir(tmp_path, cases=_two_cases())
    (tmp_path / "x_retry.json").unlink()
    assert len(score_dir(tmp_path, cases=_two_cases())) == 2
    # A run that died mid-way isn't scored: its totals would look like an improvement.
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "a.json").write_text(json.dumps({"case": "a", "spec": {}}))
    with pytest.raises(ValueError, match="missing replies for: b"):
        score_dir(partial, cases=_two_cases())


def test_two_eval_runs_in_the_same_second_dont_overwrite_each_other(tmp_path):
    cases = _two_cases()
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    run_eval(client=FakeClient([_spec(), _spec()]), cases=cases, out_dir=tmp_path, now=now)
    with pytest.raises(FileExistsError):
        run_eval(client=FakeClient([_spec(), _spec()]), cases=cases, out_dir=tmp_path, now=now)


def test_summary_table_counts_and_spells_out_misses():
    cases = _two_cases()
    scores = [score_case(_spec(direction="short", timeframe="daily"), cases[0]),
              score_case(_spec(), cases[1])]
    lines = summarise(scores, cases)
    assert lines[0].split()[:2] == ["case", "correct"]
    assert lines[1].split() == ["a", "8", "0", "1", "1", "0", "0/0"]
    assert lines[2].split() == ["b", "10", "0", "0", "0", "0", "0/1"]
    assert lines[3].split()[0] == "totals"
    body = "\n".join(lines)
    assert "a direction: wrong (expected 'long')" in body
    assert "a timeframe: invented (expected 'blank')" in body
    assert "b flag missed: 'news'" in body


def test_cli_score_prints_the_table(tmp_path, monkeypatch, capsys):
    client = FakeClient([_spec() for _ in load_cases()])
    scores, out = run_eval(client=client, out_dir=tmp_path)
    extract.main(["score", str(out)])
    printed = capsys.readouterr().out
    assert "totals" in printed and "atr_gap_up" in printed
