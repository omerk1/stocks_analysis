# Least resistance path (LRP) — formulation

**Status:** proposed formulation, 2026-09-29. Not built, not tested. Every weight and
threshold below is a fixed prior chosen before looking at outcomes. The model and the
validation harness decide what survives.

**What it answers:** for a ticker on date *t*, **which way is easier** (direction) and
**how much clear air** there is before price runs into something (distance). It does
that by folding every "meta" object the repo detects (S/R lines, fibs, AVWAPs, gaps,
volume profile, market structure, patterns, MAs) into one common *level* shape. It then
summarises those levels into a small set of per-date features, in the same ATR units as
the barrier target (`IDEAS.md` §1).

---

## 1. The unified level

Every source is mapped to a list of levels as of *t*. Each level has:

| field | meaning |
|---|---|
| `price(t)` | Level price at *t*. Fixed for horizontal levels; recomputed daily for time-varying ones (diagonal S/R lines, AVWAPs). |
| `zone = [lo, hi]` | Price band the level occupies. A zero-width level has `lo = hi = price`. |
| `source` | `sr_line`, `fib`, `avwap`, `gap`, `vp`, `structure`, `pattern`, `ma`, `hi52`/`lo52`, `round`. |
| `strength` ∈ [0, 1] | Source-native strength, converted to a **trailing percentile within its source** (invariant 3: no full-sample statistics), so sources are comparable. |
| `age` | Bars since the level formed. |
| `touches` | Times price tested it and it held. |
| `state` | `fresh` / `tested` / `flipped` (a broken level that now acts from the other side) / `dead` (dropped). |
| `prior` | Evidence prior from `IDEAS.md` §2: `weak` or `null`. No level source is `supported` yet. |

Whether a level counts as **resistance or support is decided by where price is** at *t*,
not by the source's label. A level above the close is resistance and one below is
support, so a flipped level is handled automatically.

### 1.1 Source mappings

| source | levels taken | native strength | dropped when | prior |
|---|---|---|---|---|
| S/R lines (`sr_lines`) | Each active line: `center ± half_width`; diagonal lines use `slope`/`intercept` at *t*. | `Line.strength` (already combines touch quality, duration, resilience, role reversal) | `state` broken and not flipped | null (untested) |
| Fibonacci (`fibonacci`) | Each level of each active `FibSet`. | `FibSet.weight` × ratio factor (0.382 / 0.5 / 0.618 = 1, others = 0.5) × (1.5 if `respected`) | set invalidated | null |
| AVWAP (`avwap`) | `current_value`; zone = ±0.5 × `current_std`. | `avg_reaction_atr_on_touch`, discounted by `n_crosses` (a level crossed often is weak) | anchor inactive | null |
| Gaps (`gaps`, FVGs included) | Open gaps: `[zone_bottom, zone_top]`. | `size_atr` × (1 − `max_fill_pct`), × `volume_ratio_at_creation` if present | closed | null |
| Volume profile (`volume_profile`) | POC, VAH, VAL of each active anchored profile. | Share of profile volume at the row; POC highest. Low-volume nodes aren't built yet (backlog). | anchor inactive | null |
| Market structure (`market_structure`) | Last unbroken swing high (above) and swing low (below). | 1 if volume-confirmed, else 0.5 | broken | null |
| Patterns (`patterns`) | `key_levels` (neckline, breakout line) of as-of-safe matches only (M14). | `confidence` | completed or failed | null |
| MAs | SMA 20 / 50 / 200 values at *t*. | Fixed 0.5 (no native strength). | never | **null (M5, M6.2, §7.5)** |
| 52-week high / low | Trailing 252-day high and low. | Fixed 0.5 | never | null (M18: the high is momentum re-encoded) |
| Round numbers | Nearest multiples of a step that scales with price (e.g. $1 under $20, $5 under $100, $10 under $500, else $50). | Fixed 0.25 | never | null |

**MAs, specifically.** You asked whether MAs act as support/resistance *in trends*. The
study tested exactly that:
- M6.2 compared touches of a **rising** vs **falling** MA. A rising SMA50 touched from
  above held **5.75pp less often**, not more. Once short-term reversal is controlled, the
  CI spans zero. SMA200 behaved the same way (−8pp, spans zero).
