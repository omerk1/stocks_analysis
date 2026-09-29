# Modeling phase — insights from the completed moving-averages study

**Date:** 2026-09-28. **Scope:** what the MA study (`docs/features/moving-averages/`,
22 modules, 221 `EXPERIMENTS.csv` rows, six whole-grid FDR passes, closed 2026-09-25)
actually established, and what that implies for the modeling phase sketched in the
ideas inbox (`docs/modeling/IDEAS.md`, referenced below by its own section numbers).
This document complements the inbox; it does not restate it. Every number traces to
`EXPERIMENTS.csv` (cited by `cell_id`), `FINDINGS.md`, `PREREGISTRATION.md`,
`STATUS.md`, `REPORT.md`, or a file in `src/signals/moving_averages/`.

**Track discipline carried over:** everything under "Track B" below is a pre-registered,
C2-controlled, block-bootstrapped result. Everything under "Track A" is an uncontrolled
screen and is cited only as feature-selection evidence, never as an effect size.

**The honest headline, before any table:** the study's single Tier-2 effect is
−0.248% per 21 trading days (`slope_magnitude_humped_test_sma50`). The largest
return-based point estimate in the whole grid is +1.83% per 21d on 505 events
(`pattern_context_reclaim_sma50_vcp_only`). The largest |rank-IC| in a 348-cell Track A
sweep is 0.038. Every "clears cost" verdict rests on a 10 bps round-trip convention and
a linear ×12 annualisation (`stats/costs.py::annualize`). Several FDR survivors are
mechanism reads (drawdown depth, run survival), not return claims. A model built on
this feature family is working in a weak-signal regime and should be evaluated as such.

**Correction (2026-09-29) — read before any table below.** This document was written
before the review's re-runs landed (`STATUS.md` 2026-09-29 addenda; PR #121). Two cells it
treats as live evidence are withdrawn, and the whole-grid FDR survivor set is now 2 of 107,
not 11. The text below is left as written; apply these overrides:

| where | as written | now |
|---|---|---|
| §1.1 M6.4 row; §1.2 ER-tercile row; §4 "Survival, not return" | SMA20 runs outlast the GBM null by +0.07 to +0.11 | **Withdrawn.** The null pooled rising and falling runs; with a direction-matched null 0 of 12 strata depart (+0.008 to +0.023, inside ±0.04). ER-tercile keeps a two-lookback departure only, close to circular. Not evidence for a hazard head. |
| §1.1 M14 VCP row; §1.4 M15 row; §4 "Fat left tail"; §2.2 feature #11 | +1.83%, FDR q=0.05, 68.9% hit rate, skew −0.77; "two strongest cells anti-correlated" | **Withdrawn.** The flag used the future breakout. As-of-safe: +0.85% [−0.10%, +1.88%], 402 events / 335 dates, hit rate 60.0%, skew −0.21. Tier 4. M15 now compares the Tier-2 cell with a null. |
| §1.1 FDR survivors | 11 of 107 | **2 of 107** at q=0.10 and q=0.05: M6.6 drawdown and M6.3 Tier-2. M12, M18@126d, M7, M2, M1 unchanged in value, no longer clear BH. |
| §2.2 feature #3 (slope-run age) | justified by M6.4 | Keep only as a cheap state feature; no study evidence behind it now. |
| §2.2 feature #11 (VCP flag) | "extension-robust, FDR q=0.05" | Drop from v1, or keep as an untested candidate built on the as-of-safe flag (`attach_breakout_dates`). |
| §4 "Fat left tail" exhibit | M14 VCP | Use M2 `stack_fully_bullish` instead: flat mean, +1.2pp hit rate, skew −0.35. |
| §7 `modules/pattern_context.py` | "reuse the … breakout-confirmed definition" | Reuse the 2026-09-29 as-of-safe definition only; the status filter selected on outcome. |
| §7 `stats/survival.py` | "fix σ to an autocorrelation-aware estimator" | Direction-match the null (done). The σ caveat runs the other way (lag-1 autocorrelation −0.05) and is second-order. |
| §8 E3 | VCP event-population experiment | Demote. The as-of-safe cell spans zero on thin data; run only as a cheap check, not a headline experiment. E1 and E2 stand. |
| §9 rows on F8 and §11 "only the VCP reclaim is alert-shaped" | VCP as the study's strongest event | Hold. No event in the study is currently alert-grade. |

Add to §5: the universe is survivorship-selected (no delisted ticker has any daily bar
inside 2010–2021), and the synthetic gate plants +3%/21d and never exercises C2, the
bootstrap, or `p_value_from_ci` (`VALIDATION_2026-09-28.md` §A, §B.4).

---

## 1. What the study established, at the confidence the evidence supports

### 1.1 Track B — Tier 2 and the FDR survivor set (N=107, q=0.10, 2026-09-25 pass)

Units: return cells are per-21-trading-day C2 deltas unless the row says otherwise.
"n_dates" is the effective N the study reports (distinct contributing dates). "Capped
by" is the specific reason the cell is not Tier 1/2. "Usable as" is this document's
own call for the modeling phase.

| cell_id (module) | Tier | statistic | point | 90% CI | n_events / n_dates | shape (if logged) | capped by | usable as |
|---|---|---|---|---|---|---|---|---|
| `slope_magnitude_humped_test_sma50` (M6.3) | **2** | C2 delta, middle deciles {4,5} minus tails {0,1,8,9} of per-date pctile of `slope_log_21_sma_50`, `fwd_ret_21` | −0.248% | [−0.354%, −0.153%] | 219,700 / 2,747 | — | holdout + universe tier only (infrastructure) | **feature** (per-date slope percentile, both tails) and **baseline** the model must beat |
| `slope_persistence_vol_tercile_sma20_t0/t1/t2` (M6.4) | 3 | KM survival at 21d minus GBM-null survival | +0.106 / +0.073 / +0.067 | envelopes ≈ ±0.028 | 4,772–5,466 runs / 1,857–2,018 | — | GBM null's σ from the same (possibly autocorrelated) series; unresolved | **target-design evidence** (run age of `slope_log_21_sma_20 > 0` is informative); not a return claim |
| `ribbon_agreement_extreme_drawdown` (M6.6) | 3 | C2 delta on `fwd_mdd_21`, state 5 vs 0 of {10,20,50,100,200} slope signs | +0.654pp shallower | [+0.438pp, +0.887pp] | 406,663 / 2,747 | — | drawdown read, companion `fwd_ret_21` cell spans zero | **target-design evidence** (path/drawdown labels carry signal the mean does not) + feature (ordinal 0–5 state) |
| `pattern_context_reclaim_sma50_vcp_only` (M14) | 3 | C2 delta, `above_sma_50` reclaim inside a confirmed VCP breakout vs. not | +1.83% | [+1.06%, +2.77%] | 505 in-context events / 409 dates (131 bootstrap-contributing) | hit 68.9% vs 61.3%; W/L 1.134 vs 1.132; skew −0.770 vs −0.065 | reversal check could not run (`InsufficientBlocksError`, 112 dates < 126) | **feature** (rare event flag) with a fat-left-tail caveat; too thin to be a baseline |
| `reclaim_durability_dollar_volume_sma50` (M12) | 3 | C2 delta, top vs bottom dollar-volume tercile among SMA50 reclaims | −0.870% | [−1.381%, −0.402%] | 13,880 / 2,468 | — | no PIT market-cap control; size/illiquidity premium equally plausible | **feature** only if a PIT size control exists; otherwise a **confound proxy** |
| `dist_from_52w_low_h126` (M18) | 3 | C2 decile spread, `fwd_ret_126` | +2.50% per 126d | [+1.10%, +4.02%] | 1,069,515 / 2,643 | — | survivorship-adjacent (beaten-down bucket), argued by analogy, never tested | **feature** at long horizons; carries §7.3 exposure |
| `ribbon_direction_magnitude` (M7) | 3 | C2 decile spread on `abs(fwd_ret_21)`, ribbon-width decile 9 vs 0 | −0.247% | [−0.398%, −0.093%] | 175,152 / 2,549 | — | magnitude, not signed return | **target-design evidence** (compression predicts the size of the move, not its direction) + feature for a vol/barrier model |
| `stack_fully_bearish_h21` (M2) | 3 | incremental C2 diff vs `above_sma_50`; standalone C2 +0.474% [+0.161%, +0.776%] | +1.055% incremental | [+0.419%, +1.740%] | 40,102 / 2,696 | hit 63.85%; W/L 1.32; skew +0.99 | DESIGN §7.3 survivorship cap (bearish bucket, zero delisted history pre-2024) | **feature** (full-stack state) with the survivorship caveat stamped on it |
| `above_sma_20` (M1) | 3 | C2 delta | −0.215% | [−0.350%, −0.079%] | 751,406 / 2,744 | — | fails cost (30.4 flips/ticker-yr → 3.04%/yr hurdle) | **baseline** (cheap state feature); not a standalone signal |

