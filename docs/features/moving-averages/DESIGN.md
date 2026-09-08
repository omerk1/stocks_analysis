# Design Doc: A Systematic Study of Moving-Average Behaviour in Equities

**Status:** Draft v1.0
**Type:** Research design (analysis, not a production strategy)
**Owner:** _(you)_

---

## 0. TL;DR for the impatient

We are going to build a **panel study of moving-average (MA) states and events** across a broad equity universe, and measure forward outcomes conditional on those states — always against a matched control, always with an explicit accounting for how many hypotheses we tested.

The single most important design decision in this whole document is this one:

> **Almost every MA "signal" is a re-encoding of price momentum. The research question is never "does this signal predict returns?" — it is "does this signal predict returns *beyond what a plain trailing-return momentum baseline already predicts*?"**

If you take nothing else from this doc, take that. A study that reports "stocks above their 200-day SMA returned 14% annualised vs 2% for stocks below" has discovered nothing except that stocks that went up recently tend to have gone up recently. Half of the published MA literature is exactly this mistake with better typesetting.

The second most important decision: **report effect sizes against a base rate, with an honest effective sample size.** Twenty-five years of daily data with 12-month forward returns is roughly 25 independent macro observations, not 6,000.

The deliverable is not a strategy. It is an **insight ledger**: a set of claims, each with an effect size, a confidence tier, the conditions under which it holds, and — critically — a list of directions we tested and killed.

---

## 1. Motivation and scope

### 1.1 What prompted this

Practitioner folklore around MAs is enormous, specific, and almost entirely untested in public:

- Minervini's Trend Template uses a 50/150/200-day SMA stack as a Stage-2 uptrend filter.
- Weinstein's stage analysis (the ancestor of the above) uses the 30-week MA.
- Swing traders treat the 8/9-day and 20/21-day EMAs as dynamic support in strong trends.
- "Golden cross" / "death cross" (50/200) get media coverage every time they fire.
- Extension from the 50-day SMA measured in ATR multiples (the "7–8× ATR is exhausted" heuristic) is widely traded and rarely validated.

Some of this is probably real. Some is probably a repackaging of momentum. Some is probably pure narrative. We want to know which is which, and we want the negative results written down as carefully as the positive ones.

### 1.2 Research questions

**Primary:**

1. **State conditioning.** How do forward return distributions differ conditional on a stock's MA state (above/below, stacked/unstacked, slope sign)? How much of that difference survives momentum-matching?
2. **Transitions.** Do MA *crossings* (both price×MA and MA×MA) carry information beyond the *state* they transition into?
3. **Distance.** Is displacement from an MA — in %, in ATR multiples, in a rolling z-score — monotonically related to forward return? Where does the sign flip from momentum to mean-reversion, and what conditions the flip?
4. **Level interaction.** Do MAs act as support/resistance in a way that is distinguishable from generic trend behaviour? (Placebo-testable — see §7.5.)
5. **Regime dependence.** Does the best short-term MA lookback change with regime (trending vs choppy, high vs low vol)? Is that dependence stable enough to exploit, or is it a fitting artefact?
6. **Slope and curvature.** Does the direction, magnitude, and rate-of-change of the MA itself carry information — as a standalone signal, and as a conditioner on every other MA state? Is MA slope anything other than a rescaled momentum measure?
7. **Family and horizon.** At matched lag, does the weighting kernel (SMA/EMA/WMA/HMA/KAMA) matter? Does daily vs weekly sampling matter beyond the implied lookback change?

**Secondary:**

8. Ablation of Minervini's Trend Template: which of the eight criteria carry the information, and which are free riders?
9. Ribbon geometry: does compression (low dispersion between MAs) predict expansion, and does expansion direction have any predictability at all?
10. Cross-sectional vs time-series: is "stock is furthest above its 50-day in its sector" a better signal than "stock is above its 50-day"?
11. What is the cost-adjusted survivability of anything we find?

### 1.3 Explicit non-goals

- **Not** building a live trading strategy. Strategy construction is a follow-on project that consumes this study's output.
- **Not** searching for optimal parameters. We search for *plateaus* and *monotonicities*, never for a peak. (See §6.7 — this is a hard rule, not a preference.)
- **Not** intraday. Daily bars are the base resolution; weekly and monthly are resampled from dailies.
- **Not** options, futures, crypto, or FX in v1. The universe design and the confounds differ enough to warrant separate work.
- **Not** machine learning in v1. If the panel is clean and the effect sizes are honest, a linear/tabulated analysis will tell us the truth. ML on this panel before we understand the confounds will produce a beautiful model of survivorship bias.

### 1.4 What "done" looks like

A report containing:

- ~15–30 falsifiable claims, each with a confidence tier (see §9.2).
- A **dead-ends register** — directions tested and abandoned, with the evidence that killed them, so nobody (including future-you) re-runs them.
- A reusable feature layer (`ma_state` panel) that plugs into your existing detector framework.
- A cost-sensitivity appendix showing which claims survive realistic frictions.

### 1.5 Research stance: exploratory-first, with a confirmatory gate

**This is a discovery project, not a validation project.** The goal is to find interesting things in and around the MA space — including things not anticipated in §1.2 — and only *then* to subject the survivors to hard testing. Read the rest of this document with that ordering in mind.

There is a genuine tension to manage here. The statistical machinery in §6 (pre-registration, FDR correction, locked holdout, kill criteria) is the right way to *validate* a claim, and the wrong way to *generate* one. You cannot pre-register a hypothesis you haven't had yet, and a protocol that charges you a multiple-testing penalty for every look will make you stop looking. Applied from day one, §6 would quietly kill the project's actual purpose.

So the work runs on **two tracks with different rules**, and the only unbreakable rule is that a result must not silently move between them.

#### Track A — Exploration (wide, cheap, creative, no correction)

**Rules:** Look at everything. Follow hunches. Slice by anything. Plot before you test. Chase weird residuals. Invent new features mid-stream. **No multiple-testing correction is applied**, because none of Track A's output is a claim — it's a hypothesis generator.

