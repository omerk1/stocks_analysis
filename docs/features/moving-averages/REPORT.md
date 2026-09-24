# Moving-averages study — final report

**Date:** 2026-09-18, updated 2026-09-20, 2026-09-21, 2026-09-23, 2026-09-24 (×2).
**Status:** study terminated per its own pre-registered criteria (`STATUS.md`'s
"Study-level termination" section) — the minimal-core list (DESIGN §12: M1, M2, M4,
M5, M6.2, M11, plus §7.5) ran and was tiered, and the whole-grid FDR pass executed
against the deduplicated grid. Twelve further modules were added post-termination via
DESIGN §1.5's porous-scope rule (M18 on 2026-09-20; M6.1/M6.3/M7/M13 — "Batch 1" — on
2026-09-22/23; M3/M6.5/M6.6/M12 — "Batch 2" — on 2026-09-23/24; M8/M9/M10/M6.4 —
"Batch 3" — on 2026-09-24), each pre-registered and folded into a re-run of the
whole-grid FDR pass rather than reported outside that discipline (N:
31→35→50→79→99). **The 2026-09-23 re-run changed the study's headline for the first
time**: 5 cells then survived Benjamini–Hochberg correction (1 at q=0.05), and one of
them — `slope_pctile_21_sma_50` (M6.3) — was promoted to Tier 2 the same day once a
decomposition test resolved its one open caveat. **Both 2026-09-24 re-runs (Batch 2,
N=79; Batch 3, N=99) changed which cells survive FDR — each time some cells dropped
out and others joined — but neither changed the Tier-2 count**: still exactly one
(`slope_pctile_21_sma_50`, confirmed robust across three consecutive grid expansions),
still zero Tier 1. The Batch-3 pass produced the largest survivor set in this study's
history (10 of 99 at q=0.10, 5 at q=0.05) and, for the first time, every single
survivor clears its own BH threshold without depending on the step-up sweep
mechanism. Full detail: §1, §4 below (§4 carries the current, N=99 table; the N=79
and N=50 tables are kept alongside it, marked superseded, per this report's own
no-silent-edits convention). Every number below is sourced to `EXPERIMENTS.csv`,
`FINDINGS.md`, `PREREGISTRATION.md`, or `STATUS.md` — this report synthesizes, it does
not re-derive.

---

## 1. Executive summary

**One claim reached Tier 2 ("Probable") — the study's first — and zero reached
Tier 1.** DESIGN §1.5 expected 3–6 Tier-1/2 survivors from a study this size; landing
at one, on 50 independent tests, is close to that band's floor rather than inside it,
and is reported as such rather than rounded up or down.

**Tier 2 — `slope_pctile_21_sma_50` (M6.3).** Stocks with an extreme 50-day-SMA slope
— rising or falling, either direction — outperform stocks with a flat one over the
next 21 days, the opposite of the "some trend is good, too much is exhaustion" prior
this module set out to test. C2 −0.248%, CI [−0.354%, −0.153%], clears cost at every
reading. It survives every confound checked against it: a large-move exclusion, a
short-term-reversal control, the whole-grid FDR pass (p=0.00005 — the smallest in the
study, clearing even the stricter q=0.05 screen), and a rising-tail-only vs.
falling-tail-only decomposition that ruled out a delisted-ticker survivorship
artifact (both sides independently show the same effect: rising −0.254% CI
[−0.429%, −0.085%], falling −0.244% CI [−0.413%, −0.096%]). Its only remaining gaps —
an untested holdout period and a second universe tier — are missing infrastructure,
not failures, which is exactly DESIGN §9.2's Tier-2 profile.

**2026-09-24 Batch-3 update, current: 3 more cells clear FDR at N=99 (M6.4's SMA20
vol-tercile trio), plus a repeat demonstration of FDR "flapping":**
- **`slope_persistence_vol_tercile_sma20_t0/t1/t2`** (M6.4, does empirical
  slope-persistence exceed a matched-volatility GBM-null's own survival curve —
  ranks 1/3/5, p≈0.000000/0.000016/0.000105, the three smallest p-values this study
  has ever produced): real, well-powered departures from the null (all three vol
  terciles, both SMA20 and SMA50 show the same plateau; only SMA20's p-values are
  small enough to clear correction). **Not promoted**: the GBM null's own volatility
  estimate is computed from the same potentially-autocorrelated series being tested,
  which could bias the null low and inflate apparent departures — an open, unresolved
  validity question, not yet ruled out by a direct test.
- **`ribbon_agreement_extreme_drawdown`** (M6.6) and **`reclaim_durability_dollar_volume_sma50`**
  (M12) continue to survive (ranks 2 and 6) — unchanged reasoning from the prior pass.
- **`dist_from_52w_low`@126d** (M18, rank 7) continues to survive — unchanged
  reasoning.
- **The "flapping" pattern, now observed three times in a row**: `ribbon_direction_magnitude`
  (M7), `stack_fully_bearish` (M2), and `above_sma_20` (M1) survived at N=50, dropped
  out at N=79, and are back at N=99 (ranks 8-10) — three FDR-status flips each, zero
  new evidence about any of the three. None has ever reached Tier 2 at any point (each
  capped by its own independent reason — M7's actionability gap, M2's survivorship
  policy, M1's cost failure), so **despite three flips each, the tier assignment for
  all three has never once changed.** This is the concrete, repeated version of the
  risk this report's own 2026-09-24 Batch-2 update first named as a single instance.

**Unlike every prior pass, all 10 current survivors individually clear their own BH
threshold — none depends on the step-up sweep mechanism**, even the tightest (ranks
8-9, ~95% of their own threshold).

**2026-09-24 Batch-2 pass's own summary (superseded above, kept for the record):** 4
cells cleared FDR at N=79 — `ribbon_agreement_extreme_drawdown` (M6.6, rank 1),
`slope_pctile_21_sma_50` (M6.3, rank 2), `reclaim_durability_dollar_volume_sma50`
(M12, rank 3), `dist_from_52w_low`@126d (M18, rank 4) — while `ribbon_direction_magnitude`
(M7), `stack_fully_bearish` (M2), and `above_sma_20` (M1) had dropped out from the
2026-09-23 pass's own 5-survivor set, purely from denominator growth (`above_sma_20`'s
own threshold moved from 0.0100 at N=50 to 0.0089 at N=79 against an unchanged
p=0.0090). See the Batch-3 update above for what happened to all three next.

**Two more Tier-3 cells (M6.2) do not survive FDR at all:** `extension_x_slope`
(SMA50 top decile, −0.59%, clears cost, p=0.0254) and `touch_x_slope` (SMA50
`from_above`, −5.75pp) — the latter also fails its own reversal-robustness check
(attenuates ~40%, CI now spans zero), the only cell in this study where that check
flips a result from confirmed to inconclusive.

