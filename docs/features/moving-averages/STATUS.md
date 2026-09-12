# Moving-averages study — status

One row per module actually run (Track B, pre-registered and executed). Not a
duplicate of `docs/features/moving-averages/PREREGISTRATION.md` — that file is the
frozen pre-registration text per module; this file is the cross-module scoreboard, kept
current, for "what do we actually know and what's still open." Full detail always lives
in `PREREGISTRATION.md` (per-module narrative) and `EXPERIMENTS.csv` (per-cell numbers,
every tested facet, whatever it found); this file points there rather than re-deriving.

Next up: M2 (in progress, `analysis/m2-stack-minervini`), M5, M6.2 — see
`docs/backlog.md` for the remaining minimal-core modules.

## Modules run

| Module | Run order & date | Tier & headline result | N_tests / independence / correction | Cost hurdle & verdict | Why chosen, what was known then | Numbers live in |
|---|---|---|---|---|---|---|
| **M4** — Distance from MA | 1st, 2026-09-08 (`0aa13c8`, PR #61) | **Tier 3**: `dist_pct`/`dist_atr`/`dist_z` × SMA20 only — CI excludes zero, directionally consistent, fails cost. **Tier 4**: all 6 SMA50/SMA200 facets — CI includes zero. | Declared grid: 90 bucket-level cells (3 normalisations × 3 lookbacks × 10 deciles); kill criterion evaluated at 9 facet-level (normalisation × lookback) tests. **Not deduplicated at the time it ran** — the SMA20 independence check (median per-date Spearman 0.94–0.98 between `dist_pct`/`dist_atr`/`dist_z`, found 2026-09-09 during M11 prep) was never run against M4's own grid. The same non-independence this found for SMA20 likely also holds at SMA50/SMA200, unchecked. No FDR run (deferred to whole-grid pass — see below). | Originally ad hoc (`entries_per_ticker_year`, entries-only): ~25.32/ticker-yr per leg, ~50.64/yr combined → conservative hurdle ~5.06%/yr, optimistic ~2.53%/yr. CI-low net-negative under both → **fails cost**. Reconciled 2026-09-09 against `costs.py::signals_per_year` (entry+exit convention, the repo standard going forward): 24.646/yr combined → 2.465%/yr hurdle. CI-low (1.6395%) still misses it. **Verdict unchanged under either convention.** | Promoted from Track A M0.1 (descriptive atlas) — 4 of 5 candidate observations pointed at distance-from-MA normalisation/shape questions. Ran before M1 only because Track A exploration surfaced it first, not because it outranked M1 on the minimal-core list. | `notebooks/moving_averages_distance_from_ma.ipynb` (full computation); `PREREGISTRATION.md` M4 entry + two 2026-09-09 addenda (NaN-fix check, turnover reconciliation); `EXPERIMENTS.csv` (all 9 facets, one row each). |
| **M1** — Baseline state conditioning | 2nd, 2026-09-09 (`87efc3d` PR #62, fixed `6cdee5b` PR #63, `75e42ce` PR #64) | **Tier 3**: lb20, lb50 (above/below state) — CI excludes zero, fails cost. **Tier 4**: lb200 — CI touches/spans zero at both the 3D and 4D control sets. **Run-length secondary layer: no finding** — fails the plateau rule (§6.7), zigzags sign at every lookback/direction. | Declared grid: 30 cells (3 lookbacks × [2 state + 2 directions × 4 run-length buckets]). **Primary cells (6: above/below × 3 lookbacks) are exact algebraic mirrors under C1/C2 by construction — 3 independent numbers, not 6**, found and verified bit-exact during this module's own run. The 24 run-length cells are nested inside their parent state cell (not independent additional tests). No FDR run (deferred — see below). | `stats/costs.py::signals_per_year` (entry+exit convention, the same tool later used to reconcile M4) — this is the module `costs.py` was built for. 30.377 / 17.990 / 7.785 flips/ticker-yr → 3.038% / 1.799% / 0.779%/yr hurdles at lb20/50/200. lb20: CI and point both miss. lb50: point clears at 3D, CI-bound does not (worse at 4D). lb200: CI touches/spans zero at both control sets — **fails regardless of its own (lowest) hurdle being technically clearable on point estimate alone.** | DESIGN §12's own recommended minimal-core *first* module and `docs/backlog.md`'s designated next module. Run second only because Track A happened to point at distance-from-MA first — explicitly not deprioritized on the merits (own entry's "Promoted from" note). | No notebook — `tests/test_moving_averages_baseline_state.py` + `src/signals/moving_averages/modules/baseline_state.py`; `PREREGISTRATION.md` M1 entry (all numbers reported directly in prose, cross-verified against `costs.py` — see the reconciliation note in this file's own text and in M4's addendum above); `EXPERIMENTS.csv` (3 primary lookbacks + 1 run-length summary row). |
| **M11** — Cross-sectional formulation | 3rd, 2026-09-09 (code + raw numbers, PR #67); tiered 2026-09-10 (no new PR — see the PR-boundary note below); cost-verdict correction + `dist_pct_sma_50`@21d moved to Tier 4, both 2026-09-10 (see below) | **Tier 3** (4 of 7 cells): primary `dist_pct_sma_20`@21d, `dist_pct_sma_20`@5d, and the `dist_atr`/`dist_z` companions — CI excludes zero, real weak effect. **3 of these 4 fail cost; `dist_pct_sma_20`@5d clears it** (corrected 2026-09-10 — see below). **Tier 4** (3 of 7): `dist_pct_sma_200`@21d, `dist_pct_sma_20`@63d (CI spans zero on both IC and spread), and `dist_pct_sma_50`@21d (moved 2026-09-10 — see below). **Primary cell additionally failed its own pre-registered decisive test** (`decisive_test_status=failed`, IC-floor sub-test) — killed as a *construction* ("not worth the added machinery over M4"), tiered as *evidence* per DESIGN §9.2's 2026-09-10 addendum (kill and tier are now separate axes, recorded separately, never collapsed into one label). **Tier is unchanged for the cost-viable cell too** — Tier 3 is capped by missing FDR/holdout infrastructure, not by cost; clearing cost doesn't promote it. **Four of these seven cells' neutralized-spread number is not independent of M4** — see the non-independence note below. | Declared grid: 5 (1 primary + 4 secondary); `dist_atr`/`dist_z` companions excluded up front (0.94–0.98 correlated with `dist_pct` at SMA20, found during this module's own pre-registration) — already deduplicated at declaration. | Primary cell combined hurdle: 24.635/yr flips → 2.463%/yr (10bps/rt, `costs.py`). Spread (C1), 21d→annualized: point −0.50% (×12=−6.05%, **clears**), far edge −10.88% (clears), **near-zero edge −0.51% (misses)**. Sector/vol/momentum-neutralized spread: point −5.57% (clears), near-zero edge −1.64% (misses, closer to clearing than C1's). **Verdict: fails on the CI-based test in both control layers**, same structural shape as M1's cost failures, at a proportionally larger gross magnitude. | Chosen over M2/M5/M6.2 specifically because its control design (per-date cross-sectional stat, no stratify-and-drop) sidesteps the row-loss mechanism that hit M1's C2 layer, rather than inheriting it. | `PREREGISTRATION.md` M11 entry + 2026-09-10 "Result and feasibility addendum" + 2026-09-10 correction addenda; `EXPERIMENTS.csv` (7 rows, tiered, `counted_in_n_tests`/`decisive_test_status` columns, `cost_verdict` filled in for all 7). |
| **§7.5** — Level effects vs. trend effects (placebo test) | 4th, 2026-09-12 (`873c112`, branch `analysis/placebo-7-5`, PR pending) | **Tier 4, all 3 groups — folklore confirmed, no group survives.** SMA200 vs {187,193,207,213}: killed at the trivial step, focal's own C2 CI spans zero (no detectable effect at SMA200 or any of its 4 neighbors). SMA50 vs {47,53}: **same trivial mechanism** — focal C2 CI spans zero (`[-0.006533,+0.000326]`); an earlier in-conversation summary of this cell mischaracterized it as "real effect killed by neighbor-indistinguishability," corrected against the raw output before logging. EMA21 vs {19,23}: the one group with a real, individually CI-excluding-zero focal effect (`-0.004585 [-0.007898,-0.001413]`) — killed at the intended step, indistinguishable from both untraded neighbors (both `diff_g,n` CIs span zero, and both neighbors show essentially the same effect EMA21 does). | 3 group-level tests declared and run as 3 (not the 11 individual lookback cells) — no dedup issue, declared correctly from the start. | Not applicable — no group reached "confirmed," so the pre-registered cost step (CLAUDE.md invariant #8) never fires for any of the three. | Cheapest, highest-signal item left on the minimal-core list (DESIGN §7.5: "the most elegant test... cheap to run either way"); motivated directly by M11's SMA20 cost-viable reading and the SMA200 watch below. | `PREREGISTRATION.md` §7.5 entry; `EXPERIMENTS.csv` (3 rows: `placebo_sma200_h21`, `placebo_sma50_h21`, `placebo_ema21_h21`). |

**§7.5 plateau note:** this test *is* a plateau check by construction, and it's the cleanest one this study has produced — within every group, the focal lookback's point estimate and CI sit inside its neighbors' own range, no lone bright pixel anywhere. Two of three groups (SMA200, SMA50) show no detectable dist_pct effect at all in that neighborhood; the third (EMA21/19/23) shows a real, detectable, but level-agnostic effect — the textbook "it's a trend-length proxy, not a watched level" shape DESIGN itself predicted as the likelier outcome.

**Non-independence note (2026-09-10):** M11's neutralized-spread statistic is not new
evidence for the four cells M4 already tested at 21d (`dist_pct`/`dist_atr`/`dist_z`
`_sma_20`, `dist_pct_sma_50`) — traced at the code level (not inferred from matching
numbers): both call `stats/inference.py::block_bootstrap_spread` with identical
arguments (same decile construction, same match columns post-fix, same panel, same
block/boot/seed parameters), so it deterministically recomputes M4's own C2 spread for
those cells. A reader counting these as corroborating, independent results would
double-count. What M11 does contribute independently: the rank-IC statistic itself,
the zero-row-loss C1 layer, and the `h5`/`h63` horizons M4 never tested. See
`PREREGISTRATION.md`'s M11 entry, "What M11 still buys over M4" (corrected 2026-09-10),
for the full record.

**`dist_pct_sma_50`@21d tier change (2026-09-10):** moved Tier 3 → Tier 4. Its C1-layer
CI excludes zero but its neutralized-layer CI spans zero
(`[-0.006533, +0.000326]`) — original tiering used the C1 reading without checking the
neutralized layer against it. Per DESIGN §9.2's 2026-09-10 resolution (the stronger
control tier is authoritative when the two disagree, matching this study's own
C1-vs-C2 precedent), this cell tiers on the neutralized layer.

**Cost-verdict correction (2026-09-10):** `dist_pct_sma_20`@5d's gross edge was
originally annualized with the 21d cells' ×12 factor instead of the horizon-correct
×50.4 — corrected near-zero edge is −3.45%/yr (was reported −0.82%/yr), which clears
its 2.466%/yr hurdle (hurdle itself confirmed horizon-independent, unaffected). Full
record, including why the shortest-horizon cell being the one that clears cost is the
shape a short-term-reversal generator (via the uncontrolled `mom_1_0` confound) would
produce rather than evidence favoring an MA-distance effect specifically: see
`PREREGISTRATION.md`'s dated correction addendum.

**PR-boundary note (2026-09-10):** PR #67 merged M11's code and raw numbers on
2026-09-09 with every cell tagged `pending_interpretation` — tiering happened the
following day, in conversation, with no code or file-structure changes and therefore no
new PR. In retrospect the PR boundary landed at "code + numbers," not "code + numbers +
an honest tier assignment" — M1 and M4 both had their tiering land inside the same PR
that produced their numbers. Worth naming as a process point for the next module, not a
defect in M11's result: don't assume a merged module PR means a tiered module.

## Cross-module SMA200 watch — trigger fired, not investigated

`docs/backlog.md`'s own standing item: *"If a later module turns up a third independent
SMA200-specific oddity, that's the trigger to stop treating these as coincidence and
audit SMA200 across the study."* Two were on record already — M4's `dist_z_sma_200`
(252-day normalisation-window instability) and M1's lb200 (74.9% row loss, 84.5%
all-above skew, the CI touching zero). **M11's `dist_pct_sma_200_h21` (Tier 4 in M11 —
see the Modules run table above, and `EXPERIMENTS.csv`) is the third:** CI spans zero
at both IC (`[-0.02528, 0.01663]`) and spread (`[-0.00939, 0.00465]`),
the only lookback of the three that fails this way, under a construction with **zero
row loss** — which rules out M1's leading candidate mechanism (the C2 selection/skew
effect) as the explanation for this instance specifically, since M11's C1 layer has no
stratify-and-drop step to skew anything. That narrows backlog.md's open candidate list
(selection effect vs. the 252-day-window-vs-200-day-lookback ratio vs. both vs.
unrelated) without resolving it.