**Constraints (only three, but they're absolute):**
1. **Holdout stays closed.** Track A runs on the development window only. This is the one boundary that makes the whole scheme work.
2. **Nothing from Track A is stated as a finding.** Everything is tagged `EXPLORATORY` in notebooks, figures, and conversation. No effect size from Track A appears in the final report except as motivation for a Track B test.
3. **Log every look.** A running `EXPLORATION_LOG.md` — one line per thing you looked at, whether or not it went anywhere. This is not bureaucracy: it's the only honest way to reconstruct how many hypotheses the data actually generated, which is what Track B's correction denominator needs.

**Output:** a shortlist of candidate hypotheses, each with a mechanism story ("why might this be true?") and a rough effect size.

#### Track B — Confirmation (narrow, expensive, everything in §6 applies)

Takes the Track A shortlist, pre-registers it (§6.6), and runs the full protocol: matched controls, plateau rule, definitional sensitivity, FDR, costs, holdout.

**The gate between tracks:** a hypothesis is only promoted to Track B if it has (a) a plausible mechanism, not just a good number, and (b) survives a quick re-slice on a different universe tier or subperiod within the development window. This costs an hour and kills most of the shortlist, which is the point.

**Expected ratio:** Track A should generate 100+ things worth a second look; ~20 should reach the gate; ~10 should get pre-registered; 3–6 should survive. If Track A is generating fewer than 50 candidates, you are not exploring hard enough. If Track B is confirming more than 10, your controls are broken.

#### Scope: deliberately porous

The §1.2 questions are a starting point, not a fence. Anything in the same spirit — dynamic-mean behaviour, trend-state representation, level-based reference points, the geometry of how price organises around its own history — is in scope if it looks interesting. **Appendix D lists adjacent directions worth exploring that fall outside the original question set**, and that list is meant to grow as the work proceeds. Adding to it is a deliverable, not a distraction.

On other indicators (RSI, MACD, oscillators generally): the naive answer is "out of scope, MA study." That answer is wrong, and the reason is worth stating up front. **Several widely-used indicators are MA constructs under a different name and are therefore already inside this study whether we acknowledge them or not** — MACD is an EMA crossover spread, Keltner Channels are an MA ± ATR band, Bollinger %B is a rolling z-score of distance from an MA. Excluding them by label while including them by formula would be incoherent. **Appendix E** classifies the common indicators into *already in scope in disguise*, *genuinely new operation, worth a probe*, and *actually out*, and M17 handles the probes.

The line that does hold: indicators enter as **conditioners, redundancy tests, or nonlinearity probes** — not as co-equal subjects. Promoting RSI to a first-class subject would multiply the pre-registered grid, dilute the effort, and require redoing the §7 confound analysis for a different feature family. Adding it as a conditioner costs almost nothing. What stays out entirely: chart patterns, candlestick formations, and market internals, where the confound structure really is different.

---

## 2. Prior art: what the literature and the practitioner community already say

Useful as **priors to test**, not as established fact. Note the conflicts — they're the most interesting part.

### 2.1 Academic

| Work | Claim | How we should treat it |
|---|---|---|
| Brock, Lakonishok & LeBaron (1992) | Simple MA rules on DJIA showed predictive value 1897–1986 | Foundational, but the classic data-snooping critique applies |
| Sullivan, Timmermann & White (1999) | Applying White's Reality Check to the BLL universe of rules substantially weakens the result | **Directly motivates our §6.6 multiple-testing protocol** |
| Zakamulin (multiple, 2014–2017) | Reported outperformance of MA timing rules is largely data-mining and, in some published cases, look-ahead bias; there is no single stable optimal lookback; out-of-sample performance is far weaker than in-sample | Strongest prior we have. Treat "the optimal MA length" as a non-question |
| Glabadanidis (2015) vs Zakamulin's rebuttal | Spectacular MA timing results traced to look-ahead in the simulation | A cautionary tale we will guard against structurally (§7.2) |
| "Price Distance to Moving Averages and Subsequent Returns" (IJECM, 2017) | US stocks below their MAs outperformed those above; the effect is strongest for 20/50-day MAs at 1–2 week horizons; best returns 0–5% below the short MAs | Mean-reversion evidence at short horizons |

### 2.2 Practitioner / vendor research

| Source | Claim | Note |
|---|---|---|
| CXO Advisory (2017) | Golden/death cross nomenclature is overdramatic; DJIA 126-day forward returns after death vs golden crosses were 2.8% vs 2.3% — i.e. barely distinguishable. S&P 500 showed more separation (3.8% vs 6.4%). Worst drawdowns *do* cluster after death crosses (1973, 2000, 2007) | Sample: ~58 signals per side over 90 years. **Effective N is tiny.** Suggests the death cross may be a tail/drawdown signal, not a mean-return signal |
| QuantifiedStrategies | Death cross → below-random returns for <30 days, roughly in line with random beyond; death-cross-exit/golden-cross-reentry ≈ buy-and-hold returns with materially lower drawdown | Consistent with "trend rules are risk-shapers, not return-generators" |
| tosindicators (2026) | 54% of the time the market had already bottomed before the death cross printed | Lag quantification — worth reproducing |
| Jeff Sun / theStratLab | Price reaching 7.5–8× ATR above the 50-SMA is statistically rare and marks exhaustion | Popular; testable |
| backtest.substack (2026) | On Nasdaq-100 over 25 years, high ATR-extension from the 50-SMA led to *continued outperformance* to 120+ days — momentum, not reversion | **Directly contradicts the previous row and the IJECM paper** |

### 2.3 The conflict is the opportunity

The extension literature disagrees with itself. Our hypothesis for why, which we will test explicitly in **M4**:

1. **Horizon.** Reversion may dominate at 1–10 days; continuation at 60–250 days. Both papers can be right about different horizons.
2. **Universe.** Nasdaq-100 members are survivors of a momentum filter. A broad universe including microcaps and eventual delistings will behave differently. Selection is doing work here.
3. **Normalisation.** This is the subtle one. **ATR-normalised distance implicitly conditions on volatility.** Sorting on `(price − MA) / ATR` puts low-volatility names at high multiples for small percentage moves. Since low volatility is itself a documented return predictor, an ATR-extension study without a volatility control is partly measuring the low-vol anomaly wearing a moustache. Percentage distance has the opposite tilt. **We must run both normalisations and a vol-neutralised version.**
4. **Conditioning on trend quality.** Extension in a high-efficiency-ratio trend is a different animal from extension in a chop spike.

If we resolve this cleanly, that alone justifies the project.

---

## 3. Data design

Garbage here invalidates everything downstream, and the failure is silent.

### 3.1 Requirements

| Requirement | Why | Failure mode if ignored |
|---|---|---|
| **Delisted securities included** | Survivorship | Every downtrend signal looks better than it was; "below the 200-day" gets systematically over-rewarded because the worst outcomes were deleted |
| **Point-in-time index membership** | Avoid look-ahead in universe definition | "S&P 500 stocks since 2000" means today's members, i.e. winners |
| **Split & dividend adjusted, consistently** | MA continuity | Unadjusted splits create fake 50% gaps and phantom MA crosses |
| **Adjustment applied as of the analysis date, not today** | Subtle look-ahead | Back-adjusted dividend series changes historical percentage returns; acceptable for MA geometry, must be documented |
| **True OHLC, not just close** | Touch/ATR logic needs highs and lows | Touch events undercounted by a lot |
| **Volume + dollar volume** | Liquidity filters, VWMA | Illiquid names dominate extreme buckets |
| **Corporate action flags** | Exclusion windows | Reverse-split microcaps generate spectacular fake signals |
| **Earnings dates (point-in-time)** | Biggest single confound (§7.4) | Gap returns get attributed to MA states |
| **Sector/industry (point-in-time)** | Clustering, neutralisation | 2000 and 2021 results become sector bets in disguise |

### 3.2 Universe tiers

Run every analysis on all three. Where results differ across tiers, that *is* a finding.

- **U1 — Liquid large/mid:** price > $5, 60-day median dollar volume > $10M, market cap > $1B. ~1,500–2,500 names at any time. This is where the folklore actually gets traded.
- **U2 — Broad investable:** price > $2, ADV > $1M. ~4,000–5,000 names. Tests generality.
- **U3 — Index/ETF:** SPY, QQQ, IWM, sector SPDRs, plus a few international. Tiny N, but this is where the golden-cross literature lives, and it is the only place a "market regime" signal can be defined.

Additional cuts to carry as covariates throughout: market cap decile, realised-vol decile, sector, price decile.

### 3.3 Sample period

- **Development window:** 2010-01-01 → 2021-12-31. Contains the 2011 correction, the 2015–16 slide, 2018Q4, the COVID crash and V-recovery, and the 2020–21 pandemic-liquidity bull.
- **Holdout (locked, untouched):** 2022-01-01 → present. Contains the 2022 bear market and the 2023–25+ regime.
- Optional **deep history** (1962+, index-level only) for regime-count sanity checks.

**Revised from the original 2000-2016/2017+ split** (decided 2026-09-07): the Phase 0 hygiene audit found active-ticker history in the loaded data mostly starting in 2010 or later, so 2000-2016 wasn't a usable development window (§12's development-window-coverage item has the coverage numbers). This split is what the loaded data actually supports. It does not touch the delisted-history gap — that's still handled entirely by §7.3's Tier-3 cap on weak-state/death-cross/negative-extension claims, independent of where the window boundaries sit.

**The holdout gets opened once.** Not once per module — once, at the end, for the final claim set. Write this in the repo README and make it socially expensive to violate. Every peek costs you a real degree of freedom.

### 3.4 Data hygiene tests (as unit tests, run in CI)

- No forward-filled prices across halts creating flat MA segments.
- Returns beyond ±50% in a day flagged and manually reviewed (usually bad data or a corporate action).
- MA values reproduce a reference implementation to 1e-9 on a golden fixture.
- Random spot-check: 20 (ticker, date) pairs against a chart provider.
- Delisted-name count per year is non-trivial and roughly matches expectation (if you have zero delistings, your data vendor is lying to you).

---

## 4. The feature layer: an MA state vector

Compute once, cache as partitioned Parquet, reuse everywhere. This is the reusable asset that outlives the study.

### 4.1 MA families

| Family | Include in v1? | Rationale |
|---|---|---|
| SMA | Yes | The folklore baseline; what everyone watches |
| EMA | Yes | Short-term folklore (8/9, 20/21) is EMA-native |
| WMA | Yes | Cheap, completes the linear-kernel set |
| HMA | Yes | Popular low-lag claim, worth falsifying |
| DEMA / TEMA / ZLEMA | Phase 2 only | Likely dominated by EMA at matched lag; include only for the horse race |
| KAMA (Kaufman) | Yes | Directly relevant to the regime question (M9) |
| VWMA | Yes | Volume interaction |
| Median / Kalman | No | Out of scope for v1 |

**Critical: match by lag, not by label.** Comparing SMA(50) with EMA(50) is not a fair fight. Use centre of mass:

- SMA(n): COM = (n−1)/2
- EMA(α): COM = (1−α)/α; with α = 2/(n+1), COM = (n−1)/2
- WMA(n): COM = (n−1)/3

So EMA(50) and SMA(50) are lag-matched, but WMA(50) is *substantially faster* than both and must be compared against WMA(≈74) to be honest. **A horse race that doesn't lag-match is a horse race about lookback length wearing a costume.** Build a `lag_matched_family_set(target_com)` helper and use it everywhere.

### 4.2 Lookback grid

Chosen for coverage and folklore relevance, not exhaustiveness:

- **Ultra-short:** 3, 5, 8, 9, 10
- **Short:** 13, 20, 21, 30
- **Intermediate:** 50, 65, 100
- **Long:** 150, 200, 250
- **Weekly (from weekly bars):** 10, 30, 40
- **Monthly:** 10, 12

Note that weekly 10/30/40 ≈ daily 50/150/200. Keep both — the difference is *sampling frequency*, not lookback, and that difference is itself an experiment (M10).

**Grid discipline:** any claim about a specific lookback must be accompanied by its neighbours. If 50 works and 45 and 55 don't, 50 doesn't work.

### 4.3 Derived features (the state vector)

For each (ticker, date, MA):

**Position**
- `dist_pct = (close − ma) / ma`
- `dist_atr = (close − ma) / ATR(14)`
- `dist_z = z-score of dist_pct over trailing 252d` (per-ticker self-normalisation)
- `dist_pctile = percentile rank of dist_pct over trailing 756d`
- `above = 1[close > ma]`
- `days_above` / `days_below` (run length of current state)
- `touched_today = 1[low ≤ ma ≤ high]`
- `near_atr = |close − ma| / ATR(14) < θ` for θ ∈ {0.25, 0.5, 1.0}

**Slope / shape**
- `slope_pct_k = ma_t / ma_{t−k} − 1` for k ∈ {1, 3, 5, 10, 21, 63}
- `slope_log_k = ln(ma_t) − ln(ma_{t−k})` — **the only scale-invariant version**; use this as primary
- `slope_atr_k = (ma_t − ma_{t−k}) / (k · ATR)` — per-day slope in volatility units, comparable across names
- `slope_sign`, `days_slope_positive` (run length), `slope_flip` event
- `slope_pctile_k` — rank of current slope vs its own trailing 252d history (self-normalised "is this MA rising unusually fast for this stock")
- `slope_rank_k` — cross-sectional rank of slope within universe/sector
- `curvature_k = slope_k(t) − slope_k(t−k)` (is the MA rolling over or accelerating?)
- `dropoff_contribution` — for SMAs only, the share of today's slope attributable to the bar *leaving* the window rather than the bar entering it (see §8/M6 and Appendix A; this is a real artefact, not a nicety)
- `slope_agreement` — fraction of the ribbon with positive `slope_log_21`

**Pairwise (for each MA pair, short S and long L)**
- `spread_pct = (ma_S − ma_L) / ma_L`
- `spread_atr`
- `cross_up` / `cross_down` events
- `days_since_cross`
- `stacked = 1[ma_S > ma_L]`
- `ppo = (ma_S − ma_L) / ma_L × 100` — the scale-invariant MACD. **Use this, never raw MACD**, which is in price units and therefore not comparable across tickers or across time for the same ticker
- `ppo_signal = EMA_9(ppo)`, `ppo_hist = ppo − ppo_signal`
- `ppo_above_zero = stacked` (identical — kept as a named alias to make the redundancy visible in the feature dictionary rather than hidden)
- `ppo_above_signal` — the spread rising relative to its own smoothing; an acceleration condition, not a level condition

**Ribbon (for a defined set, e.g. {10, 20, 50, 100, 200})**
- `stack_perm`: the permutation/ordering of MAs → categorical state (24 states for 4 MAs, 120 for 5; bucket into "fully bullish / fully bearish / mixed")
- `ribbon_width_atr = (max(ma) − min(ma)) / ATR`
- `ribbon_width_pctile` over trailing 252d → **compression detector**
- `ribbon_slope_agreement`: fraction of MAs with positive slope