Full ranked table, per-cell reasoning, and the FDR pass's own methodology: §4 below.

**The single cleanest result in the study is a negative one**: M5's touch/test/bounce
module found **zero** distinguishable difference between price behavior at a real,
widely-watched MA and at a statistically near-identical, unwatched synthetic
neighbor, across 3 lookback families and both directions (6/6 cells killed, largest
CI edge 0.61pp against a 2pp floor). **Support/resistance from moving averages, in
this ex-ante design, is folklore.**

**The recurring shape across the whole study**: wherever a gross, uncontrolled effect
looked real, it shrank sharply under date-matching (C1) and further under
momentum/vol/sector matching (C2). Most of the cells whose shrunk C2 effect still
excluded zero then failed a realistic 10bps-round-trip cost hurdle (M4's three SMA20
facets, M1's lb20/lb50, M11's SMA20 cells at 21d/63d, M18's `dist_from_52w_low`@63d).
Among the handful that cleared cost too, most still failed FDR — but not all: one
(§1's Tier-2 finding above) survived every check run against it. `dist_from_52w_high`
(M18) is the cleanest instance of the pattern's harshest form: two independent,
uncontrolled Track A readings (an OLS attribution coefficient, a raw IC screen) both
found a real-looking gross effect, and it vanished entirely — not just shrank — under
C2 matching. **The MA-state family in this study is mostly a re-encoding of momentum;
what survives control-matching mostly does not survive being one hypothesis among
many — with one confirmed exception.**

---

## 2. Methodology and controls (condensed)

**Universe and window (U1):** 405 S&P 500 constituents with full coverage of the
2010-01-04 → 2021-12-31 development window (S&P 500 membership as of the 2021-12-31
holdout boundary, `data.py::sp500_full_coverage_tickers`). **Holdout** (everything
after 2021-12-31) was never read, loaded, or aggregated in this study (CLAUDE.md
invariant #1) — no result here has been checked for holdout stability, and "holdout"
is accordingly one of the standing caps on every Tier-3 cell.

**One-bar lag** (invariant #2): every feature is shifted forward one trading day
before being paired with a forward return or used to define an event, applied
centrally in `features/panel.py::apply_lag` — never a per-module hand-rolled shift.

**Controls (DESIGN §6.1), used identically across every module:**
- **C0** — unconditional mean difference. Reported only for the shrinkage waterfall,
  never as a result (its baseline dilutes with the event group's own rows — see
  `pooled_delta` vs. `c0_delta`, PREREGISTRATION.md's M1 entry).
- **C1** — date-matched: event-group mean minus that date's non-event mean, averaged
  across dates (each date weighted equally).
- **C2** — date **+** momentum-tercile (`mom_12_1`) **+** vol-tercile
  (`realized_vol_63`) **+** sector matched. **This is the tier every kill criterion
  and every headline number in this study is evaluated on** — the tier that
  separates real MA information from momentum re-encoding.

**Inference:** block-bootstrap CIs over resampled *dates* (never rows — 21-day
forward returns overlap 20/21, so a naive row-level CI understates uncertainty by
roughly √21), block length 42 (2× the 21-day horizon) for return-based cells, 10 for
the sparser, non-overlapping touch-event cells (M5, M6.2's `touch_x_slope`), 500
draws, 90% CI (`stats/inference.py`).

**Kill criteria:** every module pre-registered its own, always stated *before*
running (`PREREGISTRATION.md`), always evaluated on C2. Two shapes recur: a
magnitude floor (`max(|ci_low|, |ci_high|) < 0.10%` for return-based cells, `< 2pp`
for hold-rate cells) and a distinguishability test (does the focal cell's CI exclude
zero *and* differ from every comparable neighbor/control). Per DESIGN §9.2's
2026-09-10 resolution, a kill criterion is a verdict on the *construction*, never on
the *tier* — the two are reported side by side (`decisive_test_status` alongside
`tier` in `EXPERIMENTS.csv`), never collapsed into one label.

**Costs (§6.10):** `signals_per_year × 10bps round-trip` (U1's own convention),
turnover measured directly off the panel (state-flip count), never assumed.
Annualization of a 21-day delta is a labeled linear approximation (`×12`, or the
horizon-correct multiple for other horizons) — not a compounding model.

**Plateau rule (§6.7):** applied per module as whatever "neighborhood" makes sense
for that construction — lookback neighbors (§7.5, M5's synthetic levels), sign
consistency with a parent module (M2, M6.2), or internal cross-lookback consistency.

**Minimum sample thresholds (§6.9):** 200 events, ≥30 distinct dates, ≥30 distinct
tickers, applied per cell — below-threshold cells are flagged, never dropped or
silently interpreted.

**Synthetic pipeline validation (Phase 1 gate):** `validate-synth` recovers a planted
effect at the right magnitude and reports nothing on a no-effect control — the gate
this whole study's credibility rests on (CLAUDE.md: "if this is failing or absent, no
result from this repo means anything").

**Whole-grid multiple-testing correction (§6.6):** Benjamini–Hochberg at q = 0.10,
run once, at study termination, against every module's deduplicated contribution —
methodology and full ranked table in §4 below and `STATUS.md`.

---

## 3. The shrinkage table

DESIGN's own words: "this is the paper's contribution." Not every module logged a
full C0→C1→C2 progression on a single state indicator (M4/M11/§7.5's natural
statistic is a decile spread, C1 vs. C2, rather than a state-conditional delta) — this
table reports whatever waterfall each module actually built, not a fabricated common
shape.

### M1 — full pooled(C0) → C1 → C2 waterfall (`PREREGISTRATION.md`, 2026-09-09)

| lookback | pooled (C0 leg) | C1 | C2 | shrinks monotonically? |
|---|---|---|---|---|
| above/below SMA20 | −0.5748% | −0.2734% | −0.2146% | **yes** |
| above/below SMA50 | −0.5589% | −0.3246% | −0.1830% | **yes** |
| above/below SMA200 | −0.4207% | −0.1805% | −0.2149% | **no** — \|C2\| > \|C1\| (a genuine, still-unexplained residual, not an artifact — see §5's SMA200 discussion) |

Reading: roughly 60–70% of the *gross* (pooled) SMA20/50 effect is explained away by
matching alone — real information remains (C2 excludes zero at both), but most of
what a naive unconditional comparison would report is momentum and volatility
re-encoded as "above/below the MA."

### M4 — C2 decile spread only (C1 not separately logged in this study's committed record)

| facet | C2 spread (21d) | CI | cost hurdle | verdict |
|---|---|---|---|---|
| `dist_pct_sma_20` | −0.464% | [−0.776%, −0.137%] | 2.465%/yr | fails |
| `dist_atr_sma_20` | −0.372% | [−0.665%, −0.094%] | 2.619%/yr | fails |
| `dist_z_sma_20` | −0.374% | [−0.654%, −0.118%] | 2.617%/yr | fails |
| SMA50/SMA200, all 3 normalisations (6 facets) | −0.16% to −0.30% | all span zero | n/a | not tested |

### M11 — C1 vs. sector/vol/momentum-neutralized C2 spread

| cell | C1 spread (annualized) | C2/neutralized spread (annualized) | cost hurdle | verdict |
|---|---|---|---|---|
| `dist_pct_sma_20`, 21d (primary) | −6.05%/yr | −5.57%/yr | 2.463%/yr | fails (near-zero CI edge misses on both layers: C1 −0.51%/yr, neutralized −1.64%/yr) |
| `dist_pct_sma_20`, 5d (secondary) | −10.70%/yr (raw 5d point −0.21%, ×50.4) | −10.81%/yr (raw 5d point −0.21%, ×50.4) | 2.466%/yr | **clears** (near edge −3.45%/yr, corrected annualization, 2026-09-10) |

### M2 — standalone C2 vs. incremental-vs-M1

| cell | standalone C2 | incremental vs. `above_sma_50` | cost hurdle | verdict |
|---|---|---|---|---|
| `stack_fully_bullish` | −0.064% [−0.202%, +0.067%] | +0.013% [−0.066%, +0.087%] | 1.426%/yr | fails both |
| `stack_fully_bearish` | +0.474% [+0.161%, +0.776%] | **+1.055% [+0.419%, +1.740%]** | 0.286%/yr | clears cleanly, **survives FDR as of the 2026-09-23 N=50 re-run (§4), capped at Tier 3 by DESIGN §7.3's survivorship policy instead** |

### M6.2 — C1 vs. C2, within-state/decile/touch restriction

| cell | C1 | C2 | C2 + `rev_tercile` (2026-09-21) | cost hurdle | verdict |
|---|---|---|---|---|---|
| `extension_x_slope`, SMA50 top | −0.398% | **−0.592% [−1.047%, −0.175%]** | −0.550% [−0.978%, −0.103%] — survives | 0.806%/yr | clears cleanly, **fails FDR** |
| `touch_x_slope`, SMA50 `from_above` | −7.06pp | **−5.75pp [−10.22pp, −1.94pp]** | −3.33pp [−8.18pp, +1.25pp] — **CI spans zero** | n/a (mechanism read) | **fails FDR, fails reversal check** |

### M18 — C1 vs. C2 (post-termination), decile spread

| cell | C1 | C2 | cost hurdle | verdict |
|---|---|---|---|---|
| `dist_from_52w_high`@63d | −1.93% | −0.38% [−1.51%, +0.73%] | n/a | CI spans zero, not tested |
| `dist_from_52w_high`@126d | −4.03% | −0.67% [−2.63%, +1.21%] | n/a | CI spans zero, not tested |
| `dist_from_52w_low`@63d | +1.85% | +0.96% [+0.13%, +1.84%] | 0.825%/yr | real, fails cost |
| `dist_from_52w_low`@126d | +4.12% | **+2.50% [+1.10%, +4.02%]** | 0.834%/yr | clears cleanly, **fails FDR** |

Reading: both `dist_from_52w_high` cells shrink from a real-looking C1 gross number to
a C2 CI that spans zero entirely — the sharpest C1→C2 collapse in this study (a real
effect at C1, gone at C2, not just attenuated). `dist_from_52w_low` shrinks less
(roughly half, C1→C2) and stays real at both horizons — the harder-to-explain-away
shape, consistent with a genuine effect surviving a control that is unusually close,
by construction, to the feature itself (`mom_tercile` and `dist_from_52w_low` are both
functions of roughly the trailing year's price path).

---

## 4. Whole-grid FDR pass — full result

Full methodology, per-module deduplication table, and reasoning:
`STATUS.md`'s "Whole-grid FDR pass" section (run 2026-09-17 at N=31, re-run
2026-09-20 at N=35 once M18 was added, re-run again 2026-09-23 at N=50 once Batch 1 —
M6.1, M6.3, M7, M13 — was added; each pass's own prior cells keep their p-values
unchanged, only the ranks/thresholds shift as the denominator grows). **Current
(2026-09-23) summary:**

- **N_tests = 50**, deduplicated from a naive raw sum that would run well past 140 once
  every module's own mirrors, correlated facets, cross-module duplicates, no-CI
  descriptive statistics, and robustness-check companion rows are accounted for (full
  per-module dedup table: `STATUS.md`). Batch 1 contributes 15 net new cells: M6.1's 4
  lookback cells (cross-lookback correlation checked directly, 0.35–0.88, below this
  study's own 0.89 redundancy bar), M6.3's 3 primary cells, M7's 4 (of 5 declared — two
  vol-expansion readings merged as the same hypothesis tested two ways), and M13's 4.
- **`stats/multiple_testing.py::p_value_from_ci`** backs out a two-sided Wald
  p-value from each cell's already-computed 90% CI (a labeled normal approximation —
  this study's bootstrap functions don't archive raw per-cell draws, so an exact
  empirical p-value isn't available without rebuilding every module's pipeline).
- **Result: 5 of 50 rejected at q = 0.10, 1 of 50 at q = 0.05.** This is a change from
  every prior pass in this study (all found zero survivors). `slope_pctile_21_sma_50`
  (M6.3) anchors the result at p=0.00005 — four orders of magnitude under its own
  rank-1 threshold, and the only survivor that also clears q=0.05. Its very small
  p-value sweeps four more cells into BH's rejection set via the step-up rule, three of
  which (`dist_from_52w_low`@126d, `ribbon_direction_magnitude`, `stack_fully_bearish`)
  do *not* individually clear their own rank's threshold in isolation — standard,
  correct BH behavior, not an error, but worth naming because it means those three
  survive on the grid's overall composition rather than on their own margin the way
  rank 1 and rank 5 (`above_sma_20`) do.
- **Stress-tested (2026-09-23) against three alternative reasonable dedup counts**
  (N=47, 50, 51): identical 5-cell survivor set and identical rank-1 p-value every
  time — the result is not an artifact of this pass's specific dedup judgment calls.
- **One of the 5 survivors — `slope_pctile_21_sma_50` (M6.3) — reaches Tier 2**, the
  first in this study's history: it clears DESIGN §9.2's full bar (C2, FDR, cost),
  and a same-day rising-tail-only vs. falling-tail-only decomposition resolved its one
  open caveat (delisted-ticker survivorship exposure in the falling tail) by direct
  test rather than analogy — both tails independently show the same effect. **The
  other 4 stay at Tier 3**, each for its own independent reason: cost failure
  (`above_sma_20`), DESIGN §7.3's pre-existing survivorship cap (`stack_fully_bearish`),
  a magnitude-vs-signed-return actionability gap (`ribbon_direction_magnitude`), or the
  same kind of survivorship-cap concern as M6.3's cell but not yet resolved by a direct
  test (`dist_from_52w_low`@126d). Full per-cell reasoning: `FINDINGS.md`'s 2026-09-23
  addenda on each cell.

**2026-09-24 Batch-3 update, current: N_tests = 99** (the 79 above, unchanged, plus
Batch 3's 20 — M8 contributes 0 [Reality Check's own p-value is methodologically
incompatible with this pass's Wald/BH machinery], M9 1 [DESIGN's own false-positive
warning collapsed the module to a single decisive test], M10 7, M6.4 12; full dedup
reasoning in `STATUS.md`, including a direct check that neither M9 nor M6.4 left an
independence gap the way M12 did last pass — none found). **Result: 10 of 99 rejected
at q=0.10, 5 of 99 at q=0.05** — the largest survivor set in this study's history.
Three of M6.4's SMA20 vol-tercile cells produced the three smallest p-values this
study has ever seen (ranks 1, 3, 5), displacing M6.6 to rank 2 and M6.3's own Tier-2
cell to rank 4 (still clearing q=0.05 comfortably). `reclaim_durability_dollar_volume_sma50`
(M12) and `dist_from_52w_low`@126d (M18) continue to survive (ranks 6-7). **The three
cells that dropped out at N=79 are back** (`ribbon_direction_magnitude`,
`stack_fully_bearish`, `above_sma_20` — ranks 8-10) — three FDR-status flips each
across three consecutive passes, with the tier assignment for all three never once
changing. **Unlike every prior pass, all 10 current survivors individually clear
their own rank's threshold** — none depend on a step-up sweep, even the tightest
(ranks 8-9, ~95% of their own threshold). **Tier-2 count unchanged: still exactly
`slope_pctile_21_sma_50`, confirmed robust across three consecutive grid
expansions.** Full reasoning and the current ranked table: `STATUS.md`'s "Whole-grid
FDR pass" section.

| rank | cell | p-value | BH threshold (rank/99×0.10) | reject q=0.10? |
|---|---|---|---|---|
| 1 | M6.4 `slope_persistence_vol_tercile_sma20_t0` | ~0.000000 | 0.00101 | **yes** |
| 2 | M6.6 `ribbon_agreement_extreme_drawdown` | 0.000002 | 0.00202 | **yes** |
| 3 | M6.4 `slope_persistence_vol_tercile_sma20_t1` | 0.000016 | 0.00303 | **yes** |
| 4 | M6.3 `slope_pctile_21_sma_50` | 0.000050 | 0.00404 | **yes — Tier 2** |
| 5 | M6.4 `slope_persistence_vol_tercile_sma20_t2` | 0.000105 | 0.00505 | **yes** |
| 6 | M12 `reclaim_durability_dollar_volume_sma50` | 0.003476 | 0.00606 | **yes** |
| 7 | M18 `dist_from_52w_low`@126d | 0.004679 | 0.00707 | **yes** |
| 8 | M7 `ribbon_direction_magnitude` | 0.007674 | 0.00808 | **yes** |
| 9 | M2 `stack_fully_bearish_h21` | 0.008606 | 0.00909 | **yes** |
| 10 | M1 `above_sma_20` | 0.009032 | 0.01010 | **yes** |
| 11–99 | (remaining 89 cells) | ≥0.0135 | — | no |

Full ranked table (top 25 explicitly): `STATUS.md`. Note on the flapping cells:
`above_sma_20` individually cleared its own threshold at N=50 (0.0090 vs. 0.0100),
missed at N=79 (0.0090 vs. 0.0089), and clears again at N=99 (0.0090 vs. 0.0101) —
three flips purely from denominator/anchor-point changes, not new evidence. `ribbon_direction_magnitude`
and `stack_fully_bearish_h21` show the identical pattern.

**Superseded — 2026-09-24 Batch-2 pass's own ranked table (N=79), kept for the record:**

| rank | cell | p-value | BH threshold (rank/79×0.10) | reject q=0.10? |
|---|---|---|---|---|
| 1 | M6.6 `ribbon_agreement_extreme_drawdown` | ~0.00000 | 0.0013 | **yes** |
| 2 | M6.3 `slope_pctile_21_sma_50` | 0.00005 | 0.0025 | **yes — Tier 2** |
| 3 | M12 `reclaim_durability_dollar_volume_sma50` | 0.00348 | 0.0038 | **yes** |
| 4 | M18 `dist_from_52w_low`@126d | 0.00468 | 0.0051 | **yes** |
| 5 | M7 `ribbon_direction_magnitude` | 0.0077 | 0.0063 | no |
| 6 | M2 `stack_fully_bearish` | 0.0086 | 0.0076 | no |
| 7 | M1 `above_sma_20` | 0.0090 | 0.0089 | no |
| 8–79 | (remaining 72 cells) | ≥0.0135 | — | no |

**Superseded — 2026-09-23 pass's own ranked table (N=50), kept for the record:**

| rank | cell | p-value | BH threshold (rank/50×0.10) | reject q=0.10? |
|---|---|---|---|---|
| 1 | M6.3 `slope_pctile_21_sma_50` | 0.00005 | 0.0020 | **yes — Tier 2** |
| 2 | M18 `dist_from_52w_low`@126d | 0.0047 | 0.0040 | **yes**\* |
| 3 | M7 `ribbon_direction_magnitude` | 0.0077 | 0.0060 | **yes**\* |
| 4 | M2 `stack_fully_bearish` | 0.0086 | 0.0080 | **yes**\* |
| 5 | M1 `above_sma_20` | 0.0090 | 0.0100 | **yes** |
| 6 | M11 `dist_pct_sma_20_h5` | 0.0135 | 0.0120 | no |
| 7 | M4 `dist_pct_sma_20_h21` | 0.0170 | 0.0140 | no |
| 8 | §7.5 `placebo_ema21_h21` | 0.0200 | 0.0160 | no |
| 9 | M6.2 `touch_x_slope` SMA50 `from_above` | 0.0223 | 0.0180 | no |
| 10 | M6.3 `slope_pctile_21_sma_200` | 0.0242 | 0.0200 | no |
| 11 | M6.2 `extension_x_slope` SMA50 top | 0.0254 | 0.0220 | no |
| 12 | M13 `context_vix_bottom` | 0.0286 | 0.0240 | no |
| 13 | M13 `context_breadth_top` | 0.0381 | 0.0260 | no |
| 14 | M1 `above_sma_50` | 0.0521 | 0.0280 | no |
| 15 | M18 `dist_from_52w_low`@63d | 0.0667 | 0.0300 | no |
| 16 | M6.3 `slope_pctile_21_sma_20` | 0.0826 | 0.0320 | no |
| 17 | M1 `above_sma_200` | 0.0987 | 0.0340 | no |
| 18–50 | (remaining 33 cells) | 0.11–0.95 | — | no |

\*Ranks 2–4 do not individually clear their own rank's threshold — rejected only
because rank 5 does, and BH's step-up rule rejects every hypothesis up to and
including the largest rank that clears its own threshold. See `STATUS.md` for the
full discussion of why this matters for how much confidence to place in each of the
5 survivors individually.

---

## 5. Module results

Only modules actually run are detailed; the rest of DESIGN's M1–M17 list was never
attempted (out of the minimal-core scope DESIGN §12 defines) and is listed at the end
for completeness.

**Pending as of 2026-09-23**: this section, §6 (Suggestive findings), §7 (Dead-ends
register), and §8 (Cost-sensitivity appendix) still describe the study as of
2026-09-21 and have not yet been rewritten to add full narrative entries for Batch 1's
four post-termination modules (M6.1, M6.3, M7, M13). §1 and §4 above are current and
authoritative for the whole-grid FDR result and its consequences; for these four
modules' own full results in the meantime, see `STATUS.md`'s "Modules run" table and
`FINDINGS.md`'s per-cell entries — both are current as of 2026-09-23.

**M1 — Baseline state conditioning.** Above/below SMA{20,50,200} state, C0/C1/C2,
block-bootstrap. lb20/lb50 → Tier 3 (real, CI-excluding effect, fails cost). lb200 →
Tier 4 (CI touches/spans zero at both the pre-registered and a post-hoc
reversal-controlled diagnostic) — the one primary cell whose C0→C1→C2 waterfall
doesn't shrink monotonically, a genuine residual not yet explained (part of the
cross-module SMA200 watch, never resolved to a single mechanism across this study —
see `STATUS.md`; candidates are a selection effect, the 252-day-window-vs-200-day-
lookback ratio, or both). Run-length (does state *age* matter): no finding, fails the
plateau rule outright (zigzags sign at every lookback/direction).

**M4 — Distance from MA.** `dist_pct`/`dist_atr`/`dist_z` decile spreads ×
{20,50,200} × 21d. SMA20 (all 3 normalisations): Tier 3, real but fails cost. SMA50/
SMA200 (6 facets): Tier 4, CI spans zero. The 2026-09-16 Track A sweep later
generalized this module's SMA20-specific redundancy finding (`dist_pct`/`dist_atr`
0.94–0.98 correlated) to every lookback, and found `dist_z` decorrelates
meaningfully past SMA20 (0.89 at SMA50, 0.69 at SMA200) — used in this report's FDR
dedup (§4).

**M11 — Cross-sectional formulation.** Per-date rank-IC + neutralized-spread
version of M4's question, avoiding M1's C2 row-loss mechanism. Primary
(`dist_pct_sma_20`@21d): fails its own pre-registered decisive IC-floor test (killed
as a *construction*) but tiers Tier 3 as *evidence* (CI excludes zero, fails cost).
The 5-day-horizon secondary cell is the one M11 cell that clears cost outright (after
a 2026-09-10 annualization correction). Two of the module's original 7 logged cells
(the SMA20 `dist_pct`/`dist_pct_sma_50` neutralized spreads) turned out, on tracing
the code, to be exact recomputations of M4's own C2 spread — not new evidence, and
excluded from this study's final `N_tests` accordingly (§4).

**§7.5 — Level effects vs. trend effects (placebo test).** Real MA vs.
statistically-identical untraded neighbor lookbacks (SMA200 vs. {187,193,207,213},
SMA50 vs. {47,53}, EMA21 vs. {19,23}). All 3 groups killed — SMA200/SMA50 killed
trivially (the focal lookback itself shows no detectable effect); EMA21 has a real
individual effect but is indistinguishable from its own untraded neighbors (a
trend-length proxy, not a watched level — DESIGN's own predicted likelier outcome).
This report's FDR dedup pass found, additionally, that the SMA200/SMA50 groups'
focal-cell numbers are bit-exact duplicates of M4's own `dist_pct` decile spreads at
those lookbacks (§4) — a previously-undocumented cross-module overlap.

**M2 — Stack states and Minervini ablation.** Part (a): `stack_fully_bullish` killed
(adds nothing over `above_sma_50`); `stack_fully_bearish` **not** killed — real
incremental information beyond the single-MA state, clears cost cleanly, survives a
`rev_tercile`/`mom_1_0` reversal-robustness check (attenuates ~32%, remains real) —
this study's cleanest-looking Tier-3 result, and the one with the smallest p-value in
the whole grid, still fails FDR (§4). Part (b) (256-subset ablation, descriptive, no
kill criterion by design): DESIGN's own prior ("momentum criteria 6–8 dominate") does
not hold — criterion 7 (near 52-week high) is the single largest coefficient and is
*negative*; MA-stack criteria are comparable or larger. `linear_attribution` has no
control at all (not even C1) — first-pass sign/magnitude only, corroborated
independently by the 2026-09-16 Track A sweep finding the same feature
(`dist_from_52w_high`) as the single strongest raw-IC cell in a 348-cell screen.

**M5 — Touch/test/bounce behaviour.** Ex-ante first-touch-after-≥1-ATR-away event,
real MA vs. §7.5's synthetic neighbors, `P(hold)` compared via the same C1/C2
machinery. **All 6 cells (3 lookback families × 2 directions) killed, cleanly** —
every CI edge is far under the pre-registered 2pp floor (largest 0.61pp), and every
one of the 6 CIs spans zero on the corrected run. Well-powered (smallest cell: 7,257
events, 2,102 dates). The one caveat named up front: a close-only touch definition
(no intraday wick) and a design that rules out "watched exact level" vs. "unwatched
near-identical level," not "any MA region" vs. "no support/resistance at all."

**M6.2 — Slope as conditioner.** 3 of DESIGN's 4 named sub-questions (state × slope,
extension × slope, touch × slope — golden-cross × slope deferred, needs new
crossover-event machinery). 2 of 12 cells confirmed (both described above, both fail
FDR); 1 unresolved (`extension_x_slope`/SMA200/top — `InsufficientBlocksError`, traced
to a genuine 0.5%-vs-7.1% class imbalance between SMA50 and SMA200's "extended but
still falling" populations, mechanistically explained by how much more slowly a
200-day SMA turns than price moves — not a bug, and a new, more benign entry in the
cross-module SMA200-anomaly list than the prior three); 9 inconclusive (CI spans
zero, not "killed" — the CI is wide enough to still contain an economically
meaningful effect, just not a detected one). **Reversal-robustness check run
2026-09-21** (`PREREGISTRATION.md` addendum): `extension_x_slope` survives essentially
intact; `touch_x_slope` does not — its CI now spans zero once `rev_tercile` is added
to C2, the only one of the study's four Tier-3 cells where this check flips the read.
Full account: §6 below.

**M18 — 52-week high/low range as a standalone predictor (added post-termination,
2026-09-20).** Not part of the minimal-core list — promoted from two independent
post-termination Track A readings (M2's ablation criterion 7; the 2026-09-16 348-cell
IC sweep) that had never been run through this study's own C1/C2 machinery.
`dist_from_52w_high` (63d, 126d): killed cleanly, C2 CI spans zero at both horizons —
the gross negative reading both prior Track A methods found does not survive
momentum/vol/sector matching, resolving the sign question the pre-registration raised
against George & Hwang's published (opposite-direction) 52-week-high anomaly: neither
direction is real here once matched. `dist_from_52w_low` (63d, 126d): both real (C2 CI
excludes zero), strengthening with horizon exactly as the IC sweep predicted; 126d
clears cost at every reading and survives a reversal-robustness check unattenuated —
this study's fourth cost-clearing Tier-3 cell, and the one with the smallest p-value in
the entire 35-test grid (§4). Still fails FDR, by the narrowest margin in the study.

**Not attempted (out of minimal-core scope, DESIGN §12):** M3, the rest of M6 (M6.1
horse-race, M6.3 slope-magnitude humped-or-monotonic, M6.4 slope-persistence hazard,
M6.5 SMA drop-off artefact, M6.6 ribbon agreement), M7–M17 aside from M18
(including M16's "rules as linear filters" unifying diagnostic and M9's regime
conditioning). None of these were pre-registered or run; they remain open for a
future study, not silently deprioritized — DESIGN's own text names each as a distinct,
separately-scoped question.

---

## 6. Suggestive findings (Tier 3)

Per DESIGN's 2026-09-09 addition to §9.1: these are real, CI-excluding-zero,
mechanism-plausible effects, not dead ends — but per §4 above, **all four have now
been tested against the whole-grid FDR correction and none survived it.** They are
kept in their own section, not folded into the dead-ends register, because the
underlying point estimates are real and well-controlled; what changed is not the
evidence but the accounting for how many hypotheses produced it.

1. **`stack_fully_bearish`** (M2) — full detail: `FINDINGS.md`, `PREREGISTRATION.md`
   M2 entry + 2026-09-17 reversal-robustness addendum. Capped, independently of FDR,
   by DESIGN §7.3's survivorship ceiling (a weak/bearish-state bucket; this repo's
   delisted-ticker price history only runs 2024–2026) and by the missing holdout
   check.
2. **`extension_x_slope`, SMA50 top decile** (M6.2) — `FINDINGS.md` "Finding 1".
   **Reversal-robustness check run 2026-09-21**: survives essentially intact
   (−0.55%, CI still excludes zero, ~6.7% attenuation) — not explained by
   uncontrolled 1-month reversal. Remaining live caveat: the "falling" side is a
   comparatively rare subgroup (7.1% of the top-decile population), and M6.3's own
   warning about post-earnings-gap/low-float contamination of the top slope decile
   still applies.
3. **`touch_x_slope`, SMA50 `from_above`** (M6.2) — `FINDINGS.md` "Finding 2". **Does
   not survive its 2026-09-21 reversal-robustness check** — with `rev_tercile` added
   to C2 the delta attenuates ~40% and the CI now spans zero (−3.33pp, CI [−8.18pp,
   +1.25pp]) — the only one of this study's four Tier-3 cells where the confound
   check flips the read from confirmed to inconclusive. Already FDR-failed
   regardless, but the honest read is that this cell's gross number is
   substantially a short-term-reversal artifact, not a real slope-conditioning
   effect; the earlier "two independent constructions corroborate each other"
   framing against Finding 1 no longer holds. Additionally, the 5-day outcome
   window is short and the default-C2 CI spans a 5× range between its near and far
   edges — the sign was always better established than the magnitude.
4. **`dist_from_52w_low`@126d** (M18, added post-termination 2026-09-20) — full
   detail: `FINDINGS.md`'s M18 section. Like Finding 1, this cell *has* a
   reversal-robustness check (run in the same pass, not a later gap) and survives it
   essentially unattenuated. Its remaining live caveat is different from the other
   three's: `mom_tercile` (the C2 momentum match) is conceptually close to
   `dist_from_52w_low` itself, so a genuinely tighter momentum control (decile-level
   matching, or direct residualization against `mom_12_1`) has not been ruled out as
   an explanation for the residual. **The smallest p-value in the study's entire
   grid** (0.0047) and the closest individual miss against its own FDR threshold
   (1.64×) — the nearest this study came to a Tier 2 result, found only because two
   independent Track A methods flagged the candidate before it was tested, not
   because the study kept searching after termination until something turned up.

**Where this leaves the four Tier-3 cells:** three (`stack_fully_bearish`,
`extension_x_slope`/SMA50/top, `dist_from_52w_low`@126d) are real, reversal-robust
effects that fail only on multiple-testing correction — the honest "real but not
distinguishable from 35-tests-worth of chance" read DESIGN's own FDR framing intends.
The fourth (`touch_x_slope`/SMA50/`from_above`) is different in kind: its own
confound check, not just FDR, fails to clear it — the more accurate label for this
one is closer to a dead end than a near-miss.

**What would move any of these forward, if this study resumed:** a real holdout
check (2022+, still locked); a second universe tier (U2/U3); a decile-level momentum
match or direct residualization for M18's cell; and, most importantly, more data —
every one of the three reversal-robust cells is a real effect fighting a genuinely
small edge relative to the number of ways this study looked for one.

---

## 7. Dead-ends register

Per DESIGN §9.3, assembled by filtering `EXPERIMENTS.csv` to `outcome == no_effect`
(Tier 4) — format: hypothesis, why plausible, what was run, the number, effective N,
conditions to revisit. Full per-cell detail lives in `EXPERIMENTS.csv` and
`PREREGISTRATION.md`; this section is the condensed register DESIGN asks for.

**M4 — `dist_pct`/`dist_atr`/`dist_z` × SMA{50,200}, 21d (6 facets).** Hypothesis:
displacement from a slower MA predicts forward return, same shape as SMA20.
Plausible: SMA20 itself showed exactly this. Run: C2 decile spread, block-bootstrap.
Number: all 6 CIs span zero (e.g. `dist_pct_sma_200`: −0.16% [−0.53%, +0.24%]).
Effective N: 208,973–241,891 rows, 2,549–2,747 dates. **Revisit if**: a longer horizon
(the deferred 8-horizon term structure) or a real ER/vol conditioning surfaces a
signal these two slower lookbacks don't show at 21d unconditionally.

**M1 — `above_sma_200`.** Hypothesis: forward return differs above vs. below the
200-day, same shape as SMA20/50. Plausible: SMA20/50 both showed it. Run: C0/C1/C2,
block-bootstrap. Number: CI [−0.42%, +0.005%], touches zero (3D control) and spans it
(4D reversal-controlled diagnostic). Effective N: 549,243 rows, 2,747 dates, 405
tickers — the worst row loss (74.9–51.9%, depending on control set) and heaviest
all-above skew (84.5%) of the three lookbacks. **Revisit if**: the SMA200 watch (see
M6.2's structural note, §5) is ever formally audited and a selection-effect fix
changes the eligible row population materially.

**M1 — run-length (state age).** Hypothesis: a fresh state reclaim behaves
differently from a stale one. Run: 24 cells (3 lookbacks × 2 directions × 4 age
buckets), C0/C1/C2. Number: only 1 of 24 cells has a CI excluding zero, and its
immediate age-bucket neighbors are opposite-signed — a plateau-rule failure, not a
finding. Effective N: 2,483–2,747 dates across cells. **Revisit if**: never, without
a fundamentally different age-conditioning construction — this exact grid already
failed cleanly.

**§7.5 — SMA200 and SMA50 placebo groups.** Hypothesis: the SMA200/SMA50 folklore
levels show a real, watched-level-specific effect distinguishable from nearby
untraded lookbacks. Run: `dist_pct` decile spread, focal vs. 2–4 neighbors, C2,
block-bootstrap group-diff. Number: focal CI spans zero at both groups (SMA200:
[−0.53%, +0.24%]; SMA50: [−0.65%, +0.03%]) — killed at the trivial first step, no
level-specific effect to even compare against a neighbor. Effective N: same
population as the corresponding M4 facet (these cells are bit-exact duplicates,
§4/§5). **Revisit if**: never on this construction — the "trivial kill" means there's
nothing here to sharpen further; a genuinely different feature (not `dist_pct`) at
these lookbacks would be a new question, not a revisit.

**§7.5 — EMA21 vs. its neighbors.** Hypothesis: same, for the 21-EMA. Run: same
method. Number: EMA21 itself has a real effect (CI [−0.79%, −0.14%]) but is
indistinguishable from EMA19/EMA23 (both neighbor-diff CIs span zero). **Revisit
if**: a study specifically asks "is EMA slope-length special" rather than "is this
lookback watched" — this result says the latter is folklore, not the former.

**M2 — `stack_fully_bullish`.** Hypothesis: the full 4-MA bullish stack carries
information beyond `above_sma_50`. Run: standalone C2 + incremental
`block_bootstrap_group_diff` vs. M1's `above_sma_50`. Number: both span zero
(standalone [−0.20%, +0.07%]; incremental [−0.07%, +0.09%]). Effective N: 257,861
rows, 2,741 dates. Distribution-shape addendum (2026-09-15): positive hit-rate delta
(+1.21pp vs. C2) despite the flat mean, negative skew (−0.35) — a real minority of
disproportionately large losses hiding behind a slightly-more-often-winning mean; does
not change the Tier 4 verdict (shape fields carry no kill authority) but is the
exact shape DESIGN §6.11.1 was built to surface. **Revisit if**: the shape addendum
above is ever promoted to its own hypothesis (does the bullish stack's asymmetric
loss tail matter for a stop-loss-sized question) — a different question than the one
tested here.

**M5 — all 6 cells (SMA200/SMA50/EMA21 × from_above/from_below).** Hypothesis:
MAs act as dynamic support/resistance beyond a generic nearby level. Run: ex-ante
first-touch event, real MA vs. §7.5's synthetic neighbors, `P(hold)` C2 delta.
Number: every cell's CI edge is far under the 2pp floor (largest 0.61pp,
`sma200/from_below`); all 6 CIs span zero. Effective N: 7,257–30,692 events per cell,
1,845–2,640 dates. **Revisit if**: an intraday (wick-based) touch definition is
built — this study's own close-only design is the named, explicit gap that could
change the answer.

**M6.2 — 9 inconclusive cells (state × slope × 4, extension × slope × 2, touch ×
slope × 3).** Hypothesis: slope sign changes what a state/extension/touch means.
Run: C1/C2 delta of `fwd_ret_21` or `hold_flag` between slope-sign subsets, within
each restriction. Number: every CI spans zero, but several (e.g.
`touch_x_slope`/SMA200/`from_above`, edge 17.3pp) are wide enough to still hide a
real, undetected effect — logged as inconclusive, not folklore-confirmed, per this
study's own tier-4 convention (CI-includes-zero ≠ "proven negligible" the way M5's
cells, with their tight sub-2pp edges, are). **Revisit if**: a larger event count
(a longer sample, or a coarser slope-sign definition trading precision for power)
narrows these CIs enough to actually distinguish signal from noise either way.

**M18 — `dist_from_52w_high` × {63d, 126d} (2 cells, added post-termination
2026-09-20).** Hypothesis: position near the trailing 252-day high predicts forward
return (either direction — see PREREGISTRATION.md's own discussion of the
George-&-Hwang sign question). Plausible: two independent, uncontrolled Track A
readings (M2's ablation criterion 7, the 2026-09-16 IC sweep) both found a real-
looking gross effect, negative-signed, and the second of these was the strongest cell
in a 348-cell grid. Run: C2 (`mom_tercile`/`vol_tercile`/`sector`-matched) decile
spread, block-bootstrap. Number: both CIs span zero (63d: −0.38% [−1.51%, +0.73%];
126d: −0.67% [−2.63%, +1.21%]) — the gross C1 reads (−1.93%, −4.03%) were real-looking
but entirely momentum re-encoded, the sharpest C1→C2 collapse in this study (a real
effect at C1 vanishing completely at C2, not merely shrinking). Effective N:
1,095,030/1,069,515 rows, 2,706/2,643 dates, 405 tickers. **Revisit if**: a decile-level
(not tercile) momentum match, or a longer horizon still, ever suggests the gross
reading wasn't fully explained — no evidence for that here, but the tercile-vs-decile
coarseness is a real, named gap (same one every C2 test in this study carries).

---

## 8. Cost-sensitivity appendix

Convention throughout: `signals_per_year × 10bps round-trip` (U1), turnover measured
directly off the panel, never assumed (`stats/costs.py`).

| cell | signals/yr | hurdle | point (ann.) | near CI edge (ann.) | clears? |
|---|---|---|---|---|---|
| M4 `dist_pct_sma_20` | ~24.65 | 2.465%/yr | −5.57% | −1.64% | fails |
| M4 `dist_atr_sma_20` | ~26.19 | 2.619%/yr | −4.46% | −1.12% | fails |
| M4 `dist_z_sma_20` | ~26.17 | 2.617%/yr | −4.48% | −1.42% | fails |
| M1 `above_sma_20` | 30.38 | 3.038%/yr | −2.58% | −0.95% | fails |
| M1 `above_sma_50` | 17.99 | 1.799%/yr | −2.20% | −0.37% | fails |
| M1 `above_sma_200` | 7.79 | 0.779%/yr | n/a | CI touches zero before cost applies | not tested |
| M11 `dist_pct_sma_20`, 21d | ~24.63 | 2.463%/yr | −6.05% | −0.51% | fails |
| M11 `dist_pct_sma_20`, 5d | ~24.66 | 2.466%/yr | −10.81% (neutralized/C2 spread point, annualized ×50.4) | −3.45% | **clears** |
| M2 `stack_fully_bullish` | ~14.26 | 1.426%/yr | −0.76% | CI spans zero | fails |
| M2 `stack_fully_bearish` | 2.86 | 0.286%/yr | +5.68% | +1.93% | **clears** |
| M2 `stack_fully_bearish` (reversal-controlled) | 2.86 | 0.286%/yr | +3.83% | +0.53% | **clears** |
| M6.2 `extension_x_slope`/SMA50/top | 8.06 | 0.806%/yr | −7.11% | −2.10% | **clears** |
| M18 `dist_from_52w_low`, 63d | 8.246 | 0.825%/yr | +3.82% | +0.51% | fails |
| M18 `dist_from_52w_low`, 126d | 8.336 | 0.834%/yr | +5.01% | +2.21% | **clears** |
| M18 `dist_from_52w_low`, 126d (reversal-controlled) | 8.336 | 0.834%/yr | +5.29% | +3.14% | **clears** |
| M5, M6.2 hold-rate cells | n/a | n/a | n/a | n/a | not applicable — mechanism questions, no cost annotation by pre-registered convention |

**Reading**: every cell that clears cost outright also either fails FDR
(`stack_fully_bearish`, `extension_x_slope`/SMA50/top, `dist_from_52w_low`@126d) or is
a secondary/shorter-horizon cell with its own live confound (M11's 5-day cell — a
horizon short enough that the ~50-round-trip/year turnover hurdle is easiest to clear
is also the shape a short-term-reversal generator would produce, per
`mom_1_0`/`rev_tercile` not being in this cell's C2 spec — flagged in
`PREREGISTRATION.md`'s own 2026-09-10 correction addendum). `dist_from_52w_low`@126d
is the one exception to the "uncontrolled for reversal" pattern among the
cost-clearing cells — its own reversal-controlled reading clears just as cleanly, not
weaker. **No cell in this study clears both cost and FDR.**

---

## 9. Reproducibility appendix

**Universe/window (U1):** S&P 500 constituents as of 2021-12-31, filtered to full
`bars_1d` coverage 2010-06-01 → 2021-12-01 (`data.py::sp500_full_coverage_tickers`) —
405 tickers, 1,222,605 panel rows, 2010-01-04 → 2021-12-31.

**Holdout boundary:** 2021-12-31, enforced at data-load time (`load_bars(...,
as_of=...)`), never bypassed in this study.

**Feature panel:** `data/features/moving_averages/ma_panel/` (partitioned parquet by
year), built by `src/signals/moving_averages/features/panel.py::build_panel`,
reproducible via `python -m src.signals.moving_averages.cli build-panel --universe
sp500`. Placebo/synthetic-neighbor panel (§7.5, M5): `features/placebo_ma.py::
build_placebo_panel` (not cached — rebuilt per run, deterministic given the same DB
snapshot).

**Seeds:** every block-bootstrap call in this study used `seed=0` unless a module
explicitly varied it for a robustness check (none did). `n_boot=500`, `ci=0.90`
throughout. `block_length=42` for 21d-horizon return cells (2× horizon, DESIGN §6.2),
`block_length=10` for touch-event cells (M5, M6.2's `touch_x_slope`), `block_length=
126`/`252` for M18's 63d/126d cells (same 2× horizon convention, the first module in
this study to test a horizon other than 21d/5d/63d already covered by M11).

**Synthetic validation gate:** `python -m src.signals.moving_averages.cli
validate-synth` — must pass before any result here is trusted (CLAUDE.md). Passing
as of every commit in this study's history (`tests/test_moving_averages_synthetic_validation.py`
is part of the standard `pytest tests/test_moving_averages_*.py` suite, ~197 tests
as of 2026-09-23, run and green before every commit in this study).

**Full pre-registered grid, `N_tests`:** 50 as of 2026-09-23 (deduplicated; see §4 —
31 from the minimal-core list, +4 from M18, +15 from Batch 1). Per-module raw declared
counts and the full dedup reasoning: `STATUS.md`'s "Whole-grid FDR pass" section.

**Every result's exact numbers, provenance, and commit:** `EXPERIMENTS.csv` (89
logged rows: 86 across 12 modules + 3 whole-grid-FDR-pass summary rows, as of
2026-09-23),
cross-referenced to `PREREGISTRATION.md`'s per-module entries (hypothesis/kill-
criterion/scope, written and committed before each analysis ran) and `FINDINGS.md`
(full narrative for every Tier 1–3 cell). `git log` on
`docs/features/moving-averages/` and `src/signals/moving_averages/` gives the
complete, dated build history.

**What this study did not build, and would need to before any Tier-3 cell here could
reach Tier 1/2:** a second/third universe tier (U2/U3 — DESIGN §3.2, blocked in Phase
0 on thin point-in-time market-cap data); a real holdout check (2022+, still locked);
White's Reality Check / Hansen's SPA for the horse-race-shaped questions this study
never got to (M8/M9, not attempted); a Deflated Sharpe ratio for any backtest-shaped
output (none of this study's cells were ever framed as a backtest); for M18
specifically, a decile-level (not tercile) momentum match or a direct residualization
of `dist_from_52w_low` against `mom_12_1`, given how conceptually close the two are by
construction.