Flapping note (`STATUS.md`, `REPORT.md` §4): `ribbon_direction_magnitude`,
`stack_fully_bearish_h21`, and `above_sma_20` entered/left the survivor set three times
across N=50→79→99→107 with no new evidence. Treat FDR membership at the margin
(p≈0.008–0.009 against thresholds of 0.008–0.010) as fragile.

### 1.2 Track B — real at C2 but not an FDR survivor (Tier 3)

| cell_id (module) | point / CI | n_dates | why it matters for the model |
|---|---|---|---|
| `dist_pct_sma_20_h21`, `dist_atr_sma_20_h21`, `dist_z_sma_20_h21` (M4) | −0.464% / −0.372% / −0.374% per 21d decile spread; all CIs exclude zero | 2,747 / 2,747 / 2,729 | SMA20 extension is a real, weak, cost-failing effect (hurdle ≈2.5%/yr vs. near-edge ≈1.1–1.6%/yr). The three normalisations are 0.94–0.98 correlated; one feature, not three. |
| `above_sma_50` (M1) | −0.183% [−0.341%, −0.031%] | 2,746 | Same shape as SMA20, lower turnover (18.0 flips/ticker-yr). |
| `dist_pct_sma_20_h5` (M11) | rank-IC −0.0138 [−0.0225, −0.0041]; the one M11 cell that clears cost after the ×50.4 annualisation | 2,996 | The shortest horizon clears cost — the shape a short-term-reversal generator would produce (`PREREGISTRATION.md` M11 2026-09-10 correction). A model with `mom_1_0` in the baseline should expect this to shrink. |
| `slope_cond_extension_x_slope_sma50_top` (M6.2) | −0.592% [−1.047%, −0.175%]; reversal-robust −0.550% | 2,747 | Interaction: within the top `dist_atr_sma_50` decile, a rising 50-day is *worse* than a falling one. Rare falling subgroup (7.1%). Track A follow-up (2026-09-18 surface) found it is a lone bright pixel across deciles, not a gradient. |
| `slope_cond_touch_x_slope_sma50_from_above` (M6.2) | −5.75pp hold-rate; reversal-controlled −3.33pp [−8.18pp, +1.25pp] | 2,410 | Does not survive reversal control. Do not build a feature on it. |
| `dist_from_52w_low_h63` (M18) | +0.956% [+0.128%, +1.843%] per 63d | 2,706 | Effect grows with horizon (63d → 126d); fails cost at 63d. |
| `slope_magnitude_humped_test_sma20` / `_sma200` (M6.3) | −0.117% / −0.193%; SMA200 attenuates 80.5% under reversal control, CI spans zero | 2,747 | The Tier-2 SMA50 cell's neighbours agree in sign (plateau holds on sign) but SMA200 is a reversal artefact. Use the SMA50 percentile; treat SMA20/SMA200 as weaker copies. |
| `context_vix_bottom`, `context_breadth_top` (M13) | −0.318% / −0.388%; other two regime buckets span zero | 1,195 / 882 | All four buckets sit within a narrow band around M1's own `above_sma_200` (−0.215%). The module's own read: no real regime interaction. Regime restriction also halves effective N. |
| `reclaim_hold_rate_relative_volume_sma200` (M12) | +3.35pp [+0.44pp, +6.37pp] | 2,177 | The one cell supporting "reclaim on high volume holds better", at SMA200 only. Mechanism read, single lookback. |
| `nonlinearity_macd_histogram_incremental_ic_h21` (M17) | +0.0089 [+0.00002, +0.0187]; FDR rank 34/107, p=0.115 | 2,747 | MACD histogram is not redundant with `dist_pct_sma_50`/`slope_log_21_sma_50`/`mom_12_1` (corr +0.30 / −0.25), but the incremental IC barely excludes zero and no reversal control was run. |
| `slope_persistence_er_tercile_*_t2` (M6.4 companion, not counted) | +0.174 / +0.103 / +0.091 / +0.089 at SMA20/50/150/200 | 2,109 / 1,699 / 1,116 / 895 | High-efficiency-ratio runs persist beyond the null at every lookback — the cleanest plateau in M6.4. Same null-calibration caveat. |
| `sma_dropoff_decisive_sma200_down` (M6.5 companion, not counted) | +1.03% [+0.23%, +1.72%] | 2,440 | Flagged, not promoted; reversal untested. Ignore for v1. |

### 1.3 Track B — strong nulls: do not spend features here