**Trigger fired. Not investigated inside M11, per instruction — logged here as the
record that it fired, still owner-less.** Whoever picks up M2 or later should treat an
SMA200-specific audit as live, not speculative, before trusting any future SMA200
result at face value.

**§7.5 update (2026-09-12) — contextualizes but does not resolve the watch.** The
placebo test's SMA200 group found **zero dist_pct effect at SMA200 itself** (C2 CI
`[-0.005312,0.002444]`) — and the identical near-zero non-effect at all four of its
untraded neighbors (187/193/207/213), a clean plateau. This is a different fact than
the three prior SMA200 oddities (which were about instability/row-loss/CI-width at
SMA200 specifically, not "no effect anywhere near that lookback"), so it neither
confirms nor rules out any of backlog.md's open candidates (selection effect vs.
252-day-window ratio vs. both vs. unrelated) — it does add a data point that "nothing
about *this* corner of the study is anomalous once you also look at SMA200's own
placebo neighborhood," which is mildly against a SMA200-specific mechanism and mildly
for "SMA200's oddities are a small-effect/low-power story, not a level-specific one."
Not resolved; still owner-less.

## Whole-grid FDR pass — open, owner-less

Not run. DESIGN §6.6's correction denominator (`N_tests`) accumulates across the whole
pre-registered grid, not per module — every module to date has deferred it with an
identical note, and nobody has been assigned to actually run it once the grid is
"enough."

