# Divergence-context study — exploration log (Track A)

One dated line per look, whether or not it went anywhere. Nothing in this
file is a finding; numbers here are bare rates on exploratory data.

## 2026-10-05 — step 0 (prevalence / entanglement / feasibility)

*(Amended same day, pre-merge, after code review: PIT join made rename-aware, Q2's
shape definition aligned with the stored scalars' NaN rule and its boundary filter
moved to p2_date, outcome buckets split three ways. Superseded figures: PIT 2.5–3.6k
dates, entanglement 29.1%, extension bucket 44.8%.)*

- Prevalence (404,634 dev-window events, ≤2021-12-31): pullback+rebuild shape (retrace_frac ≥ 0.33, leg2_bars ≥ 5) = 61.7% of regular/bearish, 69.4% of regular/bullish, ~91% of both hidden cells. Both shape regions well populated → **kill criterion passed, study proceeds**.
- Cells / effective N: raw 9.8–10.5k distinct p2 dates per form×direction cell; PIT-filtered (S&P 500 + NDX membership at p2, rename-aware) 2.6–3.7k dates on 11.1–18.9k rows. Feasible everywhere; yearly coverage continuous from ~1980 through 2021.
- Entanglement (300-ticker sample, as_of 2021-12-31, shape defined identically to the stored scalars — insufficient-lookback pairs excluded, divergence match by p2_date): only **29.2%** of higher-high pivot pairs with the pullback+rebuild shape carry a stored regular-bearish divergence (±5 days). The mechanical-entanglement worry was overstated — binary divergence × context designs have abundant no-divergence controls. (Caveat: ±5-day matching vs the detector's 3-bar pairing window may undercount slightly.)
- Outcome peek (bare rates, confirmed ≤ 2021-11-30, three-way shape buckets): within regular/bearish, invalidation runs extension 45.7% > pullback+rebuild 41.3% > deep-fast 38.9%; regular/bullish is nearly flat (34.7/34.2/33.6). Hidden cells sit far lower (15.0–22.4% shaped; extension sub-buckets higher but tiny, n≈0.8–1.1k) — **cross-form invalidation rates are NOT comparable**, the invalidation threshold sits at the pair extreme, farther from the reference for hidden rows by construction. Median MFE ≈ 4.4–5.4 ATR everywhere. Design input only, no claims.
- Feature-design observation: hidden cells' retrace_frac medians exceed 1 (the interpeak retrace is larger than the 63-bar impulse into p1) — for hidden events p1 is often not an impulse top at all; impulse normalization needs care before any context feature is pre-registered.

## 2026-10-10 — R/R strategy-form sweep: pre-committed grid and kill criterion (written BEFORE any payoff was computed)

*(Machine clock at commit time reads 2026-10-07, as with the DC-B1/B2 rows; narrative date is the study's.)*

Track A follow-up to the DC-B1/B2 Inconclusive readout, and a different question: means
hide what strategies harvest — a stop at the event's own invalidation level amputates the
left tail, so a rule can have positive expectancy where unconditional-return means showed
nothing. Everything below is exploration: no corrections, no findings, no tradeable claims;
the only promotion path is a DRAFT DC-B5 registration presented to the user.

**Grid** (coarse, ~324 event cells before variants):
direction {bearish→short, bullish→long} × form {regular, hidden} × indicator {rsi,
macd_hist, obv} × context class {extension, pullback_rebuild, other = band + deep-fast via
`classify_context` defaults; NaN-retrace events excluded and counted} × strength terciles
within (form × indicator × direction) × duration_bars bins {≤25, 26–45, ≥46} (dev-window
terciles ≈ 26/45). Tercile edges are a dev-window full-sample statistic — the sanctioned
cell-defining-bin exception, same pattern as the frozen PREREGISTRATION's matching bins;
bins define cells, nothing downstream treats them as point-in-time.

**Strategy form** (per event; all exits from one bar walk): enter at the open of the first
bar after `confirmed_at` (invariant #2); stop = pair price extreme (max(p1,p2) bearish /
min(p1,p2) bullish) ± 0.25 × ATR14-at-confirmation beyond it (sensitivity facet: 0.10,
0.50); R = |entry − stop|. Variants: target ∈ {1R, 2R, 3R, none} × max hold ∈ {21, 63}
bars. **Primary variant for the kill criterion: 2R target, 63-bar hold, ε = 0.25,
20 bps.** Walk semantics follow `barriers.py`: gap-through fills at the open, same-bar
target+stop tie resolves to the stop, window past `data_end` = censored (no payoff,
counted), ticker series ending early = delisting-terminal exit at last close, kept and
flagged (invariant #4). Entry already beyond the stop (R ≤ 0) or R < 0.1 × ATR (degenerate
R-multiples) → excluded and counted. Payoffs recomputed from bars loaded as_of 2021-12-31
with fail-closed `data_end` — never from the stored 20-bar lifecycle fields. Holdout
untouched (p2 and every payoff bar ≤ 2021-12-31).

**Universe:** PIT S&P 500 + NDX membership at p2 (rename-aware), delisted kept
(tickers-table timing logic as in the DC-B1/B2 run).

**Controls (mandatory, invariant #5):** the SAME walk on no-divergence pivot pairs —
regular-form events vs `regular_geometry=1, has_divergence=0`; hidden-form vs
`regular_geometry=0, has_divergence=0` (price-only `confirmed_at`). Control baselines per
(direction × geometry × context class × duration bin × p2 month); each event cell's
headline is **event expectancy MINUS the month-reweighted matched-control expectancy**
(weights = the event cell's month distribution; uncovered months dropped and renormalized,
coverage reported). "Buying crashes with stops has positive skew" is true without any
divergence and must not be rediscovered as an edge.

**Metrics per cell × variant** (all descriptive): expectancy in R (gross and net of
20 bps round-trip primary / 10 bps annotated, converted per trade via cost × entry / R),
expectancy in ATR, hit rate, win/loss magnitude ratio, skew (invariant #10 trio), MFE/MAE,
median and p10/p90 of R, resolution mix (stop/target/time/delisted/censored), rows,
**effective N = distinct p2 dates** (invariant #6), trades/year, control delta as above.

**Robustness facets** (inside Track A): era splits 2010–2015 vs 2016–2021 and 2020-in vs
2020-out; neighbor agreement across adjacent strength/duration bins (plateau discipline —
a lone bright cell is noise and will be called noise); stop-ε sensitivity.

**Kill criterion (pre-committed verbatim):** the sweep is DEAD (one log line, stop) unless
at least one (direction × form × context) region shows: net-of-cost expectancy vs matched
controls > 0 at the primary variant with ≥ ~500 distinct p2 dates, the SAME sign in both
era splits, and agreement across its neighboring magnitude/duration bins. A surviving
region's ONLY next step is a drafted DC-B5 pre-registration (own N_tests, own correction,
three-way verdicts — DC-B1/B2 template) presented to the user. No trading claims, no
FINDINGS.md entries, no promotion of any sweep number anywhere.

Code: `src/analysis/divergence_rr_sweep.py`; per-trade cache as parquet under gitignored
`data/derived/divergence_rr_sweep/` (nothing written to the shared sqlite).
