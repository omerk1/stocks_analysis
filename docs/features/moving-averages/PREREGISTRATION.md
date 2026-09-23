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

### Result (2026-09-17)

Ran against the real U1 panel (405 S&P 500 constituents with full dev-window coverage,
2010-01-04 → 2021-12-31 — corrected from a first run that accidentally omitted `start=
"2010-01-01"` and pulled full available history back to 1970 for some tickers; the
holdout boundary itself was never crossed, only the dev-window's *start* was wrong, and
this was caught and fixed before logging anything).

**Module killed. All 6 primary cells killed — support/resistance from MAs is folklore,
DESIGN's own words, and a clean one:** every cell's C2 block-bootstrap edge on
`P(hold)_focal − P(hold)_synthetic` is far under the 2pp floor, not a borderline call —
the largest edge in the whole grid is 0.61pp (`sma200/from_below`), roughly a third of
the kill threshold, and most cells sit at 0.14–0.27pp:

| group | direction | n_events | n_dates | c2 (pp) | ci_low (pp) | ci_high (pp) | edge (pp) |
|---|---|---|---|---|---|---|---|
| sma200 | from_above | 7,585 | 2,113 | −0.212 | −0.612 | +0.159 | 0.61 |
| sma200 | from_below | 7,257 | 2,102 | +0.149 | −0.227 | +0.527 | 0.53 |
| sma50 | from_above | 17,703 | 2,544 | −0.009 | −0.246 | +0.227 | 0.25 |
| sma50 | from_below | 15,887 | 2,470 | +0.055 | −0.149 | +0.272 | 0.27 |
| ema21 | from_above | 30,692 | 2,640 | +0.077 | −0.079 | +0.241 | 0.24 |
| ema21 | from_below | 25,645 | 2,602 | −0.079 | −0.225 | +0.069 | 0.23 |

All 6 cells clear DESIGN §6.9's minimum-sample floor comfortably (smallest: 7,257
events, 2,102 dates, 402 tickers) — this is a well-powered null, not a "too thin to
tell" one. **Every one of the 6 CIs spans zero** on the correct, holdout-respecting
window above — the cleanest possible reading (a caveat worth naming precisely, not
glossing over: an earlier run, before the `start="2010-01-01"` fix, mis-scoped to full
available ticker history had `ema21/from_above`'s CI excluding zero at a tiny magnitude,
`+0.037pp` to `+0.204pp` — still nowhere near the 2pp floor either way, but that number
is superseded and not part of the logged result; the corrected, canonical run's
`ema21/from_above` CI is `[-0.079pp, +0.241pp]`, spanning zero like every other cell).

**Plateau/robustness, beyond what the synthetic-neighbor design already builds in:**
all 3 lookback families (200/50/21) and both directions (support/resistance) land in
the same tiny-edge regime — this isn't one lookback narrowly failing while a
neighboring one passes; every cell in the grid tells the same story.

**Argue against this result:**
- **Close-only touch definition.** DESIGN's own deferred sub-question
  (wick-vs-close-below) is exactly the gap here: a trader reacting to an intraday
  wick-touch, not a closing-price touch, could produce a real effect this slice's
  close-based definition can't see. Not built or tested in this pass.
- **This test bounds a narrower claim than "MAs matter at all."** The synthetic
  neighbors (e.g. SMA187/193/207/213 vs. SMA200) sit at nearly the same *price level*
  as the focal MA — so this result rules out "traders specifically watch and react to
  the 200-day, distinct from any nearby long-run trend line," but says nothing about
  whether *some* long-horizon MA-ish price region acts as mild support/resistance
  everywhere, watched or not (a softer, less commonly stated version of the folklore
  claim, and not one this design can distinguish from "no support/resistance at all").
  Same scope limitation §7.5's own design already carries — named there, and true here
  for the same structural reason.
- **First-pass parameters** (1/0.25/0.5 ATR thresholds, 10/5-day windows) aren't
  DESIGN-derived and a different choice could in principle change the read at some
  setting — but given every cell in the grid lands an order of magnitude under the
  kill floor, this isn't a borderline result a parameter tweak would plausibly flip.

**Tier: 4 (killed).** No `FINDINGS.md` entry per this study's own convention (Tier 4 =
`EXPERIMENTS.csv` only, no `FINDINGS.md` claim). Logged: `EXPERIMENTS.csv` (6 rows).

---

## M6.2 — Slope as conditioner (2026-09-17)

**Module / track:** M6.2, Track B (DESIGN.md §6.2). Last module on the minimal-core
list (DESIGN §12: M1, M2, M4, M5, M6.2, M11, plus §7.5 — every other item now run).

**Promoted from:** DESIGN §12's own minimal-core list, not a Track A candidate — same
status as M1/M2/M5/M11. DESIGN's own words: "**Prior: this is the most likely Tier-1
producer in the whole slope module** ... conditioning demands far less of the data than
prediction does" — the highest expectation any single sub-question in this study has
carried going in, M2's own "highest expected-value module" framing aside.

**M6.0 prerequisite, already established, not re-derived here:** DESIGN §6.0's two
identities (1-day SMA slope = scaled momentum; EMA slope = distance-from-MA, times a
constant) were confirmed empirically against the real panel in the 2026-09-16 Track A
sweep (`EXPLORATION_LOG.md`) — `slope_log_5` vs. `dist_pct` correlation 0.986 for EMA200
(near-exact, as the identity predicts), 0.71 for SMA20 (same direction, much weaker, as
the "momentum with smoothed endpoints" framing predicts), both decorrelating
substantially by `slope_log_63`. Consequence applied here: **this slice only uses SMA
slope** (`slope_log_21_sma_{50,200}`, the exact columns DESIGN's own M6.2 text names:
"terciles of the 50 and 200") — an EMA-based version of any of these same interactions
would need to be read as "conditioning on distance-from-EMA, relabeled," per the
identity, not a second independent slope-conditioning result. Not built or tested here.

**Hypothesis (per DESIGN's own named sub-questions, 3 of its 4 taken up this slice —
see "Explicitly deferred" below):**
1. **State × slope**: "above a rising 200 vs above a falling 200 ... this is the
   cleanest test" of the folklore claim that trend direction, not just trend
   presence, changes what an above/below state means.
2. **Extension × slope**: "is +5 ATR above a flat 50-day a different object from +5 ATR
   above a steeply rising one" — M4's distance-decile effect, conditioned on slope.
3. **Touch × slope**: "MA touch with rising vs falling MA — support in an uptrend vs
   resistance in a downtrend" — M5's touch/bounce event, conditioned on slope.

**New machinery: none.** Every sub-question here reuses existing features and existing
stats primitives, restricted to a row-subset first — this is the "faceting is cheap"
property DESIGN's own prior banks on:
- `slope_sign` (new column, one line: `sign(slope_log_21_sma_k) > 0`) is the only new
  feature, built directly from the already-cached, already-lagged `slope_log_21_sma_k`
  columns (SMA20/50/200 all already in the main panel — no placebo/neighbor plumbing
  needed for this module, unlike §7.5/M5).