**Trigger condition (2026-09-09):** the pass runs at whichever comes first —
1. **Before any module is promoted above Tier 3.** Tier 2 requires "survives C2 and
   FDR" (DESIGN §9.2) — that's not assignable without the correction having actually
   run, so a Tier-2-or-above call on any facet is a hard trigger, not just a milestone.
2. **Minimal-core completion** — once M2, M5, and M6.2 have also been attempted
   (joining M1, M4, and now M11), whichever of the two conditions above is hit first.

As part of that pass, both open dedup items below get resolved properly, not deferred
again:
- **M1's mirror collapse** — primary cells are 3 independent numbers, not 6 (already
  found and verified bit-exact in M1's own entry; the pass needs to actually *consume*
  this, not just cite it).
- **M4's facet correlations, across all three lookbacks** — SMA20's 0.94–0.98
  correlation between `dist_pct`/`dist_atr`/`dist_z` is checked (2026-09-09 addendum,
  `PREREGISTRATION.md`); SMA50 and SMA200 are not yet checked at all. Both need the
  same per-date Spearman check SMA20 got before M4's contribution to the correction
  denominator can be trusted.

**Per-module contribution as currently declared (raw, not deduplicated):**

| Module | Declared N_tests | Known non-independence |
|---|---|---|
| M4 | 90 (bucket-level) / 9 (facet-level, the level kill was actually evaluated at) | SMA20's 3 normalisations are 0.94–0.98 correlated (found 2026-09-09) — **not corrected in M4's own entry.** SMA50/SMA200 unchecked. |
| M1 | 30 | Primary 6 cells are exact mirrors → 3 independent. 24 run-length cells are nested inside their parent state cell, not additional independent tests. |
| M11 | 5 | Already deduplicated at declaration — `dist_atr`/`dist_z` companions (0.94–0.98 correlated with `dist_pct_sma_20`) excluded from the count up front, not left for the whole-grid pass to catch. |