**Regime (computed per ticker AND per market index)**
- `ER_n = |close_t − close_{t−n}| / Σ|close_i − close_{i−1}|` (Kaufman efficiency ratio) for n ∈ {10, 20, 50}
- `ADX(14)`
- Choppiness index (with the caveat that it is window-sensitive and not scale-normalised across instruments — prefer ER as the primary)
- `realized_vol_20/60`, `vol_of_vol`
- `atr_pct = ATR(14)/close`
- Market-level: `pct_above_200d` (breadth), index MA state, VIX level and VIX percentile
- `regime_label` from a simple, pre-registered rule (do not fit this)

**Context**
- `dist_from_52w_high`, `dist_from_52w_low`
- `rs_rank` (cross-sectional 6m or 12-1 return rank) — **this is the momentum control, and it is load-bearing**
- `days_to_next_earnings`, `days_since_last_earnings`
- `gap_pct` at open
- `dollar_volume_pctile`

### 4.4 Panel schema

```
ma_panel/
  date=YYYY-MM-DD/
    part-*.parquet
```

Columns: `ticker, date, [OHLCV], [feature columns...], universe_flags, sector, mktcap_decile`

One row per (ticker, date). Wide. Expect ~5,000 × 6,500 ≈ 32M rows for U2 over 25 years; with ~200 float32 columns that's ~26 GB — partition by year, and materialise per-module feature subsets rather than loading the whole thing.

### 4.5 Event table schema

Every analysis reduces to this shape. Standardising it is what makes the study composable.

```
event_id, ticker, date, event_type, event_params (json),
  # state at t0
  regime_*, rs_rank, vol_decile, sector, mktcap_decile, dist_*, ...
  # forward outcomes
  fwd_ret_1, fwd_ret_3, fwd_ret_5, fwd_ret_10, fwd_ret_21, fwd_ret_63, fwd_ret_126, fwd_ret_252,
  fwd_exret_* (vs benchmark), fwd_alpha_* (beta-adjusted), fwd_sector_rel_*,
  mfe_atr_21, mae_atr_21, mfe_atr_63, mae_atr_63,
  tb_label_21 (triple-barrier), tb_hit_time,
  vol_norm_ret_21 = fwd_ret_21 / (atr_pct * sqrt(21)),
  # control matching
  control_stratum_id
```

---

## 5. Outcome (label) design

### 5.1 Horizons

1, 3, 5, 10, 21, 63, 126, 252 trading days. Always report the full term structure. **A signal that only works at one horizon and vanishes at the neighbours is noise.** The shape of the term structure is often more informative than any single number — a decaying-positive curve means something very different from a hump at 21 days.

### 5.2 Return definitions — use all four, they answer different questions

1. **Raw forward return.** Contaminated by market beta. Almost never the right headline number.
2. **Excess vs benchmark** (SPY, or U1 equal-weight). Removes the market's drift, which is *the* dominant confound for any long-only conditioning signal.
3. **Beta-adjusted alpha.** Uses trailing 252d beta. Necessary because high-beta names are systematically more often above/below MAs in trends.
4. **Sector-relative.** Removes the "you discovered that energy did well in 2021" failure.

**Report #2 as the headline.** If a claim only survives on raw returns, it is a claim about the equity risk premium.

### 5.3 Path metrics — do not skip these

Terminal return hides everything a trader cares about.

- **MFE / MAE** in ATR units over each horizon. This is where "the 21-EMA is good support" would show up if it's real: not as higher mean return, but as **smaller MAE**.
- **MAE/MFE ratio** and hit rate at R multiples (1R, 2R, 3R with R = 1 ATR or 1.5 ATR).
- **Max drawdown** over the horizon.
- **Time to +1 ATR vs time to −1 ATR.**

The golden/death cross literature strongly hints that trend rules shape the *drawdown distribution* rather than the mean. If we only measure means, we will conclude "no edge" and be wrong about what the edge is.

### 5.4 Triple-barrier labels

For a subset of event studies, apply López de Prado-style barriers: upper at +k·ATR, lower at −k·ATR, vertical at H days, k ∈ {1, 2, 3}. Gives a label that mirrors how a trade would actually resolve and is robust to the terminal-return-hides-the-path problem.

### 5.5 Volatility normalisation

Always carry a vol-normalised return alongside the raw. Otherwise every "extreme" bucket is dominated by high-vol names and you are measuring the vol factor.

---

## 6. Statistical methodology

This section is the difference between a study and a slideshow.

### 6.1 Everything is measured against a matched control

For every conditional statistic, compute the same statistic on a control set. Three control tiers, in increasing strictness:

- **C0 — Unconditional:** all (ticker, date) pairs in the same universe. Cheapest, weakest.
- **C1 — Date-matched:** for each event on date *d*, sample non-event names from the same universe on the *same date*. **Removes the market-return confound entirely.** This should be your default.
- **C2 — Date + momentum + vol + sector matched:** same date, same `rs_rank` decile, same vol decile, same sector. **This is the one that separates real MA information from momentum re-encoding.**

**Headline result format is always a delta:** `E[fwd_exret | event] − E[fwd_exret | C2]`, with a bootstrapped CI on the difference.

My strong prior: many effects that look enormous vs C0 shrink by 70–90% against C2. **That shrinkage is the most valuable output of this entire study.** Publish the shrinkage table prominently — it's the thing nobody else publishes.

### 6.2 Overlapping observations

21-day forward returns on daily data overlap 20/21. Naive t-stats will be inflated by roughly √21 ≈ 4.6×.

Mitigations (use at least two):
- **Newey–West** SEs with lag = horizon.
- **Block bootstrap** with block length ≥ 2× horizon, resampling *dates* not rows.
- **Non-overlapping subsample** as a sanity check (sample every H-th day) — lower power, but unbiased.

### 6.3 Cross-sectional dependence

Events cluster: on the day the market gaps down, 800 stocks lose their 50-day simultaneously. Those are **not 800 independent observations.**

- Cluster standard errors **by date** (this is non-negotiable).
- Report **effective N ≈ number of distinct event dates**, alongside raw N, in every table. If a table shows N = 45,000 and effective N = 61, the reader needs to see both.
- For time-series claims (index level), report the number of independent **cycles**, which is typically < 10.

### 6.4 Effective sample size — be brutal about this

State it explicitly in the report:

- 25 years of daily data, 252-day forward horizon → ~25 independent macro observations.
- Number of full bull/bear cycles since 1990 → ~4.
- Number of golden crosses on SPY since 1950 → ~35.

**Therefore: any claim conditioned on "market regime" has an effective N in the single digits and cannot be more than Tier-3 evidence (§9.2), no matter how pretty the bars look.** Write this in the report body, not a footnote. It will save you from the most seductive class of false discovery in this entire domain.

### 6.5 Cross-sectional vs time-series inference

Cross-sectional claims ("among stocks today, those X% above their 50-day outperform those Y% above") have far more effective N than time-series claims ("when SPY crosses its 200-day, go long"). **Prefer cross-sectional formulations wherever the question permits.** Much of the folklore is stated in time-series form purely for historical reasons, and restating it cross-sectionally often makes it testable with 100× the power.

### 6.6 Multiple testing

We will run thousands of hypotheses. Without correction we will "discover" dozens of edges that are pure noise.

- **Pre-register the grid.** Write the full list of (MA family × lookback × event type × horizon × universe) combinations *before* running anything. Commit it. Count it. That count *N_tests* is your correction denominator.
- **Benjamini–Hochberg FDR at q = 0.10** as the primary screen. Bonferroni is too conservative for exploratory work at this scale.
- **White's Reality Check / Hansen's SPA** for the best-rule-in-a-family questions (the horse races in M8, M9). This is precisely the setting those tests were built for.
- **Deflated Sharpe ratio** for any backtest-shaped output.
- Any result that only survives at q = 0.10 and dies at q = 0.05 is Tier-3 at best.

### 6.7 The plateau rule (hard requirement)

**A parameter result is only credible if its neighbours agree.** Report every parameter finding as a surface, not a point:

- Vary lookback ±20% → effect should decay smoothly, not cliff.
- Vary threshold ±25% → same.
- Vary horizon to adjacent values → same.
- Vary universe tier → same sign, similar magnitude.

If the heatmap is a lone bright pixel in a field of noise, **it is noise**. Say so, in the report, by name. Include the heatmaps even for the failures — a picture of a noisy surface is one of the most persuasive negative results you can produce.

### 6.8 Definitional sensitivity

Every event definition has arbitrary choices. Vary them and confirm the result doesn't hinge on one:

- Cross defined on close vs on intraday high/low.
- Cross with a buffer (0.1%, 0.25%, 0.5×ATR) to suppress micro-whipsaws.
- Confirmation requirement (must hold for 1/2/3 days).
- Touch defined as `low ≤ ma ≤ high` vs `|close − ma| < 0.25 ATR`.

If a "signal" appears with a 0.1% buffer and vanishes with 0.25%, it lives entirely in the noise band.

### 6.9 Minimum sample thresholds

No bucket reported with fewer than **200 events across at least 30 distinct dates and 30 distinct tickers.** Buckets below threshold are shown as greyed cells with the N, never as a number that invites interpretation.

### 6.10 Costs

Every claim that implies trading gets a cost annotation:
`signals_per_year × (spread/2 + commission + slippage)`. Use tiered slippage by ADV decile: 5 bps for U1, 15 bps for U2, 40 bps for the illiquid tail.

**A 5-EMA crossover rule generating ~50 round trips/year at 10 bps each carries a 5%/yr hurdle.** State the hurdle next to the gross edge, always. Most short-lookback findings will die here, and they should die visibly.

---

## 7. Confounds and traps

A dedicated section because these are what actually kill studies like this.

### 7.1 Momentum collinearity (the big one)

`price > 50 > 150 > 200 SMA, all rising` is, to a first approximation, a noisy indicator function for "this stock's trailing 6–12 month return was positive and smooth." Cross-sectional momentum is a well-documented factor. Any MA study that doesn't control for it is a momentum study with extra steps.

**Mitigation:** the C2 control (§6.1), plus an explicit regression:

```
fwd_exret ~ β₀ + β₁·mom_12_1 + β₂·mom_6_1 + β₃·vol + β₄·size + β₅·MA_FEATURE + ε
```

**β₅ is the entire finding.** Everything else in this document exists to make β₅ believable.

### 7.2 Look-ahead

The failure mode that produced published-then-retracted results. Structural defences:

