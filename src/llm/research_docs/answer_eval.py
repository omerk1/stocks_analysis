"""Evaluation of step 6's answers (`answer.py`): run every dev question through `answer`,
judge the replies, and score them against the judged-answers ledger.

`check` in `answer.py` is mechanical (valid source numbers, every sentence cited). Whether
an answer is *right* takes a judge, and judging is the expensive part, so verdicts are kept
in a committed ledger (`judged/answers.json`) keyed by content, not by run: when the prompt
changes, only what changed needs judging again.

- **Support**, one verdict per cited sentence: is the sentence backed by the sources it
  cites? Keyed by the sentence and the text of those sources, so the same sentence citing
  the same chunk keeps its verdict across runs. Judged blind to the golds: the judge sees
  the question, the sources and the answer, nothing that says which source is "right".
- **Correctness**, one verdict per answer: `correct`, `partial` or `wrong` against the
  question's golds (the judge sees the gold chunks' text), with the parts covered for a
  multi-part question. On an unanswerable question `correct` means it said "not in the
  docs" without stretching a source. Keyed by question id and answer text.

A wrong answer is then split mechanically by whether retrieval put the answer in front of
the model (`evaluate.part_ranks` on the 5 sources shown): a **retrieval miss** when a gold
(for a multi-part question, every part's) isn't in the top 5, a **generation miss** when it
is and the answer is still wrong, or when the question is unanswerable and the model
answered anyway. A "not in the docs" reply to an answerable question whose gold wasn't
retrieved counts as a retrieval miss: the model did what it was told. The hand-check can
override the split with a `miss` field and a note (stored with the sources it was made
for, `sources_key`, and ignored once they change): a question's alternative golds count as
one hit, so the answer can be "fully" retrieved by that rule and still be missing what the
judge wanted from a gold that wasn't shown.

Golds are only as complete as the pooling that found them (`evaluate.py`); an answer judged
correct from a source that isn't a gold is reported, as a candidate gold.

    python -m src.llm.research_docs.answer_eval run            # answer the dev questions (Gemini)
    python -m src.llm.research_docs.answer_eval packets RUN    # what still needs judging, as JSON
    python -m src.llm.research_docs.answer_eval score RUN      # scores from the ledger

The baseline (2026-10-16, the step-6 prompt; ~95k tokens for 43 questions) is
`judged/runs/dev_2026-10-16.json`; a prompt change is scored against it. The step-6c
prompt's run, on the same index, is `judged/runs/dev_2026-10-16_prompt.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from llama_index.core.schema import BaseNode, NodeWithScore, TextNode

from src.llm.gemini import DEFAULT_MODEL, GeminiClient
from src.llm.paths import llm_data_dir
from src.llm.research_docs.answer import (BUDGET, SYSTEM, Answer, answer, build_prompt, cited, sentences,
                                          source_text)
from src.llm.research_docs.evaluate import (answerable, load_questions, matches, part_ranks, parts, question_split,
                                            unmatched_golds)
from src.llm.research_docs.retrieve import cite

LEDGER = Path(__file__).with_name("judged") / "answers.json"
SUPPORT = ("supported", "partial", "unsupported")
CORRECTNESS = ("correct", "partial", "wrong")
MISSES = ("retrieval", "generation")
GOLD_CHUNKS = 6  # per gold, shown to the correctness judge


def _sha(*texts: str) -> str:
    return hashlib.sha256("\n\x00\n".join(" ".join(t.split()) for t in texts).encode()).hexdigest()[:16]


PROBE = NodeWithScore(node=TextNode(id_="probe", text="Probe text.", metadata={"path": "p.md", "section": "S"}),
                      score=1.0)


def prompt_id(model: str = DEFAULT_MODEL) -> str:
    """Which instructions wrote an answer: the system prompt, a probe message as the model
    would get it (`build_prompt` on a fixed question and source, so the template and the
    basic source rendering count, and a docstring edit doesn't), the reply schema and the
    model, hashed exactly. Unlike `_sha`, whitespace counts here: the model sees it. Not
    covered: generation settings (temperature, `BUDGET`) and how a real chunk's extra
    metadata renders; the probe has only a path and a section."""
    parts = (SYSTEM, build_prompt("Probe question?", [PROBE]), json.dumps(Answer.model_json_schema(), sort_keys=True),
             model)
    return hashlib.sha256("\n\x00\n".join(parts).encode()).hexdigest()[:16]


def retrieval(q: dict, nodes: list[BaseNode]) -> str:
    """Whether the shown sources hold the answer: `full`, `partial` (some parts of a
    multi-part question), `none`, or `n/a` for an unanswerable question."""
    if not answerable(q):
        return "n/a"
    full, first = part_ranks(nodes, q)
    return "full" if full else "partial" if first else "none"


def record(q: dict, a, prompt: str | None = None) -> dict:
    """One answered question as stored in a run file. `a` is an `answer.Answered`;
    `prompt` is `prompt_id` for the run's model (the default model's when not given)."""
    nodes = [h.node for h in a.sources]
    return {
        "id": q["id"], "type": q["type"], "question": q["question"], "answerable": answerable(q),
        "prompt": prompt or prompt_id(),
        "n_parts": len(parts(q)), "retrieval": retrieval(q, nodes),
        "in_docs": a.answer.in_docs, "answer": a.answer.answer, "problems": a.problems,
        "tokens": a.usage.total_tokens,
        "sources": [{"n": n, "cite": cite(node), "text": source_text(node),
                     "gold_parts": [i for i, p in enumerate(parts(q), 1) if any(matches(node, g) for g in p)]}
                    for n, node in enumerate(nodes, 1)],
    }


def run(questions: list[dict], find: Callable[[str, int], list[NodeWithScore]], client: GeminiClient,
        out: Path) -> list[dict]:
    """Answer each question, writing `out` after every one. Questions already in `out` are
    skipped, so an interrupted run resumes instead of paying again; a file written by
    different instructions is refused, so one run can't mix two prompts (and a finished
    one is returned with a warning, since nothing was re-run)."""
    done = json.loads(out.read_text()) if out.exists() else []
    have = {r["id"] for r in done}
    pid = prompt_id(getattr(client, "model", DEFAULT_MODEL))
    if other := sorted({r.get("prompt") or "unrecorded" for r in done} - {pid}):
        msg = f"{out} holds answers from another prompt ({', '.join(other)})"
        if any(q["id"] not in have for q in questions):
            raise ValueError(msg + "; use a new --out")
        print(f"warning: {msg}; nothing left to answer, so nothing was re-run", file=sys.stderr)
    for q in questions:
        if q["id"] in have:
            continue
        done.append(record(q, answer(q["question"], find, client), pid))
        tmp = out.with_suffix(".tmp")  # a crash mid-write must not lose the answers paid for
        tmp.write_text(json.dumps(done, indent=1, ensure_ascii=False))
        os.replace(tmp, out)
        print(f"{len(done):>3}/{len(questions)} {q['id']} ({done[-1]['tokens']} tokens)", flush=True)
    return done


def claims(r: dict) -> list[dict]:
    """The answer's cited sentences, each with the sources it cites and its ledger key.
    A citation to a source that doesn't exist is `check`'s problem, not the judge's."""
    texts = {s["n"]: s["text"] for s in r["sources"]}
    out = []
    for s in sentences(r["answer"]):
        ns = [n for n in cited(s) if n in texts]
        if ns:
            out.append({"key": _sha(s, *(texts[n] for n in ns)), "sentence": s, "cites": ns})
    return out


