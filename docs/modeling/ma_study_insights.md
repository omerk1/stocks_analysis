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
−0.248% per 21 trading days (`slope_magnitude_humped_test_sma50`), and only 2 of 107
tests survive whole-grid FDR. The largest |rank-IC| in a 348-cell Track A
sweep is 0.038. Every "clears cost" verdict rests on a 10 bps round-trip convention and
a linear ×12 annualisation (`stats/costs.py::annualize`). The other FDR survivor is a
drawdown read, not a return claim. A model built on
this feature family is working in a weak-signal regime and should be evaluated as such.

---

## 1. What the study established, at the confidence the evidence supports

### 1.1 Track B — Tier 2 and the strongest Tier-3 cells (FDR survivors at N=107: M6.3 and M6.6 only)

Units: return cells are per-21-trading-day C2 deltas unless the row says otherwise.
"n_dates" is the effective N the study reports (distinct contributing dates). "Capped
by" is the specific reason the cell is not Tier 1/2. "Usable as" is this document's
own call for the modeling phase.

| cell_id (module) | Tier | statistic | point | 90% CI | n_events / n_dates | shape (if logged) | capped by | usable as |
|---|---|---|---|---|---|---|---|---|
| `slope_magnitude_humped_test_sma50` (M6.3) | **2** | C2 delta, middle deciles {4,5} minus tails {0,1,8,9} of per-date pctile of `slope_log_21_sma_50`, `fwd_ret_21` | −0.248% | [−0.354%, −0.153%] | 219,700 / 2,747 | — | holdout + universe tier only (infrastructure) | **feature** (per-date slope percentile, both tails) and **baseline** the model must beat |
| `ribbon_agreement_extreme_drawdown` (M6.6) | 3 | C2 delta on `fwd_mdd_21`, state 5 vs 0 of {10,20,50,100,200} slope signs | +0.654pp shallower | [+0.438pp, +0.887pp] | 406,663 / 2,747 | — | drawdown read, companion `fwd_ret_21` cell spans zero | **target-design evidence** (path/drawdown labels carry signal the mean does not) + feature (ordinal 0–5 state) |
| `reclaim_durability_dollar_volume_sma50` (M12) | 3 | C2 delta, top vs bottom dollar-volume tercile among SMA50 reclaims | −0.870% | [−1.381%, −0.402%] | 13,880 / 2,468 | — | no PIT market-cap control; size/illiquidity premium equally plausible | **feature** only if a PIT size control exists; otherwise a **confound proxy** |
| `dist_from_52w_low_h126` (M18) | 3 | C2 decile spread, `fwd_ret_126` | +2.50% per 126d | [+1.10%, +4.02%] | 1,069,515 / 2,643 | — | survivorship-adjacent (beaten-down bucket), argued by analogy, never tested | **feature** at long horizons; carries §7.3 exposure |
| `ribbon_direction_magnitude` (M7) | 3 | C2 decile spread on `abs(fwd_ret_21)`, ribbon-width decile 9 vs 0 | −0.247% | [−0.398%, −0.093%] | 175,152 / 2,549 | — | magnitude, not signed return | **target-design evidence** (compression predicts the size of the move, not its direction) + feature for a vol/barrier model |
| `stack_fully_bearish_h21` (M2) | 3 | incremental C2 diff vs `above_sma_50`; standalone C2 +0.444% [+0.142%, +0.748%] | +1.011% incremental | [+0.359%, +1.682%] | 40,644 / 2,698 | hit 63.9%; skew +1.01 | DESIGN §7.3 survivorship cap (bearish bucket, zero delisted history pre-2024) | **feature** (full-stack state) with the survivorship caveat stamped on it |
| `above_sma_20` (M1) | 3 | C2 delta | −0.215% | [−0.350%, −0.079%] | 751,406 / 2,744 | — | fails cost (30.4 flips/ticker-yr → 3.04%/yr hurdle) | **baseline** (cheap state feature); not a standalone signal |

M12, M18, M7, M2 and M1 miss FDR by a factor of 1.2–1.6; their FDR status depends on
grid size, not on new evidence.

### 1.2 Track B — real at C2 but not an FDR survivor (Tier 3)

