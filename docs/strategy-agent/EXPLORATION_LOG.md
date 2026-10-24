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

Re-run after the third review round (per-event delta vs per-event cost replaces the
always-in-position annualization; the window exclusion became symmetric, so same-side
clustered events no longer attenuate each other); supersedes the lines above.

- 2026-10-16 [look] First touch of a moving average after being away (long): h5 ΔC2 -0.02% [-0.10%,+0.05%] effN 2080d — looks dead vs ±0.10%/event; session data/llm/look_sessions/20261016T115622_327030Z
- 2026-10-16 [look] First touch of a moving average after being away (short): h5 ΔC2 +0.00% [-0.07%,+0.09%] effN 2056d — looks dead vs ±0.10%/event; session data/llm/look_sessions/20261016T115622_327030Z
- 2026-10-16 [look] First touch (both sides), 2019–2020 sub-window only — a CLI plumbing check, not a fresh question: long h5 ΔC2 +0.02% [-0.15%,+0.19%] effN 369d, short +0.14% [-0.05%,+0.36%] effN 392d, both inconclusive (expected at a sixth of the data); session data/llm/look_sessions/20261016T122350_937461Z

## 2026-10-24

- 2026-10-24 [look] Breakout of a long multi-touch base, then a holding retest (long; first live idea, detector `base_breakout.retest`; grounding plateaued, last round 2 of 6 matches accepted, so this tests an approximation of the idea): h10 ΔC2 -0.38% [-0.71%,-0.06%] effN 332d — inconclusive; h21 ΔC2 -0.55% [-0.89%,-0.21%] effN 329d — looks inverted vs ±0.10%/event; h63 ΔC2 -0.14% (no CI: 321 dates < 3 blocks of 126) — inconclusive; session data/llm/look_sessions/20261024T170926_697437Z

Re-run after review: the detector had read the panel's one-bar-lagged `atr_14` against same-bar prices (every ATR threshold used the previous bar's ATR); fixed by rolling the stored ATR one Wilder step onto its own bar. Supersedes the line above. Depth floor 5% in both runs (the spec's 7% from grounding, loosened after a second accepted shallow near-miss).

- 2026-10-24 [look] Breakout of a long multi-touch base, then a holding retest (long; same spec and caveat as above): h10 ΔC2 -0.38% [-0.71%,-0.09%] effN 331d — inconclusive; h21 ΔC2 -0.53% [-0.85%,-0.24%] effN 328d — looks inverted vs ±0.10%/event; h63 ΔC2 -0.23% (no CI: 320 dates < 3 blocks of 126) — inconclusive; session data/llm/look_sessions/20261024T172835_500120Z
