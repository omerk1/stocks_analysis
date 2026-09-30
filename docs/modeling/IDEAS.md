# Modeling — ideas inbox

**Status:** raw inbox, not a design. Started 2026-09-24. Anything goes in here; `DESIGN.md`
gets written once the ideas below cluster into a clear shape. Each idea is tagged with
what already exists in the repo, so the design can reuse before it builds.

---

## 1. What the model should output

**The ask:** probabilistic, path-aware statements such as *"in the next 30 days, 70% chance
of +8% before −3%"*, plus the best R/R and horizon for a given setup, plus a single score
that ranks setups.

**Reframing:** this is a **barrier-hit probability surface** (a triple-barrier label,
López de Prado style). For each ticker-date and each cell of a grid:

| axis | example grid |
|---|---|
| horizon `H` (trading days) | 5, 10, 21, 42, 63 |
| upper barrier `U` (ATR multiples, or %) | 1, 2, 3, 5 |
| lower barrier `D` (ATR multiples) | 0.5, 1, 1.5, 2 |

the target is `P(hit +U before −D, within H)` (plus the "neither hit" outcome). The
outputs you asked for all come from this surface:
- **Statement:** read off one cell.
- **Best R/R and horizon:** the cell with the highest expected value after costs,
  `P·U − (1−P)·D − cost`. Maximising EV is not the same as maximising `P` or `U/D`.
- **Score:** that best-cell EV, or an EV aggregated across the surface.

**Two ways to build it:**
- **(a) One classifier per cell, or one multi-output model.** Simple to train. But the
  cells can contradict each other: nothing stops the model from saying a wider stop has a
  *lower* hit rate. That needs monotonicity constraints or post-hoc fixing.
- **(b) Model the path distribution, then derive every cell from it.** Predict the joint
  distribution of (max favourable excursion, max adverse excursion, which came first,
  when), for example with quantile or discretised-hazard heads. Every barrier
  probability then comes from one consistent distribution. More work up front, but this
  one fits "find the best R/R" best.
  `src/signals/moving_averages/labels/path_metrics.py` already computes MFE/MAE.

