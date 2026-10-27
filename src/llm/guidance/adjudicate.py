"""The gold set from two independent readings plus a person's answers on where they differ.

The two readings of each release: the drafts (`probe/drafts.json`, written by Claude
subagents before any extraction ran) and prompt v1's extractions (Gemini). Both are cut
to the agreed scope (`score.in_scope`) the same way. Then, release by release:

- **Headline items** (revenue, EPS, margin) are matched as the scorer matches them
  (`score.match_items`). A matched pair that agrees on shape, values, basis and
  revision stands as gold. A pair that differs becomes a `fields` question; an item
  only one reading has becomes an `only` question.
- **Other guidance** (capex, tax rate, production...) is checked at release level
  only: where neither reading has a matched headline item but either has other items,
  an `other` question asks whether any of them is guidance under the rules (the
  judgment calls: synergy targets, capital-return plans, non-financial goals).
- **A spot check:** `N_CHECK` releases drawn (seeded) from those with no question at
  all, asked as `check` questions, measure how often both readings are wrong the same
  way, the error the disagreements can't show.

In a `fields` question the two readings are A and B in a seeded random order, so the
answer can't lean to one source. Every question quotes the release.

Answers go on the `**Answer:**` line of `probe/questions.md`: A or B (or a letter per
row, `A B`), yes or no (or, for a check, ok / none found). Anything else is a correction in words, which
`probe/answer_overrides.json` turns into labels (qid -> {"items": [...]} or
{"present": bool}); `gold` refuses to build until every question has a usable answer.

    python -m src.llm.guidance.adjudicate questions   # -> probe/questions.md, probe/questions.json
    python -m src.llm.guidance.adjudicate gold        # -> probe/gold.json, gold_presence.json, gold_meta.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.llm.guidance import fetch, score
from src.llm.guidance.extract import EXTRACTIONS_DIR, load_extractions
from src.llm.guidance.sample import PROBE_DIR, SAMPLE_PATH
from src.llm.guidance.schema import GuidanceItem, ReleaseLabel

DRAFTS_PATH = PROBE_DIR / "drafts.json"
SEED = 20261024
N_CHECK = 8
COMPARED = ("shape", "values", "basis", "revision")  # unit is compared through the values' scale
QUESTIONS_MD = PROBE_DIR / "questions.md"
QUESTIONS_JSON = PROBE_DIR / "questions.json"
OVERRIDES_PATH = PROBE_DIR / "answer_overrides.json"
PRESENCE_PATH = score.PRESENCE_PATH
META_PATH = PROBE_DIR / "gold_meta.json"

ACCEPT = {"fields": {"a", "b"}, "only": {"yes", "no"}, "other": {"yes", "no"},
          "check": {"ok", "yes", "none found"}}
REVISION_WORDS = {"raised": "raised", "maintained": "kept the same", "lowered": "lowered",
                  "initiated": "given for the first time", "withdrawn": "withdrawn", "not_stated": "not said"}
BASIS_WORDS = {"adjusted": "adjusted (non-GAAP)", "gaap": "GAAP", "unstated": "not said"}


def readings(drafts: dict[str, dict], extractions: dict[str, ReleaseLabel | None], sample: pd.DataFrame
             ) -> dict[str, tuple[ReleaseLabel, ReleaseLabel]]:
    """accession -> (draft, model), both cut to scope; a model error reads as no items."""
    years = dict(zip(sample["accession"], sample["year"]))
    d = {a: ReleaseLabel.model_validate(v["label"]) for a, v in drafts.items()}
    m = {a: extractions.get(a) or ReleaseLabel(guidance_present=False, items=[]) for a in d}
    d, m = score.scoped(d, years), score.scoped(m, years)
    return {a: (d[a], m[a]) for a in d}


def differing(g: GuidanceItem, p: GuidanceItem) -> list[str]:
    agree = score.field_agreement(g, p)
    return [f for f in COMPARED if not agree[f]]


def questions(pairs: dict[str, tuple[ReleaseLabel, ReleaseLabel]], sample: pd.DataFrame,
              seed: int = SEED, n_check: int = N_CHECK) -> list[dict]:
    rng = np.random.default_rng(seed)
    out, quiet = [], []
    for r in sample.sort_values("slot").itertuples():
        if r.accession not in pairs:
            continue
        draft, model = pairs[r.accession]
        d = [i for i in draft.items if i.metric in score.HEADLINE]
        m = [i for i in model.items if i.metric in score.HEADLINE]
        head = {"accession": r.accession, "slot": int(r.slot), "ticker": r.ticker, "year": int(r.year)}
        asked = []
        matched = score.match_items(d, m)
        for i, j in matched:
            diff = differing(d[i], m[j])
            if diff:
                draft_first = bool(rng.random() < 0.5)
                a, b = (d[i], m[j]) if draft_first else (m[j], d[i])
                asked.append(head | {"kind": "fields", "diff": diff, "a": a.model_dump(), "b": b.model_dump(),
                                     "a_from": "draft" if draft_first else "model"})
        for side, items, used in (("draft", d, {i for i, _ in matched}), ("model", m, {j for _, j in matched})):
            asked += [head | {"kind": "only", "item": it.model_dump(), "from": side}
                      for k, it in enumerate(items) if k not in used]
        others = [i for i in draft.items + model.items if i.metric not in score.HEADLINE]
        if not matched and others:
            seen, uniq = set(), []
            for it in others:
                key = (it.metric_text.lower(), it.period_text.lower(), it.low, it.high)
                if key not in seen:
                    seen.add(key)
                    uniq.append(it.model_dump())
            asked.append(head | {"kind": "other", "items": uniq})
        if asked:
            out += asked
        else:
            quiet.append(head | {"kind": "check", "items": [d[i].model_dump() for i, _ in matched]})
    pick = sorted(rng.choice(len(quiet), size=min(n_check, len(quiet)), replace=False)) if quiet else []
    out += [quiet[k] for k in pick]
    out.sort(key=lambda q: (q["slot"], ["fields", "only", "other", "check"].index(q["kind"])))
    for n, q in enumerate(out, 1):
        q["id"] = f"Q{n:02d}"
    return out


def _num(x: float) -> str:
    """Full precision, thousands separated, no scientific notation: the reader
    compares it with the release digit by digit."""
    return f"{x:,.6f}".rstrip("0").rstrip(".")


def release_links(sample: pd.DataFrame, root: Path | None = None) -> dict[str, str]:
    """accession -> the press release's EDGAR URL, from the fetch manifests."""
    root = root or fetch.cache_root()
    out = {}
    for acc in sample["accession"]:
        m = root / acc / "manifest.json"
        if m.exists():
            release = json.loads(m.read_text()).get("release")
            if release:
                out[acc] = release["url"]
    return out