def answer_key(r: dict) -> str:
    return _sha(r["id"], r["answer"])


def sources_key(r: dict) -> str:
    """The sources an answer was shown, in order. A hand-set `miss` is about them, so it
    is stored with this key and applies only while the sources are the same."""
    return _sha(*(s["text"] for s in r["sources"]))


def load_ledger(path: Path = LEDGER) -> dict:
    ledger = json.loads(path.read_text()) if path.exists() else {}
    ledger.setdefault("support", {})
    ledger.setdefault("answers", {})
    bad = [k for k, v in ledger["support"].items() if v.get("verdict") not in SUPPORT]
    bad += [k for k, v in ledger["answers"].items()
            if v.get("verdict") not in CORRECTNESS or v.get("miss", "retrieval") not in MISSES
            or ("miss" in v and (v["verdict"] == "correct" or "miss_sources" not in v))]
    if bad:
        raise ValueError(f"ledger verdicts outside {SUPPORT} / {CORRECTNESS}, a miss outside {MISSES}, "
                         f"or a miss on a correct answer or without `miss_sources`: {', '.join(bad)}")
    return ledger


def gold_texts(q: dict, nodes: list[BaseNode], per_gold: int = GOLD_CHUNKS) -> list[list[dict]]:
    """Per part, the chunks matching each of its golds: at most `per_gold` per gold,
    since a metadata gold (an experiment id) can match hundreds of CSV rows. A chunk two
    golds match is shown once, unless the first gold cut it (then its "+N more" line
    counts it too); what was cut is said, not hidden."""
    out = []
    for p in parts(q):
        shown, seen = [], set()
        for g in p:
            hits = [n for n in nodes if matches(n, g) and n.node_id not in seen]
            seen.update(n.node_id for n in hits[:per_gold])  # a chunk cut here can still show under another gold
            shown += [{"cite": cite(n), "text": source_text(n)} for n in hits[:per_gold]]
            if len(hits) > per_gold:
                shown.append({"cite": f"{g}", "text": f"(+{len(hits) - per_gold} more chunks matching this gold)"})
        out.append(shown)
    return out


