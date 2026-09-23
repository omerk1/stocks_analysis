# Moving-averages study — status

One row per module actually run (Track B, pre-registered and executed). Not a
duplicate of `docs/features/moving-averages/PREREGISTRATION.md` — that file is the
frozen pre-registration text per module; this file is the cross-module scoreboard, kept
current, for "what do we actually know and what's still open." Full detail always lives
in `PREREGISTRATION.md` (per-module narrative) and `EXPERIMENTS.csv` (per-cell numbers,
every tested facet, whatever it found); this file points there rather than re-deriving.

**Minimal-core list complete as of 2026-09-17** (M1, M2, M4, M5, M6.2, M11, plus §7.5 —
every item on DESIGN §12's list has now been run at least once). **Whole-grid FDR pass
also run, same day: 0 of 31 deduplicated tests survive at q=0.10 or q=0.05** (see
"Whole-grid FDR pass" below — this was the study's headline result at termination).
**Termination condition reached 2026-09-17** (see "Study-level termination" below);
final report (`REPORT.md`) written the same week. **Post-termination: M18 added
2026-09-20** (52-week high/low range, DESIGN §1.5's porous-scope rule — not part of
the minimal-core list), and the whole-grid FDR pass re-run at N=35: **still 0
survivors**, though M18 contributed the closest individual miss in the study
(`dist_from_52w_low`@126d, 1.64× its own threshold). This does not reopen the study —
see "Study-level termination"'s 2026-09-20 update below. **Resolved 2026-09-21:** the
`rev_tercile`/`mom_1_0` reversal-robustness check on M6.2's two Tier-3 cells has now
been run (`PREREGISTRATION.md`'s M6.2 reversal-robustness addendum). Moot for tier
either way (both cells already FDR-failed) — but not moot for the underlying mechanism
claim: **Finding 1 (`extension_x_slope`/SMA50/top) survives, essentially intact
(~6.7% attenuation, CI still excludes zero). Finding 2 (`touch_x_slope`/SMA50/
`from_above`) does not survive — its CI now spans zero once reversal is matched out**,
the first reversal-robustness check in this study (vs. M2's `stack_fully_bearish`,
M18's two `dist_from_52w_low` cells, which all survived) where the confound check
actually flips a cell from confirmed to inconclusive. This weakens the "two
independently constructed cells corroborate each other" reading the original M6.2
write-up drew — see `FINDINGS.md`'s Finding 2 entry for the full account.
**Post-termination Batch 1 (M6.1, M6.3, M7, M13) added and merged 2026-09-22/23**
(DESIGN §1.5's porous-scope rule, `HANDOVER.md`'s 2026-09-21 triage) — see the four new
rows in "Modules run" below. **Whole-grid FDR pass re-run at N=50, 2026-09-23: 5 of 50
now survive at q=0.10 (1 at q=0.05) — the first survivors this study's own correction
has ever produced**, but **still 0 Tier 1/2** (each survivor individually checked and
capped for its own reason — see "Whole-grid FDR pass" below for the full account).
This does not reopen the study, but it does change its statistical headline; see
"Study-level termination"'s 2026-09-23 update below. Two items now open, not closed:
a rising-tail-only vs. falling-tail-only decomposition of `slope_pctile_21_sma_50`
(M6.3's newly-surfaced survivorship-cap question), and `REPORT.md`'s executive summary
(flagged for revision to reflect the new FDR result, not yet updated).

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
| **M6.3** — Slope magnitude: monotonic or humped? | 10th, post-termination Batch 1, 2026-09-22 (PR #82) | **U-shaped, not humped, at all 3 SMA lookbacks — DESIGN's own prior does not hold.** SMA50 (Tier 3, C2 `−0.248%` CI `[−0.354%,−0.153%]`) and SMA200 (Tier 3, C2 `−0.193%` CI `[−0.337%,−0.056%]`) clear cost at every reading; SMA20 clears its own kill floor but fails cost and fails its own large-move-exclusion companion. **Reversal-robustness (2026-09-22): SMA50 survives essentially unattenuated (if anything strengthened, +13.9%); SMA200 does not (80.5% attenuation, CI now spans zero — best read as a reversal artifact).** **Whole-grid FDR (2026-09-23): SMA50 survives — the first cell in this study's history to clear BH correction**, p=0.00005 against a rank-1 threshold of 0.0020, also the only one of the pass's 5 survivors to clear q=0.05. **Not promoted to Tier 2** — see the "Whole-grid FDR pass" section below and `FINDINGS.md`'s own addendum for the full reasoning (a newly-surfaced, not-fully-resolved survivorship-cap analogy, partially but not fully mitigated by this cell's own "roughly symmetric" tail shape). | 3 primary cells (SMA20/50/200) declared and run as 3; 3 large-move-exclusion companions and 2 reversal-robustness rows excluded from `N_tests` (robustness checks on the same hypotheses, not independent tests). | SMA50: 0.769%/yr hurdle vs. point −2.976%/yr, near edge −1.833%/yr — clears at every reading. SMA200: 0.382%/yr hurdle vs. point −2.313%/yr, near edge −0.668%/yr — clears at every reading. SMA20: fails (near edge misses). | Post-termination "Batch 1" module. Substituted `slope_pctile_21` for DESIGN's literal `slope_atr_21` ask (CLAUDE.md invariant #7 conflict) and a large-single-day-move proxy for the earnings-exclusion companion (no earnings table exists). | `PREREGISTRATION.md` M6.3 entry + 2026-09-22 reversal-robustness addendum + 2026-09-23 whole-grid-FDR addendum; `FINDINGS.md` (3 entries: SMA20/50/200); `EXPERIMENTS.csv` (9 rows: 3 primary + 3 excl-large-move + 2 reversal-robustness + this module's share of the FDR summary). |
| **M7** — Ribbon compression / expansion | 11th, post-termination Batch 1, 2026-09-22 (PR #84) | DESIGN's literal "compression → vol expansion" hypothesis **killed cleanly** on forward realized vol (both C2 readings, with and without the `vol_tercile` match). **`ribbon_direction_magnitude` confirmed** (Tier 3): compression predicts a larger forward 21d `\|return\|` (magnitude, not signed direction) — C2 `−0.2471%` CI `[−0.3976%,−0.0927%]`, clears cost at every reading, survives its own reversal-robustness check (2026-09-23, +7.6%, if anything strengthened). Trend-conditional and unconditional signed-direction cells are both inconclusive — the trend-conditional cell notably does **not** confirm DESIGN's own stated prior that it should show more signal than the unconditional cell. **Whole-grid FDR (2026-09-23): `ribbon_direction_magnitude` survives** (swept in by the step-up rule, p=0.0077) but **not promoted to Tier 2** — capped by its own magnitude-vs-signed-return actionability gap, independent of FDR status. | 5 declared, deduplicated to 4 for the whole-grid pass: the two vol-expansion readings (with/without `vol_tercile` match) are the same hypothesis tested two ways, an explicit internal-consistency check per this module's own pre-registration, merged into 1. | `ribbon_direction_magnitude`: 0.3163%/yr hurdle vs. point −2.97%/yr, near edge −1.11%/yr — clears at every reading, with the magnitude caveat named above. | Post-termination "Batch 1" module. Caught and fixed two real `skipna=True` bugs in new label functions (`ribbon_width`, `forward_realized_vol`) before trusting any real-panel numbers. | `PREREGISTRATION.md` M7 entry + 2026-09-23 reversal-robustness addendum; `FINDINGS.md` (1 entry, `ribbon_direction_magnitude`, + 2026-09-23 FDR addendum); `EXPERIMENTS.csv` (6 rows: 5 primary + 1 reversal-robustness). |
| **M13** — Context conditioning | 12th, post-termination Batch 1, 2026-09-22 (PR #83) | Sliced M1's `above_sma_200` C2 delta by VIX-percentile and breadth-percentile regime terciles. 2 of 4 cells (`vix`/bottom, `breadth`/top) clear zero-exclusion and cost, barely — but all 4 point estimates cluster tightly around M1's own whole-sample sign and magnitude, read by this module's own write-up as "probably the same weak baseline effect exposed by regime-slicing, not a real interaction," not oversold. Tiered 3 mechanically (this study's own convention), with that skepticism carried explicitly in the prose. Not part of this pass's 5 whole-grid FDR survivors (all 4 cells miss, ranks 12/13/37/43 of 50). | 4 declared, run as 4 — disjoint VIX/breadth tercile subpopulations of the same underlying `above_sma_200` cell, treated as a restricted-subpopulation test (same convention as M6.2's within-restriction cells), not a literal duplicate of M1's own already-counted cell. | `vix`/bottom: 0.689%/yr hurdle vs. point −3.82%/yr, near edge −0.87%/yr — clears, barely. `breadth`/top: 0.640%/yr hurdle vs. point −4.66%/yr, near edge −0.88%/yr — clears, barely. | Post-termination "Batch 1" module. Earnings/index-membership/sector-momentum sub-questions deferred (no earnings-date table exists; index-membership and sector-momentum facets deferred as a first-slice cut). | `PREREGISTRATION.md` M13 entry; `FINDINGS.md` (2 entries, `vix`/bottom and `breadth`/top, both carrying the "argue against" reasoning in full); `EXPERIMENTS.csv` (4 rows). |

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

## Whole-grid FDR pass — RUN 2026-09-17, RE-RUN 2026-09-20, RE-RUN 2026-09-23. Result: 5 of 50 survive at q=0.10 (1 at q=0.05) — first survivors in the study's history, but no cell reaches Tier 2.

**Verdict, up front (2026-09-23, current): at q = 0.10, 5 of 50 deduplicated tests
survive Benjamini–Hochberg correction; at q = 0.05, 1 of 50 survives.** This is a
change from every prior pass in this study, all of which found zero survivors. The
survivor set: `slope_pctile_21_sma_50` (M6.3, p=0.00005, clears both q=0.10 and
q=0.05 by a wide margin — the sole q=0.05 survivor), `dist_from_52w_low`@126d (M18,
p=0.0047), `ribbon_direction_magnitude` (M7, p=0.0077), `stack_fully_bearish` (M2,
p=0.0086), `above_sma_20` (M1, p=0.0090). **None of the 5 reaches Tier 2** — each has
its own independent reason to stay capped, checked individually below. The **headline
statistical fact changes** (it is no longer true that nothing survives this study's
own FDR correction); the **headline actionable conclusion does not** (no cell in this
study clears every bar DESIGN §9.2 sets for Tier 2). Both halves of that sentence
matter and neither should be dropped when this section is cited elsewhere.

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

**N_tests = 5 + 3 + 3 + 1 + 2 + 6 + 11 + 4 + 4 + 3 + 4 + 4 = 50** — down from a naive
raw sum that would run well past 140 once every module's raw declared grid is added in
without deduplication. **This is the most generous-to-survivors count achievable from
this study's own stated independence findings** — every deduplication decision above
removes a test, which only *raises*
each remaining test's BH threshold (easier to survive), which only strengthens the
finding that 5 cells now survive: even the most favorable-to-survivors count actually
produces survivors this time. **Stress-tested (2026-09-23) against three alternative
reasonable dedup counts (N=47, not splitting M6.1's 4 lookbacks into a single
representative cell; N=50, this pass's own count; N=51, not merging M7's two
vol-expansion readings): identical 5-cell survivor set and identical rank-1 p-value in
every case** — the survival of `slope_pctile_21_sma_50` in particular is not sensitive
to any of this pass's specific dedup judgment calls.

**Full ranked table (50 tests, p-value ascending, 2026-09-23 re-run):**

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

**(1) Does anything reach Tier 2?** No. Per DESIGN §9.2 (Tier 2 = "survives C2 and
FDR, but fails one of: universe generality, holdout, or cost"), each of the 5
survivors was checked individually and each has its own reason it cannot be promoted,
none of them simply "FDR used to be missing and now isn't":
- **`above_sma_20`** (M1) fails cost outright — a substantive failure this study has
  never treated as compatible with Tier 2, FDR status notwithstanding.
- **`stack_fully_bearish`** (M2) is capped by DESIGN §7.3's pre-existing, explicit
  survivorship cap on weak/bearish-state buckets, which applies "regardless of what the
  statistics show."
- **`ribbon_direction_magnitude`** (M7) is capped by its own magnitude-vs-signed-return
  actionability gap — a real limitation independent of any statistical test.
- **`dist_from_52w_low`@126d** (M18) and **`slope_pctile_21_sma_50`** (M6.3) are both
  **newly flagged in this pass** (not previously considered) as touching weak/
  beaten-down-state-adjacent populations plausibly vulnerable to the same delisted-
  ticker survivorship ceiling §7.3 already names for M1/M2 — extended here by analogy,
  not literal enumeration, so treated as an open caveat rather than a resolved cap.
  `slope_pctile_21_sma_50`'s case is partially mitigated by its own "roughly symmetric"
  tail shape; neither cell has a direct decomposition test run to settle it. Both also
  remain capped by the pre-existing holdout/universe-tier infrastructure gap common to
  every Tier-3 cell in this study.

Full per-cell reasoning: `FINDINGS.md`'s 2026-09-23 addenda on each of the 5 cells.

**(2) Does the study's statistical headline change?** Yes, and this should not be
understated: **"zero of any deduplicated grid this study has ever assembled survives
BH correction" was true through the 2026-09-20 pass and is no longer true.** Whether
that headline fact matters more than the unchanged Tier-2 answer is a framing choice
for whoever reads this next (`REPORT.md`'s executive summary has been flagged for a
2026-09-23 revision to state both halves plainly, not just the tier answer).

**Not silently re-tiered in `EXPERIMENTS.csv` or `FINDINGS.md`** at any point in this
history (this study's own no-silent-edits convention, `PREREGISTRATION.md`'s own
precedent for tier changes) — a dated addendum was added to each affected
`FINDINGS.md` entry, and a summary row logged in `EXPERIMENTS.csv` for each pass
(`whole_grid_fdr_pass_2026_09_17`, `whole_grid_fdr_pass_2026_09_20`,
`whole_grid_fdr_pass_2026_09_23`).

**Historical record (trigger condition, now resolved):**

**Trigger condition (2026-09-09, for reference):** the pass runs at whichever comes
first —
1. **Before any module is promoted above Tier 3.** Tier 2 requires "survives C2 and
   FDR" (DESIGN §9.2) — that's not assignable without the correction having actually
   run, so a Tier-2-or-above call on any facet is a hard trigger, not just a milestone.
2. **Minimal-core completion** — once M2, M5, and M6.2 have also been attempted
   (joining M1, M4, and now M11). **This is the condition that fired.**

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
| §7.5 | 3 (group-level) | Already deduplicated at declaration — the unit is the group (focal + its whole neighborhood), not the 11 individual lookback cells. |
| M2 | 2 (part a primary) + 8 (part b attribution coefficients) | Part (a)'s 2 cells are declared independent (bullish/bearish are not mirrors of each other, unlike M1). Part (b)'s 256 subsets are explicitly not counted (DESIGN's own attribution framing) — only the 8 linear coefficients are. |
| M5 | 6 (group × direction) | Declared independent at the group level, same convention as §7.5 (whose neighbor groups this module reuses directly) — a group × direction pair is one test, not one per lookback. |
| M6.2 | 12 (3 sub-questions × 2 lookbacks × 2 facets) | Declared independent at declaration (rising-within-above and rising-within-below are different row populations, not algebraic mirrors the way M1's above/below pair turned out to be) — **not yet verified**, same caveat as M4's own unresolved correlation check; the FDR pass should confirm this before trusting the 12, not just cite the declaration. |
| M18 | 4 (2 features × 2 horizons) | Checked at declaration (2026-09-20), not deferred: `dist_from_52w_high`/`dist_from_52w_low` per-date median Spearman = 0.4677 — not redundant. Not part of the minimal-core list; added post-termination (see "Modules run" above). |
| M6.1 | 4 (lookback grid) | Checked during the 2026-09-23 whole-grid pass, not at declaration: `slope_log_21` cross-lookback median Spearman 0.35–0.88, below the 0.89 bar — kept independent. |
| M6.3 | 3 (primary lookback grid) + 3 (excl-large-move) + 2 (reversal-robustness) declared, 3 counted | Robustness-companion rows excluded (same convention as M2/M6.2/M18's own reversal rows); cross-lookback correlation bounded via M6.1's own check. |
| M7 | 5 declared, 4 counted | The two vol-expansion readings merged to 1 — same hypothesis, two match-column variants, an explicit internal-consistency check, not two independent tests. |
| M13 | 4 (VIX/breadth tercile × top/bottom) | Disjoint subpopulations of M1's `above_sma_200` cell — restricted-subpopulation test, not a literal duplicate. |

Every minimal-core module has contributed a row, plus M18 and Batch-1's four
post-termination modules (M6.1, M6.3, M7, M13) — this table is complete against the
2026-09-23 re-run.

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

**Superseded 2026-09-17**: everything above this line in this section was written
while the pass was still deferred — reasoning about *why* deduplication would matter,
before actually doing it. The completed pass (top of this section) carries out exactly
the two dedup items this historical record flags (M1's mirror collapse, M4's
SMA50/SMA200 correlation check — resolved using the 2026-09-16 Track A sweep's own
numbers) plus a third the record didn't yet know to look for (§7.5 vs. M4's bit-exact
duplicate). Kept here for the reasoning trail, not as an open item anymore.

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

**Post-termination update (2026-09-23): Batch 1 (M6.1, M6.3, M7, M13) does not reopen
this verdict either, but it does change the whole-grid FDR pass's own headline for the
first time.** Four more post-termination modules ran in parallel (`HANDOVER.md`'s
2026-09-21 triage), each pre-registered and run through the same discipline as every
prior post-termination addition. The consolidated whole-grid FDR re-run (N=50, see
"Whole-grid FDR pass" above) found **5 cells now survive Benjamini–Hochberg correction
at q=0.10 (1 at q=0.05)** — the first survivors this study's own correction has ever
produced, anchored by M6.3's `slope_pctile_21_sma_50` (p=0.00005). **This does not
change the study's Tier-2-or-above count**: each of the 5 survivors was checked
individually against DESIGN §9.2's full Tier-2 bar and each has its own independent
reason to stay at Tier 3 (cost failure, DESIGN §7.3's pre-existing survivorship cap, a
cell-specific actionability gap, or a newly-surfaced, not-yet-resolved survivorship-cap
analogy — see the FDR section above for the full per-cell reasoning). **Still 0 Tier
1/2.** What changes is honesty about the statistical fact itself: this study can no
longer say "nothing has ever survived our own FDR correction," only "nothing has
survived it at a tier that would make it actionable." Both halves of that distinction
are carried forward into `REPORT.md` (flagged for revision, not yet updated as of this
note) rather than only the tier-count half. The single most consequential open
follow-up this surfaces — more consequential than the pre-existing holdout/
universe-tier gap — is a rising-tail-only vs. falling-tail-only decomposition of
`slope_pctile_21_sma_50`, which would either resolve or sharpen the newly-named
survivorship-cap concern on this study's own first FDR survivor.

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