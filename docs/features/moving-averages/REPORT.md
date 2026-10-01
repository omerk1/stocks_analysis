# Moving-averages study — final report

**Scope:** does moving-average state (level, distance, slope, stack, crossovers, touches)
predict forward equity returns once momentum, volatility and sector are controlled for?
Twenty-four modules were run on 405 S&P 500 stocks over 2010–2021; the 2022+ holdout was
never opened. Per-cell numbers: `EXPERIMENTS.csv`. Scoreboard: `STATUS.md`. Tier 1–3
write-ups: `FINDINGS.md`.

---

## 1. Executive summary

- **One Tier-2 result, no Tier 1.** Stocks whose 50-day SMA slope is at a cross-sectional
  extreme, rising or falling, outperform stocks with a flat slope. The effect is 0.25% per
  21 days, with a 90% CI of [0.15%, 0.35%]. It holds in each tail separately, under a
  reversal control, with large moves excluded, and across seeds. It clears cost at
  20 bps. That is about 3% a year gross: a feature, not a strategy.
- **A second Tier-2 cell, found against its hypothesis (M22, 2026-10-01).** After a break above
  SMA50, a retest that holds is followed by 63-day returns 2.08% [1.14%, 3.04%] *below* an
  ordinary SMA50 bounce. Robust to the confirmation parameters, both subperiods and shorter
  horizons; survives FDR at q=0.05. The size depends on matching the 21-day return, and only
  SMA200 agrees in sign, so it needs a lookback-neighbour check before use.
- **Three of 219 tests survive whole-grid FDR** at both q=0.10 and q=0.05: the two Tier-2
  cells and M6.6's drawdown cell. The drawdown cell says that when all ribbon slopes agree, the
  next 21 days' drawdown is 0.65pp shallower, but signed return is unchanged.
- **Several effects are real but weak.** They clear C2 and most clear cost, but miss FDR
  by a factor of 1.2–1.8: low-dollar-volume reclaims (size-confounded), distance above the
  52-week low at 126 days, compression predicting move size, the fully bearish stack, and
  above/below SMA20.
- **The clearest results are nulls:**
  - MAs are not support or resistance (M5).
  - Watched lookbacks behave like unwatched neighbours (§7.5).
  - Crossover events add nothing over state (M3).
  - Kernel shape doesn't matter at matched lag (M8).
  - Weekly sampling doesn't matter (M10).
  - Slope-run persistence matches a drifting random walk (M6.4).
  - An MA reclaim inside a detected chart pattern, VCP included, shows no effect (M14).
- **Recurring shape:** most of the gross MA effect is momentum and volatility. Date
  matching and then factor matching remove 60–100% of it (§3).
- **Universe caveat:** U1 contains no ticker that delisted inside the window. Every
  beaten-down-state result is biased upward by construction (§2).

## 2. Method

- **Universe (U1):** S&P 500 members as of 2021-12-31 with full daily coverage
  2010–2021; 405 tickers, 1.22M rows. This selects on end-of-window survival and index
  membership. The database has no daily bars for any delisted ticker before 2024, so
  invariant #4 holds only vacuously.
- **Lag:** every feature is shifted one bar before pairing with a label, applied centrally
  in `features/panel.py::apply_lag`.
- **Controls:**
  - C0 is unconditional.
  - C1 matches on date.
  - C2 matches on date plus momentum tercile (`mom_12_1`), vol tercile
    (`realized_vol_63`) and sector (current-state, not point-in-time).
  - Every verdict is on C2. Reversal (`mom_1_0` tercile) and extension (`dist_pct_sma_50`
    tercile) were added as robustness controls where relevant.
- **Inference:** date-block bootstrap, block = 2 × horizon, 500 draws, 90% CI, seed 0.
  Cells with fewer than 3 blocks of dates are reported as unresolved.
- **Kill criteria:** pre-registered per module in `PREREGISTRATION.md`. Kill verdicts and
  tiers are recorded separately.
- **Costs:** measured turnover × 10 bps round trip, with linear annualisation. The decile
  "spread" statistic is 10/9 × the literal top-minus-bottom, so thin cost margins are
  about 11% optimistic.