def forecast(i: dict) -> str:
    v, u = _num, i["unit"]
    return {"range": lambda: f"{v(i['low'])} to {v(i['high'])} {u}", "point": lambda: f"{v(i['low'])} {u}",
            "floor": lambda: f"at least {v(i['low'])} {u}", "ceiling": lambda: f"up to {v(i['high'])} {u}",
            "qualitative": lambda: "in words only"}[i["shape"]]()


ROWS = {"values": ("forecast", forecast), "shape": ("forecast", forecast),
        "basis": ("adjusted or GAAP", lambda i: BASIS_WORDS[i["basis"]]),
        "revision": ("change vs earlier guidance", lambda i: REVISION_WORDS[i["revision"]])}
ROW_FIELDS = {"forecast": ("shape", "low", "high", "unit"), "adjusted or GAAP": ("basis",),
              "change vs earlier guidance": ("revision",)}


def rows(q: dict) -> list[str]:
    """The table rows a `fields` question shows, in order (shape and values share one)."""
    return list(dict.fromkeys(ROWS[f][0] for f in q["diff"]))


def picks(q: dict, answer: str) -> list[str] | None:
    """'a' / 'b' for the whole item, or one letter per row ('a b'); None if neither."""
    letters = re.findall(r"[ab]", answer) if re.fullmatch(r"[ab](?:[\s,/]+[ab])*", answer) else []
    if len(letters) == 1:
        return letters * len(rows(q))
    return letters if len(letters) == len(rows(q)) else None


def combined(q: dict, letters: list[str]) -> dict:
    """The item taking each row from the reading picked for it (period and wording from A)."""
    if set(letters) == {"b"}:
        return dict(q["b"])
    item = dict(q["a"])
    for row, letter in zip(rows(q), letters):
        if letter == "b":
            item |= {f: q["b"][f] for f in ROW_FIELDS[row]}
    return item


def quotes(items: list[dict]) -> list[str]:
    seen, out = set(), []
    for i in items:
        e = i["evidence"].strip()
        if e and e not in seen:
            seen.add(e)
            out.append(f"> {e}")
    return out or ["> (no quote given)"]


def item_table(i: dict) -> list[str]:
    return ["| | |", "|---|---|", f"| what | {i['metric']} ({i['metric_text']}) |",
            f"| period | {i['period_text']} |", f"| forecast | {forecast(i)} |",
            f"| adjusted or GAAP | {BASIS_WORDS[i['basis']]} |",
            f"| change vs earlier guidance | {REVISION_WORDS[i['revision']]} |"]