- **Signal at close of day t → execution at open (or close) of day t+1.** Never same-bar. Enforce with a lag applied centrally in the feature builder, not per-analysis.
- Never use a full-period z-score, percentile, or normalisation — all rolling, all trailing.
- Universe membership determined by data available at t.
- Write an automated test: shift every feature forward by one day and confirm results degrade. **If they don't degrade, you have a bug.** This test catches more than code review does.

### 7.3 Survivorship and delisting returns

Delisted names need a terminal return, not a NaN. Bankruptcies get −100% (or the actual final value); acquisitions get the deal price. Dropping them biases every "weak MA state" bucket upward, which is precisely the bucket where the interesting downside information lives.

**Current data-limitation ceiling (found in the Phase 0 hygiene audit, 2026-09-07 — see §12's development-window-coverage item).** Delisted-ticker price history in the data loaded for this study exists only for 2024–2026 (Polygon's ~2-year free-tier entitlement); there is **zero delisted coverage before that**. This is a ceiling on what the current data can support, **not a market-behavior finding**, and must be carried as one until it's fixed.

Until either **(a)** delisted-history pre-2024 is acquired, or **(b)** the bias is explicitly bounded — e.g. by comparing this study's findings against a published reference that did use full delisted-history data (CXO Advisory's golden/death-cross study, the IJECM distance-to-MA paper) and reporting the direction and rough size of the gap between our number and theirs:

- Any Track B claim from **M1's weak/below-MA-state buckets**, **M3's death cross specifically**, or **M4's negative-extension bucket** is **capped at Tier 3 ("suggestive, not actionable"), regardless of what the statistics show**. A result that looks Tier 1/2 in one of these specific buckets does not get promoted past Tier 3 while this ceiling stands.
- **Bullish/continuation modules are not subject to this cap.** Survivors dominate the "above MA," "golden cross," and positive-extension populations whether or not delisted names are included, so the missing data doesn't bias those buckets the same way.

The cap applies narrowly, to the specific weak/bearish buckets named above — not to M1/M3/M4 wholesale — and is lifted the moment condition (a) or (b) is actually met, not left standing indefinitely out of caution once it has been.

### 7.4 Earnings

Earnings gaps are the largest single-day moves for most stocks and are unrelated to MA geometry. If an "MA support bounce" study happens to oversample pre-earnings windows, you're measuring earnings drift.

**Mitigation:** run every analysis twice — all events, and events excluding a ±3 day earnings window. Report both. Where they differ, the earnings version is a separate (and possibly more interesting) finding.

### 7.5 Level effects vs trend effects — the placebo test

The most elegant test in this whole document. Does the 200-day SMA matter *because it is watched*, or is it just a proxy for "10-month trend"?

**Placebo design:** run the identical analysis on the 187-day, 193-day, 207-day, and 213-day SMAs. These are statistically near-identical to the 200-day but nobody watches them.

- If **200 significantly outperforms its neighbours** → evidence of a genuine reflexive/self-fulfilling level effect. Genuinely novel and publishable.
- If **the whole neighbourhood performs identically** → there is nothing special about 200; you have measured a ~10-month trend, and every article about "the magic 200-day" is folklore.

My prior: the second, strongly. But this is cheap to run and the answer is interesting either way. Run the same placebo on 50 (vs 47/53) and on the 21-EMA (vs 19/23).

### 7.6 Round numbers and price clustering

Price levels cluster at round numbers. If an MA happens to sit near $100, "MA support" and "round-number support" are confounded. Add a control for `|price − nearest_round| / ATR`.

### 7.7 Regime as a single observation

"MAs worked well in 2000–2002 and 2008" describes **two** events. Not two thousand. Any regime-conditional claim must report cycle count.

### 7.8 Sector and factor concentration

An "MA breakout" cohort in 1999 is 60% tech. Report sector composition of every event cohort; if any sector exceeds 2× its universe weight, run the sector-neutral version as primary.

### 7.9 Self-reference

A stock is above its 200-day *because* it rose. Conditioning on the MA state and then measuring forward return from that elevated price embeds a "this stock already rose" selection. This is not automatically a bias — momentum is real — but it must be named, and it is exactly what C2 controls for.

### 7.10 Short-sale constraints and borrow

Death-cross and below-MA findings imply shorting. Hard-to-borrow names cluster in exactly the beaten-down cohort. Flag any short-side claim as requiring a borrow-feasibility check before it means anything.

---

## 8. Analysis modules

**M0 is Track A. M1–M16 are the Track B candidates that M0 feeds.** The hypothesis/kill-criteria framing below describes how a module looks *once promoted* — during exploration, treat every module as a place to poke around rather than a test to execute. Kill criteria are pre-committed conditions for declaring something dead, and writing them before running is the cheapest defence against motivated reasoning; but they apply at confirmation time, not while you're still looking.

### M0 — Exploration track

Unstructured by design. Run continuously alongside everything else, not as a phase that finishes. Some starting points — the list is meant to be added to:

**M0.1 — Descriptive atlas.** Before testing anything, *look* at the data. Distributions of every feature in §4.3, by universe tier, sector, vol decile, and era. Joint distributions of the interesting pairs. How often is a stock within 0.5 ATR of its 50-day? What does the distance distribution actually look like — fat-tailed, skewed, bimodal? How much do these change between 2003 and 2023? Half the surprises in a project like this are visible in a histogram and invisible in a t-test. Budget real time for this; it is not a warm-up.

**M0.2 — Residual hunting.** Fit the momentum baseline from §7.1. Then ask: **where does it get things wrong?** Sort by residual, and look for MA-state structure in the tails. This inverts the usual search — instead of asking "does feature X predict returns," it asks "what does the thing we already know fail to explain, and is any of it MA-shaped?" It's the single most efficient exploratory frame available here, because it's automatically orthogonal to the dominant confound.

**M0.3 — Behavioural clustering.** Do stocks differ systematically in how they organise around their MAs? Build a per-ticker "MA affinity" signature (touch frequency, time-above fraction, bounce rate, typical extension, distance-distribution kurtosis) and cluster. Then the two questions that matter: **does cluster membership persist** across non-overlapping periods, and **does it predict anything?** If some stocks genuinely "respect" their 21-EMA more than others in a persistent way, that's a real and marketable finding. If affinity is pure noise year to year, that kills a widespread piece of folklore. Either outcome is worth having.

**M0.4 — Interaction mining.** FDR-controlled search over pairwise interactions of the §4.3 feature set. Explicitly a fishing expedition — that's fine, it's Track A. Anything surfacing here needs a mechanism story before it gets near the gate; an unexplained interaction that survives correction is usually a data artefact.

**M0.5 — Anomaly forensics.** Pick the 30 largest winners and 30 largest losers per year. What did their MA state look like beforehand? Not a test — a source of hypotheses about what extreme outcomes have in common. Deeply biased by construction; useful anyway.

**M0.6 — Failure archaeology.** For a few well-known signals (golden cross, 21-EMA bounce), pull the individual cases where the signal failed worst and look at them by hand. Chart-by-chart. Practitioners do this instinctively and quants skip it, and it's often where the missing conditioning variable reveals itself.

**M0.7 — Reproduce the folklore literally.** Implement the claims from §2.2 exactly as stated by their authors, on their stated universes, before improving on them. If you can't reproduce a published number, you either have a data problem or the number was never real — and you want to know which *before* you build on top of it.

**Output:** `EXPLORATION_LOG.md` and a ranked candidate shortlist. Track A has no kill criteria, because nothing in it is alive yet.

### M1 — Baseline state conditioning
**Hypothesis:** Forward excess returns differ conditional on price vs a single MA.
**Method:** For each (family, lookback), bucket by `above/below`, plus run-length bucket (`days_above` ∈ 1–5, 6–21, 22–63, 64+). Compute full outcome set vs C0/C1/C2.
**Key sub-question:** does the *age* of the state matter? Folklore says fresh reclaims are strongest. Test it.
**Output:** the reference table for everything else; the C0→C2 shrinkage waterfall.
**Kill:** if C2-adjusted effect < 0.1% at 21d across all lookbacks, the entire "state" family is a momentum re-encoding — report that as a headline finding and reallocate effort to M4/M5.

### M2 — Stack states and Minervini ablation
**Hypothesis:** Multi-MA alignment carries information beyond a single MA.
**Method:**
(a) Categorical `stack_perm` state analysis over {20, 50, 150, 200}.
(b) **Full 8-criterion ablation of the Trend Template.** Run all 2⁸ = 256 subsets (or a Shapley-style attribution) to decompose which criteria carry the forward-return difference.
**Prior to test:** criteria 6–8 (25–30% above 52w low, within 25% of 52w high, RS rank ≥ 70) are pure momentum and will carry most of the load; the MA stack adds modest incremental information; "200-day rising for 1 month" is nearly redundant with "price above 200-day."
**Output:** attribution chart. If the prior holds, this is a strong, quotable, slightly heretical result.
**Kill:** none — the ablation is informative regardless of outcome. This is the highest expected-value module in the doc.

### M3 — Crossovers: state vs transition
**Hypothesis (skeptical):** A golden cross carries little information beyond "the stock is now in a 50>200 state."
**Method:** The clean test — compare forward returns on **day 0 of a golden cross** against **randomly sampled days where 50>200 has been true for a comparable duration**, matched on date and momentum. If the transition has no marginal information, these distributions coincide.
**Also test:**
- Crossover *quality*: cross with rising vs falling long MA; cross with the price above vs below both MAs (this is the user's "current price relative to the cross" question and it is a genuinely good one — a golden cross with price *below* both MAs is a very different object from one with price above);
- Cross angle / spread velocity at crossing;
- 20/50, 50/150, 10/20 EMA, 8/21 EMA in addition to 50/200;
- Drawdown/MAE metrics specifically (per §5.3, this is where the death cross may earn its keep).
**Output:** "does the event add anything to the state?" table.
**Kill:** if marginal information over state-matched controls is < 0.15% at every horizon with CI spanning zero, declare crossovers **redundant with state** and stop. (Prior: ~65% likely.)

### M4 — Distance from MA (%, ATR, z-score)
**Hypothesis:** Forward return is a non-monotonic function of displacement, with sign depending on horizon, trend quality, and normalisation.
**Method:** Decile/vigintile buckets of `dist_pct`, `dist_atr`, `dist_z`, `dist_pctile` for MAs {20, 50, 200}. Full outcome set per bucket. Then:
- **Repeat with vol-neutralisation** (within vol-decile buckets) — this is the test that resolves §2.3(3);
- Condition on trend quality (ER high/low);
- Condition on universe tier (this tests the Nasdaq-100-selection hypothesis);
- Term structure across all 8 horizons.
**Specific targets:** reproduce/falsify the 7.5–8× ATR exhaustion claim; reproduce/falsify the IJECM "0–5% below the 20/50-day is the best bucket" claim.
**Output:** a set of 2-D heatmaps: distance bucket × horizon, faceted by regime and universe. This is likely the visual centrepiece of the report.
**Kill:** if no monotonic or reliably U-shaped relationship survives vol-neutralisation in any facet, report as a strong negative.

**Status (2026-09-08 addendum) — first slice run, see `PREREGISTRATION.md` and `DEAD_ENDS.md`.** A first pre-registered pass ran the `dist_pct`/`dist_atr`/`dist_z` × SMA{20,50,200} × 21-day-horizon grid only — not the full method above. Kill criterion not triggered, but only the 3 SMA20 facets survive block-bootstrap inference, and none survives a realistic cost annotation; final tier capped at Tier 3 (no FDR/holdout/second universe tier exist yet). Explicitly deferred from that slice, not abandoned: vol-neutralisation as its own pass, ER conditioning, universe-tier conditioning, the two specific literature-claim targets above, and **the full 8-horizon term structure**. Of these, **the horizon term structure is the specific, motivated follow-up** if this module is picked up again — SMA20's surviving-but-cost-failing result at 21 days leaves open whether a different horizon (e.g. a horizon short enough that the ~50-round-trip/year turnover cost hurdle doesn't apply, or long enough that the edge compounds past it) tells a different story. This is distinct from broadly widening the grid (ER/universe tiers/vol-neutralisation), which was considered and explicitly deferred as a broad next step in favour of picking a different module (see `docs/backlog.md`).

