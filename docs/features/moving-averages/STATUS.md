# Moving-averages study — status

Kept-current scoreboard. Per-cell numbers live in `EXPERIMENTS.csv`, frozen hypothesis
text in `PREREGISTRATION.md`, Tier 1–3 write-ups in `FINDINGS.md`, narrative in
`REPORT.md`.

**State (2026-09-29):** complete. All of DESIGN's modules (M1–M18, §7.5) ran and were
tiered. **One Tier-2 result** (`slope_pctile_21_sma_50`), zero Tier 1. The whole-grid FDR
pass keeps **2 of 107** tests at q=0.10 and q=0.05.

## Modules run

| module | question | result | tier |
|---|---|---|---|
| M1 | above/below SMA20/50/200 | SMA20 −0.215% [−0.350, −0.079], SMA50 −0.183% [−0.341, −0.031]; both fail cost. SMA200 spans zero. State age: plateau failure. | 3 / 3 / 4 |
| M2 | stack states; Minervini ablation | Fully bearish stack adds +1.01% [+0.36, +1.68] over `above_sma_50`, clears cost, survivorship-capped. Bullish stack adds nothing. Ablation: near-52w-high is the largest (negative) coefficient, uncontrolled. | 3 / 4 |
| M3 | crossover events vs state | 16 cells, all span zero. | 4 |
| M4 | distance from MA | SMA20 −0.46% [−0.78, −0.14] (all 3 normalisations, 0.94–0.98 correlated), fails cost. SMA50/200 span zero. | 3 / 4 |
| M5 | touch / bounce at MA vs synthetic neighbour | 6 cells killed; largest CI edge 0.61pp vs a 2pp floor. | 4 |
| M6.1 | slope beyond momentum | 4 lookbacks, all span zero. | 4 |
| M6.2 | slope as conditioner | Rising 50-day inside the top extension decile: −0.59% [−1.05, −0.18], reversal-robust, fails FDR. Touch×slope dies to the reversal control. 9 inconclusive. | 3 |
| M6.3 | slope magnitude: humped? | **U-shaped. SMA50 −0.248% [−0.354, −0.153], both tails alone, reversal-robust, clears cost at 20 bps, survives FDR.** SMA200 a reversal artifact; SMA20 fails cost. | **2** / 3 |
| M6.4 | slope-run persistence vs GBM null | Killed: 0 of 12 strata depart from a direction-matched null. | 4 |
| M6.5 | SMA drop-off artefact | Both cells span zero, opposite signs. | 4 |
| M6.6 | slope agreement across the ribbon | All-agree states have +0.65pp [+0.44, +0.89] shallower 21d drawdown; return spans zero. Survives FDR. | 3 |
| M7 | ribbon compression | Predicts forward \|return\| (−0.25% [−0.40, −0.09]), not realised vol, not direction. | 3 |
| M8 | MA family at matched lag | 7 kernels within −0.13% to −0.21%; Reality Check p=0.19. | 4 |
| M9 | regime-conditional lookback | Out-of-sample switching rule spans zero. ADX regime persists, ER regime doesn't. | 4 |
| M10 | weekly vs daily sampling | Null; sampling gaps <0.03pp. | 4 |
| M11 | cross-sectional rank-IC | Same SMA20 signal as M4. 5-day cell clears cost but is reversal-shaped. | 3 |
| M12 | volume / liquidity | Low-dollar-volume SMA50 reclaims beat high by 0.87% [0.40, 1.38]; size confound unresolved. High-relative-volume SMA200 reclaims hold +3.4pp more often. | 3 |
| M13 | VIX / breadth regime slices | Two of four slices exclude zero, all near M1's baseline; no real interaction. | 3 / 4 |
| M14 | MA event inside a chart pattern | Pooled +0.07% [−0.31, +0.42]; VCP-only +0.85% [−0.10, +1.88] on 402 events. | 4 |
| M15 | synthesis | VCP reclaims sit in the extreme-slope tail less than baseline (enrichment 0.63–0.69). Track A. | — |
| M16 | rules as linear filters | 23 MA rules form 1 cluster at cosine ≥0.80, 10 at ≥0.95, ordered by effective lookback. Track A. | — |
| M17 | MACD / RSI / stochastics | MACD histogram incremental IC +0.0089 [+0.00002, +0.0187], fails FDR. RSI and %K span zero. | 3 / 4 |
| M18 | 52-week range | Near-52w-low: +0.96% at 63d (fails cost), +2.50% [+1.10, +4.02] at 126d (clears). Near-52w-high: spans zero. | 3 / 4 |
| §7.5 | watched level vs placebo lookback | SMA200/SMA50 show no effect; EMA21 matches its unwatched neighbours. | 4 |

