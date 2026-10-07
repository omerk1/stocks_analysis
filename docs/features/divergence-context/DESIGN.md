# Divergence-context study — design

**Research question.** Does a momentum divergence occurring after an explosive move
without meaningful consolidation have a different forward outcome from weakening
momentum during a retest after constructive consolidation — and does this hold
similarly or differently for bullish and bearish setups?

**Why it's plausible either way.** Momentum oscillators measure *speed*, not level: a
calm second leg after an impulsive first leg prints a lower indicator high almost
mechanically, so the regular-bearish label conflates "momentum fading before a
reversal" with "momentum normalizing after an unsustainable move." Whether those two
situations have different outcomes is precisely the open question — practitioner lore
says yes; lore is where dead hypotheses come from. Neither outcome is assumed; feature
names stay neutral (*normalization* vs *deterioration*, never "healthy"/"unhealthy").

## Protocol

This study follows the repo's research discipline (see the MA study's CLAUDE.md
sections, which are the reference):

- **Holdout locked**: every study analysis reads events/outcomes `<= 2021-12-31` only.
  The divergences *module* is production signal infrastructure and detects over full
  history (store spans to the present) — the lock applies to study aggregation, not
  detection.
- **Track A first** (exploration: wide, cheap, logged in `EXPLORATION_LOG.md`, nothing
  stated as a finding), **Track B** (pre-registered, controls, FDR) only for promoted
  hypotheses.
- **No bare conditional means**: any outcome claim needs its matched no-divergence /
  cross-context control. The central confound: Context 1 and Context 2 differ in
  extension, volatility, and recent momentum *regardless of divergence* — an outcome
  gap between them may be pure mean-reversion of extension.
- **Effective N = distinct event dates.** Bullish divergence after crashes clusters
  violently (2018-12, 2020-03); raw row counts overstate evidence.
- **Delisted tickers stay.** The bullish-divergence-in-selloff bucket is exactly where
  terminal returns live.

## Signals (detection, shipped)

Four cells, all first-class in `src/signals/divergences/` since #158:
`{regular, hidden} x {bearish, bullish}` on RSI / MACD-hist / OBV, ATR-adaptive
pivots, `confirmed_at` timestamps, `as_of`-safe. Full daily-universe backfill since
#163 (522,559 rows, 5,027 tickers; cells 106k–155k each, raw).

- One full-history run filtered by `confirmed_at <= t` is equivalent to a true
  `as_of=t` run for event identity/geometry (tested, zero mismatches) — **but not for
  confluence**: stored `confluence_count`/`agreeing_indicators` are full-run values.
  PIT consumers re-cluster from stored rows (`context.pit_confluence`).
- Lifecycle outcome fields (`max_favorable_move_atr`, `invalidated`, ...) are
  **outcomes, never features**. Invalidation is judged at the pair's price extreme
  (p1 for hidden rows), symmetric across forms.
- **Case C — equal-level retest with weaker momentum — is deliberately NOT an event
  type yet.** At the default `extreme_equality_tolerance_atr = 0`, equal-extreme pairs
  emit nothing; the tolerance loosening belongs to regular only (a within-tolerance
  higher high + higher indicator high is trend agreement, not hidden divergence). If
  step 0 motivates it, Case C becomes its own event definition ("close within ε·ATR of
  prior confirmed pivot extreme with indicator below its reading at that pivot"),
  which needs no pivot confirmation and carries only the standard one-bar lag.

## Context scalars (v0)

`src/signals/divergences/context.py`, stored per event in `divergence_context`
(keyed by divergence id). All windows end at **p2's bar**; availability is the event's
`confirmed_at` (structure is measured up to the second pivot, but nothing is knowable
before the pivot pair confirms). Direction-symmetric: "impulse" is the move *into* p1
in the event's own direction-of-extremes (advance into a HIGH pair's p1, decline into
a LOW pair's p1); all magnitudes stored positive.

| column | definition |
|---|---|
| `impulse_gain_pct` | move into p1 over the prior `IMPULSE_LOOKBACK_BARS` (63): from the window's opposite extreme close to p1's close, as a fraction of the former |
| `interpeak_retrace_pct` | retracement between p1 and p2 (opposite-extreme close between the pivots), as a fraction of p1's close |
| `interpeak_retrace_frac` | same retracement as a fraction of the impulse (NaN when impulse ≈ 0) |
| `leg2_gain_pct` | move from the interpeak extreme to p2, as a fraction of the interpeak extreme |
| `leg2_bars` | bars from the interpeak extreme to p2 |
| `atr_contraction` | ATR(14) at p2's bar / ATR(14) at p1's bar |

Deliberately crude and few — step 0 asks "is there mass in this region," not "what is
the final feature set." Ratios (leg speeds, normalization candidates) are derived at
analysis time from these components rather than stored. Derived features must preserve
input missingness (repo invariant #9).

**Holdout boundary of this table, explicitly:** `divergence_context` spans full
history, like `divergences` itself — the scalars are point-in-time by construction
(windows end at p2, past bars only), so post-2021 rows leak nothing *into* dev-window
analysis. The lock applies at read time: every study query filters
`confirmed_at <= 2021-12-31`. Rows past that date exist for eventual production use
and are out of bounds for any study analysis until the holdout is explicitly opened.

## Step 0 — prevalence (Track A, this PR)

Dev window only. Three questions, in `src/analysis/divergence_context_step0.py`:

1. **Does the shape exist at meaningful frequency?** Distribution of
   `interpeak_retrace_frac` / `atr_contraction` within each form x direction cell —
   what fraction of regular divergences sit in the "real pullback + base between the
   pivots" region vs "continuous extension, no reset"?
2. **How entangled are divergence and context?** On a ~300-ticker sample: among
   price-only consecutive same-kind pivot pairs with the Context-2 shape, what
   fraction print a divergence? If ≈ all, the binary divergence x context interaction
   is untestable and the study moves to the continuous "momentum deficit vs structure"
   formulation from the start.
3. **Cell counts and effective N**: events and distinct p2 dates per
   form x direction x year, raw and PIT-index-membership-filtered; descriptive outcome
   tabulations (hit rate via `invalidated`, MFE) for events confirmed `<= 2021-11-30`
   (buffer: the 20-bar outcome window must not cross the holdout).

**Kill criterion (pre-committed):** if the pullback-then-retest shape is under ~5% of
regular divergences in the dev window, or its cells cannot plausibly reach useful
effective N (distinct dates), the context study stops here and only the already-planned
divergence event-features (LRP §2.4 / IDEAS F6) proceed.

Outcome tabulations in step 0 are bare conditional rates: exploration input, never
findings.

## Out of scope (deliberate)

Weekly timeframe (backlog). Divergence on Stochastic/CCI/Williams %R/ROC (M17 priors
weak; revisit only with a Track-B reason). Triple-pivot divergences (spec backlog).
Case C detection (see above). Any model-feature integration before the step-0 gate.

## Log

- `EXPLORATION_LOG.md` here: every Track A look, one dated line each.
- `PREREGISTRATION.md` here: Track B entries (DC-B1/DC-B2 drafted 2026-10-06 — see
  its own status header for draft-vs-frozen semantics). Per-cell result logging per
  the repo's standard protocol (the MA study's file set is the template).