### M5 — Touch / test / bounce behaviour
**Hypothesis:** MAs act as dynamic support/resistance beyond generic trend.
**Method — and this is where most retail analysis goes wrong:** you cannot select on "it bounced." Bounces are only identifiable ex post; selecting on them guarantees a beautiful, meaningless result.

Define the event **ex ante**: `first touch of MA within N days after being ≥1 ATR away`. Then measure the *full distribution* of what happens next — bounce, slice-through, and chop are all outcomes of the same event, and the interesting number is P(hold) vs the base rate of P(any level holding).

**Essential control:** compare against touching a **synthetic level** — e.g. a randomly offset line with the same slope, or the placebo MAs from §7.5. The question isn't "does price often bounce near the 50-day" (it will, because price is near the 50-day a lot); it's "does price bounce there *more than at a comparable arbitrary level*."
**Sub-questions:** does touch count matter (1st vs 3rd vs 5th test)? Does volume on the touch matter? Does touch-with-a-wick vs close-below differ?
**Output:** P(hold | touch, context) tables with base rates.
**Kill:** if P(hold) at real MAs is within 2pp of synthetic levels, **support/resistance from MAs is folklore** — a major, satisfying negative result.

### M6 — Slope and curvature

This module needs more care than it first appears to, because of two exact algebraic identities that most practitioners (and a fair amount of published work) don't seem to notice. **Establish these before running anything**, because they determine which slope questions are even well-posed.

#### M6.0 — Two identities that constrain the whole module

**Identity 1 — the 1-day slope of an SMA is exactly scaled momentum.**

SMAₙ(t) − SMAₙ(t−1) = (Cₜ − Cₜ₋ₙ) / n

That is exact, not an approximation. **"Is the 200-day SMA rising today?" is literally identical to "is today's close above the close 200 days ago?"** Nothing more. Which means Minervini's criterion 3 — *the 200-day is trending up for at least 1 month* — decodes exactly to: *the close has exceeded its own value from 200 days prior, continuously, for the past 21 days.* No smoothing, no trend-quality content. Just a 200-day momentum sign, sustained.

For a k-day slope window the identity generalises to a difference of block means:

SMAₙ(t) − SMAₙ(t−k) = (k/n) · [ mean(Cₜ₋ₖ₊₁…Cₜ) − mean(Cₜ₋ₙ₋ₖ₊₁…Cₜ₋ₙ) ]

So a k-day SMA slope is **momentum with smoothed endpoints** — the same signal as raw n-day momentum but with the start and end points averaged over k days instead of sampled at a single close. That smoothing is the *only* thing slope can possibly add over raw momentum, and it's a small, precisely-specified thing. Test it directly (M6.1) rather than assuming it.

**Identity 2 — for an EMA, slope and distance-from-MA are the same variable.**

EMAₜ − EMAₜ₋₁ = α · (Cₜ − EMAₜ₋₁)

Also exact. The 1-day slope of an EMA is the price's distance from that EMA, times a constant. **This means M4 (distance) and M6 (slope) are not independent modules when the family is EMA — they are one module.** Any analysis that treats "price is 2 ATR above the 21-EMA" and "the 21-EMA is rising steeply" as two confirming signals is double-counting a single number. Flag this explicitly in the report; it is exactly the kind of thing that makes a multi-indicator screen look more robust than it is.

The practical consequence: **slope-as-an-independent-feature is really only a question for SMAs and other finite-window kernels.** For EMAs, ask instead whether multi-day slope (k > 1) decorrelates from distance enough to matter — it does, partially, but measure the correlation before building anything on it.

#### M6.1 — Does slope add anything over momentum?
**Hypothesis (skeptical):** SMA slope is momentum with cosmetic smoothing, and the smoothing buys close to nothing.
**Method:** Horse race on identical labels between `slope_log_21(SMA200)`, raw 200-day return, 12-1 momentum, and the block-mean difference form. Compare information coefficients, IC decay across horizons, and turnover. Then the decisive test: regress forward returns on momentum **and** slope jointly and inspect the incremental t-stat on slope.
**Kill:** if incremental IC over matched-horizon momentum is < 0.005 across all lookbacks, declare **SMA slope redundant with momentum**, use whichever is cheaper, and stop building slope-specific machinery. (Prior: ~65% likely, but the endpoint-smoothing argument gives it a real shot, and lower turnover alone could justify preferring it.)

#### M6.2 — Slope as conditioner (the highest-value part)
**Hypothesis:** Long-MA slope conditions every other MA state, and is more useful as an interaction term than as a standalone signal.
**Method:** Re-run M1–M5 faceted by `slope_sign` and `slope_pctile` terciles of the 50 and 200. Specifically:
- **Above a rising 200 vs above a falling 200** — folklore says these are different animals; this is the cleanest test of that.
- **Golden cross with a rising vs falling 200-day.** A 50/200 cross where the 200 is still declining is a bounce-off-the-lows event; where the 200 is rising it's a continuation event. Pooling them is probably why the crossover literature reports such muddy averages (§2.2), and separating them may be where the golden cross finally earns its name.
- **MA touch with rising vs falling MA** — support in an uptrend vs resistance in a downtrend, tested as one interaction rather than two folk beliefs.
- **Extension (M4) with slope** — is +5 ATR above a flat 50-day a different object from +5 ATR above a steeply rising one? Almost certainly yes, and this may be part of the §2.3 reconciliation.
**Output:** interaction tables. **Prior: this is the most likely Tier-1 producer in the whole slope module.** Conditioning demands far less of the data than prediction does.

#### M6.3 — Slope magnitude: monotonic or humped?
**Hypothesis:** Forward return is non-monotonic in slope magnitude — some trend is good, too much is exhaustion.
**Method:** Decile buckets of `slope_atr_21` and `slope_pctile_21` for the 20/50/200. Full outcome set, with vol-neutralisation (a steep slope in ATR units and a high-vol name are not the same thing, and the same trap from M4 applies here).
**Watch for:** the top slope decile is heavily contaminated by post-earnings-gap and low-float names. Run the earnings-excluded version as a mandatory companion.

#### M6.4 — Slope persistence and flip hazard
**Framing:** Instead of "does slope predict return," ask **"given the 50-day slope has been positive for N days, what is the probability it flips in the next k?"** This is a survival/hazard problem and it's a better fit for how slope is actually used — as a trend-intact/trend-broken switch.
**Method:** Kaplan–Meier survival curves for slope-positive runs, by lookback, stratified by vol regime and by ER. Compare against the hazard implied by a random walk with drift (the null: slope runs of an n-day MA under GBM have a known-ish distribution — simulate it). **The finding is only interesting where the empirical hazard departs from the simulated null.**
**Why this matters:** it converts a vague folklore claim ("trends persist") into a number you can actually size a stop or a holding period against.

#### M6.5 — The SMA drop-off artefact
**A genuine trap, worth its own analysis.** Because SMAₙ(t) − SMAₙ(t−1) = (Cₜ − Cₜ₋ₙ)/n, an SMA's slope can flip negative **purely because a large up-day rolled out of the back of the window**, with nothing whatsoever happening in current price. A 200-day SMA "rolling over" in March 2021 was substantially an artefact of March 2020 leaving the window.
**Method:** Decompose each slope change into entering-bar and exiting-bar contributions. Bucket slope-flip events by which side dominated. Then measure forward returns separately for **price-driven flips** vs **drop-off-driven flips**.
**Hypothesis:** price-driven flips carry information; drop-off-driven flips carry none, and pooling them dilutes every SMA-slope result in the literature.
**Corollary:** if this holds, EMAs are structurally preferable for slope work (no discrete drop-off), which is a rare case where family choice genuinely matters — and would be a useful counterexample to M8's expected null.

#### M6.6 — Slope agreement across the ribbon
Fraction of {10, 20, 50, 100, 200} with positive slope, as an ordinal 0–5 state. Cheap. Test for monotonicity in forward returns and — more likely to be useful — in forward *drawdown*. Also test whether it collapses to a single MA's slope (expect heavy collinearity; report the correlation matrix rather than pretending it's five signals).

#### M6.7 — What not to bother with
**"The angle of the moving average."** Chartists talk about a 45° MA. This is not a well-defined quantity: the visual angle depends on chart aspect ratio, the price axis range, and whether the axis is linear or log. There is no scale-invariant "angle" — there is only log-slope, which is what `slope_log_k` already measures. Note this in the report and move on; it saves anyone downstream from trying to reproduce a folklore metric that has no coordinate-free definition.

---

### M16 — Rules as linear filters (unifying diagnostic)

**Motivation:** Zakamulin (2017, ch. 5) makes a point worth building on — price-minus-MA, MA-crossover spreads, momentum, and MA slope are *all* weighted averages of past price changes, differing only in their weight kernel. Once you see it, M3/M4/M6 stop being three modules about three indicators and become one question: **which kernel shape over past returns actually predicts?**

