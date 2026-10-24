"""The review sheet: drafted labels in a short form a person can check against the
releases and correct. Corrections go into `probe/gold.json` (the drafts as
corrected), the gold set the extraction is scored on.

    python -m src.llm.guidance.review     # probe/drafts.json -> probe/review_sheet.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.llm.guidance import fetch
from src.llm.guidance.sample import PROBE_DIR, SAMPLE_PATH
from src.llm.guidance.schema import READABLE_REVISIONS, GuidanceItem, ReleaseLabel

DRAFTS_PATH = PROBE_DIR / "drafts.json"
SHEET_PATH = PROBE_DIR / "review_sheet.md"


def _num(x: float) -> str:
    """Full precision, thousands separated, no scientific notation: the reviewer
    compares it with the release digit by digit."""
    return f"{x:,.6f}".rstrip("0").rstrip(".")


def item_line(i: GuidanceItem) -> str:
    """e.g. 'eps (adjusted diluted EPS), year "fiscal 2015", adjusted: 2.1–2.2 USD per share; raised'."""
    value = {"range": lambda: f"{_num(i.low)}–{_num(i.high)} {i.unit}",
             "point": lambda: f"{_num(i.low)} {i.unit}",
             "floor": lambda: f">= {_num(i.low)} {i.unit}",
             "ceiling": lambda: f"<= {_num(i.high)} {i.unit}",
             "qualitative": lambda: "qualitative"}[i.shape]()
    return f'{i.metric} ({i.metric_text}), {i.period} "{i.period_text}", {i.basis}: {value}; {i.revision}'


def sheet(drafts: dict[str, dict], sample: pd.DataFrame, links: dict[str, str]) -> str:
    lines = ["# Guidance probe: draft labels to review", "",
             "Start with the table: one row per release (guidance present, items by metric, the "
             "revisions the release states, raised/maintained/lowered, with how many items each; "
             "whether the drafter flagged a doubt). The "
             "blocks below give every item; correct inline or as a note per slot. Item format: "
             "metric (as named), period \"as named\", basis: value; revision.", "",
             "| slot | ticker | year | present | revenue / eps / margin / other | revision stated | flagged |",
             "|---|---|---|---|---|---|---|"]
    rows = sample.sort_values("slot")
    for r in rows.itertuples():
        if r.accession not in drafts:  # no press release, so nothing to label
            lines.append(f"| {r.slot:02d} | {r.ticker} | {r.year} | no press release |  |  |  |")
            continue
        d = drafts[r.accession]
        items = ReleaseLabel.model_validate(d["label"]).items
        counts = " / ".join(str(sum(i.metric == m for i in items)) for m in ("revenue", "eps", "margin", "other"))
        stated = ", ".join(f"{n} {rev}" for rev in READABLE_REVISIONS
                           if (n := sum(i.revision == rev for i in items))) or "none"
        lines.append(f"| {r.slot:02d} | {r.ticker} | {r.year} | {'yes' if items else '**no**'} | "
                     f"{counts if items else ''} | {stated if items else ''} | {'yes' if d.get('uncertain') else ''} |")
    lines.append("")
    for r in rows[rows["accession"].isin(drafts)].itertuples():
        d = drafts[r.accession]
        lab = ReleaseLabel.model_validate(d["label"])
        head = f"**{r.slot:02d} {r.ticker}** ({r.year}, {r.sector}, {r.size}) — [release]({links.get(r.accession, r.index_url)})"
        lines.append(head + (f" — guidance: {len(lab.items)} items" if lab.guidance_present else " — **no guidance**"))
        lines += [f"- {item_line(i)}" for i in lab.items]
        for note in (lab.notes, d.get("uncertain", "")):
            if note:
                lines.append(f"- _note: {note}_")
        lines.append("")
    return "\n".join(lines)


def release_links(sample: pd.DataFrame, root: Path | None = None) -> dict[str, str]:
    root = root or fetch.cache_root()
    out = {}
    for acc in sample["accession"]:
        m = root / acc / "manifest.json"
        if m.exists():
            release = json.loads(m.read_text()).get("release")
            if release:
                out[acc] = release["url"]
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.review")
    parser.add_argument("--drafts", type=Path, default=DRAFTS_PATH)
    parser.add_argument("--out", type=Path, default=SHEET_PATH)
    args = parser.parse_args(argv)
    sample = pd.read_csv(SAMPLE_PATH, dtype={"accession": str})
    drafts = json.loads(args.drafts.read_text())
    args.out.write_text(sheet(drafts, sample, release_links(sample)) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