def packets(rows: list[dict], ledger: dict, questions: dict[str, dict], nodes: list[BaseNode]) -> dict:
    """What the ledger has no verdict for yet. `support`: question, sources and answer
    only, no golds. `correctness`: the answer with the gold chunks' text per part, and the
    sources it was written from. `nodes` are the docs chunked now, not the index: the
    judge grades against the golds as the docs say them, even when the index is stale."""
    if unknown := [r["id"] for r in rows if r["id"] not in questions]:
        raise ValueError(f"run rows for questions not in the dev split (renamed or moved?): {', '.join(unknown)}")
    support, correctness = [], []
    for r in rows:
        todo = [c for c in claims(r) if c["key"] not in ledger["support"]]
        if todo:
            support.append({"id": r["id"], "question": r["question"], "answer": r["answer"],
                            "sources": [{"n": s["n"], "text": s["text"]} for s in r["sources"]],
                            "claims": [{"key": c["key"], "sentence": c["sentence"], "cites": c["cites"]}
                                       for c in todo]})
        if answer_key(r) not in ledger["answers"]:
            correctness.append({"id": r["id"], "key": answer_key(r), "question": r["question"],
                                "answerable": r["answerable"], "in_docs": r["in_docs"], "answer": r["answer"],
                                "gold_parts": gold_texts(questions[r["id"]], nodes),
                                # so an answer right from a chunk the golds missed can be seen as right
                                "sources": [{"n": s["n"], "cite": s["cite"], "text": s["text"]}
                                            for s in r["sources"]]})
    return {"support": support, "correctness": correctness}


def miss(r: dict, verdict: str, judged: str | None = None) -> str | None:
    """`retrieval`, `generation` or None (not a miss), as in the module docstring.
    `judged` is a hand-checked override from the ledger: a question's alternative golds
    count as one hit, so "full" retrieval can still leave out the part of the answer the
    judge found missing, when it lives in a gold that wasn't shown."""
    if verdict == "correct":
        return None
    if judged:
        return judged
    if not r["answerable"]:
        return "generation"
    return "generation" if r["retrieval"] == "full" else "retrieval"


