# Strategy agent — exploration log

Track A only, one line per exploratory look the agent runs
(`python -m src.llm.strategy_spec.look`), whether or not it went anywhere — the CLI
prints each line ready to paste under a `##` date header. **Nothing here is a finding.**
A look that earns a Track B test gets its `prereg_draft.md` completed, committed to the
relevant PREREGISTRATION file, and run by a human; this log never carries that result.

Kept separate from the MA study's own `docs/features/moving-averages/EXPLORATION_LOG.md`
on purpose: that log is the study's history of its modules; this one is the agent's
history of trader-stated ideas, whatever feature family they land on.

## 2026-10-15

- 2026-10-15 [look] First touch of a moving average after being away (long): h5 ΔC2 -0.03% [-0.10%,+0.03%] effN 2089d — inconclusive; session data/llm/look_sessions/20261015T071052_887038Z
- 2026-10-15 [look] First touch of a moving average after being away (short): h5 ΔC2 -0.01% [-0.08%,+0.07%] effN 2061d — inconclusive; session data/llm/look_sessions/20261015T071052_887038Z

## 2026-10-16

Re-run after the review's control-contamination fix (a split spec's control pool was
keeping the other side's near-event rows); supersedes the 2026-10-15 lines above.

- 2026-10-16 [look] First touch of a moving average after being away (long): h5 ΔC2 -0.00% [-0.07%,+0.06%] effN 2087d — inconclusive; session data/llm/look_sessions/20261016T113826_636798Z
- 2026-10-16 [look] First touch of a moving average after being away (short): h5 ΔC2 -0.04% [-0.11%,+0.05%] effN 2058d — inconclusive; session data/llm/look_sessions/20261016T113826_636798Z
