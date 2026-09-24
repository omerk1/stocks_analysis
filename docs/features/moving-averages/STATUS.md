# Moving-averages study — status

One row per module actually run (Track B, pre-registered and executed). Not a
duplicate of `docs/features/moving-averages/PREREGISTRATION.md` — that file is the
frozen pre-registration text per module; this file is the cross-module scoreboard, kept
current, for "what do we actually know and what's still open." Full detail always lives
in `PREREGISTRATION.md` (per-module narrative) and `EXPERIMENTS.csv` (per-cell numbers,
every tested facet, whatever it found); this file points there rather than re-deriving.

**Timeline (numbers live in the table and sections below, not repeated here):**
- **2026-09-17** — minimal-core list complete (DESIGN §12: M1, M2, M4, M5, M6.2, M11,
  §7.5); whole-grid FDR pass run (N=31, 0 survivors); termination condition reached
  ("Study-level termination" below); `REPORT.md` written.
- **2026-09-20** — M18 added post-termination (DESIGN §1.5); FDR re-run (N=35, still
  0 survivors, but M18's `dist_from_52w_low`@126d is the closest individual miss in
  the study to that point).
- **2026-09-21** — M6.2's outstanding reversal-robustness check run: Finding 1
  (`extension_x_slope`) survives; Finding 2 (`touch_x_slope`) does not (`FINDINGS.md`).
- **2026-09-22/23** — Batch 1 (M6.1, M6.3, M7, M13) added post-termination
  (`HANDOVER.md`), merged, and consolidated into a third FDR re-run (N=50). **First
  survivors in the study's history (5 of 50 at q=0.10, 1 at q=0.05), and the first
  Tier-2 result** (`slope_pctile_21_sma_50`/M6.3, resolved via a same-day tail
  decomposition — see "Whole-grid FDR pass" below for the full account).

## Modules run