**Method:** For every candidate rule, derive and store its equivalent weight vector over past daily returns. Then:
- Cluster the rules by kernel similarity. Rules in the same cluster are the same signal — expect the "golden cross," "price above 200-day," and "200-day slope positive" to land uncomfortably close together.
- Plot the empirical IC as a function of kernel shape (centroid = effective lookback; dispersion = smoothing).
- Ask whether *any* interesting structure exists in kernel space, or whether IC is a smooth blob peaking around the well-known momentum horizons.

**Why it's worth doing:** it is the cleanest possible answer to "how many independent signals do we actually have?" — and my strong prior is *far fewer than the number of indicators*. If the kernel-space IC surface is a smooth blob, then the entire MA indicator zoo is one signal with a hundred names, and the report can say so with a single figure.

---

### M17 — Nonlinearity probe: does path composition matter?

**The gap this fills.** M16 establishes that MA rules are linear filters of past returns. That framing has a blind spot: **any information carried by the *asymmetry* or *composition* of the return path, rather than its net displacement, is invisible to every feature in §4.3.** Two stocks with identical 21-day returns — one that drifted up steadily, one that fell 15% and then rallied 18% — have identical values for every MA-derived feature at the relevant lookback, and are obviously different objects. M17 asks whether that difference predicts anything.

**M17.1 — MACD as a redundancy test (near-zero cost).**
MACD/PPO is an MA spread; it introduces no new mathematics. Run it anyway, as a check on M16: does `ppo` cluster with the MA spread features in kernel space, and does `ppo_above_signal` add anything over the slope features from M6? Two specific sub-questions worth their own answer:
- **Zero-line vs signal-line.** These are commonly treated as two confirming conditions. The first is a level condition on the spread, the second is an acceleration condition. Are they empirically distinguishable, or does the second collapse into M6's slope work?
- **Histogram divergence.** "Price makes a new high, MACD histogram doesn't" is heavily-traded folklore and is one of the few MACD claims that isn't obviously restating an MA state. Define divergence ex ante (§7 rules apply — no selecting on outcome) and test it.
**Kill:** if PPO features fall inside the MA-spread cluster and add < 0.005 incremental IC, fold MACD into M3/M6 permanently and note in the report that MACD is an MA crossover with better branding. (Prior: ~75% likely.)

**M17.2 — RSI as the designated nonlinearity probe.**
RSI separates `max(r,0)` from `max(−r,0)` and takes a ratio of their smoothed values. That nonlinearity is the point — it makes RSI a bounded, path-asymmetry-sensitive summary of the same window an MA would average linearly. It is the sibling of the Kaufman efficiency ratio already in §4.3: **ER measures path efficiency, RSI measures path asymmetry, and both are nonlinear functions of a return window that no MA feature can represent.**
**Method:** the only question that matters is *incremental*. Regress forward returns on the full MA feature set, then add RSI (level, slope, and the ER interaction) and inspect the marginal contribution. Also run the reverse: how much of RSI's standalone predictive content is already captured by `dist_z` at a matched lookback? (Expect: a lot. RSI at 14 periods and distance-from-20-day-MA are strongly correlated in practice, which is why RSI often behaves like an extension measure.)
**Sub-questions worth exploring:** does RSI meaningfully separate cases where MA features are ambiguous — i.e. is it most useful precisely where price sits *near* its MA and the linear features have no signal? That would be the strongest possible case for it, and it's a targeted test rather than a general one.
**Kill:** if RSI adds < 0.005 incremental IC over the MA set at every horizon, conclude that **path composition carries no information beyond net displacement at these horizons** — a strong, general, and genuinely interesting negative result that closes off a large class of oscillator work in one shot.

**M17.3 — Ordinal operations.**
Stochastics (`%K` = position within the trailing high-low range) is neither a linear filter nor a gain/loss decomposition — it's a rank statistic. Third distinct operation, cheapest possible test, include it in the M17.2 incremental regression as a third probe. Same kill criterion.

**Framing for the report:** M17 is not "we also tested some oscillators." It is a structured test of **three distinct mathematical operations on a return window** — linear averaging (MAs), gain/loss asymmetry (RSI), and rank-within-range (stochastics) — asking which of them carries information the others don't. That is a much stronger claim than any individual indicator result, and it generalises beyond the specific indicators tested.

### M7 — Ribbon compression / expansion
**Hypothesis:** Low MA dispersion (compression) precedes volatility expansion; direction of expansion is *not* predictable from compression alone.
**Method:** `ribbon_width_pctile` low buckets → forward realised vol, forward |return|, forward signed return. Interact with prior trend direction (this is essentially a quantified VCP / Bollinger-squeeze).
**Prior:** vol prediction works (vol clusters and is genuinely forecastable); direction prediction does not, *except* conditional on prior trend, where it's weakly momentum-ish. Worth stating clearly because the folklore conflates the two.

### M8 — MA family horse race at matched lag
**Hypothesis (skeptical):** At matched centre of mass, kernel shape is nearly irrelevant.
**Method:** Lag-matched comparison of SMA/EMA/WMA/HMA/DEMA/KAMA/VWMA on identical event definitions. Apply **White's Reality Check** to the best-performer claim.
**Kill:** if no family beats EMA by > 0.1% at matched lag after Reality Check, declare **MA family selection a non-question** and use EMA everywhere for computational convenience. (Prior: ~80% likely. This is a valuable dead end to close — it frees you from an entire genre of parameter fiddling.)

### M9 — Regime-conditional lookback (the user's "5 EMA in chop" question)
**Hypothesis:** The best short-term MA lookback varies with regime.
**Method — three-stage, and the staging matters:**
1. **Descriptive:** bucket by ER/ADX/vol regime; for each, compute performance across the lookback grid. Produce the regime × lookback surface. Apply the plateau rule ruthlessly.
2. **Predictive:** is regime at time *t* predictive of the best lookback over *t+1…t+k*? Regimes are persistent, so this should partly work — but persistence is not the same as exploitability.
3. **Adaptive:** does a rule that switches lookback by regime beat the best *fixed* lookback out of sample, net of switching costs? Also compare against KAMA, which does this continuously and for free.

**This is the module most likely to produce a false positive**, because a regime × lookback grid is a large search space over data with tiny effective N (§6.4). Pre-register the regime definition. Do not tune the regime thresholds. If you find yourself adjusting the ER cutoff to make results look better, you have left the study and entered the overfitting.
**Kill:** if adaptive doesn't beat fixed out-of-sample net of costs, report the honest answer: *regime-adaptive lookback selection is a plausible idea that does not survive testing* — which is a genuinely useful thing to know, and is my prior at ~70%.

### M10 — Timeframe and sampling
**Hypothesis:** Weekly MAs offer a better lag/whipsaw tradeoff than lookback-equivalent daily MAs.
**Method:** Compare (a) daily 50/150/200 evaluated daily, (b) weekly 10/30/40 evaluated weekly (Friday close only), (c) daily 50/150/200 evaluated **only on Fridays** — this last one is the key control, since it isolates *sampling frequency* from *lookback*. Also test multi-timeframe confluence (daily and weekly agreeing).
**Output:** decomposition of the weekly advantage (if any) into lag effect vs sampling effect.

### M11 — Cross-sectional formulation
**Hypothesis:** Relative MA state (ranked within universe/sector) is a stronger signal than absolute.
**Method:** Convert MA features to cross-sectional ranks; build long-short decile portfolios; measure IC (Spearman) and IC decay across horizons; compare against absolute-threshold formulations.
**Note:** this dramatically increases effective N (§6.5) and is the natural bridge to a portfolio-level strategy. If time is short, prioritise this module.

### M12 — Volume and liquidity interaction
**Hypothesis:** MA reclaims on above-average volume are more durable.
**Method:** Interact key events with relative volume deciles, dollar-volume percentile, and VWMA-vs-SMA divergence (which measures whether volume is concentrated on up or down days).

### M13 — Context conditioning
Earnings proximity, index membership changes, sector momentum, market breadth (`pct_above_200d`), VIX percentile. Mostly interaction terms on top of M1–M6 rather than standalone analysis.

### M14 — Integration with existing detectors
Use your existing indicators/detectors as conditioning variables. Concretely: does an MA event fired *inside* one of your existing detected patterns behave differently? This is the cheapest path to a compounding result and exploits work you've already done.

### M15 — Synthesis
Take the surviving Tier-1/Tier-2 claims and answer: do they combine additively, or are they the same signal wearing different hats? Correlation matrix of the surviving signals. **Expect high collinearity** — that's the honest finding, and it's why the synthesis module belongs in the plan rather than being assumed.

---

## 9. Deliverables

### 9.1 Report structure

1. Executive summary — the 10 claims that survived, one line each
2. Methodology and controls (condensed §5–7)
3. **The shrinkage table** — every headline effect at C0, C1, C2. This is the paper's contribution.
4. Module results M1–M15
5. **Dead-ends register** (§9.3)
6. Cost sensitivity appendix
7. Reproducibility appendix: seeds, data versions, full pre-registered grid, N_tests

### 9.2 Confidence tiers

| Tier | Criteria |
|---|---|
| **Tier 1 — Robust** | Survives C2 matching, BH-FDR at q=0.05, holds across all universe tiers, plateau-stable in parameters, present in holdout, survives costs |
| **Tier 2 — Probable** | Survives C2 and FDR, but fails one of: universe generality, holdout, or cost |
| **Tier 3 — Suggestive** | Directionally consistent, plausible mechanism, but effective N too small or effect within noise. Explicitly not actionable |
| **Tier 4 — Rejected** | Tested, no effect beyond control. Goes in the dead-ends register with the evidence |

**Expect the distribution to be roughly 3 / 6 / 10 / 25.** If you end up with twenty Tier-1 claims, you have a bug in your controls, not a discovery.

### 9.3 Dead-ends register format

For each: hypothesis, why it was plausible, exactly what was run, the number that killed it, effective N, and **the conditions under which it would be worth revisiting**. This section is as valuable as the positive results and takes discipline to write well. It is also the part of the report you will personally re-read most often.

---

## 10. Implementation plan

### 10.1 Repo layout

**Implementation note:** this study lives inside the existing `stocks_analysis` repo,
not a standalone project, and follows that repo's own per-module convention
(`src/signals/<name>/`, `tests/test_<name>_*.py` — see `src/signals/gaps/`,
`src/signals/relative_strength/`) rather than the tree below literally. The tree
still stands as the logical map of pipeline stages (data → features → events →
labels → stats → modules); **see `CLAUDE.md`'s Layout section for the real paths**
(`src/signals/moving_averages/...`, with `DESIGN.md`/`PREREGISTRATION.md`/
`EXPLORATION_LOG.md`/`DEAD_ENDS.md` under `docs/features/moving-averages/`).
Existing infrastructure is reused rather than rebuilt where it already covers a
stage below — notably `market_common.data` (bar loading/validation),
`market_common.indicators` (ATR/RSI/MACD/OBV), `src/signals/relative_strength/`
(the `rs_rank` momentum control from §7.1), and `db.read_index_membership`
(point-in-time universe, §3.1).

