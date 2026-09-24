# Handover — post-termination parallel batches

**Written 2026-09-22, revised 2026-09-23 (Batch 1 done), revised 2026-09-24 (Batch 2
done).** This file exists so a *different* Claude Code conversation (no memory of this
one) can pick this initiative up cold. It's session/execution state and a forward
plan, not part of this study's original file set (`STATUS.md` covers results). Read
`CLAUDE.md` first (its invariants apply to every module below, no exceptions), then
this file, then `STATUS.md` for the study's actual tiered results.

## Where things stand

The MA study reached its own termination condition on 2026-09-17 (`STATUS.md`'s
"Study-level termination"). On 2026-09-21 the user asked to scope the rest of
DESIGN's module list beyond the minimal-core set, as porous-scope post-termination
work (DESIGN §1.5) — model-input-feature candidates, not a reopening.

**Batch 1 (M6.1, M6.3, M7, M13) is done, merged, and consolidated** (PRs #81–#84,
#86). Result: the study's first Tier-2 finding
(`slope_pctile_21_sma_50`/M6.3 — see `STATUS.md`/`FINDINGS.md`) and the first cells
ever to survive this study's whole-grid FDR pass (5 of 50 at q=0.10). Full detail is
in `STATUS.md`, not repeated here.

**Batch 2 (M3, M6.5, M6.6, M12) is done, merged, and consolidated** (PRs #88–#91,
#95 [M3's spread-velocity addendum], #96 [FDR consolidation]). Process note for
whoever reads this next: PRs #88/#89 (M6.5/M3) were briefly merged, then reverted
(#92) and re-restored (#93) mid-session over a branch-protection/review-process
discussion with the user — the *content* that landed is identical to the original
PRs, just via an extra revert/restore round-trip; nothing about the module results
themselves changed. Result: **the FDR survivor set changed materially at N=79** (up
from N=50) — `ribbon_agreement_extreme_drawdown` (M6.6) is now this study's smallest
p-value ever, `reclaim_durability_dollar_volume_sma50` (M12) newly clears FDR too,
and 3 of the old pass's 5 survivors (M7/M2/M1's cells) no longer clear FDR at the
larger N — but **the Tier-2 count is unchanged** (still exactly one,
`slope_pctile_21_sma_50`/M6.3, confirmed robust to the larger grid). Full detail in
`STATUS.md`'s "Whole-grid FDR pass" section (2026-09-24 update) and `REPORT.md`.

**Two process notes worth keeping for the next batch:**
- **No module-number-prefixed file names or import aliases** — caught and fixed
  twice this batch (a scratch script, and pre-existing `as m2`/`as m5` test import
  aliases from months-earlier modules). Use descriptive acronyms instead (`cs`, `sd`,
  `bs`, `cc`, `smv`, `tb`, etc.), matching this repo's own dominant convention.
- **Multi-feature grids need an explicit cross-feature independence check before
  being counted as separate `N_tests`** — M12's own pre-registration had explicitly
  skipped this ("not checked for correlation before declaring... cheap to run both
  rather than spend the check"), which the coordinating session had to catch and run
  before finalizing the FDR consolidation. Any future module declaring 2+ features
  measuring related things (volume, distance, slope, etc.) should run this check
  itself, at declaration time, rather than leaving it for later.

**Cleanup done (2026-09-24)**: all 4 Batch-2 worktrees/branches removed. Nothing left
over from Batch 2 — Batch 3 starts clean.

**Batch 2/3/4 scoping below is unchanged and still the reusable part of this file.**

## Infrastructure inventory (check again before starting a new batch — it may have changed)

- Cached panel (`data/features/moving_averages/ma_panel/`, 405 S&P 500 tickers, U1
  universe, 2010-01-04→2021-12-31, holdout-safe) has: SMA/EMA at {20,50,150,200},
  `dist_pct`/`dist_atr`/`dist_z` + `above` state at those lookbacks, `slope_log_k` at
  k∈{5,21,63}, `atr_14`, `volume`, `mom_12_1`/`mom_1_0`/`realized_vol_63`,
  `run_length_bucket_sma_*`, `dist_from_52w_high`/`dist_from_52w_low`, `sector`
  (current-state only, not PIT), `stacked_sma`/`stacked_ema`. Full list: run
  `read_panel(...).columns` or read `features/panel.py`'s own docstring.
- **Not built**: WMA/HMA/DEMA/KAMA (only SMA/EMA exist; a minimal module-local VWMA
  stub now exists in `features/liquidity.py`, built for M12 — the full 5-kernel build
  + White's Reality Check is still M8's job), lookbacks other than {20,50,150,200} in
  the *shared* panel (M6.6 added local-only 10/100 SMA slope for its own ribbon;
  M3 added local-only EMA 8/10/21 for its own crossover pairs — neither touched the
  shared panel), `ribbon_width` as a shared panel column (M7 built its own local one),
  `features/regime.py` (ER/ADX/vol-regime), point-in-time `mktcap_decile`/
  `universe_flags` (M12's `dollar_volume`/SMA50 finding is capped at Tier 3 partly for
  lack of this — a live, named reason to eventually build it), weekly-timeframe panel
  build (though `bars_1w` raw data exists with broad coverage — 6,539 tickers — the
  panel-build path itself is daily-only). **Now built**: crossover/state-flip event
  detection (`features/crossover.py`, M3); `labels/path_metrics.py` (built twice,
  independently, by M6.6 (`forward_max_drawdown`) and M3's fork was told it might need
  the same thing and didn't collide — only `forward_max_drawdown` actually landed;
  MFE/MAE proper is still unbuilt).
- **DB tables** (`data/raw/market_data.sqlite`): `bars_1d/1h/1mo/1w`, `fetch_jobs`,
  `index_membership`, `macro_series` (VIX/FRED, no earnings), `shares_outstanding`,
  `splits`, `ticker_metadata`, `ticker_sector`, `tickers`. **No earnings-date table
  exists anywhere** — any module needing earnings proximity is out of scope until new
  data is ingested (M13, M6.3 both hit this and substituted proxies).
- **Existing pattern detectors** (a different repo subsystem M14 would integrate
  with): `src/signals/patterns/detectors/{cup_and_handle,double_top_bottom,
  flags_pennants,head_shoulders,reversal_123,triangles,vcp}.py`.
- **`market_common.indicators`** already has RSI/MACD/ATR/OBV wrappers (this repo's
  own reuse pointer in `CLAUDE.md`) — relevant to M17.

## Batch 3 — heavy, standalone infra builds (parallel-safe, but each a real project — 1-2 at a time, not 4) (next up)

| Module | What it needs |
|---|---|
| M8 | 5 new MA kernels (WMA/HMA/DEMA/KAMA/VWMA) + White's Reality Check (only BH exists in `stats/multiple_testing.py`) — DESIGN lines ~930-934 |
| M9 | `features/regime.py` (ER/ADX/vol regime), 3-stage methodology. **DESIGN itself flags this as the module most likely to produce a false positive** — pre-register the regime definition, don't tune thresholds after seeing results. DESIGN lines ~935-944 |
| M6.4 | Kaplan-Meier survival machinery + GBM-null simulation — nothing like this exists in `stats/` yet. DESIGN lines ~835-839 |
| M10 | Weekly panel-build path (`bars_1w` exists, but this needs a `Timeframe` parameter on `build_panel` — should be the only thing touching `features/panel.py` in its batch). DESIGN lines ~945-949 |

## Batch 4 — soft/hard dependencies, sequence last

- **M16** (linear-filter unification) and **M17** (RSI/stochastics nonlinearity
  probe) read better with M3/M6.1/M6.3 numbers in hand (M17 needs the full MA
  feature set as its regression baseline — already exists now). DESIGN lines
  ~854-887.
- **M14** (join with existing pattern detectors) — self-contained, needs to learn
  that subsystem's schema first. DESIGN lines ~977-979.
- **M15** (synthesis) — hard-blocked on everything else; close to moot as scoped
  (operates on "surviving Tier-1/2 claims" — as of Batch 1, one exists, so this may
  finally have something real to synthesize rather than a null note). DESIGN lines
  ~980-981.

**Not worth scoping:** M6.7 isn't an analysis module (a one-line report note about
MA "angle" being ill-defined, DESIGN lines ~849-853).

## Process notes for whoever runs the next batch

- **Use `Agent` with `subagent_type: "fork"` and `isolation: "worktree"`, one per
  module, launched in a single message for true parallelism.** Forking inherits this
  conversation's/this file's context (CLAUDE.md's invariants, the pre-registration
  template, the C1/C2/block-bootstrap machinery) without re-explaining it per prompt.
  From a fresh conversation with no shared context, use a non-fork agent and paste in
  the relevant scoping section here plus a pointer to `CLAUDE.md`/`DESIGN.md`/recent
  `PREREGISTRATION.md` entries.
- **Rate limits are the real bottleneck, not the work itself.** Every Batch-1 fork
  got interrupted at least once (some twice) and needed a `SendMessage` resume with
  an explicit "continue exactly from X" nudge — budget for this, it's normal. If a
  resumed agent's report trails off into something confused (using a tool that
  doesn't apply, waiting on a notification that isn't coming), don't trust the
  self-report — inspect the worktree directly (`git log`, `git status`) first. One
  Batch-1 fork also went genuinely idle for 9 real hours before quietly resuming on
  its own after a nudge — don't assume "no progress in N hours" means dead; check
  before duplicating its work.
- **Worktrees don't get `data/raw/market_data.sqlite`** (gitignored, ~4GB) — only
  `data/features/moving_averages/ma_panel` reliably gets symlinked in. Any module
  needing raw DB access needs `ln -s <main-repo>/data/raw/market_data.sqlite
  data/raw/` inside the worktree (untracked, no extra disk use) — tell forks needing
  DB access to do this proactively, not discover it mid-run.
- **Division of labor**: each fork owns its own new module/feature/test files plus
  its own `PREREGISTRATION.md` section, `EXPERIMENTS.csv` rows, and (Tier 1-3)
  `FINDINGS.md` entries — never `STATUS.md`/`REPORT.md` or the whole-grid FDR pass.
  The coordinating session consolidates those shared, prose-heavy files once after a
  batch lands, instead of 4+ agents fighting over the same paragraphs.
- **No AI attribution in this repo's commits or PR bodies** — no `Claude-Session:`
  line, no `Co-Authored-By`. Repeat this explicitly in every fork prompt.
- **Two-phase commit**: pre-register (commit) → build+run+log results (commit). Worth
  a quick `git log` spot-check before trusting a "done" report.
- **Verify before reporting a PR clean**: `gh pr view <n> --json files,additions,
  deletions` (no unexpected `STATUS.md`/`REPORT.md` touch), grep the PR body for
  attribution lines, spot-check the CSV's column count is consistent.
- **Doc-append merge conflicts between sibling PRs are expected and trivial** — both
  sides add a row/section at the same point; keep both, in whatever order reads
  sensibly (usually chronological by date).

## Where to actually start next

Read this file, then `STATUS.md` for the study's real tiered state and the relevant
`DESIGN.md` section for whichever module you're about to run. Batch 2's worktree
cleanup is done (2026-09-24) — nothing left over. **Batch 3 is the actual next body of
work**, but unlike Batches 1/2 it's explicitly *not* meant to run as 4 parallel forks —
each of its 4 modules (M8, M9, M6.4, M10) is its own real infrastructure project; run
1-2 at a time. M9 in particular needs a pre-registered regime definition committed
*before* looking at any results (DESIGN's own flag: "the module most likely to produce
a false positive").