## Whole-grid FDR pass

Benjamini–Hochberg over every counted cell (`counted_in_n_tests`), deduplicated to
N=107. p-values are Wald back-outs of each cell's 90% block-bootstrap CI
(`p_value_from_ci`). M6.4's rows are held at p=1, because their logged interval is a null
envelope, not a CI. Reproduce with `python -m src.signals.moving_averages.whole_grid_fdr_run`.

| rank | cell | p | threshold (q=0.10) | survives |
|---|---|---|---|---|
| 1 | M6.6 `ribbon_agreement_extreme_drawdown` | 0.0000017 | 0.00093 | yes (also q=0.05) |
| 2 | M6.3 `slope_magnitude_humped_test_sma50` | 0.000050 | 0.00187 | yes (also q=0.05) |
| 3 | M12 `reclaim_durability_dollar_volume_sma50` | 0.0035 | 0.0028 | no |
| 4 | M18 `dist_from_52w_low_h126` | 0.0047 | 0.0037 | no |
| 5 | M7 `ribbon_direction_magnitude` | 0.0077 | 0.0047 | no |
| 6 | M1 `above_sma_20` | 0.0090 | 0.0056 | no |
| 7 | M2 `stack_fully_bearish_h21` | 0.0119 | 0.0065 | no |

Ranks 3–7 miss by a factor of 1.2–1.8, so their FDR status depends on how many tests
the grid holds. The two survivors clear by 37× or more.
p-values below about 0.004 are extrapolations of a 500-draw bootstrap.

## Cross-module SMA200 watch

SMA200 misbehaves in four independent places:
- **M4**: `dist_z` window instability.
- **M1**: 75% C2 row loss and a non-monotone waterfall.
- **M11**: spans zero with no row loss.
- **M6.2**: only 0.5% of the top decile is falling.

§7.5 finds nothing distinctive in SMA200's neighbourhood, which favours a low-power
explanation over a level-specific one. Never audited. Don't privilege SMA200 features.

## Open items

- **Universe is survivorship-selected.** U1 is S&P 500 members as of 2021-12-31 with full
  coverage; the DB holds no daily bars for any delisted ticker before 2024. Invariant #4
  holds vacuously, and every weak-state bucket is biased upward. Fix: a point-in-time
  universe with delisted history.
- **Bootstrap draws aren't archived**, so FDR p-values are Wald approximations.
- **The decile "spread" is 10/9 × the literal top-minus-bottom.** Cost margins are about
  11% optimistic where they are thin.
- **`pattern_matches` is current-state-only.** A strictly point-in-time pattern flag needs
  the scanner re-run as of each date.
- **Missing infrastructure**: a 2022+ holdout check, U2/U3 universes, point-in-time market
  cap (M12), an earnings-date table.

## Study-level termination

The termination condition was met on 2026-09-17: DESIGN §12's minimal core (M1, M2, M4,
M5, M6.2, M11, §7.5) plus the whole-grid FDR pass. The remaining modules ran afterwards
under DESIGN §1.5's porous-scope rule. Nothing is queued.