| module | what was killed | the number that kills it | model implication |
|---|---|---|---|
| **M5** touch/test/bounce | MAs as support/resistance, real MA vs. unwatched synthetic neighbour, 6 cells | largest CI edge 0.61pp vs a 2pp floor; every CI spans zero; smallest cell 7,257 events / 2,102 dates | No "distance to MA as a level" feature in the LRP sense (IDEAS §3). MA proximity is an extension feature, not a support level. Caveat: close-only touches, no intraday wick. |
| **§7.5** placebo | SMA200 vs {187,193,207,213}; SMA50 vs {47,53}; EMA21 vs {19,23} | focal SMA200/SMA50 C2 CIs span zero; EMA21 real (−0.459%) but indistinguishable from EMA19/23 | Lookback is a trend-length parameter, not a watched level. Give the model a few lookbacks, never "the 200-day" as a special feature. |
| **M3** crossovers | 10 primary + 6 facet cells, golden/death across 5 pairs | all point estimates within ±0.08%; every CI spans zero | Crossover *events* add nothing over the *state*. Encode `fast > slow` state and its age; drop "days since cross" as a primary feature (IDEAS §2b lists it — keep it only as a cheap alias of state age). |
| **M8** family horse race | SMA/EMA/WMA/HMA/DEMA/KAMA/VWMA at matched lag | 7 cells cluster at −0.127% to −0.206%; White's Reality Check p=0.193; HMA/KAMA turnover 34–36 flips/ticker-yr vs 15–20 | One family (SMA or EMA) is enough. Fancy kernels add turnover, not signal. |
| **M10** timeframe | daily vs Fridays-only vs weekly-native SMA | sampling-frequency gaps −0.02/+0.02/−0.03pp against a 0.10% floor | Weekly MAs are the daily MAs at a different lookback. Do not build weekly features as a separate family. |
| **M9** regime-conditional lookback | ER-regime switching vs best fixed lookback (EMA50), OOS 2017–2021 | diff −0.0091% [−0.072%, +0.053%]; indistinguishable from KAMA | Do not let a regime gate choose lookbacks. Side finding: ER regime is memoryless at 21d (40.32% vs 40.46% base rate); ADX regime persists (+10.4pp). If a regime feature is used, ADX carries state, ER does not. |
| **M6.1** slope vs momentum | incremental IC of `slope_log_21_sma_k` over `mom_12_1`, 4 lookbacks | −0.016 / +0.002 / −0.014 / +0.001, all span zero | Raw log-slope is not distinguishable from momentum. The Tier-2 cell works on the *percentile* and the *magnitude* (both tails), which is a different object. |
| **M18** `dist_from_52w_high` | 63d and 126d | C1 −1.93% / −4.03% → C2 −0.38% / −0.67%, both span zero | The strongest Track A cell in the study vanished entirely under momentum matching. Proximity to the 52-week high is momentum re-encoded. |
| **M2** `stack_fully_bullish` | incremental vs `above_sma_50` | +0.013% [−0.066%, +0.087%] | The bullish full stack adds nothing over one MA. Shape: hit-rate +1.21pp, skew −0.35 (wins slightly more often, loses larger). |
| **M1** run length; `above_sma_200` | 24 age-bucket cells; SMA200 state | 1 of 24 excludes zero with opposite-signed neighbours; SMA200 CI [−0.42%, +0.005%] | State *age* as a feature failed the plateau rule. SMA200 is the study's recurring anomaly (three independent oddities, never resolved). |
| **M7** compression → vol expansion | forward realized vol | +0.021% [−0.007%, +0.057%] with vol match | Compression does not predict forward *vol*; it predicts the size of the forward return (`ribbon_direction_magnitude`). |
| **M17** RSI, stochastics | incremental IC at 21d/63d | all CIs span zero; RSI vs `dist_z_sma_20` corr 0.86 | RSI is nearly `dist_z`. Keep at most one. RSI's sign flips positive near the MA (+0.90%, CI spans zero) — a tree can find this if both are present; not worth hand-building. |
| **M14** pooled pattern context | reclaim inside any of 7 pattern types | −0.40% at C2 → −0.20% [−0.54%, +0.17%] once `ext_tercile` is matched (52% attenuation) | "Inside any pattern" is extension re-encoded. Only VCP survived the extension control. |

### 1.4 Track A — screens that inform feature selection (never effect sizes)

| look (date, `EXPLORATION_LOG.md`) | what it says |
|---|---|
| 348-cell IC sweep (2026-09-16) | max mean rank-IC magnitude 0.038 (`dist_from_52w_low`@126d); top-25 mostly 0.018–0.022. SMA-distance IC peaks at 21–42d and is absent from the top 25 past 42d; 52-week features strengthen out to 126d. |
| Same sweep, redundancy | `dist_pct` vs `dist_atr` 0.96–0.98 at every lookback and family; `dist_z` vs `dist_pct` 0.94 (SMA20) → 0.89 (50) → 0.74 (150) → 0.69 (200); `slope_log_5_ema_200` vs `dist_pct_ema_200` 0.986; `slope_log_63` decorrelates from distance (0.18 at SMA20, 0.32 at EMA20). |
| Distance × slope surface (2026-09-18) | `slope_log_21` vs `dist_atr` correlation 0.34→0.80 (SMA 20→200), 0.59→0.93 (EMA). No smooth 2D interaction anywhere; M6.2's SMA50 top-decile cell is a lone pixel. |
| Kernel-space scan, M16 (2026-09-24) | 23 MA rules form one cluster at cosine ≥0.80; 10 clusters at ≥0.95, ordered by effective lookback (centroid), not by indicator type. `slope_log_21_sma_200` sits at centroid 109.5 vs 66–82 for `dist_pct_sma_200`/`crossover_sma_50_sma_200`. |
| M15 overlap check (2026-09-25) | VCP reclaims fall in M6.3's extreme-slope tail 27.1% of the time vs 40.0% unconditionally (enrichment 0.68) — the two strongest cells are anti-correlated, not redundant. |
| M0.1 atlas (2026-09-07/08) | Era skew shifts were a crash artefact (4% of rows). `dist_z_sma_50` shows a dollar-volume-decile gradient in mean and skew (Candidate C-1) despite per-ticker normalisation — a size/liquidity axis the panel cannot yet separate from market cap. |

---

## 2. Feature-set implications

### 2.1 What the cached panel actually has

`data/features/moving_averages/ma_panel/`, 84 columns (`features/panel.py::build_panel`),
405 tickers, 1,222,605 rows, 2010-01-04 → 2021-12-31, all feature columns already
one-bar-lagged (`apply_lag`, panel.py:58), float32. Families: SMA/EMA at {20,50,150,200};
`dist_pct`/`dist_atr`/`dist_z`/`above` and `slope_log_{5,21,63}` at each; `run_length_bucket_sma_*`
(string buckets); `stacked_sma`/`stacked_ema`; `mom_12_1`, `mom_1_0`, `realized_vol_63`;
`dist_from_52w_high`/`low`; `atr_14`; `sector` (current-state, not PIT). Not in the panel
(module-local only): 10/100-day SMAs (M6.6), EMA 8/10/21 (M3), `ribbon_width` (M7),
`efficiency_ratio`/ADX (M9, `features/regime.py`), MACD/RSI/%K (M17,
`features/oscillators.py`), `relative_volume`/`dollar_volume` (M12, `features/liquidity.py`),
WMA/HMA/DEMA/KAMA/VWMA (M8, `features/kernels.py`), per-date percentiles (M6.3 builds them
in `modules/slope_magnitude.py::prepare`).

### 2.2 Recommended v1 MA-family feature list

