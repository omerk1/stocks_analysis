# Pre-registration

Track B only (DESIGN.md §6.6). Written and committed *before* running the analysis it
describes — that ordering is the point. Once a grid entry has been run, its definition
here is frozen; a later change of scope goes in as a new, separately dated entry, not an
edit to this one (DESIGN.md §6.6's `N_tests` denominator needs the full history, not a
silently-revised one).

## M4 — Distance from MA (2026-09-08)

**Module / track:** M4, Track B (DESIGN.md §8, M4).

**Promoted from:** Track A M0.1 descriptive atlas (`EXPLORATION_LOG.md`, 2026-09-07/08)
— four of five candidate observations pointed at distance-from-MA normalisation/shape
questions. The fifth (the liquidity-decile-gradient candidate) is tracked
separately in `EXPLORATION_LOG.md` and is **not** part of this entry.

**Hypothesis:** Forward 21-day return is a non-monotonic (or otherwise structured)
function of displacement from SMA{20,50,200}, and that structure differs by
normalisation (`dist_pct` vs. `dist_atr` vs. `dist_z`) — per DESIGN §2.3(3) and the
2026-09-07 M0.1 finding that ATR-normalisation visibly changes distribution shape, not
just scale.

**This slice's scope** (a first pass, not the full DESIGN §8 M4 spec):
- Features: `dist_pct`, `dist_atr`, `dist_z` at SMA{20, 50, 200} — the Phase 2 starting
  subset. (`dist_pctile` isn't built yet; WMA/HMA/KAMA/VWMA distance isn't in scope, per
  Phase 2's own deferral.)
- Event definition: decile bucket of the distance feature, computed and lagged exactly
  as already built in `features/distance.py`/`features/panel.py` — no new event type.
- Horizon: 21 trading days only (`fwd_ret_21`) — the horizon Phase 1's synthetic gate
  already validated. The full 8-horizon term structure is deferred to a later slice.
- Universe: the 408 S&P 500 constituents (as of 2021-12-31) already cached, dev window
  2010-01-01 → 2021-12-31. Not yet run across U1/U2/U3 tiers (DESIGN §3.2) or an ER
  high/low split — both deferred.
- Controls: **C0, C1, and C2** (date + momentum-tercile + vol-tercile + sector matched —
  see "C2 note" below for tercile vs. decile). C1 is the default per DESIGN §6.1; the
  full C0→C1→C2 shrinkage waterfall is the primary output.
- **Not in this slice:** vol-neutralisation as its own separate pass (distinct from the
  C2 vol-tercile match — DESIGN's "repeat with vol-neutralisation" sub-bullet),
  ER/trend-quality conditioning, the 7.5–8× ATR exhaustion claim, and the IJECM
  0–5%-below claim. Each needs its own pre-registered follow-up entry, not silent
  inclusion here.

**Grid size (N_tests contribution):** 3 normalisations × 3 lookbacks × 10 deciles = 90
bucket-level cells, 1 horizon, 1 universe. No FDR correction applied at this slice
(DESIGN §6.6's correction denominator accumulates across the whole pre-registered grid,
not per-module) — noted here for when that accounting happens.

**Kill criterion:** if no monotonic or reliably U-shaped relationship between distance
decile and C2-adjusted `fwd_ret_21` survives at **any** of the 9 (normalisation ×
lookback) facets — i.e. every facet's decile pattern is flat/noisy after C2 matching —
report the whole slice as a strong negative per DESIGN §8 M4's own kill criterion, and
do not narrow the search for a facet that "works."

**Control tier and why:** C1 is the default read (DESIGN §6.1) — removes the shared
market-return confound via date-matching. **C2 is the tier that actually answers the
research question** (DESIGN §6.1: "the one that separates real MA information from
momentum re-encoding"), since distance-from-MA is mechanically close to trailing
momentum — a stock far above its 50-day is largely restating "this stock went up a lot
recently" (DESIGN §7.1). C0 is reported only for the shrinkage waterfall, never as the
headline.

**2026-09-09 note — C0 here is the diluted definition, not re-audited with
`pooled_delta`.** M1's entry found `c0_delta` isn't scale-comparable to C1/C2 (its
baseline includes the event rows themselves) and that `stats/controls.py::pooled_delta`
is the correct C0 leg of a shrinkage waterfall (DESIGN §6.1, updated the same day). This
module's own tier conclusions were never shape-dependent on C0 specifically — the kill
criterion and tier assignment above are driven by C2's CI and cost, with C0 already
treated as non-headline per the line above — so no result here needs revisiting. Flagged
for completeness only: any C0 numbers shown in this module's own notebook are the
diluted definition, not re-rendered against `pooled_delta`.

**C2 note (tercile, not decile):** DESIGN §6.1 specifies "same rs_rank decile, same vol
decile, same sector." At today's universe size (408 tickers/date), decile × decile ×
11-sector matching yields up to 1,100 cells/date against ~400 tickers/date — too sparse
to populate reliably. This slice uses **terciles** for momentum and vol (3 × 3 × 11 = 99
cells/date) instead, logged here as a practical adaptation to the current universe size,
not a silent substitution. Revisit at decile granularity once the universe broadens
(e.g. full U2).

**Momentum control used:** `mom_12_1` (12-month return skipping the most recent month:
`close[t-21]/close[t-252] - 1`) — DESIGN §7.1's own vocabulary for the momentum control,
computed directly rather than via the fuller `relative_strength` module's rs_rating
pipeline (index-membership-scoped, sector-ETF-benchmarked — heavier machinery than a
tercile bucket needs; revisit if/when `rs_rank` itself becomes a first-class feature).

**Vol control used:** `realized_vol_63` (63-trading-day rolling std of daily returns).

**Minimum sample threshold (DESIGN §6.9):** no bucket reported below 200 events across
≥30 distinct dates and ≥30 distinct tickers; below-threshold buckets are shown flagged,
not as an interpretable number.

**Plateau check (DESIGN §6.7):** neighbouring deciles (±1) must agree in sign/rough
magnitude; the three lookbacks (20/50/200) are compared for consistency of pattern
across the grid, not treated as independent single points.

**Effective N:** reported as distinct event dates alongside raw row count, per bucket
(CLAUDE.md's effective-N invariant) — required in the output table, not optional.

---

### Deviations from pre-registration (logged, not silently applied)

**2026-09-08 — C2 tercile substitution.** As specified above ("C2 note"): DESIGN §6.1
calls for decile × decile × sector matching; this slice uses tercile × tercile × sector
(3 × 3 × 11 = 99 cells/date instead of 1,100) because the current 408-ticker (S&P 500)
universe can't populate decile-level cells reliably. This is a scoped, universe-size-
driven deviation, not a change to the hypothesis or kill criterion. **Revisit at decile
granularity once the universe extends past S&P 500** (e.g. the full U2 tier, DESIGN
§3.2) — a broader universe should make decile × decile × sector matching viable, and the
coarser tercile match here may be leaving real confounding unabsorbed (see the
2026-09-08 result addendum below).

### Result (2026-09-08 addendum — inference, cost, and tier assignment)

Full detail in `notebooks/moving_averages_distance_from_ma.ipynb`. Summary: block-bootstrap
CIs (DESIGN §6.2/§6.3, dates resampled in blocks of 42) show the shape-only read ("8 of
9 facets survive the kill criterion") does not hold once actual overlap-adjusted
uncertainty is accounted for — **only the 3 SMA20 facets have a 90% CI excluding zero**;
SMA50 and SMA200 (6 facets, including the SMA200 U-shapes that looked clean on point
estimates) do not. Of the 3 surviving SMA20 facets, none robustly survives a realistic
cost annotation (CLAUDE.md's cost-annotation invariant): ~25 decile-entries/ticker/year per leg (~50 round
trips/year combined, almost exactly DESIGN §6.10's own illustrative example) produces an
annualised cost hurdle that the CI's lower bound doesn't clear under either cost
convention tested, and doesn't clear the point estimate either under DESIGN's own
stated 10bps-round-trip convention.

**Tier assignment (DESIGN §9.2):** capped at Tier 3 for every facet regardless of
outcome — no FDR correction, no holdout test, and only one universe tier exist for this
slice, all three required for Tier 1/2. `dist_pct_sma_20`, `dist_atr_sma_20`,
`dist_z_sma_20` → **Tier 3** (directionally consistent, plausible mechanism, not
actionable — fails cost). The other 6 facets → **Tier 4** (CI includes zero; logged in
`EXPERIMENTS.csv`).

**2026-09-09 addendum — M4 checked against the `above()` NaN-comparison bug found while
building M1, verified unaffected.** While building M1's primary state table, a bug was
found in `features/distance.py::above`: a plain `close > ma` comparison reads a `NaN`
`ma` (its own warmup window) as `False` ("below") instead of undefined, since pandas
comparison operators don't propagate missing values the way arithmetic does. `above` is
not one of M4's own features, but M4's `dist_pct`/`dist_atr`/`dist_z` are also
MA-derived, so this got checked rather than assumed. Verified panel-wide, on the same
408-ticker/2010-2021 panel M4's own result was computed against (formula for
`dist_pct`/`dist_atr`/`dist_z` unchanged by the `above` fix — this is the same
computation M4 originally ran):

| Column | Rows where `isna()` disagrees with its MA's `isna()` | Explanation |
|---|---|---|
| `dist_pct_sma_{20,50,200}` | 0 (of 1,231,698) | exact match, every lookback |
| `dist_atr_sma_{20,50,200}` | 0 (of 1,231,698) | exact match, every lookback |
| `dist_z_sma_{20,50,200}` | 102,408 (= 251/ticker) | **not a bug** — `dist_z`'s own 252-day rolling normalisation window (`DIST_Z_WINDOW`, `features/distance.py`) adds its own warmup on top of the MA's, via arithmetic (`rolling().mean()`/`.std()`), which propagates `NaN` correctly on its own; 251 ≈ 252-day window's own extra warmup, unrelated to the comparison defect |

`dist_pct`/`dist_atr` are division, not comparison — `(close - ma) / ma` on a `NaN` `ma`
is `NaN` via ordinary float arithmetic, with no comparison operator involved anywhere in
the formula, which is exactly why they were never exposed to this defect. **M4's
published Tier assignments above are unaffected; no re-run needed.** Regression test:
`tests/test_moving_averages_features.py::test_dist_pct_and_dist_atr_are_na_wherever_the_ma_is_na`.

**2026-09-09 addendum — M4's turnover figure reconciled against `costs.py`, found
during M11 pre-registration. Verdict unchanged.** M4's own cost table (this notebook,
`entries_per_ticker_year`) counts only *entries* into a target decile — a transition
from not-in-decile to in-decile, per leg. `stats/costs.py::signals_per_year` (built
later, for M1) counts every transition of a boolean state column, entries **and**
exits, and that "flip" count is the quantity M1's already-verified hurdles are built
from (§ above). These are two different quantities, not two measurements of the same
one: for `dist_pct_sma_20`, M4's ad hoc method gives ~25.32 entries/ticker-yr per leg
(~50.64/yr combined, both legs) where `signals_per_year` on the same feature's
top/bottom-decile membership gives 12.536 / 12.111 flips/ticker-yr (24.646/yr combined)
— roughly half, consistent with "flips" counting both directions of a transition that
"entries" counts only one direction of.

Rechecked against M4's actual gross CI (`dist_pct_sma_20`: CI-low = 1.6395%/yr, point =
5.5671%/yr, from this notebook's `cost_df`) at the **lower**, `costs.py`-based combined
hurdle (2.465%/yr, vs. M4's own ~5.06%/yr conservative-convention hurdle): CI-low minus
hurdle = 1.6395% − 2.465% = **−0.83%, still negative**. Same check for `dist_atr_sma_20`
(CI-low 1.1247%/yr vs. its own `costs.py` hurdle) and `dist_z_sma_20` (CI-low 1.4188%/yr
vs. its own hurdle): both still negative. **All three SMA20 facets stay Tier 3, still
fail cost, under either turnover convention** — the 2× gap in the turnover figure
doesn't reach far enough to flip anything; the CI-low was already well below both
hurdle estimates.

**Repo standard going forward: `stats/costs.py::signals_per_year` (entry+exit flip
count), not entries-only.** It's the tested, reusable implementation, it's what M1's
published hurdles are actually built on, and "entries-only" undercounts a strategy that
must also pay to exit a position — a round trip is an entry *and* an exit, and pricing
only the entry leg understates real turnover. M4's own ~50.64/yr figure is not wrong on
its own terms (it measures something real — decile-entry frequency), but it is not the
same thing `signals_per_year` measures, and a future module reusing M4's number
alongside a `costs.py`-based one without this note would be comparing two different
quantities as if they were one.

**2026-09-09 addendum — M4's grid is not independence-checked, found during M11
pre-registration. Declared `N_tests` of 90 is inflated by an unknown factor.** M11's
own independence check (per-date cross-sectional Spearman correlation between
`dist_pct`/`dist_atr`/`dist_z` at SMA20) found median correlations of 0.94–0.98 —
these three normalisations are not independent tests. That check was never run
against M4's own grid at the time M4 shipped, and hasn't been run for SMA50 or SMA200
at all. So M4's declared 90-cell (or 9-facet) `N_tests` contribution almost certainly
overstates the true independent-test count the same way M1's 30 did — by how much is
unknown until the correlation check is repeated for SMA50/SMA200 too. **No tier
changes as a result of this note** — nothing in M4's grid cleared cost under either
turnover convention (see the addendum above), and deduplicating a set of tests that
already all failed can only make the eventual correction *more* conservative, never
less; a smaller, cleaner denominator doesn't rescue a result that didn't clear the
economic bar in the first place. Tracked as an open item, not resolved here — see
`STATUS.md`'s "Whole-grid FDR pass" section for the trigger condition and the
per-module dedup this needs before it runs.

## M1 — Baseline state conditioning (2026-09-09)

**Module / track:** M1, Track B (DESIGN.md §8, M1, lines 556-561).

**Promoted from:** not a Track A candidate — M1 is DESIGN §12's own recommended
minimal-core first module and the backlog's designated next module (`docs/backlog.md`,
2026-09-08 entry). It is run now, after M4, only because Phase 3's Track A exploration
happened to point at distance-from-MA first; M1 was not deprioritized on the merits.

**Hypothesis:** Forward excess returns differ conditional on price being above vs.
below a single SMA (state), and further conditional on the age of that state
(run-length bucket: 1–5, 6–21, 22–63, 64+ trading days, both directions) — DESIGN's
"does a fresh reclaim beat a stale one" sub-question.

**This slice's scope** (a first pass, not the full DESIGN §8 M1 method):
- Families/lookbacks: **SMA only**, {20, 50, 200} — the Phase 2 starting subset. EMA is
  explicitly **out of scope this slice**: the only existing exploratory evidence
  touching "EMA" (`EXPLORATION_LOG.md`, 2026-09-07, `corr(dist_pct_ema_50,
  slope_log_5_ema_50) = 0.947`) measures the M6.0 slope/distance algebraic identity
  *within* EMA — it says nothing about SMA-state vs. EMA-state agreement, which remains
  unmeasured. Rather than assume redundancy (or assume independence) and double
  `N_tests` on it, EMA state agreement is deferred to a cheap Track A look
  (`corr(above_sma_k, above_ema_k)`), not folded into this pre-registered grid.
- Event definition: `above_{ma_col}` (already built, already lagged, `features/panel.py`)
  for the plain state; a new run-length feature (`features/state.py`, built as part of
  this entry) for the age sub-question — see "Run-length censoring" below.
- Horizon: 21 trading days only (`fwd_ret_21`), same precedent as M4's first slice.
- Universe: the same 408 S&P 500 constituents (as of 2021-12-31,
  `data.sp500_full_coverage_tickers`), dev window 2010-01-01 → 2021-12-31 — U1 tier
  (DESIGN §3.2).
- Controls: **C0, C1, and C2** (date + momentum-tercile + vol-tercile + sector matched),
  reusing `features/context.py`/`stats/controls.py::c2_delta` and inheriting the
  tercile-not-decile deviation already logged in this file's M4 entry (2026-09-08 "C2
  tercile substitution") — referenced, not re-derived.

**Waterfall row set (methodology fix vs. M4):** C0, C1, and C2 are computed on the
**same row set** for each cell — the subset that survives C2's stratum-eligibility
criterion (non-null `mom_tercile`/`vol_tercile`/`sector`, and belonging to a
(date, mom_tercile, vol_tercile, sector) stratum with both event and control rows
present). C0 and C1 do **not** additionally run on their own wider natural row sets —
doing so would confound the C0→C1→C2 shrinkage with a change in sample composition,
not just a change in control strictness, defeating the point of the waterfall. Rows
lost vs. C0's unrestricted population are reported as a diagnostic in every table
(count and %, split into missing-C2-inputs vs. singleton-stratum), alongside effective
N.

**Run-length censoring:** the first observed state run per (ticker, MA column) — the
run already in progress when the state series begins, right after the MA's warmup
window — is left-censored: its true start (and therefore its true age) is unknown.
Its rows get **no run-length bucket** (dropped from the run-length analysis entirely,
never labeled `1-5` regardless of how short the observed remainder looks). Every
subsequent run has a directly-observed start (a state flip is directly visible in the
lagged `above` series) and is bucketed normally. A synthetic test with planted runs of
known length (including a planted first/censored run) confirms both the censoring drop
and the bucket recovery before this feature is used in any analysis (see commit
alongside this entry).

**Grid size (N_tests contribution):** 3 lookbacks × (2 state cells + 2 directions × 4
run-length buckets) = 3 × 10 = **30 cells**, 1 horizon, 1 universe. **The cells are
nested, not independent:** within each (lookback, direction), the 4 run-length buckets
partition that direction's state cell exactly (every row in the "above" state cell
falls into exactly one of the 4 above-direction run-length buckets). A later FDR pass
over the full pre-registered grid must account for this nesting rather than treating
30 as 30 exchangeable independent tests.

**Primary vs. secondary cells:** the **6 plain state cells** (above/below × 3
lookbacks) are primary — DESIGN's original M1 hypothesis and this module's core
question. The kill criterion (below) is evaluated **only** over these 6. The 24
run-length cells are secondary — DESIGN frames run-length as a "key sub-question," not
the headline test — reported alongside for the age question but do not individually
trigger the kill. Survival at any cell, primary or secondary, is **provisional pending
FDR**; only the primary-cell kill/no-kill call is this slice's actual verdict.

**Kill criterion:** DESIGN's own wording ("if C2-adjusted effect < 0.1% at 21d across
all lookbacks, the entire 'state' family is a momentum re-encoding") predates the
inference layer and is ambiguous on magnitude-vs-signed and on which point of an
interval to test. Resolved here, committed before running:
- **Magnitude, not signed.** A large real effect of either sign is not a kill, however
  the wording literally reads — a −0.5% below-MA effect must not satisfy "< 0.1%" just
  because −0.5 < 0.1.
- **Evaluated on the CI, not the point estimate**, using the most-favorable-to-survival
  reading of the 90% block-bootstrap interval (`stats/inference.py::block_bootstrap_delta`,
  block length 42): for a primary cell with point estimate and interval
  `[ci_low, ci_high]`,

  `kill_cell := max(|ci_low|, |ci_high|) < 0.10%`

  i.e. even the most extreme point the interval reaches, in either direction, fails to
  clear the 0.1% economic-significance floor. This is well-defined whether or not the
  interval spans zero (both endpoints are checked either way).
- **Module-level kill** fires iff `kill_cell` holds for **all 6** primary cells. If
  triggered: report as a headline finding that the state family is a momentum
  re-encoding, reallocate effort to M4/M5 per DESIGN's own instruction.

**Control tier and why:** C1 is the default read (DESIGN §6.1). **C2 is the tier that
answers the research question** — the same momentum-re-encoding concern DESIGN raises
for M1's own kill criterion applies to the raw state effect, so the C2-adjusted number
is the one the kill criterion is evaluated against. C0 is reported only for the
shrinkage waterfall (this module's primary *output*, per DESIGN §8), never as a
headline number on its own.

**C2 note:** tercile (not decile) momentum/vol matching, inherited unchanged from this
file's M4 entry (2026-09-08 "C2 tercile substitution") — same universe-size constraint
applies here, not re-derived.

**Momentum control used:** `mom_12_1`. **Vol control used:** `realized_vol_63`. Both
unchanged from M4.

**Minimum sample threshold (DESIGN §6.9):** no cell reported below 200 events across
≥30 distinct dates and ≥30 distinct tickers, applied to the **row-restricted**
(C2-eligible-intersection) population, not the unrestricted panel — consistent with the
waterfall row-set fix above. Below-threshold cells are shown flagged, not as an
interpretable number.

**Cost convention (DESIGN §6.10), pre-registered before any results:**
- **(a) Tiered slippage:** S&P 500 constituents are U1 (DESIGN §3.2) → 5bps slippage
  per leg → **10bps/round-trip** (2 legs). Spread/commission are not separately
  estimated in this repo (same limitation as M4); this convention is slippage-only and
  therefore a lower bound on the true hurdle.
- **(b) DESIGN's worked illustrative example** (§6.10: "50 round trips/year at 10bps
  each carries a 5%/yr hurdle" — verified: 50 × 10bps = 500bps = 5.00%/yr, confirming
  "10bps each" is a per-round-trip figure, not per-leg — a per-leg reading would give
  10%/yr, contradicting the stated hurdle): **10bps/round-trip**, applied flat
  regardless of tier.
- For this study's U1 universe (a) and (b) land on the same number, which is a
  coincidence of U1 specifically (at U2 they would diverge: 30bps vs. 10bps) — both are
  computed as separate columns in every cost-annotated table, not collapsed into one,
  so a future universe-tier extension doesn't silently inherit an assumption that only
  holds here.
- **Turnover mechanism (must be measured, not assumed):** unlike M4 (decile-membership
  crossing), a rebalance under M1's rule is triggered by (i) every state flip
  (above↔below) and, for the run-length-conditioned rule, additionally by (ii) every
  bucket-boundary crossing within an unbroken run (day 5→6, 21→22, 63→64). The
  run-length rule therefore has strictly higher turnover than the plain state rule —
  it inherits every state flip's turnover plus the internal boundary crossings.
  `signals_per_year` for each is measured directly off the built panel (bucket-label
  change count per ticker-year) once available, not assumed in advance; the plain-state
  and run-length-conditioned rules get separate hurdle numbers in the output table.

**2026-09-09 addendum — cost-convention derivation, made explicit.** Added after a
review question on whether (a) and (b) above genuinely coincide at 10bps/round-trip for
U1, or whether that was asserted rather than shown. This predates any M1 result (no
waterfall has run yet), so it's a clarifying addition, not a correction of a wrong
number — the bullets above are unchanged.

DESIGN §6.10, quoted in full: `signals_per_year × (spread/2 + commission + slippage)`.
"Use tiered slippage by ADV decile: 5 bps for U1, 15 bps for U2, 40 bps for the illiquid
tail." "A 5-EMA crossover rule generating ~50 round trips/year at 10 bps each carries a
5%/yr hurdle."

Whether "10 bps each" in the worked example is per-leg or per-round-trip is not a
reading choice — it's forced by DESIGN's own stated hurdle:

| Interpretation of "10bps each" | Arithmetic | Result | Matches stated 5%/yr? |
|---|---|---|---|
| per round trip | 50 rt/yr × 10bps | 500bps = 5.00%/yr | yes, exact |
| per leg (2 legs/rt) | 50 rt/yr × 2 × 10bps | 1000bps = 10.00%/yr | no — off by exactly 2× |

Only the per-round-trip reading reproduces DESIGN's own number, so §6.10's "10bps each"
is **10bps per round trip**, not per leg. (Corroborated by this file's own M4 addendum,
which already names its applied convention "DESIGN's own stated **10bps-round-trip**
convention" verbatim — this file resolved the same question the same way once before.)

Convention (a) built up independently, for comparison: "5 bps for U1" is the slippage
component alone, incurred once per execution (entry, and again on exit) — a round trip
is 2 executions, so 5bps + 5bps = **10bps/round-trip**. This is a separate derivation
from (b)'s (which is DESIGN's own pre-aggregated round-trip figure, not built from two
executions at all) that happens to land on the same number for U1.

**U2 divergence, shown explicitly (why this isn't assumed to generalise):**

| Tier | (a) Tiered slippage/leg | (a) Round-trip (×2) | (b) DESIGN illustrative (flat) | Coincide? |
|---|---|---|---|---|
| U1 | 5bps | 10bps | 10bps | yes |
| U2 | 15bps | 30bps | 10bps | **no — diverge by 3×** |
| Illiquid tail | 40bps | 80bps | 10bps | **no — diverge by 8×** |

(a) scales with the ADV-decile tier by construction; (b) is a flat illustrative constant
from a single worked example and does not scale with tier at all. They coincide only at
U1, which is this slice's actual universe — the alignment noted in the bullet above is
real for this slice's numbers, but must be re-derived, not assumed, the moment a U2/U3
universe tier is in scope.

**Plateau check (DESIGN §6.7):** the three lookbacks (20/50/200) are compared for
consistency of sign/rough magnitude across the grid; run-length buckets are checked for
a smooth (not cliff) progression 1–5 → 6–21 → 22–63 → 64+ within each direction.

**Effective N:** reported as distinct event dates alongside raw row count, per cell
(CLAUDE.md's effective-N invariant) — required in the output table, not optional.

**Expected, not a new problem:** per DESIGN §7.3's survivorship cap, weak/below-MA
state cells are Tier-3-capped regardless of outcome (delisted-ticker price history
exists only 2024–2026 in this repo) — the same cap M4 already operates under, not
something this module needs to re-solve.

**2026-09-09 correction — the 6 primary cells are 3 independent numbers, not 6.** Found
before interpreting the waterfall: for a fixed lookback, the "above" and "below" cells
share the same underlying row population (`state_table` builds both from the same
`working` frame, only flipping which side is labeled event vs. control) and the same
(date, mom_tercile, vol_tercile, sector) strata. Under C1/C2, `stratum_deltas` computes
`event_mean − control_mean` per stratum; swapping which side is "event" negates every
stratum's delta, and averaging is linear — so **`c1(below) = −c1(above)` and
`c2(below) = −c2(above)` exactly, by construction**, not as an empirical finding. C0
does *not* share this exact symmetry — it's a count-weighted mirror
(`w_above·c0(above) + w_below·c0(below) = 0`, not `c0(above) = −c0(below)`) — since C0
compares the event group to the *whole* population, not a directly-matched control.

**Verified numerically, not just asserted** (`c1`/`c2` computed independently for both
directions, not derived from each other in code):

| lookback | c1(above)+c1(below) | c2(above)+c2(below) | c2 CI-edge: above vs. below |
|---|---|---|---|
| 20 | 0.0 (exact) | 0.0 (exact) | 0.0034950471940253373 vs. 0.003495047194025337 (equal to float64 precision — the 1-ULP difference is summation-order rounding noise, confirmed via `np.isclose`) |
| 50 | 0.0 (exact) | 0.0 (exact) | 0.0034059770773405573 vs. 0.0034059770773405573 (bit-identical) |
| 200 | 0.0 (exact) | 0.0 (exact) | 0.004233592736636761 vs. 0.004233592736636761 (bit-identical) |

The block-bootstrap CI is *also* an exact mirror here (not just the point estimate):
same seed (`block_bootstrap_delta`'s default), same underlying dates for both
directions, per-stratum deltas exactly negated → every bootstrap draw is the negation of
its counterpart → `ci_low(below) = −ci_high(above)`, `ci_high(below) = −ci_low(above)`,
`boot_std(below) = boot_std(above)`. Consequence: `kill_cell`'s test statistic
(`max(|ci_low|, |ci_high|)`) is **identical between above and below at a given
lookback** — confirmed in the table above, not merely implied by the point-estimate
symmetry.

**Kill-criterion implication:** the committed rule ("module-level kill fires iff all 6
primary cells satisfy `kill_cell`") is truth-functionally identical to "all 3
(one per lookback) satisfy it," since each pair agrees by construction. No change to
`evaluate_kill_criterion`'s code or verdict — this is a statement about what the
existing rule actually tests, not a rule change.

**N_tests implication for a later FDR pass:** this slice's grid-size accounting (above,
"3 lookbacks × 10 cells = 30 cells") counted the primary layer as 2 cells/lookback (6
total). That overcounts the *independent* test count for FDR purposes — the primary
layer contributes **3** independent numbers, not 6, since testing "above" and testing
"below" at the same lookback is not two looks at the data, it's one number reported
twice with a sign flip. A later BH-FDR pass over the full pre-registered grid must
correct against 3, not 6, for this layer, or it over-penalizes M1 for tests that carry
no additional information. (The 24 run-length cells do **not** have this same reduction
— a run-length bucket's control is "same direction, a different bucket," not the
opposite direction, so no equivalent forced-mirror pairing exists there. Not audited for
other redundancy in this pass; flagged only where found.)

### Deviations from pre-registration (logged, not silently applied)

**2026-09-09 — post-hoc short-term-reversal control (`C2_MATCH_COLS_WITH_REVERSAL`).**
Added *after* the 3D primary numbers (`C2_MATCH_COLS` = mom-tercile + vol-tercile +
sector) had already been seen, at explicit request, in response to a real gap: `fwd_ret_21`
is a one-month horizon and `mom_12_1` deliberately skips the most recent month, so
nothing in the pre-registered C2 spec controls for one-month reversal, and being above a
short MA is mechanically correlated with having just risen over roughly that same
window. This is a **post-hoc diagnostic, not a pre-registered test** — per DESIGN §6.6,
a control added after seeing results doesn't get to retroactively become the primary
comparison, however well-motivated. **The 3D result (`C2_MATCH_COLS`) remains this
slice's pre-registered primary and the one the kill criterion is evaluated against.**
The 4D result (`C2_MATCH_COLS_WITH_REVERSAL`) is reported alongside as a robustness
check on the 3D finding, not promoted to headline, and is not itself a new pre-
registered entry (no separate kill criterion, no `N_tests` contribution of its own —
it's a diagnostic pass over the same 3 primary cells, not a new test of a new
hypothesis).

### Cost-test definitional gap (found 2026-09-09, corrected here for M2/M3 to inherit)

The CI-based cost check ("does the CI's near-zero bound clear the hurdle") was first
implemented as: pick whichever endpoint (`ci_low`, `ci_high`) has the smaller absolute
value, and compare its magnitude to the hurdle. **This is wrong whenever the interval
spans zero.** If `ci_low < 0 < ci_high`, the true most-conservative achievable magnitude
within the interval is exactly **0** (zero is a valid point inside a zero-spanning
interval) — not whichever endpoint happens to be numerically closer to zero, which can
even land on the *opposite sign* from the point estimate (seen directly on lb200's 4D
CI: point estimate −1.257%/yr, "near-zero" endpoint computed as **+1.007%/yr** — a
positive number standing in for a negative effect). Comparing that endpoint's magnitude
to a hurdle and calling it "clears" is not a conservative test; it's a coin flip on
which side of zero the wider tail happened to land.

**Corrected rule:** a cell whose CI spans (or touches) zero **automatically fails** the
CI-based cost test, full stop — no magnitude comparison is meaningful once "no effect"
is itself inside the interval. Only a CI that excludes zero entirely proceeds to the
magnitude comparison (both endpoints share the point estimate's sign in that case, so
"the endpoint closer to zero" is well-defined and conservative).

**Rescoring under the corrected rule:**

| lookback | convention | CI spans zero? | old CI-bound verdict | corrected CI-bound verdict |
|---|---|---|---|---|
| 20 | 3D | No | fail | fail (unchanged) |
| 20 | 4D | No | fail | fail (unchanged) |
| 50 | 3D | No | fail | fail (unchanged) |
| 50 | 4D | **Yes** | fail | fail (unchanged — already failed the magnitude test too, now fails for the structurally correct reason) |
| 200 | 3D | **Yes** | fail | fail (unchanged — same as above) |
| 200 | 4D | **Yes** | **pass** | **fail — rescored** |

Only one verdict actually flips: **lb200's 4D CI-bound cost test, previously reported as
passing, is rescored as a fail.** The point-estimate cost test (a separate, non-CI
comparison) is unaffected by this fix and is unchanged for every cell. This is recorded
here as a definitional gap in the shared cost-testing methodology, not an M1-specific
issue — **M2/M3 must implement the CI-based cost test with the spans-zero check from the
start**, not rediscover this.

**Annualization is approximate, labeled as such.** The ×12 (=252/21) scaling used to
annualize the 21-day `fwd_ret_21` edge into a comparable-to-`signals_per_year` annual
rate is a **linear approximation**, not a derived quantity. 21-day forward returns
overlap 20/21 (DESIGN §6.2) and don't compound or scale linearly this way in reality;
the approximation is roughest exactly at the CI bounds, where the block-bootstrap
uncertainty itself doesn't have a clean annualization rule. Treat every "annualized"
number in this entry's cost section as an order-of-magnitude comparison against the
turnover hurdle, not a precise annual rate.

### Cost hurdle, computed (2026-09-09, `stats/costs.py`)

The Tier-assignment cost verdicts below were first reported in conversation only, backed
by an ad hoc, uncommitted script — a real gap against CLAUDE.md's invariant #8 ("Any
claim implying trading carries `signals_per_year × cost` next to the gross number"),
caught during PR review. `signals_per_year`/`cost_hurdle`/`annualize`/`ci_clears_cost`/
`point_clears_cost` in `stats/costs.py` now compute this as reusable, tested code, reused
from `features/state.py::state_run_id` (no reimplemented comparison logic) — re-running
it reproduces the exact figures below, cross-checked line by line against the original
ad hoc numbers.

`signals_per_year` (plain-state rule, state-flip count per ticker-year, pooled across
all 408 tickers) and the resulting hurdle at the pre-registered 10bps/round-trip
convention (see the cost-convention addendum above):

| lookback | signals/yr | cost hurdle (annual) |
|---|---|---|
| 20 | 30.377 | 3.038% |
| 50 | 17.990 | 1.799% |
| 200 | 7.785 | 0.779% |

Against the annualized `above`-direction effect (`below` is the exact negation — see the
mirror-identity finding):

| lookback | convention | annualized gross | annualized CI | point clears? | CI clears? |
|---|---|---|---|---|---|
| 20 | 3D | −2.576% | [−4.194%, −0.950%] | No | No |
| 20 | 4D | −1.449% | [−2.481%, −0.319%] | No | No |
| 50 | 3D | −2.196% | [−4.087%, −0.367%] | **Yes** | No |
| 50 | 4D | −1.353% | [−2.920%, +0.163%] | No | No |
| 200 | 3D | −2.578% | [−5.080%, +0.057%] | **Yes** | No |
| 200 | 4D | −1.257% | [−3.476%, +1.007%] | **Yes** | No |

Every `ci_clears?` verdict is `No` — the CI-based cost test never clears at any
lookback, under either control set. The point-estimate test clears at lb50/lb200 under
3D only, not under 4D (where the reversal control shrinks the gross edge further). This
is the exact basis for the Tier-assignment cost language below.

### C1 > C0 investigation, resolved (2026-09-09)

Tested directly rather than reasoned about, per the "verify, don't assert" standard
this bug-hunt session has been holding to throughout. Two candidate mechanisms were
proposed: (1) C0's baseline dilutes the event group into the comparison population,
shrinking `|c0|`; (2) C1 weights dates equally while C0 implicitly weights rows equally,
so if breadth correlates with date-level conditions the two differ on that basis alone.

**Mechanism 1, verified exact:** `stats/controls.py::pooled_delta` computes the event-
vs-control contrast with event rows excluded from the baseline (like C1) but *without*
date stratification (unlike C1) — isolating dilution from date-weighting. The algebraic
identity `c0 = (1 - p) * pooled_delta` (p = event population share) holds to 4 decimal
places at every lookback (ratio to prediction = 1.0000, all three). Dilution is real and
exactly as predicted.

**But dilution does not explain the observed C1 > C0 gap — it predicts a much larger one
than what's observed, and something else cancels most of it:**

| lookback | p | c0 | c1 | pooled (dilution-corrected, no date-stratification) | \|pooled\|/\|c1\| |
|---|---|---|---|---|---|
| 20 | 0.564 | −0.002507 | −0.002734 | −0.005748 | **2.10×** |
| 50 | 0.587 | −0.002311 | −0.003246 | −0.005589 | **1.72×** |
| 200 | 0.598 | −0.001693 | −0.001805 | −0.004207 | **2.33×** |

The back-of-envelope prediction that motivated this check (`c0 ≈ (1-p)·c1`, i.e.
`c0 ≈ 0.44·c1` at lb20) implicitly assumed `c1 ≈ pooled` — that date-stratification
doesn't change much, so C1 could stand in for "C0 with dilution removed." **That
assumption is false: `pooled` is 1.7–2.3× *larger* in magnitude than `c1` at every
lookback.** Removing dilution alone (C0 → pooled) would roughly double the effect;
date-stratification (pooled → C1) then roughly halves it back down. The small, modest
C1 > C0 gap actually observed is the *net* of two large, opposing, and now separately
verified mechanisms — not evidence that dilution is the primary driver. **Mechanism 2
(date-vs-row weighting) is the dominant force**: it's large enough to more than reverse
what dilution-removal alone would predict. This resolves which mechanism dominates: it
does not (yet) explain *why* date-composition produces specifically this magnitude of
shrinkage — that remains unexplored, but the question "is C1>C0 just dilution" is
answered: no.

### Waterfall re-rendered with pooled_delta as C0 (2026-09-09, same-day follow-up)

The investigation above established that `c0_delta` is not scale-comparable to `c1`/`c2`
— its baseline includes the event rows themselves, diluted by their own population share
`p`. **`pooled_delta` is the actual C0 leg of a shrinkage waterfall**: same event-
excluded-from-baseline logic as C1, without C1's own date-stratification, so it's on the
same scale as C1/C2 and isolates only the "does adding controls shrink the effect"
question DESIGN §8 asks. Prediction: `pooled → c1 → c2` should now be monotone
decreasing in magnitude at all three lookbacks — the clean shrinkage waterfall this
module's whole point is to produce.

**Verified — holds at 2 of 3 lookbacks, not all 3:**

| lookback | c0 (diluted, DESIGN's literal definition) | pooled (actual C0 leg) | c1 | c2 | monotone decreasing? |
|---|---|---|---|---|---|
| 20 | −0.002507 | **−0.005748** | −0.002734 | −0.002146 | **Yes** |
| 50 | −0.002311 | **−0.005589** | −0.003246 | −0.001830 | **Yes** |
| 200 | −0.001693 | **−0.004207** | −0.001805 | −0.002149 | **No** — \|c2\| > \|c1\| |

**lb20 and lb50: fully resolved, not a market phenomenon.** With `pooled` correctly
substituted for `c0`, the waterfall shrinks cleanly and monotonically at both lookbacks
— exactly DESIGN §8's predicted shape. **The earlier "C1 > C0 hump" was entirely an
artifact of comparing two estimators on different scales** (`c0`'s diluted baseline vs.
`c1`'s pure one), not a market phenomenon requiring a mechanistic explanation. There is
nothing further to explain here — mechanism 2 (date-vs-row weighting) is still real and
still verified to dominate mechanism 1 (per the investigation above), but the *practical*
upshot is simpler: read the waterfall as `pooled → c1 → c2`, not `c0 → c1 → c2`, and the
"hump" was never there.

**lb200: the anomaly survives and is now confirmed genuine, not an artifact.** `pooled`
is scale-comparable to `c1`/`c2` by construction, and `|c2| > |c1|` still holds at lb200
even so. This rules out "it's just the C0-comparability issue" as an explanation for
lb200's non-monotone shape — whatever is happening there is a real residual finding,
distinct from (and no longer confusable with) lb20/lb50's now-fully-explained case. Not
investigated further in this pass; consistent with, and reinforcing, lb200's Tier 4
assignment below.

**Cross-module note, logged as an open question, explicitly not investigated.** SMA200
has now been the anomalous lookback in two separate modules: M4's `dist_z_sma_200` facet
was rejected as noisy, with its own diagnostic finding the 252-day self-normalisation
window measurably unstable at that lookback (cross-sectional rank correlation with
`dist_pct` drops to ~0.69 vs. ~0.88–0.93 at shorter lookbacks — `EXPERIMENTS.csv`'s
`dist_z_sma_200_h21` row); and now M1's lb200 primary cell is the one that fails to show clean monotone
shrinkage. Worth naming plainly: the 252-day window several of this study's controls
lean on (`mom_12_1`'s own lookback, `dist_z`'s normalisation window) is only ~1.26× the
200-day SMA lookback itself — not a lot of slack. lb200 also independently carries this
module's worst row loss (51.9% → 74.9%) and heaviest all-above singleton-stratum skew
(84.5%) of the three lookbacks tested. Whether the `|c2| > |c1|` shape at lb200 is (a)
the selection effect, (b) the same 252-day-window-relative-to-200-day-lookback
instability that hit M4's `dist_z_sma_200`, (c) both, or (d) unrelated to either — is
**not investigated in this pass**. **Trigger for revisiting: a third independent SMA200
oddity surfacing in a later module** (also logged in `docs/backlog.md` for whoever
starts M2) — at that point these stop being two coincidental single-module quirks and
warrant a dedicated SMA200 audit across the study.

**Reported going forward:** `modules/baseline_state.py::_cell_row` now returns `pooled`
alongside `c0`/`c1`/`c2` — `c0` stays for reference (DESIGN §6.1's literal definition)
but is explicitly labeled diluted, not part of the waterfall reading.

### Tier assignment (DESIGN §9.2)

**Two caps apply independent of any cell's own numbers:**
- **DESIGN §7.3's survivorship cap** — same as M4: delisted-ticker price history exists
  only 2024–2026 in this repo, so weak/below-MA-state cells are Tier-3-capped regardless
  of outcome.
- **Selection limitation from row loss.** The C2-eligible restriction drops 38–52% of
  the unrestricted population at 3D and 75–77% at 4D, and the dropped rows are not a
  random slice: 65–85% of dropped rows (rising with lookback) are singleton "all-above"
  strata, not a balanced mix of all-above/all-below (see the 2026-09-09 characterization
  above). This is a selection concern in the same spirit as §7.3's cap — the retained
  sample isn't the population the hypothesis is nominally about — and is treated as an
  independent cap here, not folded into §7.3's.
- Neither FDR correction, a holdout check, nor a second universe tier exist for this
  slice — all three required for Tier 1/2, same gap M4 had.

**Per-lookback** (3 independent numbers, per the above/below mirror-identity finding —
above and below are not evaluated as separate evidence):

- **lb20 → Tier 3.** 3D CI excludes zero cleanly (`[−0.003495, −0.000791]`). Fails cost
  robustly: annualized gross −2.576% (3D) / −1.449% (4D) against a 3.038%/yr hurdle
  (30.377 flips/yr) — neither the point estimate nor the CI-bound test clears it, at 3D
  or 4D (see "Cost hurdle, computed" above for the full table).
- **lb50 → Tier 3, weaker than lb20.** 3D CI excludes zero, barely
  (`[−0.003406, −0.000306]`). Point estimate clears the 3D cost hurdle (−2.196% vs.
  1.799%/yr, 17.990 flips/yr); the CI-bound test does not (3D annualized CI
  `[−4.087%, −0.367%]`, near-zero edge −0.367% < 1.799%) — and under 4D the point
  estimate no longer clears either (−1.353%), with the CI now spanning zero (an
  automatic fail there too, under the corrected rule above).
- **lb200 → Tier 4.** 3D CI already touches zero (`ci_high = +0.000048`); 4D CI clearly
  spans zero. Under the corrected cost-test rule, the CI-bound test is an unambiguous
  fail at both 3D and 4D (was previously miscategorized as passing under 4D — see the
  definitional-gap correction above); the point estimate technically clears its own
  hurdle (−2.578%/−1.257% vs. a 0.779%/yr hurdle, only 7.785 flips/yr — the lowest
  turnover of the three, which is doing most of the work here) but the CI test is what
  the tier hinges on. Also the lookback with the worst row loss (51.9% → 74.9%) and
  heaviest all-above skew (84.5%) of the three — the weakest statistically and the most
  selection-exposed, consistently with each other.

**Standing caveat on the lb20/lb50 Tier-3 pair:** unlike M4's SMA20 facets at the same
nominal tier, these carry an open selection-mechanism question (the all-above-skewed row
loss) that has not been ruled out as a contributor to the observed sign, independent of
whatever real conditioning effect (if any) exists. Treat this tier as less settled than
a typical Tier-3 call until that's addressed (e.g. once a broader universe makes decile-
level C2 matching viable — see the inherited "C2 note" above).

**(2026-09-09 update: this caveat originally also carried the "C1 > C0 hump is
unexplained" uncertainty. That's now resolved — see "Waterfall re-rendered with
pooled_delta as C0" above — the hump was purely an estimator-scale artifact, not a
market phenomenon, at both lb20 and lb50. The selection-mechanism concern above is the
only one that remains for this pair.)**

**Run-length secondary layer (the "does age matter" sub-question):** no credible
finding. Every lookback/direction's 1–5→6–21→22–63→64+ sequence zigzags in sign with no
smooth progression (DESIGN §6.7's plateau rule). The one cell whose CI excludes zero
(lb50 above / 6-21) has opposite-signed, non-significant neighbors on both sides — a
lone-pixel failure of the plateau rule, not a finding. Logged to `EXPERIMENTS.csv`
(`run_length_all_lookbacks` row).
## M11 — Cross-sectional formulation (2026-09-09)

**Module / track:** M11, Track B (DESIGN.md §8, M11).

**Promoted from:** not a Track A candidate — selected as the next minimal-core module
(DESIGN §12's list, `docs/backlog.md`) over M2/M5/M6.2 specifically because its natural
control design (per-date cross-sectional matching, structural) sidesteps the row-loss
mechanism that M1 hit hard (38–77% row loss under C2's stratify-and-drop design,
skewed toward one stratum type, still an open item in `docs/backlog.md`). M2 would
compound that same mechanism on a higher-cardinality state (`stack_perm`); M6.2 stacks
further dimensions on top of it and assumes M5 already exists; M5 needs new
event/control infrastructure and is more exposed to the §6.9 sample floor. M11 needs
none of that — reusing `stats/controls.py::cross_sectional_bucket` (already built and
used by M4) rather than `stats/controls.py::c2_eligible_mask`.

**2026-09-09 finding that reshaped this entry's hypothesis, found while resolving the
mismatch below.** `modules/distance_from_ma.py::decile_table` buckets via
`cross_sectional_bucket`, which is `pd.qcut` computed **per date**
(`stats/controls.py`, lines 111-113) — M4's "absolute-threshold" distance deciles were
already cross-sectional, not absolute. DESIGN's literal M11 hypothesis ("relative rank
beats absolute threshold") therefore has no true absolute baseline on record to compare
against; M4's Tier-3, cost-failing `dist_pct_sma_20` result already substantially *is*
the cross-sectional-rank answer, reported as decile-bucket-mean-delta rather than
Spearman IC. Building a genuine "absolute" baseline (e.g. a fixed, non-date-relative
distance threshold) is out of scope for this entry — it would be new methodology
requiring its own design pass, not a same-day resolution.

**Hypothesis (revised from DESIGN's literal comparative framing, for the reason
above):** Cross-sectional rank of an MA-state distance feature carries forward-return
information beyond zero, after cost. The DESIGN-motivated "beats absolute" question
survives only as a secondary, non-kill-triggering readout: the primary cell's
long-short spread is reported alongside M4's already-published `dist_pct_sma_20`
decile-bucket result (same feature, lookback, and horizon) as a narrower comparison —
does continuous-rank construction with sector/vol-neutralization do any better than
M4's decile-bucket, C2-tercile-matched construction, which already failed cost. This is
not the general relative-vs-absolute claim DESIGN assumed was testable; it's what's
actually decidable given M4 already ran the cross-sectional version.

**What M11 still buys over M4, said plainly, now that the comparative framing is
gone:**
1. **Continuous rank-IC vs. discrete deciles.** M4 collapses the cross-section to 10
   buckets and reports only the top-minus-bottom spread; M11's Spearman IC uses every
   ticker's rank position, not just the two extreme deciles, and gives an IC-decay curve
   across horizons that a 21d-only decile spread can't.
2. **Sector/vol/momentum neutralization — corrected 2026-09-10, was wrong.** This item
   originally claimed the neutralized layer was "structurally different" from M4's C2.
   **It isn't, for the cells both modules tested at 21d.** Traced at the code level,
   not inferred from matching numbers: after the 2026-09-09 code-review fix restored
   `mom_tercile` to `NEUTRALIZATION_MATCH_COLS`, M11's neutralization match-column set
   became identical to M4's `C2_MATCH_COLS` (`{sector, vol_tercile, mom_tercile}` both
   sides). Both call `stats/inference.py::block_bootstrap_spread` with the same decile
   construction (same feature, same 10-bucket cross-sectional `qcut`, same row
   population), same match columns, same value column (`fwd_ret_21`), same panel, same
   `block_length=42`/`n_boot=500`/`ci=0.90`/`seed=0`. `block_bootstrap_spread` is
   deterministic given identical arguments, so **for `dist_pct`/`dist_atr`/`dist_z`
   `_sma_20` and `dist_pct_sma_50`, M11's neutralized spread recomputes M4's own C2
   spread exactly** (verified to six decimals against `EXPERIMENTS.csv`'s M4 rows).
   **The fix was correct — this identity is its consequence, not a defect in the fix
   or a sign it should be reverted.** It means this specific sub-statistic is not
   independent evidence for those four cells; see `STATUS.md`'s non-independence note.
   What M11 does contribute independently, on this axis: the rank-IC statistic itself
   (not computed by M4 at all), the zero-row-loss C1 layer (item 3 below), and the
   `h5`/`h63` horizons (item 4 below) — M4 never tested a non-21d horizon, so the
   neutralized-spread identity above does not extend to those cells.
3. **Full C1-eligible-sample retention.** M4/M1's C2 layer is the one that loses
   38–77% of rows (M1) to stratum-eligibility. M11's primary (C1) layer runs on every
   row with a defined feature and forward return — no stratify-and-drop step at all.
4. **Horizon term structure.** M4 tested 21d only and explicitly deferred the full
   term structure (2026-09-08 addendum). M11's grid includes 5d and 63d on the primary
   lookback, folding that deferred follow-up in rather than leaving it open again.

None of these four is "relative beats absolute" — that framing is gone. They're methods
and coverage M4 didn't have, tested on the same feature M4 already found Tier-3 and
cost-failing. If M11 doesn't survive its own kill criterion either, the honest read is
"two different construction methods on the same underlying signal both say no," which is
a stronger negative than either alone.

**Independence check (done now, before grid finalization — same discipline M1 applied
to above/below):** per-date cross-sectional Spearman correlation between the three
SMA20 distance normalisations, measured off the rebuilt panel (1,231,698 rows, 408
tickers, 2010-01-04 → 2021-12-31):

| pair | median per-date Spearman | 5th–95th pct | n dates |
|---|---|---|---|
| `dist_pct_sma_20` vs `dist_atr_sma_20` | 0.977 | [0.908, 0.990] | 3,001 |
| `dist_pct_sma_20` vs `dist_z_sma_20` | 0.938 | [0.850, 0.964] | 2,750 |
| `dist_atr_sma_20` vs `dist_z_sma_20` | 0.952 | [0.908, 0.973] | 2,750 |

Not exact algebraic mirrors (unlike M1's above/below), but correlated enough that the
three normalisations are not independent tests. `dist_pct` is the pre-committed primary
normalisation; `dist_atr`/`dist_z` at the same lookback are reported as non-independent
companion readouts on the primary cell, excluded from `N_tests`.

**This slice's scope:**
- Features: `dist_pct` at SMA{20, 50, 200} — reusing `features/distance.py` output
  already in the panel, no new feature build. `dist_atr`/`dist_z` at SMA20 reported as
  companions only (see independence check above).
- Event definition: per-date cross-sectional decile of the already-lagged distance
  feature, via `stats/controls.py::cross_sectional_bucket` (reused from M4, not
  reimplemented) plus continuous Spearman rank-IC (feature rank vs. forward-return rank,
  per date).
- Horizons: 21 trading days (primary, matches M4 for comparability) plus 5 and 63 days
  on the primary lookback only — the term-structure follow-up DESIGN's own 2026-09-08
  M4 addendum flagged as the motivated next step, folded in here rather than deferred
  again.
- Universe: the same 408 S&P 500 constituents, dev window 2010-01-01 → 2021-12-31 (U1
  tier), verified against the freshly rebuilt panel (see this session's rebuild-diff:
  empty diff against the pre-rebuild cache on row count, NA counts, and every feature
  column).
- Controls: **C1 by construction** (per-date cross-sectional ranking is already
  date-matched — zero additional row loss) as the primary read; **sector-, vol-, and
  momentum-neutral rank** (matched within `sector`/`realized_vol_63` tercile/`mom_12_1`
  tercile per date, reusing the same tercile machinery from M1/M4's C2 — all three, not
  just sector/vol) as the C2-equivalent robustness layer, applied to every cell as a
  control-tier variant, not a separate test — same logic as C0/C1/C2 being one
  hypothesis at three strictness levels. **Momentum matching is load-bearing, not
  optional:** DESIGN §6.1 calls this exact matching "the one that separates real MA
  information from momentum re-encoding," the confound this whole study is organised
  around (§7.1) — a neutralization layer without it isn't the robustness check this
  entry claims. (Found missing during code review, 2026-09-09, and fixed before any
  interpretation of these numbers — `modules/cross_sectional.py`'s first implementation
  only matched sector/vol; `EXPERIMENTS.csv`'s M11 rows reflect the corrected,
  momentum-inclusive run.) Neither control layer drops rows the way M1/M4's
  stratify-and-drop C2 does (DESIGN §6.1's scale-comparability note doesn't apply here —
  there is no dilution-prone pooled C0 in this design, since the primary statistic is
  already a per-date contrast).

**Grid size (N_tests contribution): 5** — 1 primary cell (`dist_pct_sma_20`, 21d) + 4
secondary cells (`dist_pct_sma_50` 21d, `dist_pct_sma_200` 21d, `dist_pct_sma_20` at 5d
and 63d). `dist_atr_sma_20`/`dist_z_sma_20` at 21d are companion readouts, not counted,
per the independence check above.

**Multiple-comparison correction, stated concretely:**
- **The primary-cell kill/no-kill verdict is a single pre-registered test and needs no
  correction to be decisive** — same treatment M1 gave its own primary cells (6 state
  cells, kill evaluated only over those, run-length cells provisional). One test, one
  answer, standing on its own.
- **The 4 secondary cells are provisional pending FDR**, exactly the status M1 gave its
  run-length cells: reported for the lookback/horizon picture, not treated as confirmed
  findings on their own.
- No FDR correction is *run* at this slice — DESIGN §6.6's denominator accumulates
  across the whole pre-registered grid, not per module (same note M4 and M1 both
  logged) — but the procedure to apply, when that whole-study accounting happens, is
  fixed now: **Benjamini–Hochberg at q=0.10** over the accumulated `N_tests` count,
  consistent with DESIGN §6.6's stated primary screen. Each module's own declared
  contribution stands as written in its own entry (M4: 90 bucket-level cells; M1: 30
  cells, 6 of which are primary/non-mirrored; M11: 5) — summing these into one running
  total is exactly the kind of arithmetic that should happen once, deliberately, at the
  whole-grid accounting pass, not be asserted piecemeal across entries where a
  transcription slip could silently corrupt the eventual correction.

**Primary vs. secondary cells:** `dist_pct_sma_20` at 21d is primary — closest
continuity with M4's strongest surviving (Tier-3) facet, chosen for that reason, **not**
for the friendliest cost profile (SMA200's hurdle is lower — see below — but SMA200
carries the standing cross-module anomaly flag from M1/M4, logged above in this file's
M1 entry; a cost-driven "survival" there would need extra scrutiny, not extra credit).
The kill criterion is evaluated only on the primary cell. Secondary cells inform the
lookback/horizon picture but do not individually trigger kill, same treatment M1 gave
its run-length cells.

**Cost — measured off the panel, not assumed, before any IC is computed.** Used
`stats/costs.py::signals_per_year`/`cost_hurdle` (built for M1, reused here) on
decile-membership flips per leg, daily rebalance (matching M4's own daily
`cross_sectional_bucket` cadence), off the freshly rebuilt panel:

| feature | top-decile flips/ticker-yr | bottom-decile flips/ticker-yr | combined | hurdle @ 10bps/rt |
|---|---|---|---|---|
| `dist_pct_sma_20` (primary) | 12.536 | 12.111 | 24.646 | **2.465%/yr** |
| `dist_z_sma_20` (companion) | 13.288 | 12.885 | 26.173 | 2.617%/yr |
| `dist_pct_sma_50` | 8.092 | 7.752 | 15.845 | 1.584%/yr |
| `dist_pct_sma_200` | 4.093 | 3.828 | 7.921 | 0.792%/yr |

**Flagged discrepancy, not resolved here:** M4's own prose cites "~25 decile-entries/
ticker/year per leg (~50 round trips/year combined)" for this same feature, computed ad
hoc before `costs.py` existed (that module was built for M1, after M4 shipped). The
measured combined figure here (24.646) is roughly half M4's stated ~50. Used here
because it's reproducible off the verified-identical current panel via the repo's
standard tool, not because it's more favorable — it lowers the bar M4's own number
implied, which cuts against convenience. Worth a follow-up re-check of M4's figure
against `costs.py` directly; not blocking this entry.

**Kill criterion, pre-committed before any IC is computed:** the primary cell
(`dist_pct_sma_20`, 21d) survives only if **both**:
1. The date-clustered, block-bootstrapped 90% CI (block length 42, same convention as
   M1/M4) on mean Spearman rank-IC excludes zero **and** clears a 0.02 floor (a
   conventional weak-but-tradeable IC threshold) at its near-zero-favorable edge.
2. The long-short decile spread's 90% CI excludes zero **and** clears the 2.465%/yr
   hurdle at its near-zero-favorable edge, under the corrected `ci_clears_cost` rule
   (spanning zero is an automatic fail — the same rule found and fixed during M1).

Failing either test — kill: report cross-sectional rank as **not worth the added
machinery over M4's existing absolute-threshold-shaped result**, log to
`EXPERIMENTS.csv`, and treat M1/M4's existing results as the standing formulation.

**Secondary, non-kill-triggering comparison:** report the primary cell's long-short
spread alongside M4's published `dist_pct_sma_20` decile-bucket result (same feature,
lookback, horizon) — does continuous-rank + neutralization construction do any better
than M4's decile-bucket + C2-tercile construction, which already failed cost. Descriptive
only; does not affect the kill/tier call above.

**Minimum sample threshold (DESIGN §6.9):** no bucket/cell reported below 200 events
across ≥30 distinct dates and ≥30 distinct tickers, same as M1/M4.

**Plateau check (DESIGN §6.7):** the three lookbacks (20/50/200) compared for
consistency of sign/pattern, not treated as independent single points; the three
horizons (5/21/63) on the primary lookback checked for a smooth, not cliff-edged, IC
decay.

**Effective N:** reported as distinct event dates alongside raw row count, per cell,
same invariant as every prior module.

**Panel provenance for this entry:** rebuilt from current `main` (commit `75e42ce`,
`build-panel --universe sp500`) this session and diffed against the pre-rebuild cache —
empty diff on row count, column set, NA counts per column, and value equality on every
column including `above_*`, `run_length_bucket_*`, `stacked_sma`, `stacked_ema`. The
`state_run_id` internal-NaN-gap guard added in `75e42ce` is confirmed inert on this
panel by the rebuild, not by code-reading alone.

### Result and feasibility addendum (2026-09-10)

**The kill criterion bound as written, and the verdict stands.** Applied literally: the
primary cell's IC CI is `[-0.032670, -0.001304]` — excludes zero, but the near-zero edge
(`-0.001304`) is far short of the 0.02 floor. Test 1 fails on the floor sub-condition
alone; per "failing either test — kill," the primary cell is killed as a construction,
independent of the cost sub-test (which also fails: the spread's near-zero edge, `-0.51%`
annualized, misses the 2.463%/yr hurdle). **Cross-sectional rank, as built here
(continuous rank-IC + sector/vol/momentum-neutralized spread), is not worth the added
machinery over M4's existing decile-bucket result** — the literal, pre-committed
consequence of this module's kill criterion.

**The floor was unreachable at this sample size — a finding about the pre-registration,
not a reason it was relaxed.** Computed directly (not estimated) from the actual
block-bootstrap output (block_length=42, 500 draws, seed 0, ~71 effective non-overlapping
blocks at `n_dates=2980`): holding the primary cell's realized near-side CI half-width
fixed (0.017662), the near-zero edge would have needed a point-estimate IC of **-0.0377**
to clear 0.02. The largest `|IC|` this entire 7-cell M11 grid produced, companions
included, is **0.020977** (`dist_z_sma_20_h21`) — the required value is **1.8×** the
largest effect this grid ever found. Retroactively applying the same 0.02 near-edge bar
to M1's and M4's existing Tier-3 cells (a diagnostic only, not a re-tiering — see
`STATUS.md`): **zero of the five clear it either** (their near-edges run 0.0003–0.0014).
The 0.02 floor, as a bare number, was not calibrated against what any module in this
study — including M11's own grid — has actually produced. This does not change the
verdict: the criterion binds as written, and the primary cell still kills as a
construction. It does mean the failure is a property of the threshold chosen at
pre-registration time, not evidence that no effect exists — see DESIGN §9.2's
2026-09-10 addendum for how kill and tier are now recorded as separate axes as a
result (`decisive_test_status` alongside tier, not folded into it). Under that rule,
the primary cell's tier is decided by DESIGN §9.2's general rubric like any other cell,
independent of this kill outcome — see `STATUS.md`/`EXPERIMENTS.csv` for the assigned
tier.

**Forward rule for future floors:** a magnitude floor (an IC threshold, an economic-
significance floor, any bare-number bar) must be checked against the realized CI
half-width its own sample size will produce — or at minimum against the largest
comparable effect size already on record in this study — **before** it's written into a
pre-registration, not discovered to be reachable or not only after the bootstrap runs.
A round number chosen for being conventional (0.02 as "a conventional weak-but-tradeable
IC threshold," this entry's own words) is not the same thing as a number calibrated to
what this study's sample size can actually resolve.

### Correction: wrong annualization factor on the 5d/63d secondary cells (2026-09-10)

**The error.** `dist_pct_sma_20_h5`'s gross edge was annualized with the same ×12
(252/21) factor used for every 21d cell in this module, instead of the horizon-correct
×50.4 (252/5). Found while drafting the Tier 1/2/3 register, by re-deriving the number
rather than re-auditing on suspicion — not caught earlier because every other M11 cell
shares the 21d horizon and the bug only manifests where that assumption is wrong.

**Corrected numbers.** Near-zero CI edge: **−3.45%/yr** (was reported as −0.82%/yr).
Hurdle: **2.466%/yr, unchanged** — verified, not assumed, that the turnover/hurdle
computation is horizon-independent: `decile_turnover_hurdle` measures how often
`dist_pct_sma_20`'s own decile membership changes day to day, a property of the
feature's daily rebalancing, not of which `fwd_ret_h` column is being tested against
it (the decile assignment never reads `horizon` at all — only the return column does).
Only the numerator needed the fix. **This moves the cell from failing its CI-based
cost test to passing it** — CI excludes zero and the near edge now clears the hurdle,
where the uncorrected number showed a miss.

`dist_pct_sma_20_h63` was also affected in an ephemeral, never-recorded comparison
made in conversation — its actual stored record (`EXPERIMENTS.csv`: Tier 4,
`no_effect`) was always driven by both CI's spanning zero, never by a cost comparison.
Nothing to correct there. M1 and M4 never tested a non-21d horizon at all (both
hardcode `HORIZON = 21` in code and in their own pre-registration text) — the bug
cannot have manifested in either, and does not appear anywhere in already-merged work.

**Tier is unchanged — say this explicitly so it isn't read as grounds to promote the
cell.** Tier 3 here is capped by missing FDR/holdout infrastructure (DESIGN §9.2), not
by cost — the same ceiling every other Tier-3 cell in this study sits under, M1 and M4
included. Clearing the cost test moves `dist_pct_sma_20_h5` from "real effect, fails
cost" to "real effect, clears cost" within Tier 3; it does not, by itself, clear the
FDR/holdout bar Tier 2 requires. `EXPERIMENTS.csv`'s `tier` column stays `3`; only
`outcome` moves, from `weak_not_cost_viable` to `weak_cost_viable`.

**Necessary context, not a weakening of the correction: this is the shape a
short-term-reversal generator would produce.** `dist_pct_sma_20` is mechanically close
to "how far the stock has recently risen" — the same momentum-collinearity concern
already live for M11's primary cell (see the momentum-confound discussion in this
session's own Q&A, never resolved by adding `mom_1_0` to the neutralization layer).
That concern is **more** live at a 5-day forward horizon, not less: a short-term
reversal effect is strongest and most detectable at the shortest forward window and
decays as the window lengthens, which is exactly the term-structure shape observed
here — the one secondary cell whose cost test passes is the shortest-horizon one,
while the 21d and 63d cells (where a pure reversal effect would have more time to
dissipate) do not clear cost (21d) or don't even clear CI-excludes-zero (63d). A
genuine MA-distance effect has no particular reason to concentrate at the shortest
horizon; a reversal effect does. This doesn't change the correction above — the number
is fixed regardless of what's generating it — but it means the corrected result should
not be read as stronger evidence for cross-sectional MA-state information than it is;
if anything, its position in the term structure argues for reversal over MA-distance
as the more likely generator, unresolved and unexplored here per this module's own
scope.

### Post-hoc tier change: `dist_pct_sma_50_h21`, Tier 3 → Tier 4 (2026-09-10)

Found while drafting the Tier 1/2/3 register, checking every M11 cell's IC-CI,
C1-spread-CI, and neutralized-spread-CI for mutual agreement (previously only IC vs.
C1-spread had been checked). `dist_pct_sma_50_h21`'s C1-layer CI excludes zero
(`[-0.010182, -0.000127]`) but its neutralized-layer CI spans zero
(`[-0.006533, +0.000326]`) — the two control tiers of the same spread statistic
disagree on whether the effect is distinguishable from zero at all.

This is not the divergence DESIGN §9.2's original open-gap note anticipated (that note
is about *different statistics* — IC vs. spread — disagreeing at the *same* control
tier; this is the *same* statistic disagreeing across *different* control tiers).
Resolved as its own case, DESIGN §9.2, 2026-09-10: the stronger control tier is
authoritative when the two disagree, the same precedent DESIGN §6.1 already sets for
preferring C2 over C1 generally. Applying that rule here: `dist_pct_sma_50_h21` tiers
on its neutralized-layer reading (CI spans zero) rather than its C1 reading (CI
excludes zero) — **Tier 3 → Tier 4, outcome `weak_not_cost_viable` →
`no_effect`.** `EXPERIMENTS.csv` and `STATUS.md` updated to match.

---

## §7.5 — Level effects vs. trend effects (the placebo test) (2026-09-12)

**Module / track:** Not a numbered M-module — DESIGN §7.5, Track B. Pre-registered here
with its own hypothesis/kill-criterion/control-tier statement, same discipline as every
numbered module, per this file's own convention.

**Promoted from:** not a Track A candidate — DESIGN's own words: "the most elegant test
in this whole document... cheap to run and the answer is interesting either way."
Directly motivated by two things already on record: M11's `dist_pct_sma_20` surviving
to a cost-viable Tier-3-pending-FDR reading at the 5-day horizon (2026-09-10 cost
correction, this file's M11 entry), and the cross-module SMA200 watch (`STATUS.md`,
trigger fired 3× — M4's `dist_z_sma_200`, M1's lb200, M11's `dist_pct_sma_200_h21` —
not yet investigated). This test is the direct way to ask whether any of that is a
genuine watched-level effect or purely a trend-length proxy, before spending more
modules' worth of grid on SMA200/SMA50/EMA-family features that might all be measuring
the same non-thing.

**Hypothesis (skeptical, per DESIGN):** the apparent distance/state effects already
found at SMA200, SMA50, and (folklore) the 21-EMA are indistinguishable from the
identical analysis run on statistically near-identical, unwatched neighbor lookbacks —
i.e., "200" is a stand-in for "~10-month trend," not a reflexive level. Genuinely
falsifiable in either direction; DESIGN frames both outcomes as informative, not just
the null.

**Scope (three independent focal/neighborhood groups, one horizon, one universe —
a first slice, matching M4/M1's own precedent of not running the full DESIGN method in
one pass):**

- **Group A (SMA200):** focal SMA200 vs. neighbors SMA{187, 193, 207, 213}.
- **Group B (SMA50):** focal SMA50 vs. neighbors SMA{47, 53}.
- **Group C (21-EMA):** focal EMA21 vs. neighbors EMA{19, 23} — note the panel's
  cached EMA lookback is currently 20 (`features/ma.py::LOOKBACKS = (20, 50, 200)`),
  not 21; the folklore lookback DESIGN names is 21, so this group needs its own focal
  MA built, not just its neighbors.
- **New build required:** none of these 8 neighbor lookbacks (187/193/207/213/47/53/
  19/23) or the EMA21 focal are in the cached panel's default `LOOKBACKS`. They're
  computed via `features/ma.py::compute_ma` (already accepts arbitrary lookback, not
  restricted to the cached tuple) and must be routed through `features/panel.py`'s
  existing one-bar-lag application rather than a hand-rolled shift (invariant #2) —
  this is new plumbing (a small script/module, not a new lag implementation) and gets
  a look-ahead shift test before use, same as the cached panel's own hygiene tests.
- **Primary statistic:** `dist_pct` decile spread (top-decile-minus-bottom-decile,
  `stats/inference.py::block_bootstrap_spread` — reused unchanged from M4/M11 so the
  comparison is apples-to-apples) on `fwd_ret_21`.
- **Universe/window:** unchanged — the 408 S&P 500 constituents (as of 2021-12-31),
  U1, dev window 2010-01-01 → 2021-12-31.
- **Horizon:** 21 trading days only, same precedent as M4/M1/M11's first slices.

**Grid size (N_tests contribution):** the unit of inference is the **group**, not the
lookback — **3 group-level comparisons** (A, B, C), each internally built from its
focal MA and 2–4 neighbors. The 11 individual lookback cells (3 focal + 8 neighbor) are
not 11 independent tests; only the 3 group-level `diff_g` statistics below count toward
`N_tests`.

**Kill criterion, per group, stated before running (both directions are a real
result, not just the null — logged either way):**
- For each neighbor `n` in a group, compute `diff_g,n = spread(focal) − spread(n)`
  using the same block-bootstrap machinery (identical block length/seed convention as
  M1/M4/M11) so `diff_g,n` gets its own CI, not a naive difference of two point
  estimates.
- **Level effect confirmed for group `g`** iff the focal lookback's own CI excludes
  zero **and** `diff_g,n`'s CI excludes zero for **every** neighbor `n` in the group —
  the focal MA is a distinguishable outlier from its whole matched neighborhood, not
  merely individually significant.
- **Level effect killed (folklore confirmed) for group `g`** iff `diff_g,n`'s CI
  includes zero for **any** neighbor `n` — the focal MA is statistically
  indistinguishable from at least one untraded neighbor, so "it's just a trend proxy"
  cannot be ruled out for that group.
- No module-level kill across all three groups is declared — each group is scored
  independently (e.g. SMA200 could confirm while SMA50 kills; both are reported, per
  DESIGN's own "the answer is interesting either way").

**Control tier and why:** C1 is the default read (DESIGN §6.1). **C2 (date +
momentum-tercile + vol-tercile + sector matched, `mom_12_1`/`realized_vol_63`, unchanged
from M1/M4/M11) is the tier `diff_g,n` is evaluated on** — a raw momentum confound is
exactly what this test exists to rule out (a higher-momentum stock sits further from
*any* ~200-day-ish MA; without matching on momentum, "focal beats its neighbors" could
just mean "the stocks currently far from SMA200 happen to be higher-momentum than the
stocks far from SMA193," not a level effect at all).

**Cost annotation:** not applicable to the confirm/kill call itself — this test asks a
mechanism question, not a tradeable-edge question. If any group is confirmed, a cost
annotation is still required before that finding is stated as a claim (invariant #8),
using `stats/costs.py`'s existing turnover/hurdle machinery, same 10bps/round-trip U1
convention as every other module.

**Plateau check (DESIGN §6.7):** this test *is*, in effect, the study's most direct
application of the plateau rule — "the neighborhood performs identically" is the
plateau signature DESIGN already asks every lookback claim to survive. Report it as
such rather than as a separate check.

**Effective N:** reported as distinct event dates alongside raw row count, per
lookback cell, standard invariant.

**Minimum sample threshold:** DESIGN §6.9's numbers (200 events, ≥30 distinct dates,
≥30 distinct tickers) applied per lookback cell, unchanged from M4/M1/M11 — below-
threshold cells flagged, not dropped.

---

## M2 — Stack states and Minervini ablation (2026-09-12)

**Module / track:** M2, Track B (DESIGN.md §8, M2, lines 744–751).

**Promoted from:** not a Track A candidate — DESIGN's own words: "this is the highest
expected-value module in the doc," kill criterion "none — the ablation is informative
regardless of outcome." `STATUS.md`/`docs/backlog.md`'s designated next-up module,
alongside M5 and M6.2.

**Hypothesis:**
(a) Multi-MA stack alignment (`stack_perm` over SMA{20, 50, 150, 200}) carries forward-
return information beyond what a single MA's above/below state already showed in M1.
(b) Decomposing Minervini's 8-criterion Trend Template by ablation shows criteria 6–8
(≥25–30% above the 52-week low, within 25% of the 52-week high, RS rank ≥ 70 — pure
momentum proxies) carry most of the attributable signal; the MA-stack-specific criteria
(1, 2, 4, 5, and criterion 3, which DESIGN's own M6.0 identity shows decodes exactly to
"sustained 200-day momentum," not trend quality) contribute modestly if at all.

**New feature-build required (checked before writing this — none of this exists yet):**
`features/ma.py::LOOKBACKS = (20, 50, 200)` has no 150. `features/context.py`'s own
docstring explicitly flags `dist_from_52w_high/low` and the full `rs_rank` as not yet
built. Concretely, this slice needs:
1. **SMA150** — via `features/ma.py::compute_ma` (already accepts arbitrary lookback),
   routed through `features/panel.py`'s existing lag, not hand-rolled (invariant #2).
2. **`dist_from_52w_high`, `dist_from_52w_low`** — rolling 252-trading-day max/min of
   `close`, new. NaN for a ticker's first 252 days, not zero/false (invariant #9) —
   needs its own test asserting NA across that warmup region, same shape as the
   `above_sma_200` fix CLAUDE.md's invariant #9 already documents.
3. **`rs_rank`** — reuse, not rebuild, per this repo's own reuse pointer
   (`src/signals/relative_strength`, `store.read_relative_strength`, `comparison=
   'stock_vs_market'`, `rs_rating` column already an IBD-style 0–99ish rating per
   ticker/date). Join onto the panel by (ticker, date). **Before trusting it inside a
   one-bar-lag pipeline, confirm its own point-in-time discipline directly** (it was
   built for a different study, for a different purpose) rather than assume it's
   already lag-safe.
4. **"200-day rising for ≥1 month"** — per DESIGN §6.0's identity
   (`SMAₙ(t) − SMAₙ(t−1) = (Cₜ − Cₜ₋ₙ)/n`), this is exactly `close_t > close_{t-200}`
   sustained for 21 consecutive trading days. Implement via that identity (or the sign
   of `slope_log_21(SMA200)`), not as a fresh "is the MA increasing" computation — it's
   the same number M6.0 already named, not a new question.

**The 8 Trend Template criteria** (standard Minervini formulation; DESIGN itself only
restates 3 and 6–8 verbatim, criteria 1/2/4/5 are the standard MA-stack conditions per
DESIGN line 31's "50/150/200-day SMA stack"):
1. Price > SMA150 and price > SMA200
2. SMA150 > SMA200
3. SMA200 rising for ≥1 month (§6.0 identity, above)
4. SMA50 > SMA150 and SMA50 > SMA200
5. Price > SMA50
6. Price ≥ 30% above the 52-week low (the more common formulation — stated precisely
   here so it isn't left ambiguous at analysis time)
7. Price within 25% of the 52-week high
8. RS rank ≥ 70

**Method:**
(a) **`stack_perm`** — a new categorical feature over the 4-way ordering of
{SMA20, SMA50, SMA150, SMA200} vs. price, built from the existing lagged `above_sma_k`
boolean columns already in the panel (reused inputs, new combination logic — this is
not `features/state.py`, which is run-length-only). C0/C1/C2 deltas on `fwd_ret_21` per
non-empty permutation category vs. baseline, same approach as M1.
(b) **Full 2⁸ = 256-subset ablation** of the 8 boolean criteria (each built lagged,
invariant #9-compliant) on `fwd_ret_21`, C1/C2 controls. Computationally cheap once the
8 columns exist — vectorized boolean combination, no per-ticker loop, float32, per
CLAUDE.md's style rules. Decomposed via a linear/Shapley-style attribution per
criterion, as DESIGN specifies, **not** read as 256 individual hypothesis tests.

**Horizon:** 21 trading days only. **Universe/window:** unchanged, U1, 408 S&P 500
constituents, dev window 2010-01-01 → 2021-12-31.

**Grid size (N_tests contribution):** part (b)'s 256 subsets are attribution inputs,
not 256 independent tests — DESIGN's own "kill: none, informative regardless" framing
treats the ablation as a decomposition, not a battery of hypotheses. The quantities
that matter for `N_tests` are the **8 per-criterion attribution coefficients**
(or Shapley values), logged as this module's actual grid contribution for part (b).
Part (a)'s `stack_perm` primary comparison (see kill criterion below) contributes a
small number of pre-registered primary cells — "fully-bullish stack" and
"fully-bearish stack" vs. baseline, 2 cells — with the remaining non-empty permutation
categories reported as secondary/descriptive, same primary-vs-secondary split M1 used
for its run-length layer.

**Kill criterion:**
- **Part (b) (the ablation itself): none, by DESIGN's own explicit statement.** The
  attribution is informative regardless of which criteria carry the weight — this is
  not a construction that gets declared dead.
- **Part (a) (`stack_perm` as an independent signal) does need one**, since "the stack
  carries information beyond a single MA" is a real, falsifiable claim. Same CI-based
  rule M1 established (2026-09-09 correction: spans-zero auto-fails, no magnitude
  comparison is meaningful once "no effect" is inside the interval; otherwise
  `max(|ci_low|, |ci_high|) < 0.10%` fails the economic-significance floor): applied to
  the 2 primary cells (fully-bullish, fully-bearish stack) against a control matched on
  M1's own single-best-lookback state, not just C2's generic momentum/vol/sector match
  — the specific question is whether the *full stack* adds anything over what M1
  already found for individual lookbacks. If both primary cells fail, **"the stack adds
  nothing over single-MA state"** is the module-level verdict for part (a) only; part
  (b)'s attribution result stands regardless.

**Control tier and why:** C1 default, **C2 is the tier the part-(a) kill criterion is
evaluated on** (DESIGN §6.1 precedent, unchanged `mom_12_1`/`realized_vol_63`/`sector`
match columns from M1/M4/M11). Part (b)'s ablation reports C1/C2 deltas per subset for
completeness but, per DESIGN, isn't gated on either.

**Cost convention:** unchanged 10bps/round-trip, U1 (`stats/costs.py`). Turnover
mechanism for part (a) is stack-category-change count, measured off the built panel,
not assumed — same precedent as M1's state-flip turnover.

**Minimum sample threshold:** DESIGN §6.9's numbers (200 events, ≥30 dates, ≥30
tickers), applied per stack-permutation category and per ablation subset. Many of the
256 subsets will be near-empty by construction (e.g. RS rank ≥ 70 co-occurring with
price below SMA200 is rare) — flagged, not dropped, same as M4/M1/M11.

**Plateau check (DESIGN §6.7):** not a lookback-neighborhood test here — applied
instead as directional consistency: the "above SMA20 & above SMA50 & above SMA200"
stack category should agree in sign with M1's own per-lookback above-cells, not
contradict them. A contradiction would be a red flag for the new `stack_perm`
construction, not a finding.

**Effective N:** standard invariant, reported per stack category and per ablation
subset above the minimum-sample threshold.

**SMA200 watch, noted not folded in:** criterion 3 leans on SMA200 directly, and the
cross-module SMA200 watch (`STATUS.md`) has fired 3× without being investigated. This
module is a natural place to also run that audit as a side-check, but it is **not**
part of this pre-registered grid or its `N_tests` — if done, it's logged separately as
a Track A look in `EXPLORATION_LOG.md`, not folded into M2's own numbers.

### Wording correction (2026-09-13, found while implementing — not a scope change)

This entry's kill-criterion paragraph (above) describes part (a)'s rule as "the same
CI-based rule M1 established (2026-09-09 correction: spans-zero auto-fails... otherwise
`max(|ci_low|, |ci_high|) < 0.10%` fails)" — that conflates two different M1 rules.
M1's 2026-09-09 "spans-zero auto-fails" correction (this file's M1 entry, "Cost-test
definitional gap") was applied only to `stats/costs.py::ci_clears_cost`, the **cost**
test — not to M1's actual `evaluate_kill_criterion`
(`modules/baseline_state.py`), which was, from the start, exactly
`max(|ci_low|, |ci_high|) < 0.10%` with no separate spans-zero branch (verified against
the real code, not re-derived from memory): that formula already handles a
zero-spanning interval correctly on its own terms, since both endpoints are compared
regardless of sign — it just isn't the same mechanism as the cost-test fix. M2's
implementation (`modules/stack_minervini.py::evaluate_part_a_kill_criterion`) uses the
literal, unambiguous formula this same paragraph also states in the same sentence
(`max(|ci_low|, |ci_high|) < 0.10%`) — i.e. M1's actual rule. The parenthetical
attributing the spans-zero fix to the kill criterion is the error, corrected here; no
analysis behavior changed as a result (the formula run was always the correct one).

### Part (b) control-tier caveat (2026-09-13, found while implementing — logged, not silently applied)

This entry says part (b)'s ablation "reports C1/C2 deltas per subset for completeness."
As implemented, `ablation_subset_table` reports a C1 (date-matched) delta per subset,
not C2 — and `linear_attribution` (the 8-coefficient OLS readout this entry's `N_tests`
declaration is actually keyed to) has **no control at all**, not even date-stratified
C1 weighting: it's a single pooled OLS of `fwd_ret_21` on the 8 raw boolean criteria
across every eligible row, unweighted by date. This is consistent with DESIGN's own
framing of part (b) as descriptive attribution with "no CI, no kill criterion" — but
"no CI" was not meant to imply "no control at all," and the distinction matters for
reading the coefficients: an uncontrolled pooled regression can't distinguish a
criterion's own marginal contribution from "this criterion happened to be true more
often in dates/regimes that had higher returns for unrelated reasons" (exactly the
kind of confound C1's per-date matching exists to remove). Read the 8 coefficients'
signs and relative magnitudes as a first-pass attribution, not as a controlled
estimate — a date-stratified (or at minimum C1-weighted) version of the same
regression is the natural follow-up if this module's ablation result is ever promoted
past Track A description.

### Reversal-robustness addendum (pre-registered 2026-09-17, before running)

**Module / track:** M2, Track B. Promoted from `STATUS.md`'s own saturation-watch note
(2026-09-13): `stack_fully_bearish` is the one Tier-3 result in the study so far that
clears cost cleanly at every reading, but its C2 spec (`C2_MATCH_COLS` — momentum
tercile, vol tercile, sector) has no reversal control, and `STATUS.md` names the live
alternative explanation directly: "the sign pattern is exactly what uncontrolled
1-month reversal would produce." This addendum runs the check `STATUS.md` recommended
rather than leaving it open, using infrastructure that already exists
(`modules/baseline_state.py`'s own `C2_MATCH_COLS_WITH_REVERSAL` precedent, run against
M1's lb200 cell during that module's own diagnostic pass) — no new statistical
machinery, no new feature (`rev_tercile` is `mom_1_0`'s own tercile bucket, and
`mom_1_0` already exists in the panel, `features/context.py::mom_1_0`).

**Hypothesis:** `stack_fully_bearish`'s C2 delta on `fwd_ret_21` survives once the C2
match set additionally controls for the prior 21-day return tercile (`rev_tercile`) —
i.e. the effect is not merely a re-encoding of uncontrolled short-term reversal.
`stack_fully_bullish` is re-run alongside it for completeness (cheap, same code path)
but is not the subject of this addendum — it is already Tier 4 and this check cannot
promote it regardless of outcome.

**Method:** `modules/stack_minervini.py::primary_stack_table`, called with
`match_cols=C2_MATCH_COLS_WITH_REVERSAL` (`("mom_tercile", "vol_tercile", "sector",
"rev_tercile")`) instead of the module's default 3-column `C2_MATCH_COLS`. Same
C2-eligible restriction, same block-bootstrap CI machinery, same panel (U1, 408 S&P 500
constituents as of 2021-12-31, dev window 2010-01-01 → 2021-12-31) — only the match-column
list changes. `rev_tercile` computed exactly as `baseline_state.py`'s own robustness
column: `cross_sectional_bucket(working, "mom_1_0", n_buckets=3)`.

**Kill criterion:** identical rule to M2's own primary kill criterion
(`evaluate_part_a_kill_criterion`'s underlying test, same as M1's
`evaluate_kill_criterion`): `max(|ci_low|, |ci_high|) < 0.10%` on the 4-column C2 delta
→ killed under the reversal control (read as "reversal explains the effect, or it was
never distinguishable from noise once reversal is matched out"). A CI that still
excludes zero and clears the 0.10% floor is read as "survives reversal-matching" — not
by itself a tier promotion (Tier 3 stays capped by the missing FDR/holdout infra
regardless), but it resolves the specific confound question `STATUS.md` left open.

**Control tier and why:** C2, 4-column (`mom_tercile`, `vol_tercile`, `sector`,
`rev_tercile`) — the same tier M1 used for its own lb200 reversal diagnostic
(`PREREGISTRATION.md`'s M1 entry), applied here to M2's `stack_fully_bearish` cell for
the first time.

**Cost convention:** unchanged, not re-evaluated here — this addendum is about whether
the gross C2 delta survives a confound check, not a second cost pass. If the cell
survives, M2's already-logged cost numbers (`EXPERIMENTS.csv`) stand unchanged.

**Grid size (`N_tests` contribution):** 2 cells (bullish, bearish), same primary-cell
count as M2's own part (a) — this is a re-evaluation of an already-declared cell under
an alternative control, not a new hypothesis, so it does not add to the whole-grid
`N_tests` denominator beyond what M2 already declared (per this study's own convention
for a same-cell alternative-control diagnostic — M1's lb200 reversal check was treated
the same way, logged but not double-counted).

**Universe/window/horizon:** unchanged from M2's own entry above.

### Result (reversal-robustness addendum, 2026-09-17)

**`stack_fully_bearish` survives.** Default 3-column C2: `c2=+0.4675%`, CI
`[+0.1488%, +0.7762%]` (2026-09-13 row). With `rev_tercile` added to the match set:
`c2=+0.3188%`, CI `[+0.0444%, +0.5976%]` — n_events 39,759 → 31,297, n_dates 2,696 →
2,642 (standalone C2-eligible population, recomputed fresh here; not the same row set
as the 2026-09-13 row's *incremental-vs-M1* n_events=40,102). The point estimate
attenuates by roughly a third once short-term reversal is matched out, but the CI still
excludes zero and clears the 0.10% kill floor by a wide margin (edge 0.598%) —
**not killed**. Annualized at the same ×12 convention as the original row: point
≈+3.83%/yr, near edge ≈+0.53%/yr, far edge ≈+7.17%/yr, all still above the unchanged
0.2863%/yr cost hurdle — the cell still clears cost under the reversal-controlled
number, not just the original one.

**Reading:** uncontrolled 1-month reversal is a real, partial contributor to the gross
number (a third of the magnitude), but not the whole story — a residual bearish-stack
effect survives its removal. This resolves the specific confound `STATUS.md` flagged as
live ("the sign pattern is exactly what uncontrolled 1-month reversal would produce")
without resolving the module's actual tier cap: `stack_fully_bearish` stays **Tier 3**,
capped by the same two things as before (missing whole-grid FDR/holdout infrastructure;
DESIGN §7.3's survivorship cap on a weak/bearish-state bucket) — a reversal-robust
result does not by itself clear either cap. What it does change: the "is this even a
real stack effect, or entirely a reversal re-encoding" question from open to resolved
(no) — the remaining honest caveat is infrastructure, not confound.

**`stack_fully_bullish`** was re-run alongside (same script, no added cost) purely for
completeness: CI still spans zero under the reversal control, same as under the default
C2 — no new information, does not change its Tier 4 status.

**Logged:** `EXPERIMENTS.csv` (2 new rows, both dated 2026-09-17,
`stack_fully_bearish_h21_reversal_robustness` / `stack_fully_bullish_h21_reversal_robustness`);
`FINDINGS.md`'s `stack_fully_bearish` entry updated with this result in place of its
prior "live unresolved confound" framing.

---

## M5 — Touch / test / bounce behaviour (2026-09-17)

**Module / track:** M5, Track B (DESIGN.md §5). Last of the minimal-core list before
M6.2 (decision recorded in `STATUS.md`'s 2026-09-17 saturation-watch resolution:
continue to full completion rather than an early stop).

**Promoted from:** DESIGN §12's own minimal-core list, not a Track A candidate — same
status as M1/M2/M11, a pre-committed module rather than something surfaced by
exploration.

**Hypothesis (skeptical, per DESIGN's own framing):** MAs act as dynamic
support/resistance beyond what a generic, unwatched level at a similar location would
show — i.e., price is more likely to hold (bounce) at a real, widely-watched MA than
at a statistically near-identical synthetic level nearby. DESIGN's own explicit
warning shapes this entry's whole design: **you cannot select on "it bounced"** —
bounce/slice-through/chop are all outcomes of the *same* ex-ante event (first return to
the level after being meaningfully away from it), scored together, never selected
into after the fact.

**Event definition (ex ante, stated in full since none of this exists in the panel
yet):**
- **"Away"**: `|dist_atr| >= 1` (1 ATR, DESIGN's own literal threshold) for the given
  (family, lookback).
- **"Touch"**: `|dist_atr| <= 0.25` — tight enough to mean "at the level," loose enough
  not to require an exact zero-crossing on noisy daily closes. New parameter, not in
  DESIGN — chosen as a quarter of the "away" threshold, flagged as a first-pass number
  a later sensitivity pass could revisit (same spirit as M4's deferred term-structure
  follow-up).
- **Event day**: the *first* day, within `MAX_DAYS_TO_TOUCH = 10` trading days after an
  "away" run ends (i.e., after `|dist_atr|` first drops back under 1), where "touch" is
  true. At most one event per away-run (first touch only — this is what makes the
  event ex ante rather than selected-on-outcome). An away-run with no touch within 10
  days contributes no event. 10 trading days (~2 calendar weeks) is a first-pass window
  size, not derived from DESIGN; a shorter/longer window is a natural follow-up if this
  slice's result is promoted.
- **Direction**: `from_above` (price was >= +1 ATR above the MA before the touch — a
  potential *support* test) vs. `from_below` (price was <= -1 ATR below — a potential
  *resistance* test), scored **separately**, per DESIGN's own M6.2 framing that these
  are different animals, not pooled into one folklore claim.
- **Outcome, `OUTCOME_HORIZON = 5` trading days after the touch day**: compare
  `dist_atr` at touch+5 against a `RESOLVE_THRESHOLD = 0.5` ATR band, direction-aware —
  for `from_above`: **hold** if `dist_atr[touch+5] >= +0.5` (bounced back up, support
  held), **slice-through** if `<= -0.5` (broke down, support failed), **chop**
  otherwise; mirrored for `from_below`. All three outcomes reported (DESIGN's own "measure
  the full distribution," not just the hold rate) — `hold_flag` (1/0) is the one fed
  into the kill-criterion statistic below.
- **NaN handling**: every boolean built from a `dist_atr` comparison (`away`, `touch`,
  the direction/outcome flags) is explicitly masked wherever `dist_atr` itself is NaN
  (CLAUDE.md invariant #9) — an MA's warmup window must read as undefined, not as
  "not away"/"no touch."
- **Basis**: daily close only, not intraday high/low — consistent with every other
  distance/state feature in this study (all close-derived); an intraday-wick touch
  definition is out of scope for this slice, noted as a possible refinement, not built.

**Synthetic-level control:** DESIGN's own suggested shortcut — "the placebo MAs from
§7.5" — reused directly rather than building a new "randomly offset line" mechanism.
Same 3 groups, same focal/neighbor lookbacks as §7.5:
- **Group A (SMA200):** focal 200 vs. neighbors {187, 193, 207, 213}.
- **Group B (SMA50):** focal 50 vs. neighbors {47, 53}.
- **Group C (21-EMA):** focal 21 vs. neighbors {19, 23}.

`features/placebo_ma.py` currently only builds `dist_pct` for these lookbacks — this
module extends it to also build `dist_atr` (needs `atr_14`, already computed in that
module's per-ticker build step for consistency with the main panel's own ATR(14)
convention) for every focal + neighbor lookback, new code but not new *machinery*: same
`ma.compute_ma`/`apply_lag` reuse pattern §7.5 already established.

**Method:** For each group, build one pooled event table across the focal lookback and
all its neighbors (one row per qualifying touch event, tagged with `is_focal`,
`direction`, `hold_flag`, `outcome`). Test statistic: `stats.controls.c1_delta`/
`stats.inference.block_bootstrap_delta`, called with `group_col="is_focal"`,
`value_col="hold_flag"` — i.e. **P(hold | focal touch) − P(hold | synthetic-neighbor
touch)**, date-matched (C1) and date+`mom_tercile`+`vol_tercile`+`sector`-matched (C2,
unchanged match columns from M1/M4/M11/M2). This reuses the study's existing
control/bootstrap infrastructure unchanged — a hold/no-hold flag is just another
`value_col`, nothing new needed in `stats/controls.py` or `stats/inference.py`.

**Grid size (`N_tests` contribution):** **6 primary cells** — 3 groups × 2 directions.
Same "group, not individual lookback, is the unit of inference" convention §7.5
established (a group's synthetic comparison pools 2–4 neighbors into one statistic, not
one test per neighbor).

**Kill criterion, per cell, stated before running (DESIGN's own literal wording,
translated into this study's CI-based convention — same shape as every other module's
`max(|ci_low|, |ci_high|) < floor` rule, floor changed from a return magnitude to
DESIGN's own named percentage-point gap):**
`max(|ci_low|, |ci_high|) < 0.02` (2 percentage points) on the C2 block-bootstrap
`hold_flag` delta → **killed** — "P(hold) at the real MA is within 2pp of synthetic
levels, support/resistance from MAs is folklore" for that group/direction, DESIGN's own
words. A CI excluding zero *and* clearing the 2pp floor is read as a real, distinguishable
support/resistance effect at that focal lookback. **Module-level kill** fires iff all 6
cells are killed; DESIGN frames this as "a major, satisfying negative result" in its own
right, not a failure to find something.

**Control tier and why:** C1 default, **C2 is the tier the kill criterion is evaluated
on** — same rationale as every prior module: a raw hold rate could differ between focal
and synthetic touches for reasons unrelated to the level itself (e.g. which tickers/
regimes happen to generate more away-then-touch cycles at one lookback vs. a
neighboring one), and C2's momentum/vol/sector matching is this study's standing answer
to that class of confound.

**Cost annotation:** not applicable to the kill/confirm call itself — like §7.5, this
is a mechanism question (does the level itself matter) not a tradeable-edge question.
If any cell is confirmed, a cost annotation (turnover of the touch-event flow itself)
would be required before it's stated as an actionable claim (invariant #8) — deferred
until/unless that happens, not computed here.

**Plateau check (DESIGN §6.7):** built into the design itself, same as §7.5 — the
synthetic-neighbor comparison *is* the plateau check (does the focal lookback stand out
from its own near neighborhood), not a separate post-hoc pass.

**Effective N:** distinct event dates and tickers per cell, standard invariant —
expected to be far smaller than M1/M4/M11/M2's row counts (this is an event-count, not a
row-per-day-per-ticker, design), so DESIGN §6.9's minimum-sample floor (200 events, ≥30
dates, ≥30 tickers) is a live constraint here, not a formality — flagged per cell if
missed, not silently dropped.

**Universe/window/horizon:** unchanged, U1 (408 S&P 500 constituents as of
2021-12-31), dev window 2010-01-01 → 2021-12-31. The event horizon itself
(`OUTCOME_HORIZON = 5` trading days from the touch day) is intentionally short and
independent of this study's usual `fwd_ret_21` convention — this module measures a
level-hold probability shortly after the touch, not a 21-day forward return.

**Explicitly deferred (DESIGN §5's own sub-questions, out of this first slice, same
"first slice not full spec" precedent as M4/M1/M11/§7.5):** touch count (1st vs. 3rd vs.
5th test of the same level), volume on the touch, wick-vs-close-below distinction. None
of these are built or tested in this pass.
