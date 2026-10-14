"""Back-reporting: the unsupported requests a spec carries are appended to a local log, and
`python -m src.llm.strategy_spec.unsupported summary` lists the most-requested ones. That
list is the development backlog: what users ask for that doesn't exist yet.

The log is `data/llm/unsupported_requests.jsonl` in the main checkout (git-ignored, found
through git like the Gemini usage ledger). Each spec writes one JSON line per distinct
request: the same wording (case, spacing and hyphenation ignored) and reason filed under two fields is
one line listing both fields, with each detail under the field it was given for
(`"details": {"trigger": ["intraday entry"]}`), so the summary counts ideas asking,
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
from src.llm.strategy_spec.schema import StrategySpec, group_unsupported, request_wording

LOG_NAME = "unsupported_requests.jsonl"


def default_log_path() -> Path:
    return llm_data_dir() / LOG_NAME


def log_unsupported(spec: StrategySpec, idea: str | None = None, path: Path | None = None,
                    now: datetime | None = None) -> int:
    """Append one line per distinct request in `spec`; returns how many were logged.
    `idea` is the user's original text, kept so a request can be read in context."""
    groups = group_unsupported(spec.unsupported)
    if not groups:
        return 0
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("`now` must be timezone-aware")
    time = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    # Keys listed by hand: the file format is its own contract, not whatever the class holds.
    lines = [json.dumps({"time": time, "spec_name": spec.name, "idea": idea, "requested": g.requested,
                         "reason": g.reason, "fields": list(g.fields),
                         "details": {f: list(d) for f, d in g.details}}) for g in groups]
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
            if _readable(row):
                rows.append(row)
            else:
                warnings.warn(f"{path}:{n}: unreadable line skipped")
    return rows


def _time(row: dict) -> datetime:
    return datetime.fromisoformat(row["time"])


def _is_text(x) -> bool:
    """A non-blank string, as the spec's own text fields are."""
    return isinstance(x, str) and bool(x.strip())


def _readable(row) -> bool:
    """A line a reader can rely on: wording, reason, at least one field, an aware time, and
    `details` (optional, since the summary doesn't use it) as `{field: [details]}`, every
    key one of the line's fields and every detail text. Shape only: reasons and fields
    aren't checked against today's schema, so old lines still count after it changes."""
    if not (isinstance(row, dict) and _is_text(row.get("requested")) and _is_text(row.get("reason"))
            and isinstance(row.get("fields"), list) and row["fields"]
            and all(_is_text(f) for f in row["fields"]) and _is_text(row.get("time"))):
        return False
    details = row.get("details", {})
    if not (isinstance(details, dict) and set(details) <= set(row["fields"])
            and all(isinstance(d, list) and d and all(_is_text(x) for x in d) for d in details.values())):
        return False
    try:
        return _time(row).utcoffset() is not None
    except ValueError:
        return False


def summarise(rows: list[dict], top: int = 20) -> list[str]:
    """The `top` most-requested (wording, reason) pairs, most requested first: how many
    ideas asked, the reason, the fields it was filed under, the last day it was asked
    (UTC), and the wording."""
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "fields": set(), "last": None, "wording": None})
    for r in rows:
        g = groups[(request_wording(r["requested"]), r["reason"])]
        g["count"] += 1
        g["fields"].update(r["fields"])
        # Shown as the user first put it, collapsed onto one line.
        g["wording"] = g["wording"] or " ".join(r["requested"].split())
        t = _time(r)
        g["last"] = t if g["last"] is None else max(g["last"], t)
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:top]
    return [f"{g['count']:>4}  {reason:<22} {','.join(sorted(g['fields'])):<20} "
            f"last {g['last'].astimezone(timezone.utc).date()}  {g['wording']}"
            for (_, reason), g in ranked]


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
