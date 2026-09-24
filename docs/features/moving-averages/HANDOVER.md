# Handover — post-termination parallel batches

**Written 2026-09-22, revised 2026-09-23 (Batch 1 done), revised 2026-09-24 (Batch 2
done), revised 2026-09-24 (Batch 3 done), revised 2026-09-25 (Batch 4 in progress).**
This file exists so a *different* Claude
Code conversation (no memory of this one) can pick this initiative up cold. It's
session/execution state and a forward plan, not part of this study's original file set
(`STATUS.md` covers results). Read `CLAUDE.md` first (its invariants apply to every
module below, no exceptions), then this file, then `STATUS.md` for the study's actual
tiered results.

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

**Batch 3 (M8, M9, M10, M6.4) is done, merged, and consolidated** (PRs #97–#100, plus
this session's own FDR consolidation — same coordinating-session job as Batches 1/2).
Run 2 pairs, not 4-way parallel, per this file's own Batch-3 scoping: M8+M10 first
(disjoint files — M10 owns `features/panel.py` exclusively, M8 never touches it), then
M9+M6.4 (both wanted an "efficiency ratio" feature; M9 owns the new shared
`features/regime.py`, M6.4 built its own local temporary copy of the identical formula
rather than block on M9, flagged for reconciliation — never actually reconciled this
session, still open, see below). Result: **M8 and M9 killed cleanly** (DESIGN's own
~80%/~70% priors both held); **M10 killed cleanly** (no weekly-sampling advantage);
**M6.4 was NOT killed** — a real, well-powered slope-persistence departure from a GBM
null, capped at Tier 3 by an open, unresolved null-calibration caveat (the GBM null's
own volatility estimate may be circular). The whole-grid FDR re-run (N=79→99) produced
this study's **largest survivor set to date** (10 of 99 at q=0.10, 5 at q=0.05),
anchored by M6.4's SMA20 vol-tercile trio (the three smallest p-values this study has
ever produced) — **but the Tier-2 count is still unchanged** (still exactly one,
`slope_pctile_21_sma_50`/M6.3, now confirmed robust across three consecutive grid
expansions). A genuinely new, repeated pattern surfaced this pass: `ribbon_direction_magnitude`
(M7), `stack_fully_bearish` (M2), and `above_sma_20` (M1) have each now flipped FDR
status three times across three consecutive passes (survived at N=50, dropped at
N=79, back at N=99) with their tier assignment never once changing — a live
demonstration, not just a hypothetical, of why FDR-survivor-set membership alone
shouldn't be read as evidence quality. Full detail in `STATUS.md`'s "Whole-grid FDR
pass" section (2026-09-24 Batch-3 update) and `REPORT.md`.