```
ma_study/          # logical map only -- see note above for real paths
  data/
    loaders.py           # vendor adapters, PIT universe, corporate actions
    validate.py          # §3.4 hygiene tests
  features/
    ma.py                # families, lag-matching helpers
    distance.py          # pct/atr/z/pctile normalisations
    slope.py
    ribbon.py
    regime.py            # ER, ADX, vol, breadth
    build_panel.py       # → parquet
  events/
    definitions.py       # every event type, parameterised
    build_events.py      # → event table
  labels/
    forward_returns.py
    path_metrics.py      # MFE/MAE
    barriers.py
  stats/
    controls.py          # C0/C1/C2 matching
    inference.py         # NW, block bootstrap, date clustering
    multiple_testing.py  # BH, Reality Check, SPA, DSR
    plateau.py           # neighbourhood stability
  modules/
    m01_state.py ... m15_synthesis.py
  reports/
    templates/
    figures/
  tests/
    test_indicators.py   # golden fixtures
    test_lookahead.py    # §7.2 shift test
  PREREGISTRATION.md     # the committed hypothesis grid
  DEAD_ENDS.md
```

### 10.2 Phasing

| Phase | Content | Rough effort | Gate to proceed |
|---|---|---|---|
| **P0** | Data acquisition, hygiene, delisting handling | 15–20% | All §3.4 tests pass; delisting counts sane |
| **P1** | Feature layer + panel build + caching | 15% | Golden-fixture indicator tests pass; look-ahead shift test fails correctly |
| **P2** | Event/label/control/inference infrastructure | 15% | C2 matching validated on a synthetic dataset with a known planted effect |
| **P3** | **Pre-registration written and committed** | 2% | N_tests counted and frozen |
| **P4** | Core modules M1–M6 | 25% | — |
| **P5** | Extended modules M7–M14 | 15% | — |
| **P6** | Synthesis, holdout opened **once**, report | 10% | — |

**P2's gate deserves emphasis:** build a synthetic dataset with a *known* planted effect of known size, and verify your pipeline recovers it at the right magnitude. Then build one with *no* effect and verify the pipeline reports nothing. Most analysis pipelines have never been validated this way, and it is the reason so many of them find things that aren't there. This takes a day and is worth a month.

### 10.3 Compute notes

- Vectorise MA computation across the full panel (numpy/pandas `ewm`, `rolling`); do not loop per ticker.
- Cache aggressively at the panel and event-table level; make every module read from cache.
- Bootstrap and permutation tests are the expensive step — parallelise those, not the feature build.
- Use float32 for features; the precision is irrelevant and it halves memory.

---

## 11. Priors: where I expect this to go

Stated up front so the study can embarrass me. Anything I get wrong here is a more interesting result than anything I get right.

### 11.1 Likely productive