The ordering principle from M16 and the IC sweep: **one representative per effective-lookback
cluster per operation (distance, slope, spread), transformed to per-date ranks.** Roughly
a dozen columns replace the 68 numeric MA columns in the panel.

| # | feature | construction | one-line justification |
|---|---|---|---|
| 1 | `slope_pctile_21_sma_50` | per-date `cross_sectional_bucket`/rank of `slope_log_21_sma_50` (as `modules/slope_magnitude.py::prepare`) | The Tier-2 cell. Keep the *rank*, and let the model see both tails (the effect is U-shaped, M6.3). |
| 2 | `abs_slope_pctile_21_sma_50` | rank − 0.5, absolute value | Encodes the U directly so a linear baseline can use it; a tree does not need it. |
| 3 | slope-sign run age of `slope_log_21_sma_20` | `features/state.py::state_run_id`/`days_in_run` on `slope_log_21_sma_20 > 0` | M6.4: runs persist beyond a GBM null at SMA20/50, all vol terciles. Age of the current slope-sign run is the feature, not the sign alone (M1's *state* age failed; M6.4's *slope* run survival did not). |
| 4 | `dist_z_sma_20` (or `dist_pct_sma_20`, one only) | panel | M4/M11: the only extension lookback with a real effect; `dist_z` is 0.94-correlated with `dist_pct` here so either works. Also the extension confound control for every pattern feature (M14). |
| 5 | `dist_z_sma_200` | panel | Keeps a slow-lookback extension that is only 0.69-correlated with `dist_pct_sma_200` (sweep). Carries the SMA200 anomaly; expect little. |
| 6 | `slope_log_63_sma_50` | panel | The one slope window that decorrelates from distance at every lookback (0.18–0.32, sweep). Cheap diversification of the slope cluster. |
| 7 | `ribbon_agreement_state` (0–5 over {10,20,50,100,200} slope signs) | rebuild as in `modules/ribbon_slope_agreement.py` | M6.6: predicts `fwd_mdd_21` (+0.65pp), pairwise slope correlations 0.28–0.89 so it is not one MA in disguise. A drawdown-side feature. |
| 8 | `ribbon_width_pctile` | `features/ribbon.py::ribbon_width_pctile` | M7: compression predicts the size of the forward return (−0.25% decile spread on `abs(fwd_ret_21)`). Directly relevant to a barrier target's reach probability. |
| 9 | `stack_fully_bearish` (price < SMA20 < SMA50 < SMA150 < SMA200) | `modules/stack_minervini.py` construction | M2: +1.06% incremental over `above_sma_50`, hit 63.85%, skew +0.99. Survivorship-capped (§7.3); flag it as such in the feature registry. |
| 10 | `dist_from_52w_low` | panel | M18: +0.96% (63d), +2.50% (126d) C2 decile spread, reversal-robust. Matters only at H ≥ 63. |
| 11 | `vcp_reclaim_event` (`above_sma_50` reclaim within 21d of a confirmed VCP breakout, confidence ≥ 0.7) | `modules/pattern_context.py` joined to the `pattern_matches` table | M14: +1.83–1.99% per 21d, extension-robust, FDR q=0.05. 505 events in 12 years: an event-population feature, not a dense column. |
| 12 | `macd_histogram` (12,26,9) | `features/oscillators.py::macd_components` | M17: incremental IC +0.0089 over the MA block, correlation −0.25 with `slope_log_21_sma_50`. Marginal; include and let importance decide, as IDEAS F4 already says. |
| 13 | `dollar_volume` per-date tercile | `features/liquidity.py::dollar_volume` | M12's strongest cell, but only as a **size/liquidity control** until PIT market cap exists (§2.4). |
| 14 | `adx_14` regime (`features/regime.py::adx_regime`) | M9 | The regime construction that actually persists (+10.4pp). Use as an interaction gate, not as a lookback selector (M9 killed that). |

Controls that belong in every feature set and every baseline (§3): `mom_12_1`, `mom_1_0`
(reversal), `realized_vol_63`, `sector`, and `ext_tercile` (= `dist_pct_sma_50` tercile).

### 2.3 Dropped, and why

| dropped | evidence |
|---|---|
| Any second distance normalisation at the same lookback (`dist_pct` + `dist_atr` + `dist_z` together) | 0.94–0.98 pairwise correlation at SMA20 (M4 2026-09-09; sweep 2026-09-16). |
| `slope_log_5_*` on EMAs | 0.986 correlation with `dist_pct` at EMA200 (sweep); it *is* distance. |
| `above_sma_k` flags beyond one lookback | M1: mirror cells, three independent numbers; SMA200 anomalous; §7.5 shows no lookback is special. |
| Golden/death cross event flags, days-since-cross | M3: 16 cells, all span zero. State + age already covers it. |
| WMA/HMA/DEMA/KAMA/VWMA columns | M8: Reality Check p=0.193; 2× turnover for HMA/KAMA. |
| Weekly-timeframe MAs | M10: sampling frequency effect < 0.03pp. |
| Run-length bucket of `above_sma_k` (state age) | M1: plateau failure across 24 cells. Keep slope-run age (M6.4) instead. |
| `dist_from_52w_high` | M18: C2 CI spans zero at both horizons; the C1 effect was momentum. |
| Distance-to-MA as a *support level* input to an LRP feature (IDEAS §3) | M5: 6/6 cells killed against synthetic neighbours; §7.5 placebo. |
| RSI and stochastic %K as separate columns when `dist_z_sma_20` is present | M17: RSI vs `dist_z_sma_20` corr 0.86; incremental IC spans zero at 21d and 63d. |
| VIX/breadth regime × MA-state interactions | M13: all four buckets sit around the whole-sample number; effective N falls to 786–1,195 dates. |
| ER-regime lookback switching | M9 killed; ER regime memoryless at 21d. |

### 2.4 Needs new infrastructure before it can be a feature

| feature | blocker | where the study hit it |
|---|---|---|
| Point-in-time market cap / size decile | `shares_outstanding` history: yfinance 2016+, survivors only (IDEAS §7). SEC EDGAR bulk company-facts ingest has since landed on `main` (commits 8915910, a35b57f) — coverage against the 2010–2021 PIT universe is not verified in this document. | M12's `dollar_volume` cell capped for exactly this; C-1 candidate in `EXPLORATION_LOG.md` never disentangled. |
| Earnings dates | no table anywhere in the DB | M6.3 substituted a large-move proxy; M13 deferred; DESIGN §7.4 unaddressable. For a barrier target this is the largest single gap (IDEAS §3 already says so). |
| Intraday (wick) touches | close-only bars in the touch detector (`features/touch.py`) | M5's named caveat. Only matters if an LRP feature is rebuilt on intraday data. |
| Point-in-time sector | `ticker_sector` is a current snapshot | Every C2 match in the study used a non-PIT sector column (`panel.py` docstring). Same leak in a model's sector feature. |
| MFE / MAE / barrier hit times | `labels/path_metrics.py` has only `forward_max_drawdown` | Needed for the barrier surface (IDEAS §1). |
| Delisted-ticker history before 2024 | zero rows (DESIGN §7.3, §12) | Every bearish/weak-state feature (rows 9, 10 in §2.2) is survivorship-exposed. |

