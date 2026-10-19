# Judged verdicts for the research-docs evaluation

Kept here, not under `docs/`, because everything under `docs/` is indexed: the answer key
would be retrieved too.

- `answers.json`: verdicts on step 6's generated answers (`answer_eval.py`). `support` is
  keyed by a cited sentence plus the text of the sources it cites; `answers` by question
  id plus answer text. A rerun that reproduces a sentence or an answer reuses its verdict.
  Every verdict was proposed by a fresh agent and checked by hand against the sources;
  a `judge_note` keeps the agent's wording where the hand-check rewrote a note, and a
  `miss` with its `miss_note` records where the hand-check overrode the mechanical
  retrieval/generation split; it is pinned to the sources it was made for
  (`miss_sources`) and ignored after they change.
- `runs/`: the answer runs those verdicts were made on (question, answer, the sources
  as shown, which sources match a gold). `dev_2026-10-16.json` is the baseline;
  `dev_2026-10-16_prompt.json` the step-6c prompt on the same index (`docs/done.md` #152).
  Both were written before rows carried a `prompt` id; theirs were added afterwards,
  computed from the code each run was made with (`answer.py` at #150, and at #152).
  After the 2026-10-17 index rebuild (step 7d): `dev_2026-10-18_rebuilt_top5.json`, the
  same prompt with 5 sources, and `dev_2026-10-19_rebuilt_top10.json` with 10 (rows carry
  `k`). A row with `error` got no usable reply and is counted wrong.
- `pooling/`: the retrieval pooling record (`evaluate.py`), moved from the git-ignored
  `data/llm/`. `judged_top5_pre_rebuild_2026-10-14.json` holds every method's top 5 texts
  per question saved before the 2026-10-14 index rebuild (these count as judged afterwards);
  `pool_rebuilt_2026-10-14.json` the unjudged chunks the rebuilt index surfaced, which
  were then judged. The `_2026-10-17` pair is the same for the next rebuild, on the dev
  split only and the re-ranker's top 10. Only the "yes" verdicts were
  kept, as golds in `eval_questions.json`; a chunk in these files that isn't a gold was
  judged "no".