| cell_id (module) | point / CI | n_dates | why it matters for the model |
|---|---|---|---|
| `dist_pct_sma_20_h21`, `dist_atr_sma_20_h21`, `dist_z_sma_20_h21` (M4) | −0.464% / −0.372% / −0.374% per 21d decile spread; all CIs exclude zero | 2,747 / 2,747 / 2,729 | SMA20 extension is a real, weak, cost-failing effect (hurdle ≈2.5%/yr vs. near-edge ≈1.1–1.6%/yr). The three normalisations are 0.94–0.98 correlated; one feature, not three. |
| `above_sma_50` (M1) | −0.183% [−0.341%, −0.031%] | 2,746 | Same shape as SMA20, lower turnover (18.0 flips/ticker-yr). |
| `dist_pct_sma_20_h5` (M11) | rank-IC −0.0138 [−0.0225, −0.0041]; the one M11 cell that clears cost after the ×50.4 annualisation | 2,996 | The shortest horizon clears cost — the shape a short-term-reversal generator would produce (`PREREGISTRATION.md` M11 2026-09-10 correction). A model with `mom_1_0` in the baseline should expect this to shrink. |
| `slope_cond_extension_x_slope_sma50_top` (M6.2) | −0.592% [−1.047%, −0.175%]; reversal-robust −0.550% | 2,747 | Interaction: within the top `dist_atr_sma_50` decile, a rising 50-day is *worse* than a falling one. Rare falling subgroup (7.1%). Track A follow-up (2026-09-18 surface) found it is a lone bright pixel across deciles, not a gradient. |
| `slope_cond_touch_x_slope_sma50_from_above` (M6.2) | −5.75pp hold-rate; reversal-controlled −3.33pp [−8.18pp, +1.25pp] | 2,410 | Does not survive reversal control. Null prior only (§2.3); don't hand-build it. |
| `dist_from_52w_low_h63` (M18) | +0.956% [+0.128%, +1.843%] per 63d | 2,706 | Effect grows with horizon (63d → 126d); fails cost at 63d. |
| `slope_magnitude_humped_test_sma20` / `_sma200` (M6.3) | −0.117% / −0.193%; SMA200 attenuates 80.5% under reversal control, CI spans zero | 2,747 | The Tier-2 SMA50 cell's neighbours agree in sign (plateau holds on sign) but SMA200 is a reversal artefact. Use the SMA50 percentile; treat SMA20/SMA200 as weaker copies. |
| `context_vix_bottom`, `context_breadth_top` (M13) | −0.318% / −0.388%; other two regime buckets span zero | 1,195 / 882 | All four buckets sit within a narrow band around M1's own `above_sma_200` (−0.215%). The module's own read: no real regime interaction. Regime restriction also halves effective N. |
| `reclaim_hold_rate_relative_volume_sma200` (M12) | +3.35pp [+0.44pp, +6.37pp] | 2,177 | The one cell supporting "reclaim on high volume holds better", at SMA200 only. Mechanism read, single lookback. |
| `nonlinearity_macd_histogram_incremental_ic_h21` (M17) | +0.0089 [+0.00002, +0.0187]; FDR rank 34/107, p=0.115 | 2,747 | MACD histogram is not redundant with `dist_pct_sma_50`/`slope_log_21_sma_50`/`mom_12_1` (corr +0.30 / −0.25), but the incremental IC barely excludes zero and no reversal control was run. |
| `sma_dropoff_decisive_sma200_down` (M6.5 companion, not counted) | +1.03% [+0.23%, +1.72%] | 2,440 | Flagged, not promoted; reversal untested. Null prior for v1 (§2.3). |

### 1.3 Track B — strong nulls: null prior only, never a hand-picked feature