---

## 3. Baselines the model must beat

The study's C0→C1→C2 waterfall is the core argument for why "beats the unconditional
base rate" is not evidence (M1, `PREREGISTRATION.md` 2026-09-09; `REPORT.md` §3):

| cell | pooled (C0 leg) | C1 (date-matched) | C2 (date + mom + vol + sector) | shrink |
|---|---|---|---|---|
| `above_sma_20` | −0.575% | −0.273% | −0.215% | 63% of the gross effect is market and factor exposure |
| `above_sma_50` | −0.559% | −0.325% | −0.183% | 67% |
| `dist_from_52w_high`@126d (M18) | — | −4.03% | −0.67% [−2.63%, +1.21%] | 100%: the C1 effect *was* momentum |
| `pattern_context_reclaim_sma50` pooled (M14) | — | — | −0.40% → −0.20% (spans zero) once `ext_tercile` is added | extension explains half |

Translate the study's control tiers into harness baselines, in this order. Each later
baseline must be beaten by the model on the same folds, with a block-bootstrap CI on the
difference (`stats/inference.py::block_bootstrap_group_diff` is the existing primitive
for exactly this comparison).

| baseline | construction | what the study's tier it mirrors |
|---|---|---|
| B0 unconditional | per-date base rate of the target | C0. Beating it proves nothing (DESIGN §6.1). |
| B1 date-demeaned | per-date cross-sectional mean removed from the target; predict the residual | C1. Removes the market's own move on the same day. Any model that only learns "the market went up" beats B0 and ties B1. |
| B2 factor-matched | target regressed per date on `mom_12_1` tercile × `realized_vol_63` tercile × `sector` cell means (or a small per-date OLS on the continuous versions) | C2. This is the tier every kill criterion in the study was evaluated on. A gradient-boosted model given only these four columns is the honest B2. |
| B3 reversal-augmented | B2 + `mom_1_0` (`rev_tercile`) | The 4-column C2. It killed `touch_x_slope` (M6.2, −40%), `dollar_volume`/SMA20 (M12, −47%), `slope_pctile_21_sma_200` (M6.3, −80%), and attenuated `stack_fully_bearish` by 32%. |
| B4 extension-augmented | B3 + `dist_pct_sma_50` tercile | Killed M14's pooled cell. Any pattern/level feature must beat this one. |
| B5 single-best-study-feature | B4 + `slope_pctile_21_sma_50` (both tails) | The Tier-2 cell as a model. A many-family model that cannot beat one column is not adding information. |

Why per-date matching and not just a factor column: the study's C2 is a *stratum* match
(`stats/controls.py::stratum_deltas`), so a stratum with only events or only controls
contributes nothing and row loss is real — M1 lost 38–52% of rows at 3 match columns and
75–77% at 4 (`docs/backlog.md`, M1 entry). A regression-style B2 keeps every row; the
harness should report both the matched and the regression version of B2 once to confirm
they agree before standardising on the cheaper one.

---

## 4. Target and label design