**Resolved 2026-09-25 (PR #102)**: M9's and M6.4's independently-built `efficiency_ratio`
copies are reconciled into one shared function in `features/regime.py`. Along the way,
found and fixed a real (if harmless-to-already-logged-numbers) invariant-#9 concern:
M6.4's own copy used `.fillna(0.0)` on undefined warmup rows instead of leaving them
`NaN` — checked directly that this never affected any already-logged number before
swapping the implementation (M6.4's shortest construction needs ~41 days of warmup,
far past ER's own 10-day warmup, so no real run-entry row was ever misclassified).

**Cleanup done (2026-09-24)**: all 2 Batch-3 worktree pairs (4 worktrees total)
removed, all branches deleted (local and remote). Nothing left over from Batch 3 —
Batch 4 starts clean.

**Batch 4 (M16, M17, M14, M15) analysis work is done, 2026-09-25 — merging/consolidation
in progress.** Run as 3 parallel forks (M16/M17/M14, each in its own worktree — no
shared-file conflicts among the three, unlike Batch 3's M8/M10 pairing) plus M15 held
back as hard-blocked on the other three finishing, per this file's own scoping below.
- **M16 (PR #103) and M17 (PR #104) are done, merged, and consolidated into `STATUS.md`.**
  M16 (Track A): DESIGN's own "one signal, many names" clustering prior holds at a
  loose similarity threshold, with one genuine deviation found at a tighter one
  (`slope_log_21_sma_200` doesn't cluster with the SMA200 crossover/distance rules the
  way DESIGN predicted). M17: MACD is **not** redundant with the MA feature set
  (contradicting DESIGN's own 75% prior), Tier 3, capped by an unresolved reversal
  confound; RSI/stochastics stay inconclusive.
- **M14 (PR #105) is done, complete, and open, but not yet merged.** Pooled cell
  (all 7 pattern types): not confirmed, Tier 4, killed by the same extension/momentum
  confound M6.3 already found. **A targeted VCP-specific addendum** (does the result
  differ specifically within VCP formations, given VCP's own MA-native construction —
  a single hypothesis, not a full 7-pattern-type sweep) found something real
  underneath the pooled null: an **opposite-signed, extension-robust** effect
  (default C2 +1.83% CI [+1.06%,+2.77%], extension-neutralized +1.99% CI
  [+1.43%,+2.61%] — not attenuated), clearing cost by the widest margin in this
  study's history. Well-powered for a targeted slice (505 events, 409 dates, 227
  tickers, passed its own effective-N gate before trusting the number) but its
  reversal-robustness check hit `InsufficientBlocksError` (too few contributing
  dates) — an honest open gap — and carries a real shape caveat (favorable hit rate,
  but markedly more negative skew in-context, a fatter downside tail). Tier 3.
  **Once merged**: needs its own `STATUS.md` "Modules run" row and folding into the
  next whole-grid FDR pass, same as every other module — not done yet, this file's
  own next-step item.
- **Whole-grid FDR re-run for Batch 4 not yet done** — M17 contributes 6 new counted
  cells; M14's own contribution (pending the VCP addendum's outcome) isn't final yet.
  Held until M14 lands, same one-consolidation-per-batch discipline as Batches 2/3,
  rather than running it twice in quick succession.
- **A real, separate documentation-debt item found and partially fixed 2026-09-25,
  while checking that everything landed this session was actually documented**:
  `REPORT.md`'s §5 ("Module results"), §6 ("Suggestive findings"), and §7 ("Dead-ends
  register") had never been updated past the original minimal-core module set + M18 —
  §5 still explicitly claimed M3/M6.1/M6.3-M6.6/M7-M17 (aside from M18) were "never
  attempted," which was false for all of them by this point. Being fixed as part of
  this same revision — check `REPORT.md`'s own header date before trusting it's
  current, the same "don't assume, verify" discipline this file asks of everything
  else.

**Batch 2/3/4 scoping below is unchanged and still the reusable part of this file.**

## Infrastructure inventory (check again before starting a new batch — it may have changed)

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
  and M6.4's own local temporary `efficiency_ratio` both operate off existing panel
  columns without adding new lookbacks either — none of these touched the shared
  panel), `ribbon_width` as a shared panel column (M7 built its own local one),
  point-in-time `mktcap_decile`/`universe_flags` (M12's `dollar_volume`/SMA50 finding
  and M6.4's GBM-null calibration are both capped at Tier 3 partly for lack of
  this-or-adjacent infra — live, named reasons to eventually build it), MFE/MAE proper
  (`labels/path_metrics.py` only has `forward_max_drawdown` so far). **Now built**:
  crossover/state-flip event detection (`features/crossover.py`, M3); WMA/HMA/DEMA/
  KAMA/VWMA (`features/kernels.py`, M8 — VWMA also has a separate, simpler module-local
  stub in `features/liquidity.py` from M12, not reconciled with `kernels.py`'s own
  version, low priority); White's Reality Check (`stats/multiple_testing.py::white_reality_check`,
  M8); a `Timeframe` parameter on `build_panel` (`features/panel.py`, M10 — daily
  default unchanged, `Timeframe.WEEKLY` resamples live from `bars_1d`; only
  MA/distance/slope/ATR/run-length features are timeframe-correct at non-daily
  granularity, day-count-calibrated context features like `mom_12_1` are not
  recalibrated, a named open gap); `features/regime.py` (`efficiency_ratio`,
  `average_directional_index`, M9 — M6.4's own local temporary `efficiency_ratio` copy
  is not yet reconciled with this one, see the open item above); Kaplan-Meier survival
  + GBM-null simulation (`stats/survival.py`, M6.4, entirely new).
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

## Batch 4 — soft/hard dependencies, sequence last

- **M16** (linear-filter unification) — **done**, PR #103, merged. DESIGN lines
  ~854-865.
- **M17** (RSI/stochastics nonlinearity probe) — **done**, PR #104, merged. DESIGN
  lines ~867-887.
- **M14** (join with existing pattern detectors) — **first result landed**, PR #105,
  open; a targeted VCP-specific addendum is running as of this revision (see "Where
  things stand" above). DESIGN lines ~977-979.
- **M15** (synthesis) — **next up, still hard-blocked on M14 landing** (operates on
  "surviving Tier-1/2 claims" — one exists as of Batch 1, `slope_pctile_21_sma_50`/
  M6.3, confirmed robust through every subsequent FDR re-run). DESIGN lines ~980-981.

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
`DESIGN.md` section for whichever module you're about to run. **All of Batch 4's
analysis work is done** (M16/M17 merged; M14 including its VCP addendum is complete,
PR #105 open, not yet merged — see "Where things stand" above for its own striking
result). **Once M14 merges**: (1) run the whole-grid FDR re-run (M17's 6 counted
cells + M14's contribution, neither folded in yet), (2) update `STATUS.md`/`REPORT.md`
the same way every prior batch's consolidation did — including a full M14 entry given
its VCP finding, not just a one-line mention, (3) clean up the remaining Batch-4
worktree/branch, (4) start M15 (synthesis) — the only module left in Batch 4,
hard-blocked until here, and now has a real second Tier-1/2-adjacent candidate to
synthesize against M6.3's cell, not just a null note.
Also worth a spot-check before trusting `REPORT.md` for anything: its §5-§7 were
significantly out of date as of 2026-09-25 (see "Where things stand" above) and were
being brought current in the same revision as this note — confirm that actually
landed rather than assuming it did.