| module | what was killed | the number that kills it | model implication |
|---|---|---|---|
| **M5** touch/test/bounce | MAs as support/resistance, real MA vs. unwatched synthetic neighbour, 6 cells | largest CI edge 0.61pp vs a 2pp floor; every CI spans zero; smallest cell 7,257 events / 2,102 dates | No "distance to MA as a level" feature in the LRP sense (IDEAS §3). MA proximity is an extension feature, not a support level. Caveat: close-only touches, no intraday wick. |
| **M19** MA respect history (2026-09-30) | Does an MA that held ≥2 times in the last 126d (touch → confirmed 1-ATR reversal within 5d) hold better on the next touch than one with none, more than its unwatched neighbour does; 4 MAs × 2 directions | Killed, 0 of 8. Raw hold rates by 0/1/≥2 prior bounces are flat in both arms (e.g. SMA20↑ 35.2/35.7/36.3% real, 35.4/35.2/36.1% synthetic). Two C2+rev-only CIs off zero rest on 2–8% of events and vanish at C1. | No "respect count" / "times this level held" strength input for MA levels. Confirmed-bounce history is not a feature; it is also not a generic mean-reversion proxy (the synthetic arm is flat too). |
| **M20** confirmed bounce as an entry (2026-09-30) | Touch, then ≥1 ATR back within 5d without a close through: is the confirmation day an entry? Forward return at 5/10/21/63d vs a same-size move with no MA touched; 4 MAs × 2 directions | Killed, 0 of 32. Bounce arm never clears zero in the hypothesised direction; from-above bounces run −0.3 to −0.5% at 63d, from-below rejections +0.3% at 21d (reversal). Generic ≥1-ATR moves sit on top of the bounce arm; `rev_tercile` absorbs most of the C1 delta. | No "bounced off the MA" entry flag. If a bounce feature is built at all it belongs in the short-term-reversal block, sign-flipped from the folklore. |
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
| **M14** pattern context | reclaim inside a detected pattern, as-of-safe flag | pooled +0.07% [−0.31%, +0.42%]; VCP-only +0.85% [−0.10%, +1.88%], 402 events | Null. Per-pattern flags stay only as null-prior candidates (§2.3). The earlier +1.83% VCP reading came from a flag that used the future breakout. |
| **M6.4** slope persistence | slope-sign run survival vs a direction-matched GBM null | 0 of 12 strata depart | Slope runs last as long as a drifting random walk's. No hazard-model evidence. |

### 1.4 Track A — screens that inform feature selection (never effect sizes)

| look (date, `EXPLORATION_LOG.md`) | what it says |
|---|---|
| 348-cell IC sweep (2026-09-16) | max mean rank-IC magnitude 0.038 (`dist_from_52w_low`@126d); top-25 mostly 0.018–0.022. SMA-distance IC peaks at 21–42d and is absent from the top 25 past 42d; 52-week features strengthen out to 126d. |
| Same sweep, redundancy | `dist_pct` vs `dist_atr` 0.96–0.98 at every lookback and family; `dist_z` vs `dist_pct` 0.94 (SMA20) → 0.89 (50) → 0.74 (150) → 0.69 (200); `slope_log_5_ema_200` vs `dist_pct_ema_200` 0.986; `slope_log_63` decorrelates from distance (0.18 at SMA20, 0.32 at EMA20). |
| Distance × slope surface (2026-09-18) | `slope_log_21` vs `dist_atr` correlation 0.34→0.80 (SMA 20→200), 0.59→0.93 (EMA). No smooth 2D interaction anywhere; M6.2's SMA50 top-decile cell is a lone pixel. |
| Kernel-space scan, M16 (2026-09-24) | 23 MA rules form one cluster at cosine ≥0.80; 10 clusters at ≥0.95, ordered by effective lookback (centroid), not by indicator type. `slope_log_21_sma_200` sits at centroid 109.5 vs 66–82 for `dist_pct_sma_200`/`crossover_sma_50_sma_200`. |
| M15 overlap check (re-run 2026-09-29) | VCP reclaims fall in M6.3's extreme-slope tail 25.4% of the time vs 40.0% unconditionally. With the VCP cell now a null, this says nothing about a second signal. |
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
cluster per operation (distance, slope, spread), transformed to per-date ranks.** Twelve
columns replace the 68 numeric MA columns in the panel.

