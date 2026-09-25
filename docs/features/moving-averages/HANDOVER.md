# Handover — MA study complete, archival

**Written 2026-09-22 as a live batch-coordination doc, closed out 2026-09-25 once M15
(Synthesis) — the last module on DESIGN's own list — merged (PR #107).** This file
originally existed so a *different* Claude Code conversation (no memory of this one)
could pick up in-progress post-termination batch work cold. There is no more
in-progress work to pick up: every module in DESIGN's list (M1–M18, all M6.x
sub-modules, §7.5) has run, been tiered, and been folded into the current whole-grid
FDR pass. `STATUS.md` is now the sole authoritative "what do we actually know"
record — read that first, not this file, for any question about study results.

**What's kept here, and why:** the two sections below are genuine operational
knowledge that isn't written down anywhere else in this study's file set. Everything
else this file used to carry — the batch-by-batch blow-by-blow ("Batch 2 is done,
merged..." etc.), the per-batch dependency sequencing, a "where to start next"
pointer — was live coordination state for work that's now finished, fully superseded
by `STATUS.md`'s own "Modules run" table and Timeline, and deleted here rather than
kept as duplicate, staleness-prone bookkeeping. If DESIGN's porous-scope rule is ever
invoked again for a genuinely new module, that's the moment to write a fresh version
of the sections that were removed — not to resurrect these from git history, since
they describe batches that no longer need coordinating.

## Infrastructure inventory (verify against the code before trusting — this is a snapshot as of 2026-09-25)

- Cached panel (`data/features/moving_averages/ma_panel/`, 405 S&P 500 tickers, U1
  universe, 2010-01-04→2021-12-31, holdout-safe) has: SMA/EMA at {20,50,150,200},
  `dist_pct`/`dist_atr`/`dist_z` + `above` state at those lookbacks, `slope_log_k` at
  k∈{5,21,63}, `atr_14`, `volume`, `mom_12_1`/`mom_1_0`/`realized_vol_63`,
  `run_length_bucket_sma_*`, `dist_from_52w_high`/`dist_from_52w_low`, `sector`
  (current-state only, not PIT), `stacked_sma`/`stacked_ema`. Full list: run
  `read_panel(...).columns` or read `features/panel.py`'s own docstring.
- **Not built**: lookbacks other than {20,50,150,200} in the *shared* panel (M6.6
  added local-only 10/100 SMA slope for its own ribbon; M3 added local-only EMA
  8/10/21 for its own crossover pairs; M9's `efficiency_ratio`/`average_directional_index`
  operate off existing panel columns without adding new lookbacks either), `ribbon_width`
  as a shared panel column (M7 built its own local one), point-in-time
  `mktcap_decile`/`universe_flags` (M12's `dollar_volume`/SMA50 finding and M6.4's
  GBM-null calibration are both capped at Tier 3 partly for lack of this-or-adjacent
  infra — live, named reasons to eventually build it), MFE/MAE proper
  (`labels/path_metrics.py` only has `forward_max_drawdown` so far), a **real 2022+
  holdout check** (still locked per CLAUDE.md invariant #1 — every Tier-3 cell in this
  study is capped partly on this), a **second/third universe tier** (U2/U3, DESIGN
  §3.2), an **earnings-date table** (M13, M6.3 both hit this gap and substituted
  proxies).
- **Now built**: crossover/state-flip event detection (`features/crossover.py`, M3);
  WMA/HMA/DEMA/KAMA/VWMA (`features/kernels.py`, M8 — VWMA also has a separate,
  simpler module-local stub in `features/liquidity.py` from M12, not reconciled with
  `kernels.py`'s own version, low priority); White's Reality Check
  (`stats/multiple_testing.py::white_reality_check`, M8); a `Timeframe` parameter on
  `build_panel` (`features/panel.py`, M10 — daily default unchanged,
  `Timeframe.WEEKLY` resamples live from `bars_1d`; only MA/distance/slope/ATR/
  run-length features are timeframe-correct at non-daily granularity,
  day-count-calibrated context features like `mom_12_1` are not recalibrated, a named
  open gap); `features/regime.py` (`efficiency_ratio`, `average_directional_index`,
  M9 — reconciled 2026-09-25 with M6.4's own independently-built duplicate, PR #102,
  one shared implementation now); Kaplan-Meier survival + GBM-null simulation
  (`stats/survival.py`, M6.4); `features/oscillators.py` (MACD/RSI/stochastic-%K
  wrappers, M17); `stats/kernel_space.py` (linear-filter weight-vector diagnostics,
  M16 — a different concept from M8's `features/kernels.py`, named distinctly to
  avoid confusion); `modules/pattern_context.py` and a `pattern_matches` SQLite table
  (M14, joins the shared panel against `src/signals/patterns/`'s own chart-pattern
  detectors); `modules/synthesis.py` (M15, the overlap/enrichment check between M6.3's
  and M14's cells).
- **DB tables** (`data/raw/market_data.sqlite`): `bars_1d/1h/1mo/1w`, `fetch_jobs`,
  `index_membership`, `macro_series` (VIX/FRED, no earnings), `shares_outstanding`,
  `splits`, `ticker_metadata`, `ticker_sector`, `tickers`. **No earnings-date table
  exists anywhere.**
- **Existing pattern detectors** (a different repo subsystem, integrated by M14):
  `src/signals/patterns/detectors/{cup_and_handle,double_top_bottom,flags_pennants,
  head_shoulders,reversal_123,triangles,vcp}.py`.
- **`market_common.indicators`** already has RSI/MACD/ATR/OBV wrappers (this repo's
  own reuse pointer in `CLAUDE.md`).

## Process notes, if this study is ever extended

These are real, hard-won operational lessons from running four batches of parallel
forked agents across this study's post-termination phase. Still true regardless of
whether new modules ever get added:

- **Use `Agent` with `subagent_type: "fork"` and `isolation: "worktree"`, one per
  module, launched in a single message for true parallelism.** Forking inherits the
  coordinating conversation's context (CLAUDE.md's invariants, the pre-registration
  template, the C1/C2/block-bootstrap machinery) without re-explaining it per prompt.
  From a fresh conversation with no shared context, use a non-fork agent and paste in
  `CLAUDE.md`/`DESIGN.md`/recent `PREREGISTRATION.md` entries directly.
- **Rate limits and premature turn-endings are the real bottleneck, not the work
  itself.** Forks routinely get interrupted mid-run, or end their own turn right
  after launching a slow background script instead of waiting for it or checking its
  output — sometimes repeatedly, restarting the same script from scratch each time
  rather than resuming. Don't trust a "done" or "waiting" self-report at face value:
  inspect the worktree directly (`git log --oneline`, `git status --short`,
  `ps aux | grep python3`) before deciding whether to nudge, and when nudging, be
  explicit ("don't restart the script, check `<output file>` from the run already in
  progress" or "run with an explicit long `timeout` instead of letting it get
  backgrounded"). One fork went genuinely idle for 9 real hours before quietly
  resuming on its own after a nudge — don't assume "no progress in N hours" means
  dead; check before duplicating its work.
- **Worktrees don't get `data/raw/market_data.sqlite`** (gitignored, ~4GB) — only
  `data/features/moving_averages/ma_panel` reliably gets symlinked in. Any module
  needing raw DB access needs `ln -s <main-repo>/data/raw/market_data.sqlite
  data/raw/` inside the worktree (untracked, no extra disk use) — tell forks needing
  DB access to do this proactively, not discover it mid-run.
- **Division of labor**: each fork owns its own new module/feature/test files plus
  its own `PREREGISTRATION.md` section, `EXPERIMENTS.csv` rows, and (Tier 1-3)
  `FINDINGS.md`/`EXPLORATION_LOG.md` entries — never `STATUS.md`/`REPORT.md` or the
  whole-grid FDR pass. The coordinating session consolidates those shared,
  prose-heavy files once after a batch lands, instead of multiple agents fighting
  over the same paragraphs.
- **No module-number-prefixed file names or import aliases anywhere** — no
  `m15_synthesis.py`, no `import ... as m15`. Use descriptive names matching this
  repo's own dominant convention (`slope_magnitude.py`, `pattern_context.py`, `cs`,
  `smv`, `tb`, etc.). Caught and fixed repeatedly across this study whenever missed.
- **No AI attribution in this repo's commits or PR bodies** — no `Claude-Session:`
  line, no `Co-Authored-By`. Repeat this explicitly in every fork prompt.
- **Two-phase commit**: pre-register (commit) → build+run+log results (commit). Worth
  a quick `git log` spot-check before trusting a "done" report.
- **Verify before reporting a PR clean**: `gh pr view <n> --json files,additions,
  deletions,mergeStateStatus` (no unexpected `STATUS.md`/`REPORT.md` touch), grep the
  PR body for attribution lines, spot-check the CSV's column count is consistent, and
  check for any leftover untracked scratch files in the worktree before calling it done.
- **Doc-append merge conflicts between sibling PRs are expected and trivial** — both
  sides add a row/section at the same point; keep both, in whatever order reads
  sensibly (usually chronological by date).
- **The coordinating session never merges its own or a fork's PRs** — only the human
  user merges. The coordinating session opens PRs, resolves conflicts by pushing to
  the PR's own branch, and waits to be told a PR number has been merged before doing
  any cleanup (worktree/branch removal) or starting dependent follow-on work.
