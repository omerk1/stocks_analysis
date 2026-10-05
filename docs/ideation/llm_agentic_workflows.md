# LLM / agentic workflows — ideation

Status: brainstorm (2026-10-05). Nothing here is decided or built yet. The goal is short
cycles: each idea should ship in a few days and teach one technique (RAG, tool calling,
agents) on a problem this repo already has.

## Ground rule: LLMs stay outside the backtested path

An LLM has read about what happened after any historical date. A feature it produces on
2015 data quietly sees the future, the same kind of leak as breaking the holdout lock, and
no test can catch it. So the LLM work is **tooling around the research** (search,
explanations, live-only context), never a model input or a source of historical signals.

Code would live in a new `src/llm/` (or `src/agents/`), separate from `src/signals/` and
`src/models/`.

## Ideas, smallest first

### 1. Search over the project's own research docs (LlamaIndex) — ~1–2 days

- **Corpus:** `docs/features/moving-averages/` (`DESIGN.md`, `FINDINGS.md`,
  `EXPERIMENTS.csv`, `PREREGISTRATION.md`, `STATUS.md`), `docs/done.md`,
  `docs/decisions/`, `docs/modeling/`, `docs/backlog.md`.
- **Example questions:** "Has SMA200 slope been tested on 21-day horizons? What came of
  it?", "Why were baselines B1 and B5 dropped?"
- **Why it's useful:** CLAUDE.md requires checking `EXPERIMENTS.csv`/`FINDINGS.md` before
  re-running a hypothesis. Today that's a manual grep.
- **What it teaches:** chunking (markdown sections vs CSV rows), embeddings, retrieval
  quality, answers that cite their sources.
- **Evaluation:** a hand-written set of ~20 questions with known answers. The docs are
  familiar, so wrong answers are easy to spot.

### 2. Agent that answers questions from the DB (LangGraph or plain tool use) — ~2–3 days

- **Tools (read-only):** bars for a ticker/date range, `rs_rank`, active signals for a
  ticker on a date, breadth. The holdout lock is enforced inside the tools.
- **Example question:** "What did AAPL's setup look like on 2019-03-12, and which signals
  were active?"
- **What it teaches:** tool calling, the agent loop, guardrails. If the goal is LangChain
  experience, LangGraph is the place for it: its graph/state model fits a multi-step agent.
- **Becomes the backbone for idea 3.**

### 3. Plain-language reasons on alerts — ~1 day, after the model exists

- Take a scored setup and its feature values, and have the LLM write a 3-line reason for
  the notification. The facts come from idea 2's tools, so the model only writes prose.
- Mostly prompt work. Waits for harness step 4 and a real fitted model.

### 4. Search over SEC filings — bigger, later

- `data/raw/sec/submissions.zip` is already downloaded, but it holds only per-company
  filing indexes (form type, filing dates, accession numbers), not filing text. It tells us
  which filings exist and when; the 10-K/8-K text itself still has to be fetched from EDGAR
  (rate-limited), parsed out of HTML, and chunked. That fetch is most of the work.
- Useful for **live** alert context ("any 8-K in the last 5 days?"), not for backtests,
  because of the ground rule above.

## Suggested order

1 → 2 → 3, with 4 when there's appetite for a larger cycle. Idea 1 needs no new data and
has a simple evaluation; idea 2 makes idea 3 cheap once the model is ready.

## Framework notes

- **LlamaIndex** fits idea 1 well: document loaders, chunking, retrieval out of the box.
- **LangChain** adds a lot of layers that small projects may not need. **LangGraph** is the
  part worth learning, for idea 2.
- Plain API tool use is a valid baseline for idea 2 if a framework gets in the way.
