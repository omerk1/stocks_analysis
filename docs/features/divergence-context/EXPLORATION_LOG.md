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
