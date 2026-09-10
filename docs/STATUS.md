# Moving-averages study — status

One row per module actually run (Track B, pre-registered and executed). Not a
duplicate of `docs/features/moving-averages/PREREGISTRATION.md` — that file is the
frozen pre-registration text per module; this file is the cross-module scoreboard, kept
current, for "what do we actually know and what's still open." Full detail always lives
in `PREREGISTRATION.md` (per-module narrative) and `EXPERIMENTS.csv` (per-cell numbers,
every tested facet, whatever it found); this file points there rather than re-deriving.

Next up: M2, M5, M6.2 — see `docs/backlog.md` for the remaining minimal-core modules.

## Modules run

| Module | Run order & date | Tier & headline result | N_tests / independence / correction | Cost hurdle & verdict | Why chosen, what was known then | Numbers live in |
|---|---|---|---|---|---|---|
| **M4** — Distance from MA | 1st, 2026-09-08 (`0aa13c8`, PR #61) | **Tier 3**: `dist_pct`/`dist_atr`/`dist_z` × SMA20 only — CI excludes zero, directionally consistent, fails cost. **Tier 4**: all 6 SMA50/SMA200 facets — CI includes zero. | Declared grid: 90 bucket-level cells (3 normalisations × 3 lookbacks × 10 deciles); kill criterion evaluated at 9 facet-level (normalisation × lookback) tests. **Not deduplicated at the time it ran** — the SMA20 independence check (median per-date Spearman 0.94–0.98 between `dist_pct`/`dist_atr`/`dist_z`, found 2026-09-09 during M11 prep) was never run against M4's own grid. The same non-independence this found for SMA20 likely also holds at SMA50/SMA200, unchecked. No FDR run (deferred to whole-grid pass — see below). | Originally ad hoc (`entries_per_ticker_year`, entries-only): ~25.32/ticker-yr per leg, ~50.64/yr combined → conservative hurdle ~5.06%/yr, optimistic ~2.53%/yr. CI-low net-negative under both → **fails cost**. Reconciled 2026-09-09 against `costs.py::signals_per_year` (entry+exit convention, the repo standard going forward): 24.646/yr combined → 2.465%/yr hurdle. CI-low (1.6395%) still misses it. **Verdict unchanged under either convention.** | Promoted from Track A M0.1 (descriptive atlas) — 4 of 5 candidate observations pointed at distance-from-MA normalisation/shape questions. Ran before M1 only because Track A exploration surfaced it first, not because it outranked M1 on the minimal-core list. | `notebooks/moving_averages_distance_from_ma.ipynb` (full computation); `PREREGISTRATION.md` M4 entry + two 2026-09-09 addenda (NaN-fix check, turnover reconciliation); `EXPERIMENTS.csv` (all 9 facets, one row each). |
| **M1** — Baseline state conditioning | 2nd, 2026-09-09 (`87efc3d` PR #62, fixed `6cdee5b` PR #63, `75e42ce` PR #64) | **Tier 3**: lb20, lb50 (above/below state) — CI excludes zero, fails cost. **Tier 4**: lb200 — CI touches/spans zero at both the 3D and 4D control sets. **Run-length secondary layer: no finding** — fails the plateau rule (§6.7), zigzags sign at every lookback/direction. | Declared grid: 30 cells (3 lookbacks × [2 state + 2 directions × 4 run-length buckets]). **Primary cells (6: above/below × 3 lookbacks) are exact algebraic mirrors under C1/C2 by construction — 3 independent numbers, not 6**, found and verified bit-exact during this module's own run. The 24 run-length cells are nested inside their parent state cell (not independent additional tests). No FDR run (deferred — see below). | `stats/costs.py::signals_per_year` (entry+exit convention, the same tool later used to reconcile M4) — this is the module `costs.py` was built for. 30.377 / 17.990 / 7.785 flips/ticker-yr → 3.038% / 1.799% / 0.779%/yr hurdles at lb20/50/200. lb20: CI and point both miss. lb50: point clears at 3D, CI-bound does not (worse at 4D). lb200: CI touches/spans zero at both control sets — **fails regardless of its own (lowest) hurdle being technically clearable on point estimate alone.** | DESIGN §12's own recommended minimal-core *first* module and `docs/backlog.md`'s designated next module. Run second only because Track A happened to point at distance-from-MA first — explicitly not deprioritized on the merits (own entry's "Promoted from" note). | No notebook — `tests/test_moving_averages_baseline_state.py` + `src/signals/moving_averages/modules/baseline_state.py`; `PREREGISTRATION.md` M1 entry (all numbers reported directly in prose, cross-verified against `costs.py` — see the reconciliation note in this file's own text and in M4's addendum above); `EXPERIMENTS.csv` (3 primary lookbacks + 1 run-length summary row). |
| **M11** — Cross-sectional formulation | 3rd, 2026-09-09 (PR #67) | **Pending interpretation.** Raw numbers computed (7 cells: primary `dist_pct_sma_20`@21d, 4 secondary, 2 companions) but the pre-registered decisive test (IC floor 0.02 AND cost-adjusted spread CI, both CI-based) hasn't been applied yet — reported as data, not yet tiered, per instruction to report before interpreting. | Declared grid: 5 (1 primary + 4 secondary); `dist_atr`/`dist_z` companions excluded up front (found correlated with `dist_pct` at 0.94–0.98 during this module's own pre-registration). Already deduplicated at declaration — no further reduction expected at the whole-grid pass. | Primary cell combined hurdle: 24.635/yr flips → 2.463%/yr (10bps/rt, `costs.py`). Verdict not yet applied. | Chosen over M2/M5/M6.2 specifically because its control design (per-date cross-sectional stat, no stratify-and-drop) sidesteps the row-loss mechanism that hit M1's C2 layer, rather than inheriting it. | `PREREGISTRATION.md` M11 entry; `modules/cross_sectional.py`; `EXPERIMENTS.csv` (7 rows, `outcome=pending_interpretation`). |

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