| Direction | Why |
|---|---|
| **Long-MA slope as a *conditioner*** | "Above a rising 200-day" vs "above a falling 200-day" should separate meaningfully. Conditioning is a much weaker demand on the data than prediction, so this is where slope most likely pays (M6.2) |
| **Separating golden crosses by 200-day slope** | Likely explains why the published crossover averages are so muddy — two different events pooled into one statistic |
| **Slope-flip hazard curves** | Reframes trend persistence as a survival problem with an actual number attached; useful for holding-period and stop design even if the mean-return edge is nil (M6.4) |
| **The SMA drop-off decomposition** | Testable, mechanical, and if it holds it invalidates a chunk of published SMA-slope work — and gives EMAs a principled edge for slope purposes (M6.5) |
| **Path metrics over mean returns** | Trend rules probably shape MAE/drawdown far more than mean return. The whole golden/death-cross literature points here |
| **Cross-sectional distance ranking** | Higher effective N, natural portfolio formulation, most likely to yield a Tier-1 claim |
| **Ribbon compression → vol expansion** | Volatility is genuinely forecastable; this should work (direction won't) |
| **Minervini ablation** | Will produce a clear, quotable attribution regardless of which way it falls |
| **The 200-day placebo test** | Cheap, decisive, interesting either way |
| **Regime *conditioning* (not adaptation)** | Reporting that a signal works in trending regimes and fails in chop is achievable; *switching* on that basis probably isn't |

### 11.2 Likely dead ends (test cheaply, then close)

| Direction | Why I expect it to fail | Confidence |
|---|---|---|
| **Optimal MA length** | Zakamulin's work is unambiguous: no stable optimum, and the surface is a noise field. Expect no plateau | High |
| **MA family selection at matched lag** | Kernel shape is second-order to lag. HMA/DEMA/ZLEMA marketing is about lag, and once you match lag there's nothing left | High |
| **Crossovers as standalone entries after costs** | The cross is redundant with the state, and short-lookback crosses generate a cost hurdle that eats the gross edge | High |
| **Death cross as a short signal** | Signal fires after the majority of the decline; ~54% of the time the low is already in. May work as a *risk reducer*, not a return generator | High |
| **"5 EMA in chop beats 8 EMA"** | Likely a volatility-scaling effect in disguise, and the regime × lookback search space is too large for the effective N. Will not survive out-of-sample | Medium-high |
| **MAs as genuine support/resistance** | Once you control for "price is near the MA a lot" and compare against synthetic levels, the excess hold-rate probably vanishes | Medium |
| **The magic of 200 specifically** | Neighbours will perform identically | Medium-high |
| **Ticker-specific optimal MA pairs** | Textbook overfitting. Include one demonstration of how badly it fails as a teaching exhibit in the report | Very high |
| **Complex ribbon permutations** | 120 states, most sparsely populated, high collinearity with a simple stack score. Will collapse to a scalar | Medium |
| **MA slope as a standalone predictive signal** | By the M6.0 identity it *is* momentum, rescaled. Endpoint smoothing is the only possible increment and it's small | Medium-high |
| **Treating EMA slope and EMA distance as two signals** | They are algebraically the same variable. Any screen using both is double-counting | Certain — this is arithmetic, not an empirical claim |
| **"45-degree angle" MA slope** | Not a coordinate-free quantity; depends on chart aspect ratio and axis scaling. Only log-slope is well defined | Certain |
| **Slope agreement across the full ribbon as a rich state** | Will collapse to roughly one number, heavily collinear with the 50-day slope | Medium |

### 11.3 The result I'd most like to be wrong about

That **MA information is entirely subsumed by momentum + volatility factors** — i.e. β₅ in §7.1 is indistinguishable from zero across the board. That's my ~40% case. If true, it's still the most useful thing this study could produce, because it would redirect your effort away from an entire class of indicator work and toward the things that aren't already priced into a momentum factor.

---

## 12. Open questions to settle before P0

1. **Data vendor.** Does your current source have delisted securities and point-in-time index membership? If not, that's the first purchase, and it's not optional. (Norgate, CRSP, and Sharadar are the usual answers at different price points.)
2. **Earnings dates.** Do you have point-in-time earnings calendars? Without them, §7.4 is unaddressable.
3. **Existing indicator reuse.** Which of ATR, ADX, RS-rank already exist in your codebase and are trustworthy? Reuse beats reimplementation, but only after the golden-fixture tests pass.
4. **Scope of v1.** Fifteen modules is a lot. If effort is constrained, my recommended minimal core is **M1, M2, M4, M5, M6.2, M11** plus the §7.5 placebo — that set answers the most questions per unit of work and produces at least one publishable-quality negative result.
5. **Holdout discipline.** Are you willing to genuinely not look at the holdout period until the end? If not, shrink the development window and carve a different holdout — a holdout you peek at is just a slower training set. **Resolved 2026-09-07** — see §12's development-window-coverage item (below) and §3.3: the window was shrunk precisely for this reason, and the holdout (2022-01-01 →) stays locked under the same discipline as originally specified, just at a different boundary date.
6. **Development window coverage. Resolved 2026-09-07 — see §3.3.** Found in the Phase 0 hygiene audit (2026-09-07), rerunnable via `src/signals/moving_averages/data.py`'s `delisted_coverage_by_year` and `tests/test_moving_averages_hygiene.py::test_smoke_delisted_tickers_have_price_history`:
   - **Delisted-ticker price history exists only for 2024–2026** (via Polygon, consistent with its ~2-year free-tier entitlement — see `docs/limitations.md`). Zero delisted-ticker coverage for anything earlier. This is **not** fixed by the window change below — it's handled separately by §7.3's Tier-3 cap, which stays in effect regardless of where the window boundaries sit.
   - **Active-ticker history commonly starts in 2010 or later.** Only 11 of 5,304 active tickers in the DB had price history spanning the original 2000–2016 window; 2,202 tickers' histories start in exactly 2010, with further clusters starting 2018–2026.

   **Decision:** development window moved to 2010-01-01 → 2021-12-31, holdout to 2022-01-01 → present (§3.3) — what the loaded active-ticker data actually supports.

---

## Appendix A — Formula reference

**Centre of mass (lag proxy)**
- SMA(n): (n−1)/2
- EMA(α), α = 2/(n+1): (1−α)/α = (n−1)/2
- WMA(n): (n−1)/3
- HMA(n): ≈ (√n − 1)/2 effective (approximate; measure empirically via impulse response rather than trusting the closed form)

**MA slope identities (exact — see M6.0)**
- SMAₙ(t) − SMAₙ(t−1) = (Cₜ − Cₜ₋ₙ) / n
- SMAₙ(t) − SMAₙ(t−k) = (k/n) · [mean(Cₜ₋ₖ₊₁…Cₜ) − mean(Cₜ₋ₙ₋ₖ₊₁…Cₜ₋ₙ)]
- EMA_α(t) − EMA_α(t−1) = α · (Cₜ − EMA_α(t−1))  ← slope ≡ distance, for EMAs
- SMA second difference = (1/n)[(Cₜ − Cₜ₋₁) − (Cₜ₋ₙ − Cₜ₋ₙ₋₁)]  ← half of "curvature" is the drop-off bar

**Scale-invariant slope**
slope_log_k = ln(MAₜ) − ln(MAₜ₋ₖ)  (the only version invariant to price level and chart scaling)

**Kaufman Efficiency Ratio**
ER(n) = |Cₜ − Cₜ₋ₙ| / Σᵢ₌₁ⁿ |Cₜ₋ᵢ₊₁ − Cₜ₋ᵢ| ∈ [0,1]

**KAMA** (baseline params 10, 2, 30)
SC = [ER × (2/(fast+1) − 2/(slow+1)) + 2/(slow+1)]²
KAMAₜ = KAMAₜ₋₁ + SC × (Cₜ − KAMAₜ₋₁)

**ATR-normalised distance**
dist_atr = (C − MA) / ATR(14)

**Vol-normalised forward return**
r̃ = r_H / (atr_pct × √H)

## Appendix B — Pre-registered grid template

```yaml
families:   [sma, ema, wma, hma, kama, vwma]
lookbacks:  [3,5,8,9,10,13,20,21,30,50,65,100,150,200,250]
placebo_lookbacks: [47,53,187,193,207,213,19,23]
events:     [state, state_agefirst, cross_price_ma, cross_ma_ma,
             touch, reclaim, lose, dist_bucket_pct, dist_bucket_atr,
             dist_bucket_z, ribbon_compress, ribbon_expand, slope_flip]
horizons:   [1,3,5,10,21,63,126,252]
universes:  [U1, U2, U3]
controls:   [C0, C1, C2]
# N_tests = <computed and frozen at P3>
```

## Appendix C — References

- Brock, Lakonishok & LeBaron (1992), *Simple Technical Trading Rules and the Stochastic Properties of Stock Returns*, Journal of Finance 47(5)
- Sullivan, Timmermann & White (1999), *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap*
- White (2000), *A Reality Check for Data Snooping*, Econometrica 68(5)
- Hansen (2005), *A Test for Superior Predictive Ability*
- Zakamulin (2014), *The Real-Life Performance of Market Timing with Moving Average and Time-Series Momentum Rules*, Journal of Asset Management
- Zakamulin (2015), *A Comprehensive Look at the Real-Life Performance of Moving Average Trading Strategies*
- Zakamulin (2017), *Market Timing with Moving Averages: The Anatomy and Performance of Trading Rules*
- Kaufman (1995), *Smarter Trading*
- López de Prado (2018), *Advances in Financial Machine Learning* — triple-barrier labelling, deflated Sharpe
- Minervini, *Trade Like a Stock Market Wizard* / *Think & Trade Like a Champion* — Trend Template
- Weinstein (1988), *Secrets for Profiting in Bull and Bear Markets* — stage analysis, 30-week MA
- CXO Advisory, *U.S. Stock Market Death Crosses and Golden Crosses* (2017)
- *Price Distance to Moving Averages and Subsequent Returns*, IJECM (2017)

## Appendix D — Adjacent directions (in scope, outside the original question set)

Not prioritised, not exhaustive, meant to grow. These are the "same spirit" ideas that fall outside §1.2 but belong in Track A.

### D.1 — MAs as exits, not entries
The doc as written is entry-biased, but most practitioners use MAs primarily to *stay in* or *get out* — trailing the 21-EMA, exiting on a 50-day close-below. **Exit rules are a different statistical object from entry rules** and may well be where the real edge lives, since they only need to be right about the conditional distribution given you're already in a trend. Test: fixed-horizon exit vs MA-trailing exit vs ATR-trailing exit, from a common set of entries, compared on the full return *distribution* rather than the mean.

### D.2 — MAs on the relative-strength line, not price
Compute MAs on the ratio `stock / benchmark` (or stock / sector ETF) instead of raw price. IBD-style practitioners watch the RS line explicitly. This is a genuinely different signal from price MAs and is automatically market-neutral, which sidesteps a large chunk of §5.2's confounds. Plausibly the highest-value single item on this list.

### D.3 — Trend consistency, not trend state
Fraction of the last N days spent above the 50-day, rather than the binary above/below. A stock that has held its 50-day for 180 of 200 days is telling you something different from one that crossed yesterday. Cheap to compute, folklore-adjacent ("orderly uptrend"), and not obviously collinear with momentum — a stock can have identical 12-month returns with wildly different path consistency.

### D.4 — Time-since-touch, not just distance
The doc measures extension in magnitude. Duration is a separate axis: *how long since price last touched the 21-EMA?* Sixty days without a touch is a different condition from 5 days, even at identical extension. Also enables "first pullback after breakout" — a specific and heavily traded folklore claim that deserves a direct test.

### D.5 — Asymmetry: support vs resistance
Does the *same* MA behave differently when approached from above versus below? Folklore says a lost MA becomes resistance ("kiss goodbye"). Directly testable and rarely tested. Related: the O'Neil/Minervini "undercut and rally" — price briefly slices the MA, shakes out stops, then reclaims. Define the shakeout event ex ante (close below, reclaim within k days) and measure it.

### D.6 — Anchored VWAP as a competitor
AVWAP from a major low/high/earnings date is arguably a better-motivated dynamic level than an MA, because it carries volume and has a meaningful anchor rather than an arbitrary lookback. Worth running head-to-head on the M5 touch framework. If AVWAP dominates MAs on the same tests, that's a significant finding and a redirect.

### D.7 — Geometric / log-price MAs
Take MAs of log price rather than price. For trending series over long lookbacks the difference is non-trivial, and log-space is the natural home for multiplicative processes. Almost nobody does this. Cheap to test, possibly nothing, occasionally these things are something.

### D.8 — Breadth: MAs applied to the universe, not the name
`% of universe above its 200-day` is a market-state variable built from MAs. Its *level*, its *slope*, and divergences between it and the index are classic breadth analysis. This is the natural bridge from single-name work to a market regime filter, and it feeds directly back into M9 and M13.

### D.9 — Volume MAs and the volume/price MA interaction
Relative volume is already a covariate, but MAs *of volume* (and volume-MA crossovers) are their own folklore. Cheap add-on to the existing feature builder.

### D.10 — MA behaviour through gaps
Gaps through an MA are structurally different from a drift-through — no touch occurs, no opportunity to trade the level. Does a gap-through resolve differently from a grind-through? Ties into the earnings confound (§7.4) but is worth separating as its own phenomenon.

### D.11 — Nested timeframe conditioning
Not just "daily and weekly agree" (M10), but *the sector's* MA state and *the index's* MA state as conditioners on the single name. A stock reclaiming its 50-day while its sector is below its own 200-day is a different setup from the same event in a healthy sector.

### D.12 — Price input choice
MAs of close vs typical price (HLC/3) vs HL2 vs VWAP-of-day. Trivial to test, almost certainly nothing, worth ten minutes to close off permanently.

### D.13 — Does MA relevance decay?
Hypothesis: an MA matters more when it has been *recently and repeatedly tested* — i.e. its relevance is endogenous to how much attention it's getting. Proxy: number of touches in the last 60 days. If MA levels work partly through reflexivity (§7.5), this should show up as touch-count-dependent hold rates, and it would be one of the few pieces of direct evidence for the reflexive mechanism.

## Appendix E — Indicator taxonomy: what's already in scope in disguise

The organising question is not "which indicators should we add?" but **"which popular indicators are a relabelling of something already in §4.3, and which represent a genuinely new operation on the return series?"** Classifying them this way costs an afternoon and prevents both scope creep *and* accidental exclusion of things already present.

### E.1 — Already in scope (MA constructs under another name)

These require **no new modules**. They are alias entries in the feature dictionary, and their value is as redundancy tests for M16.

| Indicator | What it actually is | Where it already lives |
|---|---|---|
| **MACD** | EMA(12) − EMA(26) | MA spread — M3, §4.3 `ppo` |
| **MACD zero-line cross** | EMA(12) crosses EMA(26) | A crossover event — M3 |
| **MACD signal cross** | Spread vs its own EMA(9) | Slope/acceleration of the spread — M6 |
| **PPO** | MACD normalised by the slow EMA | `ppo` — the version to actually use |
| **Bollinger %B** | Position within MA ± k·rolling σ | `dist_z` — M4 already *is* a Bollinger study |
| **Bollinger bandwidth** | Rolling σ relative to MA | Ribbon/vol compression — M7 |
| **Keltner Channels** | MA ± k·ATR | `dist_atr` — M4 is also a Keltner study |
| **MA envelopes** | MA ± k% | `dist_pct` — M4 again |
| **CCI** | (typical price − SMA) / (0.015 × mean deviation) | A differently-normalised `dist_*` — M4 |
| **DPO** | Price minus a displaced SMA | `dist_pct` with a shift — M4 |
| **TRIX** | Rate of change of a triple-smoothed EMA | MA slope with a different kernel — M6 + M8 |
| **Coppock / KST** | Weighted sums of smoothed rate-of-change | Linear filters — M16 kernel space |
| **Golden/death cross** | 50/200 SMA cross | M3 |
| **Minervini trend template** | Stacked-MA state + momentum filters | M2 |

**The point worth making in the report:** roughly a dozen indicators with distinct names, distinct Wikipedia pages, and distinct followings reduce to **three underlying quantities** — distance from an MA, spread between two MAs, and slope of an MA. If M16's kernel clustering confirms this empirically rather than just algebraically, it's one of the more valuable things the study can say.

### E.2 — Genuinely new operation (worth a probe, M17)

| Indicator | The new operation | Why it might add something |
|---|---|---|
| **RSI** | Gain/loss decomposition — nonlinear | Encodes path asymmetry, invisible to linear filters |
| **Stochastics %K** | Rank within trailing range — ordinal | Neither linear nor a gain/loss split; a third operation |
| **ADX / DMI** | Smoothed directional movement | Already partly present as a regime variable (§4.3); check for redundancy with ER |
| **Kaufman ER** | Displacement / path length — nonlinear | **Already in scope**; the existing nonlinear probe, and RSI's natural comparator |
| **OBV / volume-weighted** | Signed volume accumulation | Partly present via VWMA; the signing is the new part |

### E.3 — Out of scope

Chart patterns, candlestick formations, Elliott/Gann/Fibonacci constructions, market internals (TICK, TRIN, put/call). Not judgements about their merit — the §7 confound analysis genuinely doesn't transfer, and each would need its own event-definition and control design. If any becomes interesting, it deserves its own design doc rather than an annex to this one.

### E.4 — The general principle

Before adding any indicator to this study, answer one question: **what operation does it perform on the return series, and is that operation already represented?** If the answer is "weighted average of past prices," it's already here — add it as an alias and a redundancy check, not a module. If it's something else, it earns a probe. This test is cheap, and it is the difference between a study that grows in depth and one that grows only in length.
