# Dead Ends

Negative Track B results (CLAUDE.md: "Negative results → `DEAD_ENDS.md` with the number
that killed it and the effective N"). Each entry: hypothesis, what was run, the number
that killed it, effective N, and the conditions under which it would be worth revisiting.
**A null result here is a successful outcome** — do not re-run these looking for a
framing that makes them alive again.

## M4 — Distance from MA: SMA50 and SMA200 facets (2026-09-08)

**Hypothesis:** forward 21-day return is a non-monotonic (or otherwise structured)
function of displacement from SMA{50,200}, across `dist_pct`/`dist_atr`/`dist_z`. See
`PREREGISTRATION.md`'s M4 entry for the full pre-registration.

**Why it looked plausible:** point-estimate decile tables showed a broadly monotonic
decline (SMA50) or a genuine U-shape (SMA200 `dist_pct`/`dist_atr`) surviving C2 matching
— visually indistinguishable, at that stage, from the SMA20 facets that ultimately
survived. Only the block-bootstrap inference layer separated them.

**What was run:** `stats/inference.py::block_bootstrap_spread` — the C2-adjusted
`decile9 - decile0` spread, 500 draws, dates resampled in contiguous blocks of 42 (2x
the 21-day horizon), 90% CI.

**The number that killed it:** every one of the 6 facets' 90% CI includes zero.

| Facet | Point estimate | 90% CI | Raw N (decile 0 + decile 9 rows) | Effective N (distinct dates) |
|---|---|---|---|---|
| `dist_pct_sma_50` | -0.0030 | [-0.0065, +0.0003] | 241,891 | 2,747 |
| `dist_atr_sma_50` | -0.0026 | [-0.0058, +0.0004] | 241,891 | 2,747 |
| `dist_z_sma_50`   | -0.0018 | [-0.0045, +0.0010] | 221,292 | 2,699 |
| `dist_pct_sma_200`| -0.0016 | [-0.0053, +0.0024] | 229,580 | 2,747 |
| `dist_atr_sma_200`| -0.0020 | [-0.0052, +0.0014] | 229,580 | 2,747 |
| `dist_z_sma_200`  | -0.0027 | [-0.0055, +0.0002] | 208,973 | 2,549 |

**Effective N:** 2,549–2,747 distinct dates per facet, alongside the raw row count
(CLAUDE.md invariant #6 / DESIGN §6.3 require both, not just one) — the CI is built from
the effective N, since 21-day return overlap means the raw row count vastly overstates
usable information.

**Tier:** 4 (Rejected) — tested, no effect beyond C2 control.

**Revisit if:** the C2 tercile-vs-decile deviation (`PREREGISTRATION.md`) is resolved by
a broader universe (past S&P 500) and the effect reappears under proper decile matching
— plausible in principle (a coarser match leaves more room for residual confounding to
mask a real effect) but not assumed; re-test, don't just widen the universe and declare
it fixed. For `dist_z_sma_200` specifically, the normalisation-window diagnostic in
`notebooks/moving_averages_distance_from_ma.ipynb` found the 252-day self-normalisation
window measurably unstable at that lookback (cross-sectional rank correlation with
`dist_pct` drops to ~0.69 vs. ~0.88-0.93 at shorter lookbacks) — a plausible mechanism
for why this specific facet is noisy, independent of the universe-size question.
