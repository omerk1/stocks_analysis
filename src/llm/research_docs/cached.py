"""Model replies about a question, kept in a JSON file so the same question always gets
the same reply: temperature 0 isn't repeatable, and a retrieval eval and an answer run
have to search the same thing. Used by question splitting (`split.py`) and query
rewriting (`rewrite.py`).

Each entry is keyed by the question and holds the prompt id it was made with
(the caller's `prompt_id`), so a reply from other instructions or another model is made
again. The `GeminiClient` is made on the first question not in the file, so a fully
cached run needs no API key. The id doesn't cover the caller's clean-up of a reply, so a
change to that needs a new cache file.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from src.llm.gemini import GeminiClient


def same_text(text: str) -> str:
    """What two questions are compared by: case, spacing and trailing punctuation ignored."""
    return " ".join(text.split()).lower().rstrip("?.!").rstrip()


def prompt_id(system: str, schema: type[BaseModel], model: str) -> str:
    """Which instructions made a reply: the system prompt, the reply schema and the model,
    hashed exactly."""
    parts = (system, json.dumps(schema.model_json_schema(), sort_keys=True), model)
    return hashlib.sha256("\n\x00\n".join(parts).encode()).hexdigest()[:16]


class ReplyCache:
    def __init__(self, client: Callable[[], GeminiClient], path: Path | None, pid: str, model: str):
        self.make_client, self.client, self.path, self.pid, self.model = client, None, path, pid, model
        self.known: dict[str, dict] = json.loads(path.read_text()) if path and path.exists() else {}

    def get(self, question: str) -> dict | None:
        """The stored entry, if it was made with this prompt id."""
        hit = self.known.get(question)
        return hit if hit and hit.get("prompt") == self.pid else None

    def fetch(self, question: str, field: str, clean: Callable[[str, list[str]], list[str]], *, purpose: str,
              system: str, schema: type[BaseModel]) -> list[str]:
        """The list `field` for the question: the stored one, or one asked for and stored,
        either way passed through `clean(question, items)` (a stored one too, in case the
        file was edited)."""
        if (hit := self.get(question)) and field in hit:
            return clean(question, hit[field])
        items = clean(question, getattr(self.ask(question, purpose=purpose, system=system, schema=schema), field))
        self.put(question, **{field: items})
        return items

    def ask(self, question: str, *, purpose: str, system: str, schema: type[BaseModel]) -> BaseModel:
        """One structured, temperature-0 call with the question as the prompt."""
        if self.client is None:
            client = self.make_client()
            if getattr(client, "model", self.model) != self.model:  # its replies would be stored under `model`
                raise ValueError(f"the client runs {client.model}, the cache is keyed by {self.model}")
            self.client = client
        return self.client.generate(question, purpose=purpose, system=system, response_schema=schema,
                                    temperature=0.0).parsed

    def put(self, question: str, **fields) -> None:
        """Store `fields` for the question and write the file (when there is one)."""
        self.known[question] = {"prompt": self.pid, **fields}
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.known, indent=1, ensure_ascii=False))
            os.replace(tmp, self.path)