- M5 and the §7.5 placebo found real MAs do no better than unwatched MAs a few days off.

So MAs are in the pool, but at a null prior. Caveat: the study used daily-close touches
only (no intraday wicks), the first touch after being ≥1 ATR away.

**Divergences are not levels.** They say which way pressure points, not where price
stops. They enter as a separate *pressure* term (§2.4), not in the level pool.

### 1.2 Effective strength

Each level's weight on date *t*:

```
w = strength_pctile × decay(age) × state_factor × prior_factor
decay(age)     = 0.5 ** (age / 126)          # half-life ~6 months
state_factor   = 1.0 fresh | 1.2 tested | 0.8 flipped
prior_factor   = 1.0 (all sources start equal; see §3)
```

The half-life and state factors are priors, not tuned. The harness compares them with
the untransformed per-source features (§2.1) to see whether the hand weighting helps.

---

## 2. Per-date features

Notation, per ticker-date *t*: close `C`, ATR(14) `A`. Each level's signed distance is
`d = (edge − C) / A`, where `edge` is the zone edge nearest to price. `d > 0` is above
(resistance), `d < 0` below (support). Levels whose zone contains `C` get `d = 0` and
count on both sides.

### 2.1 Per-source nearest distances (the learnable layer)

For each source *s*: `near_up_s` = smallest `d > 0`, `near_dn_s` = smallest `|d|` for
`d < 0`, plus that level's `w`. Capped at 10 ATR, with a missing flag when there's no
level.

These let the model learn its own source weights instead of trusting §1.2's. There are
about 20 columns (10 sources × 2 sides) plus their weights.

### 2.2 Aggregate LRP features (the hand-built layer)

| feature | definition |
|---|---|
| `clear_up_θ`, `clear_dn_θ` | Distance in ATR to the first point where **cumulative** `w` since `C` reaches θ, for θ ∈ {0.5, 1.5}. "How far until a meaningful wall." Capped at 10. |
| `density_up_h`, `density_dn_h` | Σ `w` of levels within `h` ATR, h ∈ {1, 2, 3, 5}. |
| `lrp_dir` | `log((clear_up_1.5 + 0.25) / (clear_dn_1.5 + 0.25))`. Positive means more room up than down. |
| `lrp_pressure_h` | `density_dn_h − density_up_h`, h ∈ {2, 3}. Positive means support below outweighs resistance above. |
| `confluence_up`, `confluence_dn` | Largest Σ `w` of levels from **≥2 different sources** inside any 0.5-ATR window within 5 ATR. Plus that cluster's distance. |

### 2.3 Barrier-conditional features (the bridge to the target)

The target is a surface of cells (`H`, `U`, `D`), so obstacles are also measured *per
cell*. For target `U` and stop `D` (both in ATR):

| feature | definition |
|---|---|
| `obstacle_up(U)` | Σ `w` of resistance levels with `0 < d < U`: walls between price and the target. |
| `cushion_dn(D)` | Σ `w` of support levels with `−D < d < 0`: floors between price and the stop. |
| `target_on_wall(U)` | `w` of the strongest level within ±0.25 ATR of `+U`. A target placed at a wall is less likely to fill. |
| `stop_below_floor(D)` | 1 if a level with `w ≥ 0.5` sits just above `−D` (within 0.5 ATR), i.e. the stop sits behind a floor. |
| `vp_ease(U)`, `vp_ease(D)` | Share of the most recent active volume profile's volume inside `(C, C+U·A)` and `(C−D·A, C)`. Low means thin volume, which is easy to travel. Needs `volume_profile` rows; open follow-up (d) adds low/high-volume node detection. |

These go into the model with the cell's `(H, U, D)` as inputs, once per cell for a
stacked-rows model (`IDEAS.md` §1 option a). For the path-distribution model (option
b), they go in on a fixed grid instead.

### 2.4 Directional pressure (non-level)