| # | feature | construction | one-line justification |
|---|---|---|---|
| 1 | `slope_pctile_21_sma_50` | per-date `cross_sectional_bucket`/rank of `slope_log_21_sma_50` (as `modules/slope_magnitude.py::prepare`) | The Tier-2 cell. Keep the *rank*, and let the model see both tails (the effect is U-shaped, M6.3). |
| 2 | `abs_slope_pctile_21_sma_50` | rank − 0.5, absolute value | Encodes the U directly so a linear baseline can use it; a tree does not need it. |
| 3 | `dist_z_sma_20` (or `dist_pct_sma_20`, one only) | panel | M4/M11: the only extension lookback with a real effect; `dist_z` is 0.94-correlated with `dist_pct` here so either works. Also the extension confound control for every pattern feature (M14). |
| 4 | `dist_z_sma_200` | panel | Keeps a slow-lookback extension that is only 0.69-correlated with `dist_pct_sma_200` (sweep). Carries the SMA200 anomaly; expect little. |
| 5 | `slope_log_63_sma_50` | panel | The one slope window that decorrelates from distance at every lookback (0.18–0.32, sweep). Cheap diversification of the slope cluster. |
| 6 | `ribbon_agreement_state` (0–5 over {10,20,50,100,200} slope signs) | rebuild as in `modules/ribbon_slope_agreement.py` | M6.6: predicts `fwd_mdd_21` (+0.65pp), pairwise slope correlations 0.28–0.89 so it is not one MA in disguise. A drawdown-side feature. |
| 7 | `ribbon_width_pctile` | `features/ribbon.py::ribbon_width_pctile` | M7: compression predicts the size of the forward return (−0.25% decile spread on `abs(fwd_ret_21)`). Directly relevant to a barrier target's reach probability. |
| 8 | `stack_fully_bearish` (price < SMA20 < SMA50 < SMA150 < SMA200) | `modules/stack_minervini.py` construction | M2: +1.01% incremental over `above_sma_50`, hit 63.9%, skew +1.01. Survivorship-capped (§7.3); flag it as such in the feature registry. |
| 9 | `dist_from_52w_low` | panel | M18: +0.96% (63d), +2.50% (126d) C2 decile spread, reversal-robust. Matters only at H ≥ 63. |
| 10 | `macd_histogram` (12,26,9) | `features/oscillators.py::macd_components` | M17: incremental IC +0.0089 over the MA block, correlation −0.25 with `slope_log_21_sma_50`. Marginal; include and let importance decide, as IDEAS F4 already says. |
| 11 | `dollar_volume` per-date tercile | `features/liquidity.py::dollar_volume` | M12's strongest cell, but only as a **size/liquidity control** until PIT market cap exists (§2.4). |
| 12 | `adx_14` regime (`features/regime.py::adx_regime`) | M9 | The regime construction that actually persists (+10.4pp). Use as an interaction gate, not as a lookback selector (M9 killed that). |

Controls that belong in every feature set and every baseline (§3): `mom_12_1`, `mom_1_0`
(reversal), `realized_vol_63`, `sector`, and `ext_tercile` (= `dist_pct_sma_50` tercile).

### 2.3 Near-copies (drop) and nulls (null prior, test as a group)