- Sub-questions 1 and 2 are answered by **restricting the panel to the relevant
  row-subset first** (state=above/below for #1, decile=top/bottom for #2), then running
  `stats.inference.block_bootstrap_delta` with `group_col=slope_sign`,
  `value_col=fwd_ret_21` — the *exact same primitive* every other module's C1/C2 delta
  uses, just on a pre-restricted population. No new statistical machinery.
- Sub-question 3 reuses `features/touch.py::touch_events` (M5's own event extraction)
  directly on the **main cached panel's** `dist_atr_sma_{50,200}` columns (not the
  placebo panel — no synthetic-neighbor comparison needed here, since this question is
  about the real MA's own slope, not real-vs-synthetic), joins `slope_sign` at the
  touch day, and runs `block_bootstrap_delta` with `group_col=slope_sign`,
  `value_col=hold_flag` — the same reuse pattern M5 itself used for `is_focal`.

**Method, per sub-question:**
1. **State × slope** (4 cells: lookback ∈ {50, 200} × state ∈ {above, below}): restrict
   panel to `above_sma_k == state`, then C1/C2 delta of `fwd_ret_21` between
   `slope_sign_sma_k` = rising vs. falling within that restricted population.
2. **Extension × slope** (4 cells: lookback ∈ {50, 200} × extension ∈ {top decile,
   bottom decile} of `dist_atr_sma_k`): restrict panel to that decile, then C1/C2 delta
   of `fwd_ret_21` between rising vs. falling within it.
3. **Touch × slope** (4 cells: lookback ∈ {50, 200} × direction ∈ {`from_above`,
   `from_below`}): M5-style touch-event table on the real MA only (no synthetic
   neighbors), C1/C2 delta of `hold_flag` between rising-at-touch vs. falling-at-touch.

**Grid size (`N_tests` contribution):** **12 primary cells** (3 sub-questions × 2
lookbacks × 2 facets each). Each cell is its own independent row/state/decile
restriction — no algebraic mirrors of the kind M1's above/below pairs turned out to be
(rising-within-above and rising-within-below are different row populations, not
complements of each other the way above/below themselves are), so no dedup collapse is
expected here the way it was needed for M1 — flagged as a specific thing for the
whole-grid FDR pass to actually check, not assumed.

**Kill criterion, per cell, same convention as every prior module (a floor keyed to
the value type, not a new threshold invented for this module):**
- Sub-questions 1–2 (`value_col=fwd_ret_21`, a return): `max(|ci_low|, |ci_high|) <
  0.10%` (M1/M2's own floor) → killed (slope doesn't change the read within that
  state/decile).
- Sub-question 3 (`value_col=hold_flag`, a probability): `max(|ci_low|, |ci_high|) <
  2pp` (M5's own floor) → killed (slope doesn't change the hold rate).
- No module-level kill declared across all 12 — each sub-question (and each cell within
  it) is scored independently, same "the answer is interesting either way" framing
  §7.5/M5 already established for a conditioning/mechanism question.

**Control tier and why:** C1 default, **C2 (date + `mom_tercile` + `vol_tercile` +
`sector`, unchanged match columns) is the tier every kill criterion above is evaluated
on** — same rationale as every prior module: slope and momentum are related but not
identical (§6.0's own identity only makes them the *same variable* for a 1-day EMA
slope, not for a 21-day SMA slope, which is what this slice actually uses), so momentum
still needs matching out separately.

**Cost annotation:** sub-questions 1–2 imply a tradeable claim (a return delta) — if any
cell is confirmed, CLAUDE.md invariant #8 requires a cost annotation before it's stated
as a claim, using the combined state-and-slope-sign flag's own turnover
(`stats/costs.py::signals_per_year`, same convention as every prior module), not
computed unless triggered. Sub-question 3 is not applicable to cost directly, same
reasoning as M5 (a hold-rate difference is a mechanism read, not a tradeable edge on its
own).

**Plateau check (DESIGN §6.7):** applied as directional consistency with each
sub-question's own parent module, same convention M2 used: sub-question 1's
above-and-rising cell should agree in sign with M1's own `above_sma_k` cell (a
conditioning effect that flips the parent module's own sign would be a red flag for the
slope-sign construction, not a finding); sub-question 2 similarly against M4's own
decile-spread sign; sub-question 3 against... there is no parent-module sign to check
against directly (M5 found no real vs. synthetic effect at all, not a directional one)
— for sub-question 3, the plateau check instead is internal: both lookbacks (50, 200)
and both directions should tell a broadly consistent story, not one lookback
confirming while its only sibling kills, absent a specific mechanism reason.

**Effective N:** distinct event dates and tickers per cell, standard invariant.
Sub-questions 1–2 restrict an already-large row population (should clear DESIGN §6.9's
floor easily, same order of magnitude as M1/M4's own cells); sub-question 3 restricts
M5's already-thinner touch-event population further by slope sign — flagged, not
assumed, if any cell falls short.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents with full
dev-window coverage — the corrected count M5's run established), dev window
2010-01-01 → 2021-12-31, `fwd_ret_21` for sub-questions 1–2 (unchanged horizon
convention), M5's own touch/outcome-horizon definition for sub-question 3.

**Explicitly deferred (DESIGN §6.2's 4th named sub-question, out of this first slice,
same "first slice not full spec" precedent as every prior module):** **golden cross ×
slope** ("a 50/200 cross where the 200 is still declining is a bounce-off-the-lows
event; where the 200 is rising it's a continuation event"). This needs new
crossover-event-detection machinery (a state-flip/transition detector for
`above_sma_50_vs_200`) that doesn't exist yet in this codebase, unlike sub-questions
1–3, which reuse existing features/primitives entirely — a real, motivated follow-up
(DESIGN explicitly ties it to explaining "why the crossover literature reports such
muddy averages," §2.2) but a new build, not a faceting exercise, so scoped out of this
slice rather than rushed. `slope_pctile` terciles (vs. this slice's binary
`slope_sign`) are also deferred — DESIGN mentions both, but every one of its own named
sub-questions is phrased in rising-vs-falling (sign) terms, so the sign-only version is
this slice's literal reading of what was asked, not an arbitrary simplification.

### Result (2026-09-17)

Ran against the real U1 panel (405 S&P 500 constituents, 2010-01-04 → 2021-12-31 — the
main cached panel, correct window from the start, no repeat of M5's execution slip).

**2 of 12 cells confirmed (CI excludes zero, clears their own floor); 1 cell
unresolved (thin-stratum, not killed and not confirmed, a genuine data-scarcity
finding in its own right); the remaining 9 are CI-spans-zero and inconclusive — not
"killed" under the pre-registered rule, since their CI edge is wide enough to still
contain an economically meaningful effect, just not a detected one.**

| sub_question | lookback | facet | n_events | n_dates | c2 | ci_low | ci_high | edge | read |
|---|---|---|---|---|---|---|---|---|---|
| state_x_slope | 50 | above | 560,242 | 2,747 | +0.066% | −0.158% | +0.286% | 0.286% | inconclusive |
| state_x_slope | 50 | below | 165,802 | 2,728 | −0.015% | −0.207% | +0.154% | 0.207% | inconclusive |
| state_x_slope | 200 | above | 720,928 | 2,747 | −0.102% | −0.311% | +0.102% | 0.311% | inconclusive |
| state_x_slope | 200 | below | 110,430 | 2,747 | −0.034% | −0.260% | +0.214% | 0.260% | inconclusive |
| extension_x_slope | 50 | top | 104,129 | 2,747 | **−0.592%** | **−1.047%** | **−0.175%** | 1.047% | **confirmed** |
| extension_x_slope | 50 | bottom | 30,330 | 2,551 | −0.107% | −0.506% | +0.270% | 0.506% | inconclusive |
| extension_x_slope | 200 | top | 111,154 | 2,747 | n/a | n/a | n/a | n/a | **unresolved** |
| extension_x_slope | 200 | bottom | 26,646 | 2,362 | +0.113% | −0.352% | +0.570% | 0.570% | inconclusive |
| touch_x_slope | 50 | from_above | 14,138 | 2,410 | **−5.75pp** | **−10.22pp** | **−1.94pp** | 10.22pp | **confirmed** |
| touch_x_slope | 50 | from_below | 6,480 | 1,845 | +1.18pp | −2.17pp | +4.23pp | 4.23pp | inconclusive |
| touch_x_slope | 200 | from_above | 6,107 | 1,887 | −8.05pp | −17.31pp | +2.36pp | 17.31pp | inconclusive |
| touch_x_slope | 200 | from_below | 3,769 | 1,525 | −4.67pp | −13.82pp | +4.13pp | 13.82pp | inconclusive |

**Finding 1 — `extension_x_slope`, SMA50, top decile:** among stocks already ≥ the top
decile of `dist_atr_sma_50` (already deep in M4's "extended" territory), those where the
50-day is **rising** show a **lower** forward 21-day return than those where it's
**falling**, C2 (mom/vol/sector-matched) `−0.592%` per 21d, CI `[−1.047%, −0.175%]`,
excludes zero. **Cost (invariant #8, triggered since this cell is confirmed):**
combined "top-decile-and-rising" flag turnover 8.061 flips/ticker-yr → hurdle
0.806%/yr (10bps/rt, `stats/costs.py`). Annualized (×12): point −7.11%/yr, near-zero
edge −2.10%/yr, far edge −12.56%/yr — **clears at every reading.**

**Finding 2 — `touch_x_slope`, SMA50, from_above:** among first-touch-of-the-50-day
events approaching from above (M5's own event definition, real MA only), touches where
the 50-day is **rising** at the touch show a **lower** `P(hold)` than touches where it's
**falling** — C2 `−5.75pp`, CI `[−10.22pp, −1.94pp]`, excludes zero, far past the 2pp
floor. **Cost: not applicable**, per this entry's own pre-registered convention
(mechanism read, same as M5 itself).

**Both findings point the same direction, at the same lookback, from two independently
constructed cells (a decile restriction vs. an event-based restriction) — worth naming
as a soft corroboration, not a formal plateau check:** an actively rising 50-day,
conditional on already being in an extended/testing configuration, is associated with
*worse* near-term outcomes than an otherwise-identical setup on a flattening/falling
50-day. This runs counter to the common folklore reading ("buy the dip in an uptrend is
safer than in a downtrend") — DESIGN itself flagged this general shape as plausible
("is +5 ATR above a flat 50-day a different object... almost certainly yes").

**Plateau check (as pre-registered):** Finding 1's sign agrees with M4's own SMA50
decile-spread sign (`dist_atr_sma_50`'s top-minus-bottom C2 spread is negative,
`EXPERIMENTS.csv`'s `dist_pct_sma_20_h21`-family rows — extension predicts lower
forward returns; this cell's "rising side underperforms the falling side within the
same extended decile" is a same-direction intensification of that pattern, not a
contradiction). Finding 2 has no parent-module sign to check against (M5 found no
real-vs-synthetic effect at all, a different axis) — its own internal consistency check
(same sign at SMA200/`from_above`, `−8.05pp`, though CI-spans-zero and much noisier at
`n_events=6,107`) is a directionally-consistent, not lone-pixel, read.

**Argue against both findings (not resolved here, flagged as live alternatives):**
- **No short-term-reversal control** (same gap M1/M2 already named and only partially
  closed for `stack_fully_bearish` — not run here at all): a stock that reaches
  top-decile-extension-above-a-falling-50-day plausibly got there via a sharp,
  recent bounce/squeeze — its very recent (< 1 month) return pattern, not captured by
  `mom_12_1` (skips the most recent month), could itself explain the gap on both sides
  of this comparison.
  M6.3's own explicit warning ("the top slope decile is heavily contaminated by
  post-earnings-gap and low-float names") is exactly the composition-effect risk that
  applies here too, on the "falling despite being far above" side specifically.
- **Both confirmed cells' "falling" side is a comparatively rare population**
  (`slope_sign=False` is 7.1% of the SMA50 top-decile row population; M5's from_above
  touch events split more evenly) — a real effect on a rare subpopulation is still a
  real result, but its generality (does it hold outside these specific
  extended/touching conditions) is untested.
- **Sub-question 3's 5-day outcome window is short and noisy** — Finding 2's own CI is
  wide relative to its point estimate (a 5x range between near and far edges), a wider
  outcome window is a natural robustness follow-up, not built here.

**Finding 3 (unresolved, a data-scarcity finding, not a confound) — `extension_x_slope`,
SMA200, top decile:** `InsufficientBlocksError` — traced directly (not inferred): within
the top decile of `dist_atr_sma_200`, only 544 of 111,698 C2-eligible rows (0.5%) have
`slope_sign_sma_200 = False` (falling) — vs. 7.1% at the equivalent SMA50 cell. Once
stratified by (date, `mom_tercile`, `vol_tercile`, `sector`), only 112 distinct dates
have *both* sides of a stratum populated, short of the block-bootstrap's 126-date
minimum (`MIN_BLOCKS × block_length = 3 × 42`). **Mechanistically explicable, not
mysterious**: a 200-day SMA moves far more slowly than price, so "already many ATRs
above the 200-day, but the 200-day itself hasn't yet turned down" is a rare, transient
combination by construction — unlike the 50-day, which turns over often enough for a
"still falling but price already far above it" state to occur more than an order of
magnitude more often. **Cross-reference to `STATUS.md`'s SMA200 watch**: this is a
different mechanism than the three prior SMA200 oddities logged there (M4's `dist_z`
window instability, M1's lb200 row-loss/skew, M11's `dist_pct_sma_200_h21` CI-spanning
result) — those were about instability or no-detectable-effect; this is about a
genuinely thin subpopulation at the intersection of two SMA200-derived conditions,
which is a *structural* consequence of 200 being a long, slow-moving window, not a
newly-suspicious anomaly. Logged as context for whoever eventually does the SMA200
audit, not folded into that watch item's trigger count as a 4th instance — the
mechanism here is understood, not open.

**Tier: 3** for both confirmed cells (Finding 1, Finding 2) — capped by the same
missing FDR/holdout infrastructure every Tier-3 cell in this study carries, clearing
cost (Finding 1) or not needing to (Finding 2) doesn't lift the cap. **Tier: not
tiered** for the unresolved SMA200 cell (below-threshold, same convention as M1's own
thin secondary cells). **Tier: 4** for the remaining 9 inconclusive cells — read as "no
detected effect at this control tier and sample," not "confirmed folklore," per this
study's own Tier-3/4 distinction (CLAUDE.md: a Tier-4 CI-spans-zero result is still a
real report, not silence).

**Logged:** `EXPERIMENTS.csv` (12 rows); `FINDINGS.md` (2 new entries, Finding 1 and
Finding 2); `STATUS.md` (module table, minimal-core-list completion, whole-grid FDR
pass trigger now fired).

### Reversal-robustness addendum (pre-registered 2026-09-21, before running)

**Module / track:** M6.2, Track B. Promoted from `STATUS.md`'s own "Not yet done,
optional/follow-up only, not gating termination" note: Finding 1 (`extension_x_slope`/
SMA50/top) and Finding 2 (`touch_x_slope`/SMA50/`from_above`) both carry the same named
live caveat in this entry's own "Argue against both findings" section above — "no
short-term-reversal control ... not run here at all" — the one gap this study's own
established check (M1's lb200 diagnostic, M2's `stack_fully_bearish` addendum, M18's
own two `dist_from_52w_low` cells) has now closed for every other Tier-3 cell in the
study except these two. Both cells already failed the whole-grid FDR pass
(`STATUS.md`), so this cannot change their tier — the value here is resolving the
specific, named confound question sitting open in their `FINDINGS.md` entries, not a
tier promotion, matching M2's own addendum framing exactly.

**Hypothesis:** both cells' C2 deltas survive once the C2 match set additionally
controls for the prior 21-day return tercile (`rev_tercile`) — i.e. the "falling side is
a rare, plausibly-just-bounced subpopulation" alternative explanation named in M6.2's own
"Argue against both findings" section is not the whole story.

**Method:** `modules/slope_conditioner.py::_delta_cell`, called with
`match_cols=C2_MATCH_COLS_WITH_REVERSAL` (`("mom_tercile", "vol_tercile", "sector",
"rev_tercile")`, new constant added to the module this addendum) instead of the module's
default 3-column `C2_MATCH_COLS`, for exactly the two already-confirmed cells only
(`extension_x_slope`/SMA50/top decile; `touch_x_slope`/SMA50/`from_above`) — the 10
inconclusive/unresolved cells are not re-run, same "only the survivors get the
confound check" scope M18's own reversal addendum used. Same panel (U1, 405 S&P 500
constituents, dev window 2010-01-01 → 2021-12-31), same restriction logic, same
block-bootstrap CI machinery (`block_length=42` for the return cell, `block_length=10`
for the touch cell, unchanged from the primary run) — only the match-column list
changes. `rev_tercile` computed exactly as `stack_minervini.py`'s/`baseline_state.py`'s
own robustness column: `cross_sectional_bucket(working, "mom_1_0", n_buckets=3)`.

**Kill criterion:** identical rule to each cell's own pre-registered kill criterion
above (same shape as M2's own reversal addendum): `max(|ci_low|, |ci_high|) < 0.10%` for
`extension_x_slope` (a return), `< 2pp` for `touch_x_slope` (a hold-rate) on the
4-column C2 delta → killed under the reversal control (read as "reversal explains the
effect, or it was never distinguishable from noise once reversal is matched out"). A CI
that still excludes zero and clears its own floor is read as "survives
reversal-matching" — not by itself a tier change (both cells are already FDR-failed,
Tier 3 either way), but it resolves the specific confound question named above.

**Control tier and why:** C2, 4-column (`mom_tercile`, `vol_tercile`, `sector`,
`rev_tercile`) — the same tier M1/M2/M18 have each already used for this exact
diagnostic, applied here to M6.2's two surviving cells for the first time.

**Cost convention:** unchanged, not re-evaluated here — this addendum is about whether
the gross C2 delta survives a confound check, not a second cost pass. If
`extension_x_slope` survives, its already-logged cost numbers (`EXPERIMENTS.csv`) stand
unchanged; `touch_x_slope` was never cost-annotated (mechanism read, M5's own
convention) and stays that way.

**Grid size (`N_tests` contribution):** 2 cells, same primary-cell count as the two
Findings already declared — this is a re-evaluation of already-declared cells under an
alternative control, not a new hypothesis, so it does not add to the whole-grid
`N_tests` denominator beyond what M6.2 already declared (same convention as M1's lb200
and M2's `stack_fully_bearish` reversal diagnostics — logged, not double-counted; the
whole-grid FDR pass itself is not re-run for this addendum, since neither underlying
cell can change tier).

**Universe/window/horizon:** unchanged from M6.2's own entry above.

### Result (reversal-robustness addendum, 2026-09-21)

**Reproducibility note, checked before trusting anything below:** re-running the
unmodified `extension_slope_table`/`touch_slope_table` (default 3-column C2, no
addendum logic involved) against the same cached panel reproduces slightly different
numbers than the ones logged on 2026-09-17: `extension_x_slope`/SMA50/top now reads
`c2=-0.5898%`, CI `[-1.0425%, -0.1714%]` (logged: `-0.5924%`, CI `[-1.0469%,
-0.1750%]`); `touch_x_slope`/SMA50/`from_above` now reads `c2=-5.4968pp`, CI
`[-10.0474pp, -1.8643pp]` (logged: `-5.7523pp`, CI `[-10.2207pp, -1.9416pp]`). Same
`n_events`/`n_dates` both cells (104,129/2,747 and 14,138/2,410 respectively — identical
row populations), same code (`git log` confirms no changes to `touch.py`,
`slope_conditioner.py`, `panel.py`, or `inference.py` since the commit that produced the
original numbers) — the drift is small (≤4.6% relative on the point estimate, both cells
same sign, same CI-excludes-zero read under the default C2) and doesn't change either
cell's Tier-3/FDR-failed status, but is logged here rather than silently treated as an
exact match; root cause not chased further (not gating this addendum, and the margin is
nowhere near flipping a kill/confirm call). The **reversal comparison below uses this
addendum's own freshly-computed default-C2 numbers as its baseline**, not the
2026-09-17 logged ones, so the "attenuation" percentages compare like-for-like.

**Finding 1 (`extension_x_slope`/SMA50/top) survives, mildly attenuated.** Default C2
(this addendum's own rerun): `c2=-0.5898%`, CI `[-1.0425%, -0.1714%]`. With
`rev_tercile` added: `c2=-0.5503%`, CI `[-0.9777%, -0.1033%]` (n_events 104,129 →
104,129, n_dates 2,747 → 2,747 — unchanged; the top-decile restriction already
determines row membership, `rev_tercile` only adds another match dimension within it).
Point estimate attenuates ~6.7%, CI still excludes zero, clears the 0.10% floor by a
wide margin (edge 0.1033%) — **not killed, and not meaningfully explained by reversal.**

**Finding 2 (`touch_x_slope`/SMA50/`from_above`) does *not* survive — this is the
addendum's actual result, not a clean confirmation.** Default C2 (this addendum's own
rerun): `c2=-5.4968pp`, CI `[-10.0474pp, -1.8643pp]`, excludes zero. With `rev_tercile`
added: `c2=-3.3259pp`, CI `[-8.1800pp, +1.2450pp]` (n_events 14,138 → 14,138, n_dates
2,410 → 2,410 — unchanged, same event population). The point estimate attenuates by
~40% and **the CI now spans zero** — under the pre-registered rule this is `killed=False`
(edge 8.18pp still clears the 2pp floor, so it isn't a "no effect at all" kill), but
`ci_excludes_zero=False`: an inconclusive read, not a confirmed one, per this study's
own established distinction between those two fields (`modules/slope_conditioner.py`'s
own `_delta_cell` docstring: "a cell can have `killed=False` and still have a CI
spanning zero — an inconclusive/underpowered read, not a confirmed effect").

**Reading:** the two findings diverge under this check, unlike every prior
reversal-robustness pass in this study (M2's `stack_fully_bearish`, M18's two
`dist_from_52w_low` cells all survived, attenuated by 0–32% but always CI-excluding).
Finding 1 behaves the same way — a real, reversal-independent effect. **Finding 2 does
not**: once 1-month reversal is matched out, its CI now spans zero, meaning the "falling
side is a rare, plausibly-just-bounced subpopulation" alternative explanation named in
M6.2's own "Argue against both findings" section is not merely a live caveat, it
substantially accounts for Finding 2's gross number. This does not change Finding 2's
tier (already Tier 3, already failed the whole-grid FDR pass on independent grounds —
this addendum cannot lower a tier any further than FDR already has) — but it changes the
honest read of the underlying mechanism claim: Finding 1 ("extended + rising 50-day
underperforms extended + falling 50-day") is a real, reversal-robust pattern; Finding 2
("support test on a rising 50-day holds less often than on a falling one") is now best
read as **substantially, not just partially, a short-term-reversal artifact** — the
"two independent constructions pointing the same direction" corroboration the original
write-up drew between them is weaker than it read at the time, since only one of the two
constructions survives the confound check that would distinguish "real mechanism" from
"reversal re-encoding."

**Logged:** `EXPERIMENTS.csv` (2 new rows, both dated 2026-09-21,
`slope_cond_extension_x_slope_sma50_top_reversal_robustness` /
`slope_cond_touch_x_slope_sma50_from_above_reversal_robustness`); `FINDINGS.md`'s
Finding 1 and Finding 2 entries updated with this result in place of their prior "no
reversal control run" open caveat; `STATUS.md`'s post-termination note updated to mark
this item done and to record Finding 2's weakened reading.

---

## M18 — 52-week high/low range as a standalone predictor (2026-09-20)

**Track B.** Written and committed before running, per this study's own workflow.
DESIGN.md now has a matching M18 section (added same day) — read that first for the
"why this exists at all" framing; this entry is the concrete hypothesis/kill/scope
statement DESIGN's own convention asks every module to write down before analysis code
runs.

**Promoted from:** two independent Track A observations, both from *after* this
study's formal termination (`STATUS.md`'s "Study-level termination", reached
2026-09-17): M2's Minervini ablation (`FINDINGS.md`/`EXPERIMENTS.csv`,
`ablation_tt_c7_h21` — criterion 7, near-52w-high, the single largest attribution
coefficient, negative sign, but that module's own `linear_attribution` has no control
at all, not even C1) and the 2026-09-16 348-cell feature×horizon IC sweep
(`EXPLORATION_LOG.md`), which found `dist_from_52w_high`/`dist_from_52w_low` are the
two strongest cells in the entire grid and the only ones that *strengthen* with horizon
rather than fade. Neither prior reading used this study's actual C1/C2 machinery or
produced a CI — this module is the first controlled test of this feature family.
Promotion-gate re-slice (DESIGN §1.5, 2026-09-20, `high_low_52w_gate_check.py`): 3 of 4
(feature, horizon) cells same-signed across a 2010-2015/2016-2021 subperiod split; the
fourth is near-zero-not-opposite-signed in the early subperiod. Passes the gate.

**Hypothesis:** position within the trailing 252-day high/low range (`dist_from_52w_high`
= `close/rolling_252d_max - 1`, always ≤ 0; `dist_from_52w_low` = `close/rolling_252d_min
- 1`, always ≥ 0 — both already in the cached panel, built for M2, `features/context.py`)
predicts forward return at 63/126-day horizons beyond a momentum/vol/sector-matched
control. This is the same question this whole study asks of every MA-distance feature
(does displacement information survive momentum-decile matching), applied to a feature
that is, by construction, closely related to `mom_12_1` itself — a genuinely harder bar
to clear than most of this study's other C2 tests, not an easier one, precisely because
the momentum-tercile match is matching out something close to what the feature already
measures. Mechanism prior: George & Hwang's 52-week-high anomaly (nearness to the
52-week high predicts *higher*, not lower, subsequent return in that literature) is the
standard academic prior — note this cuts the opposite direction from M2's own ablation
sign (criterion 7 negative) and the IC sweep's own sign (`dist_from_52w_high` IC
negative), which would make a confirmed result here a genuine sign-conflict with a
well-known published anomaly, worth flagging explicitly rather than only citing the
literature that agrees.

**Kill criterion:** for each of the 4 primary cells (`dist_from_52w_high` × {63d, 126d},
`dist_from_52w_low` × {63d, 126d}), killed if the C2 block-bootstrap CI on the
top-minus-bottom decile spread of the horizon-matched forward return spans zero — the
exact same decisive test M4 uses (no separate IC floor gate, unlike M11 — DESIGN §9.2's
2026-09-10 resolution already separated "kill" from "tier" as independent axes, and
M11's own two-joint-test construction is exactly the added complexity that resolution
was reacting to; this module keeps one decisive test and reports the per-date rank-IC
bootstrap alongside as a corroborating readout, not a second gate). Not killed → tier
per DESIGN §9.2 using cost (CLAUDE.md invariant #8) and, if it ever gets there, the
whole-grid FDR pass (already run once against the minimal-core grid; a new cell that
survives here would need that pass re-run, not silently left out — see "FDR
re-entry" below).

**Control tier and why:** C1 (date-matched, zero row loss — the primary reading, same
convention M11 established) and **C2 (date + `mom_tercile` + `vol_tercile` + `sector`,
unchanged match columns) is the tier the kill criterion above is evaluated on** — the
same three columns as M1/M2/M4/M6.2/M11's own C2, for direct comparability across the
study rather than inventing a module-specific spec. A `rev_tercile`-augmented C2 (M1's
own 1-month-reversal robustness check) is run in the same pass and reported alongside,
not gating — proactively, since M6.2's own open caveat (no reversal control run for
either of its two surviving cells) was named as a process gap worth avoiding on the
next module, not just M6.2's own outstanding item.

**Method:** reuses `modules/cross_sectional.py`'s exact machinery (`daily_rank_ic`,
`cross_sectional_bucket`, `block_bootstrap_series`, `block_bootstrap_spread`,
`decile_turnover_hurdle`/`signals_per_year`/`cost_hurdle`) — new module
`modules/high_low_52w.py` generalizes M11's `cell_result` from a `{feature}_sma_{lookback}`
column to a plain single-column feature (no lookback grid), otherwise identical
construction: per-date decile bucketing (10 deciles), IC bootstrap, C1 spread bootstrap,
C2 spread bootstrap, turnover-based cost hurdle. `fwd_ret_63`/`fwd_ret_126` added via
the existing `labels/forward_returns.py::forward_return`, unchanged.

**Grid size (`N_tests` contribution):** **4 primary cells** (2 features × 2 horizons).
No companion/redundancy exclusions needed at declaration — `dist_from_52w_high` and
`dist_from_52w_low` are two different columns (not correlated normalisations of the same
one, unlike M4's `dist_pct`/`dist_atr`/`dist_z`), and 63d/126d are two different
horizons on the same feature, which M11's own precedent (`dist_pct_sma_20`@5d vs. @21d)
already treats as separate tests, not mirrors. Flagged for a same-module correlation
check anyway before trusting both as independent (below).

**Correlation check (before trusting 4 independent cells, not deferred):**
`dist_from_52w_high` and `dist_from_52w_low` are two different quantities (distance from
the max vs. distance from the min of the same rolling window) but could still move
together if a ticker's 252-day range is roughly constant in width — checked via the same
per-date median Spearman convention as M4/the 2026-09-16 sweep before the grid's
`N_tests=4` is trusted, reported in the "Result" section below alongside the main
numbers, not assumed independent by construction.

**Cost annotation:** implies a tradeable claim (a return delta) — CLAUDE.md invariant #8
applies. Turnover measured the same way as M4/M11: top/bottom-decile membership flip
count (`stats/costs.py::signals_per_year`, entry+exit convention), combined across both
legs, 10bps/round-trip (this study's U1 convention throughout). `annualize()`'s linear
scaling is applied at the horizon-correct multiple (`252/63` or `252/126`), not the 21d
cells' `×12` — a labeled approximation either way, per `costs.py`'s own docstring.

**Plateau check (DESIGN §6.7):** the two horizons (63d, 126d) on the same feature are
this cell's own neighborhood — a real effect at 126d that reverses sign or vanishes at
63d (or vice versa) is the kind of lone-bright-pixel pattern the 2026-09-18 distance×
slope generalization already found once in this study; checked directly rather than
assumed smooth, given that prior result.

**FDR re-entry, stated up front:** this module runs *after* the whole-grid FDR pass
already executed (`STATUS.md`, 2026-09-17, N=31). If any of these 4 cells survives its
own kill criterion and clears cost, the correct handling is to add it to the
deduplicated grid (N=32) and **re-run** `benjamini_hochberg` against the full,
now-larger ranked table — not report a standalone significance claim outside that
grid's own discipline, which is exactly the "widen the grid without going through the
process" case CLAUDE.md's own Stop-and-ask section names. If no cell survives its own
kill criterion, no FDR re-entry is needed and this module closes as a dead end, logged
in `EXPERIMENTS.csv` the same as any other Tier-4 result.

### Result (2026-09-20)

**Correlation check first, as committed above:** per-date median Spearman(`dist_from_
52w_high`, `dist_from_52w_low`) = **0.4677** — moderate, well short of M4's 0.94–0.98
redundancy bar. All 4 declared cells trusted as independent.

**`dist_from_52w_high` — killed cleanly at both horizons.** 63d: C2 spread −0.379%, CI
[−1.514%, +0.734%], spans zero. 126d: C2 spread −0.674%, CI [−2.632%, +1.208%], spans
zero. Both cells' point estimates keep the sign the raw IC sweep and M2's ablation
both found — but neither survives momentum/vol/sector matching. **This resolves the
sign-conflict question this entry's own hypothesis section flagged up front** (M2's
ablation and the IC sweep's negative reading on this feature vs. George & Hwang's
published positive-nearness-to-high anomaly): there is no real academic-anomaly-style
effect here in *either* direction once matched — the gross negative reading both prior
Track A methods found is, like most of this study's gross reads, momentum re-encoded.
Tier 4, `EXPERIMENTS.csv` only (no `FINDINGS.md` entry, per this study's own
Tier-4 convention).

**`dist_from_52w_low` — real at both horizons, one clears cost cleanly.** 63d: C2
spread +0.956%, CI [+0.128%, +1.843%] — excludes zero, Tier 3, **fails cost** (near
edge +0.51%/yr vs. 0.825%/yr hurdle). 126d: C2 spread +2.504%, CI [+1.104%, +4.017%] —
excludes zero, Tier 3, **clears cost at every reading** (near edge +2.21%/yr vs.
0.834%/yr hurdle) — this study's third cost-clearing Tier-3 cell, alongside `stack_
fully_bearish` (M2) and `extension_x_slope`/SMA50 (M6.2). Both cells survive a
`rev_tercile`-augmented C2 (reversal-robustness) essentially unattenuated. Full
numbers, effective N, and the argue-against-it discussion: `FINDINGS.md`'s M18 section.

**Plateau check:** `dist_from_52w_low`'s effect strengthens from 63d to 126d (matches
the 2026-09-16 sweep's own horizon-shape finding exactly); `dist_from_52w_high`'s null
is consistent (spans zero) at both horizons. Neither is a lone-bright-pixel read.

**FDR re-entry, carried out (not deferred):** contrary to this entry's own preview
language above ("add it to the grid, N=32"), **all 4 declared cells** — not just
survivors — are added to the deduplicated grid, matching this study's own established
practice (Tier-4 cells are counted in every other module's `N_tests` contribution too;
FDR corrects across everything tested, not just the interesting results). New N = 31 +
4 = **35**. Re-running `benjamini_hochberg` at q = 0.10 and q = 0.05: **0 of 35
rejected at either level.** `dist_from_52w_low`, 126d is now the smallest Wald p-value
in the study's entire grid (0.0047, rank 1 of 35, vs. its own BH threshold of
0.002857 — a 1.64× miss, the closest any cell in this study has come). Full ranked
table: `STATUS.md`'s "Whole-grid FDR pass" section (2026-09-20 update). `dist_from_
52w_low`, 63d (p = 0.0667) is not close.

**Study-termination status, updated:** this module does not reopen the study's overall
verdict — the whole-grid pass, re-run against the larger grid, still finds zero
survivors, and `REPORT.md`'s headline (0 Tier 1/2, negative-leaning finish) is
unchanged. What it adds: a fourth Tier-3 cell, the closest individual result to
clearing FDR this study produced, and a clean resolution of the George & Hwang
sign question for `dist_from_52w_high` specifically. `STATUS.md` and `REPORT.md`
updated in the same session, not left stale against this new result.

**Logged:** `EXPERIMENTS.csv` (7 rows: 4 primary cells + 2 reversal-robustness checks +
1 updated whole-grid FDR summary row); `FINDINGS.md` (2 new entries, both `dist_from_
52w_low` cells, plus the FDR re-run addendum); `STATUS.md` (module table, whole-grid
FDR pass section, termination section); `REPORT.md` (executive summary, shrinkage
table, FDR table, module results, suggestive findings, dead-ends register, cost
appendix — all updated to reflect M18).

---

## M7 — Ribbon compression / expansion (2026-09-22)

**Module / track:** M7, Track B (DESIGN.md M7, lines 925-929). Not part of the original
minimal-core list (DESIGN §12) — added post-termination via DESIGN §1.5's porous-scope
rule, same precedent as M18. Promoted from the coordinating session's own Batch-1
scoping pass (2026-09-21): M7 was identified as one of the cheapest remaining modules
in DESIGN's full M0-M18 list — it reuses the existing {20,50,150,200} SMA lookbacks
already in the cached panel, needs no new crossover/regime/survival machinery, and no
raw-DB joins.

**Hypothesis (DESIGN's own):** low MA dispersion (compression) precedes volatility
expansion; direction of that expansion is *not* predictable from compression alone,
except weakly, conditional on prior trend (DESIGN's own prior: "vol prediction works
... direction prediction does not, except conditional on prior trend, where it's
weakly momentum-ish. Worth stating clearly because the folklore conflates the two.").

**New machinery:** two small additions, both new files/functions, neither touching
`features/panel.py` or any other module's files (this module ran alongside three
sibling forks working on M6.1/M6.3/M13 in parallel, in isolated worktrees — the
per-module-local-feature convention every prior module in this study already follows
is what keeps that safe):
- `features/ribbon.py::ribbon_width` — coefficient-of-variation dispersion
  (std/mean) of the four already-cached, already-lagged SMA columns at each row.
  Needs no re-lagging of its own (arithmetic on already-lagged inputs).
- `features/ribbon.py::ribbon_width_pctile` — per-ticker rolling min-max scaling of
  `ribbon_width` over a trailing 252-day window (same window convention as
  `distance.py::DIST_Z_WINDOW`/`context.py::FIFTY_TWO_WEEK_WINDOW`). **Deliberately an
  approximation, not an exact rolling percentile rank**: an exact rank would need an
  O(n×window) rolling `.apply` per ticker; min-max range position is fully vectorized
  (rolling min/max only) and is the same construction family this codebase's own
  `dist_from_52w_high`/`dist_from_52w_low` already use for an analogous "position
  within a trailing range" question. Stated explicitly here rather than silently
  presented as a true percentile.
- `labels/forward_returns.py::forward_realized_vol` — std of the next `horizon` daily
  simple returns (matches `realized_vol_63`'s own convention: simple returns, not log,
  non-annualized). A forward-looking **label**, not a feature — CLAUDE.md's one-bar-lag
  invariant constrains features used to condition on a forward outcome, not labels,
  same as `forward_return` itself.

**Method:** `ribbon_width_pctile` bucketed into 10 deciles (0 = most compressed, 9 =
most dispersed, via `floor(pctile × 10)` — a direct binning of the already-[0,1]-scaled
value, not a per-date `cross_sectional_bucket` cut, since this is a per-ticker
time-series measure, not a cross-sectional one). Five primary cells, all reusing this
study's existing block-bootstrap primitives unchanged (`stats/inference.py
::block_bootstrap_spread`/`block_bootstrap_delta`, M4/M11/M18's and M6.2's own):
1. **Vol expansion, standard C2** (`mom_tercile`/`vol_tercile`/`sector`): decile-9-minus-
   decile-0 spread of `fwd_vol_21` (forward 21-day realized vol).
2. **Vol expansion, C2 without `vol_tercile`**: same spread, `mom_tercile`/`sector` only
   — see "Control tier and why" below for why both readings are reported.
3. **Direction, unconditional (signed)**: decile-9-minus-decile-0 spread of `fwd_ret_21`.
4. **Direction, unconditional (magnitude)**: decile-9-minus-decile-0 spread of
   `fwd_absret_21` (`|fwd_ret_21|`) — a distinct question from vol_21 (a single
   cumulative 21-day move's magnitude vs. the full window's realized vol), both named
   by DESIGN, kept as separate cells rather than collapsed into one.
5. **Direction, conditional on trend**: within the compressed (decile-0) population
   only, C2 delta of `fwd_ret_21` between `prior_trend_up` (`mom_12_1 > 0`) and
   `prior_trend_up=False` — DESIGN's own "weakly momentum-ish, conditional on trend"
   sub-claim, the one cell where direction is expected to show up.

**Kill criterion, per cell (a floor keyed to the value type, same convention every
prior module uses — no single number DESIGN gives for this module, so each floor is
stated and justified here rather than assumed):**
- Cells 1-2 (vol-expansion, `value_col=fwd_vol_21`): `max(|ci_low|,|ci_high|) < 0.001`
  (absolute, daily-return-std units) → killed. Calibrated against this panel's own
  `realized_vol_63` distribution (median ≈0.0146, IQR [0.0113, 0.0194]) — 0.001 is
  ≈7% of the median level, a floor meant to rule out a trivially small but
  CI-excluding-zero shift, not derived from a DESIGN-stated formula.
- Cells 3-5 (return-based, `value_col∈{fwd_ret_21, fwd_absret_21}`):
  `max(|ci_low|,|ci_high|) < 0.10%` — this study's own standard floor (M1/M2/M6.2).

**Control tier and why:** C2 (`mom_tercile`/`vol_tercile`/`sector`) is this study's
standard tier, used for cells 3-5 without modification. For the two vol-expansion
cells (1-2), this study's usual `vol_tercile` match column is in direct tension with a
hypothesis that's partly *about* vol itself — matching on trailing 63-day realized vol
before testing whether compression predicts a change in vol risks partially matching
away the very effect being tested. Both readings are reported side by side rather than
picking one: cell 1 (with `vol_tercile`) is the conservative, standard-tier reading;
cell 2 (without it) is the more literal test of the hypothesis. Neither is designated
"primary" over the other up front — both count toward this module's `N_tests`
contribution (see below), and the write-up will report both numbers rather than
picking whichever is more favorable after the fact.

**Cost annotation:** cells 3-5 (direction/magnitude) imply a tradeable claim if
confirmed — CLAUDE.md invariant #8 applies, using `stats/costs.py::signals_per_year`
on a compressed-decile membership flag, same convention as every prior module. Cells
1-2 (vol expansion) are a forecast-quality/mechanism read, not directly tradeable on
their own (same "not applicable" convention M5 used for hold-rate cells) — stated
explicitly rather than skipped silently.

**Grid size (`N_tests` contribution):** 5 primary cells. No companion/redundancy
exclusions — each cell is a distinct outcome column or a distinct row restriction, not
a re-parameterization of another cell in this grid.

**Plateau check (DESIGN §6.7):** not a lookback-neighborhood question (this module has
no lookback grid — one ribbon, {20,50,150,200}, is the whole feature) — read instead as
internal consistency across the two vol-expansion readings (cells 1-2, C2 with/without
`vol_tercile` — should agree in sign and rough magnitude if the effect is real and not
an artifact of the match-column choice) and between the unconditional (cell 3) and
trend-conditional (cell 5) direction cells (DESIGN's own prior: cell 3 should be
null/weak, cell 5 should show more signal than cell 3 — if cell 3 is *stronger* than
cell 5, that would contradict DESIGN's own stated prior and needs scrutiny, not a
comfortable "still directionally consistent" wave-through).

**Effective N:** distinct dates and tickers per cell, standard invariant (CLAUDE.md
#6) — expected to comfortably clear DESIGN §6.9's floor (200 events, ≥30 dates, ≥30
tickers) given this reuses the full U1 panel population, flagged per cell if not.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents, dev window
2010-01-04 → 2021-12-31), `fwd_ret_21`/`fwd_absret_21`/`fwd_vol_21` all at the 21-day
horizon this study uses throughout.

**Whole-grid FDR pass:** this module ran after the whole-grid FDR pass already
executed (`STATUS.md`, most recently N=35, 2026-09-20). Per M18's own established
"FDR re-entry" precedent: if any cell here survives its own kill criterion and (for
cells 3-5) clears cost, it gets flagged as **pending whole-grid FDR re-entry** in its
`EXPERIMENTS.csv` row, not reported as a standalone significance claim — a consolidated
re-run against the larger grid happens once, after this module and its sibling
Batch-1 forks (M6.1, M6.3, M13) have all landed, not run separately here.

### Result (2026-09-22)

Ran against the real U1 panel (405 S&P 500 constituents, 2010-01-04 → 2021-12-31).
**A real bug found and fixed before trusting anything below**: `features/ribbon.py
::ribbon_width` and `labels/forward_returns.py::forward_realized_vol` both initially
used pandas' default `skipna=True` on a row-wise `.std(axis=1)`/`.mean(axis=1)` — this
silently computed a width/vol from *fewer than all four SMAs* (or fewer than `horizon`
forward returns) instead of propagating NaN when one input was still in its warmup
window, arithmetic NaN-propagation working differently than the comparison-operator
case CLAUDE.md invariant #9 names, but the same class of "missingness silently
dropped" bug. Caught by this module's own new tests
(`test_ribbon_width_is_coefficient_of_variation_of_the_four_smas`,
`test_forward_realized_vol_matches_hand_computed_std_of_forward_daily_returns`), fixed
with explicit `skipna=False`, and the real-panel run below reflects the fixed version
only (an initial buggy run's numbers were discarded, not reported anywhere).

| outcome | match | n_events | n_dates | n_tickers | c2 | ci_low | ci_high | edge | kill_threshold | killed | ci_excludes_zero |
|---|---|---|---|---|---|---|---|---|---|---|---|
| vol_expansion | c2_standard | 175,152 | 2,549 | 402 | +0.000214 | −0.000069 | +0.000573 | 0.000573 | 0.001 | **True** | False |
| vol_expansion | c2_no_vol_match | 175,152 | 2,549 | 402 | +0.000277 | −0.000180 | +0.000827 | 0.000827 | 0.001 | **True** | False |
| direction_signed | — | 175,152 | 2,549 | 402 | −0.002039 | −0.004660 | +0.000915 | 0.004660 | 0.001 | False | False |
| direction_magnitude | — | 175,152 | 2,549 | 402 | **−0.002471** | **−0.003976** | **−0.000927** | 0.003976 | 0.001 | False | **True** |
| direction_conditional_on_trend | — | 136,572 | 2,549 | 402 | −0.000784 | −0.004972 | +0.003202 | 0.004972 | 0.001 | False | False |

**Vol expansion — killed cleanly under both C2 readings.** Both the standard C2
(`+0.000214`, CI spans zero) and the no-vol-match C2 (`+0.000277`, CI spans zero) fall
under the pre-registered 0.001 floor and don't distinguish from zero — the two
readings agree in sign and rough magnitude (internal-consistency plateau check named
in the pre-registration above: **passes**, not a lone-pixel read). DESIGN's own "vol
prediction works" prior does **not** hold in this specific construction (a 21-day
forward realized-vol decile spread on `ribbon_width_pctile`'s min-max-scaled
compression measure) — a clean negative, not an ambiguous one.

**Direction, unconditional — inconclusive, consistent with DESIGN's own prior of no
effect.** `−0.002039`, CI spans zero. Descriptive shape stats (CLAUDE.md invariant
#10, no CI/kill authority): hit rate 61.7% (C2 delta +1.03pp vs. control), win/loss
ratio 1.13, skew −0.30 — a mild negative skew on the compressed-decile population's
own return distribution, not itself a claim.

**Direction, magnitude — confirmed, the one real cell in this module.** `−0.002471`,
CI `[−0.003976, −0.000927]`, excludes zero, clears the 0.10% floor. Read: among
already-compressed-ribbon rows (decile 0), the subsequent 21-day |return| is larger
than among already-dispersed-ribbon rows (decile 9) — a real, if partial, vindication
of the compression-precedes-a-bigger-move idea, showing up in *net cumulative
displacement magnitude* rather than in the *full-window realized-vol* measure the
vol-expansion cells tested. Shape stats not computed for this cell (a `|return|`
column is ≥0 by construction, so hit-rate/win-loss on it would be a degenerate,
near-100%-hit-rate non-statistic — restricted to genuinely signed outcomes only,
`ribbon_compression.py::_spread_cell`).

**Cost (invariant #8, triggered — this cell is confirmed):** compressed-decile
membership flag turnover 3.163 flips/ticker-yr → hurdle 0.3163%/yr (10bps/rt,
`costs.py`). Annualized (×12): point −2.97%/yr, near-zero edge −1.11%/yr, far edge
−4.77%/yr — **clears at every reading.** **Important caveat, named up front, not
buried**: `fwd_absret_21` is a *magnitude*, not a signed return — "clears cost" here
answers "is the shift in |return| bigger than the turnover cost of the flag," not "can
you make money going long or short this signal." Turning this into an actual monetizable
claim would need a specific strategy construction this cell doesn't test (e.g. a
long-volatility/straddle-style position, or a stop/position-sizing rule keyed to the
flag) — flagged as the live gap between "statistically real" and "actionable,"
distinct from every other Tier-3 cell in this study, whose confirmed cells are all
signed-return deltas.

**Direction, conditional on trend — inconclusive, and this itself is worth naming
plainly: it does *not* confirm DESIGN's own stated prior.** `−0.000784`, CI spans
zero. DESIGN's own text expected this cell (direction *within* the compressed
population, split by prior trend) to show *more* signal than the unconditional cell
above ("direction prediction does not [work], except conditional on prior trend,
where it's weakly momentum-ish") — it doesn't. Both the unconditional and
trend-conditional direction cells are CI-spans-zero nulls, not a case where the
conditional cell picks up signal the unconditional one misses. Stated as a partial
disconfirmation of DESIGN's own prior, not smoothed into "still broadly consistent."
Shape stats: hit rate 62.1% (C2 delta −0.03pp, essentially zero — no shape-level
signal either), win/loss ratio 1.14, skew −0.12.

**Argue against the one confirmed cell (`direction_magnitude`), per CLAUDE.md's own
"after running" step:** the leading candidate confound is short-term
reversal/mean-reversion, the same class this study has flagged repeatedly (M1/M2/M6.2's
own `rev_tercile` diagnostics) — decile 9 (already-dispersed ribbon) mechanically
correlates with tickers that already had a large *recent* price move (that's what
pushed the ribbon apart in the first place); if such tickers partially mean-revert,
their *subsequent* |return| would mechanically shrink relative to decile 0's, producing
exactly this cell's sign without "compression → expansion" being the real mechanism at
all. **Partial mitigation, not a full answer**: cells 3-5's C2 already matches on
`vol_tercile` (63-day trailing realized vol), which absorbs some but not all of this —
a ticker's 63-day vol level isn't the same as "just had a big move in the last few
days," which is exactly the gap `mom_1_0`/`rev_tercile` exists to close elsewhere in
this study. **Not run here** — a `rev_tercile`-augmented C2 check (this study's own
established diagnostic) is the natural next step to resolve this, left as an explicit
open item rather than run speculatively in this pass.

**Tier:** 3 for `direction_magnitude` — capped by the same missing FDR/holdout
infrastructure every Tier-3 cell in this study carries, *and* by the
signed-vs-magnitude actionability caveat named above (a second, cell-specific cap, not
just the study-wide one). Tier 4 for the other four cells (2 cleanly killed, 2
inconclusive — CLAUDE.md's own convention: a Tier-4 CI-spans-zero result is still a
real, reported outcome, not silence).

**Pending whole-grid FDR re-entry:** `direction_magnitude` clears its own kill
criterion and cost hurdle — per this entry's own "FDR re-entry" statement above, it is
flagged pending, not reported as a standalone significance claim. The consolidated
re-run happens once, after this module and its three sibling Batch-1 forks (M6.1, M6.3,
M13) have all landed — not run separately here.

**Logged:** `EXPERIMENTS.csv` (5 rows); `FINDINGS.md` (1 new entry, `direction_magnitude`).

### Result (reversal-robustness addendum, 2026-09-23)

The entry above named the exact open item this addendum resolves: `direction_magnitude`'s
leading candidate confound is short-term reversal/mean-reversion, left explicitly unrun
at pre-registration. Same construction as M6.2's/M6.3's own reversal-robustness
addenda and `modules/slope_conditioner.py`'s `C2_MATCH_COLS_WITH_REVERSAL` precedent: a
`rev_tercile` column (per-date tercile of `mom_1_0`, the prior 1-day return) added to
`modules/ribbon_compression.py::prepare()`, and a `C2_MATCH_COLS_WITH_REVERSAL =
(*C2_MATCH_COLS, "rev_tercile")` match set passed into `_spread_cell` alongside the
existing default-C2 run — both computed fresh in the same pass, on the real cached U1
panel (402-ticker coverage, 2010-01-01→2021-12-31).

**Survives — if anything slightly stronger, not explained by reversal.** Default C2
(this addendum's own fresh rerun): `c2=-0.002471`, CI `[-0.003976,-0.000927]` — matches
the originally-logged row exactly (no reproducibility drift, unlike M6.2's addendum).
With `rev_tercile` added: `c2=-0.002660`, CI `[-0.004238,-0.001027]` (n_events 175,152
→ 175,152, n_dates 2,549 → 2,549, unchanged — the decile-0/decile-9 restriction already
determines row membership). The point estimate is ~7.6% *larger* in magnitude, not
smaller, and the CI still excludes zero by a wide margin.

**Reading:** the leading confound named at pre-registration — decile 9's dispersed
ribbon mechanically correlating with a ticker that just had a large recent move, then
partially mean-reverting — does not account for this cell's gross number. Matching out
1-month-scale reversal (`mom_1_0`) leaves the effect intact, sharpened rather than
attenuated, the same direction M6.3's own SMA50 cell moved under the identical check.
This does not change the cell's tier (already Tier 3, still capped by missing
FDR/holdout infrastructure and the magnitude-vs-signed-return actionability gap named
at pre-registration) or its pending whole-grid FDR re-entry — but it removes the single
most consequential open caveat this module's own write-up carried.

**Logged:** `EXPERIMENTS.csv` (1 new row, `ribbon_direction_magnitude_reversal_robustness`);
`FINDINGS.md`'s `direction_magnitude` entry updated with this result in place of its
prior "leading confound... not tested here" open item.

---

## M6.3 — Slope magnitude: monotonic or humped? (2026-09-22)

**Module / track:** M6.3, Track B (DESIGN.md, "M6.3 — Slope magnitude: monotonic or
humped?"). Not part of the original minimal-core list (DESIGN §12) — post-termination,
DESIGN §1.5's porous-scope rule, same standing as M18. Promoted directly from DESIGN's
own module list (not a Track-A-discovered candidate) as part of a scoping pass over
every not-yet-run module in DESIGN.md, done in parallel with three sibling modules
(M6.1, M7, M13) each in their own isolated worktree/branch.

**Hypothesis (DESIGN's own):** forward return is non-monotonic in slope magnitude —
some trend is good, too much is exhaustion.

**Two logged deviations from DESIGN's literal method text, both load-bearing for this
module's design, stated up front rather than buried in a result section:**

1. **`slope_atr_21` is not built.** DESIGN's method line asks for "decile buckets of
   `slope_atr_21` and `slope_pctile_21`." `slope_atr_21` — an ATR-normalized,
   price-unit slope, `(ma_t − ma_{t−21}) / atr_14` — directly conflicts with CLAUDE.md
   invariant #7: "Log scale for slopes. `slope_log_k` only. Percentage and price-unit
   slopes are not comparable across tickers." `features/slope.py`'s own docstring
   independently confirms this: `slope_pct_k`/`slope_atr_k` were deliberately excluded
   from Phase 2 because `slope_log_k` is "the only scale-invariant version" CLAUDE.md's
   invariant permits. This module therefore uses **`slope_pctile_21` only** — a
   per-date cross-sectional decile rank of the existing, already-lagged, log-scale
   `slope_log_21_sma_k` column. This is DESIGN's own named alternative formulation in
   the same sentence, not an invented substitute, and it never leaves log scale.
2. **The "earnings-excluded companion" DESIGN asks for is a proxy, not the real
   thing.** No earnings-date table exists anywhere in this repo's raw-data DB (checked
   directly: `bars_1d/1h/1mo/1w`, `fetch_jobs`, `index_membership`, `macro_series`,
   `shares_outstanding`, `splits`, `ticker_metadata`, `ticker_sector`, `tickers` — none
   is earnings-related, same gap M6.3's own sibling check for M13 independently
   confirmed). Substituted with a `recent_large_move` exclusion flag: an event day
   preceded within the trailing 5 trading days by a single-day |return| > 7% is
   excluded from the companion population. First-pass thresholds, not DESIGN-derived —
   flagged as a proxy, not claimed equivalent to a true earnings-proximity filter (a
   large move can be a buyout, a guidance cut, a macro shock; a genuine earnings drift
   with no single outsized day would be missed by this filter). Deliberately distinct
   from `data.py::flag_large_moves`'s own 50% threshold, which flags likely data
   errors for manual review, not real gap days — a different purpose, not reused here.

**Method:** `slope_pctile_21_sma_k` (`cross_sectional_bucket` on the already-cached,
already-lagged `slope_log_21_sma_k`, k ∈ {20, 50, 200} — DESIGN's own named
lookbacks) built in this module's own `prepare()`, not the shared cached panel (per
this study's established per-module-local-feature convention, so parallel modules
don't collide on `features/panel.py`). Two outputs per lookback:
- **`shape_table`** (descriptive): one row per decile (0–9) of `slope_pctile_21_sma_k`,
  C0/C1/C2 point-estimate deltas on `fwd_ret_21` — same construction as M4's own
  `decile_table`, reused pattern, no bootstrap CI (a shape read, not a hypothesis
  test in itself — "Plots before tests," CLAUDE.md's own style rule).
- **`humped_test`** (the one CI-backed decisive test per lookback): C2 block-bootstrap
  delta (`stats/inference.py::block_bootstrap_delta`, reused unchanged, block length
  42, 500 draws, 90% CI, seed 0) of `fwd_ret_21` between the pooled middle deciles
  (4, 5) and the pooled tail deciles (0, 1, 8, 9) — restricted to only those 6
  deciles' rows first, then a group_col=`is_middle` delta, same restrict-then-delta
  pattern M6.2's `_delta_cell` established. Run twice per lookback: once on the full
  population, once on the `recent_large_move`-excluded companion population
  (deviation 2, above).

**Kill criterion:** DESIGN states none explicitly for M6.3 (framed as a
shape-characterization question, not a binary claim) — stated here, following this
study's own standard floor for a return-valued cell: `max(|ci_low|,|ci_high|) < 0.10%`
(M1/M2/M6.2's own floor) on `humped_test`'s middle-vs-tails delta → **killed** (no
humped or U-shaped structure at this control tier; read `shape_table`'s per-decile
point estimates for a monotonic-vs-flat characterization instead, descriptively, not
as a second hypothesis test). CI excluding zero, positive, clearing the floor →
**humped** (middle beats tails). CI excluding zero, negative, clearing the floor →
**U-shaped** (tails beat the middle).

**Control tier and why:** C2 (`mom_tercile`, `vol_tercile`, `sector`) — this study's
standard tier, applied here for the same reason DESIGN itself names: "a steep slope in
ATR units and a high-vol name are not the same thing, and the same trap from M4
applies here" — vol_tercile matching is this study's standing answer to that
confound.

**Cost annotation:** `shape_table` is descriptive, not a claim (CLAUDE.md invariant #8
doesn't apply to it directly). If `humped_test` confirms a middle-vs-tails effect,
that does imply a tradeable claim (a return delta between two identifiable
populations) — invariant #8 requires a cost annotation before it's stated as such,
using the combined middle-vs-tail membership flag's own turnover
(`stats/costs.py::signals_per_year`, same convention as every prior module), computed
only if triggered.

**Grid size (`N_tests` contribution):** **3 primary cells** — one `humped_test` per
lookback (20, 50, 200), full population. The `recent_large_move`-excluded companion
runs are a robustness check on the same 3 cells (same convention as this study's own
reversal-robustness addenda — M2, M18, M6.2), not 3 additional independent tests. The
30 `shape_table` rows (3 lookbacks × 10 deciles) are descriptive, not a hypothesis
test each — same convention as M4's own `decile_table`, which never counted its 90
bucket-level rows as 90 independent tests either.

**Effective N:** distinct event dates and tickers per cell, standard invariant —
`humped_test`'s restricted 6-decile population is expected to be smaller than a
full-panel cell but still large relative to DESIGN §6.9's floor (200 events, ≥30
dates, ≥30 tickers), flagged via `below_threshold` if any cell falls short, same
convention as every prior module.

**Plateau check (DESIGN §6.7):** applied as consistency across the three lookbacks
(20/50/200) — a humped/U-shaped read that only shows up at one lookback with the other
two flat is the "lone bright pixel" pattern this study has already caught once
(the 2026-09-18 distance × slope generalization, `EXPLORATION_LOG.md`) and should be
read the same way here, not as three independent confirmations.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents, dev window
2010-01-04 → 2021-12-31), `fwd_ret_21` (this study's standard horizon).

**New machinery:** `slope_magnitude.py`'s own `prepare`/`shape_table`/`humped_test`/
`run_grid` — the only genuinely new statistical component is the middle-vs-tails
restrict-then-delta construction; everything else (`cross_sectional_bucket`,
`c0_delta`/`c1_delta`/`c2_delta`, `block_bootstrap_delta`) is reused unchanged. New
column: `recent_large_move` (lagged via the shared `features/panel.py::apply_lag`,
not a hand-rolled shift, per CLAUDE.md invariant #2).

### Result (2026-09-22)

**DESIGN's literal hypothesis (humped: middle beats tails) is not what was found.**
All three lookbacks show the opposite shape — **U-shaped: the pooled tail deciles
(0, 1, 8, 9 — the steepest slope magnitude in either direction) outperform the pooled
middle deciles (4, 5 — the flattest slope) on `fwd_ret_21`**, C2-controlled, CI
excluding zero, clearing the 0.10% kill floor at all three lookbacks. Stated plainly
since it's the opposite of what was pre-registered as the hypothesis to test: this is
a real, honestly-reported result, not the one DESIGN predicted going in.

| lookback | c2 (21d) | 90% CI | edge | killed | n_events | n_dates | n_tickers |
|---|---|---|---|---|---|---|---|
| 20 | −0.1173% | [−0.2286%, −0.0063%] | 0.2286% | False | 219,654 | 2,747 | 402 |
| 50 | −0.2480% | [−0.3540%, −0.1528%] | 0.3540% | False | 219,700 | 2,747 | 402 |
| 200 | −0.1928% | [−0.3370%, −0.0556%] | 0.3370% | False | 219,731 | 2,747 | 402 |

**Cost (invariant #8, triggered — all three cleared their kill floor):** turnover
measured on the `is_middle` state-flip flag (`stats/costs.py::signals_per_year`,
10bps/rt, same convention as every prior module), annualized at this study's standard
×12 (21d cells):

| lookback | signals/yr | hurdle/yr | point (×12) | near edge | far edge | verdict |
|---|---|---|---|---|---|---|
| 20 | 13.365 | 1.3365% | −1.408% | **−0.075%** | −2.743% | **fails** (near edge misses) |
| 50 | 7.691 | 0.7691% | −2.976% | **−1.833%** | −4.248% | **clears at every reading** |
| 200 | 3.819 | 0.3819% | −2.313% | **−0.668%** | −4.044% | **clears at every reading** |

**Recent-large-move-excluded companion (this module's proxy for DESIGN's
"earnings-excluded" robustness check — see the deviations section above):**

| lookback | c2 (excl.) | 90% CI (excl.) | ci_excludes_zero | vs. full-population read |
|---|---|---|---|---|
| 20 | −0.1167% | [−0.2373%, **+0.0009%**] | **False** | **effect vanishes** once large-move days are excluded |
| 50 | −0.2637% | [−0.3759%, −0.1676%] | True | essentially unchanged (if anything slightly larger) |
| 200 | −0.1693% | [−0.3120%, −0.0297%] | True | survives, magnitude modestly smaller |

**Reading, per lookback:**
- **SMA50 and SMA200 are the real result of this module**: CI excludes zero, clears
  cost at every reading, and — critically — **survives the large-move-exclusion
  companion largely intact**, arguing against "this is just gap/earnings
  contamination in the tails." **Tier 3** for both, capped by this study's standard
  missing FDR/holdout infrastructure (not by cost or by this particular confound
  check).
- **SMA20 is the weakest of the three and does not reach the same status.** It clears
  its own kill floor on the primary read, but (a) **fails the CI-based cost test**
  (near edge −0.075%/yr misses the 1.3365%/yr hurdle by a wide margin — the shortest
  lookback also has by far the highest turnover, same shape M1's lb20 and M4's SMA20
  facets showed), and (b) **does not survive the large-move-exclusion companion at
  all** (CI flips to spanning zero). Read: SMA20's gross number looks substantially
  driven by exactly the gap-contamination mechanism DESIGN's own "watch for" line
  named — not a real U-shape at the shortest lookback, or at least not one
  distinguishable from that confound with this test. **Tier 3 on the literal
  CI-excludes-zero rule, but functionally closer to a dead end than SMA50/200** — logged
  as such, not silently upgraded to match its siblings.

**Plateau check (as pre-registered):** all three lookbacks agree in sign (middle
underperforms tails) — not a lone bright pixel on the headline sign. But the *shape*
is not uniform: SMA50/200 show a roughly symmetric U (both tails elevated, per
`shape_table`'s per-decile C2 point estimates — e.g. SMA200: decile 0 = +0.253%,
decile 9 = +0.389%, both clearly positive), while SMA20's lift is concentrated on the
falling side (decile 0 = +0.104%, decile 1 = +0.125%) with the rising side barely
positive to negative (decile 8 = −0.062%, decile 9 = +0.015%) — an asymmetric shape,
consistent with the large-move-exclusion companion result above (SMA20's effect is
mechanistically different from, not just a noisier version of, SMA50/200's).

**Argue against SMA50/200 specifically (not resolved here, flagged as live
alternatives — this is the single most important open item this module leaves):** **no
short-term-reversal control was run** (`rev_tercile`/`mom_1_0`, this study's own
established check — M1, M2, M6.2, M18 all eventually got this, not run here). This
matters more than usual for this specific result: the U-shape's two tails plausibly
reflect two different mechanisms — the rising tail as momentum continuation, the
falling tail as a bounce/mean-reversion setup — and an uncontrolled 1-month reversal
effect would produce exactly the elevated-falling-tail component of this shape without
needing a real "slope magnitude" mechanism at all. The large-move-exclusion companion
rules out the crudest version of this (a one-day gap-and-bounce), but not a more
gradual multi-week reversal pattern `mom_1_0` would catch and `rev_tercile` would
control for. **What would change the verdict:** the reversal-robustness check;
the whole-grid FDR pass (this module has not been added to it — see below); a holdout
check.

**Shape stats (CLAUDE.md invariant #10, descriptive only):**

| lookback | hit_rate (middle) | hit_rate_delta_c2 | win/loss ratio (middle) | skew (middle) |
|---|---|---|---|---|
| 20 | 60.59% | +0.13pp | 1.110 | −0.342 |
| 50 | 60.40% | −0.84pp | 1.094 | −0.444 |
| 200 | 60.88% | −0.14pp | 1.101 | −0.459 |

The middle group's own hit rate is high (~60-61%) at every lookback, but its C2-matched
hit-rate *delta* is small and inconsistent in sign (slightly positive at SMA20, negative
at SMA50/200) — the mean-delta result above is not being driven by a clean hit-rate
story; skew is consistently negative for the middle group's own distribution. Descriptive
only, no kill authority (per the invariant).

**FDR re-entry:** this module runs after the whole-grid FDR pass already executed
(`STATUS.md`, N=35 as of the 2026-09-20 re-run). SMA50 and SMA200 both clear their own
kill criterion and cost — per this study's own established practice (Tier-3 cells get
added to the deduplicated grid and the pass re-run), **these 2 primary cells are
pending whole-grid FDR re-entry**, not yet added to `STATUS.md`'s ranked table. SMA20 is
also added to the `N_tests` count (3 primary cells total, matching this entry's own
declared grid size) even though its own robustness reading is weak — this study's
convention counts every declared cell, not just the interesting ones. **Not run in this
pass** — flagged for the coordinating session to fold in alongside its sibling
Batch-1 modules (M6.1, M7, M13), consistent with the instruction that individual
forked modules don't each run their own mini FDR pass.

**Logged:** `EXPERIMENTS.csv` (6 rows: 3 primary cells + 3 large-move-exclusion
robustness rows); `FINDINGS.md` (3 new entries — SMA20/50/200 all get one, matching
this study's actual convention: every Tier-3 cell gets a `FINDINGS.md` entry regardless
of whether it clears cost, same as M4's `dist_pct_sma_20`@21d, which also fails cost
and still has a full entry there. SMA20's own entry states its cost failure and
large-move-exclusion failure prominently, same as M4's own cost-failing entries do —
not a reason to omit it, per that established precedent).

### Result (reversal-robustness addendum, 2026-09-22)

Both entries above (SMA50, SMA200) flagged the same open caveat as the single most
important item left unresolved: no short-term-reversal control had been run, and the
U-shape's falling tail is exactly the shape an uncontrolled 1-month reversal effect
would produce. SMA20 is out of scope for this addendum — it already fails cost and
fails its own large-move-exclusion companion, so a reversal check cannot change its
verdict either way. Same construction as M6.2's own 2026-09-21 reversal-robustness
addendum and `modules/slope_conditioner.py`'s `C2_MATCH_COLS_WITH_REVERSAL` precedent:
a `rev_tercile` column (per-date tercile of `mom_1_0`, the prior 1-day return) added to
`modules/slope_magnitude.py::prepare()`, and a `C2_MATCH_COLS_WITH_REVERSAL =
(*C2_MATCH_COLS, "rev_tercile")` match set passed into `humped_test` alongside the
existing default-C2 run — both computed fresh in the same pass, on the real cached
U1 panel (405-ticker coverage, 2010-01-01→2021-12-31), for an apples-to-apples
comparison rather than diffing against the originally-logged numbers.

**SMA50 — survives, if anything slightly stronger.** Default C2 (this addendum's own
fresh rerun): `c2=-0.002480`, CI `[-0.003540,-0.001528]` (matches the originally-logged
row exactly — no reproducibility drift here, unlike M6.2's addendum). With
`rev_tercile` added: `c2=-0.002825`, CI `[-0.003886,-0.001754]` (n_events 219,700 →
219,700, n_dates 2,747 → 2,747, unchanged — the middle/tail decile restriction already
determines row membership). The point estimate is ~13.9% *larger* in magnitude, not
smaller, and the CI still excludes zero by a wide margin. **Not explained by reversal —
if anything, matching reversal out sharpens the read.**

**SMA200 — does not survive.** Default C2 (fresh rerun): `c2=-0.001928`, CI
`[-0.003370,-0.000556]` (also matches the originally-logged row exactly). With
`rev_tercile` added: `c2=-0.000376`, CI `[-0.001980,+0.001195]` (same n_events/n_dates,
219,731/2,747). The point estimate attenuates ~80.5% and **the CI now spans zero** —
inconclusive, not confirmed, once 1-month reversal is matched out.

**Reading:** the two cells diverge, the same shape of result M6.2's own reversal
addendum found between its Finding 1 and Finding 2 — one cell's effect is
reversal-independent, the other's gross number is now best read as substantially a
short-term-reversal artifact. Combined with `FINDINGS.md`'s own plateau note (SMA50/200
were "roughly symmetric," SMA20 was "asymmetric, falling-tail-driven" and already failed
its own robustness check), the honest whole-module read is: **only the SMA50 U-shape
cell is a real, reversal-robust effect; the SMA200 cell is no longer distinguishable
from reversal, and SMA20 was already the weakest link on independent grounds.** This
does not change either surviving cell's tier (both already Tier 3, both already pending
the same whole-grid FDR re-entry as every other Batch-1 cell) — but it changes which of
the two cost-clearing cells should be read as a genuine candidate mechanism versus a
confound re-encoding.

**Logged:** `EXPERIMENTS.csv` (2 new rows, dated 2026-09-22:
`slope_magnitude_humped_test_sma50_reversal_robustness`,
`slope_magnitude_humped_test_sma200_reversal_robustness`); `FINDINGS.md`'s SMA50 and
SMA200 entries both updated with this result in place of their prior "no
reversal-robustness check run" open caveat.

### Result (rising-vs-falling tail decomposition addendum, 2026-09-23)

**Module/track:** M6.3, Track B. **Promoted from:** the 2026-09-23 whole-grid FDR
consolidation (`STATUS.md`), which flagged a newly-surfaced, not-yet-resolved
caveat on SMA50's now-FDR-surviving cell: the pooled tail statistic (`TAIL_DECILES
= (0,1,8,9)`) includes the extreme-negative-slope deciles (0,1), a population
structurally similar to M1's/M2's already-capped "weak/bearish-state" buckets and
plausibly vulnerable to the same delisted-ticker survivorship ceiling (DESIGN §7.3,
zero delisted coverage before 2024) — a company approaching delisting would pass
through exactly that "sharply falling slope" bucket before disappearing from this
panel.

**Hypothesis:** if the effect is a genuine "extreme trend, either direction, beats
flat" phenomenon rather than a survivorship-inflated read of the falling tail
specifically, the rising-tail-only comparison (deciles 8,9 vs. middle deciles 4,5) —
a population with *no* survivorship exposure, since it's the strongly-bullish side —
should independently show a C2-excluding-zero effect of comparable sign and rough
magnitude to the pooled result, not a null or much-smaller one.

**Kill criterion:** if the rising-tail-only CI spans zero, or its point estimate is
much smaller than the falling-tail-only comparison's, the pooled SMA50 result is
better read as substantially driven by the (survivorship-exposed) falling tail —
the caveat would stand, not be resolved.

**Control tier:** C2 (`mom_tercile`, `vol_tercile`, `sector`) — identical to the
primary cell, for direct comparability, not the reversal-augmented match set (a
different confound, already separately resolved above).

**Method:** the same `prepare()`'d panel and `block_bootstrap_delta` primitive
`humped_test` itself uses, called twice on SMA50 with the tail restricted to one
side at a time instead of pooled — `{4,5}` vs. `{8,9}` (rising-tail-only) and
`{4,5}` vs. `{0,1}` (falling-tail-only) — same block length (42), draws (500), CI
(90%), seed (0) as the primary cell.

**Result: both sides independently confirm the effect, at nearly identical
magnitude.** Rising-tail-only: `c2=-0.2544%`, CI `[-0.4290%,-0.0846%]` — excludes
zero. Falling-tail-only: `c2=-0.2442%`, CI `[-0.4127%,-0.0959%]` — excludes zero.
(n_events_middle=219,700, n_dates=2,747, n_tickers=402, identical across both — the
middle group doesn't change; n_events_tail 221,609 rising / 221,604 falling, an
even split.) The two point estimates differ by under 5% of each other's magnitude
and both individually clear the CI-excludes-zero bar. **The rising tail — which has
zero exposure to the delisted-ticker survivorship mechanism — shows the same effect
on its own.** This directly rules out "the pooled result is a falling-tail
survivorship artifact" as an explanation: if it were, the rising-tail-only number
would be null or much smaller, not a near-exact match.

**Reading:** this is the last of SMA50's four confound checks (large-move exclusion,
reversal, whole-grid FDR, and now this) to have been *directly tested* rather than
argued by analogy. All four resolve in the cell's favor. Per DESIGN §9.2's Tier 2
definition ("survives C2 and FDR, but fails one of: universe generality, holdout, or
cost"), this cell now clears C2, FDR (both q=0.10 and q=0.05), and cost at every
reading, with its only remaining gaps being missing holdout and universe-tier
*infrastructure* — not failures. **Promoted to Tier 2** — the first Tier 2 result in
this study's history. See `STATUS.md`/`FINDINGS.md`/`REPORT.md`'s 2026-09-23
addenda for the full write-up.

**Logged:** `EXPERIMENTS.csv` (2 new rows, dated 2026-09-23:
`slope_magnitude_humped_test_sma50_rising_tail_only`,
`slope_magnitude_humped_test_sma50_falling_tail_only`); `FINDINGS.md`'s SMA50 entry
updated with the tier promotion and this result in place of the prior open
survivorship caveat; `STATUS.md`'s whole-grid FDR section and study-level-termination
section updated; `REPORT.md`'s executive summary updated to reflect the study's
first Tier-2 finding.

---

## M13 — Context conditioning (2026-09-21)

**Module / track:** M13, Track B. Not part of the original minimal-core list (DESIGN
§12) — added post-termination via DESIGN §1.5's porous-scope rule, one of a batch of
parallel post-termination modules scoped in the same session as M18 (the coordinating
session's own Batch-1 triage: modules that reuse existing infrastructure with no new
shared machinery, safe to run independently of one another).

**Promoted from:** DESIGN's own module list directly, not a Track A candidate — DESIGN's
text for this module (line 974) is short: "Earnings proximity, index membership
changes, sector momentum, market breadth (`pct_above_200d`), VIX percentile. Mostly
interaction terms on top of M1–M6 rather than standalone analysis." This entry
operationalizes that into a concrete, testable first slice rather than attempting all
four facets against all of M1–M6 at once — the same "first slice, not full spec"
discipline M1/M4/M5/M6.2 each used on their own first pass.

**Scope decisions, stated up front (not discovered mid-run):**
- **Earnings proximity is out of scope entirely.** This repo's DB (`bars_1d/1h/1mo/1w`,
  `fetch_jobs`, `index_membership`, `macro_series`, `shares_outstanding`, `splits`,
  `ticker_metadata`, `ticker_sector`, `tickers`) has no earnings-date table — building
  one is new data ingestion, not in scope for this module. A deliberate, named cut, not
  a silent omission.
- **Index-membership changes and sector momentum are explicitly deferred**, not
  attempted this slice — same "explicitly deferred" precedent M6.2 used for
  golden-cross × slope. Both are feasible with existing tables
  (`db.read_index_membership`, `ticker_sector`) if a later pass wants them.
- **This slice tests:** does M1's own `above_sma_200` conditional effect on
  `fwd_ret_21` hold equally across (a) a VIX regime (top vs. bottom trailing tercile of
  FRED's `VIXCLS`) and (b) a market-breadth regime (top vs. bottom trailing tercile of
  `pct_above_sma_200`, i.e. the fraction of the U1 universe above its own 200-day SMA
  on that date)? `above_sma_200` chosen (over `above_sma_50`/`above_sma_20`) because
  DESIGN's own regime-conditioning language (M9) centers on the long lookback, and
  because M1's own `above_sma_200` cell is this study's most-flagged SMA200 anomaly —
  an already-weak, borderline-CI baseline is exactly the kind of cell where a real
  regime interaction would be most visible if one exists.

**Hypothesis (skeptical, matching this study's own default framing for a conditioning
question):** the `above_sma_200` effect is not materially different across VIX or
breadth regimes — i.e. `above_sma_200` is not a regime-dependent signal, the same
weak/borderline effect M1 already found holds (or fails to hold) uniformly regardless
of market context.

**New machinery:** one small helper, `_rolling_tercile` (a trailing/rolling
percentile-rank bucket over a date-indexed series — **not** a full-sample `pd.qcut`,
which CLAUDE.md invariant #3 forbids here: a regime bucket for a 2015 date must not be
informed by 2021 VIX/breadth values). 252-trading-day trailing window, matching this
study's existing rolling-self-normalisation convention (`dist_z`). Everything else
reuses existing primitives unchanged: `stats.inference.block_bootstrap_delta`
(`modules/slope_conditioner.py`'s own "restrict-then-delta" pattern, sub-question 1's
exact shape — restrict the panel to a regime bucket, then C1/C2 delta of
`above_sma_200` on `fwd_ret_21` within it), `features.panel.apply_lag` (the one central
lag function — not a hand-rolled shift), `db.read_macro_series` (`VIXCLS`).

**Method:**
- `breadth_tercile`: per-date mean of the already-lagged `above_sma_200` column
  (cross-sectional aggregate across the U1 universe), then `_rolling_tercile` — no
  further lag needed, since it's built entirely from data already lagged in the cached
  panel.
- `vix_tercile`: `db.read_macro_series(conn, "VIXCLS")`, holdout-filtered (`<=
  2021-12-31`), `_rolling_tercile`, then `features.panel.apply_lag` — a VIX close on
  day *t* is not tradable information until day *t+1* (CLAUDE.md invariant #2). Since
  every ticker has exactly one row per date, shifting this date-level column forward
  one row *within each ticker* (`apply_lag`'s own grouping) is exactly a
  one-trading-day lag of the underlying date-level series.
- For each of the 4 (regime, bucket) combinations, restrict the prepared panel to that
  bucket, then `block_bootstrap_delta(group_col="above_sma_200", value_col=
  "fwd_ret_21", match_cols=("mom_tercile","vol_tercile","sector"))` — M1's own C2 spec,
  unchanged.
- Middle terciles (bucket = 1) are dropped, not tested — a clean two-sided top-vs-bottom
  comparison, the same "drop the middle tercile" convention the 2026-09-18 distance ×
  slope generalization script used to match M6.2's own binary construction.

**Kill criterion:** per cell, `max(|ci_low|,|ci_high|) < 0.10%` (M1's own floor — this
cell's statistic is the exact same shape as M1's primary cells, just row-restricted
first, so it inherits M1's threshold rather than inventing a new one) → killed (no
detectable `above_sma_200` effect in that regime bucket). **This floor answers "is
there any effect in this regime slice," not "does the regime change the effect"** —
the latter, the module's actual hypothesis, is read by comparing the top-bucket and
bottom-bucket point estimates/CIs against each other and against M1's own whole-sample
number, descriptively. A formal delta-of-deltas CI (a joint significance test on "does
the effect differ between regimes") was considered and **not built**: this study's
existing bootstrap primitives cover same-rows/different-columns
(`block_bootstrap_group_diff`) and same-column/different-decile-columns
(`block_bootstrap_spread_diff`), but not same-column/disjoint-row-subset differences —
building one is a new statistical primitive, out of scope for this first slice, and
flagged here as a named limitation rather than silently worked around.

**Control tier and why:** C2 (`mom_tercile`, `vol_tercile`, `sector`) as the base,
unchanged from every module in this study — the regime (VIX/breadth) is an additional
row-restriction on top of C2, not a replacement for it.

**Cost annotation:** applies (invariant #8) only to whichever cells, if any, have a
CI excluding zero — computed post-hoc for those cells only, using
`costs.signals_per_year` on the regime-restricted population's own `above_sma_200`
flip rate (a labeled simplification: this does not additionally account for turnover
from entering/exiting the regime bucket itself, only from the state flipping within
it — flagged, not hidden, same "labeled approximation" convention this study's cost
math already uses elsewhere).

**Grid size (`N_tests` contribution):** 4 primary cells (2 regimes × 2 buckets).
Declared independent at declaration: VIX and breadth are two different underlying
series (FRED macro data vs. an aggregate of the panel's own cross-sectional state), not
two normalisations of the same quantity — no correlation check performed before
declaring independence here (unlike M4/M18's own facet-correlation checks), flagged as
a gap for the eventual whole-grid FDR pass to verify rather than assumed away.

**Shape stats (CLAUDE.md invariant #10, forward-looking, applies to this module):**
`stats/shape.py`'s `hit_rate_deltas`/`distribution_shape` computed for the event
(`above_sma_200=True`) side of each of the 4 cells, reported alongside the mean/CI —
descriptive only, no kill authority, no `N_tests` contribution.

**Effective N:** distinct event dates and tickers per cell, standard invariant — see
Result section below.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents, dev window
2010-01-04 → 2021-12-31, holdout-safe), `fwd_ret_21` (M1's own horizon, since this
module directly extends M1's own cell).

### Result (2026-09-22)

| regime | bucket | n_events | n_dates | n_tickers | c1 | c2 | ci_low | ci_high | edge | killed | ci_excludes_zero |
|---|---|---|---|---|---|---|---|---|---|---|---|
| vix | top | 171,836 | 786 | 402 | −0.195% | −0.078% | −0.389% | +0.258% | 0.389% | no | no |
| vix | bottom | 392,184 | 1,195 | 402 | −0.039% | **−0.318%** | **−0.551%** | **−0.073%** | 0.551% | no | **yes** |
| breadth | top | 298,354 | 882 | 402 | −0.044% | **−0.388%** | **−0.690%** | **−0.074%** | 0.690% | no | **yes** |
| breadth | bottom | 205,085 | 871 | 402 | −0.254% | −0.087% | −0.375% | +0.189% | 0.375% | no | no |

None of the 4 cells is killed by the per-cell 0.10% floor. 2 of 4 (`vix`/bottom,
`breadth`/top) have a C2 CI excluding zero; the other 2 span zero.

**Reading the actual hypothesis (does regime change the effect), not just "is there an
effect in this slice":** **No — this does not look like a real regime interaction.**
All 4 point estimates are the same sign (negative) as M1's own whole-sample
`above_sma_200` number (−0.215%, `EXPERIMENTS.csv`) and all 4 sit within a narrow band
(−0.078% to −0.388%) around it — no cell flips sign, and no cell is dramatically larger
in magnitude than M1's own baseline (the largest, `breadth`/top at −0.388%, is under
2× the whole-sample point estimate, well within the range ordinary sampling noise
around an already-small, already-borderline-CI number would produce). The 2
CI-excluding-zero cells are not obviously the *economically distinct* half either:
`vix`/bottom and `breadth`/top are not the two "config in the same direction" buckets
by any a priori story this entry's hypothesis section proposed — the pattern reads more
like "which side of a near-zero, already-thin split happens to land with a
CI-excluding-zero draw" than a coherent, single regime-driven story.

**Argue against this result (per CLAUDE.md's own discipline):** M1's own
`above_sma_200` whole-sample cell already has a CI that "touches zero" and is this
study's most heavily flagged SMA200 anomaly (`STATUS.md`'s cross-module SMA200 watch).
Splitting an already near-zero, borderline cell into two independent binary facets (4
buckets total) and finding that *some* buckets' CIs exclude zero while others don't is
close to the base-rate outcome you'd expect from resampling variation alone, not
necessarily evidence of a real regime-conditional mechanism — this is exactly the kind
of pattern DESIGN's own multiple-testing discipline exists to catch, and it's the
central reason this entry treats the "regime changes the effect" question as answered
**no** despite 2 of 4 cells individually clearing their own CI-excludes-zero /
cost bars.

**Cost annotation (invariant #8, computed for the 2 CI-excluding-zero cells only):**
Turnover measured as `above_sma_200`'s own flip rate *within* the regime-restricted
population (a labeled simplification — does not additionally count turnover from
entering/exiting the regime bucket itself).
- `vix`/bottom: 6.894 flips/ticker-yr → hurdle 0.689%/yr. Annualized (×12): point
  −3.82%/yr, near edge −0.87%/yr, far edge −6.61%/yr. **Clears at every reading**
  (barely, at the near edge).
- `breadth`/top: 6.404 flips/ticker-yr → hurdle 0.640%/yr. Annualized (×12): point
  −4.66%/yr, near edge −0.88%/yr, far edge −8.28%/yr. **Clears at every reading**
  (barely, at the near edge).

**Shape stats (invariant #10, descriptive only):**
- `vix`/bottom: hit rate 57.09% (C2 delta −0.81pp), win/loss ratio 1.11, skew +0.30.
- `breadth`/top: hit rate 57.72% (C2 delta +0.15pp), win/loss ratio 1.02, skew −0.74.
Neither shows a shape signature that reinforces the mean-delta story the way
`stack_fully_bearish` did (M2) — `vix`/bottom's hit-rate delta is *negative* despite a
negative mean delta (consistent), but `breadth`/top's hit-rate delta is essentially
zero/slightly positive despite a negative mean delta (inconsistent with a clean
"more frequent small losses" story) — another data point against reading these as a
coherent effect.

**Plateau check:** not applicable in the usual lookback-neighborhood sense (this
module has no neighboring lookback/parameter to compare against) — the "argue against"
discussion above is this cell's substitute plateau-style skepticism check.

**Tier:** per this study's own mechanical tiering convention (CI excludes zero + clears
cost → Tier 3, capped by missing FDR/holdout infrastructure, same as every other
Tier-3 cell in this study), `vix`/bottom and `breadth`/top are **Tier 3**. This entry's
own "argue against" section above should be read alongside the tier, not overridden by
it — this study's convention tiers mechanically and lets the accompanying prose carry
the skepticism (same pattern M6.2's `touch_x_slope` used before its own
reversal-robustness check). **Pending whole-grid FDR re-entry** (M18's own phrasing) —
not run here; the coordinating session re-runs the whole-grid pass once, after all
Batch-1 modules land. `vix`/top and `breadth`/bottom are **not tiered** (CI spans
zero, not killed — inconclusive, same convention as every other module's
CI-spanning-zero cells).

**Effective N:** see table above (n_dates 786–1,195 per cell, n_tickers 402 — all well
above DESIGN §6.9's minimum-sample floor).

**Logged:** `EXPERIMENTS.csv` (4 rows); `FINDINGS.md` (2 new entries, `vix`/bottom and
`breadth`/top, both carrying this entry's own "argue against" reasoning in full — not
presented as clean standalone findings).

---

## M6.1 — Does slope add anything over momentum? (2026-09-21)

**Module / track:** M6.1, Track B (DESIGN.md §6.0/§6.1). Not part of the original
minimal-core list (DESIGN §12 names M1, M2, M4, M5, M6.2, M11, plus §7.5) — added
post-termination via DESIGN §1.5's porous-scope rule, the same precedent M18 already
established: this study reached its termination condition on 2026-09-17 and was
reconfirmed on 2026-09-20 (`STATUS.md`), and a new module beyond that list is a
deliberate, disciplined extension, not a reopening — same pre-registration/kill-
criterion/FDR discipline as every module before it.

**Promoted from:** DESIGN's own module list, not a Track A candidate — same status as
M1/M2/M5/M6.2/M11. Run this session as one of four modules ("Batch 1" of a
parallel-scoping pass) chosen specifically because they need zero new shared
infrastructure and touch no file another parallel module also touches (the coordinating
session's own scoping, this conversation).

**M6.0 prerequisite (DESIGN §6.0), already established, not re-derived here:** the 1-day
SMA slope is exact scaled momentum, and for a k-day window the identity generalizes to a
difference of block means: `SMAn(t) - SMAn(t-k) = (k/n) * [mean(recent k days) -
mean(the k days ending n days back)]`. DESIGN's own words: "a k-day SMA slope is
momentum with smoothed endpoints — the same signal as raw n-day momentum but with the
start and end points averaged over k days instead of sampled at a single close. That
smoothing is the only thing slope can possibly add over raw momentum... Test it
directly (M6.1) rather than assuming it."

**Hypothesis (skeptical, DESIGN's own wording):** SMA slope is momentum with cosmetic
smoothing, and the smoothing buys close to nothing.

**New machinery: two small local features, computed in this module's own `prepare()`,
never written to the shared panel cache (`features/panel.py`) or to `features/slope.py`**
— so this module and any sibling M6.x module running in parallel this session never
touch the same file:
- `raw_return_k(close, k)` = `log(C_t / C_{t-k})` — plain k-day momentum, no skip, no
  smoothing. Distinct from `mom_12_1` (which skips the most recent month).
- `block_mean_diff_log(close, k=21, n)` = DESIGN's own k-day identity above, expressed
  in log space (`log(recent k-day mean) - log(prior k-day mean, ending n days back)`)
  rather than the raw linear difference, for the same cross-ticker comparability reason
  `slope_log_k` itself is logged (CLAUDE.md invariant #7 — "Log scale for slopes...
  Percentage and price-unit slopes are not comparable across tickers"). This is a
  documented modeling choice (the identity is exact in raw/linear space; taking logs on
  top is this module's own choice for consistency with the rest of the study's slope
  convention), not a silent deviation from DESIGN's literal formula.
- Both are computed from the panel's own unlagged `close`, then passed through the same
  central `features/panel.py::apply_lag` every cached feature already went through
  (CLAUDE.md invariant #2) — `slope_log_21_sma_k` and `mom_12_1` are already lagged
  cached-panel columns, untouched.

**Method:** Two parts, matching DESIGN's own method paragraph's two asks:
1. **Horse race (descriptive, primary lookback SMA200 only, per DESIGN's own method
   text):** per-date Spearman rank-IC (`modules/cross_sectional.py::daily_rank_ic`,
   reused unchanged) of each of {`slope_log_21_sma_200`, `raw_return_200`, `mom_12_1`,
   `block_mean_diff_log_200`} against `fwd_ret_{21,63,126}`, block-bootstrapped
   (`stats/inference.py::block_bootstrap_series`, reused unchanged, block length
   `max(42, 2×horizon)`) — IC and IC-decay across horizons, DESIGN's own named
   comparison. Plus a turnover comparison (`stats/costs.py::signals_per_year`, reused
   unchanged, on each feature's own top-decile membership flag) for
   `slope_log_21_sma_200` vs `mom_12_1` specifically — DESIGN's own "lower turnover
   alone could justify preferring it" consideration.
2. **Decisive test (the kill-criterion test, run "across all lookbacks" per DESIGN's own
   kill-criterion wording):** per-date cross-sectional partial correlation — residualize
   `slope_log_21_sma_k` against `mom_12_1` via one-date-at-a-time OLS (no pooled
   full-sample regression, CLAUDE.md invariant #3), then Spearman rank-IC of the
   residual against `fwd_ret_21` — "incremental IC," DESIGN's own named quantity, run at
   all four cached SMA lookbacks (`k ∈ {20, 50, 150, 200}`), block-bootstrapped the same
   way as the horse race's own IC series.

**Kill criterion (DESIGN's own, made precise):** killed iff **every** lookback's
incremental-IC edge (`max(|ci_low|, |ci_high|)` on the decisive test's block-bootstrap
CI) is below **0.005** → declare SMA slope redundant with momentum, use whichever is
cheaper, stop building slope-specific machinery. Not killed if even one lookback's edge
clears 0.005 (a real, distinguishable incremental effect at that lookback).

**Control tier and why:** the decisive test's own construction (partial correlation
against `mom_12_1`) *is* the control — momentum is directly regressed out per date
before testing what's left, a tighter control than this study's usual C2 tercile-match
for exactly this question (does slope survive momentum, not does slope survive
momentum+vol+sector). The descriptive horse race doesn't use C1/C2 at all — it's a raw
IC comparison across candidate features, not a group-delta claim, so this study's usual
C0/C1/C2 framing doesn't apply the same way; documented here rather than silently
omitted.

**Cost annotation:** this module is diagnostic/redundancy in nature (DESIGN's own
framing — "test it directly... use whichever is cheaper," not itself proposing a new
trade), not a standalone tradeable claim — no cost hurdle is computed. The turnover
comparison above is reported as a raw descriptive number (signals/ticker-year), not
converted to a cost hurdle, per this reasoning. If a future module wanted to trade on
whichever of slope/momentum this test favors, that claim would need its own cost
annotation at that point (CLAUDE.md invariant #8), not retroactively here.

**Grid size (`N_tests` contribution):** **4 cells** (the decisive incremental-IC test at
each of 4 lookbacks) — the horse race's 12 IC cells (4 features × 3 horizons) are
descriptive only, not hypothesis tests with their own kill criterion, so they don't
enter `N_tests`, same convention this study uses for every purely-descriptive readout
(e.g. M6.2's plateau checks, this study's own shape-stats addenda).

**Distribution shape (CLAUDE.md invariant #10):** this module's own "standard result
object" is a per-date IC/partial-correlation series, not a group-vs-group delta on a
boolean event flag — `stats/shape.py`'s `hit_rate_deltas`/`distribution_shape` are both
defined relative to a boolean `group_col` (an event flag) and don't have a natural
mapping onto a rank-correlation statistic. Documented here as a deliberate scope
decision, not a silent omission of the invariant: this module reports no hit-rate/
win-loss/skew numbers, because there is no boolean event group in its own construction
to compute them against.

**Plateau check (DESIGN §6.7):** the 4-lookback decisive-test grid is itself a
plateau/robustness check across lookbacks — a result driven by one lookback's own edge
case rather than a broadly consistent read across {20,50,150,200} is flagged as such in
the Result section below, not silently generalized from a single lookback.

**Effective N:** distinct dates and tickers per cell, standard invariant — reported per
lookback in the Result section.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents, dev window
2010-01-04 → 2021-12-31 — the same cached panel M6.2/M18 already used, reused directly,
not rebuilt). `fwd_ret_21` for the decisive test (this study's primary horizon
throughout); `fwd_ret_{21,63,126}` for the descriptive horse race.

### Result (2026-09-21/22)

Ran against the real cached U1 panel (405 tickers, 1,222,605 rows, 2010-01-04 →
2021-12-31).

**Horse race (descriptive, SMA200, per-date Spearman rank-IC, block-bootstrapped):**
none of the four candidate features shows a CI-excluding-zero IC at any of the three
horizons — every one of the 12 cells spans zero, and the point estimates are small and
not obviously ordered by construction (e.g. at h=21: `block_mean_diff_log` 0.0055,
`slope_log_21` 0.0050, `raw_return_k` 0.0046, `mom_12_1` 0.0036; at h=63/126 several
flip sign). Full table: `EXPERIMENTS.csv`. This is already broadly consistent with
DESIGN's own skeptical hypothesis — none of the four constructions, including momentum
itself, shows a distinguishable univariate edge at SMA200 in this design.

**Turnover:** `slope_log_21_sma_200`'s own top-decile-membership turnover is
**0.902 flips/ticker-yr**, vs. `mom_12_1`'s **3.340 flips/ticker-yr** — slope churns
roughly **3.7× less** than momentum. This is the one clean, directly actionable number
this module produced (DESIGN's own "lower turnover alone could justify preferring it"
consideration) — independent of whether slope carries genuinely different information,
it is markedly cheaper to trade if the two are similar.

**Decisive test (incremental IC, `slope_log_21_sma_k` residualized against `mom_12_1`,
vs. `fwd_ret_21`, block-bootstrapped, all four lookbacks well-powered — n_events
1,111,635, n_dates 2,747, n_tickers 405 at every lookback, `below_threshold=False`
throughout):**

| lookback | incremental IC | 90% CI | edge | CI excludes zero |
|---|---|---|---|---|
| 20 | −0.01585 | [−0.03210, +0.00120] | 0.03210 | no |
| 50 | +0.00164 | [−0.01850, +0.02293] | 0.02293 | no |
| 150 | −0.01381 | [−0.03301, +0.00440] | 0.03301 | no |
| 200 | +0.00118 | [−0.01699, +0.01805] | 0.01805 | no |

**Kill verdict: NOT killed** — `kill_verdict()` (the pre-registered rule, `edge < 0.005`
at every lookback) returns `False`, since lookbacks 20 and 150's edges (0.032, 0.033)
exceed the 0.005 floor. **This does not mean a real incremental effect was found** — no
lookback's CI excludes zero, so per this rule not firing is a product of wide CIs at two
lookbacks, not a detected effect at any of the four. Read precisely, per this study's own
established `killed=False` + `ci_excludes_zero=False` distinction (`modules/
slope_conditioner.py`'s own docstring, reused verbatim here): **inconclusive at every
lookback, not confirmed and not cleanly killed.**

**Plateau check (as pre-registered):** no consistent direction across the four
lookbacks — negative point estimates at 20/150, near-zero-positive at 50/200 — and none
individually distinguishable from zero. This is a flat, sign-flipping null across the
whole grid, not a lone bright pixel and not a directional pattern; read as "no
detectable incremental information at any lookback in this design," consistent with the
horse race's own flat univariate ICs.

**Argue against this result (not resolved here, flagged as live alternatives):** (1)
the per-date OLS residualization is a linear partial correlation — if slope's
incremental content over momentum is nonlinear (e.g. only shows up in the extreme
deciles, the kind of thing M4/M6.2 found via decile/event restriction rather than a
whole-panel linear regression), this construction would not detect it; this module
deliberately tests DESIGN's own literally-stated method (a joint linear regression),
not a restricted/interaction form — M6.2 already covers several of those. (2) `mom_12_1`
itself showed no detectable univariate IC either in the horse race — a possible
underpowered-horizon/window issue affecting the whole cell, not specific to slope's own
construction, though the sample is large and well-powered by every effective-N measure
this study tracks, arguing against a simple power explanation.

**Tier:** 4 for all four decisive-test cells (well-powered, CI spans zero — "no detected
effect at this control tier and sample," not silence, per this study's own Tier-3/4
convention). No `FINDINGS.md` entry (Tier 4 needs none, per CLAUDE.md's own logging
rule). The horse race's 12 descriptive cells and the 2 turnover numbers are not
independently tiered (descriptive only, no kill criterion of their own, per this
entry's own N_tests scoping above).

**Reading for the study:** DESIGN's own skeptical prior ("SMA slope is momentum with
cosmetic smoothing, and the smoothing buys close to nothing") is not confirmed by a
clean kill, but every number this module produced points the same direction as that
prior would predict — no univariate feature shows an edge, no lookback shows a
detectable incremental effect, and the one clear asymmetry between slope and momentum
(turnover, ~3.7× lower for slope) argues for preferring slope on cost grounds precisely
in the scenario where the two carry similar information. Honest summary: **not
distinguishable from "slope is redundant with momentum," but not proven to be so under
this study's own CI-based kill-criterion discipline** — a genuine inconclusive result,
reported as such rather than rounded off in either direction.

**Logged:** `EXPERIMENTS.csv` (4 rows, the decisive-test cells; the horse race and
turnover numbers are referenced here and in `output/moving_averages/m6_1_*.csv`,
regenerable from this module, not separately logged as CSV rows since they carry no
kill criterion of their own — same convention as this study's other purely-descriptive
readouts, e.g. plateau checks).

## M6.6 — Slope agreement across the ribbon (2026-09-23)

**Module / track:** M6.6, Track B (DESIGN.md, "M6.6 — Slope agreement across the
ribbon"). Not part of the original minimal-core list (DESIGN §12) — post-termination
"Batch 2" module (`HANDOVER.md`'s 2026-09-22 triage), run in parallel with three
sibling modules (M3, M6.5, M12) each in their own isolated worktree/branch.

**Hypothesis (DESIGN's own):** the fraction of the ribbon {10, 20, 50, 100, 200} with
positive slope — an ordinal 0–5 state — is monotonically associated with forward return
and, more likely to be useful per DESIGN's own text, forward *drawdown*. DESIGN
explicitly warns the state may "collapse to a single MA's slope" (heavy collinearity)
and asks for the correlation matrix to be reported either way, not just on a positive
result.

**One logged deviation from DESIGN's literal lookback set, load-bearing for this
module's design, stated up front:** DESIGN names {10, 20, 50, 100, 200} — not this
study's shared cached-panel lookback set {20, 50, 150, 200}. The cached panel has no
10-day or 100-day SMA. `sma_10`/`sma_100` and their `slope_log_21` are built here,
module-local (`modules/ribbon_slope_agreement.py::_build_new_sma_slopes`), not added to
the shared panel — per this study's established per-module-local-feature convention
(M6.3's `slope_pctile_21`, M7's `ribbon_width`), so parallel Batch-2 modules don't
collide on `features/panel.py`. `sma_20`/`sma_50`/`sma_200`'s already-cached
`slope_log_21_sma_k` columns are reused unchanged. 150 is *not* substituted for 100 —
DESIGN's named set is used exactly, unlike M7's ribbon (which uses this study's
existing {20,50,150,200} set for a different question, dispersion not slope-sign
agreement).

**No literal kill criterion from DESIGN** (framed as an exploratory shape/collinearity
question, same situation M6.3/M6.6's sibling modules were in). Stated here, following
this study's own established floor for a return-valued cell: `max(|ci_low|,|ci_high|)
< 0.10%` (M1/M2/M6.2/M6.3's own floor) on the decisive extreme-state test →
**killed for that outcome** (no detected ribbon-agreement effect beyond a single MA's
own slope, at this control tier). CI excluding zero and clearing the floor →
**confirmed for that outcome**, tiered per DESIGN §9.2 as usual.

**Method — two outputs, following M6.3's shape/decisive-test split:**
- **`slope_correlation_matrix`** (required regardless of the decisive test's outcome,
  per DESIGN's own text): per-date median Spearman correlation
  (`feature_sweep.py::per_date_median_corr`, this study's established redundancy-check
  primitive — M6.1/M11 precedent) between every pair of the five lookbacks'
  `slope_log_21` values (10 pairs), plus each lookback vs. the ordinal
  `ribbon_agreement_state` itself (5 more rows).
- **`shape_table`** (descriptive): one row per ordinal state (0–5), C0/C1/C2
  point-estimate deltas on both `fwd_ret_21` and a new label, `fwd_mdd_21` (below) — no
  bootstrap CI, same convention as M4's `decile_table`/M6.3's `shape_table`. The
  monotonicity read DESIGN asks for is descriptive off this table (consistency across
  adjacent states, same spirit as this study's plateau checks), not a battery of five
  separate per-adjacent-pair CI tests — kept out of `N_tests` for the same reason M4/
  M6.3's own per-bucket rows were.
- **`extreme_state_test`** (the decisive, CI-backed test): C2 block-bootstrap delta
  (`stats/inference.py::block_bootstrap_delta`, block length 42, 500 draws, 90% CI,
  seed 0) between the two ordinal extremes — state 5 (all five lookbacks rising) vs.
  state 0 (all five falling) — restricted to only those two states' rows first, same
  restrict-then-delta pattern M6.2/M6.3 established. Run twice: once on `fwd_ret_21`
  (DESIGN's "forward returns"), once on a new label, `fwd_mdd_21` (DESIGN's "forward
  drawdown").

**New label — `labels/path_metrics.py::forward_max_drawdown`:** the maximum adverse
excursion over the forward 21-day window — the worst `low[t+k]/close[t] − 1` for k in
1..21, using the path's own daily lows, not just the horizon's closing return
(`forward_return`'s outcome). Minimal, purpose-built for this module's own "forward
drawdown" need — not DESIGN's full M6.4 path-metrics/MFE scope (Kaplan-Meier survival,
barrier hits), which stays unbuilt. A forward-looking label, not a lagged feature
(CLAUDE.md invariant #2 constrains features, not labels — same status as
`forward_return`/`forward_realized_vol`).

**Control tier and why:** C2 (`mom_tercile`, `vol_tercile`, `sector`) — this study's
standard tier, same reasoning M6.3 gives: a steep slope in one normalisation and a
high-vol name are not the same thing.

**Cost annotation:** `shape_table` is descriptive, not a claim. If `extreme_state_test`
on `fwd_ret_21` confirms an effect, that implies a tradeable claim — invariant #8
requires a cost annotation, computed on the `ribbon_agreement_state == 5` ("fully
agreeing bullish") flag's own turnover (`stats/costs.py::signals_per_year`, same
convention as every prior module). State 0 ("fully agreeing bearish") is a short-side/
exit signal, not separately cost-annotated here. `fwd_mdd_21`'s own extreme-state test
is a drawdown-avoidance read, not directly a return-implying trading claim in the same
sense — not cost-annotated on its own (DESIGN itself frames "more useful" drawdown
information as a risk-management input, not a standalone entry signal).

**Grid size (`N_tests` contribution):** **2 primary cells** — `extreme_state_test` on
`fwd_ret_21` and on `fwd_mdd_21`. The correlation matrix (15 numbers) and `shape_table`
(6 states × 6 columns) are descriptive, not hypothesis tests each — same convention as
M4's `decile_table`/M6.3's `shape_table`, neither of which counted their per-bucket
rows as independent tests.

**Effective N:** distinct event dates and tickers per cell, standard invariant — the
two-state-extremes-only restricted population is expected to be smaller than a
full-panel cell but still checked against DESIGN §6.9's floor (200 events, ≥30 dates,
≥30 tickers) via `below_threshold`, same convention as every prior module.

**Plateau check (DESIGN §6.7):** applied as consistency across `shape_table`'s six
states — a real extreme-state spread that isn't at least roughly monotonic through the
middle states (2/3 in particular) is the same "lone bright pixel" pattern this study
has caught before (M6.3's own SMA20 asymmetry), read the same way here: reported, not
silently treated as a clean monotonic function.

**Universe/window/horizon:** unchanged, U1 (405 S&P 500 constituents, dev window
2010-01-04 → 2021-12-31), `fwd_ret_21` / `fwd_mdd_21` (both 21-day, this study's
standard horizon).

**New machinery:** `labels/path_metrics.py` (new file, `forward_max_drawdown`);
`modules/ribbon_slope_agreement.py`'s own `prepare`/`slope_correlation_matrix`/
`shape_table`/`extreme_state_test`/`cost_annotation`/`run_grid`. Everything else
(`cross_sectional_bucket`, `c0_delta`/`c1_delta`/`c2_delta`, `block_bootstrap_delta`,
`per_date_median_corr`) is reused unchanged. New columns: `slope_log_21_sma_{10,100}`
(module-local, lagged via the shared `features/panel.py::apply_lag`, per CLAUDE.md
invariant #2), `ribbon_agreement_state` (masked to NaN wherever any of the five
lookbacks' slope is undefined — CLAUDE.md invariant #9, enforced by this module's own
test, `test_ribbon_agreement_state_is_na_during_sma_100_warmup`).

### Result (2026-09-23)

**DESIGN's own stated expectation holds exactly: the drawdown outcome is where the
signal is, the return outcome is not.**

| cell | c2 (21d) | 90% CI | ci_excludes_zero | edge | n_events | n_dates | n_tickers |
|---|---|---|---|---|---|---|---|
| `extreme_state_test` on `fwd_ret_21` | −0.2060% | [−0.6231%, +0.1835%] | False | 0.6231% | 406,663 | 2,747 | 402 |
| `extreme_state_test` on `fwd_mdd_21` | +0.6538% | [+0.4379%, +0.8870%] | **True** | 0.8870% | 406,663 | 2,747 | 402 |

`fwd_ret_21`: CI spans zero — not confirmed, not killed by the floor either (edge
clears 0.10%) — a genuine "no detected effect at this control tier" read, same
convention as M6.2's own inconclusive cells.

`fwd_mdd_21`: CI excludes zero, clears the floor. Positive sign means state 5 (all five
lookbacks rising) has a *shallower* worst-21-day-drawdown than state 0 (all five
falling), by 0.65pp beyond the C2 match. **Confirmed.**

**Cost (invariant #8, triggered for the confirmed drawdown cell):** `ribbon_agreement_
state == 5` flag turnover, `stats/costs.py::signals_per_year` (10bps/rt): 5.415
flips/ticker-yr → hurdle 0.5415%/yr. Annualized (×12): point +7.85%/yr, near edge
+5.25%/yr, far edge +10.64%/yr — **clears at every reading**, with the same
avoided-loss-vs-signed-return actionability caveat M7's `ribbon_direction_magnitude`
carries (see `FINDINGS.md`'s entry for the full statement — "clears cost" here is about
drawdown-shallowing, not a signed return claim).

**Reversal-robustness (run same day, on the confirmed drawdown cell only — the return
cell did not confirm, nothing to robustness-check):** C2 + `rev_tercile`
(`C2_MATCH_COLS_WITH_REVERSAL`): +0.5346%, CI [+0.2397%, +0.8361%] — attenuates ~18%
from the default-C2 number, CI still excludes zero, still clears the 0.10% floor by a
wide margin. Short-term reversal is a minor contributor at most, not the driver.

**Correlation matrix (required regardless of outcome, DESIGN's own text):**

| pair | median Spearman |
|---|---|
| slope_10 vs slope_20 | 0.8868 |
| slope_10 vs slope_50 | 0.5141 |
| slope_10 vs slope_100 | 0.3567 |
| slope_10 vs slope_200 | 0.2790 |
| slope_20 vs slope_50 | 0.6806 |
| slope_20 vs slope_100 | 0.4722 |
| slope_20 vs slope_200 | 0.3522 |
| slope_50 vs slope_100 | 0.7329 |
| slope_50 vs slope_200 | 0.5097 |
| slope_100 vs slope_200 | 0.7110 |
| slope_10 vs ribbon_agreement_state | 0.6860 |
| slope_20 vs ribbon_agreement_state | 0.7570 |
| slope_50 vs ribbon_agreement_state | 0.7408 |
| slope_100 vs ribbon_agreement_state | 0.6886 |
| slope_200 vs ribbon_agreement_state | 0.5966 |

Every pairwise slope correlation sits at or below this study's 0.89 non-redundancy bar
(M11's precedent) — **DESIGN's own stated collinearity concern ("expect heavy
collinearity") is not borne out**: the five lookbacks are meaningfully distinct
signals, closest at the two fastest (10, 20) lookbacks, most distinct at 10-vs-200. Full
matrix: `output/moving_averages/m6_6_ribbon_slope_agreement_correlation_matrix.csv`.

**Shape table (descriptive, both outcomes, all 6 states):**

| state | n_events | n_dates | c2_return | c2_drawdown |
|---|---|---|---|---|
| 0 | 83,990 | 2,766 | +0.2936% | −0.3048% |
| 1 | 106,458 | 2,768 | +0.1889% | −0.0444% |
| 2 | 148,020 | 2,779 | −0.1219% | −0.1664% |
| 3 | 191,367 | 2,779 | −0.0109% | −0.0172% |
| 4 | 177,453 | 2,778 | −0.0753% | +0.0299% |
| 5 | 417,307 | 2,779 | −0.0124% | +0.2196% |

**Plateau check (DESIGN §6.7):** the drawdown column is directionally consistent
end-to-end (state 0 worst, state 5 best) but not a clean monotonic staircase through the
middle (state 1 less negative than state 2) — endpoints clean, middle noisy, same
"not a lone bright pixel but not a smooth function either" read M6.3's own U-shape got.
The return column declines from state 0 to state 2 then flattens near zero through
state 5 — consistent with that outcome's own CI-spans-zero extreme-state read.

**Argue against the confirmed drawdown result:** the reversal-robustness check above
(the leading candidate confound) attenuates the effect by only ~18% and the CI still
excludes zero — not the whole story. A second candidate: `mom_tercile`/`vol_tercile`
match on their own 12-1-month/63-day windows may not fully capture the *very*
short-horizon momentum embedded in the fast 10-day-lookback component of
`ribbon_agreement_state` — the `rev_tercile` check (1-day prior return) partially
addresses this but a multi-week reversal window is not separately ruled out here. Not
resolved in this run — flagged as the most plausible remaining alternative explanation,
same open-item discipline as M6.3's own SMA50/200 argue-against note.

**Logged:** `EXPERIMENTS.csv` (3 rows: the 2 primary decisive cells + 1 reversal-
robustness companion, not counted in `N_tests`); `FINDINGS.md` (1 entry,
`ribbon_agreement_extreme_drawdown`, Tier 3, with the return-outcome and correlation-
matrix results folded into the same entry per this study's convention for a
two-outcome module); `output/moving_averages/m6_6_ribbon_slope_agreement_*.csv` (full
result table, correlation matrix, shape table — regenerable via
`ribbon_slope_agreement_run.py`).
