# Handover — parallel post-termination batches

**Written 2026-09-22, end of Batch 1's execution.** This file exists so a *different*
Claude Code conversation (no memory of this one) can pick this initiative up cold. It is
not part of this study's original file set (`CLAUDE.md`'s own Layout section) — it's
session/execution state and a forward plan, which `STATUS.md` (a *results* scoreboard)
doesn't cover. Read `CLAUDE.md` first regardless (its invariants apply to every module
below, no exceptions), then this file, then `STATUS.md` for the study's actual tiered
results.

## Why this exists at all

The MA study reached its own pre-registered termination condition on 2026-09-17,
confirmed again on 2026-09-20 after M18 (see `STATUS.md`'s "Study-level termination").
The minimal-core list (DESIGN §12: M1, M2, M4, M5, M6.2, M11, §7.5) and M18 are done,
tiered, and folded into a 35-test whole-grid FDR pass that found 0 Tier-1/2 survivors.

On 2026-09-21, the user asked to scope the *rest* of DESIGN's module list (M3, M6.1,
M6.3–M6.6, M7–M17 minus M11/M18) for parallel execution — not because the study needs
to reopen, but because the user wants these as model-input-feature candidates and
there's real remaining value in DESIGN's own module list beyond the minimal-core
subset. This is **explicitly post-termination, porous-scope work** (DESIGN §1.5, the
same rule that let M18 in) — every module below still goes through full pre-registration,
kill-criterion, C1/C2 control, and (eventually) the whole-grid FDR pass, same discipline
as everything else in this study. Nothing here is exempt from CLAUDE.md's invariants.

