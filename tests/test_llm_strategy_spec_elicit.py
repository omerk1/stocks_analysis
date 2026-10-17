import json
from typing import get_args

import pytest

from src.llm.gemini import Reply, Usage
from src.llm.strategy_spec import elicit as el
from src.llm.strategy_spec.elicit import _ANSWER_MODELS, Question, apply_answer, elicit, next_question
from src.llm.strategy_spec.schema import (
    Control, Duration, Rule, Size, SpecField, StrategySpec, Trigger, UnsupportedRequest, find_gaps)


def _spec(**overrides):
    fields = dict(
        name="x", direction="long", timeframe="daily",
        duration=Duration(min_bars=10, max_bars=40),
        size=Size(normalisation="atr", max=1.5),
        trigger=Trigger(description="close above range high", price_basis="close", execution="next_open"),
        horizons_bars=[5, 20],
        invalidation=[Rule(description="close back inside the range", phase="after_entry")],
        control=Control(description="same dates, no pattern"),
    )
    return StrategySpec(**{**fields, **overrides})


INTRADAY = UnsupportedRequest(requested="15-minute bars", field="timeframe", reason="unsupported_timeframe")


# --- questions --------------------------------------------------------------------


def test_complete_spec_has_no_question():
    assert next_question(_spec()) is None


def test_first_open_field_in_order_with_its_gaps_bundled():
    q = next_question(_spec(direction=None, timeframe=None, control=None))
    assert q.field == "direction" and "long, short, or both?" in q.text
    q = next_question(_spec(trigger=Trigger(description="breaks out")))
    assert q.field == "trigger" and len(q.gaps) == 2  # basis and execution, one question
    assert "close or" in q.text and "next bar's open?" in q.text


def test_an_unsupported_gap_reads_as_news_plus_choice():
    q = next_question(_spec(timeframe=None, unsupported=[INTRADAY]))
    assert q.field == "timeframe"
    assert "isn't supported" in q.text and "drop" in q.text
    assert "which bar resolution" in q.text  # the field is also still missing


def test_the_current_partial_value_is_shown():
    q = next_question(_spec(duration=Duration(description="a few weeks")))
    assert q.field == "duration" and '"a few weeks"' in q.text
    q = next_question(_spec(size=Size(normalisation="atr", min=2.0, max=1.0)))
    assert "can't be right" in q.text and "min 2.0 > max 1.0" in q.text


def test_a_question_exists_for_every_answer_model():
    assert set(_ANSWER_MODELS) == set(get_args(SpecField))
    # The per-field schema takes the field's own shape and rejects strays.
    model = _ANSWER_MODELS["duration"]
    parsed = model.model_validate({"value": {"min_bars": 10}, "unsupported": []})
    assert parsed.value.min_bars == 10
    with pytest.raises(Exception):
        model.model_validate({"value": {"min_bars": 10}, "extra": 1})


# --- applying answers -------------------------------------------------------------


