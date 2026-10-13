"""A Gemini client that can't overspend: the token budget from `docs/strategy-agent/idea.md`
("LLM guardrails"), shared by every LLM caller in the repo.

Every call goes through `GeminiClient.generate`, which:

1. **counts the prompt first.** Gemini's token-counting call is free. Everything sent is
   counted: the system instruction, the prompt and, for a structured reply, the JSON
   schema. A prompt over `Budget.max_input_tokens` is refused before anything is spent.
2. **checks the daily cap against the worst case.** Today's usage so far, plus this
   prompt, plus the most the reply can cost (`max_output_tokens` plus the thinking
   budget), must fit under `Budget.daily_token_cap`. Checking the worst case, not a
   guess, means the cap can't be overshot by one big reply.
3. **caps the reply.** `max_output_tokens` bounds the answer and `thinking_budget` the
   model's hidden reasoning. Gemini 2.5 models think by default, and thinking tokens are
   billed as output, so the default here is 0 (off) and a caller turns it on on purpose.
4. **records what was spent.** The token counts the API reports back are appended to a
   ledger (one JSON line per call). If the call fails after it may have been sent (anything
   but a connection that never opened or a 4xx rejection, which isn't billed), or the reply
   carries no usage, the worst case is recorded instead (`"estimated": true`): spending
   that might have happened counts against the cap. `python -m src.llm.gemini usage`
   summarises the ledger.

The ledger lives in the main checkout's `data/llm/` (git-ignored), found through git, so
every worktree charges the same daily total instead of each starting from zero. A file
lock is held from the cap check to the ledger write, so two processes can't both pass
the check on the same remaining budget; calls from parallel processes run one at a time,
which is fine at this repo's scale. Requests time out (`request_timeout_ms`, scaled to the
budget's worst-case reply), so a hung call can't hold the lock forever. The lock uses
`fcntl`, so this module is Unix only.

The cap is in tokens, not money: prices change and differ per model, token counts don't
drift. A prepaid balance with auto-reload off is the hard money limit; this is the one the
code controls.

Tests never reach the API: `GeminiClient` takes any object shaped like
`google.genai.Client` (`client=`), and the tests pass a stub.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import warnings
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from src.llm.paths import llm_data_dir

DEFAULT_MODEL = "gemini-2.5-flash"
LEDGER_NAME = "gemini_usage.jsonl"
# 4xx codes that can arrive after the reply was generated (request timeout, cancelled), so
# may be billed; every other 4xx is a rejection before generating.
BILLED_CLIENT_ERRORS = {408, 499}


@dataclass(frozen=True)
class Budget:
    max_input_tokens: int = 8_000
    max_output_tokens: int = 4_000
    # 0 turns thinking off on 2.5 Flash / Flash-Lite. 2.5 Pro can't turn it off (min 128).
    # Must be a fixed number: "dynamic" thinking (-1) has no worst case to check.
    thinking_budget: int = 0
    daily_token_cap: int = 300_000

    def __post_init__(self):
        if self.thinking_budget < 0:
            raise ValueError("thinking_budget must be >= 0; dynamic thinking (-1) can't be budgeted")
        if min(self.max_input_tokens, self.max_output_tokens, self.daily_token_cap) <= 0:
            raise ValueError("token caps must be positive")

    def request_timeout_ms(self) -> int:
        """The lock is held across the call, so a hung request must not hold it forever;
        but a big reply must still fit. 60 s plus 25 ms per worst-case reply token
        (160 s at the defaults)."""
        return 60_000 + 25 * (self.max_output_tokens + self.thinking_budget)


class BudgetExceeded(RuntimeError):
    """A call was refused before reaching the model. Nothing was spent."""


class ReplyError(RuntimeError):
    """The model replied, but not usably (cut off, blocked, empty, or not the requested
    shape). The tokens were spent and are in the ledger."""


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
    return llm_data_dir() / LEDGER_NAME


def read_ledger(path: Path) -> list[dict]:
    """Every readable ledger line. A damaged line (an interrupted write) is skipped with a
    warning rather than making every later call fail."""
    if not path.exists():
        return []
    rows = []
    with path.open() as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                row = None
            if isinstance(row, dict) and isinstance(row.get("time"), str) and isinstance(row.get("total_tokens"), int):
                rows.append(row)
                continue
            warnings.warn(f"{path}:{n}: unreadable ledger line skipped")
    return rows


def used_on(path: Path, day: str) -> int:
    """Total tokens recorded on `day` (UTC, `YYYY-MM-DD`)."""
    return sum(r["total_tokens"] for r in read_ledger(path) if r["time"][:10] == day)


@contextmanager
def _locked(ledger_path: Path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
            client = genai.Client(  # reads GOOGLE_API_KEY
                http_options=genai.types.HttpOptions(timeout=budget.request_timeout_ms()))
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
        import httpx
        from google.genai import errors, types

        b = self.budget
        schema = response_schema.model_json_schema() if response_schema else None
        # Count everything sent. The smoke test's reported input (26 tokens with the
        # strategy spec's schema attached) suggests the schema isn't billed as input, but
        # counting it errs on the safe side and costs nothing.
        sent = [system, prompt, json.dumps(schema) if schema else None]
        counted = self._client.models.count_tokens(
            model=self.model, contents="\n\n".join(p for p in sent if p)).total_tokens
        if counted > b.max_input_tokens:
            raise BudgetExceeded(f"prompt is {counted} tokens, over the per-call cap of {b.max_input_tokens}")
        worst = counted + b.max_output_tokens + b.thinking_budget

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=b.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=b.thinking_budget),
            response_mime_type="application/json" if schema else None,
            # `response_json_schema` takes standard JSON Schema ($defs/$ref, nullable anyOf,
            # additionalProperties). The older `response_schema` takes an OpenAPI subset and
            # rejects `additionalProperties`, which `extra="forbid"` models emit.
            response_json_schema=schema,
        )
        with _locked(self.ledger_path):
            used = used_on(self.ledger_path, self._now().date().isoformat())
            if used + worst > b.daily_token_cap:
                raise BudgetExceeded(
                    f"{used} tokens used today; this call could take {worst} more, "
                    f"over the daily cap of {b.daily_token_cap}")
            try:
                response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # The request never left the machine (offline, DNS, refused): nothing billed.
                raise
            except errors.ClientError as e:
                # 4xx (bad request, bad key, rate limit): rejected before generating, not
                # billed, except a timeout or cancel that may come after generation.
                if e.code in BILLED_CLIENT_ERRORS:
                    self._record(purpose, Usage(counted, 0, 0, worst), estimated=True)
                raise
            except BaseException:
                # Anything else (server error, read timeout, Ctrl-C mid-call) may have been
                # billed after generation finished: charge the worst case rather than nothing.
                self._record(purpose, Usage(counted, 0, 0, worst), estimated=True)
                raise
            meta = response.usage_metadata
            if meta is None or not meta.total_token_count:
                usage, estimated = Usage(counted, 0, 0, worst), True
            else:
                usage, estimated = Usage(
                    prompt_tokens=meta.prompt_token_count or 0,
                    output_tokens=meta.candidates_token_count or 0,
                    thinking_tokens=meta.thoughts_token_count or 0,
                    total_tokens=meta.total_token_count,
                ), False
            self._record(purpose, usage, estimated=estimated)

        if not response.candidates:
            raise ReplyError("no reply: the prompt was blocked")
        finish = response.candidates[0].finish_reason
        # Some responses carry no finish reason. A structured reply that validates is
        # complete (a cut-off one wouldn't parse); free text can't be checked, so it raises.
        if finish is None and response_schema is not None:
            finish_reason = "STOP"
        else:
            finish_reason = getattr(finish, "name", str(finish))
        if finish_reason == "MAX_TOKENS":
            raise ReplyError(f"reply cut off at max_output_tokens={b.max_output_tokens}")
        if finish_reason != "STOP":
            raise ReplyError(f"reply stopped early: {finish_reason}")
        text = response.text or ""
        if not text.strip():
            raise ReplyError("empty reply")
        parsed = None
        if response_schema is not None:
            try:
                parsed = response_schema.model_validate_json(text)
            except ValidationError as e:
                raise ReplyError(f"reply doesn't match {response_schema.__name__}: {e}") from e
        return Reply(text=text, parsed=parsed, usage=usage, finish_reason=finish_reason)

    def _record(self, purpose: str, usage: Usage, estimated: bool = False) -> None:
        line = {"time": self._now().isoformat(timespec="seconds"), "model": self.model,
                "purpose": purpose, **asdict(usage)}
        if estimated:
            line["estimated"] = True
        # After an interrupted write the file ends mid-line; start a new line so this row
        # isn't glued onto the damaged one and lost with it.
        damaged_end = False
        if self.ledger_path.exists() and self.ledger_path.stat().st_size:
            with self.ledger_path.open("rb") as f:
                f.seek(-1, 2)
                damaged_end = f.read(1) != b"\n"
        with self.ledger_path.open("a") as f:
            f.write(("\n" if damaged_end else "") + json.dumps(line) + "\n")


def summarise(rows: list[dict]) -> list[str]:
    """One line per (day, model, purpose): calls and tokens, newest day first."""
    totals: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for r in rows:
        t = totals[(r["time"][:10], r.get("model", "?"), r.get("purpose", "?"))]
        t[0] += 1
        t[1] += r.get("prompt_tokens", 0)
        t[2] += r.get("output_tokens", 0)
        t[3] += r.get("thinking_tokens", 0)
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
        print(f"today ({today}, UTC): {used_on(path, today)} tokens "
              f"(the default daily cap is {Budget().daily_token_cap}; a caller may set its own)")
        for line in summarise(rows):
            print(line)


if __name__ == "__main__":
    main()
