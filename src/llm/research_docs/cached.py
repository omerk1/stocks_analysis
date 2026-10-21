"""Model replies about a question, kept in a JSON file so the same question always gets
the same reply: temperature 0 isn't repeatable, and a retrieval eval and an answer run
have to search the same thing. Used by question splitting (`split.py`) and query
rewriting (`rewrite.py`).

Each entry is keyed by the question and holds the prompt id it was made with
(the caller's `prompt_id`), so a reply from other instructions or another model is made
again. The `GeminiClient` is made on the first question not in the file, so a fully
cached run needs no API key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from src.llm.gemini import GeminiClient


class ReplyCache:
    def __init__(self, client: Callable[[], GeminiClient], path: Path | None, pid: str, model: str):
        self.make_client, self.client, self.path, self.pid, self.model = client, None, path, pid, model
        self.known: dict[str, dict] = json.loads(path.read_text()) if path and path.exists() else {}

    def get(self, question: str) -> dict | None:
        """The stored entry, if it was made with this prompt id."""
        hit = self.known.get(question)
        return hit if hit and hit["prompt"] == self.pid else None

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
