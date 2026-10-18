"""Score the cached extractions against the gold labels, and measure how often
releases carry guidance at all.

Gold: `probe/gold.json` (accession -> `ReleaseLabel`), the drafted labels as
corrected by hand. Effective N is releases, which here are also companies (one
release per company by construction).

- **Presence:** release-level precision and recall of `guidance_present`. A
  cached error (unusable reply) counts as "no guidance found".
- **Items:** within a release, a predicted item can match a gold item only on the
  same metric and period; pairs are chosen greedily by how many other fields agree
  (basis, shape, values, revision), one-to-one. Item recall = matched / gold items,
  precision = matched / predicted items.
- **Fields,** on matched pairs: shape, values (low and high equal, to 1e-6
  relative), unit, basis, revision.
- **Revision readability:** of gold items, the share whose revision is raised,
  maintained or lowered, i.e. readable from the release; per release, whether any
  item's is. Plus the model's accuracy on those items.

    python -m src.llm.guidance.score     # writes probe/score_<version>.json, prints tables
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd

from src.llm.guidance import prompt
from src.llm.guidance.extract import EXTRACTIONS_DIR, load_extractions
from src.llm.guidance.sample import PROBE_DIR, SAMPLE_PATH
from src.llm.guidance.schema import READABLE_REVISIONS, GuidanceItem, ReleaseLabel

GOLD_PATH = PROBE_DIR / "gold.json"
FIELDS = ("shape", "values", "unit", "basis", "revision")
HEADLINE = ("revenue", "eps", "margin")


def load_gold(path: Path = GOLD_PATH) -> dict[str, ReleaseLabel]:
    return {acc: ReleaseLabel.model_validate(lab) for acc, lab in json.loads(path.read_text()).items()}


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def field_agreement(g: GuidanceItem, p: GuidanceItem) -> dict[str, bool]:
    return {"shape": g.shape == p.shape,
            "values": _same(g.low, p.low) and _same(g.high, p.high),
            "unit": g.unit.strip().lower() == p.unit.strip().lower(),
            "basis": g.basis == p.basis,
            "revision": g.revision == p.revision}


def years(period_text: str) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d\d\b", period_text))


def same_period(g: GuidanceItem, p: GuidanceItem) -> bool:
    """Same period kind, and the same years where both name them ('fiscal 2015' can't
    pair with '2016'; 'full year' with 'fiscal 2015' can)."""
    gy, py = years(g.period_text), years(p.period_text)
    return g.period == p.period and (not gy or not py or gy == py)


def match_items(gold: list[GuidanceItem], pred: list[GuidanceItem]) -> list[tuple[int, int]]:
    """One-to-one (gold index, predicted index) pairs on the same metric and period,
    greedily by the number of agreeing fields, ties to the earlier items."""
    candidates = sorted(
        ((-sum(field_agreement(g, p).values()), i, j)
         for i, g in enumerate(gold) for j, p in enumerate(pred)
         if g.metric == p.metric and same_period(g, p)))
    used_g, used_p, pairs = set(), set(), []
    for _, i, j in candidates:
        if i not in used_g and j not in used_p:
            used_g.add(i)
            used_p.add(j)
            pairs.append((i, j))
    return sorted(pairs)


def headline_only(labels: dict[str, ReleaseLabel | None]) -> dict[str, ReleaseLabel | None]:
    """The same labels kept to revenue, EPS and margin items: the outlook a reader of
    "guidance" usually means, without capex, tax rates, production and the like."""
    out = {}
    for acc, lab in labels.items():
        if lab is None:
            out[acc] = None
            continue
        items = [i for i in lab.items if i.metric in HEADLINE]
        out[acc] = ReleaseLabel(guidance_present=bool(items), items=items, notes=lab.notes)
    return out


def score(gold: dict[str, ReleaseLabel], pred: dict[str, ReleaseLabel | None]) -> dict:
    missing = sorted(set(gold) - set(pred))
    if missing:
        raise ValueError(f"no extraction for {len(missing)} gold releases, e.g. {missing[:3]}")
    tp = fp = fn = tn = errors = 0
    n_gold = n_pred = n_matched = 0
    agree = {f: 0 for f in FIELDS}
    readable_items = readable_right = 0
    for acc, g in gold.items():
        p = pred[acc]
        errors += p is None
        p_items = p.items if p is not None else []
        has_p = bool(p_items)
        tp += g.guidance_present and has_p
        fp += (not g.guidance_present) and has_p
        fn += g.guidance_present and not has_p
        tn += not g.guidance_present and not has_p
        n_gold += len(g.items)
        n_pred += len(p_items)
        pairs = match_items(g.items, p_items)
        n_matched += len(pairs)
        for i, j in pairs:
            for f, ok in field_agreement(g.items[i], p_items[j]).items():
                agree[f] += ok
        by_gold = dict(pairs)
        for i, item in enumerate(g.items):
            if item.revision in READABLE_REVISIONS:
                readable_items += 1
                readable_right += i in by_gold and p_items[by_gold[i]].revision == item.revision
    ratio = lambda a, b: a / b if b else None
    return {
        "releases": len(gold), "unusable_replies": errors,
        "presence": {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                     "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)},
        "items": {"gold": n_gold, "predicted": n_pred, "matched": n_matched,
                  "recall": ratio(n_matched, n_gold), "precision": ratio(n_matched, n_pred)},
        "field_accuracy_on_matched": {f: ratio(agree[f], n_matched) for f in FIELDS},
        "revision": {"gold_items_readable": readable_items, "share_of_gold_items": ratio(readable_items, n_gold),
                     "model_right_on_readable": ratio(readable_right, readable_items)},
    }


def revision_by_release(gold: dict[str, ReleaseLabel]) -> pd.Series:
    """Per release with guidance: whether any item's revision is readable."""
    return pd.Series({acc: any(i.revision in READABLE_REVISIONS for i in g.items)
                      for acc, g in gold.items() if g.guidance_present})


