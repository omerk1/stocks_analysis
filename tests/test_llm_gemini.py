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

    def __init__(self, prompt_tokens=100, text='{"answer": "yes"}', finish="STOP", output=20, thinking=0):
        self.prompt_tokens, self.text, self.finish = prompt_tokens, text, finish
        self.output, self.thinking = output, thinking
        self.generate_calls = []

    def count_tokens(self, *, model, contents):
        return SimpleNamespace(total_tokens=self.prompt_tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        meta = SimpleNamespace(prompt_token_count=self.prompt_tokens, candidates_token_count=self.output,
                               thoughts_token_count=self.thinking,
                               total_token_count=self.prompt_tokens + self.output + self.thinking)
        return SimpleNamespace(text=self.text, usage_metadata=meta,
                               candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=self.finish))])


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