INTRO = """# Guidance probe: questions

Two readings of each release, made independently, were compared after the scope rules
below. Where they agree, nothing is asked. Below is every place they differ, plus a
few releases where they agree, as a spot check. Each question quotes the release; open
the link only when the quote isn't enough.

**Answer on the `**Answer:**` line**, with one word where you can:

- **A or B**: which reading is right (which one is A is random per question); where
  they differ on two rows and each is right on one, a letter per row, e.g. `A B`;
- **yes or no**: whether the item is guidance under the rules and right as written;
- **ok**, or **none found**, on a spot check that is right;
- anything else: say what's right in your own words, and I'll turn it into labels.

**Guidance, under the agreed rules:** a number (range, point, at least, up to) for the
company's own results, for the next quarter or the current or next fiscal year, that
forecasts an outcome. Not guidance: synergy targets, multi-year targets, buybacks,
dividends and other capital-return plans, non-financial goals, and outlooks in words
only (the last three kinds were already removed by code).

**The rows:** *forecast* is the number(s) and the unit. *Adjusted or GAAP*: adjusted
when the release calls it adjusted, non-GAAP, or "excluding" some items; GAAP when it
says GAAP or reported; otherwise not said. *Change vs earlier guidance*: raised, kept
the same, or lowered only when the release itself says so ("raises", "reaffirms",
"maintains", "lowers", "continues to expect"); new when it says the guidance is given
for the first time; otherwise not said, even if you can tell it changed.
"""


def render(qs: list[dict], links: dict[str, str]) -> str:
    lines = [INTRO]
    for q in qs:
        link = links.get(q["accession"], "")
        tag = f"{q['slot']:02d} {q['ticker']} ({q['year']})"
        if q["kind"] == "fields":
            a, b = q["a"], q["b"]
            lines += [f"### {q['id']} · {tag} · {a['metric']} for \"{a['period_text']}\"", f"[release]({link})",
                      "", *quotes([a, b]), "", "The readings differ on:", "", "| | A | B |", "|---|---|---|"]
            if sorted(a["period_text"].lower().split()) != sorted(b["period_text"].lower().split()):
                lines.append(f"| period | {a['period_text']} | {b['period_text']} |")
            fns = {name: fn for name, fn in ROWS.values()}
            for name in rows(q):
                lines.append(f"| {name} | {fns[name](a)} | {fns[name](b)} |")
            ask = "Which is right: A or B?"
            if len(rows(q)) > 1:
                ask += " If each is right on a different row, give one letter per row, top to bottom (e.g. `A B`)."
            lines += ["", ask, ""]
        elif q["kind"] == "only":
            i = q["item"]
            lines += [f"### {q['id']} · {tag} · only one reading found this", f"[release]({link})", "",
                      *quotes([i]), "", *item_table(i), "",
                      "Is this guidance under the rules, and right as written: yes or no?", ""]
        elif q["kind"] == "other":
            lines += [f"### {q['id']} · {tag} · no revenue, EPS or margin guidance; other items", f"[release]({link})",
                      "", "Neither reading found revenue, EPS or margin guidance here, but they found:", ""]
            for i in q["items"]:
                lines += [f"- **{i['metric_text']}**, {i['period_text']}: {forecast(i)}", f"  > {i['evidence'].strip()}"]
            lines += ["", "Is any of these guidance under the rules (a forecast of the company's own results, not a "
                          "synergy target or capital-return plan): yes or no?", ""]
        else:
            lines += [f"### {q['id']} · {tag} · spot check, the readings agree", f"[release]({link})", ""]
            if q["items"]:
                for i in q["items"]:
                    lines += [*quotes([i]), "", *item_table(i), ""]
                lines += ["Is this right (and nothing missing on revenue, EPS or margin)? ok, or what's wrong.", ""]
            else:
                lines += ["Both readings found no guidance at all. Open the release and search for \"outlook\", "
                          "\"expect\", \"guidance\". none found, or what you found.", ""]
        lines += ["**Answer:** ", ""]
    return "\n".join(lines)


def parse_answers(md: str) -> dict[str, str]:
    """qid -> the answer text (everything after `**Answer:**` up to the next question)."""
    out = {}
    for block in re.split(r"^### ", md, flags=re.MULTILINE)[1:]:
        qid = block.split(" ", 1)[0]
        m = re.search(r"\*\*Answer:\*\*(.*)", block, flags=re.DOTALL)
        out[qid] = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return out


def normal(answer: str) -> str:
    return re.sub(r"[.!]+$", "", answer.strip().lower())


def other_side(side: str) -> str:
    return "model" if side == "draft" else "draft"