class StubClient:
    """Returns scripted per-field answers; records what it was asked."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        parsed = kwargs["response_schema"].model_validate(self.replies.pop(0))
        return Reply(text="{}", parsed=parsed, usage=Usage(10, 5, 0, 15), finish_reason="STOP")


def test_apply_answer_sets_only_the_asked_field():
    spec = _spec(direction=None)
    client = StubClient([{"value": "short"}])
    q = next_question(spec)
    out = apply_answer(spec, q, "short please", client)
    assert out.direction == "short" and out.timeframe == "daily"
    prompt, kwargs = client.calls[0]
    assert "short please" in prompt and "long, short, or both?" in prompt
    assert kwargs["purpose"] == "strategy_spec.elicit" and kwargs["temperature"] == 0.0
    assert "change nothing outside the asked section" in kwargs["system"]
    assert "indicator:rsi" in kwargs["system"]  # the catalogue rides along


def test_a_null_value_leaves_the_field_and_the_gap():
    spec = _spec(control=None)
    out = apply_answer(spec, next_question(spec), "hmm, not sure", StubClient([{"value": None}]))
    assert out.control is None and find_gaps(out)


def test_dropping_an_unsupported_entry_takes_an_explicit_resolution():
    spec = _spec(timeframe=None, unsupported=[
        INTRADAY, UnsupportedRequest(requested="earnings", field="supporting_signals",
                                     reason="unsupported_data")])
    q = next_question(spec)  # about timeframe: the unsupported request plus missing
    # The model answers the value but doesn't name the request: it is kept, not dropped.
    out = apply_answer(spec, q, "the pattern is on daily charts", StubClient([{"value": "daily"}]))
    assert out.timeframe == "daily"
    assert sorted(u.requested for u in out.unsupported) == ["15-minute bars", "earnings"]
    # Named (wording folded), it goes; the other field's entry is untouched either way.
    out = apply_answer(spec, q, "fine, daily bars then — forget the 15 minute part",
                       StubClient([{"value": "daily", "resolved_requests": ["15 Minute bars"]}]))
    assert out.timeframe == "daily"
    assert [u.requested for u in out.unsupported] == ["earnings"]
    # Echoing the question's whole displayed line still resolves it (containment).
    out = apply_answer(spec, q, "drop it", StubClient([
        {"value": None, "resolved_requests": ["'15-minute bars': unsupported timeframe"]}]))
    assert [u.requested for u in out.unsupported] == ["earnings"]


def test_a_naming_resolves_its_best_match_not_every_substring():
    news = UnsupportedRequest(requested="news", field="timeframe", reason="unsupported_data")
    score = UnsupportedRequest(requested="news sentiment score", field="timeframe",
                               reason="unsupported_data")
    spec = _spec(timeframe=None, unsupported=[news, score])
    out = apply_answer(spec, next_question(spec), "drop the sentiment score part",
                       StubClient([{"value": None, "resolved_requests": ["news sentiment score"]}]))
    assert [u.requested for u in out.unsupported] == ["news"]  # the shorter ask survives


def test_a_resolved_ask_rereturned_by_the_model_stays_resolved():
    spec = _spec(timeframe=None, unsupported=[INTRADAY])
    echo = {"requested": "'15-minute bars': unsupported timeframe", "field": "timeframe",
            "reason": "unsupported_timeframe"}
    out = apply_answer(spec, next_question(spec), "drop it",
                       StubClient([{"value": None, "resolved_requests": ["15-minute bars"],
                                    "unsupported": [echo]}]))
    assert out.unsupported == []


def test_one_wording_under_two_reasons_is_one_ask_and_resolves_together():
    # The trader resolves by their words, not by the model's reason classification.
    spec = _spec(timeframe=None, unsupported=[
        INTRADAY, UnsupportedRequest(requested="15-MINUTE bars", field="timeframe", reason="other")])
    out = apply_answer(spec, next_question(spec), "drop it",
                       StubClient([{"value": None, "resolved_requests": ["15-minute bars"]}]))
    assert out.unsupported == []


def test_a_new_entry_is_added_alongside_the_kept_ones():
    spec = _spec(timeframe=None, unsupported=[INTRADAY])
    q = next_question(spec)
    reply = {"value": None,
             "unsupported": [{"requested": "tick charts", "field": "timeframe", "reason": "unsupported_data"}]}
    out = apply_answer(spec, q, "tick charts then?", StubClient([reply]))
    assert sorted(u.requested for u in out.unsupported) == ["15-minute bars", "tick charts"]


def test_an_entry_for_another_field_is_refused():
    from src.llm.gemini import ReplyError

    spec = _spec(timeframe=None)
    stray = {"value": None, "unsupported": [{"requested": "x", "field": "trigger", "reason": "other"}]}
    with pytest.raises(ReplyError, match="other fields"):
        apply_answer(spec, next_question(spec), "whatever", StubClient([stray]))


# --- the loop ---------------------------------------------------------------------


def _extraction_stub(monkeypatch, spec):
    monkeypatch.setattr(el.extraction, "extract",
                        lambda idea, client: Reply(text="{}", parsed=spec,
                                                   usage=Usage(1, 1, 0, 2), finish_reason="STOP"))


def test_loop_asks_until_complete_and_saves_the_transcript(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(direction=None, control=None))
    client = StubClient([{"value": "long"}, {"value": {"description": "same dates, no pattern"}}])
    answers = iter(["long only", "same dates without the pattern"])
    said = []
    path = tmp_path / "s.json"
    spec = elicit("buy the dip", client, ask=lambda q: next(answers), say=said.append,
                  session_path=path, log_path=tmp_path / "log.jsonl")
    assert spec.direction == "long" and spec.control is not None
    assert "The spec is complete." in said
    saved = json.loads(path.read_text())
    assert saved["complete"] and saved["gaps_remaining"] == []
    assert [t["field"] for t in saved["turns"]] == ["direction", "control"]
    assert saved["turns"][0]["answer"] == "long only"
    assert not (tmp_path / "log.jsonl").exists()  # nothing unsupported came up


def test_stopping_early_keeps_the_open_gaps_in_the_transcript(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(direction=None, control=None))
    path = tmp_path / "s.json"
    said = []
    spec = elicit("idea", StubClient([{"value": "long"}]),
                  ask=lambda q: {0: "long"}.get(len(q) and 0) if "direction" in q else None,
                  say=said.append, session_path=path, log_path=tmp_path / "log.jsonl")
    saved = json.loads(path.read_text())
    assert spec.direction == "long" and not saved["complete"]
    assert any("control" in g for g in saved["gaps_remaining"])
    # A voluntary stop says so once; it isn't also reported as hitting the turn cap.
    assert any("Stopping here" in s for s in said)
    assert not any("Stopping after" in s for s in said)


def test_hitting_the_turn_cap_reports_the_real_answer_count(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(direction=None, control=None))
    said = []
    elicit("idea", StubClient([{"value": "long"}]), ask=lambda q: "long", say=said.append,
           session_path=tmp_path / "s.json", log_path=tmp_path / "log.jsonl", max_turns=1)
    assert any("Stopping after 1 answer;" in s for s in said)


def test_the_log_and_pointer_survive_a_failing_transcript_save(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(timeframe=None, unsupported=[INTRADAY]))
    said = []
    log = tmp_path / "log.jsonl"
    with pytest.raises(OSError):  # IsADirectoryError here; PermissionError on Windows
        elicit("idea", StubClient([]), ask=lambda q: None, say=said.append,
               session_path=tmp_path, log_path=log)  # the "file" is a directory
    assert any("Transcript:" in s for s in said)
    assert json.loads(log.read_text())["requested"] == "15-minute bars"


def test_unreadable_answers_count_toward_the_stall_guard(tmp_path, monkeypatch):
    # Two refused replies in a row skip the field like two stalled parses would:
    # re-asking re-spends tokens either way.
    _extraction_stub(monkeypatch, _spec(direction=None))
    stray = {"value": None, "unsupported": [{"requested": "x", "field": "trigger", "reason": "other"}]}
    client = StubClient([stray] * 2)
    said = []
    spec = elicit("idea", client, ask=lambda q: "gibberish", say=said.append,
                  session_path=tmp_path / "s.json", log_path=tmp_path / "log.jsonl", max_turns=10)
    assert spec.direction is None
    assert sum("asking again" in s for s in said) == 2
    assert any("isn't converging" in s for s in said)
    assert any(s.startswith("Done with the questions; still open: direction") for s in said)
    saved = json.loads((tmp_path / "s.json").read_text())
    # Error turns are saved too: a killed session keeps the error strings.
    assert [t["field"] for t in saved["turns"]] == ["direction"] * 2
    assert all("error" in t for t in saved["turns"])


def test_the_last_allowed_answer_completing_the_spec_says_so(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(direction=None))
    said = []
    spec = elicit("idea", StubClient([{"value": "long"}]), ask=lambda q: "long", say=said.append,
                  session_path=tmp_path / "s.json", log_path=tmp_path / "log.jsonl", max_turns=1)
    assert spec.direction == "long"
    assert "The spec is complete." in said and not any("Stopping after" in s for s in said)


def test_uncatalogued_uses_ids_are_dropped_with_a_notice(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(uses=["indicator:rsi", "indicator:stochastic"]))
    said = []
    spec = elicit("idea", StubClient([]), ask=lambda q: None, say=said.append,
                  session_path=tmp_path / "s.json", log_path=tmp_path / "log.jsonl")
    assert spec.uses == ["indicator:rsi"]
    assert any("indicator:stochastic" in s and "Dropped" in s for s in said)
    assert "The spec is complete." in said  # no gap left behind by the model's slip


def test_every_distinct_unsupported_request_is_logged_once(tmp_path, monkeypatch):
    _extraction_stub(monkeypatch, _spec(timeframe=None, unsupported=[INTRADAY]))
    # The answer resolves the intraday ask but raises a new one on the same field.
    reply = {"value": "daily",
             "unsupported": [{"requested": "tick charts", "field": "timeframe", "reason": "unsupported_data"}]}
    log = tmp_path / "log.jsonl"
    answers = iter(["daily is fine", None])
    spec = elicit("idea", StubClient([reply, {"value": None}]),
                  ask=lambda q: next(answers), say=lambda s: None,
                  session_path=tmp_path / "s.json", log_path=log)
    assert spec.timeframe == "daily"
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    # Both the extraction-time request and the one raised mid-loop, one line each.
    assert sorted(r["requested"] for r in rows) == ["15-minute bars", "tick charts"]
    assert all(r["idea"] == "idea" for r in rows)


def test_a_field_that_stops_converging_is_skipped_not_relooped(tmp_path, monkeypatch):
    # The model keeps parsing the answer into the same invalid shape (the live demo
    # burned 90k tokens this way): two stalled rounds skip the field, the rest proceeds.
    _extraction_stub(monkeypatch, _spec(size=None, control=None))
    bad_size = {"value": {"normalisation": "atr", "min": 1.0, "max": 0.25}}
    # Round 1 moves the gap from missing to invalid (that counts as movement); rounds
    # 2 and 3 leave it identical, which is the stall that triggers the skip.
    client = StubClient([bad_size, bad_size, bad_size, {"value": {"description": "same dates"}}])
    said = []
    spec = elicit("idea", client, ask=lambda q: "away 1 ATR, touch a quarter", say=said.append,
                  session_path=tmp_path / "s.json", log_path=tmp_path / "log.jsonl")
    assert any("isn't converging" in s for s in said)
    assert any(s.startswith("Done with the questions; still open: size") for s in said)
    assert spec.control is not None  # the loop moved on and finished the rest
    assert [g.field for g in find_gaps(spec)] == ["size"]  # kept as an open gap


def test_next_question_skips_given_fields():
    spec = _spec(direction=None, control=None)
    assert next_question(spec, frozenset({"direction"})).field == "control"
    assert next_question(spec, frozenset({"direction", "control"})) is None


def test_cli_rejects_zero_two_or_empty_idea_sources(tmp_path, capsys):
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n")
    for argv in ([], ["idea", "--file", "x.txt"], [""], ["--file", str(empty)]):
        with pytest.raises(SystemExit):
            el.main(argv)