Two different reasons a feature is off the v1 list above, handled differently
(decided 2026-09-29, matching IDEAS §2's feature priors).

**Near-copies: drop.** The same signal a v1 feature already carries. Adding them gives
the model nothing new and splits feature-importance credit across copies.

| dropped | evidence |
|---|---|
| Any second distance normalisation at the same lookback (`dist_pct` + `dist_atr` + `dist_z` together) | 0.94–0.98 pairwise correlation at SMA20 (M4 2026-09-09; sweep 2026-09-16). |
| `slope_log_5_*` on EMAs | 0.986 correlation with `dist_pct` at EMA200 (sweep); it *is* distance. |
| WMA/HMA/DEMA/KAMA/VWMA columns | M8: Reality Check p=0.193; 2× turnover for HMA/KAMA. |
| Weekly-timeframe MAs | M10: sampling frequency effect < 0.03pp; they are the daily MAs at a longer lookback. |
| RSI and stochastic %K as separate columns when `dist_z_sma_20` is present | M17: RSI vs `dist_z_sma_20` corr 0.86; incremental IC spans zero at 21d and 63d. |
| ER-regime lookback switching | M9 killed; ER regime memoryless at 21d. A method, not a feature. |

**Nulls: null prior, test as a group.** Separate measurements that came out
indistinguishable from zero. Individually dead, but weak signals may still combine, so
they enter the model as one group and stay only if the group ablation shows an
out-of-sample gain. Being in the model never turns one into evidence.

| null-prior candidate | evidence |
|---|---|
| `above_sma_k` flags beyond one lookback | M1: mirror cells, three independent numbers; SMA200 anomalous; §7.5 shows no lookback is special. |
| Crossover state age (covers golden/death cross flags and days-since-cross) | M3: 16 cells, all span zero. Encode as state + age, not as event flags. |
| Run-length bucket of `above_sma_k` (state age), or slope-sign run age | M1: plateau failure across 24 cells. M6.4: slope runs match a direction-matched random walk. |
| VCP-reclaim and other per-pattern flags (as-of-safe only) | M14: as-of-safe VCP cell +0.85% [−0.10%, +1.88%], spans zero on 402 events. |
| `dist_from_52w_high` | M18: C2 CI spans zero at both horizons; the C1 effect was momentum. |
| Distance to an MA as a *level* in the LRP pool (IDEAS §3) | M5: 6/6 cells killed against synthetic neighbours; §7.5 placebo. |
| VIX/breadth regime × MA-state interactions | M13: all four buckets sit around the whole-sample number; effective N falls to 786–1,195 dates. |
| `touch_x_slope` (M6.2), `sma_dropoff_decisive_sma200_down` (M6.5 companion) | §1.2: fails reversal control / reversal untested. |

### 2.4 Needs new infrastructure before it can be a feature

| feature | blocker | where the study hit it |
|---|---|---|
| Point-in-time market cap / size decile | `shares_outstanding` history: yfinance 2016+, survivors only (IDEAS §7). SEC EDGAR bulk company-facts ingest has since landed on `main` (commits 8915910, a35b57f) — coverage against the 2010–2021 PIT universe is not verified in this document. | M12's `dollar_volume` cell capped for exactly this; C-1 candidate in `EXPLORATION_LOG.md` never disentangled. |
| Earnings dates | no table anywhere in the DB | M6.3 substituted a large-move proxy; M13 deferred; DESIGN §7.4 unaddressable. For a barrier target this is the largest single gap (IDEAS §3 already says so). |
| Intraday (wick) touches | close-only bars in the touch detector (`features/touch.py`) | M5's named caveat. Only matters if an LRP feature is rebuilt on intraday data. |
| Point-in-time sector | `ticker_sector` is a current snapshot | Every C2 match in the study used a non-PIT sector column (`panel.py` docstring). Same leak in a model's sector feature. |
| MFE / MAE / barrier hit times | `labels/path_metrics.py` has only `forward_max_drawdown` | Needed for the barrier surface (IDEAS §1). |
| Delisted-ticker history before 2024 | zero rows (DESIGN §7.3, §12) | Every bearish/weak-state feature (rows 8, 9 in §2.2) is survivorship-exposed. |

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
| Fat left tail | M2 `stack_fully_bearish`: hit rate 63.9%, skew +1.01; M2 `stack_fully_bullish`: skew −0.35 on a flat mean | Tails differ between states with similar means. The EV cell in IDEAS §1 must use the full barrier distribution, not P·U − (1−P)·D with a fixed D. |

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
0.90; crossovers 1.4–11.8), so the cost term in the
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
| Volatility | C2's `vol_tercile`; M7's vol-match changed nothing | `realized_vol_63` in B2; barrier units in ATR so extreme buckets are not vol buckets (DESIGN §5.5). |
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
| `stats/survival.py` (`kaplan_meier`, `gbm_null_survival`) | yes | always pass `direction=` to match the empirical side | A pooled-direction null reads positive drift as persistence (the M6.4 error). |
| `labels/forward_returns.py`, `labels/path_metrics.py` | yes | add MFE, first-touch ordering, hit time, and a triple-barrier label alongside `forward_max_drawdown`, keeping its `skipna=False` convention | Only `forward_return`, `forward_realized_vol`, `forward_max_drawdown` exist. |
| `synthetic.py` (`build_synthetic_panels`, `run_validation`, `gate_verdict`) | port the pattern | plant a barrier-hit effect rather than a +3% mean shift | The gate tests a 5-day SMA state and `c1_delta`; the model harness needs its own planted target. |
| `features/state.py` (`state_run_id`, `days_in_run`) | yes | age of any state | Rejects internal NaN gaps by design. |
| `features/touch.py`, `features/crossover.py`, `features/placebo_ma.py` | available | only if an event-population model is built on touches/crosses (both are study nulls) | Close-only touches; first-pass thresholds. |
| `modules/pattern_context.py` (`load_qualifying_patterns`, `attach_breakout_dates`, `add_pattern_context_flag`) | only if pattern features are tried | use the as-of-safe flag (window after the verified breakout date, no status filter) | `pattern_matches` is current-state-only; a strict point-in-time history needs the scanner re-run as of each date. |
| `modules/synthesis.py` | pattern only | overlap/enrichment check between any rare event and any dense rank feature | — |
| `data.py::sp500_full_coverage_tickers` | **do not reuse for the model universe** | replace with `db.read_index_membership` per date plus a liquidity floor | End-of-window membership + full coverage = survivorship on both axes. |

