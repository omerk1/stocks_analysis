"""Run the frozen prompt (`prompt.py`, v1) on the sample and cache every reply.

One call per release that has a press release, through `prompt.extract` (Gemini
2.5 Flash, temperature 0, thinking off). Each reply is saved as
`probe/extractions/<version>/<accession>.json`, committed, with the prompt's
fingerprint and a hash of the text it read; a cached reply with the same
fingerprint and text hash is never asked again, so a rerun spends nothing. A reply
that comes back unusable (cut off, not the schema) is cached as an error and
scored as a miss: v1 is measured as it is, never retried until it passes.

    python -m src.llm.guidance.extract            # spends tokens: ~50 calls
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.llm.gemini import BudgetExceeded, ReplyError
from src.llm.guidance import fetch, prompt
from src.llm.guidance.sample import PROBE_DIR, SAMPLE_PATH
from src.llm.guidance.schema import ReleaseLabel

EXTRACTIONS_DIR = PROBE_DIR / "extractions" / prompt.PROMPT_VERSION


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def cached(path: Path, fingerprint: str, digest: str) -> dict | None:
    if not path.exists():
        return None
    row = json.loads(path.read_text())
    return row if row.get("fingerprint") == fingerprint and row.get("text_sha256") == digest else None


def run_one(gemini, accession: str, text: str, out_dir: Path = EXTRACTIONS_DIR) -> dict:
    """The cached reply for one release, calling the model only when there is none."""
    fp, digest = prompt.fingerprint(), text_hash(text)
    path = out_dir / f"{accession}.json"
    hit = cached(path, fp, digest)
    if hit is not None:
        return hit
    row = {"accession": accession, "prompt_version": prompt.PROMPT_VERSION, "fingerprint": fp,
           "model": prompt.MODEL, "text_sha256": digest}
    try:
        reply = prompt.extract(gemini, text)
        row |= {"label": reply.parsed.model_dump(), "usage": asdict(reply.usage)}
    except (ReplyError, BudgetExceeded) as e:  # BudgetExceeded: e.g. a release over the input cap
        row["error"] = f"{type(e).__name__}: {e}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=1) + "\n")
    return row


def load_extractions(out_dir: Path = EXTRACTIONS_DIR) -> dict[str, ReleaseLabel | None]:
    """accession -> the parsed reply, or None for a cached error. Refuses a reply made
    under another fingerprint: scoring it as this version would be scoring a stale run."""
    out = {}
    for path in sorted(out_dir.glob("*.json")):
        row = json.loads(path.read_text())
        if row.get("fingerprint") != prompt.fingerprint():
            raise ValueError(f"{path.name} was made under another prompt fingerprint; rerun the extraction")
        out[row["accession"]] = ReleaseLabel.model_validate(row["label"]) if "label" in row else None
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.extract")
    parser.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    args = parser.parse_args(argv)
    sample = pd.read_csv(args.sample, dtype={"accession": str})
    gemini = prompt.client()
    for r in sample.itertuples():
        text = fetch.load_text(r.accession)
        if text is None:
            print(f"{r.slot:>2} {r.ticker:<6} no press release")
            continue
        row = run_one(gemini, r.accession, text)
        if "error" in row:
            print(f"{r.slot:>2} {r.ticker:<6} ERROR {row['error'][:80]}")
        else:
            label = row["label"]
            print(f"{r.slot:>2} {r.ticker:<6} present={label['guidance_present']!s:<5} items={len(label['items'])}")


if __name__ == "__main__":
    main()