def build_gold(pairs: dict[str, tuple[ReleaseLabel, ReleaseLabel]], qs: list[dict], answers: dict[str, str],
               overrides: dict[str, dict]) -> tuple[dict[str, ReleaseLabel], dict[str, bool], dict]:
    """(headline gold labels, presence of any in-scope guidance, a summary)."""
    problems = []
    for q in qs:
        a = normal(answers.get(q["id"], ""))
        if q["id"] in overrides:
            continue
        if not a:
            problems.append(f"{q['id']}: no answer")
        elif (picks(q, a) is None) if q["kind"] == "fields" else (a not in ACCEPT[q["kind"]]):
            problems.append(f"{q['id']}: needs an override, answer was {answers[q['id']]!r}")
    if problems:
        raise ValueError("cannot build gold:\n" + "\n".join(problems))

    by_acc: dict[str, list[dict]] = {}
    for q in qs:
        by_acc.setdefault(q["accession"], []).append(q)
    gold, presence = {}, {}
    wins = {"draft": 0, "model": 0, "split": 0, "neither": 0}
    check = {"asked": 0, "right": 0}
    for acc, (draft, model) in pairs.items():
        d = [i for i in draft.items if i.metric in score.HEADLINE]
        m = [i for i in model.items if i.metric in score.HEADLINE]
        asked = by_acc.get(acc, [])
        items = [d[i] for i, j in score.match_items(d, m)
                 if not differing(d[i], m[j])]  # agreed pairs: the drafts' wording
        other = None
        for q in asked:
            a, ov = normal(answers.get(q["id"], "")), overrides.get(q["id"])
            if q["kind"] == "fields":
                if ov is not None:
                    items += [GuidanceItem.model_validate(i) for i in ov["items"]]
                    wins["neither"] += 1
                else:
                    letters = picks(q, a)
                    items.append(GuidanceItem.model_validate(combined(q, letters)))
                    if len(set(letters)) > 1:
                        wins["split"] += 1
                    else:
                        wins[q["a_from"] if letters[0] == "a" else other_side(q["a_from"])] += 1
            elif q["kind"] == "only":
                if ov is not None:
                    items += [GuidanceItem.model_validate(i) for i in ov["items"]]
                    wins["neither"] += 1
                else:
                    if a == "yes":
                        items.append(GuidanceItem.model_validate(q["item"]))
                    wins[q["from"] if a == "yes" else other_side(q["from"])] += 1
            elif q["kind"] == "other":
                other = ov["present"] if ov is not None else a == "yes"
            else:
                check["asked"] += 1
                if ov is not None:
                    items = [GuidanceItem.model_validate(i) for i in ov.get("items", [])]
                    other = ov.get("present", other)
                else:
                    check["right"] += 1
        gold[acc] = ReleaseLabel(guidance_present=bool(items), items=items)
        presence[acc] = bool(items) or bool(other)
    meta = {"questions": len(qs), "by_kind": pd.Series([q["kind"] for q in qs]).value_counts().to_dict(),
            "disagreements_won": wins, "spot_check": check, "overrides": sorted(overrides)}
    return gold, presence, meta


def load_inputs() -> tuple[pd.DataFrame, dict[str, tuple[ReleaseLabel, ReleaseLabel]]]:
    sample = pd.read_csv(SAMPLE_PATH, dtype={"accession": str})
    drafts = json.loads(DRAFTS_PATH.read_text())
    return sample, readings(drafts, load_extractions(EXTRACTIONS_DIR), sample)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.llm.guidance.adjudicate")
    parser.add_argument("step", choices=["questions", "gold"])
    args = parser.parse_args(argv)
    sample, pairs = load_inputs()
    if args.step == "questions":
        if QUESTIONS_MD.exists() and any(parse_answers(QUESTIONS_MD.read_text()).values()):
            raise SystemExit(f"{QUESTIONS_MD} already has answers; not overwriting it")
        qs = questions(pairs, sample)
        QUESTIONS_JSON.write_text(json.dumps(qs, indent=1) + "\n")
        QUESTIONS_MD.write_text(render(qs, release_links(sample)) + "\n")
        kinds = pd.Series([q["kind"] for q in qs]).value_counts().to_dict()
        print(f"wrote {len(qs)} questions ({kinds}) over {len({q['accession'] for q in qs})} releases")
        return
    qs = json.loads(QUESTIONS_JSON.read_text())
    overrides = json.loads(OVERRIDES_PATH.read_text()) if OVERRIDES_PATH.exists() else {}
    gold, presence, meta = build_gold(pairs, qs, parse_answers(QUESTIONS_MD.read_text()), overrides)
    score.GOLD_PATH.write_text(json.dumps({a: g.model_dump() for a, g in gold.items()}, indent=1) + "\n")
    PRESENCE_PATH.write_text(json.dumps(presence, indent=1) + "\n")
    META_PATH.write_text(json.dumps(meta, indent=1, default=int) + "\n")
    print(json.dumps(meta, indent=1, default=int))


if __name__ == "__main__":
    main()