def score(rows: list[dict], ledger: dict) -> str:
    """The per-question table and the totals. Questions or sentences without a verdict
    are counted as unjudged, never as passes."""
    prompts = sorted({r.get("prompt") or "unrecorded" for r in rows})
    lines = [f"prompt: {', '.join(prompts)}" + (" (MIXED: rows from different prompts)" if len(prompts) > 1 else ""),
             f"{'question':<24} {'type':<8} {'retr':<7} {'docs':<5} {'verdict':<8} {'support':<9} miss"]
    verdicts, misses, sup_all, unjudged, clean, citing = {}, {}, [], [], 0, 0
    for r in rows:
        entry = ledger["answers"].get(answer_key(r), {})
        v = entry.get("verdict")
        if v is None:
            unjudged.append(r["id"])
        verdicts[r["id"]] = v
        judged_miss = entry.get("miss") if entry.get("miss_sources") == sources_key(r) else None
        misses[r["id"]] = miss(r, v, judged_miss) if v else None
        sup = [ledger["support"].get(c["key"], {}).get("verdict") for c in claims(r)]
        sup_all += sup
        ok = sum(s == "supported" for s in sup)
        # over answers that cite something, all of it judged: an answer citing nothing has
        # nothing to support (an uncited in-docs answer is `check`'s problem)
        if sup and all(sup):
            citing += 1
            clean += ok == len(sup)
        lines.append(f"{r['id']:<24} {r['type']:<8} {r['retrieval']:<7} {str(r['in_docs'])[0]:<5} {v or '?':<8} "
                     f"{f'{ok}/{len(sup)}':<9} {(misses[r['id']] or '') if v else '?'}")
    judged = [r for r in rows if verdicts[r["id"]]]
    groups = {"answerable": [r for r in judged if r["answerable"] and r["n_parts"] == 1],
              "multi-part": [r for r in judged if r["n_parts"] > 1],
              "unanswerable": [r for r in judged if not r["answerable"]]}
    lines.append("")
    for name, group in groups.items():
        n = {v: sum(verdicts[r["id"]] == v for r in group) for v in CORRECTNESS}
        lines.append(f"{name:<13} {len(group):>3} questions: " + ", ".join(f"{n[v]} {v}" for v in CORRECTNESS))
    kinds = [misses[r["id"]] for r in judged]
    lines.append(f"misses (partial or wrong): {kinds.count('retrieval')} retrieval, "
                 f"{kinds.count('generation')} generation")
    known = [s for s in sup_all if s]
    lines.append(f"cited sentences: {len(sup_all)}, " + ", ".join(f"{known.count(v)} {v}" for v in SUPPORT)
                 + (f", {len(sup_all) - len(known)} unjudged" if len(known) < len(sup_all) else ""))
    lines.append(f"answers with every cited sentence supported: {clean} of {citing} that cite a source "
                 "(and have every citation judged)")
    lines.append(f"mechanical citation problems (check): {sum(bool(r['problems']) for r in rows)} answers")
    if unjudged:
        lines.append(f"UNJUDGED answers: {', '.join(unjudged)}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.llm.research_docs.answer_eval")
    sub = ap.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="answer every dev question (spends Gemini tokens)")
    run_cmd.add_argument("--out", type=Path, default=None,
                         help="run file (default data/llm/answer_runs/dev_<UTC time>.json)")
    run_cmd.add_argument("--allow-stale", action="store_true", help="run even if some golds aren't in the index")
    for name in ("packets", "score"):
        sub.add_parser(name).add_argument("run_file", type=Path)
    args = ap.parse_args()
    questions = [q for q in load_questions() if question_split(q) == "dev"]  # the test split is spent
    if args.command == "score":
        print(score(json.loads(args.run_file.read_text()), load_ledger()))
        return
    from src.llm.research_docs.chunk import chunk_documents
    from src.llm.research_docs.load import load_documents
    current = chunk_documents(load_documents())
    if args.command == "packets":
        rows = json.loads(args.run_file.read_text())
        print(json.dumps(packets(rows, load_ledger(), {q["id"]: q for q in questions}, current),
                         indent=1, ensure_ascii=False))
        return
    from src.llm.research_docs.index import embed_model, load_index
    index = load_index(embed_model())
    nodes = list(index.docstore.docs.values())
    # As in evaluate.py: a gold the index can't match would score as a retrieval miss that
    # is really a stale index, and this run costs tokens, so refuse unless told otherwise.
    unmatched = unmatched_golds(questions, nodes, current)
    if unmatched and not args.allow_stale:
        print("golds that match no indexed chunk:", *unmatched, sep="\n  ", file=sys.stderr)
        raise SystemExit("rebuild the index, or pass --allow-stale and say so in the results")
    from src.llm.research_docs.keyword import KeywordIndex
    from src.llm.research_docs.rerank import cross_encoder, rerank_search
    keywords, scorer = KeywordIndex(nodes), cross_encoder()
    out = args.out or llm_data_dir() / "answer_runs" / f"dev_{datetime.now(timezone.utc):%Y-%m-%dT%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"run file: {out}")
    run(questions, lambda q, k: rerank_search(index, keywords, scorer, q, k), GeminiClient(budget=BUDGET), out)


if __name__ == "__main__":
    main()