- **Multiple testing:** Benjamini–Hochberg over the deduplicated grid (§4).
- **Synthetic gate:** `validate-synth` recovers a planted +3%/21d effect, stays silent on
  noise, and degrades under an extra one-bar shift. It does not exercise C2 or the
  bootstrap at realistic effect sizes.

## 3. Shrinkage

What most MA "effects" are made of. M1, above minus below, 21d:

| lookback | pooled | C1 | C2 |
|---|---|---|---|
| SMA20 | −0.575% | −0.273% | −0.215% |
| SMA50 | −0.559% | −0.325% | −0.183% |
| SMA200 | −0.421% | −0.181% | −0.215% (CI spans zero) |

The starkest case is M18's distance from the 52-week high at 126 days. It is −4.03% at C1
and −0.67% at C2, where the CI spans zero, so the entire effect was momentum.

## 4. Whole-grid FDR

N = 219 deduplicated tests (M19–M22 added 112 on 2026-09-30/10-01). Benjamini–Hochberg is applied to Wald p-values backed out of
each cell's CI. M6.4's cells are held at p=1, because their logged interval is a null
envelope. The full ranked table is in `STATUS.md`, and the pass is reproducible from the
ledger.

| cell | effect (90% CI) | p | survives q=0.05 |
|---|---|---|---|
| M6.6 ribbon agreement, 21d drawdown | +0.65pp (+0.44, +0.89) | 0.0000017 | yes |
| M6.3 extreme vs flat SMA50 slope | 0.25% (0.15, 0.35) per 21d | 0.00005 | yes |
| M22 held retest above SMA50 vs ordinary bounce, 63d | −2.08% (−3.04, −1.14) | 0.00033 | yes |

The next six cells (M12, M19 SMA50↓ hold, M18@126d, M7, M1 SMA20, M2) miss by a factor of 1.7–2.4, so
their status depends on grid size. p-values below about 0.004 are normal-tail
extrapolations of a 500-draw bootstrap.

## 5. Results by module

| module | result | tier |
|---|---|---|
| M1 state | SMA20/50 real, fail cost; SMA200 spans zero; state age fails plateau | 3 / 4 |
| M2 stacks | Bearish stack +1.01% over one-MA state, survivorship-capped; bullish adds nothing | 3 / 4 |
| M3 crossovers | 16 cells span zero | 4 |
| M4 distance | SMA20 −0.46%, fails cost; SMA50/200 span zero | 3 / 4 |
| M5 touch/bounce | 6 cells killed, largest CI edge 0.61pp vs 2pp floor | 4 |
| M6.1 slope vs momentum | spans zero at 4 lookbacks | 4 |
| M6.2 slope as conditioner | Rising-while-extended −0.59%, a lone pixel; touch cell dies to reversal | 3 |
| **M6.3 slope magnitude** | **U-shape at SMA50, Tier 2**; SMA200 reversal artifact; SMA20 fails cost | **2** / 3 |
| M6.4 slope persistence | 0 of 12 strata depart from a direction-matched random walk | 4 |
| M6.5 drop-off artefact | spans zero | 4 |
| M6.6 ribbon agreement | shallower drawdown +0.65pp; return spans zero | 3 |
| M7 compression | predicts \|move\| (−0.25%), not vol or direction | 3 |
| M8 MA family | Reality Check p=0.19 | 4 |
| M9 regime lookback | out-of-sample spans zero | 4 |
| M10 timeframe | null | 4 |
| M11 cross-sectional | same SMA20 signal as M4; 5d cell reversal-shaped | 3 |
| M12 volume | low-volume reclaims +0.87%, size-confounded | 3 |
| M13 regime slices | near M1's baseline, no interaction | 3 / 4 |
| M14 pattern context | pooled +0.07%, VCP +0.85%, both span zero | 4 |
| M15 synthesis | VCP reclaims under-represented in the slope tail (Track A) | — |
| M16 linear filters | MA rules cluster by effective lookback (Track A) | — |
| M17 oscillators | MACD marginal (+0.009 IC), RSI and %K span zero | 3 / 4 |
| M18 52-week range | near-low +2.50% at 126d, clears cost; near-high spans zero | 3 / 4 |
| M19 respect history | killed, 0 of 8; hold rates flat across prior bounces at real and synthetic MAs; two C2+rev-only CIs are thin-strata reads | 4 / 3 |
| M20 bounce as entry | killed, 0 of 32; a confirmed bounce's forward return matches a same-size move without the MA, and tilts to reversal, not continuation | 4 / 3 |
| M21 break as entry | killed, 0 of 32; a confirmed break through the MA tracks any same-size move; one SMA50 breakdown cell right-signed but fragile | 4 / 3 |
| **M22 break and retest** | **killed as hypothesised; a held retest above SMA50 underperforms an ordinary bounce by 2.08% at 63d, Tier 2** | **2** / 3 / 4 |
| §7.5 placebo | no lookback is special | 4 |

