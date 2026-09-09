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
`DEAD_ENDS.md`).

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
  robustly: neither the point estimate nor the CI-bound test clears the hurdle, at 3D or
  4D.
- **lb50 → Tier 3, weaker than lb20.** 3D CI excludes zero, barely
  (`[−0.003406, −0.000306]`). Point estimate clears the 3D cost hurdle; the CI-bound
  test does not (and, under the corrected rule above, the 4D CI spans zero — an
  automatic fail there too).
- **lb200 → Tier 4.** 3D CI already touches zero (`ci_high = +0.000048`); 4D CI clearly
  spans zero. Under the corrected cost-test rule, the CI-bound test is an unambiguous
  fail (was previously miscategorized as passing — see the definitional-gap correction
  above). Also the lookback with the worst row loss (51.9% → 74.9%) and heaviest
  all-above skew (84.5%) of the three — the weakest statistically and the most
  selection-exposed, consistently with each other.

**Standing caveat on the lb20/lb50 Tier-3 pair:** unlike M4's SMA20 facets at the same
nominal tier, these carry an open selection-mechanism question (the all-above-skewed row
loss) that has not been ruled out as a contributor to the observed sign, independent of
whatever real conditioning effect (if any) exists. Treat this tier as less settled than
a typical Tier-3 call until that's addressed (e.g. once a broader universe makes decile-
level C2 matching viable — see the inherited "C2 note" above).

**Run-length secondary layer (the "does age matter" sub-question):** no credible
finding. Every lookback/direction's 1–5→6–21→22–63→64+ sequence zigzags in sign with no
smooth progression (DESIGN §6.7's plateau rule). The one cell whose CI excludes zero
(lb50 above / 6-21) has opposite-signed, non-significant neighbors on both sides — a
lone-pixel failure of the plateau rule, not a finding. Logged to `DEAD_ENDS.md`.
