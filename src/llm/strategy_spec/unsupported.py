"""Back-reporting: the unsupported requests a spec carries are appended to a local log, and
`python -m src.llm.strategy_spec.unsupported summary` lists the most-requested ones. That
list is the development backlog: what users ask for that doesn't exist yet.

The log is `data/llm/unsupported_requests.jsonl` in the main checkout (git-ignored, found
through git like the Gemini usage ledger). Each spec writes one JSON line per distinct
request: the same wording (case and spacing ignored) and reason filed under two fields is
one line listing both fields and every detail given, so the summary counts ideas asking,
not how often the LLM repeated itself. "Intraday bars" and "intraday bars" count together,
while "15-minute bars" is its own line: merging synonyms is a judgement left to whoever
reads the summary.
"""

from __future__ import annotations

import argparse
import json
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.llm.paths import llm_data_dir, locked
from src.llm.strategy_spec.schema import StrategySpec, request_wording

LOG_NAME = "unsupported_requests.jsonl"


def default_log_path() -> Path:
    return llm_data_dir() / LOG_NAME


def log_unsupported(spec: StrategySpec, idea: str | None = None, path: Path | None = None,
                    now: datetime | None = None) -> int:
    """Append one line per distinct request in `spec`; returns how many were logged.
    `idea` is the user's original text, kept so a request can be read in context."""
    groups: dict[tuple[str, str], dict] = {}
    for item in spec.unsupported:
        g = groups.setdefault(item.key(), {"requested": item.requested, "reason": item.reason,
                                           "fields": [], "details": []})
        g["fields"] += [item.field] if item.field not in g["fields"] else []
        g["details"] += [item.detail] if item.detail and item.detail not in g["details"] else []
    if not groups:
        return 0
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("`now` must be timezone-aware")
    time = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    lines = [json.dumps({"time": time, "spec_name": spec.name, "idea": idea, **g}) for g in groups.values()]
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
            row = _parse(line)
            if row is None:
                warnings.warn(f"{path}:{n}: unreadable line skipped")
            else:
                rows.append(row)
    return rows


def _parse(line: str) -> dict | None:
    """A log line with its `time` as an aware datetime, or None if it isn't one."""
    try:
        row = json.loads(line)
        if not (isinstance(row, dict) and isinstance(row.get("requested"), str)
                and isinstance(row.get("reason"), str) and isinstance(row.get("fields"), list)):
            return None
        time = datetime.fromisoformat(row["time"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return {**row, "time": time} if time.utcoffset() is not None else None


def summarise(rows: list[dict], top: int = 20) -> list[str]:
    """The `top` most-requested (wording, reason) pairs, most requested first: how many
    ideas asked, the reason, the fields it was filed under, the last day it was asked
    (UTC), and the wording."""
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "fields": set(), "last": None})
    for r in rows:
        g = groups[(request_wording(r["requested"]), r["reason"])]
        g["count"] += 1
        g["fields"].update(map(str, r["fields"]))
        g["last"] = r["time"] if g["last"] is None else max(g["last"], r["time"])
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:top]
    return [f"{g['count']:>4}  {reason:<22} {','.join(sorted(g['fields'])):<20} "
            f"last {g['last'].astimezone(timezone.utc).date()}  {requested}"
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