More modules (M2, M5, M6.2) will add rows here as they're pre-registered.

**This changes the 30 — and probably the 90 too.** Naively summing the raw declared
counts (90 + 30 + 5 = 125, before any later module adds its own) overstates the actual
number of independent hypothesis tests by a wide margin once every module's
mirrors/companions/nesting are accounted for. M1's
own entry already states its primary layer is 3 independent numbers, not 6, but the
FDR pass hasn't been run against that reduced count — it's been reported, not consumed.
M4 has never had the equivalent check run at all; the SMA20 finding strongly suggests it
needs one before its 9 (or 90) enters any correction denominator. **The whole-grid pass,
whenever it runs, needs to deduplicate each module's own contribution first** (per that
module's own stated independence findings), not take each module's raw declared grid
size at face value and sum them.

**A second, distinct source of inflation in the naive 125, found 2026-09-10: cells
aren't only non-independent *within* a module, some aren't independent *across*
modules either.** M11's neutralized spread for `dist_pct_sma_20`/`dist_atr_sma_20`/
`dist_z_sma_20`/`dist_pct_sma_50` (all at 21d) is a deterministic recomputation of
M4's own C2 spread for those same (feature, lookback) pairs — traced at the code
level, `block_bootstrap_spread` called with identical arguments in both modules (see
the M11 row's non-independence note above). That's a different failure mode from the
within-module mirror/nesting/correlation issues already tracked in the table above —
those are about one module's own grid double-counting itself; this is about two
modules' grids partially double-counting *each other*. The whole-grid pass needs to
catch both, and the cross-module case is easy to miss precisely because it looks like
independent corroboration (two modules, two different pre-registrations) rather than
the same number twice.

## Study-level termination — when this is finished

Per DESIGN §1.4/§1.5, "done" is a report with **~15–30 falsifiable claims** (each
tiered per §9.2), a dead-ends register, the reusable feature panel, and a
cost-sensitivity appendix — **not** a target number of Tier-1 findings. DESIGN §1.5's
own expected ratio: Track A generates 100+ candidates, ~20 reach the promotion gate,
~10 get pre-registered, **3–6 survive** to Tier 1/2. Landing meaningfully outside that
band is itself informative (§9.2: "if you end up with twenty Tier-1 claims, you have a
bug in your controls, not a discovery").

**Termination is reached when either:**
- The minimal-core list (DESIGN §12: M1, M2, M4, M5, M6.2, M11, plus the §7.5 placebo)
  is run, tiered, and the whole-grid FDR pass above has actually executed against the
  deduplicated count — **not just deferred again** — or
- Evidence saturates before the full list finishes: if 4–5 modules in a row land Tier 3
  or 4 with no Tier-1/2 survivor and no new mechanism story emerging (the M4→M1
  SMA200-anomaly watch item is the kind of thing that would count as "new mechanism
  story" and extend the study, not close it), that's a legitimate early stop, documented
  as such.

**The negative case is a valid finish, not a failure to reach one.** Two modules in (M4,
M1), the running result is already mostly negative-leaning: 5 of 9 M4 facets and 1 of 3
M1 lookbacks are Tier 4 outright, and every SMA20/lb20/lb50 Tier-3 result that looked
real gross died on cost. If this pattern holds through the rest of the minimal-core
list — directionally-real-but-uneconomical or outright-absent everywhere — **the
finished study is "the MA-state family is mostly a re-encoding of momentum and mostly
doesn't survive realistic costs where it isn't,"** written up with the same rigor and
the same report structure (§9.1) as a positive result would get. DESIGN says this
explicitly and this file takes it at face value: **a null result is a successful
outcome**, not a reason to keep looking for a cut that works.

**Saturation watch (2026-09-12): 4 modules in a row now Tier 3/4 only.** M4, M1, M11,
and §7.5 have all landed with no Tier-1/2 survivor — exactly the count the early-stop
clause above names ("4–5 modules in a row"). §7.5's result is arguably a *supporting*
mechanism story (folklore-confirmed, level-agnostic effect), not a *new* one in the
sense that would reset this counter — it explains *why* M4/M1/M11's SMA-state effects
look the way they do (trend-length proxy), it doesn't introduce a fresh candidate
mechanism. Not calling early termination unilaterally here — M2 is already in flight
(`analysis/m2-stack-minervini`) and DESIGN's own words call it "the highest
expected-value module in the doc," worth seeing regardless. But whoever reviews M2's
result should weigh the early-stop clause explicitly rather than defaulting to "run M5
next" on autopilot, if M2 also lands Tier 3/4 with nothing new.
