"""Back-reporting: every unsupported request a spec carries is appended to a local log, and
`python -m src.llm.strategy_spec.unsupported summary` lists the most-requested ones. That
list is the development backlog: what users ask for that doesn't exist yet.

The log is `data/llm/unsupported_requests.jsonl` in the main checkout (git-ignored, found
through git like the Gemini usage ledger), one JSON line per request. Requests are grouped
by their wording (case and spacing ignored) and reason, so "Intraday bars" and "intraday
bars" count together, while "15-minute bars" is its own line: merging synonyms is a
judgement left to whoever reads the summary.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.llm.paths import llm_data_dir, locked
from src.llm.strategy_spec.schema import StrategySpec, distinct_unsupported, request_wording

LOG_NAME = "unsupported_requests.jsonl"


def default_log_path() -> Path:
    return llm_data_dir() / LOG_NAME


def log_unsupported(spec: StrategySpec, idea: str | None = None, path: Path | None = None,
                    now: datetime | None = None) -> int:
    """Append one line per unsupported request in `spec`; returns how many were logged.
    `idea` is the user's original text, kept so a request can be read in context. A request
    the spec repeats is logged once: the count is of ideas asking, not of LLM repeats."""
    items = distinct_unsupported(spec)
    if not items:
        return 0
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")
    time = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    lines = [json.dumps({"time": time, "spec_name": spec.name, "idea": idea, **item.model_dump()})
             for item in items]
    path = path or default_log_path()
    # Locked like the Gemini ledger: sessions in other worktrees append to the same file.
    with locked(path), path.open("a") as f:
        f.write("".join(line + "\n" for line in lines))
    return len(lines)


def read_log(path: Path) -> list[dict]:
    """Every readable line; a damaged one (an interrupted write) is skipped with a warning."""
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
            if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("time", "requested", "reason")):
                rows.append(row)
                continue
            warnings.warn(f"{path}:{n}: unreadable line skipped")
    return rows


def summarise(rows: list[dict], top: int = 20) -> list[str]:
    """The `top` most-requested (wording, reason) pairs, most requested first: count,
    reason, the fields it was asked for in, when it was last asked, and the wording."""
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "fields": set(), "last": ""})
    for r in rows:
        g = groups[(request_wording(r["requested"]), r["reason"])]
        g["count"] += 1
        g["fields"].add(str(r.get("field", "?")))
        g["last"] = max(g["last"], r["time"])
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:top]
    return [f"{g['count']:>4}  {reason:<22} {','.join(sorted(g['fields'])):<20} last {g['last'][:10]}  {requested}"
            for (requested, reason), g in ranked]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.strategy_spec.unsupported")
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary", help="the most-requested things the platform can't test yet")
    summary.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)
    if args.command == "summary":
        path = default_log_path()
        rows = read_log(path)
        print(f"log: {path} ({len(rows)} requests)")
        for line in summarise(rows, args.top):
            print(line)


if __name__ == "__main__":
    main()