The full module-by-module build-cost triage (what infra exists vs. what's new, what's
parallel-safe vs. shared-file risk, what's genuinely infeasible) is in "Batch 2/3/4
scoping" below — that's the reusable part for whoever picks this up next.

## Batch 1 — done, PRs open, NOT merged, NOT consolidated

Four modules ran as parallel forked agents, each in its own git worktree (`isolation:
worktree` on the `Agent` tool) so they couldn't clobber each other's working directory.
All four are complete, individually verified (diff reviewed, no attribution lines, CSV
schema checked), tests passing — but **none of the following consolidation work has
happened yet**:

| Module | PR | Branch | Result | Tier-3 cells | Reversal check run? |
|---|---|---|---|---|---|
| M6.1 | [#81](https://github.com/omerk1/stocks_analysis/pull/81) | `m6-1-slope-vs-momentum` | Inconclusive — not killed, not confirmed (2 of 4 lookbacks' incremental-IC CI misses the 0.005 floor). Slope trades ~3.7x less than momentum for a similar signal — a real cost-shaped consideration even without a stronger IC edge. | 0 | n/a |
| M6.3 | [#82](https://github.com/omerk1/stocks_analysis/pull/82) | `m6-3-slope-magnitude-shape` | **U-shaped, not humped** (opposite of DESIGN's own prior) at all 3 SMA lookbacks. SMA50 (C2 −0.248%, CI [−0.354%,−0.153%]) and SMA200 (C2 −0.193%, CI [−0.337%,−0.056%]) **clear cost at every reading**. SMA20 clears the kill floor but fails cost and fails its own large-move-exclusion robustness check (gap-contamination-driven read). Substituted `slope_pctile_21` for DESIGN's literal `slope_atr_21` ask (invariant #7 conflict) and a large-single-day-move proxy for the earnings-exclusion companion (no earnings table exists). | **2** (SMA50, SMA200) | **No** — flagged as the top open caveat; the U-shape's falling tail is exactly what an uncontrolled reversal effect would produce |
| M7 | [#84](https://github.com/omerk1/stocks_analysis/pull/84) | `m7-ribbon-compression` | DESIGN's literal "compression → vol expansion" hypothesis **killed cleanly** on forward realized vol. A related cell survives: compression predicts bigger forward 21d \|return\| (magnitude, not signed direction) — C2 −0.2471%, CI [−0.3976%,−0.0927%], clears cost. Trend-conditional direction cell is inconclusive (does not confirm DESIGN's own stated prior). Caught and fixed two real `skipna=True` bugs in new label functions before trusting any real-panel numbers. | **1** (`direction_magnitude`) | **No** |
| M13 | [#83](https://github.com/omerk1/stocks_analysis/pull/83) | `m13-context-conditioning` | Sliced M1's `above_sma_200` C2 delta by VIX-percentile and breadth-percentile regime terciles. 2 of 4 cells clear zero-exclusion and cost, barely — but all 4 point estimates cluster tightly around M1's own whole-sample sign, read by the fork itself as "probably the same weak baseline effect exposed by regime-slicing, not a real interaction," not oversold. Earnings sub-question dropped (no data source); index-membership/sector-momentum facets deferred as a first-slice cut. | 2 (flagged skeptically) | n/a (weak/likely-spurious reading already) |

**Local worktrees still on disk** (safe to remove once each PR merges — `git worktree
remove` from the main checkout, not `rm -rf`, so git's own bookkeeping stays clean):
`.claude/worktrees/agent-{ad13886428efdeb82,aa8b1c43e8895674f,a2abb6fd00c1b3f62,a959b2c58b11ae870}`.

### Batch 1 — remaining work before it's actually "done" (in this order)

1. **Reversal-robustness check** (this study's own `rev_tercile`/`mom_1_0` C2 addition,
   established by M2/M6.2/M18) on the **3 cost-clearing Tier-3 cells**: M6.3's SMA50 and
   SMA200 U-shape cells, and M7's `direction_magnitude` cell. Same pattern as
   `PREREGISTRATION.md`'s M6.2 addendum (2026-09-21) — pre-register the addendum, run
   against each module's own already-built code (`match_cols` parameter should already
   exist or be trivial to add, following `stack_minervini.py`'s/`slope_conditioner.py`'s
   own `C2_MATCH_COLS_WITH_REVERSAL` precedent), log the result whichever way it goes.
   M6.3's fork explicitly flagged this as live and consequential (the U-shape's falling
   tail is plausibly a reversal/bounce artifact) — don't skip it.
2. **Merge the 4 PRs, one at a time, resolving conflicts as they land.** All four touch
   `PREREGISTRATION.md`, `EXPERIMENTS.csv`, and (where Tier 1-3) `FINDINGS.md` at
   overlapping append points — conflicts are expected and mostly trivial ("both sides
   add a row/section," keep both), not a sign anything is wrong. None of the four touch
   `STATUS.md`/`REPORT.md` (by design, see below) or each other's new module/test files,
   so there's no *logic* conflict, only doc-append conflicts. Suggested order: #81 (no
   Tier-3 cells, simplest) → #83 → #84 → #82 (do the reversal check from step 1 before or
   as part of merging #82, since it changes what #82's own entries should say).
3. **Consolidated whole-grid FDR re-run.** Current state: N=35 (`STATUS.md`, as of
   M18). Batch 1 adds candidate cells the same way M18 did — every declared cell counts
   toward `N_tests`, not just survivors (this study's established convention). Needs:
   a fresh dedup pass (check new cells for correlation/redundancy against each other and
   against the existing 35, same discipline as every prior pass), then re-run
   `stats/multiple_testing.py::benjamini_hochberg`. Do this **after** the reversal checks
   in step 1, since a cell that dies under reversal-matching still gets logged but
   arguably shouldn't be presented as a live FDR candidate the same way (see how M6.2's
   `touch_x_slope` was handled after its own reversal check failed — same treatment
   applies here if M6.3/M7's cells don't survive theirs).
4. **Consolidate `STATUS.md` and `REPORT.md` myself** (the coordinating session's job,
   explicitly withheld from all 4 forks to avoid a 4-way conflict on prose-heavy shared
   sections): new "Modules run" table rows for M6.1/M6.3/M7/M13, an updated whole-grid
   FDR section reflecting the new N and ranked table, and — if warranted by outcome —
   an update to `REPORT.md`'s executive summary / suggestive-findings section. This is
   the same shape of work as the M6.2 reversal-robustness session (see that PR, #80, for
   the pattern: pre-register → run → log to PREREGISTRATION/EXPERIMENTS/FINDINGS →
   consolidate STATUS/REPORT last).
5. Clean up the 4 worktrees and merged branches (local `git worktree remove` +
   `git branch -d` + `git push origin --delete`), same as was done after PR #80.

## Batch 2/3/4 scoping — carried over from the 2026-09-21 triage, unchanged

This is the build-cost/dependency triage for everything DESIGN defines beyond the
minimal-core list and Batch 1, worked out by checking what infrastructure actually
exists in this codebase (not just what DESIGN describes) before estimating cost. Still
accurate as of 2026-09-22 — nothing in Batch 1 changed what exists for these.

**Infrastructure inventory that drove this triage (check again before starting a new
batch — it may have changed):**
- Cached panel (`data/features/moving_averages/ma_panel/`, 405 S&P 500 tickers, U1
  universe, 2010-01-04→2021-12-31, holdout-safe) has: SMA/EMA at {20,50,150,200},
  `dist_pct`/`dist_atr`/`dist_z` + `above` state at those lookbacks, `slope_log_k` at
  k∈{5,21,63}, `atr_14`, `volume`, `mom_12_1`/`mom_1_0`/`realized_vol_63`,
  `run_length_bucket_sma_*`, `dist_from_52w_high`/`dist_from_52w_low`, `sector`
  (current-state only, not PIT), `stacked_sma`/`stacked_ema`. Full list: run
  `read_panel(...).columns` or read `features/panel.py`'s own docstring.
- **Not built**: WMA/HMA/DEMA/KAMA/VWMA (only SMA/EMA exist), lookbacks other than
  {20,50,150,200}, `ribbon_width`-as-a-shared-column (M7 built its own local one, not
  added to the shared panel), `features/regime.py` (ER/ADX/vol-regime — doesn't exist),
  crossover/state-flip event detection, point-in-time `mktcap_decile`/`universe_flags`,
  weekly-timeframe panel build (though `bars_1w` raw data exists with broad coverage —
  6,539 tickers — the panel-build path itself is daily-only).
- **DB tables** (`data/raw/market_data.sqlite`): `bars_1d/1h/1mo/1w`, `fetch_jobs`,
  `index_membership`, `macro_series` (has `VIXCLS`/FRED VIX and other FRED series, no
  earnings), `shares_outstanding`, `splits`, `ticker_metadata`, `ticker_sector`,
  `tickers`. **No earnings-date table exists anywhere** — any module needing earnings
  proximity is out of scope until new data is ingested (M13 and M6.3 already hit this
  and substituted proxies; the same substitution pattern applies to any future module
  that wants earnings).
- **Existing pattern detectors** (a different repo subsystem M14 would integrate with):
  `src/signals/patterns/detectors/{cup_and_handle,double_top_bottom,flags_pennants,
  head_shoulders,reversal_123,triangles,vcp}.py`.
- **`market_common.indicators`** already has RSI/MACD/ATR/OBV wrappers (per this
  repo's own reuse pointer in `CLAUDE.md`) — relevant to M17.

**Batch 2 — moderate builds, module-local, no cross-conflicts (next up, same
parallel-fork pattern as Batch 1):**
| Module | What it needs |
|---|---|
| M3 | New crossover-event detector (DESIGN lines ~753-762) — also becomes the shared infra M6.2's deferred "golden cross × slope" sub-question needs, and is loosely relevant to M16 |
| M6.5 | SMA drop-off decomposition (entering-bar vs. exiting-bar contribution, DESIGN lines ~840-845) |
| M6.6 | New lookbacks 10/100 added *locally* (not to the shared panel) so ribbon-slope-agreement can be computed (DESIGN lines ~846-848) |
| M12 | Relative-volume/dollar-volume features (`volume` is already in the panel); VWMA — soft overlap with M8, can stub its own minimal version rather than wait (DESIGN lines ~970-973) |

**Batch 3 — heavy, standalone infra builds (parallel-safe across agents, but each is a
real project — probably don't bundle 4 of these into one wave the way Batch 1 did 4
cheap ones; consider 1-2 at a time given how much rate-limit budget even the cheap
Batch-1 modules burned across multiple resume cycles):**
| Module | What it needs |
|---|---|
| M8 | 5 new MA kernels (WMA/HMA/DEMA/KAMA/VWMA) + White's Reality Check (only BH exists in `stats/multiple_testing.py`) — DESIGN lines ~930-934 |
| M9 | `features/regime.py` (ER/ADX/vol regime — doesn't exist), 3-stage methodology. **DESIGN itself flags this as the module most likely to produce a false positive** — pre-register the regime definition, don't tune thresholds after seeing results. DESIGN lines ~935-944 |
| M6.4 | Kaplan-Meier survival machinery + GBM-null simulation — nothing like this exists in `stats/` yet. DESIGN lines ~835-839 |
| M10 | Weekly panel-build path. `bars_1w` exists with broad coverage, but this is the one module that needs to extend `features/panel.py` itself (a `Timeframe` parameter on `build_panel`) — should be the only thing touching that file in whatever batch includes it, to avoid conflicting with anything else in flight. DESIGN lines ~945-949 |

**Batch 4 — soft/hard dependencies, sequence last:**
- **M16** (linear-filter unification, DESIGN lines ~854-864) and **M17** (RSI/stochastics
  nonlinearity probe, DESIGN lines ~867-887) — buildable earlier, but both read much
  better with M3/M6.1/M6.3 numbers already in hand (M17 specifically needs "the full MA
  feature set" as its regression baseline, which already exists now).
- **M14** (join with existing pattern detectors, DESIGN lines ~977-979) — self-contained
  but needs to learn that subsystem's schema first.
- **M15** (synthesis, DESIGN lines ~980-981) — hard-blocked on everything else finishing;
  also close to moot as scoped (it operates on "surviving Tier-1/2 claims," and nothing
  has reached Tier 1/2 in this study yet — may end up being a short "still nothing to
  synthesize" note rather than real analysis, unless something above finally clears FDR).

**Not worth scoping:** M6.7 isn't an analysis module (a one-line report note about MA
"angle" being ill-defined, DESIGN lines ~849-853).

## Process notes for whoever runs the next batch

- **Use `Agent` with `subagent_type: "fork"` and `isolation: "worktree"`, one per
  module, launched in a single message for true parallelism.** Forking (not a fresh
  agent) matters here — it inherits this conversation's/this file's context (CLAUDE.md's
  invariants, the established per-module PREREGISTRATION.md template, the C1/C2/
  block-bootstrap machinery, the reuse pointers) without you having to re-explain all of
  it in every prompt. If starting from a *new* conversation with no shared context, use
  a non-fork agent and paste in the relevant scoping section from this file plus a
  pointer to read `CLAUDE.md`/`DESIGN.md`/recent `PREREGISTRATION.md` entries directly.
- **Rate limits are the real bottleneck, not the work itself.** Every one of Batch 1's
  4 forks got interrupted by session rate limits at least once (some twice) and needed
  a `SendMessage` resume with an explicit "continue exactly from X" nudge. Budget for
  this — it's normal, not a sign anything is broken. When a resume notification shows
  the agent's `<result>` trailing off into something confused (e.g. trying to use a tool
  that doesn't apply, waiting on a notification that isn't coming), don't assume it
  finished — inspect the worktree directly (`git log`, `git status`, `git branch
  --show-current`) before either trusting its self-report or writing a resume message,
  same as was done for M6.1's stalled first resume.
- **Worktrees don't automatically get `data/raw/market_data.sqlite`** (it's gitignored,
  ~4GB, not copied into a fresh worktree checkout) — only `data/features/moving_averages/
  ma_panel` reliably gets symlinked in. Any module needing raw DB access (new joins
  against `macro_series`/`index_membership`/`ticker_sector`, or anything not already in
  the cached panel) will hit a missing-DB error. The clean fix, done successfully by the
  M13 fork on its own: `ln -s <main-repo>/data/raw/market_data.sqlite data/raw/` inside
  the worktree (untracked, `git status` stays clean, no extra disk use). Consider telling
  future forks to do this proactively up front if their module needs DB access, rather
  than discovering it mid-run.
- **Division of labor that worked well and should repeat:** each fork owns its own new
  module/feature/test files plus its own `PREREGISTRATION.md` section, `EXPERIMENTS.csv`
  rows, and (if Tier 1-3) `FINDINGS.md` entries — and explicitly does NOT touch
  `STATUS.md`/`REPORT.md` or run the whole-grid FDR pass. The coordinating session
  consolidates those two shared, prose-heavy files once, after a batch lands, instead of
  4+ agents fighting over the same paragraphs.
- **No AI attribution in this repo's commits or PR bodies** — no `Claude-Session:` line,
  no `Co-Authored-By`. This is a stored user preference for this specific repo; repeat it
  explicitly in every fork prompt, since a fresh (or resumed-after-rate-limit) agent
  won't otherwise know and the general system default is to *add* such a line.
- **Two-phase commit pattern**: pre-register (commit) → build+run+log results (commit).
  Every fork in Batch 1 was told this; one (M6.3) briefly violated it (wrote code before
  committing the pre-registration) and self-corrected once nudged — worth restating
  clearly in future prompts, and worth a quick `git log` spot-check before trusting a
  "done" report.
- **Verify before reporting a PR as clean**, same as was done for all 4 Batch-1 PRs:
  `gh pr view <n> --json files,additions,deletions` (confirm no `STATUS.md`/`REPORT.md`
  touch, no unexpected file), grep the PR body for attribution lines, and spot-check the
  CSV's column count is consistent (`csv.reader` + compare row lengths) rather than just
  trusting the fork's self-report.

## Where to actually start next

Read this file, then `STATUS.md` (for the study's real tiered state) and the relevant
`DESIGN.md` sections for whichever module(s) you're about to run — per `CLAUDE.md`'s own
"Session start" instructions, unchanged by any of this. If Batch 1's PRs are still open
and unmerged, the reversal checks + merge + FDR re-run + STATUS/REPORT consolidation
(above) is the actual next step, not starting Batch 2 on top of an unconsolidated Batch 1.
