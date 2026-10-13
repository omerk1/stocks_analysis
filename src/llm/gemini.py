"""A Gemini client that can't overspend: the token budget from `docs/strategy-agent/idea.md`
("LLM guardrails"), shared by every LLM caller in the repo.

Every call goes through `GeminiClient.generate`, which:

1. **counts the prompt first.** Gemini's token-counting call is free. A prompt over
   `Budget.max_input_tokens` is refused before anything is spent.
2. **checks the daily cap against the worst case.** Today's usage so far, plus this
   prompt, plus the most the reply can cost (`max_output_tokens` plus the thinking
   budget), must fit under `Budget.daily_token_cap`. Checking the worst case, not a
   guess, means the cap can't be overshot by one big reply.
3. **caps the reply.** `max_output_tokens` bounds the answer and `thinking_budget` the
   model's hidden reasoning. Gemini 2.5 models think by default, and thinking tokens are
   billed as output, so the default here is 0 (off) and a caller turns it on on purpose.
4. **records what was spent.** The token counts the API reports back are appended to a
   ledger (one JSON line per call), which step 2 reads. `python -m src.llm.gemini usage`
   summarises it.

The ledger lives in the main checkout's `data/llm/` (git-ignored), found through git, so
every worktree charges the same daily total instead of each starting from zero.

The cap is in tokens, not money: prices change and differ per model, token counts don't
drift. On Flash-class models the default daily cap is well under a dollar at the prices
listed when this was written. A prepaid balance with auto-reload off is the hard money
limit; this is the one the code controls.

Tests never reach the API: `GeminiClient` takes any object shaped like
`google.genai.Client` (`client=`), and the tests pass a stub.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gemini-2.5-flash"
LEDGER_NAME = "gemini_usage.jsonl"


@dataclass(frozen=True)
class Budget:
    max_input_tokens: int = 8_000
    max_output_tokens: int = 4_000
    # 0 turns thinking off on 2.5 Flash / Flash-Lite. 2.5 Pro can't turn it off (min 128).
    thinking_budget: int = 0
    daily_token_cap: int = 300_000


class BudgetExceeded(RuntimeError):
    """A call was refused before reaching the model. Nothing was spent."""


class ReplyError(RuntimeError):
    """The model replied, but not usably (cut off, or not the requested shape). The
    tokens were spent and are in the ledger."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class Reply:
    text: str
    parsed: BaseModel | None
    usage: Usage
    finish_reason: str


def default_ledger_path() -> Path:
    """`data/llm/gemini_usage.jsonl` in the main checkout, from any worktree."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=Path(__file__).parent,
        ).stdout.strip()
        root = Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        root = Path(__file__).resolve().parents[2]
    return root / "data" / "llm" / LEDGER_NAME


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def used_on(path: Path, day: str) -> int:
    """Total tokens recorded on `day` (UTC, `YYYY-MM-DD`)."""
    return sum(r["total_tokens"] for r in read_ledger(path) if r["time"][:10] == day)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GeminiClient:
    def __init__(
        self,
        budget: Budget = Budget(),
        model: str = DEFAULT_MODEL,
        ledger_path: Path | None = None,
        client: Any = None,
        now=_utc_now,
    ):
        self.budget = budget
        self.model = model
        self.ledger_path = ledger_path or default_ledger_path()
        self._now = now
        if client is None:
            from dotenv import load_dotenv
            from google import genai

            load_dotenv()
            client = genai.Client()  # reads GOOGLE_API_KEY
        self._client = client

    def generate(
        self,
        prompt: str,
        *,
        purpose: str,
        system: str | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> Reply:
        """One budgeted call. `purpose` labels the ledger line (e.g. "strategy_spec.extract").

        With `response_schema`, Gemini is asked for JSON in that shape and the reply is
        validated into it (`Reply.parsed`); a reply that doesn't validate raises.
        """
        from google.genai import types

        b = self.budget
        # The system instruction is billed as input too; count it with the prompt.
        counted = self._client.models.count_tokens(
            model=self.model, contents="\n\n".join(p for p in (system, prompt) if p)
        ).total_tokens
        if counted > b.max_input_tokens:
            raise BudgetExceeded(f"prompt is {counted} tokens, over the per-call cap of {b.max_input_tokens}")
        today = self._now().date().isoformat()
        used = used_on(self.ledger_path, today)
        worst = counted + b.max_output_tokens + b.thinking_budget
        if used + worst > b.daily_token_cap:
            raise BudgetExceeded(
                f"{used} tokens used today; this call could take {worst} more, "
                f"over the daily cap of {b.daily_token_cap}")

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=b.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=b.thinking_budget),
            response_mime_type="application/json" if response_schema else None,
            # `response_json_schema` takes standard JSON Schema ($defs/$ref, nullable anyOf,
            # additionalProperties). The older `response_schema` takes an OpenAPI subset and
            # rejects `additionalProperties`, which `extra="forbid"` models emit.
            response_json_schema=response_schema.model_json_schema() if response_schema else None,
        )
        response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)

        meta = response.usage_metadata
        usage = Usage(
            prompt_tokens=meta.prompt_token_count or 0,
            output_tokens=meta.candidates_token_count or 0,
            thinking_tokens=meta.thoughts_token_count or 0,
            total_tokens=meta.total_token_count or 0,
        )
        self._record(purpose, usage)

        finish = response.candidates[0].finish_reason if response.candidates else None
        finish_reason = getattr(finish, "name", str(finish))
        text = response.text or ""
        if finish_reason == "MAX_TOKENS":
            raise ReplyError(f"reply cut off at max_output_tokens={b.max_output_tokens}")
        parsed = None
        if response_schema is not None:
            try:
                parsed = response_schema.model_validate_json(text)
            except ValidationError as e:
                raise ReplyError(f"reply doesn't match {response_schema.__name__}: {e}") from e
        return Reply(text=text, parsed=parsed, usage=usage, finish_reason=finish_reason)

    def _record(self, purpose: str, usage: Usage) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        line = {"time": self._now().isoformat(timespec="seconds"), "model": self.model,
                "purpose": purpose, **asdict(usage)}
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(line) + "\n")


def summarise(rows: list[dict]) -> list[str]:
    """One line per (day, model, purpose): calls and tokens, newest day first."""
    totals: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for r in rows:
        t = totals[(r["time"][:10], r["model"], r["purpose"])]
        t[0] += 1
        t[1] += r["prompt_tokens"]
        t[2] += r["output_tokens"]
        t[3] += r["thinking_tokens"]
        t[4] += r["total_tokens"]
    lines = []
    for (day, model, purpose), (calls, p, o, th, tot) in sorted(totals.items(), reverse=True):
        lines.append(f"{day}  {model:<22} {purpose:<28} calls {calls:>4}  in {p:>8}  out {o:>7}  "
                     f"thinking {th:>7}  total {tot:>8}")
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.gemini")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("usage", help="tokens spent per day, model and purpose")
    args = parser.parse_args(argv)
    if args.command == "usage":
        path = default_ledger_path()
        rows = read_ledger(path)
        print(f"ledger: {path}")
        today = _utc_now().date().isoformat()
        print(f"today ({today}, UTC): {used_on(path, today)} of {Budget().daily_token_cap} tokens")
        for line in summarise(rows):
            print(line)


if __name__ == "__main__":
    main()
