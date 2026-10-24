"""Score the cached extractions against the gold labels, and measure how often
releases carry guidance at all.

Gold (built by `adjudicate.py`): `probe/gold.json`, accession -> `ReleaseLabel` with
the headline items (revenue, EPS, margin), and `probe/gold_presence.json`,
accession -> whether the release carries any guidance in scope. The extractions are
cut to the same scope (`in_scope`) before scoring. Effective N is releases, which
here are also companies (one release per company by construction).

Two views: **headline** (everything below) and **any** (presence and coverage only;
the other items, capex and the like, were checked at release level only).

- **Presence:** release-level precision and recall of `guidance_present`. A
  cached error (unusable reply) counts as "no guidance found".
- **Items:** within a release, a predicted item can match a gold item only on the
  same metric and period; pairs are chosen greedily by how many other fields agree
  (basis, shape, values, revision), one-to-one. Item recall = matched / gold items,
  precision = matched / predicted items.
- **Fields,** on matched pairs: shape, values (low and high equal, to 1e-6
  relative, once the unit's scale is applied), unit, basis, revision ('initiated'
  counted as 'not_stated', `revision_kind`).
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
PRESENCE_PATH = PROBE_DIR / "gold_presence.json"
FIELDS = ("shape", "values", "unit", "basis", "revision")
HEADLINE = ("revenue", "eps", "margin")
SCALES = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}


def load_gold(path: Path = GOLD_PATH) -> dict[str, ReleaseLabel]:
    return {acc: ReleaseLabel.model_validate(lab) for acc, lab in json.loads(path.read_text()).items()}


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def scale(unit: str) -> float:
    """The multiplier a unit's word carries: 'USD billions' -> 1e9, else 1."""
    u = unit.lower()
    return next((m for word, m in SCALES.items() if word in u), 1.0)


def same_values(g: GuidanceItem, p: GuidanceItem) -> bool:
    """Low and high equal once the unit's scale is applied ($1.2 billion = $1,200 million)."""
    sg, sp = scale(g.unit), scale(p.unit)
    f = lambda x, s: None if x is None else x * s
    return _same(f(g.low, sg), f(p.low, sp)) and _same(f(g.high, sg), f(p.high, sp))


def in_scope(item: GuidanceItem, release_year: int) -> bool:
    """The mechanical part of the agreed scope: a number (not words), for a quarter or a
    year, no named year after the one following the release (so not a multi-year
    target). Synergy targets, capital-return plans and the other judgment calls are
    left to the person adjudicating (`adjudicate.py`)."""
    return (item.shape != "qualitative" and item.period in ("quarter", "year")
            and all(int(y) <= release_year + 1 for y in years(item.period_text)))


def scoped(labels: dict[str, ReleaseLabel | None], release_years: dict[str, int]) -> dict[str, ReleaseLabel | None]:
    """The labels with out-of-scope items dropped (`in_scope`)."""
    out = {}
    for acc, lab in labels.items():
        if lab is None:
            out[acc] = None
            continue
        items = [i for i in lab.items if in_scope(i, release_years[acc])]
        out[acc] = ReleaseLabel(guidance_present=bool(items), items=items, notes=lab.notes)
    return out


def field_agreement(g: GuidanceItem, p: GuidanceItem) -> dict[str, bool]:
    return {"shape": g.shape == p.shape,
            "values": same_values(g, p),
            "unit": g.unit.strip().lower() == p.unit.strip().lower(),
            "basis": g.basis == p.basis,
            "revision": revision_kind(g.revision) == revision_kind(p.revision)}


def revision_kind(revision: str) -> str:
    """'initiated' counts as 'not_stated': neither revises earlier guidance, which is what
    the probe measures, and the readings split on it by habit (a Q4 release's
    full-year outlook reads as new to one, as not a revision to the other)."""
    return "not_stated" if revision == "initiated" else revision


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


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def presence(gold: dict[str, bool], pred: dict[str, bool]) -> dict:
    """Release-level confusion counts, precision and recall of 'carries guidance'."""
    tp = sum(gold[a] and pred[a] for a in gold)
    fp = sum(not gold[a] and pred[a] for a in gold)
    fn = sum(gold[a] and not pred[a] for a in gold)
    tn = sum(not gold[a] and not pred[a] for a in gold)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}


def score(gold: dict[str, ReleaseLabel], pred: dict[str, ReleaseLabel | None]) -> dict:
    missing = sorted(set(gold) - set(pred))
    if missing:
        raise ValueError(f"no extraction for {len(missing)} gold releases, e.g. {missing[:3]}")
    errors = n_gold = n_pred = n_matched = 0
    agree = {f: 0 for f in FIELDS}
    readable_items = readable_right = 0
    for acc, g in gold.items():
        p = pred[acc]
        errors += p is None
        p_items = p.items if p is not None else []
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
    ratio = _ratio
    return {
        "releases": len(gold), "unusable_replies": errors,
        "presence": presence({a: g.guidance_present for a, g in gold.items()},
                             {a: bool(pred[a] and pred[a].items) for a in gold}),
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


def coverage(present: dict[str, bool], sample: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """How often releases carry guidance, by year, sector and size, with N. Over the
    labeled releases only (a sample release without a press release has no label)."""
    s = sample[sample["accession"].isin(present)]
    s = s.assign(present=s["accession"].map(present).astype(bool))
    out = {}
    for by in ("year", "sector", "size"):
        t = s.groupby(by).agg(releases=("present", "size"), with_guidance=("present", "sum"))
        t["share"] = (t["with_guidance"] / t["releases"]).round(2)
        out[by] = t
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.score")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--presence", type=Path, default=PRESENCE_PATH)
    parser.add_argument("--extractions", type=Path, default=EXTRACTIONS_DIR)
    parser.add_argument("--out", type=Path, default=PROBE_DIR / f"score_{prompt.PROMPT_VERSION}.json")
    args = parser.parse_args(argv)
    gold = load_gold(args.gold)
    gold_any = json.loads(args.presence.read_text())
    sample = pd.read_csv(SAMPLE_PATH, dtype={"accession": str})
    pred = scoped(load_extractions(args.extractions), dict(zip(sample["accession"], sample["year"])))
    r = score(gold, headline_only(pred))
    rev = revision_by_release(gold)
    r["revision"] |= {"releases_with_guidance": len(rev), "releases_with_a_readable_revision": int(rev.sum())}
    views = {"headline": (r, coverage({a: g.guidance_present for a, g in gold.items()}, sample)),
             "any": ({"presence": presence(gold_any, {a: bool(pred[a] and pred[a].items) for a in gold_any})},
                     coverage(gold_any, sample))}
    result = {}
    for view, (res, cov) in views.items():
        result[view] = res | {"coverage": {k: v.reset_index().to_dict("records") for k, v in cov.items()}}
        print(f"\n=== {view} ===")
        print(json.dumps(res, indent=1))
        for k, v in cov.items():
            print(f"\nby {k}:\n{v.to_string()}")
    args.out.write_text(json.dumps(result, indent=1, default=int) + "\n")


if __name__ == "__main__":
    main()
