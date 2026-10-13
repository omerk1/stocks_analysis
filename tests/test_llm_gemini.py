import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from src.llm.gemini import (
    Budget, BudgetExceeded, GeminiClient, ReplyError, read_ledger, summarise, used_on)

NOW = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)


class StubModels:
    """Shaped like `google.genai.Client().models`: records calls, returns canned replies."""

    def __init__(self, prompt_tokens=100, text='{"answer": "yes"}', finish="STOP", output=20, thinking=0,
                 candidates=True, usage=True, error=None):
        self.prompt_tokens, self.text, self.finish = prompt_tokens, text, finish
        self.output, self.thinking = output, thinking
        self.candidates, self.usage, self.error = candidates, usage, error
        self.generate_calls, self.counted = [], []

    def count_tokens(self, *, model, contents):
        self.counted.append(contents)
        return SimpleNamespace(total_tokens=self.prompt_tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        if self.error:
            raise self.error
        meta = SimpleNamespace(prompt_token_count=self.prompt_tokens, candidates_token_count=self.output,
                               thoughts_token_count=self.thinking,
                               total_token_count=self.prompt_tokens + self.output + self.thinking)
        reason = SimpleNamespace(name=self.finish) if self.finish else None
        candidates = [SimpleNamespace(finish_reason=reason)] if self.candidates else []
        return SimpleNamespace(text=self.text, usage_metadata=meta if self.usage else None, candidates=candidates)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


def _client(tmp_path, budget=Budget(), **stub):
    models = StubModels(**stub)
    client = GeminiClient(budget=budget, ledger_path=tmp_path / "usage.jsonl",
                          client=SimpleNamespace(models=models), now=lambda: NOW)
    return client, models


def test_call_is_recorded_in_the_ledger(tmp_path):
    client, _ = _client(tmp_path, prompt_tokens=100, output=20, thinking=5)
    reply = client.generate("hi", purpose="test")
    assert reply.text == '{"answer": "yes"}' and reply.finish_reason == "STOP"
    assert (reply.usage.prompt_tokens, reply.usage.output_tokens, reply.usage.thinking_tokens,
            reply.usage.total_tokens) == (100, 20, 5, 125)
    [row] = read_ledger(tmp_path / "usage.jsonl")
    assert row["purpose"] == "test" and row["total_tokens"] == 125 and row["time"].startswith("2026-10-13")


def test_config_caps_output_and_thinking(tmp_path):
    client, models = _client(tmp_path, budget=Budget(max_output_tokens=500, thinking_budget=0))
    client.generate("hi", purpose="test", system="be brief")
    config = models.generate_calls[0].config
    assert config.max_output_tokens == 500
    assert config.thinking_config.thinking_budget == 0
    assert config.system_instruction == "be brief"


def test_prompt_over_the_input_cap_is_refused_before_any_call(tmp_path):
    client, models = _client(tmp_path, budget=Budget(max_input_tokens=50), prompt_tokens=51)
    with pytest.raises(BudgetExceeded, match="per-call cap"):
        client.generate("long", purpose="test")
    assert models.generate_calls == []
    assert read_ledger(tmp_path / "usage.jsonl") == []


def test_daily_cap_checks_the_worst_case(tmp_path):
    budget = Budget(max_output_tokens=400, thinking_budget=0, daily_token_cap=1_000)
    ledger = tmp_path / "usage.jsonl"
    # 500 already used today, 10,000 yesterday (doesn't count).
    ledger.write_text(
        json.dumps({"time": "2026-10-12T23:59:00+00:00", "total_tokens": 10_000}) + "\n"
        + json.dumps({"time": "2026-10-13T08:00:00+00:00", "total_tokens": 500}) + "\n")
    assert used_on(ledger, "2026-10-13") == 500
    client, models = _client(tmp_path, budget=budget, prompt_tokens=100)
    with pytest.raises(BudgetExceeded, match="daily cap"):  # 500 + 100 + 400 = 1,000 fits; next one doesn't
        client.generate("a", purpose="test")
        client.generate("b", purpose="test")
    assert len(models.generate_calls) == 1


def test_structured_reply_is_validated(tmp_path):
    client, models = _client(tmp_path)
    reply = client.generate("hi", purpose="test", response_schema=Answer)
    assert reply.parsed == Answer(answer="yes")
    config = models.generate_calls[0].config
    assert config.response_mime_type == "application/json"
    # Standard JSON Schema, which keeps additionalProperties: false (the older
    # response_schema field rejects it; found by the smoke test).
    assert config.response_json_schema["additionalProperties"] is False


def test_unusable_replies_raise_but_are_still_charged(tmp_path):
    client, _ = _client(tmp_path, text='{"wrong": 1}')
    with pytest.raises(ReplyError, match="doesn't match Answer"):
        client.generate("hi", purpose="test", response_schema=Answer)
    client, _ = _client(tmp_path, finish="MAX_TOKENS")
    with pytest.raises(ReplyError, match="cut off"):
        client.generate("hi", purpose="test")
    assert len(read_ledger(tmp_path / "usage.jsonl")) == 2


def test_count_includes_system_and_schema(tmp_path):
    client, models = _client(tmp_path)
    client.generate("the prompt", purpose="test", system="the system", response_schema=Answer)
    [counted] = models.counted
    assert "the system" in counted and "the prompt" in counted and '"answer"' in counted


def test_worst_case_includes_thinking(tmp_path):
    # 100 prompt + 400 output + 501 thinking = 1,001 > 1,000, refused; with 500 thinking it fits.
    client, models = _client(tmp_path, budget=Budget(max_output_tokens=400, thinking_budget=501,
                                                     daily_token_cap=1_000))
    with pytest.raises(BudgetExceeded):
        client.generate("a", purpose="test")
    client, _ = _client(tmp_path, budget=Budget(max_output_tokens=400, thinking_budget=500, daily_token_cap=1_000))
    client.generate("a", purpose="test")


def test_blocked_stopped_or_empty_replies_raise_and_are_charged(tmp_path):
    for stub, match in [(dict(candidates=False), "blocked"), (dict(finish="SAFETY"), "SAFETY"),
                        (dict(text=""), "empty")]:
        client, _ = _client(tmp_path, **stub)
        with pytest.raises(ReplyError, match=match):
            client.generate("hi", purpose="test")
    assert len(read_ledger(tmp_path / "usage.jsonl")) == 3


def test_missing_usage_or_failed_call_charges_the_worst_case(tmp_path):
    budget = Budget(max_output_tokens=400, thinking_budget=0)
    client, _ = _client(tmp_path, budget=budget, usage=False)
    client.generate("hi", purpose="test")
    client, _ = _client(tmp_path, budget=budget, error=TimeoutError("read timeout"))
    with pytest.raises(TimeoutError):
        client.generate("hi", purpose="test")
    rows = read_ledger(tmp_path / "usage.jsonl")
    assert [(r["total_tokens"], r.get("estimated")) for r in rows] == [(500, True), (500, True)]


def test_rejected_request_is_not_charged_but_an_interrupted_one_is(tmp_path):
    from google.genai import errors

    rejected = errors.ClientError(429, {"error": {"code": 429, "message": "rate limited", "status": "RESOURCE_EXHAUSTED"}})
    client, _ = _client(tmp_path, error=rejected)
    with pytest.raises(errors.ClientError):
        client.generate("hi", purpose="test")
    assert read_ledger(tmp_path / "usage.jsonl") == []
    client, _ = _client(tmp_path, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        client.generate("hi", purpose="test")
    assert [r.get("estimated") for r in read_ledger(tmp_path / "usage.jsonl")] == [True]


def test_missing_finish_reason_with_text_is_a_normal_reply(tmp_path):
    client, _ = _client(tmp_path, finish=None)
    assert client.generate("hi", purpose="test").finish_reason == "STOP"


def test_parallel_calls_cannot_share_the_last_budget(tmp_path):
    # Room for exactly one call (100 + 400 = 500 of 700); the stub is slow, so without the
    # lock both threads would pass the check before either records.
    import threading
    import time

    budget = Budget(max_output_tokens=400, daily_token_cap=700)
    outcomes = []

    def call():
        client, models = _client(tmp_path, budget=budget, output=400)
        original = models.generate_content
        models.generate_content = lambda **kw: (time.sleep(0.2), original(**kw))[1]
        try:
            client.generate("hi", purpose="test")
            outcomes.append("ok")
        except BudgetExceeded:
            outcomes.append("refused")

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "refused"]


def test_damaged_ledger_line_is_skipped(tmp_path):
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(json.dumps({"time": "2026-10-13T08:00:00+00:00", "total_tokens": 7}) + "\n"
                      + '{"time": "2026-10-13T09')
    with pytest.warns(UserWarning, match="unreadable"):
        assert used_on(ledger, "2026-10-13") == 7
    # The next record starts on a fresh line instead of being glued onto the damaged one.
    client, _ = _client(tmp_path)
    with pytest.warns(UserWarning):
        client.generate("hi", purpose="test")
    with pytest.warns(UserWarning):
        assert used_on(ledger, "2026-10-13") == 7 + 120
    # Valid JSON that isn't a record is skipped too.
    ledger.write_text("12\n")
    with pytest.warns(UserWarning):
        assert used_on(ledger, "2026-10-13") == 0


def test_budget_rejects_dynamic_thinking():
    with pytest.raises(ValueError, match="dynamic"):
        Budget(thinking_budget=-1)


def test_summarise_groups_by_day_model_and_purpose():
    rows = [{"time": "2026-10-13T09:00:00+00:00", "model": "m", "purpose": "p", "prompt_tokens": 10,
             "output_tokens": 2, "thinking_tokens": 0, "total_tokens": 12}] * 2
    [line] = summarise(rows)
    assert "calls    2" in line and "total       24" in line


@pytest.mark.skipif(not os.environ.get("RUN_GEMINI_SMOKE"), reason="calls the real API; set RUN_GEMINI_SMOKE=1")
def test_real_api_smoke():
    """One real call, with the strategy spec as the reply schema: checks the key, the
    budget plumbing, and whether Gemini accepts the spec's JSON schema. A few hundred
    tokens, recorded in the real ledger."""
    from src.llm.strategy_spec.schema import StrategySpec

    client = GeminiClient(budget=Budget(max_output_tokens=1_500))
    reply = client.generate(
        "Trading idea: buy daily-bar breakouts above a 20-day high. Fill in only what this sentence states.",
        purpose="smoke_test", response_schema=StrategySpec)
    assert isinstance(reply.parsed, StrategySpec)
    assert reply.usage.total_tokens > 0