## 6. Suggestive (Tier 3)

These are real at C2 but not FDR survivors, or they carry an open confound. Full entries
are in `FINDINGS.md`.
- Low-dollar-volume SMA50 reclaims (M12): size proxy.
- Distance above the 52-week low at 126d (M18): momentum-adjacent and
  survivorship-exposed.
- Compression predicting move size (M7): not directional.
- The bearish stack (M2): survivorship-capped.
- Rising slope while extended (M6.2): a lone pixel.
- MACD histogram (M17): marginal.
- SMA20 distance and state (M1, M4, M11): fail cost.

## 7. Dead ends

Every Tier-4 cell is in `EXPERIMENTS.csv` with its number and effective N. The ones worth
remembering before trying again:
- **Support/resistance at MAs (M5, §7.5), and its persistence per name (M19).** A first
  touch holds no better than at an unwatched neighbour, an MA that held twice recently
  does not hold better next time, and neither a confirmed bounce (M20) nor a confirmed break
  through (M21) is an entry: both carry the forward return of any ≥1 ATR move. Revisit only
  with intraday touches; the study used closes.
- **Crossovers (M3), kernel choice (M8), weekly sampling (M10), regime-chosen lookbacks
  (M9).** Revisit only with a genuinely new construction.
- **Proximity to the 52-week high (M18).** It is momentum.
- **Slope-run persistence (M6.4).** It matches a drifting random walk.
- **Chart-pattern context (M14).** An as-of-safe flag gives nothing. Any rerun must use
  patterns detected as of each date.

## 8. Cost

Cells whose CI edge nearest zero clears cost, annualised, at 10 bps:

| cell | hurdle | CI ends (per year) | clears at 20 bps |
|---|---|---|---|
| M6.3 SMA50 (Tier 2) | 0.77% | −1.83% / −4.25% | yes |
| M6.6 drawdown | 0.54% | +5.25% / +10.64% | yes (avoided loss) |
| M12 dollar volume | 0.29% | −4.82% / −16.57% | yes |
| M18 52w low, 126d | 0.83% | +2.21% / +8.03% | yes |
| M7 magnitude | 0.32% | −1.11% / −4.77% | yes (not directional) |
| M2 bearish stack | 0.30% | +1.70% / +8.98% | yes; reversal-controlled fails even at 10 bps |
| M6.2 extension × slope | 0.81% | −2.10% / −12.56% | yes |
| M6.3 SMA200 | 0.38% | −0.67% / −4.04% | no |

M1, M4, M11 at 21d, and M18 at 63d fail cost at 10 bps.

## 9. Reproducibility and what's missing

- **Panel**: `python -m src.signals.moving_averages.cli build-panel --universe sp500`
  builds `data/features/moving_averages/ma_panel/`.
- **Gates**: `pytest tests/test_moving_averages_*.py` and `cli validate-synth` must pass.
- **Module drivers**: `src/signals/moving_averages/*_run.py`.
- **FDR**: `whole_grid_fdr_run.py`.
- **Seeds and bootstrap**: seed 0, 500 draws, 90% CI, block = 2 × horizon.
- **Before any Tier-3 cell could move up, the study would need**:
  - a point-in-time universe with delisted history;
  - the 2022+ holdout;
  - U2/U3 universes;
  - point-in-time market cap;
  - an earnings-date table;
  - archived bootstrap draws;
  - a patterns scanner run as of each date.
