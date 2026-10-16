# Judged verdicts for the research-docs evaluation

Kept here, not under `docs/`, because everything under `docs/` is indexed: the answer key
would be retrieved too.

- `answers.json`: verdicts on step 6's generated answers (`answer_eval.py`). `support` is
  keyed by a cited sentence plus the text of the sources it cites; `answers` by question
  id plus answer text. A rerun that reproduces a sentence or an answer reuses its verdict.
  Every verdict was proposed by a fresh agent and checked by hand against the sources;
  a `judge_note` keeps the agent's wording where the hand-check rewrote a note, and a
  `miss` with its `miss_note` records where the hand-check overrode the mechanical
  retrieval/generation split.
- `runs/`: the answer runs those verdicts were made on (question, answer, the 5 sources
  as shown, which sources match a gold). `dev_2026-10-16.json` is the baseline.
- `pooling/`: the retrieval pooling record (`evaluate.py`), moved from the git-ignored
  `data/llm/`. `judged_top5_pre_rebuild_2026-10-14.json` holds every method's top 5 texts
  per question saved before the 2026-10-14 index rebuild (these count as judged afterwards);
  `pool_rebuilt_2026-10-14.json` the unjudged chunks the rebuilt index surfaced;
  `judge_packet_*.txt` those chunks as shown to the judges. Only the "yes" verdicts were
  kept, as golds in `eval_questions.json`; a chunk in these files that isn't a gold was
  judged "no".