**Trap to design against:** picking the best cell per ticker is itself a selection step.
The best of 100 noisy cells looks good by construction (winner's curse). Probabilities
must be **calibrated**, and the reported EV must be measured on out-of-sample data
*after* the argmax, not the in-sample value of the chosen cell.

**Barrier units:** use ATR multiples as the primary units, because % barriers mean
different things for a utility and a biotech. They should also share units with the
level-distance features below (§3, "LRP made quantitative").

---

## 2. Feature families (user's list), tagged

| # | Family | Exists in repo? | Notes / risks |
|---|---|---|---|
| F1 | Raw OHLCV time series | `market_common.data` (load/validate) | Must be normalised (log returns, ranges in ATR units, relative volume), otherwise the model learns each ticker's price *level*. Raw series imply a sequence model (see §5). |
| F2 | Main MAs as TS, slopes | `moving_averages/features/` panel (`slope.py`, `ribbon.py`, `state.py`, `crossover.py`) | Slope set: signed `slope_log_k` (so rising vs falling is built in); its cross-sectional percentile (`slope_pctile_21_sma_50` is the study's Tier 2, and it's the *extremes in both directions* that matter); acceleration (change in slope); agreement across MAs (ribbon, M6.6 state 0–5); `dist_from_52w_low` (M18). Null-prior candidates kept cheap: a slope-sign flag and its run length (M1's state-age cells failed the plateau rule; M6.4 found slope runs last as long as a drifting random walk's). `slope_log_k` only (MA invariant 7). |
| F3 | Price distance from MAs (% / ATR) | `features/distance.py` | Already built; in the model. `extension_x_slope` (M6.2 Finding 1, weak prior): both of its inputs are in the model, so a tree can learn the interaction itself. A hand-built interaction column is an optional extra, not needed for v1. |
| F4 | RSI, MACD, ATR, ADR… | `market_common.indicators`, `feature_engineering/`, `moving_averages/features/oscillators.py` (M17) | M17 (final): MACD adds information beyond the MA set at its control (Tier 3) but **fails the whole-grid FDR pass** (p=0.115). RSI/stochastics inconclusive; RSI flips sign when price is near its MA, a hint of an interaction worth letting a tree find. MACD is in the model with a weak prior: both lines *and* the histogram, and the ablation decides. (Its study evidence is thin: incremental IC barely above zero, never tested against `mom_1_0`.) ATR is needed anyway (barrier units). |
| F5 | Relative strength | `signals/relative_strength` (`rs_rating`, plus `rs_ratio`, `rs_mansfield`, and since #141 the raw `rs_weighted_return`) | Also the momentum **baseline** (see §6). Three distinct signals, not one: the ratio line (a level vs the benchmark), the raw weighted-return score (the stock's *own* 3/6/9/12-month return, IBD weights), and the percentile rank of that score among same-date peers. The rank is ordinal and saturates at the top, so a leader's score can halve while its rank stays at 99; the rank alone hides that move, the raw score carries it. Give the model the score (or score change) next to the rank, not the rank alone. `rs_mansfield` had a four-session look-ahead until 2026-09-30 (weekly value forward-filled from its Monday label; fixed in #141) — any RS feature in the harness is built on the fixed version, and `test_mansfield_on_a_day_ignores_closes_after_that_day` is the check to copy. |
| F6 | Divergences, gaps, FVGs, fibs, AVWAP, AVP | `divergences`, `gaps` (FVGs included), `fibonacci`, `avwap` (now with volume-weighted std bands, #109). **AVP now built:** `signals/volume_profile` (#110), with shared anchor discovery in `market_common`. | Event/level objects, not series. They need converting to per-date features (§3). Check that each one is `as_of`-safe when computed across the full panel. |
| F7 | S/R lines (duration, relevance, strength) | `sr_lines` (has scoring and lifecycle) | Same conversion to per-date features. |
| F8 | Chart patterns (duration, relevance, strength) | `patterns` (7 detectors, scoring); a holdout-bounded `pattern_matches` table was populated by M14 | **M14:** nothing once the pattern flag is as-of-safe. The earlier flag used the future breakout. Pooled +0.07% [−0.31%, +0.42%]; VCP-only +0.85% [−0.10%, +1.88%] on 402 events / 335 dates; both span zero. So per-pattern-type features are *untested*, not supported. Keep them as null-prior candidates, each of which must beat an extension-aware baseline, not just a base rate. |
| F9 | Metadata: market cap, shares, sector… | Code exists: `shares_outstanding` table (historical, from yfinance), `market_cap.py` (split-reconciled). **Data doesn't: `shares_outstanding` and `ticker_metadata` both have 0 rows (checked 2026-09-24).** `ticker_sector`: 1,148 rows, current snapshot only. | ⚠ Historical market cap has to be ingested first (see §7). The snapshot tables are look-ahead if used as history. Sector is probably tolerable (it changes slowly) but that needs a note. |
| F10 | Macro: rates, VIX… | FRED `CURATED_SERIES` (18 series), `market_common.macro.as_of_join` (publication-date safe). ⚠ Stored history: **HY OAS starts 2023-09 and SP500 starts 2016-09**, so both are unusable for the 2010–2021 development window. VIX, rates, curve, dollar and claims go back far enough. | Identical for every ticker on a given date, so it can only help with *timing*, never with ranking stocks against each other. Its effective N is the number of distinct regimes (a handful in 2010–2021), and the fed funds rate sat near zero for most of the window, so the model never sees a rate-hike regime while the 2022 holdout *is* one. Prefer a few coarse, trailing-percentile regime gates used as interactions over 18 raw series. |

**What the finished MA study tells the model.** Full detail, numbers and a v1 feature
list: `ma_study_insights.md`. The points that shape this inbox:
- **One Tier-2 feature.** `slope_pctile_21_sma_50` (M6.3): flat-slope stocks trail both
  extreme tails by about 0.25% per 21 days, roughly 3%/yr gross. That's a feature, not a
  strategy. Whole-grid FDR keeps 2 of 107 tests; the other survivor (M6.6 ribbon
  agreement) is a drawdown read, not a return claim.
- **The MA family is close to one signal.** M16: all 23 MA rules form one cluster at
  cosine ≥0.80, about 10 clusters (by effective lookback) at ≥0.95. Pick a few
  representatives per lookback cluster. `slope_log_21_sma_200` is an outlier cluster, and
  M16 excluded thresholded rules (`above_*`, crossover events). SMA200 features are in
  the model like every other lookback. They just aren't treated as special (e.g. no
  hand-coded "the 200-day" level or flag), since no lookback was special in the study
  (§7.5 placebo, and the unresolved SMA200 anomalies).
- **Recurring confounds: momentum/vol matching and short-term reversal.** M6.2's touch
  cell died to the reversal control; `dist_from_52w_high` died to momentum matching.
  Extension killed the pooled pattern cell (M14). Every family's ablation baseline should
  include `mom_12_1`, `mom_1_0`, realised vol and extension.
- **A mean can hide an asymmetric stop-out rate.** M2's `stack_fully_bullish` has a flat
  mean but a hit rate +1.2pp above control and skew −0.35: it wins slightly more often
  and loses bigger. That's why the barrier/path target (§1) beats a mean-return target.
- **Survivorship.** The study universe has no delisted tickers inside 2010–2021, so
  weak-state (bearish-side) results are biased. The model universe should be
  point-in-time with delisted history (§7).

**Keeping weak and null MA features (decided 2026-09-29).** Weak signals may still help
in combination, so the model gets them rather than dropping them. Each feature carries a
*prior* in the feature registry (§9), used only to order ablations and to read results:
- **supported:** Tier 2, or Tier 3 that survives FDR (M6.3 slope percentile, M6.6 ribbon
  agreement).
- **weak:** Tier 3, real at its control but not FDR-surviving. Examples: SMA20
  extension (M4), `dist_from_52w_low` (M18), `stack_fully_bearish` (M2), dollar volume
  (M12), MACD histogram (M17), `ribbon_width` (M7), `extension_x_slope` (M6.2).
- **null:** tested and not distinguishable from zero, but cheap. Examples: crossover
  state age (M3), slope-sign run length (M6.4), VCP and other per-pattern flags (M14),
  `dist_from_52w_high` (M18), state age (M1).
  Enters as a group, and stays only if the group ablation shows an out-of-sample gain.

Near-copies are not kept, since they're the same signal twice: extra distance
normalisations at one lookback, `slope_log_5` on EMAs, exotic MA kernels (M8), weekly
MAs (M10), and RSI/%K next to `dist_z_sma_20` (M17, corr 0.86).
Full list: `ma_study_insights.md` §2.3.

A null prior never becomes evidence by being in the model. Only the harness's ablation
result counts. **Priors order the tests; they never keep a feature out.** Every weak and
null feature gets its out-of-sample chance.

**Near-copies** (the same signal twice, e.g. three distance normalisations at one
lookback, 0.94–0.98 correlated) stay out of the default set, because they split
feature-importance credit and add almost no information. One explicit ablation adds them
all back; if that shows a gain, they go in. `ma_study_insights.md` §2.3 carries the same split.

**"Least resistance path" (LRP):** the term doesn't appear anywhere in the repo's docs or
code yet. It needs a written definition before it can be a feature or a target.

### 2b. Feature *shapes*: why one flat table doesn't fit, and a hierarchical approach

The families above come in five different shapes:

| Shape | Examples | Natural encoding |
|---|---|---|
| Dense series | OHLCV, MAs, slopes, RSI/MACD, ATR | Values at *t* plus a trailing window |
| Sparse events | golden/death cross, gap opens, divergence fires, pattern completes, BOS/CHoCH | Fired-today flag, days since the event, count in the last N days, state still in force and its age |
| Level sets (a varying number of objects) | S/R lines, fib levels, AVWAPs, gap edges, prior highs and lows | Nearest above/below in ATR; strength-weighted count within k·ATR; strongest level's age and touch count |
| Static / slow | sector, market cap bucket, listing age | Categorical or bucketed, updated as of *t* |
| Market-wide | macro, breadth, SPX trend | Same value for every ticker on a date; gates/interactions |

**Hierarchical options, simplest first:**
1. **Summarise each family into fixed per-date columns** (the table above), then fit one
   gradient-boosted model. Everything else builds on this step, so it comes first.
2. **Stacking:** one sub-model per family produces an out-of-fold family score ("trend
   0.7, structure 0.4, volume 0.5"), and a meta-model combines them with the context
   gates. This gives interpretable per-family scores, which matches the scoring ask. It
   needs *nested* out-of-fold predictions, otherwise the meta-model trains on leaked
   scores (see §8).
3. **Learned per-family encoders** (a neural net per shape, e.g. a set encoder for level
   sets or a sequence encoder for dense series), trained end to end. Most flexible, and
   the most data-hungry, so it only makes sense if 1–2 show there's signal to extract.

**Events:** each can be a *feature* (the event encodings above) or define the *training
population* (only rows where the event fired, which is the "score a setup" use in §6).
MA-study M3 found crossover *events* add nothing beyond the *state* (all 16 cells span
zero). So encode crossovers as state plus state age (`features/crossover.py` /
`state.py`), with a null prior, rather than as an event family of their own.

---

## 3. Additions — things not on the list

**Structure and levels**
- **LRP made quantitative (highest priority):** for each ticker-date, compute the distance
  in ATR to the nearest resistance *above* and the nearest support *below*, pooled across
  every level source (S/R lines, fib levels, AVWAPs, gap edges, round numbers, prior
  52-week high/low). Add a strength-weighted count of levels within k·ATR in each
  direction. This is the feature version of the barrier target: "3 ATR of clear air
  above, a strong shelf 1 ATR below" maps directly onto a barrier cell.
- **Market structure (BOS/CHoCH):** `signals/market_structure` already exists and isn't
  on the list.
- **Time-since features:** days since the 52-week high, since the last gap, since the
  last touch of a level. These are often more informative than the level itself. (Days
  since an MA cross is the same as crossover state age, a null prior per M3.)

**Volatility and volume**
- Volatility regime: realised vol, its percentile against the ticker's own history, and
  vol-of-vol.
- Compression: ribbon width percentile (weak prior, M7), plus Bollinger-width percentile,
  ATR percentile and NR7 (null priors). All in the model. Ribbon and Bollinger width are
  highly correlated but not identical, so both go in and the ablation decides. M7:
  compression predicts the *size* of the forward move, not forward realised vol. The VCP detector already
  exists; it's an untested compression candidate (M14 is a null once as-of-safe).
  Compression changes barrier probabilities directly, because a squeeze reaches a far
  barrier more easily.
- Volume structure: relative volume, up-volume vs down-volume, accumulation/distribution
  days, OBV slope.
- Dollar volume as a liquidity measure. It is also the input for **per-ticker cost** in
  the EV calculation.
- Bar shape: close location within the bar's range, wick ratios, gap-and-go vs
  gap-and-fade days.

**Cross-sectional and relative**
- **Per-date cross-sectional ranks** of most features, rather than raw values. The MA
  study's Tier-2 cell is a rank feature, and rank transforms are cheap and match how the
  study built its features. That's one cell, not proof that ranks beat levels: M4's
  decile spreads were also per-date ranks and stayed Tier 3.
- Sector-relative versions: the stock vs its sector's median, and sector momentum.
- Beta to SPX, idiosyncratic vol, and rolling correlation to the market.
- Classic factor controls: 1–5-day reversal, 12-1 momentum, size. These are the
  baselines, not features to discover: they're exactly the study's C2 match plus the
  reversal tercile, and they removed 60–100% of gross MA effects. They sit in B2/B3,
  with extension as B4 (`ma_study_insights.md` §3, `VALIDATION_HARNESS.md` §5).

**Market context**
- Breadth: `signals/breadth` already exists (% above MAs, A/D, golden-cross breadth)
  and isn't on the list. Equal- and cap-weighted S&P 500 breadth are both stored; cap
  weights use SEC share counts and split-only prices (#116, #133). Use 2011 onward.
- SPX's own trend state (reuse the MA features on the index), yield curve, HY credit
  spread. In the model as regime inputs that other features can interact with (null
  prior: M13 found no regime interaction). Report the number of regimes as effective N,
  since regime slices cut it to 786–1,195 dates.

**Calendar and events**
- Day of week, turn of month, options-expiry week.
- ⚠ **Earnings dates: not in the database.** This is the largest single gap for a
  barrier model, because an earnings gap jumps straight through both barriers. Either
  source earnings dates or flag the "earnings inside the horizon" risk explicitly.

---

## 4. Constraints carried over from the MA study

- **Weak signal.** The MA study's single Tier-2 effect is about 0.25% over 21 days. A
  model built on 10+ feature families will find *something* in-sample every time.
  Discipline about the baselines and the holdout matters more here than in the study.
- **Holdout** stays locked (after 2021-12-31). All model selection happens inside
  2010–2021.
- **Walk-forward validation with purging and an embargo.** Barrier labels span up to `H`
  days, so neighbouring samples overlap. A plain k-fold split leaks.
- **One-bar lag, point-in-time universe, delisted tickers kept.** A delisted ticker's
  barrier label comes from its terminal return.
- **Model selection is multiple testing.** Log every model, feature set and
  hyperparameter trial, the same way `EXPERIMENTS.csv` does for the study.
- **Effective N:** report distinct dates alongside row counts.

---

## 5. How to build it in stages

Each feature family has to earn its place through measured improvement over the stage
before it (ablation), not by being on the list.

0. **Validation harness (§8), then labels and baselines.** Barrier surface labels.
   Baselines B0–B5 (`ma_study_insights.md` §3): base rate, date-demeaned, then
   momentum (`mom_12_1` / `rs_rank`), vol, sector, reversal, extension, and the Tier-2
   slope percentile. `rs_rank` is the momentum control, so it lives here, not in stage 1.
1. **Gradient-boosted trees on cheap panel features:** F2–F4, the volatility and volume
   additions, and cross-sectional ranks. Measure calibration and EV after costs.
2. **Add the level and structure features:** F6–F8, and LRP as nearest-level distance.
   This is the expensive stage, so it's worth measuring what it adds first.
3. **Add context:** F9 and F10, breadth, calendar.
4. **Sequence model on raw F1** (a temporal CNN or transformer over normalised OHLCV),
   *compared against* stage 1–3's trees. It isn't a replacement for them.

---

## 6. Open questions

- [x] **How the model will be used → a notification service** (decided 2026-09-25,
      see §11).
- [x] **Universe → S&P 500, Nasdaq-100 and a Russell-style broad set, each with a
      liquidity floor** (decided 2026-09-29). What the data supports today:
      - S&P 500: point-in-time membership since 1996 (`index_membership`).
      - Nasdaq-100: point-in-time membership only from 2015-01-01, so it covers
        half the development window.
      - Russell: **no membership data**, and point-in-time Russell history isn't freely
        available. Proposal: rebuild it the way Russell does, as the top 1,000 / 3,000
        US common stocks by point-in-time market cap, reconstituted each June, from SEC
        share counts × price. Until delisted prices exist (§7), that rebuilt universe is
        survivors-only too.
      - Liquidity floor: a minimum trailing dollar volume, e.g. $20M ADV for the large
        caps. The level is still open, and may need to differ per universe.
- [x] **Direction → long-only alerts for v1, short side later** (decided 2026-09-29).
      The barrier surface is symmetric, so the short side is computed from the start as
      a diagnostic. Short-side *insights* are a stated later goal. They need borrow
      costs and, more than the long side, survivorship-free data (§7).
- [x] **Horizons → 10, 21, 42, 63 trading days; 5 as a diagnostic only** (decided
      2026-09-29, open to revision). At short horizons, one daily bar can touch both
      barriers, and daily data can't say which came first. The label needs a stated
      tie-break (e.g. count it as a stop-out).
- [x] **LRP definition → proposed formulation in `LRP.md`** (2026-09-29): unified level
      object, per-source and aggregate features, barrier-conditional features, test plan.
      An industry term with no single definition; worth exploring
      rather than fixing up front. Working direction (2026-09-29): both a *direction*
      ("which side is easier") and a *distance* ("how much clear air"), from:
      - the nearest-levels pool: S/R lines, fibs, AVWAPs, gap edges;
      - the volume profile: low-volume nodes are easy to travel through;
      - market structure;
      - **MAs**: requested as core to how traders read the chart. Evidence caveat: M5
        and the §7.5 placebo found MAs don't act as support or resistance levels (real
        MAs did no better than unwatched synthetic neighbours). So MA distance enters
        the level pool as a **null-prior** source (§2), tested as a group like the other
        nulls, not as an assumed level. MAs still enter the model through the
        trend/extension features, where the evidence is.
      Open: how level strength is weighted, and whether one strong level outweighs
      several weak ones.
- [ ] **Earnings dates: missing for now**, logged in `docs/backlog.md`. Source identified:
      SEC `submissions.zip` (8-K item 2.02 filings), deferred until it's downloaded.
- [x] **AVP** → built (`signals/volume_profile`, #110).

---

## 7. Data gaps found (checked 2026-09-24)

- **Historical shares outstanding / market cap:** the yfinance backfill ran on
  2026-09-25 (5,211 tickers, 2.27M rows, active tickers only by design). Coverage
  against the point-in-time S&P 500 universe (1,209 tickers), counting history up to
  2021-12-31 only:

  | | S&P members | with share history | history starts by 2014 | by 2017 |
  |---|---|---|---|---|
  | Active today | 691 | 653 | 5 | 584 |
  | Delisted | 518 | **0** | 0 | 0 |

  In practice that means **2016+ only, and survivors only.** Market-cap features and
  cap-weighted breadth built on it would be survivorship-biased for the whole window
  and missing for 2010–2015.
- **Alternative sources, probed 2026-09-25:**
  - **Polygon ticker details with a `date` parameter:** works for a delisted ticker
    (HNZ 2012: 320M shares, CIK returned). But AAPL 2012 came back with *split-adjusted*
    weighted shares (16.4B) and a nonsense market cap. A renamed ticker (DISCA) returned
    NOT_FOUND. Also slow: 5 requests/min.
  - **SEC XBRL (`dei:EntityCommonStockSharesOutstanding`), best candidate:** free,
    ~10 requests/s, bulk `companyfacts.zip` also available. HNZ returned 19 quarterly
    points from 2009 **with the `filed` date**, which makes it genuinely point-in-time
    (the as-of date is the filing date, the same logic as `macro.as_of_join`). Covers
    delisted companies. XBRL became mandatory for all filers by 2011, so it covers the
    development window.
    Needs: a ticker→CIK map for delisted tickers (Polygon's reference tickers endpoint
    returns CIK in bulk pages); handling multi-class share structures (e.g. GOOG/GOOGL);
    split reconciliation (`market_cap.py`'s job already). SEC requires a contact in the
    User-Agent.
- **Update 2026-09-28, SEC ingest landed (#114/#115, `source=sec_edgar`, from the
  hand-downloaded `companyfacts.zip`):** 4,290 tickers. Point-in-time S&P members that
  are still listed: 602/691 covered, **460 from mid-2011 or earlier**, so the depth
  problem is solved for them. Delisted: still 0, because `company_tickers.json` maps
  only today's symbols.
  - **Mapping delisted tickers to SEC IDs is solvable.** Polygon `list_tickers(ticker=…,
    date=<a date inside the S&P membership>)` returns the right company even when the
    symbol was later reused (NVLS in 2010 → Novellus, not the 2017 Nivalis). Its CIK
    is in `companyfacts.zip`. Without the `date` parameter it returns the later reuser,
    a silent wrong-company trap.
  - **But it's moot for now: delisted *price* history is the real blocker.** Only
    38 of the 179 S&P members delisted inside 2010–2021 have any `bars_1d` rows. This is
    already known: MA DESIGN §12 item 6 says delisted bars exist only for 2024–2026
    (Polygon free-tier entitlement). Share counts without prices give no market cap.
  - **What this means for modeling:** barrier labels on a survivors-only 2010–2021
    panel undercount stop-outs, the downside-first paths of companies that later
    died. The MA study handled it with a Tier-3 cap on bearish-side claims
    (DESIGN §7.3). Modeling needs its own answer: a paid survivorship-free source
    (e.g. Norgate, Sharadar, EODHD), or an explicit bias bound on every
    reported probability.
- **HY credit spread and SP500 from FRED:** stored history starts after 2021, so neither
  exists inside the development window. **Filled 2026-09-28:** ETF daily bars (yfinance, 2005+) now in
  `bars_1d`: SPY/QQQ/IWM/DIA, the 11 SPDR sectors (XLRE from 2015, XLC from 2018),
  HYG (2007+)/LQD for a credit proxy, IEF/TLT/SHY for rates, GLD, UUP. None were loaded
  before, although `relative_strength` expects SPY. Side effect to know about: signal CLIs'
  `--all` (`SELECT DISTINCT ticker FROM bars_1d`) now include these ETFs too.
- **Earnings dates:** absent (§3).
- **Survivorship-free prices: decision pending**, logged in `docs/backlog.md`. Options:
  pay for a source (Norgate, Sharadar, EODHD, roughly $30–100/month), or state a bias
  bound next to every reported probability.

---

## 8. Validation harness (build before any model)

**Full design: `VALIDATION_HARNESS.md`** (2026-09-30). The list below is the original
sketch it grew from.

- **Walk-forward, date-grouped:** all tickers on a date go to the same fold. Run both
  expanding and sliding windows, since a gap between the two is itself a regime-drift
  signal.
- **Purging:** drop training rows whose label window (up to `H` days) overlaps the test
  fold. **Embargo:** also drop a few days after the test fold.
- **Nested folds** for hyperparameters and for stacking (§2b option 2): the inner folds
  produce the family scores, and the outer fold judges the meta-model.
- **Metrics:**
  - Calibration: Brier score and a reliability curve, per barrier cell.
  - Per-date rank correlation.
  - EV after costs of the top-scored bucket, measured *after* the best-cell argmax.
  - Effective N (distinct dates).
  - Confidence intervals via the MA study's block bootstrap (`moving_averages/stats/`).
- **Trial log:** every fit (features, hyperparameters, folds, metrics) gets appended
  automatically, the same way `EXPERIMENTS.csv` works for the study. This is what makes
  "how many things did we try" answerable later.
- **Planted-effect check:** reuse the `validate-synth` idea. The harness must recover a
  planted edge and report nothing on pure noise.

---

## 9. Tooling: code contracts first, skills second

The delicate parts of feature work: point-in-time joins, one-bar lag, trailing-only
normalisation, NaN preservation (MA invariant 9), and warmup. These are best enforced as
**code plus tests**, not as instructions:
- A feature registry where each feature declares its family, shape, warmup, source and
  normalisation.
- A shared **leakage test:** perturb all data after *t* and assert every feature at *t*
  is unchanged. Every registered feature runs through it automatically.

Skills sit on top of that, as process checklists for recurring jobs ("add a feature
family", "run a model trial and log it"). Write them *after* doing each job once by
hand. Written earlier, they'd lock in guesses.

---

## 10. Phase B: conditional alerts ("coiling, watch a break above $100")

This builds on Phase A:
- *Coiling* = compression features (ATR/BB-width percentile, ribbon compression). VCP is
  an untested candidate here, not a validated signal.
- *$100* = nearest-resistance level from the LRP features.
- The alert = score the barrier surface under a **hypothetical bar** that closes just
  above the level, and report how much the surface improves.

Requirements this puts on Phase A: features must be recomputable from a hypothetical
next bar, and the model must behave sensibly near unseen values. Trees extrapolate
flatly, which is fine here, but the model needs checking on it.

---

## 11. Target use: a notification service

**Recommendation:** train on *all* liquid ticker-days. Notifications are thresholds on
the model's output, not a separate model. Three kinds of alert:
1. **Setup alert:** the best barrier cell's calibrated EV after costs clears a threshold.
   The message reads like the §1 statement.
2. **Watch alert (Phase B, §10):** a coiling stock near a level; "if it closes above L,
   the surface becomes X".
3. **Event alert:** reserved for an event that proves alert-grade out of sample. None in
   the MA study is. Extreme slope covers 40% of the panel on any date, so it's a ranking
   feature, not an alert.

What a notification service changes in the evaluation:
- **Precision beats recall.** A missed setup costs nothing; a bad alert costs trust.
- **Fixed alert budget.** Say ≤5 per day. The core metric becomes *precision and EV of
  the top-k per day*, measured out of sample, rather than global AUC.
- **Calibration matters most.** "70%" must mean 70%, checked per probability bucket.
- **Alert fatigue and clustering.** Alerts on the same day are correlated (market-wide
  moves). Report effective N by date, and consider capping alerts per sector.
- **Operationally:** end-of-day batch after the close, alerts computed for execution at
  the next bar (the one-bar lag), plus a log of every alert sent. Logging from day one
  gives a genuine forward test.

---

## 12. Model family: why trees first, not an LSTM or transformer

This isn't a rejection of sequence models. It's an order of work: the tree model is the
bar a sequence model has to clear.

- **Effective N is small.** There are millions of ticker-day rows, but only ~3,000
  development dates, and cross-sectional rows on the same date are correlated. Deep
  sequence models need far more independent signal than that to beat simpler learners.
- **The signal is weak.** The MA study's best effects are fractions of a percent. On
  low signal-to-noise tabular finance data, gradient-boosted trees are consistently
  hard to beat, and they're less prone to memorising noise.
- **Half the families aren't sequences.** Level sets, events, and static and
  market-wide data (§2b) fit an RNN poorly. The time-series families can already be
  given to trees as trailing summaries (slopes, percentiles, run lengths). The MA study
  showed such summaries carry *weak* signal after controls; it never compared them with a
  sequence model. Its effect sizes are what a sequence model has to beat.
- **Speed and diagnosability.** Trees train in minutes, so walk-forward × many folds
  × ablations is affordable. Feature attributions show *which* family drove an alert,
  and a notification needs that "why".

**Where sequence models earn a place:** learning shapes we didn't engineer from raw
normalised OHLCV (F1). A good compromise is a hybrid: a small 1D-CNN or transformer
encoder over the last ~60 bars produces an embedding, which is fed *alongside* the
engineered features. It stays in only if the harness shows an out-of-sample gain over
the tree-only model. That's Stage 4 in §5.