---

## 8. Proposed first modeling experiments (pre-registration drafts)

Each is written so it can be copied into a modeling pre-registration file with a
date. Both sit inside the 2010–2021 window; the holdout stays locked.

### E1 — Does the MA feature set add anything over the C2/reversal baseline on a 21-day barrier target?

- **Hypothesis.** A gradient-boosted classifier on the §2.2 v1 list (12 columns plus
  controls) improves calibrated `P(+1 ATR before −1 ATR within 21d)` over baseline B3
  (date-demeaned target; `mom_12_1`, `mom_1_0`, `realized_vol_63`, `sector`, `dollar_volume`
  tercile).
- **Motivating evidence.** M6.3 (Tier 2), M6.6/M7 (path labels carry the signal), M2
  (shape statistics diverge from the mean).
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

---

## 9. Corrections and caveats to IDEAS.md

| inbox statement | what the evidence supports | corrected statement |
|---|---|---|
| §2 F2: "SMA20 slope persistence (M6.4)" listed as a feature alongside the Tier-2 cell | M6.4 is killed: 0 of 12 strata depart from a direction-matched null | Drop it as evidence; slope-run length stays only as a null-prior candidate (§2.3). |
| §2 F3: "`extension_x_slope` (M6.2 Finding 1) is a candidate interaction" | Real at C2 and reversal-robust, but fails FDR (p=0.0254) and the 2026-09-18 Track A surface found no gradient across deciles — a lone pixel | Let a tree find extension × slope; do not hand-build it as a v1 interaction. |
| §2 F4: "MACD adds information beyond the MA set at its control (Tier 3) but fails the whole-grid FDR pass" | Correct as written; add that the incremental IC's lower CI edge is +0.00002 and no reversal control was run | Keep the sentence; add "marginal, untested against `mom_1_0`". |
| §2 F8: "VCP alone is the strongest single event in the MA study" | Wrong: the flag used the future breakout. As-of-safe, +0.85% [−0.10%, +1.88%] on 402 events | Drop VCP as evidence; per-pattern features must each beat B4 on an as-of-safe flag. |
| §2 closing bullet: "The MA family is close to one signal … give the model a few representatives per lookback cluster" | Correct; the cluster count is 10 at cosine ≥0.95 and the axis is effective lookback, not indicator type; `slope_log_21_sma_200` is an outlier cluster | Add the cluster count and that M16 excluded thresholded rules (`above_*`, crossover events). |
| §2b "Sparse events … golden/death cross … Fired-today flag, days since the event" | M3: crossover events add nothing over state (16 cells span zero) | Encode crossover *state* and its age; drop the event flag as a primary feature. |
| §3 "LRP made quantitative: distance in ATR to the nearest resistance above and support below, pooled across every level source (S/R lines, fib levels, AVWAPs, gap edges, round numbers, prior 52-week high/low)" | M5 and §7.5: an MA is not a level; the 52-week *high* is momentum re-encoded (M18); the 52-week *low* is a real feature but as distance, not as a level | Exclude MAs from the level pool. Keep the 52-week low as its own feature. The remaining level sources (S/R lines, fibs, AVWAP, gaps) are untested by this study and must each beat B4. |
| §3 "Time-since features: days since the 52-week high, since the last gap, since the last MA cross" | Days since MA cross = state age; M1's state-age buckets failed the plateau rule, and M6.4's slope runs match a random walk | Drop "since the last MA cross". |
| §3 "Per-date cross-sectional ranks of most features … the MA study's only Tier-2 survivor is a percentile feature, which is evidence that ranks travel better" | The evidence is one cell; M4's decile spreads are also per-date ranks and stayed Tier 3 | Weaken to "the Tier-2 cell is a rank feature; rank transforms are cheap and consistent with the study's construction, not proven superior". |
| §3 "Classic factor controls: 1–5-day reversal, 12-1 momentum, size. If the model can't beat them, nothing else matters" | Correct and under-stated: these are exactly C2 + `rev_tercile`, and the study shows they remove 60–100% of gross MA effects | Promote to §4 constraints as B2/B3 (this document §3); add `dist_pct_sma_50` tercile as B4. |
| §3 "Volatility regime … vol-of-vol"; "Compression: ATR percentile, Bollinger-width percentile, NR7" | M7: compression predicts the size of the move, not forward vol; Bollinger width ≈ ribbon width (DESIGN Appendix E) | Keep one compression feature (`ribbon_width_pctile` or Bollinger-width percentile, not both); drop the expectation that it predicts realised vol. |
| §3 "SPX's own trend state (reuse the MA features on the index)" | M13: index-level regime slices of `above_sma_200` show no interaction and cut effective N to 786–1,195 dates | Include as a gate only; expect nothing; report the regime count as effective N (DESIGN §6.4). |
| §4 "The MA study's single Tier-2 effect is about 0.25% over 21 days" | Correct (−0.248%) | No change. Add: the 90% CI is [−0.354%, −0.153%] and the cell's cost hurdle is 0.77%/yr against a ×12-annualised near edge of −1.83%/yr. |
| §5 stage 1 "F2–F5 … cross-sectional ranks" | F5 `rs_rank` is the momentum baseline, not a stage-1 alpha feature (DESIGN §4.3: "this is the momentum control, and it is load-bearing") | Move `rs_rank`/`mom_12_1` into stage 0's baselines explicitly. |
| §7 "SEC XBRL … best candidate" | The SEC EDGAR bulk company-facts ingest has landed on `main` (commits 8915910 and a35b57f, 2026-09-27) | Update the data-gap table once coverage against the PIT S&P 500 universe (delisted included) is measured; until then M12's cell stays a control, not a feature. |
| §8 "Confidence intervals via the MA study's block bootstrap" | Correct; add the gate: `MIN_BLOCKS × block_length` dates, and that the study's p-values were Wald approximations because draws were discarded | Archive draws; report `n_dates` per fold; state the block length per horizon. |
| §11 "Event alert: a known strong event fires (VCP reclaim, extreme-slope entry)" | The VCP reclaim is a null; the extreme-slope tail is 40% of the panel | No event in the study is alert-grade. Extreme slope is a ranking feature. |
| §12 "Half the families aren't sequences … trailing summaries … exactly what the MA study validated" | The study validated that trailing summaries carry *weak* signal after controls; it did not compare them against a sequence model | Keep trees-first on effective-N and diagnosability grounds; drop "validated" in favour of "the study's effect sizes are what a sequence model has to beat". |

**Not in the inbox, worth adding:** (1) the universe must be point-in-time membership,
not `sp500_full_coverage_tickers` (§5, §7); (2) `sector` is not PIT (§2.4); (3) the
2022+ holdout is the first rate-hiking regime in the data (IDEAS F10 notes the fed funds
rate, not the consequence for the holdout read); (4) the SMA200 anomaly (§6) argues
against giving SMA200 any privileged role; (5) `pattern_matches` is current-state-only,
so any pattern feature history must be regenerated as-of each date for the model, not read from
the table (`docs/backlog.md`, chart-pattern entry).