def coverage(gold: dict[str, ReleaseLabel], sample: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """How often releases carry guidance, by year, sector and size, with N. Over the
    labeled releases only (a sample release without a press release has no label)."""
    s = sample[sample["accession"].isin(gold)]
    s = s.assign(present=s["accession"].map(lambda a: gold[a].guidance_present))
    out = {}
    for by in ("year", "sector", "size"):
        t = s.groupby(by).agg(releases=("present", "size"), with_guidance=("present", "sum"))
        t["share"] = (t["with_guidance"] / t["releases"]).round(2)
        out[by] = t
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.score")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--extractions", type=Path, default=EXTRACTIONS_DIR)
    parser.add_argument("--out", type=Path, default=PROBE_DIR / f"score_{prompt.PROMPT_VERSION}.json")
    args = parser.parse_args(argv)
    gold = load_gold(args.gold)
    sample = pd.read_csv(SAMPLE_PATH, dtype={"accession": str})
    pred = load_extractions(args.extractions)
    result = {}
    for view, g, p in (("all", gold, pred), ("headline", headline_only(gold), headline_only(pred))):
        r = score(g, p)
        rev = revision_by_release(g)
        r["revision"] |= {"releases_with_guidance": len(rev), "releases_with_a_readable_revision": int(rev.sum())}
        cov = coverage(g, sample)
        r["coverage"] = {k: v.reset_index().to_dict("records") for k, v in cov.items()}
        result[view] = r
        print(f"\n=== {view} items ===")
        print(json.dumps({k: v for k, v in r.items() if k != "coverage"}, indent=1))
        for k, v in cov.items():
            print(f"\nby {k}:\n{v.to_string()}")
    args.out.write_text(json.dumps(result, indent=1, default=int) + "\n")


if __name__ == "__main__":
    main()
