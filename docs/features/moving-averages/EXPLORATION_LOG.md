# Exploration Log

Track A only (DESIGN.md §1.5). One line per look, whether or not it went anywhere.
**Nothing here is a finding.** Killed Track B hypotheses go in `DEAD_ENDS.md`; anything
promoted past the gate goes in the final report, not here.

## 2026-09-07

- M0.1 descriptive atlas (`notebooks/moving_averages_m0_descriptive_atlas.ipynb`): distributions of `dist_pct`, `dist_atr`, `dist_z`, `slope_log_21` (SMA-50), 408 S&P 500 constituents (as of 2021-12-31), dev window 2010-2021 only, faceted by era / sector / dollar-volume decile. EXPLORATORY.
- All four distributions unimodal at every facet checked — no bimodality found anywhere. EXPLORATORY, didn't go anywhere as a "bimodal shape" candidate.
- `dist_pct`/`dist_z`/`slope_log_21` (SMA-50) get markedly more left-skewed and fat-tailed in 2018-2021 vs. 2010-2013/2014-2017 (e.g. `dist_pct_sma_50` skew: -0.07 → -0.14 → -0.85). EXPLORATORY — candidate for M9 (regime-conditional) or an era facet within M4.
- `dist_atr_sma_50` is visibly less skewed and less fat-tailed than `dist_pct_sma_50` on the same rows — normalisation changes the shape, not just the scale. EXPLORATORY — visually confirms DESIGN §2.3(3)'s concern; reinforces that M4 must run both normalisations as planned, not pick one.
- Sector skew doesn't track sector volatility: Utilities/Real Estate have the lowest `dist_pct_sma_50` spread but among the most negatively skewed distributions; Healthcare/Communication Services have wider spread but are nearly symmetric. EXPLORATORY — candidate for a sector facet in M4.
- `dist_z_sma_50` shows a monotonic gradient by dollar-volume decile (explicit proxy, not true market cap — see Phase 0's thin `shares_outstanding` coverage) despite already being self-normalised per ticker: mean -0.03 → -0.07, skew -0.55 → -0.24, smallest to largest decile. EXPLORATORY — candidate for M4's universe-tier facet once a real `mktcap_decile` exists.
- `corr(dist_pct_ema_50, slope_log_5_ema_50)` = 0.947 on real data — confirms the M6.0 algebraic identity's practical bite at k=5, not just its exact k=1 form. EXPLORATORY — not a new finding, a sanity check ahead of M6 relying on it.