Kept separate from levels:
- **Divergences:** net active divergence direction, weighted by `strength`, over the
  last 21 bars; confluence of the newest one — **recomputed point-in-time, never the
  stored column** (see constraints below).
- **Divergence-feature constraints (added 2026-10-09, from the divergence-context
  study — full record in `docs/features/divergence-context/`):**
  1. **Stored `confluence_count`/`agreeing_indicators` are FULL-RUN values** — the
     backfill runs `as_of=None`, and confluence is deliberately computed after the
     as_of filter because it is not truncation-stable. A per-date feature reading
     the stored columns is look-ahead. Use `divergences.context.pit_confluence()`
     to re-cluster from stored rows at each date (everything needed is stored);
     the equivalence guarantee (`tests/test_divergences_asof_equivalence.py`)
     covers event identity/geometry only, explicitly not confluence.
  2. **Hidden forms exist** (`form` column, #158): `direction` is the implied move
     for both forms, but regular (reversal-flavored) and hidden
     (continuation-flavored) are different claims off the same swing — decide
     explicitly whether "net direction" pools them, and prefer separate features
     or a form interaction over silent pooling.
  3. **Condition on context.** The study's one solid result: the label's
     information content differs ~3× by context — near-tautological after an
     explosive move (nearly every new extreme prints one), selective after a
     consolidation (~29% of comparable swings). `divergence_context` stores the
     scalars (retrace fraction, leg2 bars, impulse, vol); an interaction or
     context gate beats pooling. The registered mean-level test read out
     all-Inconclusive, so this is a feature-engineering prior, not a claimed
     effect.
  4a. **Hidden-form depth scalar (added 2026-10-12):** for hidden events the
     stored `interpeak_retrace_frac` is misfit (medians > 1 — p1 is often not an
     impulse extreme; Done #119); the usable depth measure is the pivot-to-pivot
     **hidden-fit retrace fraction**
     (`src.analysis.divergence_hidden_prep.hidden_fit_retrace_frac`:
     counter-move / trend-leg, bounded in (0,1), 100% defined on the recomputed
     base). The registered mean-level test of it (DC-B3/B4) was drafted, sized,
     and deliberately closed without running (PREREGISTRATION.md disposition
     2026-10-12: Dead unreachable at available N) — the scalar enters F6 as a
     continuous feature or form×depth interaction instead, judged on the trading
     scorecard like every other feature, and no standalone effect claim exists
     for it.
  4. **Survivorship gate:** the `divergences`/`divergence_control_pairs`
     tables were survivors-only (zero delisted tickers) until the 2026-10-10
     recompute (Done #112), which added every delisted ticker the vendor
     fallback covers (117, all 111 delisted 2010–2021 index members among them).
     F6 features built before 2026-10-10 inherit the bias; rebuild them, or
     mark the trial accordingly.
- **Market structure:** direction of the last BOS/CHoCH and bars since it.
- **Patterns:** direction of an as-of-safe active pattern, and its `confidence`.

---

## 3. How it gets tested

Everything here has a null prior until the harness says otherwise.
- **Baseline:** B4 = momentum (`mom_12_1`), reversal (`mom_1_0`), realised vol,
  extension tercile, plus the v1 MA block (`ma_study_insights.md` §2.2).
- **Ablations, in order:**
  1. §2.1 per-source distances;
  2. + §2.2 aggregates;
  3. + §2.3 barrier-conditional;
  4. + §2.4 pressure.

  Each is a group.
- **Metric:** out-of-sample Brier improvement per barrier cell, and top-k-per-day
  precision after costs (`IDEAS.md` §11), with date-block bootstrap CIs.
- **Kill criterion** (amended 2026-10-07 — three verdicts, not two; the earlier
  "includes zero → written up as a null" conflated a demonstrated null with an
  underpowered cell; rule mirrors
  `docs/features/divergence-context/PREREGISTRATION.md` "Verdicts and kill
  criteria"): a group is **dropped** if its CI on Brier improvement over the
  previous step includes zero at every horizon — the operational gate is unchanged.
  The recorded verdict then distinguishes:
  - **null** — the entire CI sits inside the pre-committed
    minimum-relevant-improvement band at every horizon (the band is set in the
    experiment's `PREREGISTRATION.md` entry before the run): an improvement big
    enough to matter is affirmatively ruled out;
  - **inconclusive** — the CI includes zero but extends beyond the band at some
    horizon: the data couldn't tell. Logged as underpowered, never as evidence of
    no effect.
  If **all four** groups fail the gate, LRP as formulated stops; it is written up
  as a null only for groups that meet the band test, and as inconclusive for the
  rest. No reformulating until something passes either way.
- **Source weights:** if the model's own use of §2.1 disagrees with §1.2's equal
  `prior_factor`, that's a finding to log. Only the next dated revision of this document
  may change the priors. They're never tuned against test folds.

### Addendum (2026-10-11): judged on the trading scorecard

Added after the modeling phase's direction changed (`VALIDATION_HARNESS.md` §9 step 6,
2026-10-08). The text above stays as written. It describes the ablation plan from
before that change.
- **Where the level groups go:** §2.1–2.3 are registered as feature groups of the one
  combined model. They are not a separate LRP model or a stand-alone test.
- **What judges them:** the trading scorecard (`run-scorecard` / `rescore-scorecard`,
  `rank="ev_atr"`). The model's top-20 picks are compared with B4's picks ranked the
  same way, the market basket and the random-k basket, after costs. The step 2 run
  compares the model with the level columns against the step 1b (`S1b`) numbers. It is
  Track A: a `TRIALS.csv` row per cell, no verdict.
- **Ablations are diagnostics:** the order and the Brier-improvement metric above still
  describe what to look at, for example whether a group carries anything the model
  uses. No group is dropped, and no LRP verdict is recorded, from a Brier ablation.
- **The three-verdict rule stays** for any pre-registered test. That includes the
  planned pre-registered trading test of the full feature set: its relevance band is set
  in its `PREREGISTRATION.md` entry before it runs.
- **Scope of step 2:** the level sources only. Patterns (§1.1) and all of §2.4 pressure
  are step 3, under §2.4's constraints. The v1 source list and its cost come from §4's
  timing (see the §4 addendum).

---

## 4. Point-in-time computation — the real cost

The stored signal tables are **current-state**: a later run overwrites what the detector
believed earlier. For example, `pattern_matches` can't answer "what did we believe on
day D". All eight detectors support `as_of`, so levels must be **regenerated as of each
date**, never read from the tables.

Plan:
- **Weekly snapshots:** each detector runs `as_of` every Friday for every ticker in the
  universe. That gives the level set, with states as of that day.
- **Daily roll-forward:** between snapshots, levels are fixed. Daily work is only price,
  ATR, the time-varying level prices (AVWAP from its anchor, diagonal lines from
  slope/intercept), and the state changes triggered by that day's bar (a close through a
  level flips or kills it). Stale by at most 4 days for *new* levels, never leaky.
- **First task before building:** time one detector's full `as_of` history on ~20
  tickers, then extrapolate to the universe × 12 years × 52 snapshots. If it's too slow,
  drop to fewer sources for v1 (S/R lines, gaps, AVWAP, structure are the cheapest
  candidates) rather than cutting the point-in-time rule.


### Addendum (2026-10-11): timing, and the v1 source list

The first task above, run read-only (no DB writes) on 20 S&P 500 tickers (16 live, 4
delisted and read from Tiingo; `cli._smoke_tickers`), every 13th Friday of 2010–2021
(49 dates), one `as_of` call per detector, ticker and date: 7,680 calls, no errors.
Extrapolated with a per-detector linear fit of seconds against date to the S&P 500
member-weeks of 2010–2021 (~314k: ~502 members × 626 Fridays).

| source | s / call, 2010 → 2021 | weekly `as_of`, 1 process | 4 cores |
|---|---|---|---|
| S/R lines | 0.19 → 0.21 (3-year window, flat) | 18 h | 4.4 h |
| AVWAP | 0.12 → 0.16 | 12 h | 3.0 h |
| market structure | 0.20 → 0.30 | 22 h | 5.5 h |
| fibonacci | 0.35 → 0.52 | 38 h | 9.4 h |
| volume profile | 0.10 → 0.13 | 10 h | 2.4 h |
| gaps, weekly `as_of` | 0.37 → 0.58 | 41 h | 10 h |
| **gaps, one run + `relevance.gap_states`** | 2.2 s per ticker, all days | **0.4 h** | ~0.1 h |
| patterns (step 3) | 1.8 → 3.0 | 208 h | 52 h |
| divergences (step 3) | 0.6 → 1.0 | 70 h | 17 h |

Patterns and divergences ran alongside other checks; their uncontended pilot was about
2× faster, so read those two rows as upper bounds.

What the timing showed:
- **Delisted tickers get no levels from today's detectors.** Only `divergences.detect`
  takes `source=`; the level detectors read the primary vendor only, so a Tiingo-only
  ticker loads no bars and is skipped without an error. The timing passed the resolved
  vendor in through a shim, and every delisted call then returned levels. The builder
  needs a `source=` parameter on each detector it uses, resolved by
  `price_basis.resolve_sources`, as divergences already does.
- **The cost is the detector, not the read:** loading bars is 2–22% of a call.
  Per-call cost grows 1.1–1.6× from 2010 to 2021 (each call re-reads all history), which
  is mild, so no lookback cap is needed.
- **Gaps need no weekly runs.** `gap_states` (tested equal to `detect(as_of=...)`)
  gives each gap's exact state on any date from one full-history detection. It is daily,
  so gaps are never stale.
- **The leakage gate** (`gates.py`) perturbs bars in memory, while the detectors read
  the DB. Each detector used here gets an entry point that takes bars (gaps already has
  `detect_on_bars`), and a registered level source calls that, so the gate perturbs the
  real computation; the parquet cache is a speed copy of the same function. The gate
  only needs snapshots near its cut: 20 tickers × ~8 Fridays × 5 runs, about 15 minutes.
- **Storage:** weekly snapshots of S/R, AVWAP and VP (~40 levels per ticker-week) are
  ~0.3–0.5 GB as parquet; the gap list ~50 MB. Daily gap states (~80M rows) are computed
  when features are built, never stored. With the feature cache and one scorecard run,
  step 2 adds ~1.5–2 GB.

**v1 sources (decided 2026-10-11): the cheap set, on the full universe.** S/R lines,
AVWAP, volume profile and gaps, plus the three that need no detector (MA 20/50/200,
52-week high/low, round numbers): about 10 h on 4 cores, resumable per ticker. Market
structure (+5.5 h) and fibonacci (+9.4 h) are added as their own builds only if the
cheap set shows something on the scorecard; the cache is per source, so adding them
redoes nothing. Two alternatives were rejected:
- **All six level sources at once** (~22 h): the extra 9.4 h is mostly fibonacci, spent
  before knowing whether levels help at all.
- **A pilot on ~100 random tickers:** 5× less training data, top-5 instead of top-20
  (CIs about 2× wider), and S1b would need its own rerun on the subset. It could only
  show a large effect.

Round numbers depend on the price level, so they are computed from the unadjusted
close; on adjusted prices the future-split perturbation would fail them. Patterns and
§2.4 stay in step 3. Divergences likely need no weekly runs either: stored events plus
`pit_confluence()` are point-in-time (§2.4 constraint 1).

**The comparison:** step 2's scorecard compares against a run with the same other
columns, so the difference is the levels alone. Step 2b's indicator features (#208) were
registered after S1b, so the no-levels side is step 2b's `S2` run if it lands first,
otherwise a rerun on the same columns.

---

## 5. Open questions

- How strength combines: sum (many weak levels = one strong one) vs max (only the
  strongest counts). §2.2 uses sums, and `confluence_*` captures the "different sources
  agree" case. The model can compare against §2.1's per-source maxima.
- Whether flipped levels deserve their own feature (breakout-retest is a common setup).
- Intraday touches: daily bars only today. `bars_1h` is empty (AVP follow-up (a) in
  `docs/backlog.md`).