What exists: `labels/forward_returns.py::forward_return` (close-to-close, per ticker),
`forward_realized_vol`, and `labels/path_metrics.py::forward_max_drawdown` (worst low
touched over H days relative to today's close). No MFE, no barrier hit time, no
first-touch ordering. The barrier surface in IDEAS §1 needs all three.

Evidence for a path-aware target over a mean-return target:

| evidence | cell(s) | implication for IDEAS §1 |
|---|---|---|
| Same restriction, different label, opposite verdicts | M6.6: `fwd_mdd_21` +0.65pp [+0.44, +0.89] vs `fwd_ret_21` −0.21% [−0.62%, +0.18%] | The ribbon signal lives in the *lower barrier* hit probability, not in the terminal return. A mean-return model would drop the feature; a barrier model keeps it. |
| Magnitude without direction | M7: `abs(fwd_ret_21)` decile spread −0.25% while the signed spread spans zero | Compression changes the *width* of the outcome distribution. Only a target that separates "reaches +U" from "reaches −D" can use it; a signed mean cannot. |
| Mean and hit rate disagree | M2 `stack_fully_bullish`: mean +0.01% (spans zero), hit-rate delta +1.21pp, skew −0.35 | "Wins slightly more often, loses larger" is invisible to a mean. A calibrated P(hit +U before −D) exposes it. |
| Fat left tail under a large mean | M14 VCP: +1.83% mean, hit 68.9%, skew −0.770 vs −0.065 out of context | The best event in the study has a worse tail than its control. The EV-after-cost cell in IDEAS §1 must use the full barrier distribution, not P·U − (1−P)·D with a fixed D. |
| Survival, not return | M6.4: SMA20 slope-run 21d survival exceeds the GBM null by +0.07 to +0.11 | "How long does the state last" is a hazard model. A discretised-hazard head (IDEAS §1 option b) is the natural encoding. |

Horizon evidence:

| horizon | evidence | read |
|---|---|---|
| 5d | M11 `dist_pct_sma_20_h5` is the only SMA-distance cell that clears cost, and only via ×50.4 annualisation | Short horizons are where reversal lives. Include H=5 only with `mom_1_0` in the baseline. |
| 21d | Every Tier-2/3 return cell in the study | The study's evidence base is essentially a 21-day study. |
| 63d | M11 `dist_pct_sma_20_h63` spans zero; M18 `dist_from_52w_low_h63` real; M17 RSI/%K span zero | SMA-distance fades by 63d; 52-week features begin. |
| 126d | M18 `dist_from_52w_low_h126` +2.50%; IC sweep's strongest cells | Slow features need long horizons; the bootstrap block length becomes 252 days and n_dates/block ≈ 10. |

Implications for the H × U × D grid in IDEAS §1: (a) the grid's H axis should span 5–126,
not 5–63, or the 52-week family is wasted; (b) effective N per H cell falls as
n_dates / (2H) — at H=126 the study had about 10 independent blocks, which is a Tier-3
ceiling by DESIGN §6.4's own rule; (c) turnover differs by an order of magnitude across
the features (`above_sma_20` 30.4 flips/ticker-yr; `slope_log_21_sma_200` top-decile
0.90; VCP reclaim 0.185 events/ticker-yr; crossovers 1.4–11.8), so the cost term in the
EV cell must be per-feature-implied-turnover, not one constant.

Barrier units: ATR multiples (IDEAS §1 already chooses this). The study's own
`dist_atr` uses `atr_14` (`features/panel.py`, `indicators.atr`), already lagged. Reuse it
so barrier distances and extension features share units.

---

## 5. Validation-harness lessons → concrete requirements

| lesson from the study | where it bit | harness requirement (IDEAS §8) |
|---|---|---|
| Overlapping labels inflate naive SEs by ≈√H | DESIGN §6.2; every CI is a date-block bootstrap with block = 2H (`stats/inference.py`, default 42) | Purge = H rows and embargo ≥ H rows between train and test folds; CIs on any metric via `block_bootstrap_series` with block 2H, never row-level. |
| Effective N is dates, not rows | 1.2M rows → 2,747 dates; regime restriction (M13) → 786–1,195; VCP reversal check → 112 dates and `InsufficientBlocksError` (`MIN_BLOCKS=3`) | Every metric row reports `n_dates`; any fold or subgroup with fewer than 3 × 2H contributing dates is reported as "not computable", not silently pooled. |
| The p-values are Wald approximations from a 90% CI | `stats/multiple_testing.py::p_value_from_ci`; the 500-draw bootstrap never archived its draws. An empirical bootstrap p from 500 draws bottoms out around 0.002–0.004; the study's p≈0.000000 ranks are normal-tail extrapolations | Archive the bootstrap draws per trial (a few KB each). Rank models by CI width and effect, not by extrapolated p. |
| FDR membership flaps with grid size | `above_sma_20` in/out/in/in at N=50/79/99/107 with p fixed at 0.0090 | Pre-register the trial count per experiment; apply BH once per experiment at its close, and never re-rank a finished experiment when a later one grows the denominator. |
| Plateau rule | M6.2's cell was a lone pixel across deciles (2026-09-18 surface); M9's argmax lookback picked noise; M8's 7 families clustered | For every tuned hyper-parameter or feature threshold, report the ±20% neighbours' metric; a lone best is noise. |
| Seed never varied | `REPORT.md` §9: `seed=0` everywhere | Every trial runs at ≥3 seeds; report the across-seed spread next to the across-fold spread. |
| Universe is survivorship-filtered twice | `data.py::sp500_full_coverage_tickers`: members as of 2021-12-31 (end of window) with full 2010–2021 coverage; zero delisted history before 2024 | The model universe must be point-in-time membership (`db.read_index_membership`) per date, not end-of-window membership; delisted tickers kept with terminal returns (CLAUDE.md invariant #4). Until pre-2024 delisted history exists, tag every bearish/weak-state feature as capped, and report the fraction of a fold's events that fall in those buckets. |
| The window is one macro regime | 2010–2021: near-zero policy rate throughout; the 2022+ holdout starts with a hiking cycle (IDEAS F10) | Report metrics per calendar year and per 2010–2015 / 2016–2021 (the study's own promotion-gate split, `high_low_52w_gate_check.py`); a feature whose sign flips between halves does not ship. Expect the holdout to differ for reasons unrelated to the model. |
| Non-PIT sector in every C2 match | `panel.py` docstring | Either accept and document the leak, or build a PIT sector table before using sector in a baseline. |
| Cost convention | 10 bps round trip, linear ×(252/H) annualisation (`costs.py`), turnover measured off the panel | EV after cost uses per-feature turnover measured on the training folds, at ≥2 cost levels (10 and 25 bps), and reports the near CI edge, not the point. |
| Look-ahead test | `synthetic.py`: planted +3% recovered; null reports nothing; a one-day extra shift degrades recovery to <70% | Port the three-check gate: plant an effect in a synthetic panel, confirm recovery, confirm null silence, confirm degradation under an extra one-bar shift. Run it on the harness before any real fit (IDEAS §8 already lists it). |
| Definitional sensitivity | DESIGN §6.8 checks were rarely run; `touch.py` thresholds (1.0 / 0.25 ATR, 10 / 5 days) are first-pass | Any event-defined training population reports its metric at ±25% of every threshold. |

---

## 6. Confound map

| confound | study cells it killed or attenuated | how the model should handle it |
|---|---|---|
| Market return on the day (C0→C1) | M1: 40–50% of the gross effect; M18 `dist_from_52w_high` C1 −4.03% → C2 −0.67% | B1: per-date demeaning of the target, or per-date rank targets. |
| 12-1 momentum, vol, sector (C1→C2) | M1: a further 10–25% of the gross effect; M18 `dist_from_52w_high` to zero; M6.1: raw slope indistinguishable from `mom_12_1` | `mom_12_1` in every baseline (B2); report incremental gain over it. |
| Short-term reversal (`mom_1_0`) | `touch_x_slope` (−40%, CI spans zero); `dollar_volume`/SMA20 (−47%); `slope_pctile_21_sma_200` (−80%); `stack_fully_bearish` (−32%); M11's 5d cell is the shape it produces; M17 MACD untested | `mom_1_0` in B3. Any H=5 target without it is measuring reversal. |
| Extension (`dist_pct_sma_50`) | M14 pooled cell (−52%, CI spans zero); M6.2 `extension_x_slope` lives inside it | `ext_tercile` in B4; every level/pattern feature is judged against it. |
| Volatility | C2's `vol_tercile`; M7's vol-match changed nothing; M6.4's null is vol-matched | `realized_vol_63` in B2; barrier units in ATR so extreme buckets are not vol buckets (DESIGN §5.5). |
| Sector | C2's `sector` (non-PIT) | sector in B2; document the PIT gap. |
| Size / liquidity | M12 `dollar_volume`/SMA50 capped; C-1 gradient in `dist_z_sma_50` by dollar-volume decile | `dollar_volume` tercile as a control until PIT market cap exists; never as an alpha feature before that. |
| Survivorship | §7.3 caps on `stack_fully_bearish`, `dist_from_52w_low`, falling slope tails (M6.3 resolved its own by the rising-tail decomposition) | Point-in-time universe; keep delisted names; flag weak-state features; report event share in capped buckets. |
| Earnings gaps | M6.3's large-move exclusion changed nothing for SMA50; M13 deferred | Source earnings dates or add a "large move in trailing 5d" flag as the study's proxy (`modules/slope_magnitude.py`, `recent_large_move`). |
| Regime as one observation | M13: 4 buckets around the whole-sample number; M9: ER regime memoryless | Regime gates as interactions only; effective N for any regime claim is the number of regimes, not rows (DESIGN §6.4, §7.7). |
| SMA200 anomaly | M4 `dist_z_sma_200` instability; M1 lb200 row loss 74.9% and non-monotone waterfall; M11 SMA200 spans zero at zero row loss; M6.2 SMA200 top `InsufficientBlocksError` (0.5% falling) | Do not privilege SMA200 features; if included, expect the 252-day normalisation window vs 200-day lookback to interact badly; prefer SMA150 or `dist_z_sma_200` with a longer z window. |

---

## 7. Reusable infrastructure

| component | import as-is | adapt | limitation found |
|---|---|---|---|
| `features/panel.py::apply_lag` | yes — the central one-bar lag, grouped by ticker | — | Row-order based; correct at any timeframe. Everything new must pass through it. |
| `features/panel.py::build_panel` + `write_panel`/`read_panel` | yes for the MA family | extend `_build_ticker_features` rather than adding a second builder; add per-date percentile columns (`cross_sectional_bucket`) after the panel is assembled, since they are cross-sectional | `sector` is not PIT; `end` must be passed explicitly or the holdout is loaded; `Timeframe.WEEKLY` does not recalibrate `mom_12_1`/`realized_vol_63`. |
| `stats/controls.py` (`stratum_deltas`, `c1_delta`, `c2_delta`, `c2_eligible_mask`, `cross_sectional_bucket`) | yes | use `c2_eligible_mask` to build the B2 matched baseline population; use `cross_sectional_bucket` for every per-date rank feature | Stratum matching drops single-sided strata (row loss up to 77% at 4 columns). |
| `stats/inference.py` (`block_bootstrap_delta`, `_spread`, `_group_diff`, `_series`) | yes | add a variant that returns the draws; raise `n_boot` for any p-value use | `MIN_BLOCKS=3` gate; `seed=0` default. |
| `stats/costs.py` (`signals_per_year`, `cost_hurdle`, `annualize`, `ci_clears_cost`) | yes | generalise `signals_per_year` from a boolean state column to a position series (the model's chosen top-k per day) | Linear annualisation; entry+exit convention; per-ticker loop inside `signals_per_year`. |
| `stats/shape.py` (`hit_rate_deltas`, `distribution_shape`) | yes | compute per fold and per barrier cell | Descriptive only by charter (invariant #10). |
| `stats/multiple_testing.py` (`benjamini_hochberg`, `white_reality_check`) | yes | Reality Check is the right tool for "best of K models" claims (M8 used it for 7 kernels); BH for per-experiment trial grids | `p_value_from_ci` is a Wald approximation; do not feed it into BH when draws are available. |
| `stats/survival.py` (`kaplan_meier`, `gbm_null_survival`) | yes | fix the null's σ to an autocorrelation-aware estimator before relying on it (the open M6.4 caveat) | GBM null calibrated from the tested series. |
| `labels/forward_returns.py`, `labels/path_metrics.py` | yes | add MFE, first-touch ordering, hit time, and a triple-barrier label alongside `forward_max_drawdown`, keeping its `skipna=False` convention | Only `forward_return`, `forward_realized_vol`, `forward_max_drawdown` exist. |
| `synthetic.py` (`build_synthetic_panels`, `run_validation`, `gate_verdict`) | port the pattern | plant a barrier-hit effect rather than a +3% mean shift | The gate tests a 5-day SMA state and `c1_delta`; the model harness needs its own planted target. |
| `features/state.py` (`state_run_id`, `days_in_run`) | yes | slope-sign run age (M6.4) | Rejects internal NaN gaps by design. |
| `features/touch.py`, `features/crossover.py`, `features/placebo_ma.py` | available | only if an event-population model is built on touches/crosses (both are study nulls) | Close-only touches; first-pass thresholds. |
| `modules/pattern_context.py` (`load_qualifying_patterns`, `add_pattern_context_flag`) | yes | the VCP event feature; reuse the confidence ≥ 0.7 + 21-day + breakout-confirmed definition | `pattern_matches` is current-state-only (`docs/backlog.md`); the populated table was holdout-bounded once and is not reproducible as of a given date without a re-run. |
| `modules/synthesis.py` | pattern only | overlap/enrichment check between any rare event and any dense rank feature | — |
| `data.py::sp500_full_coverage_tickers` | **do not reuse for the model universe** | replace with `db.read_index_membership` per date plus a liquidity floor | End-of-window membership + full coverage = survivorship on both axes. |

---

## 8. Proposed first three modeling experiments (pre-registration drafts)

Each is written so it can be copied into a modeling pre-registration file with a
date. All three sit inside the 2010–2021 window; the holdout stays locked.

### E1 — Does the MA feature set add anything over the C2/reversal baseline on a 21-day barrier target?

- **Hypothesis.** A gradient-boosted classifier on the §2.2 v1 list (14 columns plus
  controls) improves calibrated `P(+1 ATR before −1 ATR within 21d)` over baseline B3
  (date-demeaned target; `mom_12_1`, `mom_1_0`, `realized_vol_63`, `sector`, `dollar_volume`
  tercile).
- **Motivating evidence.** M6.3 (Tier 2), M6.6/M7 (path labels carry the signal), M2 and
  M14 (shape statistics diverge from the mean), M15 (the two strongest cells are
  anti-correlated so they should be additive).
- **Baseline.** B3, then B5 (B3 + `slope_pctile_21_sma_50` both tails). E1 passes only if
  it beats B5, not just B3.
- **Metric.** Brier score and reliability curve per fold; EV after cost of the top-5%
  scored rows per date at 10 bps and 25 bps; per-date Spearman IC; all with a 42-day
  block bootstrap CI on the difference vs. baseline; `n_dates` per fold.
- **Folds.** Expanding-window walk-forward, yearly test folds 2014–2021, purge 21 rows,
  embargo 21 rows, 3 seeds.
- **Kill criterion.** The 90% CI on (model − B5) Brier improvement includes zero on the
  pooled folds, **or** the improvement is positive in fewer than 5 of 8 yearly folds
  (plateau across time), **or** top-5% EV after cost at 25 bps is negative at the near CI
  edge.
- **Trial budget.** 12 trials (3 feature ablations × 2 tree depths × 2 learning rates),
  declared before the first fit; BH at q=0.10 across the 12 at close.

### E2 — Is the barrier surface's signal in the lower barrier (drawdown) or the upper barrier (return)?

- **Hypothesis.** For the ribbon/compression features (`ribbon_agreement_state`,
  `ribbon_width_pctile`), the model's incremental gain over B3 is larger on
  `P(hit −D within H)` than on `P(hit +U within H)`, at D = U = 1 ATR, H = 21.
- **Motivating evidence.** M6.6: +0.65pp on `fwd_mdd_21`, `fwd_ret_21` spans zero. M7:
  magnitude, not direction. DESIGN §5.3's stated prior that trend rules shape the
  drawdown distribution.
- **Baseline.** B3 fitted separately to each barrier target.
- **Metric.** Brier improvement on each target, with a block-bootstrap CI on the
  difference of improvements (lower minus upper).
- **Kill criterion.** The CI on (lower-barrier gain − upper-barrier gain) includes zero.
  A kill here means the barrier decomposition is not buying anything over a signed
  return target for this family, and IDEAS §1 option (a) is sufficient.
- **Trial budget.** 4 trials (2 features × 2 horizons {21, 63}).

### E3 — Does the VCP-reclaim event survive as an event-population model?

- **Hypothesis.** Training only on `above_sma_50` reclaim events (39,452 in 2010–2021,
  `pattern_context_reclaim_sma50` population), a model with the VCP flag plus the v1 list
  has higher top-decile EV after cost than the same model without the VCP flag, and the
  VCP flag's effect survives `mom_1_0` in the baseline (the check M14 could not run).
- **Motivating evidence.** M14 VCP cell +1.83% [+1.06%, +2.77%], extension-robust, FDR
  q=0.05; the reversal check hit `InsufficientBlocksError` at 112 dates. Pooling the
  event population across all reclaims gives 2,656 dates, so the reversal control becomes
  computable inside a model rather than as a stratum match.
- **Baseline.** B4 (with `ext_tercile`) on the reclaim population, no VCP flag.
- **Metric.** Top-decile EV after cost at 10 and 25 bps; hit rate; skew of the top decile
  (M14's −0.770 in-context skew is the number to beat); `n_dates` of the VCP-positive rows
  per fold (expect about 50 per yearly fold — most folds will be under the 3 × 42 gate, so
  the primary read is pooled across folds).
- **Kill criterion.** The block-bootstrap CI on the VCP flag's SHAP/permutation
  contribution to top-decile EV includes zero, **or** the flag's contribution changes sign
  once `mom_1_0` is added. Either kill closes the VCP line for v1.
- **Trial budget.** 2 trials (with / without the flag), plus the `mom_1_0` ablation.

---

## 9. Corrections and caveats to IDEAS.md

| inbox statement | what the evidence supports | corrected statement |
|---|---|---|
| §2 F2: "SMA20 slope persistence (M6.4)" listed as a feature alongside the Tier-2 cell | M6.4's cells are survival-vs-null departures, not return effects; capped by an unresolved null-calibration caveat | List slope-run *age* as a feature and M6.4 as the reason to try it; do not cite M6.4's p-values (Wald extrapolations, §5) as evidence of return predictability. |
| §2 F3: "`extension_x_slope` (M6.2 Finding 1) is a candidate interaction" | Real at C2 and reversal-robust, but fails FDR (p=0.0254) and the 2026-09-18 Track A surface found no gradient across deciles — a lone pixel | Let a tree find extension × slope; do not hand-build it as a v1 interaction. |
| §2 F4: "MACD adds information beyond the MA set at its control (Tier 3) but fails the whole-grid FDR pass" | Correct as written; add that the incremental IC's lower CI edge is +0.00002 and no reversal control was run | Keep the sentence; add "marginal, untested against `mom_1_0`". |
| §2 F8: "VCP alone is the strongest single event in the MA study … Tier 3 (reversal check underpowered)" | Correct; add the effective-N numbers: 505 events, 409 dates, 131 bootstrap-contributing dates, 0.185 events/ticker-yr | Add the numbers; note that per-fold evaluation will mostly be under the bootstrap gate (§8 E3). |
| §2 closing bullet: "The MA family is close to one signal … give the model a few representatives per lookback cluster" | Correct; the cluster count is 10 at cosine ≥0.95 and the axis is effective lookback, not indicator type; `slope_log_21_sma_200` is an outlier cluster | Add the cluster count and that M16 excluded thresholded rules (`above_*`, crossover events). |
| §2b "Sparse events … golden/death cross … Fired-today flag, days since the event" | M3: crossover events add nothing over state (16 cells span zero) | Encode crossover *state* and its age; drop the event flag as a primary feature. |
| §3 "LRP made quantitative: distance in ATR to the nearest resistance above and support below, pooled across every level source (S/R lines, fib levels, AVWAPs, gap edges, round numbers, prior 52-week high/low)" | M5 and §7.5: an MA is not a level; the 52-week *high* is momentum re-encoded (M18); the 52-week *low* is a real feature but as distance, not as a level | Exclude MAs from the level pool. Keep the 52-week low as its own feature. The remaining level sources (S/R lines, fibs, AVWAP, gaps) are untested by this study and must each beat B4. |
| §3 "Time-since features: days since the 52-week high, since the last gap, since the last MA cross" | Days since MA cross = state age; M1's state-age buckets failed the plateau rule; M6.4's slope-run age did not | Replace "since the last MA cross" with "age of the current slope-sign run". |
| §3 "Per-date cross-sectional ranks of most features … the MA study's only Tier-2 survivor is a percentile feature, which is evidence that ranks travel better" | The evidence is one cell; M4's decile spreads are also per-date ranks and stayed Tier 3 | Weaken to "the Tier-2 cell is a rank feature; rank transforms are cheap and consistent with the study's construction, not proven superior". |
| §3 "Classic factor controls: 1–5-day reversal, 12-1 momentum, size. If the model can't beat them, nothing else matters" | Correct and under-stated: these are exactly C2 + `rev_tercile`, and the study shows they remove 60–100% of gross MA effects | Promote to §4 constraints as B2/B3 (this document §3); add `dist_pct_sma_50` tercile as B4. |
| §3 "Volatility regime … vol-of-vol"; "Compression: ATR percentile, Bollinger-width percentile, NR7" | M7: compression predicts the size of the move, not forward vol; Bollinger width ≈ ribbon width (DESIGN Appendix E) | Keep one compression feature (`ribbon_width_pctile` or Bollinger-width percentile, not both); drop the expectation that it predicts realised vol. |
| §3 "SPX's own trend state (reuse the MA features on the index)" | M13: index-level regime slices of `above_sma_200` show no interaction and cut effective N to 786–1,195 dates | Include as a gate only; expect nothing; report the regime count as effective N (DESIGN §6.4). |
| §4 "The MA study's single Tier-2 effect is about 0.25% over 21 days" | Correct (−0.248%) | No change. Add: the 90% CI is [−0.354%, −0.153%] and the cell's cost hurdle is 0.77%/yr against a ×12-annualised near edge of −1.83%/yr. |
| §5 stage 1 "F2–F5 … cross-sectional ranks" | F5 `rs_rank` is the momentum baseline, not a stage-1 alpha feature (DESIGN §4.3: "this is the momentum control, and it is load-bearing") | Move `rs_rank`/`mom_12_1` into stage 0's baselines explicitly. |
| §7 "SEC XBRL … best candidate" | The SEC EDGAR bulk company-facts ingest has landed on `main` (commits 8915910 and a35b57f, 2026-09-27) | Update the data-gap table once coverage against the PIT S&P 500 universe (delisted included) is measured; until then M12's cell stays a control, not a feature. |
| §8 "Confidence intervals via the MA study's block bootstrap" | Correct; add the gate: `MIN_BLOCKS × block_length` dates, and that the study's p-values were Wald approximations because draws were discarded | Archive draws; report `n_dates` per fold; state the block length per horizon. |
| §11 "Event alert: a known strong event fires (VCP reclaim, extreme-slope entry)" | Extreme-slope tail is 40% of the panel on any date (M15: 40.03% unconditional tail rate) — it is not a rare event | Only the VCP reclaim is alert-shaped (0.185/ticker-yr). Extreme slope is a ranking feature, not an alert. |
| §12 "Half the families aren't sequences … trailing summaries … exactly what the MA study validated" | The study validated that trailing summaries carry *weak* signal after controls; it did not compare them against a sequence model | Keep trees-first on effective-N and diagnosability grounds; drop "validated" in favour of "the study's effect sizes are what a sequence model has to beat". |

**Not in the inbox, worth adding:** (1) the universe must be point-in-time membership,
not `sp500_full_coverage_tickers` (§5, §7); (2) `sector` is not PIT (§2.4); (3) the
2022+ holdout is the first rate-hiking regime in the data (IDEAS F10 notes the fed funds
rate, not the consequence for the holdout read); (4) the SMA200 anomaly (§6) argues
against giving SMA200 any privileged role; (5) `pattern_matches` is current-state-only,
so a VCP feature history must be regenerated as-of each date for the model, not read from
the table (`docs/backlog.md`, chart-pattern entry).