| Module | Run order & date | Tier & headline result | N_tests / independence / correction | Cost hurdle & verdict | Why chosen, what was known then | Numbers live in |
|---|---|---|---|---|---|---|
| **M4** — Distance from MA | 1st, 2026-09-08 (`0aa13c8`, PR #61) | **Tier 3**: `dist_pct`/`dist_atr`/`dist_z` × SMA20 only — CI excludes zero, directionally consistent, fails cost. **Tier 4**: all 6 SMA50/SMA200 facets — CI includes zero. | Declared grid: 90 bucket-level cells (3 normalisations × 3 lookbacks × 10 deciles); kill criterion evaluated at 9 facet-level (normalisation × lookback) tests. **Not deduplicated at the time it ran** — the SMA20 independence check (median per-date Spearman 0.94–0.98 between `dist_pct`/`dist_atr`/`dist_z`, found 2026-09-09 during M11 prep) was never run against M4's own grid. The same non-independence this found for SMA20 likely also holds at SMA50/SMA200, unchecked. No FDR run (deferred to whole-grid pass — see below). | Originally ad hoc (`entries_per_ticker_year`, entries-only): ~25.32/ticker-yr per leg, ~50.64/yr combined → conservative hurdle ~5.06%/yr, optimistic ~2.53%/yr. CI-low net-negative under both → **fails cost**. Reconciled 2026-09-09 against `costs.py::signals_per_year` (entry+exit convention, the repo standard going forward): 24.646/yr combined → 2.465%/yr hurdle. CI-low (1.6395%) still misses it. **Verdict unchanged under either convention.** | Promoted from Track A M0.1 (descriptive atlas) — 4 of 5 candidate observations pointed at distance-from-MA normalisation/shape questions. Ran before M1 only because Track A exploration surfaced it first, not because it outranked M1 on the minimal-core list. | `notebooks/moving_averages_distance_from_ma.ipynb` (full computation); `PREREGISTRATION.md` M4 entry + two 2026-09-09 addenda (NaN-fix check, turnover reconciliation); `EXPERIMENTS.csv` (all 9 facets, one row each). |
| **M1** — Baseline state conditioning | 2nd, 2026-09-09 (`87efc3d` PR #62, fixed `6cdee5b` PR #63, `75e42ce` PR #64) | **Tier 3**: lb20, lb50 (above/below state) — CI excludes zero, fails cost. **Tier 4**: lb200 — CI touches/spans zero at both the 3D and 4D control sets. **Run-length secondary layer: no finding** — fails the plateau rule (§6.7), zigzags sign at every lookback/direction. | Declared grid: 30 cells (3 lookbacks × [2 state + 2 directions × 4 run-length buckets]). **Primary cells (6: above/below × 3 lookbacks) are exact algebraic mirrors under C1/C2 by construction — 3 independent numbers, not 6**, found and verified bit-exact during this module's own run. The 24 run-length cells are nested inside their parent state cell (not independent additional tests). No FDR run (deferred — see below). | `stats/costs.py::signals_per_year` (entry+exit convention, the same tool later used to reconcile M4) — this is the module `costs.py` was built for. 30.377 / 17.990 / 7.785 flips/ticker-yr → 3.038% / 1.799% / 0.779%/yr hurdles at lb20/50/200. lb20: CI and point both miss. lb50: point clears at 3D, CI-bound does not (worse at 4D). lb200: CI touches/spans zero at both control sets — **fails regardless of its own (lowest) hurdle being technically clearable on point estimate alone.** | DESIGN §12's own recommended minimal-core *first* module and `docs/backlog.md`'s designated next module. Run second only because Track A happened to point at distance-from-MA first — explicitly not deprioritized on the merits (own entry's "Promoted from" note). | No notebook — `tests/test_moving_averages_baseline_state.py` + `src/signals/moving_averages/modules/baseline_state.py`; `PREREGISTRATION.md` M1 entry (all numbers reported directly in prose, cross-verified against `costs.py` — see the reconciliation note in this file's own text and in M4's addendum above); `EXPERIMENTS.csv` (3 primary lookbacks + 1 run-length summary row). |
| **M11** — Cross-sectional formulation | 3rd, 2026-09-09 (code + raw numbers, PR #67); tiered 2026-09-10 (no new PR — see the PR-boundary note below); cost-verdict correction + `dist_pct_sma_50`@21d moved to Tier 4, both 2026-09-10 (see below) | **Tier 3** (4 of 7 cells): primary `dist_pct_sma_20`@21d, `dist_pct_sma_20`@5d, and the `dist_atr`/`dist_z` companions — CI excludes zero, real weak effect. **3 of these 4 fail cost; `dist_pct_sma_20`@5d clears it** (corrected 2026-09-10 — see below). **Tier 4** (3 of 7): `dist_pct_sma_200`@21d, `dist_pct_sma_20`@63d (CI spans zero on both IC and spread), and `dist_pct_sma_50`@21d (moved 2026-09-10 — see below). **Primary cell additionally failed its own pre-registered decisive test** (`decisive_test_status=failed`, IC-floor sub-test) — killed as a *construction* ("not worth the added machinery over M4"), tiered as *evidence* per DESIGN §9.2's 2026-09-10 addendum (kill and tier are now separate axes, recorded separately, never collapsed into one label). **Tier is unchanged for the cost-viable cell too** — Tier 3 is capped by missing FDR/holdout infrastructure, not by cost; clearing cost doesn't promote it. **Four of these seven cells' neutralized-spread number is not independent of M4** — see the non-independence note below. | Declared grid: 5 (1 primary + 4 secondary); `dist_atr`/`dist_z` companions excluded up front (0.94–0.98 correlated with `dist_pct` at SMA20, found during this module's own pre-registration) — already deduplicated at declaration. | Primary cell combined hurdle: 24.635/yr flips → 2.463%/yr (10bps/rt, `costs.py`). Spread (C1), 21d→annualized: point −0.50% (×12=−6.05%, **clears**), far edge −10.88% (clears), **near-zero edge −0.51% (misses)**. Sector/vol/momentum-neutralized spread: point −5.57% (clears), near-zero edge −1.64% (misses, closer to clearing than C1's). **Verdict: fails on the CI-based test in both control layers**, same structural shape as M1's cost failures, at a proportionally larger gross magnitude. | Chosen over M2/M5/M6.2 specifically because its control design (per-date cross-sectional stat, no stratify-and-drop) sidesteps the row-loss mechanism that hit M1's C2 layer, rather than inheriting it. | `PREREGISTRATION.md` M11 entry + 2026-09-10 "Result and feasibility addendum" + 2026-09-10 correction addenda; `EXPERIMENTS.csv` (7 rows, tiered, `counted_in_n_tests`/`decisive_test_status` columns, `cost_verdict` filled in for all 7). |
| **§7.5** — Level effects vs. trend effects (placebo test) | 4th, 2026-09-12 (`873c112`, PR #73, merged) | **Tier 4, all 3 groups — folklore confirmed, no group survives.** SMA200 vs {187,193,207,213}: killed at the trivial step, focal's own C2 CI spans zero (no detectable effect at SMA200 or any of its 4 neighbors). SMA50 vs {47,53}: **same trivial mechanism** — focal C2 CI spans zero (`[-0.006533,+0.000326]`); an earlier in-conversation summary of this cell mischaracterized it as "real effect killed by neighbor-indistinguishability," corrected against the raw output before logging. EMA21 vs {19,23}: the one group with a real, individually CI-excluding-zero focal effect (`-0.004585 [-0.007898,-0.001413]`) — killed at the intended step, indistinguishable from both untraded neighbors (both `diff_g,n` CIs span zero, and both neighbors show essentially the same effect EMA21 does). | 3 group-level tests declared and run as 3 (not the 11 individual lookback cells) — no dedup issue, declared correctly from the start. | Not applicable — no group reached "confirmed," so the pre-registered cost step (CLAUDE.md invariant #8) never fires for any of the three. | Cheapest, highest-signal item left on the minimal-core list (DESIGN §7.5: "the most elegant test... cheap to run either way"); motivated directly by M11's SMA20 cost-viable reading and the SMA200 watch below. | `PREREGISTRATION.md` §7.5 entry; `EXPERIMENTS.csv` (3 rows: `placebo_sma200_h21`, `placebo_sma50_h21`, `placebo_ema21_h21`). |
| **M2** — Stack states and Minervini ablation | 5th, 2026-09-13 (`44f5589`, branch `analysis/m2-stack-minervini`, PR pending) | **Part (a): module not killed — one of two primary cells survives.** `stack_fully_bullish`: **Tier 4**, no standalone effect (C2 CI spans zero) and the incremental-vs-M1 test is killed (diff CI `[-0.066%,+0.086%]`, both endpoints under the 0.10% floor — the full stack adds nothing over `above_sma_50` on the bullish side). `stack_fully_bearish`: **Tier 3**, real standalone effect (C2 `+0.474%` CI `[+0.161%,+0.776%]`) **and** the incremental test is *not* killed (diff CI `[+0.419%,+1.740%]`, both endpoints far past 0.10% — the stack adds real info beyond `above_sma_50` on the bearish side), clears cost cleanly at every reading (0.286%/yr hurdle vs. point +5.68%/yr, near edge +1.93%/yr) — but capped at Tier 3 twice over: missing FDR/holdout infra (every Tier-3 cell in this study) **and** DESIGN §7.3's survivorship cap (it's a weak/bearish-state bucket, delisted-data ceiling). Confound checked 2026-09-17 (reversal-robustness addendum): adding `rev_tercile`/`mom_1_0` to the C2 match set attenuates the standalone delta by ~32% (`+0.4675%`→`+0.3188%`) but the CI still excludes zero and clears cost at every reading — reversal explains part, not all, of the gross number; tier unchanged (still capped by FDR/holdout infra + §7.3 survivorship, not by this confound). **Part (b) (ablation, no kill criterion by design): DESIGN's own prior does not hold** — criteria 6–8 don't dominate positively; criterion 7 (near 52w high) is the single largest coefficient and is *negative*; MA-stack criteria 4/5 are comparable-or-larger. Corroborated by the primary-cell sign (all-8-true subset worse than all-8-false). Caveat: `linear_attribution` has no control at all, not even C1 date-matching — first-pass sign/magnitude only. | Part (a): 2 primary cells declared, run as 2. Part (b): 8 per-criterion attribution coefficients declared as the `N_tests` contribution (not the 256 subsets — DESIGN's own attribution framing). | `stack_fully_bullish`: fails both point and CI. `stack_fully_bearish`: clears at every reading (see above). | DESIGN's own words: "the highest expected-value module in the doc," kill: none on the ablation. Chosen alongside §7.5 to make parallel progress toward the minimal-core list. | `PREREGISTRATION.md` M2 entry + 2026-09-13 wording-correction and control-tier-caveat addenda; `FINDINGS.md` (`stack_fully_bearish` full entry); `EXPERIMENTS.csv` (10 rows: 2 primary cells + 8 ablation coefficients). Independently reproduced end-to-end against the real DB (full 408-ticker panel rebuild) by the coordinating session before logging — primary-cell numbers match the agent's report to the reported precision. |
| **M5** — Touch/test/bounce behaviour | 6th, 2026-09-17 | **Tier 4, all 6 primary cells killed — support/resistance from MAs is folklore, cleanly.** 3 groups (SMA200, SMA50, EMA21) × 2 directions (`from_above`/`from_below`) vs. §7.5's own synthetic-neighbor MAs: every cell's `max(\|ci_low\|,\|ci_high\|)` is far under the pre-registered 2pp kill floor (largest: 0.61pp at `sma200/from_below`, most sit at 0.14–0.27pp) — not a borderline call, and every one of the 6 CIs spans zero on the corrected, canonical run. Well-powered (smallest cell: 7,257 events, 2,102 dates, 402 tickers), not a "too thin to tell" null. Caveats named in full in `PREREGISTRATION.md`: close-only touch definition (no intraday wick — DESIGN's own deferred sub-question); the synthetic-neighbor design rules out "watched exact level" vs. "unwatched near-identical level," not "any MA region" vs. "no support/resistance at all" (same scope limit §7.5 already carries). **Execution note, caught before logging, not a result-affecting bug**: a first run of the real-data script omitted `start="2010-01-01"`, pulling full ticker history back to 1970 for some names — the holdout boundary was never crossed, but the dev-window scope was wrong; caught, fixed, and rerun before anything was logged. | 6 primary cells (3 groups × 2 directions) declared and run as 6 — same "group is the unit of inference" convention as §7.5, whose synthetic-neighbor machinery this module reuses directly rather than re-deriving. No FDR run yet (deferred — see below). | Not applicable — mechanism question (does the level itself matter), not a tradeable-edge question, same convention as §7.5. | Last of the minimal-core list's touch/support-resistance question (DESIGN §5) — decision to continue past M2's saturation-watch note (below) rather than stop, made 2026-09-17. New machinery: `features/touch.py` (ex-ante event extraction — away/touch/direction/outcome), reusing `features/state.py`'s run-length primitives and §7.5's own synthetic-neighbor groups; `modules/touch_bounce.py` reuses the existing C1/C2 block-bootstrap infrastructure unchanged (a hold/no-hold flag is just another `value_col`). | `PREREGISTRATION.md` M5 entry + 2026-09-17 "Result" section; `EXPERIMENTS.csv` (6 rows); no `FINDINGS.md` entry (Tier 4). |
| **M6.2** — Slope as conditioner | 7th (last of minimal core), 2026-09-17 | **2 of 12 cells confirmed (CI excludes zero) — the study's clearest new signal since M2's `stack_fully_bearish`.** `extension_x_slope`/SMA50/top-decile: **Tier 3**, C2 `−0.592%` CI `[−1.047%,−0.175%]`, clears cost cleanly (0.806%/yr hurdle vs. point −7.11%/yr, near edge −2.10%/yr). `touch_x_slope`/SMA50/`from_above`: **Tier 3**, C2 `−5.75pp` CI `[−10.22pp,−1.94pp]`, cost n/a (mechanism read, M5's own convention). **Both originally read as saying the same thing from two independent constructions (a decile restriction, an event-based restriction): an actively rising 50-day, conditional on already being extended/testing, predicts *worse* near-term outcomes than the same setup on a falling 50-day** — counter to the "uptrend makes a pullback safer" folklore. **Reversal-robustness check run 2026-09-21 (`PREREGISTRATION.md` addendum): `extension_x_slope` survives essentially intact (−0.5503%, CI excludes zero, ~6.7% attenuation); `touch_x_slope` does not (−3.33pp, CI now spans zero, ~40% attenuation)** — reversal substantially explains Finding 2 specifically, weakening (not eliminating) the two-cells-corroborate-each-other reading; full account in `FINDINGS.md`'s Finding 2 entry. **1 cell unresolved** (`extension_x_slope`/SMA200/top): `InsufficientBlocksError` — only 0.5% of that cell's population has `slope_sign=False`, vs. 7.1% at SMA50 — a data-scarcity finding, mechanistically explained (a 200-day SMA moves far slower than price) not a new SMA200 anomaly. **9 of 12 cells inconclusive** (CI spans zero, edge wide enough to still contain a meaningful effect — not "killed," just not detected). | 12 primary cells (3 sub-questions × 2 lookbacks × 2 facets) declared and run as 12 — no dedup collapse expected (rising-within-above and rising-within-below are different row populations, not complements), flagged for the FDR pass to actually verify. | Only sub-question 2 (extension × slope) implies a tradeable claim; triggered for the one confirmed cell there (see above) — clears at every reading. Sub-questions 1/3 not applicable / not triggered. | DESIGN's own words: "the most likely Tier-1 producer in the whole slope module" — last item on the minimal-core list (DESIGN §12). Golden-cross × slope (DESIGN's 4th named sub-question) deferred — needs new crossover-event-detection machinery, a real build not a faceting exercise. | `PREREGISTRATION.md` M6.2 entry + 2026-09-17 "Result" section + 2026-09-21 reversal-robustness addendum; `FINDINGS.md` (2 entries, "Finding 1"/"Finding 2", both updated 2026-09-21); `EXPERIMENTS.csv` (14 rows: 12 primary + 2 reversal-robustness). |
| **M18** — 52-week high/low range | 8th, post-termination, 2026-09-20 | **Not part of the original minimal-core list** (DESIGN §12) — added after the study's own termination condition had already been reached (below), via DESIGN §1.5's porous-scope rule, promoted from two independent post-termination Track A readings (M2's ablation criterion 7; the 2026-09-16 348-cell IC sweep) that had never been run through this study's own C1/C2 machinery. `dist_from_52w_high`: **Tier 4, killed cleanly at both horizons** (63d CI `[−1.514%,+0.734%]`, 126d CI `[−2.632%,+1.208%]`, both span zero) — resolves the sign question this module's own pre-registration flagged (M2's ablation and the IC sweep both read this feature negative; George & Hwang's published anomaly reads the opposite direction; neither survives momentum matching, so there's no real effect here in either direction). `dist_from_52w_low`: **2 of 2 cells confirmed.** 63d: Tier 3, C2 `+0.956%` CI `[+0.128%,+1.843%]`, fails cost (near edge +0.51%/yr vs. 0.825%/yr hurdle). 126d: **Tier 3, C2 `+2.504%` CI `[+1.104%,+4.017%]`, clears cost at every reading** (near edge +2.21%/yr vs. 0.834%/yr hurdle) — this study's **third** cost-clearing Tier-3 cell, alongside `stack_fully_bearish` (M2) and `extension_x_slope`/SMA50 (M6.2). Both `dist_from_52w_low` cells survive a `rev_tercile`-augmented C2 essentially unattenuated. | 4 primary cells (2 features × 2 horizons) declared and run as 4 — independence checked directly before trusting the grid (per-date median Spearman(`dist_from_52w_high`, `dist_from_52w_low`) = 0.4677, well short of M4's 0.94–0.98 redundancy bar). All 4 (not just survivors) added to the whole-grid FDR re-run below, per this study's own established practice of correcting across everything tested. | `dist_from_52w_low`/126d: 0.834%/yr hurdle vs. point +5.01%/yr, near edge +2.21%/yr, far edge +8.03%/yr — **clears at every reading.** `dist_from_52w_low`/63d: 0.825%/yr hurdle vs. point +3.82%/yr (clears), near edge +0.51%/yr (**fails**). `dist_from_52w_high` (both horizons): not tested, CI spans zero before cost applies. | Two independent post-termination Track A signals (an uncontrolled OLS attribution coefficient, a raw IC screen) flagging the same feature family as the strongest unexplored candidate in the whole study — cheap to test properly (existing M11 machinery reused unchanged), passed the promotion-gate subperiod re-slice before being pre-registered. | `PREREGISTRATION.md` M18 entry + 2026-09-20 "Result" section; `FINDINGS.md` (2 new entries, both `dist_from_52w_low` cells); `EXPERIMENTS.csv` (7 rows: 4 primary + 2 reversal-robustness + 1 FDR-summary); DESIGN.md's M18 section. |
| **M6.1** — Slope vs. momentum horse race | 9th, post-termination Batch 1, 2026-09-22 (PR #81) | **Inconclusive, not killed, not confirmed.** 4 lookbacks' decisive incremental-IC test (slope residualized against `mom_12_1`), all 4 CI-spans-zero, no consistent sign across lookbacks (−0.016/+0.002/−0.014/+0.001) — not distinguishable from "slope is redundant with momentum," but not proven so either under this study's own CI discipline. One clean, actionable number outside the kill criterion: `slope_log_21_sma_200`'s turnover is ~3.7× lower than `mom_12_1`'s (0.902 vs 3.340 flips/ticker-yr). | 4 declared, run as 4 — cross-lookback correlation of `slope_log_21` checked directly during the 2026-09-23 whole-grid consolidation (median per-date Spearman 0.35–0.88 across all 6 pairs), below this study's own 0.89 non-redundancy bar (M11 precedent), kept independent. | Not applicable — diagnostic/redundancy question, not a tradeable claim on its own. | Post-termination "Batch 1" module (parallel with M6.3/M7/M13), scoped from DESIGN's own remaining module list per the 2026-09-21 triage (`HANDOVER.md`). | `PREREGISTRATION.md` M6.1 entry; `EXPERIMENTS.csv` (4 rows); no `FINDINGS.md` entry (Tier 4). |
| **M6.3** — Slope magnitude: monotonic or humped? | 10th, post-termination Batch 1, 2026-09-22 (PR #82) | **U-shaped, not humped, at all 3 SMA lookbacks — DESIGN's own prior does not hold.** SMA50 (Tier 3, C2 `−0.248%` CI `[−0.354%,−0.153%]`) and SMA200 (Tier 3, C2 `−0.193%` CI `[−0.337%,−0.056%]`) clear cost at every reading; SMA20 clears its own kill floor but fails cost and fails its own large-move-exclusion companion. **Reversal-robustness (2026-09-22): SMA50 survives essentially unattenuated (if anything strengthened, +13.9%); SMA200 does not (80.5% attenuation, CI now spans zero — best read as a reversal artifact).** **Whole-grid FDR (2026-09-23): SMA50 survives — the first cell in this study's history to clear BH correction**, p=0.00005 against a rank-1 threshold of 0.0020, also the only one of the pass's 5 survivors to clear q=0.05. **Promoted to Tier 2 (2026-09-23) — the first Tier-2 result in this study's history**, once a same-day rising-tail-only vs. falling-tail-only decomposition (rising `−0.254%` CI `[−0.429%,−0.085%]`; falling `−0.244%` CI `[−0.413%,−0.096%]`, nearly identical) directly ruled out the survivorship-bias concern the FDR consolidation had raised — see `FINDINGS.md`'s own addendum for the full reasoning. | 3 primary cells (SMA20/50/200) declared and run as 3; 3 large-move-exclusion companions and 2 reversal-robustness rows excluded from `N_tests` (robustness checks on the same hypotheses, not independent tests). | SMA50: 0.769%/yr hurdle vs. point −2.976%/yr, near edge −1.833%/yr — clears at every reading. SMA200: 0.382%/yr hurdle vs. point −2.313%/yr, near edge −0.668%/yr — clears at every reading. SMA20: fails (near edge misses). | Post-termination "Batch 1" module. Substituted `slope_pctile_21` for DESIGN's literal `slope_atr_21` ask (CLAUDE.md invariant #7 conflict) and a large-single-day-move proxy for the earnings-exclusion companion (no earnings table exists). | `PREREGISTRATION.md` M6.3 entry + 2026-09-22 reversal-robustness addendum + 2026-09-23 whole-grid-FDR addendum; `FINDINGS.md` (3 entries: SMA20/50/200); `EXPERIMENTS.csv` (9 rows: 3 primary + 3 excl-large-move + 2 reversal-robustness + this module's share of the FDR summary). |
| **M7** — Ribbon compression / expansion | 11th, post-termination Batch 1, 2026-09-22 (PR #84) | DESIGN's literal "compression → vol expansion" hypothesis **killed cleanly** on forward realized vol (both C2 readings, with and without the `vol_tercile` match). **`ribbon_direction_magnitude` confirmed** (Tier 3): compression predicts a larger forward 21d `\|return\|` (magnitude, not signed direction) — C2 `−0.2471%` CI `[−0.3976%,−0.0927%]`, clears cost at every reading, survives its own reversal-robustness check (2026-09-23, +7.6%, if anything strengthened). Trend-conditional and unconditional signed-direction cells are both inconclusive — the trend-conditional cell notably does **not** confirm DESIGN's own stated prior that it should show more signal than the unconditional cell. **Whole-grid FDR (2026-09-23): `ribbon_direction_magnitude` survives** (swept in by the step-up rule, p=0.0077) but **not promoted to Tier 2** — capped by its own magnitude-vs-signed-return actionability gap, independent of FDR status. | 5 declared, deduplicated to 4 for the whole-grid pass: the two vol-expansion readings (with/without `vol_tercile` match) are the same hypothesis tested two ways, an explicit internal-consistency check per this module's own pre-registration, merged into 1. | `ribbon_direction_magnitude`: 0.3163%/yr hurdle vs. point −2.97%/yr, near edge −1.11%/yr — clears at every reading, with the magnitude caveat named above. | Post-termination "Batch 1" module. Caught and fixed two real `skipna=True` bugs in new label functions (`ribbon_width`, `forward_realized_vol`) before trusting any real-panel numbers. | `PREREGISTRATION.md` M7 entry + 2026-09-23 reversal-robustness addendum; `FINDINGS.md` (1 entry, `ribbon_direction_magnitude`, + 2026-09-23 FDR addendum); `EXPERIMENTS.csv` (6 rows: 5 primary + 1 reversal-robustness). |
| **M13** — Context conditioning | 12th, post-termination Batch 1, 2026-09-22 (PR #83) | Sliced M1's `above_sma_200` C2 delta by VIX-percentile and breadth-percentile regime terciles. 2 of 4 cells (`vix`/bottom, `breadth`/top) clear zero-exclusion and cost, barely — but all 4 point estimates cluster tightly around M1's own whole-sample sign and magnitude, read by this module's own write-up as "probably the same weak baseline effect exposed by regime-slicing, not a real interaction," not oversold. Tiered 3 mechanically (this study's own convention), with that skepticism carried explicitly in the prose. Not part of this pass's 5 whole-grid FDR survivors (all 4 cells miss, ranks 12/13/37/43 of 50). | 4 declared, run as 4 — disjoint VIX/breadth tercile subpopulations of the same underlying `above_sma_200` cell, treated as a restricted-subpopulation test (same convention as M6.2's within-restriction cells), not a literal duplicate of M1's own already-counted cell. | `vix`/bottom: 0.689%/yr hurdle vs. point −3.82%/yr, near edge −0.87%/yr — clears, barely. `breadth`/top: 0.640%/yr hurdle vs. point −4.66%/yr, near edge −0.88%/yr — clears, barely. | Post-termination "Batch 1" module. Earnings/index-membership/sector-momentum sub-questions deferred (no earnings-date table exists; index-membership and sector-momentum facets deferred as a first-slice cut). | `PREREGISTRATION.md` M13 entry; `FINDINGS.md` (2 entries, `vix`/bottom and `breadth`/top, both carrying the "argue against" reasoning in full); `EXPERIMENTS.csv` (4 rows). |
| **M3** — Crossovers: state vs transition | 13th, post-termination Batch 2, 2026-09-23 (PR #89, reverted via #92 during a process/branch-protection review, restored via #93) + spread-velocity addendum, 2026-09-24 (PR #95) | **Clean-to-mostly-clean null across the whole crossover grid — DESIGN's own skeptical prior (~65% likely) holds.** All 10 primary cells (5 fast/slow pairs × golden/death: sma50/200, sma20/50, sma50/150, ema10/20, ema8/21) have CI spanning zero. The literal module-level kill criterion (`edge<0.15%` on every cell) doesn't formally fire only because the 3 SMA pairs' thinner event counts (3,025–3,840) leave a wider CI than the 0.15% floor — not because they show more signal than the EMA pairs (23,782–26,081 events), which do clear the kill floor cleanly: all 10 point estimates sit within ±0.08% of each other regardless. 4 quality facets (slope-sign, price-position on `sma_50/sma_200`/golden) and 2 spread-velocity facets (2026-09-24 addendum, correcting an over-broad initial scope cut that had bundled "spread velocity" in with DESIGN's genuinely ill-defined "cross angle" under M6.7's reasoning — velocity is scale-invariant by construction, angle isn't) all CI-span-zero too. Tier 4 throughout, no `FINDINGS.md` entry. | 16 declared, run as 16 — 10 primary + 4 quality facets + 2 spread-velocity facets, all distinct restricted subpopulations of the state-matched crossover-vs-control comparison (golden/death, slope-sign, price-position, and spread-velocity-sign are four different ways of partitioning event populations, not the same statistic recomputed). Contributes 16 to the 2026-09-24 whole-grid FDR re-run (N=79). | Not applicable — every primary cell's CI spans zero before cost is evaluated. Descriptive cost hurdles by pair logged in `PREREGISTRATION.md` for the record (0.139%/yr–1.180%/yr range, far lower turnover than any above/below state-flip cell in this study). | Post-termination "Batch 2" module (`HANDOVER.md`'s 2026-09-22 triage), one of 4 parallel modules run in isolated worktrees. New machinery: `features/crossover.py` (event detector, reuses `features/state.py`'s run-length primitives), `modules/crossover_state.py`. Spread-velocity addendum added 2026-09-24 after a scope review during the coordinating session's Batch-2 consolidation. | `PREREGISTRATION.md` M3 entry + 2026-09-24 spread-velocity addendum; `EXPERIMENTS.csv` (18 rows: 16 counted + 4 horizon companions... see file for exact split); no `FINDINGS.md` entry (Tier 4). |
| **M6.5** — The SMA drop-off artefact | 14th, post-termination Batch 2, 2026-09-23 (PR #88, reverted via #92, restored via #93) | **Both primary cells inconclusive — not killed, not confirmed, and fails its own plateau check.** SMA50 pooled: C2 −0.081% CI [−0.255%,+0.102%]. SMA200 pooled: +0.134% CI [−0.196%,+0.458%]. Neither CI excludes zero; neither clears the module's own 0.15% kill floor either (edges 0.255%/0.458%). **Opposite-sign point estimates between the two lookbacks — plateau check fails**, same flat/sign-flipping-null shape M6.1's own decisive test produced. **One flagged-not-promoted companion, pre-registered as not counted toward `N_tests`:** the SMA200 down-only flip split (DESIGN's own literal "rolling over" example) does clear the kill floor — price-driven down-flips outperform drop-off-driven down-flips by +1.029%/21d, CI [+0.231%,+1.716%] — but the leading alternative explanation (uncontrolled short-term reversal, the same confound M2/M6.3 already found elsewhere) hasn't been checked for this specific cell, so it stays a flagged open question, not a claim. | 2 primary cells (SMA50, SMA200) declared and run as 2 — different lookbacks' flip-event populations are largely disjoint (a 50-day and 200-day SMA don't flip sign on the same days), no redundancy-check needed the way same-date-value column pairs get one. Contributes 2 to the 2026-09-24 whole-grid FDR re-run. | Not applicable — mechanism/diagnostic question about whether an existing slope construction's flips are contaminated by the drop-off artefact, not a standalone tradeable claim (same convention as M5/§7.5). | Post-termination "Batch 2" module. New machinery: `modules/sma_dropoff.py` (entering-bar/exiting-bar slope-change decomposition). Explicitly does not resolve whether M6.1/M6.3's own 21-day `slope_log_21` results are drop-off-contaminated (this module only decomposes the 1-day raw slope) — left as an open question, not assumed either way. | `PREREGISTRATION.md` M6.5 entry; `EXPERIMENTS.csv` (10 rows: 2 primary + 4 direction-split companions + 4 diagnostics); no `FINDINGS.md` entry (both primary cells Tier 4). |
| **M6.6** — Slope agreement across the ribbon | 15th, post-termination Batch 2, 2026-09-23 (PR #90) | **DESIGN's own stated expectation held exactly — drawdown is where the signal is, return is not.** `ribbon_agreement_extreme_drawdown` (ordinal state 5 vs. state 0 of {10,20,50,100,200}-day SMA slope signs, on `fwd_mdd_21`): **Tier 3**, C2 +0.6538% CI [+0.4379%,+0.8870%], clears cost at every reading (0.5415%/yr hurdle vs. point +7.85%/yr, near edge +5.25%/yr), survives reversal-robustness (~18% attenuation, CI still excludes zero). **2026-09-24 whole-grid FDR re-run: this cell is now the study's smallest p-value ever (p≈0.00000), the new rank-1 survivor at N=79** — but stays capped at Tier 3 by its own magnitude-vs-signed-return actionability gap (an avoided-loss/drawdown-shallowing read, not a direct realized-return claim — the same limitation M7's `ribbon_direction_magnitude` carries, and which that cell no longer even needs since it drops out of FDR survivorship at the larger N — see the FDR section below). `ribbon_agreement_extreme_return` (same restriction, on `fwd_ret_21`): Tier 4, CI spans zero. **Required correlation matrix** (regardless of outcome, DESIGN's own text): pairwise per-date median Spearman among `slope_log_21` at {10,20,50,100,200} ranges 0.279 (10-vs-200) to 0.887 (10-vs-20, right at this study's 0.89 non-redundancy bar) — the ribbon does not collapse to a single MA's own slope. | 2 declared, run as 2 — different outcome variables (`fwd_mdd_21` vs. `fwd_ret_21`) on the same state5-vs-state0 restriction, not a robustness check of the same hypothesis (kept independent, same treatment M2's `stack_fully_bullish`/`stack_fully_bearish` pair received). Contributes 2 to the 2026-09-24 whole-grid FDR re-run. | `ribbon_agreement_extreme_drawdown`: 0.5415%/yr hurdle vs. point +7.85%/yr, near edge +5.25%/yr, far edge +10.64%/yr — clears at every reading, with the avoided-loss caveat named above. | Post-termination "Batch 2" module. New machinery: `labels/path_metrics.py::forward_max_drawdown` (independently built here; M3's own fork was separately told it might need the same function and didn't collide since neither depended on the other landing first). New local (not shared-panel) `sma_10`/`sma_100` + their `slope_log_21`, DESIGN's own named lookback set, not the panel's {20,50,150,200}. | `PREREGISTRATION.md` M6.6 entry + Result addendum; `FINDINGS.md` (1 entry, `ribbon_agreement_extreme_drawdown`); `EXPERIMENTS.csv` (3 rows). |
| **M12** — Volume and liquidity interaction | 16th, post-termination Batch 2, 2026-09-23 (PR #91) | **`dollar_volume`/SMA50 survives — Tier 3, opposite sign from DESIGN's own hypothesis.** C2 −0.8696% CI [−1.3809%,−0.4019%], clears cost cleanly (0.291%/yr hurdle vs. point −10.44%/yr, near edge −4.82%/yr — the largest cost-viability margin of any Tier-3 cell in this study), survives reversal-robustness (~34% attenuation, CI still excludes zero). **Sign is opposite DESIGN's own hypothesis**: bottom-dollar-volume reclaims outperform top-dollar-volume reclaims, not the reverse. **2026-09-24 whole-grid FDR re-run: this cell newly clears FDR too (p=0.00348, rank 3 of 79)** — but **not promoted to Tier 2**: this panel has no point-in-time market-cap/size control (`HANDOVER.md`'s own infra inventory), and dollar volume correlates strongly with size, so an uncontrolled small-cap/illiquidity premium remains at least as plausible as a genuine reclaim-durability mechanism — an open, *un*resolved confound (unlike M6.3's tail-decomposition, nothing here has directly ruled it out), same "flagged, not promoted" treatment M18's `dist_from_52w_low_h126` already received for an analogous reason. `dollar_volume`/SMA20: Tier 4 — same direction, but does *not* survive reversal-robustness (CI now spans zero, ~47% attenuation) — reads as a reversal artifact. `relative_volume`/SMA200 hold-rate companion: Tier 3, mechanism read, no cost — the one cell supporting DESIGN's literal hypothesis in the stated direction. Every other cell (6 of 9 primary): Tier 4, flat. | 9 primary cells (3 sub-questions × 3 lookbacks) declared as 9, **independence explicitly checked this session (2026-09-24)** — M12's own pre-registration had left this unchecked ("not checked for correlation before declaring... cheap to run both rather than spend the check"), a real gap by this study's own standard (every other multi-feature grid, M4/M18, got this check before being counted). Per-date median Spearman across all pairs of {`relative_volume`, `dollar_volume`, `vwma_divergence`-at-own-lookback}: 0.00–0.41 (highest: `vwma_divergence_20` vs. `vwma_divergence_50`, expected from overlapping windows) — well under this study's 0.89 bar. All 9 confirmed independent, kept as 9. Contributes 9 to the 2026-09-24 whole-grid FDR re-run. | `dollar_volume`/SMA50: 0.291%/yr hurdle vs. point −10.44%/yr, near edge −4.82%/yr, far edge −16.57%/yr — clears at every reading. | Post-termination "Batch 2" module. New machinery: `features/liquidity.py` (`relative_volume`, `dollar_volume`, a minimal module-local `vwma` stub — full VWMA kernel deferred to M8). | `PREREGISTRATION.md` M12 entry + reversal-robustness addendum; `FINDINGS.md` (2 entries: `dollar_volume`/SMA50, `relative_volume` hold-rate/SMA200); `EXPERIMENTS.csv` (14 rows). |
| **M8** — MA family horse race at matched lag | 17th, post-termination Batch 3, 2026-09-24 (PR #97) | **Module killed — DESIGN's own ~80%-likely prior holds.** Lag-matching methodology: each family's own average lag measured empirically via an impulse-response center-of-mass test (`features/kernels.py::impulse_center_of_mass`), validated against SMA/EMA's known-exact closed form `(period-1)/2` before trusting it for HMA/DEMA (no independent closed form). Reference lag: SMA(50)'s own COM = 24.5 days; matched periods SMA=50, EMA=50, WMA=74, DEMA=224, VWMA=50 (a constant-volume idealization reduces exactly to SMA). **HMA's lag reduction is so extreme that literal matching to 24.5 days would need a ~1,900-day period** — impractical given this panel's ~3,000-day history; reported at the idiomatic "same n=50" convention instead, with its own much-shorter realized lag (~1.67 days) stated explicitly, not hidden. KAMA used canonical params (10/2/30) — its own impulse-response COM (162.5) is a documented artifact of the test itself against KAMA's own adaptive mechanism, not a meaningful lag number. **Best candidate (HMA) nominally clears the 0.10% magnitude floor over EMA (+0.1059%, date-equal-weighted) but White's Reality Check p=0.193** — far from this study's 0.10 convention. All 7 families' primary cells cluster tightly (−0.127% to −0.206%), same sign, overlapping CIs — the cleanest plateau-check confirmation in this study's history that kernel shape doesn't matter. All 7 fail cost at the CI edge. Tier 4, no `FINDINGS.md` entry. | 8 declared (7 family cells + 1 Reality Check summary), **all `counted_in_n_tests=False`** — Reality Check's own empirical bootstrap p-value (from a max-order-statistic null, already internally corrected for comparing 6 candidates) is methodologically incompatible with the whole-grid pass's Wald-approximate CI-based p-values; BH-correcting it again would double-count the same multiplicity question. Contributes 0 to the whole-grid FDR re-run. | Not evaluated per-family (all fail cost at the CI edge; hurdles 1.52–3.61%/yr vs. 0.30–0.79%/yr near-edge magnitudes) — not the module's decisive test regardless (Reality Check is). | Post-termination "Batch 3" module (`HANDOVER.md`'s own scoping — unlike Batches 1/2, run 1-2 at a time, not 4-way parallel; ran alongside a sibling M10 fork, explicitly not touching `features/panel.py`, M10's own exclusive file this batch). New machinery: `features/kernels.py` (WMA/HMA/DEMA/KAMA/VWMA + lag-matching tools), `stats/multiple_testing.py::white_reality_check` (White 2000, new). | `PREREGISTRATION.md` M8 entry; `EXPERIMENTS.csv` (8 rows); no `FINDINGS.md` entry (Tier 4). |
| **M10** — Timeframe and sampling | 18th, post-termination Batch 3, 2026-09-24 (PR #98) | **Clean null — DESIGN's own hypothesis ("weekly MAs offer a better lag/whipsaw tradeoff") does not hold.** DESIGN's own "key control" (construction c: daily SMA evaluated Fridays-only, isolating sampling frequency from lookback) killed cleanly at all 3 lookbacks — gaps of −0.02pp/+0.02pp/−0.03pp vs. construction (a) (daily, evaluated daily), all far under the 0.10% floor, CIs overlapping heavily. The bar-aggregation effect (construction b, weekly-native SMA{10,30,40} vs. construction c) is small and directionally consistent (weekly-native always slightly less negative, all 3 matched pairs) but not distinguishable from noise. Well-powered throughout (64,757–432,955 events, 402 tickers per cell). Tier 4 throughout, no `FINDINGS.md` entry. Real bugs caught and fixed against real-panel data before logging: a `merge_asof` global-sort requirement, a datetime64 dtype mismatch between a fresh weekly resample and the cached daily panel, a silent `sector`-column merge collision (now covered by a regression test). Also flagged, not resolved: M1's own logged `n_events` for `above_sma_50` (743,745) doesn't match a fresh recomputation on the identical panel (432,955) despite matching point estimate/CI closely — likely a pre/post-C2-eligibility-restriction labeling inconsistency in M1's historical row, named for whoever next touches M1, not audited here. | 9 declared, **7 counted** — `(a)/lb50` and `(a)/lb200` are exact duplicates of M1's own already-counted `above_sma_50`/`above_sma_200` cells (confirmed via a fresh run of `baseline_state.py`'s own construction on the identical panel), excluded; `(a)/lb150` (M1 never tested SMA150 standalone), all 3 `(c)` cells, and all 3 `(b)` cells are genuinely new, kept. Contributes 7 to the whole-grid FDR re-run. | Not evaluated for any of the 7 counted cells — every CI spans zero or the decisive (c)-vs-(a) gap is far under the kill floor before cost applies. | Post-termination "Batch 3" module. **Owns `features/panel.py` exclusively this batch** — new `Timeframe` parameter on `build_panel` (backward compatible, `Timeframe.WEEKLY` resamples live from `bars_1d`, never the separately-ingested, incomplete `bars_1w` table). Scope note: only MA/distance/slope/ATR/run-length features are timeframe-correct at non-daily granularity; day-count-calibrated context features (`mom_12_1`, `realized_vol_63`, etc.) are not recalibrated, a named open gap. | `PREREGISTRATION.md` M10 entry; `EXPERIMENTS.csv` (9 rows); no `FINDINGS.md` entry (Tier 4). |
| **M6.4** — Slope persistence and flip hazard | 19th, post-termination Batch 3, 2026-09-24 (PR #99) | **Module NOT killed — a real, well-powered departure from a GBM null.** Kaplan-Meier survival of slope-positive runs (SMA{20,50,150,200}) vs. a matched-volatility GBM-null simulation (2,000 paths, `sigma` = each vol-tercile's own median entry-day `realized_vol_63`). Primary grid (vol-tercile, 12 strata): 7 depart, always toward *more* persistence than the null predicts — a clean plateau at SMA20/SMA50 (all 6 cells depart), SMA150/200 read as underpowered (envelopes widen as runs get scarcer) rather than a clean effect-size decline. **The module's cleanest result is its companion facet** (ER-tercile, not counted toward `N_tests`): the top efficiency-ratio tercile departs at **all four lookbacks**, a genuine plateau with no lookback-decay. **Argued against directly**: the GBM null's own `sigma` is computed from the same potentially-autocorrelated series being tested — if real returns carry positive short-horizon autocorrelation, this could bias the null's noise level low and inflate apparent departures. Named as an open, unresolved validity question, the reason every departing stratum caps at Tier 3. **2026-09-24 whole-grid FDR re-run: the 3 SMA20 vol-tercile cells clear FDR by the widest margin in this study's history** — t0 is the new rank 1 of 99 (p≈0.000000), t1 rank 3, t2 rank 5 — **still not promoted to Tier 2**, same open-caveat reasoning as M12's `dollar_volume`/SMA50. | 12 primary (vol-tercile) declared and counted; 12 ER-tercile companion cells (a second stratification lens on the same runs, pre-registered as a companion, deliberately not crossed with vol-tercile per DESIGN §6.4's own tiny-effective-N warning) not counted. Contributes 12 to the whole-grid FDR re-run. | Not applicable — a survival/mechanism question (how long a trend-intact state actually lasts), not a standalone tradeable claim, same convention as M5/§7.5/M6.5. | Post-termination "Batch 3" module, run alongside a sibling M9 fork (both needed an "efficiency ratio" feature — M6.4 built its own local, temporary copy of the identical formula already inline in M8's `kernels.py::kama`, flagged for reconciliation once M9's shared `features/regime.py` landed). New machinery: `stats/survival.py` (Kaplan-Meier estimator + GBM-null simulator, nothing like this existed before), `modules/slope_persistence.py` (per-ticker slope-run construction with proper right-censoring for delisted/coverage-boundary-truncated tickers). | `PREREGISTRATION.md` M6.4 entry; `FINDINGS.md` (2 entries + 2026-09-24 FDR addendum on the SMA20 vol-tercile plateau); `EXPERIMENTS.csv` (24 rows). |
| **M9** — Regime-conditional lookback | 20th, post-termination Batch 3, 2026-09-24 (PR #100) | **Module killed — DESIGN's own ~70%-likely prior holds.** DESIGN itself names this the module most likely to produce a false positive in the whole study; regime definition (ER via Kaufman's formula, ADX via Wilder's formula, both fixed/published, not tuned) pre-registered and committed before any real-panel number was computed. Stage 1 (descriptive, fit period 2010-2016): every regime × lookback cell negatively signed, CIs overlapping heavily within each regime — picks aren't statistically separated from their own neighbors (DESIGN's own "apply the plateau rule ruthlessly" reads this as noise). Stage 2: ER regime shows ~zero persistence excess at 21 days (essentially memoryless) — a real, informative side-finding that mechanistically pre-explains stage 3's null; ADX regime, by contrast, shows a genuine +10.4pp persistence excess. Stage 3 (test period 2017-2021, the decisive test): the ER-regime-switching rule vs. the best fixed lookback (EMA50) — CI spans zero after sign-rotation; also indistinguishable from KAMA, DESIGN's own named comparison. Tier 4, no `FINDINGS.md` entry. Real bug caught before logging: an earlier `best_lookback_per_regime` assumed positive-only signing and consequently selected nothing in any regime (every cell in this study's own `above_ema_k` construction is negatively signed) — fixed to sign-agnostic largest-magnitude/CI-excluding-zero selection. | 25 declared, **only 1 counted** (the single decisive stage-3 test) — DESIGN's own large-search-space false-positive warning motivated collapsing this module to one decisive test before running anything, same convention M8's Reality Check used for its own best-of-K claim. Contributes 1 to the whole-grid FDR re-run. | Incremental switching cost (30.34 vs. 20.23 flips/ticker-yr) not evaluated — the decisive test's own CI (sign-rotated) spans zero before cost applies. | Post-termination "Batch 3" module, run alongside a sibling M6.4 fork. **Owns `features/regime.py` exclusively this batch** — `efficiency_ratio` (extracted from M8's `kernels.py::kama` own inline formula, so M6.4's independently-built local copy of the identical formula reconciles cleanly), `average_directional_index` (Wilder's ADX). | `PREREGISTRATION.md` M9 entry; `EXPERIMENTS.csv` (25 rows); no `FINDINGS.md` entry (Tier 4). |

**M2 plateau note:** `stack_fully_bullish`'s and `stack_fully_bearish`'s C2 signs both
agree with all four individual `above_sma_{20,50,150,200}` cells' own signs — passes
DESIGN §6.7 as applied here (directional consistency, not a lookback-neighborhood
sweep, per this module's own pre-registered scope).

**§7.5 plateau note:** this test *is* a plateau check by construction, and it's the cleanest one this study has produced — within every group, the focal lookback's point estimate and CI sit inside its neighbors' own range, no lone bright pixel anywhere. Two of three groups (SMA200, SMA50) show no detectable dist_pct effect at all in that neighborhood; the third (EMA21/19/23) shows a real, detectable, but level-agnostic effect — the textbook "it's a trend-length proxy, not a watched level" shape DESIGN itself predicted as the likelier outcome.

**Shape-stats addendum (2026-09-15) — DESIGN §6.11.1 / CLAUDE.md invariant #10.**
Computed for §7.5 and M2 (both ran after the invariant existed on 2026-09-10 and
should have reported this at the time — a gap fixed now, not a backfill of M1/M4/M11,
which predate the invariant and are deliberately left alone). New: `stats/shape.py`
(`hit_rate_deltas`, `distribution_shape`), wired into both modules' shared per-cell
result functions. Full numbers: `EXPERIMENTS.csv` notes (all 5 affected rows) and
`FINDINGS.md`'s new shape addendum (`stack_fully_bearish`).

**The one result worth surfacing here: `stack_fully_bullish` (Tier 4, CI-spans-zero
mean) has a *positive* hit-rate delta vs. control (+1.21pp at C2) and *negative* skew
(−0.35).** That's the exact diagnostic shape DESIGN §6.11.1 was written to catch — a
flat-to-negative mean CI can hide "wins slightly more often than control, but a
minority of losses are disproportionately larger than the wins," which a mean/CI
table alone can't distinguish from genuinely nothing happening. This doesn't change
`stack_fully_bullish`'s Tier 4 verdict (shape fields carry no kill authority, per the
invariant's own rule) — it explains the shape of the null, which is new information
for anyone using this as a candidate feature rather than a standalone claim.

By contrast, `stack_fully_bearish` (the Tier-3 survivor) has hit rate 63.85% (vs.
58.57% for bullish), win/loss ratio 1.32 (vs. 1.04), and positive skew +0.99 (vs.
−0.35) — favorable on every shape axis, not just the mean, and internally consistent
with its own positive mean delta. §7.5's three groups show a similar, more modest
version of the same asymmetry (bottom-decile skew running noticeably higher than
top-decile skew in all three placebo groups) — descriptive only, doesn't reopen any
of §7.5's Tier 4 verdicts.

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

## Whole-grid FDR pass — RUN 2026-09-17, RE-RUN 2026-09-20, RE-RUN 2026-09-23, RE-RUN 2026-09-24 (Batch 2), RE-RUN 2026-09-24 (Batch 3). Result: 10 of 99 survive at q=0.10 (5 at q=0.05) — the largest survivor set in this study's history, anchored by M6.4's SMA20 vol-tercile cells; the study's one Tier-2 finding is unchanged and confirmed robust across three consecutive grid expansions.

**Verdict, up front (2026-09-24, Batch 3 re-run, current): at q = 0.10, 10 of 99
deduplicated tests survive Benjamini–Hochberg correction; at q = 0.05, 5 of 99
survive.** Adding Batch 3 (M8 [0 counted], M9 [1], M10 [7], M6.4 [12] — see the
"Modules run" table above) pushed N from 79 to 99. Three of M6.4's new cells produced
p-values an order of magnitude below anything in this study's prior history, which —
unlike the 2026-09-20 re-run's pure threshold-shrinking — pulled the whole survivor set
up, not down: **every one of the 10 survivors individually clears its own BH threshold**
(the cleanest pass yet — even the 2026-09-24 Batch 2 pass's 4 survivors needed ranks 3-4
to clear by only ~8%; here the tightest margins, ranks 8-9, still clear by ~5%).
**Survivor set, ranked:**
1. `slope_persistence_vol_tercile_sma20_t0` (M6.4, p≈0.000000) — new rank 1, the
   smallest p-value this study has ever produced.
2. `ribbon_agreement_extreme_drawdown` (M6.6, p=0.000002) — was rank 1 last pass.
3. `slope_persistence_vol_tercile_sma20_t1` (M6.4, p=0.000016).
4. `slope_pctile_21_sma_50` (M6.3, p=0.000050) — **still the study's sole Tier-2
   finding**, still clears q=0.05, confirmed robust across three consecutive grid
   expansions (N=50→79→99) without ever needing a step-up sweep to survive.
5. `slope_persistence_vol_tercile_sma20_t2` (M6.4, p=0.000105).
6. `reclaim_durability_dollar_volume_sma50` (M12, p=0.003476) — survives again.
7. `dist_from_52w_low`@126d (M18, p=0.004679) — survives again.
8. `ribbon_direction_magnitude` (M7, p=0.007674) — **back in**, having dropped out at
   N=79.
9. `stack_fully_bearish_h21` (M2, p=0.008606) — **back in**, same as M7.
10. `above_sma_20` (M1, p=0.009032) — **back in**, same as M7/M2.

**The "flapping" pattern is worth naming plainly, not smoothing over**: M7's, M2's, and
M1's cells survived FDR at N=50, dropped out at N=79, and are now back at N=99 —
three flips in three consecutive passes, purely from denominator/anchor-point changes,
zero new evidence about those three cells themselves. This is the concrete, repeated
demonstration of exactly what this study's own Wald-approximation caveat has been
warning about since the 2026-09-23 pass: a cell sitting close to its own BH threshold
will flip in and out as the grid's composition changes, and that flipping is not
informative about the cell's own evidence. **None of these three has ever reached
Tier 2** (each capped by an independent, FDR-independent reason — M7's actionability
gap, M2's DESIGN §7.3 survivorship cap, M1's outright cost failure) — so despite three
flips each, **the tier assignment for all three has never once changed.** **The
study's actionable headline is unchanged across all five passes to date**: still
exactly one Tier-2 finding (`slope_pctile_21_sma_50`), still zero Tier 1.

**2026-09-24 Batch 2 pass (superseded above, kept for the record): at q = 0.10, 4 of 79
deduplicated tests survived; at q = 0.05, 2 of 79.** Survivor set: `ribbon_agreement_extreme_drawdown`
(M6.6, p=0.00000, rank 1), `slope_pctile_21_sma_50` (M6.3, p=0.00005, rank 2),
`reclaim_durability_dollar_volume_sma50` (M12, p=0.00348, rank 3),
`dist_from_52w_low`@126d (M18, p=0.00468, rank 4). Three of the 2026-09-23 pass's five
survivors (`ribbon_direction_magnitude`, `stack_fully_bearish`, `above_sma_20`) had
dropped out at this N — see the Batch-3 update above for what happened to them next.

**2026-09-23 pass (superseded above, kept for the record): at q = 0.10, 5 of 50
deduplicated tests survived Benjamini–Hochberg correction; at q = 0.05, 1 of 50
survived.** Survivor set: `slope_pctile_21_sma_50` (M6.3, p=0.00005, sole q=0.05
survivor), `dist_from_52w_low`@126d (M18, p=0.0047), `ribbon_direction_magnitude` (M7,
p=0.0077), `stack_fully_bearish` (M2, p=0.0086), `above_sma_20` (M1, p=0.0090). One of
the 5 — `slope_pctile_21_sma_50` — reached Tier 2, the first in this study's history,
via a same-day rising-vs-falling tail decomposition (see the M6.3 entry below). The
other 4 stayed at Tier 3.

**2026-09-17/2026-09-20 history (superseded below, kept for the record):** at N=31
then N=35, zero of the deduplicated tests survived at either q=0.10 or q=0.05. None of
the study's then four Tier-3 cells (`stack_fully_bearish`, M6.2's
`extension_x_slope`/SMA50/top, M6.2's `touch_x_slope`/SMA50/`from_above`, M18's
`dist_from_52w_low`@126d) reached Tier 2.

**2026-09-20 re-run, why:** M18 (a new, post-termination module — see the "Modules
run" table above) pre-registered its own "FDR re-entry" plan before running: if any of
its 4 declared cells survived their own kill criterion, they'd be added to this pass's
grid and the correction re-run, not reported as a standalone claim outside the study's
whole-grid discipline. Two cells did (`dist_from_52w_low`@63d, @126d); per this
study's own established practice (Tier-4 cells are counted in every other module's
`N_tests` too — FDR corrects across everything tested, not just the interesting
results), all 4 of M18's primary cells were added, not just the 2 survivors. N = 31 →
**35**. The 2026-09-17 pass's own 31 cells and their p-values are unchanged below; only
the ranks/thresholds shift because the denominator grew.

**2026-09-23 re-run, why:** four post-termination "Batch 1" modules (M6.1, M6.3, M7,
M13 — see the "Modules run" table above) ran in parallel per the 2026-09-21 triage
(`HANDOVER.md`), each scoped to reuse existing infrastructure with no new shared
machinery. Per this study's own established practice (every declared cell counts
toward `N_tests`, not just survivors — the same rule M18's own re-entry followed), all
of their deduplicated cells were added to this pass, not just the ones that turned out
significant. N = 35 → **50**. The 2026-09-20 pass's own 35 cells and their p-values are
unchanged below; only the ranks/thresholds shift because the denominator grew — except
this time, unlike 2026-09-20, the shift is large enough to actually flip 5 cells'
verdicts, because one of the new cells (`slope_pctile_21_sma_50`, p=0.00005) has a
p-value an order of magnitude smaller than anything previously in the grid, which
anchors BH's step-up procedure at a much more permissive point than before.

**2026-09-24 re-run, why:** four post-termination "Batch 2" modules (M3, M6.5, M6.6,
M12 — see the "Modules run" table above) ran in parallel per `HANDOVER.md`'s
2026-09-22 triage, plus a same-day spread-velocity addendum to M3. Per this study's
own established practice, every declared/deduplicated cell counts toward `N_tests`.
N = 50 → **79** (16 from M3, 2 from M6.5, 2 from M6.6, 9 from M12 — full
deduplication reasoning in the table below). Unlike the 2026-09-20 re-run (which only
shrank thresholds) and more like the 2026-09-23 re-run (which flipped verdicts), this
pass **both adds a new smaller rank-1 p-value AND removes three previous survivors** —
the first re-run in this study's history where the survivor *composition* changes in
both directions at once, not just its count.

**2026-09-24 re-run (Batch 3), why:** the remaining four post-termination "Batch 3"
modules (M8, M9, M10, M6.4 — see the "Modules run" table above) landed the same day,
run 1-2 at a time per `HANDOVER.md`'s own Batch-3 scoping (heavier standalone infra
builds, not 4-way parallel). Per this study's own established practice, every
declared/deduplicated cell counts toward `N_tests` regardless of outcome. N = 79 →
**99** (0 from M8 — Reality Check's own p-value is methodologically incompatible with
this pass's Wald/BH machinery, see the dedup table below; 1 from M9 — DESIGN's own
false-positive warning collapsed the whole module to a single decisive test; 7 from
M10; 12 from M6.4). Checked directly before trusting the count: none of the four
modules left an independence check unresolved the way M12 did last pass (grepped both
modules' own `PREREGISTRATION.md` sections for the same "not checked for
correlation"-style admission — none found). This pass **both adds three new
smaller-than-ever p-values AND restores three previously-dropped survivors** — the
"flapping" pattern named in the verdict above.

**Method (`stats/multiple_testing.py`, new — DESIGN §6.6's own named procedure):**
1. **`p_value_from_ci`**: a two-sided Wald p-value backed out of each cell's
   already-computed 90% block-bootstrap CI (`SE = (ci_high − ci_low) / (2 × 1.645)`,
   `z = point_estimate / SE`). **Labeled approximation, not a re-derivation from raw
   bootstrap draws** — this study's bootstrap functions (`stats/inference.py`)
   summarize each draw set to `point_estimate`/`ci_low`/`ci_high` and were never
   archived as raw per-cell draws across modules, so re-deriving an exact empirical
   p-value would mean rebuilding every module's pipeline from scratch. **This
   approximation now matters more than it used to**: at N=35, the smallest p-value in
   the grid (0.0086) sat at roughly 2.7× its own rank's BH threshold, comfortably far
   from the decision boundary. At N=50, the new smallest p-value (0.00005,
   `slope_pctile_21_sma_50`/M6.3) is two orders of magnitude under its own threshold —
   still not a boundary case for *that* cell — but three of the four cells it sweeps
   along via BH's step-up rule (`ribbon_direction_magnitude`, `stack_fully_bearish`,
   `above_sma_20`) sit much closer to their own individual thresholds (within ~10-30%),
   where a Wald-vs-exact-bootstrap discrepancy could plausibly matter. This is flagged
   explicitly as an open precision caveat on those three specifically, not on the
   pass's central result (`slope_pctile_21_sma_50`'s own survival, and the fact that
   *something* now survives, are both robust to this approximation by a wide margin).
   **2026-09-24 update: this caveat's predicted risk materialized** — at N=79, ranks 1
   and 2 (`ribbon_agreement_extreme_drawdown`, `slope_pctile_21_sma_50`) still clear
   their own thresholds by a wide margin, but **ranks 3 and 4
   (`reclaim_durability_dollar_volume_sma50`, `dist_from_52w_low`@126d) now individually
   clear their own thresholds by only ~8%** (p=0.00348 vs. threshold 0.00380; p=0.00468
   vs. threshold 0.00506) — tighter margins than anything in the 2026-09-23 pass. Unlike
   that pass, though, **these two no longer depend on a step-up sweep from a tiny
   anchor p-value to survive** — each clears its own rank's bar directly — so the
   approximation risk here is about whether the *exact* p-value might sit just above
   0.00380/0.00506 rather than just below, which would drop that one cell specifically,
   not about the qualitative "does anything survive" question.
   **2026-09-24 Batch-3 update: this pass is the cleanest yet on this specific
   precision axis.** All 10 survivors individually clear their own BH threshold — even
   the tightest (ranks 8-9, `ribbon_direction_magnitude` and `stack_fully_bearish_h21`,
   at ~95% of their own threshold, the closest margins in this pass) don't depend on
   the step-up sweep mechanism the way three of the 2026-09-23 pass's five survivors
   did. The precision caveat is now narrower in scope than it has ever been: it applies
   only to whether ranks 8-10 (the three "flapping" cells) individually clear by their
   own ~5-11% margins, not to whether the pass's headline finding survives — M6.4's
   three new top-ranked p-values are orders of magnitude under their own thresholds,
   and M6.3's Tier-2 cell clears by nearly three orders of magnitude, both far outside
   any plausible Wald-vs-exact-bootstrap discrepancy.
2. **`benjamini_hochberg`**: standard BH step-up procedure.

**Deduplication (the actual work of this pass — every open item the sections below
used to defer is resolved here, not just cited):**

| Module | Raw declared | Deduplicated | What was collapsed |
|---|---|---|---|
| M4 | 9 facet-level | **5**: `dist_pct_sma_20` (representing all 3 SMA20 normalisations, 0.94–0.98 correlated per the 2026-09-16 Track A sweep — this is what finally answers this table's own long-standing "SMA50/SMA200 unchecked" note, using that sweep's own numbers: `dist_pct`/`dist_atr` are 0.96–0.98 correlated at *every* lookback, so they always merge; `dist_z` decorrelates from 0.94 at SMA20 to 0.89 at SMA50 to 0.69 at SMA200, "genuinely more separate" past SMA20 — so SMA50 and SMA200 each keep 2: their own `dist_pct` and `dist_z`), `dist_pct_sma_50`, `dist_z_sma_50`, `dist_pct_sma_200`, `dist_z_sma_200`. | `dist_atr` at every lookback (redundant with `dist_pct`, 0.94–0.98 corr); `dist_z_sma_20` (redundant with `dist_pct_sma_20` specifically, 0.94 corr). |
| M1 | 30 (6 primary + 24 run-length) | **3**: `above_sma_20`, `above_sma_50`, `above_sma_200`. | Above/below are exact algebraic mirrors (already collapsed at declaration into these 3 rows). 24 run-length cells excluded — no clean CI to correct (killed by the plateau rule, not by CI), not a hypothesis BH can evaluate. |
| M11 | 5 declared | **3**: `dist_pct_sma_200_h21`, `dist_pct_sma_20_h5`, `dist_pct_sma_20_h63`. | **New this pass**: `dist_pct_sma_20_h21` and `dist_pct_sma_50_h21` are cross-module duplicates of M4's own cells of the same name (already flagged in this file's 2026-09-10 note as a deterministic recomputation via identical `block_bootstrap_spread` calls) — excluded here from M11's own count to avoid double-counting, not just noted. `dist_atr`/`dist_z` SMA20 companions were already excluded at declaration. |
| §7.5 | 3 group-level | **1**: `placebo_ema21_h21`. | **New finding of this pass**: `placebo_sma200_h21` and `placebo_sma50_h21` are **bit-exact duplicates** of M4's `dist_pct_sma_200_h21`/`dist_pct_sma_50_h21` (identical CI to 6 decimal places, confirmed by inspection of `EXPERIMENTS.csv`) — §7.5's own "focal cell" for the SMA200/SMA50 groups is, by construction, the same `dist_pct` decile spread M4 already computed at those lookbacks. Only the EMA21 group is a genuinely new lookback M4 never tested. |
| M2 | 2 (part a) + 8 (part b, declared) | **2**: `stack_fully_bullish_h21`, `stack_fully_bearish_h21` (both the pre-registered **incremental-vs-M1** statistic, the actual hypothesis M2 declared and evaluated its kill criterion on — not the standalone C2 delta). | Part (b)'s 8 ablation coefficients have **no CI at all** (DESIGN's own "no CI, no kill criterion" framing) — excluded from the correction entirely, not counted as 8 tests with an assumed p-value. This is stricter than this table's own prior wording ("declared N_tests contribution" implied they counted); they don't, because BH literally has no p-value to give them. |
| M5 | 6 (group × direction) | **6**, unchanged. | Already independent — 3 disjoint feature families × 2 disjoint direction subsets, no mirrors or cross-module overlap found. |
| M6.2 | 12 (3 sub-questions × 2 lookbacks × 2 facets) | **11**, unchanged except dropping the 1 unresolved cell. | The 12th (`extension_x_slope`/SMA200/top) has no CI (`InsufficientBlocksError`) — excluded, not treated as p=1. The other 11 checked against M1/M4/M5's own comparisons and each other: no duplication found (different row-restriction logic in every case — within-state, within-decile, and within-touch-event are three different populations, not the same statistic recomputed). |
| M18 | 4 (2 features × 2 horizons) | **4**, unchanged. | Checked directly before declaration, not deferred: per-date median Spearman(`dist_from_52w_high`, `dist_from_52w_low`) = 0.4677 — well short of M4's 0.94–0.98 redundancy bar, both features kept. No cross-module duplicate found either (no other module tests this feature family). |
| M6.1 | 4 (lookback grid, sma20/50/150/200) | **4**, unchanged — **new this pass**, checked directly, not deferred: median per-date Spearman of `slope_log_21` across all 6 lookback pairs is 0.35–0.88 (highest at the adjacent 150/200 pair), below M11's own 0.89 non-redundancy bar at every pair. Also non-independence-checked against M6.3's `slope_pctile_21` (a per-date decile rank of the same underlying `slope_log_21` columns): Spearman correlation between a raw value and its own per-date rank transform is monotonic by construction and the decile-bucketing only coarsens it further, so M6.3's cells are bounded *below* M6.1's own raw-value correlations at the same lookback pairs — already comfortably under the redundancy bar, no separate computation needed. | None. |
| M6.3 | 3 (primary humped-test cells, sma20/50/200) | **3**, unchanged. | Cross-lookback correlation bounded via M6.1's own check above (see that row). The 3 large-move-exclusion companions and 2 reversal-robustness rows are robustness checks on the same 3 hypotheses, not independent tests — excluded, matching this pass's own treatment of every module's robustness-companion rows (M2's, M6.2's, M18's). |
| M7 | 5 declared (2 vol-expansion readings + 3 direction cells) | **4**: `ribbon_vol_expansion_c2_standard`, `ribbon_direction_signed`, `ribbon_direction_magnitude`, `ribbon_direction_conditional_on_trend`. | The two vol-expansion readings (`_c2_standard`/`_c2_no_vol_match`) are the same hypothesis tested two ways — an explicit internal-consistency check named at this module's own pre-registration ("agrees in sign/magnitude with the... reading below"), not two independent hypotheses — merged to 1, keeping the standard-C2 reading as the representative. The 3 direction cells test different statistics/populations (signed vs. magnitude vs. trend-conditional-signed) — kept independent, same reasoning M6.2's within-restriction cells received. |
| M13 | 4 (VIX/breadth tercile × top/bottom) | **4**, unchanged. | Disjoint tercile subpopulations of the same underlying `above_sma_200` cell — a restricted-subpopulation test, same treatment M6.2's within-restriction cells received in the original 2026-09-17 pass, not a literal duplicate of M1's own already-counted `above_sma_200` cell (different, smaller row population, not a deterministic recomputation with identical arguments the way M11's neutralized spread was found to duplicate M4's). |
| M3 | 16 (10 primary + 4 quality facets + 2 spread-velocity facets) | **16**, unchanged — **new this pass**. All 16 are distinct restricted subpopulations of the same underlying state-matched crossover-vs-control comparison (5 fast/slow pairs × 2 directions for the primary grid; slope-sign, price-position, and spread-velocity-sign each partition the `sma_50/sma_200`/golden primary cell's own population into two disjoint halves) — checked directly, no cross-cell overlap found within the module. Cross-module: M3's crossover-day-vs-state-matched-control construction is checked against M1's above/below state cells and M6.2's touch/slope cells — all three use disjoint row-selection logic (crossover *day* only, vs. the whole above/below population, vs. touch-event days), no duplication. |
| M6.5 | 2 (primary decisive cells, sma50/sma200) | **2**, unchanged — **new this pass**. The two lookbacks' flip-event populations are largely disjoint in time (a 50-day and 200-day SMA's 1-day slope rarely flips sign on the same date), unlike M4/M6.1's same-date-value-column pairs — no per-date Spearman check applies the same way; kept independent by construction. |
| M6.6 | 2 (return, drawdown outcomes on the same state5-vs-state0 restriction) | **2**, unchanged — **new this pass**. Different outcome variables (`fwd_ret_21` vs. `fwd_mdd_21`) on the same row restriction, not the same hypothesis tested twice — same treatment M2's `stack_fully_bullish`/`stack_fully_bearish` pair received (different statistics, not a redundancy-check pair). Cross-module: `ribbon_agreement_state` (an aggregate ordinal count across 5 lookbacks) is a new derived statistic, not a duplicate of any single-lookback `slope_log_21` test M6.1/M6.3 already ran. |
| M12 | 9 (3 sub-questions × 3 lookbacks) | **9**, unchanged — **independence explicitly checked this session (2026-09-24)**, closing a gap M12's own pre-registration had left open ("not checked for correlation before declaring"). Per-date median Spearman across all 3 pairs of {`relative_volume`, `dollar_volume`, `vwma_divergence`-at-own-lookback}: 0.00–0.41 (highest: `vwma_divergence_20` vs. `vwma_divergence_50`, the two most-overlapping windows) — well under this study's 0.89 bar at every pair. All 9 kept independent. |
| M8 | 8 (7 family cells + 1 Reality Check summary) | **0**. Reality Check's own p-value is an empirical bootstrap p-value from a max-order-statistic null (already internally corrected for comparing 6 candidates against EMA) — methodologically incompatible with this pass's Wald-approximate, CI-half-width p-values; feeding it through `p_value_from_ci`/`benjamini_hochberg` would double-count the same best-of-K multiplicity question Reality Check already resolves on its own terms. The 7 family cells are explicitly descriptive input to that one decisive test, not independent claims (same convention as M4's decile tables). |
| M9 | 25 (9 ER descriptive + 9 ADX descriptive + 2 persistence + 3 benchmark-selection + 1 decisive + 1 KAMA comparison) | **1**: `regime_adaptive_vs_fixed_decisive`. DESIGN's own explicit false-positive warning for this module ("a regime × lookback grid is a large search space over data with tiny effective N") motivated collapsing the entire module to its one pre-registered decisive test before running anything — same convention M8's Reality Check used, applied here to a different mechanism (module-level pre-commitment rather than a best-of-K correction). |
| M10 | 9 (2 duplicate-of-M1 + 1 new lookback + 3 `(c)` + 3 `(b)`) | **7**. `(a)/lb50` and `(a)/lb200` are exact duplicates of M1's own already-counted `above_sma_50`/`above_sma_200` (confirmed via a fresh run of `baseline_state.py`'s own construction on the identical panel) — excluded. `(a)/lb150` (M1 never tested SMA150 standalone), all 3 `(c)` (Friday-only sampling) cells, and all 3 `(b)` (weekly-native) cells are genuinely new constructions, kept independent — no correlation check needed the way same-date-value-column pairs (M4-style) get one, since these are different row-selection/sampling-frequency constructions, not the same statistic recomputed. |
| M6.4 | 24 (12 primary vol-tercile + 12 companion ER-tercile) | **12** (primary only). The 12 ER-tercile companion cells are a second stratification lens on the *same* underlying slope-runs, pre-registered as a companion before running (not crossed with vol-tercile, per DESIGN §6.4's own tiny-effective-N warning) — excluded from `N_tests`, same treatment this study gives every companion/robustness row. The 12 primary cells (4 lookbacks × 3 vol-terciles) are disjoint row populations (terciles partition the data) — same treatment M13's VIX/breadth tercile cells received, kept independent. |

**N_tests = 5 + 3 + 3 + 1 + 2 + 6 + 11 + 4 + 4 + 3 + 4 + 4 + 16 + 2 + 2 + 9 + 0 + 1 + 7 + 12 = 99**
(the first 16 terms — 79 — unchanged from the 2026-09-24 Batch-2 pass; the last 4 terms
are Batch 3's contribution) — down from a naive raw sum that would run well past 200
once every module's raw declared grid is added in without deduplication. **Independence
check explicitly done for this pass, not deferred**: grepped both M9's and M6.4's
`PREREGISTRATION.md` sections for the same "not checked for correlation"-style
admission M12 carried last pass — none found in either, so no extra correlation
computation was needed before trusting their declared counts (unlike M12 last time).
**Not re-stress-tested against alternative dedup counts this pass** (the 2026-09-23
pass's own N=47/50/51 stress test is not repeated here for the +20 new cells) — worth
doing eventually, though this pass's own survivors clear their own thresholds by wider
margins on average than the 2026-09-24 Batch-2 pass's did, so the exact dedup count is
less load-bearing here than it was for that pass's ranks 3-4.

**Full ranked table (99 tests, p-value ascending, 2026-09-24 Batch-3 re-run — current):**

| rank | module | cell | p (Wald, from CI) | BH threshold (rank/99×0.10) | reject q=0.10 |
|---|---|---|---|---|---|
| 1 | M6.4 | `slope_persistence_vol_tercile_sma20_t0` | ~0.000000 | 0.00101 | **yes** |
| 2 | M6.6 | `ribbon_agreement_extreme_drawdown` | 0.000002 | 0.00202 | **yes** |
| 3 | M6.4 | `slope_persistence_vol_tercile_sma20_t1` | 0.000016 | 0.00303 | **yes** |
| 4 | M6.3 | `slope_pctile_21_sma_50` | 0.000050 | 0.00404 | **yes — Tier 2** |
| 5 | M6.4 | `slope_persistence_vol_tercile_sma20_t2` | 0.000105 | 0.00505 | **yes** |
| 6 | M12 | `reclaim_durability_dollar_volume_sma50` | 0.003476 | 0.00606 | **yes** |
| 7 | M18 | `dist_from_52w_low`@126d | 0.004679 | 0.00707 | **yes** |
| 8 | M7 | `ribbon_direction_magnitude` | 0.007674 | 0.00808 | **yes** |
| 9 | M2 | `stack_fully_bearish_h21` | 0.008606 | 0.00909 | **yes** |
| 10 | M1 | `above_sma_20` | 0.009032 | 0.01010 | **yes** |
| 11 | M11 | `dist_pct_sma_20_h5` | 0.013494 | 0.01111 | no |
| 12 | M4 | `dist_pct_sma_20_h21` | 0.016963 | 0.01212 | no |
| 13 | §7.5 | `placebo_ema21_h21` | 0.020025 | 0.01313 | no |
| 14 | M6.2 | `touch_x_slope`/SMA50/`from_above` | 0.022273 | 0.01414 | no |
| 15 | M6.4 | `slope_persistence_vol_tercile_sma50_t0` | 0.022592 | 0.01515 | no |
| 16 | M6.3 | `slope_pctile_21_sma_200` | 0.024201 | 0.01616 | no |
| 17 | M6.2 | `extension_x_slope`/SMA50/top | 0.025408 | 0.01717 | no |
| 18 | M13 | `context_vix_bottom` | 0.028563 | 0.01818 | no |
| 19 | M12 | `reclaim_durability_dollar_volume_sma20` | 0.030302 | 0.01919 | no |
| 20 | M6.4 | `slope_persistence_vol_tercile_sma50_t2` | 0.035240 | 0.02020 | no |
| 21 | M13 | `context_breadth_top` | 0.038108 | 0.02121 | no |
| 22 | M10 | `timeframe_daily_fridays_only_sma50` | 0.039204 | 0.02222 | no |
| 23 | M1 | `above_sma_50` | 0.052138 | 0.02323 | no |
| 24 | M6.4 | `slope_persistence_vol_tercile_sma50_t1` | 0.055076 | 0.02424 | no |
| 25 | M18 | `dist_from_52w_low`@63d | 0.066710 | 0.02525 | no |
| 26–99 | — | (all remaining cells, incl. M6.3's SMA20 cell, M1's `above_sma_200`, M9's decisive cell, M6.4's SMA150/200 cells, all of M3/M6.5) | ≥0.083 | — | no |

**Every one of the 10 survivors individually clears its own threshold — no step-up
sweep dependency anywhere in this pass**, unlike the 2026-09-23 pass (3 of 5 survivors
needed the sweep) and even the 2026-09-24 Batch-2 pass (ranks 3-4 cleared by only ~8%).
The tightest margins here are ranks 8-9 (`ribbon_direction_magnitude`,
`stack_fully_bearish_h21`, both ~95% of their own threshold) — real margins, not
sweep-dependent ones.

**Note on the "flapping" cells (ranks 8-10 — `ribbon_direction_magnitude`,
`stack_fully_bearish_h21`, `above_sma_20`):** all three survived at N=50, dropped out
at N=79, and are back at N=99 — three flips in three passes, purely from
denominator/anchor-point changes. None has ever reached Tier 2 (each capped by its own
independent, FDR-independent reason), so despite flipping FDR status three times, the
tier assignment for all three has never once changed. This is the concrete pattern the
2026-09-20 pass's own commentary first warned about, now observed directly and
repeatedly rather than as a hypothetical risk.

**Superseded — full ranked table (79 tests, p-value ascending, 2026-09-24 Batch-2 pass, kept for the record):**

| rank | module | cell | p (Wald, from CI) | BH threshold (rank/79×0.10) | reject q=0.10 |
|---|---|---|---|---|---|
| 1 | M6.6 | `ribbon_agreement_extreme_drawdown` | ~0.00000 | 0.0013 | **yes** |
| 2 | M6.3 | `slope_pctile_21_sma_50` | 0.00005 | 0.0025 | **yes** |
| 3 | M12 | `reclaim_durability_dollar_volume_sma50` | 0.00348 | 0.0038 | **yes** |
| 4 | M18 | `dist_from_52w_low`@126d | 0.00468 | 0.0051 | **yes** |
| 5 | M7 | `ribbon_direction_magnitude` | 0.0077 | 0.0063 | no |
| 6 | M2 | `stack_fully_bearish_h21` | 0.0086 | 0.0076 | no |
| 7 | M1 | `above_sma_20` | 0.0090 | 0.0089 | no |
| 8–79 | — | (all remaining cells) | ≥0.0135 | — | no |

**Superseded — full ranked table (50 tests, p-value ascending, 2026-09-23 pass, kept for the record):**

| rank | module | cell | p (Wald, from CI) | BH threshold (rank/50×0.10) | reject q=0.10 |
|---|---|---|---|---|---|
| 1 | M6.3 | `slope_pctile_21_sma_50` | 0.00005 | 0.0020 | **yes** |
| 2 | M18 | `dist_from_52w_low`@126d | 0.0047 | 0.0040 | **yes**\* |
| 3 | M7 | `ribbon_direction_magnitude` | 0.0077 | 0.0060 | **yes**\* |
| 4 | M2 | `stack_fully_bearish_h21` | 0.0086 | 0.0080 | **yes**\* |
| 5 | M1 | `above_sma_20` | 0.0090 | 0.0100 | **yes** |
| 6 | M11 | `dist_pct_sma_20_h5` | 0.0135 | 0.0120 | no |
| 7 | M4 | `dist_pct_sma_20_h21` | 0.0170 | 0.0140 | no |
| 8 | §7.5 | `placebo_ema21_h21` | 0.0200 | 0.0160 | no |
| 9 | M6.2 | `touch_x_slope`/SMA50/`from_above` | 0.0223 | 0.0180 | no |
| 10 | M6.3 | `slope_pctile_21_sma_200` | 0.0242 | 0.0200 | no |
| 11 | M6.2 | `extension_x_slope`/SMA50/top | 0.0254 | 0.0220 | no |
| 12 | M13 | `context_vix_bottom` | 0.0286 | 0.0240 | no |
| 13 | M13 | `context_breadth_top` | 0.0381 | 0.0260 | no |
| 14 | M1 | `above_sma_50` | 0.0521 | 0.0280 | no |
| 15 | M18 | `dist_from_52w_low`@63d | 0.0667 | 0.0300 | no |
| 16 | M6.3 | `slope_pctile_21_sma_20` | 0.0826 | 0.0320 | no |
| 17 | M1 | `above_sma_200` | 0.0987 | 0.0340 | no |
| 18–50 | — | (all remaining cells) | 0.11–0.95 | — | no |

\*Ranks 2–4 do not individually clear their own rank's threshold (2: 0.0047 vs 0.0040;
3: 0.0077 vs 0.0060; 4: 0.0086 vs 0.0080 — each a genuine miss in isolation). They are
rejected anyway because BH's step-up rule rejects every hypothesis up to and including
the *largest* rank that clears its own threshold, and rank 5 (`above_sma_20`, 0.0090 vs
0.0100) does clear. This is standard, correct BH behavior — the procedure's FDR
guarantee is about the whole rejected set, not each member's individual margin — not a
sign of an error in this pass, but worth stating plainly since it means ranks 2–4's
inclusion is more sensitive to the overall grid's composition than rank 1's or rank 5's
own individual clearance is. The stress test above (N=47/50/51) found the same 5-cell
set every time, which is the actual evidence this sensitivity isn't fatal to the
result — but it is a real, worth-naming difference in kind between rank 1 (survives on
its own terms by two orders of magnitude, would survive at nearly any plausible N) and
ranks 2–5 (survive only via the step-up mechanism, individually much closer to their
own thresholds).

**What this means, precisely — two separate questions, not one:**

**(1) Does anything reach Tier 2? — 2026-09-24 Batch-3 update, current.** **Still just
one: `slope_pctile_21_sma_50` (M6.3) — confirmed across three consecutive grid
expansions, not newly joined.** Each of the 10 current survivors checked individually
against DESIGN §9.2's bar:
- **`slope_persistence_vol_tercile_sma20_t0/t1/t2`** (M6.4, ranks 1/3/5) are **not
  promoted** despite clearing FDR by the widest margin in this study's history: the
  GBM null's own `sigma` is computed from the same potentially-autocorrelated series
  being tested for persistence, which could bias the null's noise level low and
  inflate apparent departures — an open, *unresolved* validity question named
  explicitly in M6.4's own `FINDINGS.md` entry, not something a direct test has ruled
  out the way M6.3's tail-decomposition ruled out its own analogous-looking concern.
  Same "flagged, not resolved" bar as `reclaim_durability_dollar_volume_sma50` below.
  Stays Tier 3 (all three).
- **`ribbon_agreement_extreme_drawdown`** (M6.6, rank 2) — unchanged reasoning from the
  Batch-2 pass below. Stays Tier 3.
- **`slope_pctile_21_sma_50`** (M6.3, rank 4) — unchanged reasoning from the
  2026-09-23 pass below. Confirmed to survive an even larger, more skeptical grid (99
  tests vs. 79 vs. 50) without ever needing a step-up sweep. **Remains Tier 2.**
- **`reclaim_durability_dollar_volume_sma50`** (M12, rank 6) — unchanged reasoning
  from the Batch-2 pass below. Stays Tier 3.
- **`dist_from_52w_low`@126d** (M18, rank 7) — unchanged reasoning from the
  2026-09-23 pass below. Stays Tier 3.
- **`ribbon_direction_magnitude`** (M7, rank 8), **`stack_fully_bearish_h21`** (M2,
  rank 9), **`above_sma_20`** (M1, rank 10) — all three back in this pass after
  dropping out at N=79 (the "flapping" pattern named above). Unchanged reasoning from
  the 2026-09-23 pass below for each — **tier assignment for all three has never once
  changed across any pass**, despite three FDR-status flips each. Stay Tier 3/4
  respectively (per their own original tiering).

**Per-cell reasoning for the 2026-09-24 Batch-2 pass's own 4 survivors (superseded
above where it conflicts, kept for the record):**
- **`ribbon_agreement_extreme_drawdown`** (M6.6) is capped by its own
  magnitude-vs-signed-return actionability gap — an avoided-loss/drawdown-shallowing
  read, not a direct realized-return claim, the identical limitation `ribbon_direction_magnitude`
  (M7) carried in the 2026-09-23 pass. That M7 cell no longer even clears FDR at N=79
  is irrelevant to this reasoning — the actionability gap was never conditional on FDR
  status, and M6.6's version of the same underlying pattern (ribbon-level trend
  agreement predicting *magnitude of adverse move*, not *direction of return*) simply
  replaces M7's as this study's clearest instance of it. Stays Tier 3.
- **`slope_pctile_21_sma_50`** (M6.3) — unchanged from the 2026-09-23 promotion
  reasoning below. Confirmed to survive a much larger, more skeptical grid (79 tests
  vs. 50) without needing the step-up sweep the way three of the old pass's survivors
  did — if anything, a stronger result than before. **Remains Tier 2.**
- **`reclaim_durability_dollar_volume_sma50`** (M12) is **not promoted** despite
  clearing FDR, cost, and C2, and despite surviving reversal-robustness: this panel has
  no point-in-time market-cap/size control (`HANDOVER.md`'s own infra inventory), and
  dollar volume is strongly correlated with size, so an uncontrolled small-cap/
  illiquidity premium is at least as plausible an explanation as a genuine
  reclaim-durability mechanism — named explicitly in M12's own `FINDINGS.md` entry as
  an **open, unresolved** caveat, not something a direct test has ruled out the way
  M6.3's tail-decomposition ruled out its own survivorship concern. This is the same
  "flagged by analogy, not resolved by test" standard that kept `dist_from_52w_low`@126d
  at Tier 3 in the prior pass — applied here to a genuinely different confound
  (illiquidity/size, not delisted-ticker survivorship), same bar. Stays Tier 3.
- **`dist_from_52w_low`@126d** (M18) — unchanged reasoning from the 2026-09-23 pass
  (below), still an open, un-resolved survivorship-adjacent caveat. Stays Tier 3.

**Per-cell reasoning for the 2026-09-23 pass's own 5 survivors (superseded above where
it conflicts, kept for the historical record):**
- **`above_sma_20`** (M1) fails cost outright — a substantive failure this study has
  never treated as compatible with Tier 2, FDR status notwithstanding. Stays Tier 3.
- **`stack_fully_bearish`** (M2) is capped by DESIGN §7.3's pre-existing, explicit
  survivorship cap on weak/bearish-state buckets, which applies "regardless of what the
  statistics show." Stays Tier 3.
- **`ribbon_direction_magnitude`** (M7) is capped by its own magnitude-vs-signed-return
  actionability gap — a real limitation independent of any statistical test. Stays
  Tier 3.
- **`dist_from_52w_low`@126d** (M18) is flagged (this pass) as touching a
  weak/beaten-down-state population (near its 52-week low) plausibly vulnerable to the
  same delisted-ticker survivorship ceiling §7.3 already names for M1/M2 — extended
  here by analogy, not literal enumeration, and not directly tested. Stays Tier 3,
  open caveat.
- **`slope_pctile_21_sma_50`** (M6.3) carried the same kind of caveat at first —
  extreme-negative-slope rows are a similarly weak-state-adjacent population — but
  **this one was resolved by direct test the same day, not left as an analogy**: a
  rising-tail-only vs. falling-tail-only decomposition (`FINDINGS.md`'s M6.3 entry,
  `PREREGISTRATION.md`'s tail-decomposition addendum) found both sides independently
  show the same effect (rising `−0.254%` CI `[−0.429%,−0.085%]`; falling `−0.244%` CI
  `[−0.413%,−0.096%]`) — if the pooled result were a falling-tail survivorship
  artifact, the survivorship-immune rising side would be null or much smaller, and
  it isn't. With that resolved, this cell clears C2, FDR, and cost, and its only
  remaining gaps (holdout, a second universe tier) are missing infrastructure, not
  failures — the Tier-2 profile by DESIGN's own definition. **Promoted.**

Full per-cell reasoning: `FINDINGS.md`'s 2026-09-23 addenda on each of the 5 cells
(historical), plus `FINDINGS.md`'s 2026-09-24 addenda on `ribbon_agreement_extreme_drawdown`
(M6.6) and `reclaim_durability_dollar_volume_sma50` (M12) — the two newly-FDR-clearing
cells' own tier reasoning above needs to actually be written into those entries, not
just asserted here (open item for this session, see below).

**(2) Does the study's statistical headline change? — 2026-09-24 Batch-3 update,
current.** The Tier-2 count still does **not** change (still exactly one,
`slope_pctile_21_sma_50`) across all five passes to date — but the **FDR-survivor set
keeps changing, materially, every time the grid grows**: this pass alone adds 3 new
cells that didn't exist in any prior grid (M6.4's SMA20 vol-tercile trio) and restores
3 cells that had dropped out at N=79 (`ribbon_direction_magnitude`, `stack_fully_bearish_h21`,
`above_sma_20`) — the "flapping" pattern named above. Anyone citing "which cells
survive this study's FDR correction" needs the current N=99 table above, not any
earlier one. The **study's actionable headline is unchanged across every pass run so
far**: one Tier-2 finding, zero Tier 1. `REPORT.md`'s executive summary has been
updated to reflect the current survivor set (see below).

**2026-09-24 Batch-2 pass's own version of this question (superseded above, kept for
the record):** Tier-2 count unchanged; FDR-survivor set changed materially (3 dropped,
2 new). **2026-09-23 pass's own version (superseded, kept for the record):** "zero of
any deduplicated grid this study has ever assembled survives BH correction" was true
through the 2026-09-20 pass and became false; "zero claims have reached Tier 2" was
true through that pass's own first draft and became false once the tail decomposition
resolved same-day.

**Not silently re-tiered in `EXPERIMENTS.csv` or `FINDINGS.md`** at any point in this
history (this study's own no-silent-edits convention, `PREREGISTRATION.md`'s own
precedent for tier changes) — a dated addendum was added to each affected
`FINDINGS.md` entry, and a summary row logged in `EXPERIMENTS.csv` for each pass
(`whole_grid_fdr_pass_2026_09_17`, `whole_grid_fdr_pass_2026_09_20`,
`whole_grid_fdr_pass_2026_09_23`, `whole_grid_fdr_pass_2026_09_24`,
`whole_grid_fdr_pass_2026_09_24_batch3`).

**Historical note:** this section originally carried ~75 lines of pre-pass reasoning
(written 2026-09-09, before the pass first ran) about *why* deduplication would
matter — a trigger condition, a raw per-module N_tests table, and the cross-module
double-counting concern that led to catching §7.5 vs. M4's bit-exact duplicate. All of
it was superseded on 2026-09-17 once the actual pass (top of this section) carried it
out; removed here as redundant with the completed dedup table above, not as a loss of
any conclusion — every dedup decision that reasoning anticipated is reflected in that
table.

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

**First condition reached, 2026-09-17.** The minimal-core list is run and tiered
(7/7 items), and the whole-grid FDR pass has executed against the deduplicated 31-test
count (see above) — the exact literal condition this bullet names. **The study is at
its termination point.** What remains is not more analysis but the write-up: a report
with DESIGN §9.1's structure, the ~15–30 falsifiable claims this study's `EXPERIMENTS.csv`
already constitutes (54 logged cells across 7 modules, tiered), the dead-ends register
(superseded into `EXPERIMENTS.csv` itself per this study's own convention), the reusable
feature panel (`data/features/moving_averages/`), and a cost-sensitivity appendix (every
Tier-3 cell already carries its own cost annotation at both CI edges). The result lands
on the **negative side** of DESIGN §1.5's expected 3–6-Tier-1/2-survivors band — **0
Tier 1/2, 3 Tier 3 (all three now FDR-tested and failed, not merely infrastructure-capped)**
— read in full below, not as a shortfall but as the study's actual, honestly-reported
answer.

**Post-termination update (2026-09-20): M18 does not reopen this verdict.** After this
section's own termination condition had already been reached, two independent Track A
signals (both flagged post-termination — M2's ablation, the 2026-09-16 IC sweep) named
`dist_from_52w_high`/`dist_from_52w_low` as the strongest untested candidate in the
whole feature set. Run as a new, pre-registered module (M18, DESIGN.md/PREREGISTRATION.md)
rather than left as an unresolved Track A note. Result: a fourth Tier-3 cell
(`dist_from_52w_low`@126d, clears cost cleanly) — the closest individual result to
surviving the whole-grid FDR pass this study has produced (1.64× its own BH threshold,
vs. the prior closest at 2.7×) — but still **0 Tier 1/2** once the pass is re-run
against the larger, still-fully-deduplicated grid (N=35). The study's headline is
unchanged: negative-leaning, on the far side of DESIGN §1.5's expected band, now with
one more well-controlled near-miss on the record rather than fewer. This is the
intended shape of "continue looking after termination, but only through the same
pre-registration/kill-criterion/FDR discipline as everything else" — not a reason to
keep extending the study indefinitely chasing the next near-miss.

**Post-termination update (2026-09-23): Batch 1 (M6.1, M6.3, M7, M13) changes the
study's own scorecard for the first time — one Tier-2 finding, where every prior pass
found none.** Four more post-termination modules ran in parallel (`HANDOVER.md`'s
2026-09-21 triage), each pre-registered and run through the same discipline as every
prior post-termination addition. The consolidated whole-grid FDR re-run (N=50, see
"Whole-grid FDR pass" above) found 5 cells survive Benjamini–Hochberg correction at
q=0.10 (1 at q=0.05) — the first survivors this study's own correction has ever
produced, anchored by M6.3's `slope_pctile_21_sma_50` (p=0.00005). Each of the 5 was
then checked individually against DESIGN §9.2's full Tier-2 bar: 4 stay at Tier 3 for
their own independent reasons (cost failure, DESIGN §7.3's pre-existing survivorship
cap, a cell-specific actionability gap, or an unresolved survivorship-cap analogy —
see the FDR section above). **The fifth, `slope_pctile_21_sma_50`, was promoted to
Tier 2 the same day**, once a rising-tail-only vs. falling-tail-only decomposition
directly ruled out its one open caveat (both tails independently show the same
effect — rising `−0.254%`, falling `−0.244%`, nearly identical — ruling out a
falling-tail-specific survivorship artifact) rather than leaving it an open analogy.
This is a real, if modest, move toward DESIGN §1.5's originally expected 3–6-survivor
band (§9.2) — the study still landed on the negative side of that band, now with one
confirmed exception rather than zero. `REPORT.md`'s executive summary has been
updated to reflect this.

**The negative case is, on the whole, still the honest characterization, with one
confirmed exception.** Two modules in (M4,
M1), the running result is already mostly negative-leaning: 5 of 9 M4 facets and 1 of 3
M1 lookbacks are Tier 4 outright, and every SMA20/lb20/lb50 Tier-3 result that looked
real gross died on cost. If this pattern holds through the rest of the minimal-core
list — directionally-real-but-uneconomical or outright-absent everywhere — **the
finished study is "the MA-state family is mostly a re-encoding of momentum and mostly
doesn't survive realistic costs where it isn't,"** written up with the same rigor and
the same report structure (§9.1) as a positive result would get. DESIGN says this
explicitly and this file takes it at face value: **a null result is a successful
outcome**, not a reason to keep looking for a cut that works.

**Saturation watch (2026-09-13 update): 5 modules in, still no Tier-1/2 survivor —
but M2 is not a repeat of the same shape.** M4, M1, M11, §7.5, and now M2 have all
landed with nothing above Tier 3, meeting the early-stop clause's named count
("4–5 modules in a row") on a literal reading. **But M2's `stack_fully_bearish` cell
is a real, clean, cost-clearing Tier-3 result** (see the Modules run table above) —
capped at Tier 3 purely by infrastructure/survivorship, not because the effect is
weak or the CI is borderline the way every prior Tier-3 cell in this study has been.
That's a materially different shape than "directionally-real-but-uneconomical or
outright-absent everywhere" (the pattern the termination section above describes as
the likely negative-finish shape) — this cell would plausibly be Tier 1/2 today if
the whole-grid FDR pass and a holdout check existed. Whether that counts as "a new
mechanism story" in the early-stop clause's sense is a judgment call, not something
this file should decide unilaterally: on one hand it's the same MA-stack family, not
a new mechanism; on the other, it's the single strongest, cleanest gross number this
study has produced, sitting behind an unresolved and specific alternative explanation
(uncontrolled 1-month reversal via `mom_1_0`/`rev_tercile`, not yet tested for this
cell). **Recommendation, not a decision made here: the reversal-robustness check
(M1's own precedent) on `stack_fully_bearish` is cheap, already-built infrastructure,
and directly resolves whether this is real incremental stack information or a
confound already diagnosed elsewhere in this study — worth running before deciding
whether to continue to M5/M6.2 or call the study saturated.**

**Resolved 2026-09-17: ran the reversal-robustness check.** `stack_fully_bearish`
survives with `rev_tercile` added to the C2 match set — C2 delta attenuates ~32%
(`+0.4675%` → `+0.3188%`) but the CI still excludes zero and the cell still clears
cost at every reading (full numbers: `PREREGISTRATION.md`'s M2 reversal-robustness
addendum, `FINDINGS.md`, `EXPERIMENTS.csv`). Reversal is a real but partial
contributor, not the whole effect — this closes the confound question this note
raised, though it does not by itself lift the Tier-3 cap (still FDR/holdout +
survivorship, unchanged). **Decision on M5/M6.2 made the same day: continue —
full completion of the minimal-core list (M5, then M6.2), not an early stop.**

**M5 update (2026-09-17): a clean, decisive Tier-4 kill, not a repeat of M2's shape.**
All 6 primary cells killed, well-powered, no lone survivor — see the Modules run table
above. This is now 6 modules in with exactly one Tier-3 (or better) survivor
(`stack_fully_bearish`) and everything else Tier 4 — a *cleaner* instance of the
"mostly negative" pattern the termination section above describes, not a new mechanism
story. Doesn't change the continue-to-M6.2 decision already made (M6.2 is DESIGN's own
named highest-value part of the slope module, "the most likely Tier-1 producer in the
whole slope module" per DESIGN §6, and is next regardless), but it does mean the
whole-grid FDR pass's eventual denominator is looking more, not less, top-heavy on one
module's one cell — worth keeping in view once M6.2 lands and the FDR pass actually runs.

**M6.2 update (2026-09-17): the "one lone survivor" shape is over — DESIGN's own prior
for this module paid off.** Minimal core is now complete (7 items run: M1, M2, M4, M5,
M6.2, M11, §7.5), and the running count is no longer "6 modules Tier ≤3, one survivor."
M6.2 alone confirmed 2 more Tier-3 cells (`extension_x_slope`/SMA50/top,
`touch_x_slope`/SMA50/`from_above` — see the Modules run table above), both pointing
the same direction from independent constructions. **Total across the whole study:
3 Tier-3 survivors** (`stack_fully_bearish`, and these two), everything else Tier 4 or
below-threshold. This is squarely inside DESIGN §1.5's own expected range (100+ Track A
candidates → ~20 promoted → ~10 pre-registered → **3–6 survive to Tier 1/2** — these 3
are Tier 3, one rung short, entirely because the FDR/holdout infrastructure that would
let any of them clear that bar has never been run, not because the effects themselves
are weak). **The early-stop clause no longer applies on any reading** — it was written
for "4–5 modules in a row, no survivor," and this is now the opposite shape: multiple
independent, real, CI-excluding-zero effects, capped only by infrastructure. **The
whole-grid FDR pass is the load-bearing next step for the whole study, not an optional
housekeeping item** — it is the only thing standing between "3 Tier-3 cells" and an
actual Tier 1/2 verdict on any of them.