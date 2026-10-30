"""Step 8 of the research-docs RAG (`docs/ideation/llm_agentic_workflows.md`, idea 1):
`ask`, the command for daily use. The docs-check before re-running a hypothesis that
CLAUDE.md asks for, without the manual grep.

The answer itself is `answer.answer` unchanged (re-rank top 5, Gemini, citation check).
What this adds around it:

- **A stale-index warning.** Every chunk keeps the hash of the file it was cut from (its
  source `Document`'s, which covers the text and the loader's metadata), so comparing
  those with the docs as they are now lists the files changed, added or removed since the
  build, with no model involved (`stale`). The answer still runs: most questions don't
  touch those files. A source from a changed or deleted file is marked in the source
  list, since what it says may be out of date. Rebuilding (~13 min) is left to `index build`.
- **`--rewrite`** (off by default): search the question and three rewordings, re-ranked
  against the question (`rewrite.pooled_search`), for questions worded unlike the docs.
  About 290 more tokens and up to four times the re-ranking time. Rewordings are cached in
  `data/llm/ask_rewrites.json`, never in the eval's committed cache. If the rewording call
  fails, the question is searched as written (`FallbackRewriter`).
- **`--show-sources`**: each source's text under its citation, to check a claim against
  what it cites without opening the file.
- **The budget.** The answer call keeps `answer.BUDGET` and the shared 300k daily cap
  (`gemini.Budget`). When the answer call fails (refused by the budget, before it is sent;
  or a reply that can't be used, which the ledger has charged), the retrieved sources are
  printed anyway: retrieval is local and free, so the question still gets a search result.
- **A question log**, `data/llm/ask_log.jsonl` (git-ignored, in the main checkout like the
  token ledger): question, options, sources, answer or error, tokens, seconds and the
  index's build date and staleness, one JSON line per question, failed answer calls
  included (a failed search is a local bug, and stops with its traceback). Raw
  material for growing the eval set, not part of it: eval questions are written blind and
  their golds judged by hand.

    python -m src.llm.research_docs.ask "Was a golden cross tested?"
    python -m src.llm.research_docs.ask --rewrite --show-sources -k 8 "..."
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from google.genai import errors
from llama_index.core.schema import BaseNode, NodeWithScore

from src.llm.gemini import BudgetExceeded, DailyCapExceeded, GeminiClient, ReplyError, default_ledger_path, used_on
from src.llm.paths import llm_data_dir, locked
from src.llm.research_docs.answer import BUDGET, MAX_K, Answered, answer, cited, format_answered, source_lines
from src.llm.research_docs.retrieve import TOP_K, cite

LOG_NAME = "ask_log.jsonl"
REWRITES_NAME = "ask_rewrites.json"
REBUILD = "python -m src.llm.research_docs.index build  (~13 min)"
# How a Gemini call can fail: refused by the budget, an unusable reply, the API, or the
# network. Anything else (a bug, a missing API key, an unwritable ledger or cache) raises.
CALL_FAILED = (BudgetExceeded, ReplyError, errors.APIError, httpx.HTTPError)


@dataclass(frozen=True)
class Staleness:
    built: date
    changed: list[str]  # in the index, changed since
    added: list[str]  # not in the index
    removed: list[str]  # in the index, gone from the docs

    @property
    def count(self) -> int:
        return len(self.changed) + len(self.added) + len(self.removed)

    def outdated(self, path: str | None) -> str | None:
        """"changed" or "deleted" when the indexed chunks of `path` no longer match the docs."""
        return "changed" if path in self.changed else "deleted" if path in self.removed else None

    def __bool__(self) -> bool:
        return self.count > 0


def _file(node: BaseNode) -> str | None:
    """The id of the file a chunk came from (its path, `load.load_documents`'s doc id)."""
    return node.source_node.node_id if node.source_node else None


def stale(nodes: Iterable[BaseNode], current: dict[str, str], built: date) -> Staleness:
    """Compare each chunk's source-file hash, stored at build time, with `current`
    (doc id -> hash of the docs as they are now)."""
    indexed = {_file(n): n.source_node.hash for n in nodes if n.source_node}
    return Staleness(built,
                     changed=sorted(p for p in indexed.keys() & current.keys() if indexed[p] != current[p]),
                     added=sorted(current.keys() - indexed.keys()),
                     removed=sorted(indexed.keys() - current.keys()))


def format_staleness(s: Staleness) -> str:
    if not s:
        return f"index built {s.built}, up to date"
    lines = [f"index built {s.built}; {s.count} doc file{'s' * (s.count != 1)} differ from it "
             "(answers may miss or be out of date):"]
    for label, paths in (("changed", s.changed), ("not in the index", s.added), ("deleted", s.removed)):
        lines += [f"  {label}: {p}" for p in paths]
    lines.append(f"  rebuild: {REBUILD}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Asked:
    question: str
    sources: list[NodeWithScore]
    answered: Answered | None  # None when the answer call failed
    error: str | None  # why it failed, and what to do about it
    seconds: float


def ask(question: str, search: Callable[[str, int], list[NodeWithScore]], client: GeminiClient,
        k: int = TOP_K) -> Asked:
    """Search, then answer from what was found. A failed answer call (`CALL_FAILED`)
    keeps the sources instead of raising."""
    if not 1 <= k <= MAX_K:  # before the search, which answer() can't check first here
        raise ValueError(f"k must be 1-{MAX_K}, got {k}")
    start = time.perf_counter()
    sources = search(question, k)
    answered = error = None
    try:
        answered = answer(question, lambda q, n: sources, client, k)
    except DailyCapExceeded as e:
        error = f"{e}. The call wasn't sent; the daily cap resets at 00:00 UTC."
    except BudgetExceeded as e:
        error = f"{e}. The call wasn't sent; the sources are too long for one call, try a lower -k."
    except CALL_FAILED as e:
        error = f"{type(e).__name__}: {e}. Any tokens it used are in the ledger (python -m src.llm.gemini usage)."
    return Asked(question, sources, answered, error, time.perf_counter() - start)


class FallbackRewriter:
    """`rewriter`, or no rewordings when its call fails (said on stderr, kept in `error`):
    `rewrite.pooled_search` then pools the question's own search alone, which is the plain
    re-rank search."""

    def __init__(self, rewriter: Callable[[str], list[str]]):
        self.rewriter, self.error = rewriter, None

    def __call__(self, question: str) -> list[str]:
        try:
            return self.rewriter(question)
        except CALL_FAILED as e:
            self.error = f"{type(e).__name__}: {e}"
            print(f"rewording failed ({self.error}); searching the question as written", file=sys.stderr)
            return []


def _outdated_mark(s: Staleness) -> Callable[[BaseNode], str]:
    def mark(node: BaseNode) -> str:
        how = s.outdated(_file(node))
        return f"  (file {how} since the build)" if how else ""
    return mark


def _indented(text: str) -> list[str]:
    return ["      " + line for line in text.splitlines()] + [""]


def format_asked(a: Asked, s: Staleness, used_today: int, daily_cap: int, show_text: bool = False) -> str:
    text = _indented if show_text else None
    if a.answered is None:
        body = [f"Not answered: {a.error}", "", "Sources (retrieved, not answered):",
                *source_lines(a.sources, mark=_outdated_mark(s), text=text)]
    else:
        body = [format_answered(a.answered, mark=_outdated_mark(s), text=text)]
    return "\n".join([format_staleness(s), "", *body,
                      f"{a.seconds:.1f}s; today {used_today:,} of {daily_cap:,} tokens (UTC day)"])


def log_entry(a: Asked, s: Staleness, k: int, rewrite: bool, now: datetime, rewrite_error: str | None = None) -> dict:
    """One question-log line. Sources are kept by citation and chunk id, not text: the
    docs hold the text, and a rebuild changes the ids anyway. `rewrite` is what was asked
    for; `rewrite_error`, when set, says the question was searched as written instead."""
    entry = {"time": now.isoformat(timespec="seconds"), "question": a.question, "k": k, "rewrite": rewrite,
             "index_built": s.built.isoformat(), "stale_files": s.count,
             "sources": [{"cite": cite(h.node), "id": h.node.node_id,
                          "outdated": s.outdated(_file(h.node))} for h in a.sources],
             "seconds": round(a.seconds, 1)}
    if rewrite_error:
        entry["rewrite_error"] = rewrite_error
    if a.answered is None:
        return entry | {"error": a.error}
    an = a.answered
    return entry | {"in_docs": an.answer.in_docs, "answer": an.answer.answer, "cited": cited(an.answer.answer),
                    "problems": an.problems, "prompt_tokens": an.usage.prompt_tokens,
                    "output_tokens": an.usage.output_tokens, "total_tokens": an.usage.total_tokens}


def append_log(path: Path, entry: dict) -> None:
    with locked(path), path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.llm.research_docs.ask")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=TOP_K, help=f"sources given to the model (default {TOP_K}, at most {MAX_K})")
    ap.add_argument("--rewrite", action="store_true", help="also search three rewordings (~290 tokens more)")
    ap.add_argument("--show-sources", action="store_true", help="print each source's text")
    args = ap.parse_args()
    if not 1 <= args.k <= MAX_K:
        ap.error(f"-k must be 1-{MAX_K}")
    from src.llm.research_docs import rewrite
    from src.llm.research_docs.index import PERSIST_DIR, embed_model, load_index
    from src.llm.research_docs.keyword import KeywordIndex
    from src.llm.research_docs.load import load_documents
    from src.llm.research_docs.rerank import cross_encoder, rerank_search

    index = load_index(embed_model())
    nodes = list(index.docstore.docs.values())
    # when the docstore was last written (UTC), which a copy of the directory resets
    built = datetime.fromtimestamp((PERSIST_DIR / "docstore.json").stat().st_mtime, timezone.utc).date()
    staleness = stale(nodes, {d.doc_id: d.hash for d in load_documents()}, built)
    keywords = KeywordIndex(nodes)
    score = cross_encoder()
    rewriter = None
    if args.rewrite:
        rewriter = FallbackRewriter(rewrite.Rewriter(lambda: GeminiClient(budget=rewrite.BUDGET),
                                                     llm_data_dir() / REWRITES_NAME))
        search = lambda q, k: rewrite.pooled_search(index, keywords, score, rewriter, q, k)  # noqa: E731
    else:
        search = lambda q, k: rerank_search(index, keywords, score, q, k)  # noqa: E731

    asked = ask(args.question, search, GeminiClient(budget=BUDGET), args.k)
    now = datetime.now(timezone.utc)
    used = used_on(default_ledger_path(), now.date().isoformat())
    print(format_asked(asked, staleness, used, BUDGET.daily_token_cap, args.show_sources))  # before the log can fail
    append_log(llm_data_dir() / LOG_NAME,
               log_entry(asked, staleness, args.k, args.rewrite, now, rewriter.error if rewriter else None))
    if asked.answered is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
