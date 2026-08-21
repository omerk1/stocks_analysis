# Chart Pattern Detection Module — Design Doc

**Purpose:** Spec for a mid/long-term (daily/weekly bar) technical-pattern detection engine covering Head & Shoulders, Inverse H&S, VCP, Triangles (asc/desc/symmetric), Cup & Handle, and adjacent patterns. Written to be handed to Claude Code as an implementation brief.

**Scope note up front:** every pattern below is geometrically fuzzy by nature (Bulkowski himself calls H&S "subjective, under expert judgment"). There is no single canonical algorithm in the literature — academic approaches (Lo/Mamaysky/Wang's kernel-regression smoothing + local-extrema rules, Chong & Poon's noise-filtered recognition, HMM/compressive-sensing methods) and practitioner approaches (ZigZag + rule engines, as used by most retail platforms) converge on the same two-stage architecture. This doc specifies that architecture precisely so results are reproducible and backtestable, not vibes-based.

---

## 1. Architecture Overview

```
Raw OHLCV
   │
   ▼
[1] Preprocessing & smoothing
   │   (optional: kernel/EMA smoothing to denoise before pivot extraction)
   ▼
[2] Pivot / Swing Extraction  →  ordered sequence of (index, price, type: HIGH|LOW)
   │   (ZigZag % / ATR threshold, OR Perceptually Important Points, OR fractal + zigzag hybrid)
   ▼
[3] Pattern Grammar Matchers  →  per-pattern rule engines running over sliding windows of pivots
   │   (each matcher: geometry checks → volume checks → confidence score)
   ▼
[4] Confirmation / State Machine  →  PENDING → CONFIRMED → (ACTIVE → HIT_TARGET | INVALIDATED | EXPIRED)
   │
   ▼
[5] Output: PatternMatch objects (type, pivots, neckline/trendlines, target, stop, confidence, status)
```

This two-stage split (reduce noisy OHLCV to a small ordered set of pivots, *then* pattern-match on the pivot sequence, not on raw candles) is the standard approach used across both academic recognition algorithms and production indicators (TradingView/MT5 pattern scanners) — pattern matching on raw bars is intractable and overfits to noise.

---

## 2. Stage 2 — Pivot Extraction (the foundation everything else depends on)

Get this wrong and every downstream pattern will be garbage. Implement **two interchangeable pivot detectors** behind a common interface, since different patterns behave better with different pivot granularity:

### 2a. ZigZag (percentage or ATR-based reversal threshold)
- Track a running extreme in the current direction (up-leg → track highest high; down-leg → track lowest low).
- Confirm a pivot only when price retraces from that extreme by more than a threshold: either a fixed `%` (e.g. 3–5% for daily charts, higher for volatile small caps) or an **ATR multiple** (e.g. `2.5 × ATR(14)`), which self-adjusts per-stock volatility and is the better default for a cross-market screener.
- Pivots strictly alternate HIGH/LOW.
- **Known weakness:** lagging/repainting — a pivot is only confirmed *after* the reversal happens, and the most recent pivot can repaint as new bars come in. Always mark the last pivot `unconfirmed` in output.

### 2b. Perceptually Important Points (PIP)
- Start with first/last point of window as PIPs.
- Iteratively insert the point with maximum vertical (or perpendicular) distance from the line connecting its two neighboring PIPs, until you have N points or all distances fall below a threshold.
- Useful as a secondary check on geometric patterns (triangles, wedges) since it directly optimizes "visual significance" rather than a fixed % move.

### 2c. Recommended default
Use **ATR-scaled ZigZag** as primary pivot detector (simpler, causal/real-time-safe, standard across the industry), with configurable `depth` (min bars between pivots) and `deviation` (ATR multiplier or %). Expose both as tunable parameters — different patterns want different granularity (VCP wants fine-grained pivots to catch each contraction leg; H&S wants coarser pivots for the 5 major swings).

```python
class Pivot:
    index: int          # bar index
    date: datetime
    price: float
    kind: Literal["HIGH", "LOW"]
    confirmed: bool      # False for the most recent, still-repainting pivot

def extract_pivots(df: pd.DataFrame, atr_mult: float = 2.5, min_bars: int = 3) -> list[Pivot]:
    ...
```

Every pattern matcher below consumes `list[Pivot]` (plus raw OHLCV + volume for confirmation checks), never raw bars directly.

---

## 3. Common Concepts Used Across All Patterns

### 3.1 Prior trend requirement
Most reversal/continuation patterns are **meaningless without qualifying the prior trend** — three random peaks in a sideways market is not a head and shoulders. Standard rule: require a prior move of **≥ X% over ≥ N bars** immediately preceding the pattern's first pivot (typical thresholds: 15–20% for H&S, 30%+ for cup & handle, per O'Neil). Implement as a reusable `has_prior_trend(df, pivot, min_pct, min_bars, direction)` helper.

### 3.2 Trendline fitting & touch validation
For any pattern needing a trendline (neckline, triangle boundary, channel):
- Fit via linear regression through the relevant pivots, OR through the actual extreme high/low if only 2 points.
- A "touch" counts if a pivot (or, more leniently, any bar's high/low) comes within a tolerance band of the line — tolerance = `max(0.5 × ATR, 0.5% of price)` is a reasonable default.
- **Minimum touches = 2 per trendline (4 total for a triangle)** is the textbook floor; treat 2-touch patterns as low-confidence and 3+ touches per line as higher-confidence. Score this continuously rather than as a hard gate (see §6).

### 3.3 Volume confirmation
Nearly every pattern in this doc has a volume signature that separates real institutional patterns from noise:
- **Base-building phase:** volume should generally contract/decline as the pattern matures (supply drying up).
- **Breakout bar:** volume should expand, typically **≥ 40–50% above the 50-day average volume** (this exact threshold shows up consistently across VCP and cup-and-handle sources — treat it as the default breakout-volume filter, tunable).
- Compute `rel_volume = breakout_bar_volume / sma(volume, 50)` and use it both as a hard filter (reject breakout below 1.0×) and as a confidence input (score scales up to ~1.5×+).

### 3.4 Breakout / confirmation logic
A pattern is **CONFIRMED** only on a *close* beyond the relevant level (neckline, resistance trendline, handle high, pivot point) — not an intrabar wick — to avoid false positives from noise spikes. Add an optional "buffer" (e.g. 0.1–0.5% or a fixed cents amount, echoing O'Neil's classic 10-cent buffer for cup & handle) to avoid whipsaw on marginal closes.

### 3.5 Invalidation logic (state machine)
Every pattern gets 4 states:
- `PENDING` — geometry present, not yet broken out (pattern is "forming").
- `CONFIRMED` — breakout close through the trigger level with volume confirmation.
- `INVALIDATED` — price violates the pattern's structural premise before/without a valid breakout (defined per-pattern below — e.g., a new pivot exceeding the head in an H&S, or price closing back inside a triangle after a false breakout).
- `EXPIRED` — pattern exceeds a max lifespan (e.g., no breakout within `2×` the pattern's formation duration) without confirming or invalidating; drop it as no-longer-relevant.

### 3.6 Measured-move price target
Standard convention across nearly all these patterns: **project the pattern's vertical height from the breakout point** in the breakout direction.
- H&S: `target = neckline_price_at_breakout − (head_price − neckline_price_at_head)`
- Cup & Handle: `target = breakout_price + (cup_high − cup_low)`
- Triangle: `target = breakout_price ± (triangle_height_at_widest_point)`
- VCP: no formal measured-move convention in the source material; use `pivot_price + (pivot_price − base_low)` as a conservative default, and treat the prior base's high (if a prior base exists) as an alternate reference target.

---

## 4. Pattern-by-Pattern Specifications

For each pattern: **Geometry → Pivot sequence → Detection algorithm → Quantitative thresholds → Validation checklist → Invalidation → Volume signature → Target.**

### 4.1 Head and Shoulders (Top) — bearish reversal

**Geometry:** Left shoulder (peak) → trough → Head (higher peak) → trough → Right shoulder (peak, roughly ≈ left shoulder height) → neckline break.

**Pivot sequence (5 pivots minimum):** `HIGH(LS) → LOW(T1) → HIGH(Head) → LOW(T2) → HIGH(RS)`, then a close below the neckline (line through T1–T2) confirms.

**Detection algorithm:**
1. Require a qualifying prior uptrend of **≥ 15%** into the left shoulder.
2. Scan consecutive pivot 5-tuples of the above H-L-H-L-H shape.
3. Check `Head > LeftShoulder` and `Head > RightShoulder` (strict).
4. Check shoulder symmetry: `|LS − RS| / Head ≤ tolerance` (typical tolerance ~10–15% of head height; score continuously — tighter symmetry = higher confidence rather than a hard cutoff, since real-world shoulders are rarely equal).
5. Fit neckline through T1, T2 — allow **sloped neckline** (up or down) but cap slope (e.g. reject if neckline slope implies >X% change over the pattern's width — a wildly sloped neckline undermines the pattern's premise).
6. Confirm minimum bar-count between pivots (avoid 3-bar noise patterns) — e.g. each leg ≥ 5 trading days.
7. PENDING until close beyond neckline; CONFIRMED on that close (extra confidence if it comes with the ~40%+ volume expansion signature).

**Inverse H&S (bottom):** identical logic mirrored (L-H-L-H-L pivots, head is *lowest* low, breakout is close *above* neckline, bullish), requires prior **downtrend**.

**Invalidation:**
- Any pivot after the head that *exceeds* the head (new high beyond head level before neckline break) invalidates — the "head" is no longer the dominant peak.
- Price closing back above the neckline shortly after a confirmed breakdown (failed breakout / whipsaw) → flag as `INVALIDATED_FAILED_BREAKOUT`, don't silently drop it — record it, it's useful for false-positive analysis.
- Right shoulder forming *above* the head → not H&S at all, reclassify/reject.

**Volume signature:** classically, volume is highest on the left shoulder's advance, lower on the head's advance (early divergence warning), and lowest on the right shoulder's advance; breakout volume should expand. Weight this as a confidence booster, not a hard gate — real data is noisy here.

**Target:** neckline − (head − neckline), measured vertically at the breakout point, projected downward from the breakout.

---

### 4.2 Double Top / Double Bottom (bonus — closely related to H&S, cheap to add)

**Geometry:** two peaks (or troughs) at approximately equal price, separated by one trough (or peak).

**Pivot sequence:** `HIGH(P1) → LOW(T) → HIGH(P2)`, with `|P1 − P2| / P1 ≤ ~3%` tolerance, confirmed on close below T (the intervening trough acts as the "neckline").

**Invalidation:** a new high beyond both P1/P2 before confirmation. **Target:** trough − (peak − trough), same measured-move logic as H&S with a single "head."

---

### 4.3 Ascending / Descending / Symmetric Triangles — continuation (occasionally reversal)

**Geometry:**
- **Ascending:** flat/horizontal resistance (upper trendline) + rising support (lower trendline) → bullish bias.
- **Descending:** flat/horizontal support (lower trendline) + falling resistance (upper trendline) → bearish bias.
- **Symmetric:** converging trendlines, resistance falling and support rising → neutral, direction confirmed only by breakout.

**Pivot sequence & detection algorithm:**
1. Take the most recent **N pivots** (5–6 is the common convention — enough for 2–3 touches per side without being so many that the "pattern" is really just a wide trading range).
2. Split pivots into HIGHs and LOWs; fit a regression line through each set.
3. Classify by slope:
   - `|upper_slope| < flat_threshold` and `lower_slope > 0` → Ascending.
   - `|lower_slope| < flat_threshold` and `upper_slope < 0` → Descending.
   - `upper_slope < 0` and `lower_slope > 0` (both meaningfully non-flat) → Symmetric.
4. **Minimum touches: 2 per trendline (4 total)** is the hard floor to even call it a triangle; treat this as gating. 3+ touches per line is a confidence boost, not a requirement.
5. Require **convergence**: the trendlines must actually be narrowing (`range_at_start > range_at_end`), and check the **apex is ahead of, not behind, the current bar** (a triangle whose lines would have already crossed is stale/invalid).
6. Duration check: reject triangles that resolve in a handful of bars (typical: several weeks to a few months on daily charts) — too-fast "triangles" are usually just noise around 4 random points.
7. Confirm on close beyond either boundary. For ascending/descending, note whether breakout direction matches the pattern's directional bias (upside break of an ascending triangle is the "expected" resolution; a downside break is a valid but lower-prior-probability signal — still tag it, don't discard).

**Invalidation:**
- A pivot inside the pattern that breaks a trendline *without* a qualifying close-through (a wick-only violation) does not invalidate but should reduce confidence.
- Price reaching the apex without breaking out → pattern **EXPIRES** (no more room left for the triangle to mean anything).
- A confirmed breakout that closes back inside the triangle within a few bars → `INVALIDATED_FAILED_BREAKOUT`.

**Volume signature:** declining volume into the apex, expansion (again, the ~40–50%-above-average convention) on breakout.

**Target:** height of the triangle at its widest point (left side), projected from the breakout point in the breakout direction.

---

### 4.4 Cup and Handle (+ Inverse) — bullish continuation

**Geometry:** rounded U-shaped "cup" (not a sharp V) recovering to roughly the prior high, followed by a smaller, tighter "handle" pullback in the upper half of the cup, then breakout above the handle high.

**Pivot sequence:** `HIGH(left rim) → LOW(cup bottom, possibly several pivots forming the rounding) → HIGH(right rim ≈ left rim) → LOW(handle low) → breakout`.

**Detection algorithm & thresholds** (O'Neil's original criteria, as adapted/refined by later practitioners — treat the ranges as configurable parameters, not magic constants):
1. Require prior uptrend **≥ 30%** into the left rim.
2. **Cup depth:** 12–33% retracement from left-rim high (allow up to 40–50% only in high-volatility regimes/bear markets — flag these as lower-confidence rather than rejecting outright).
3. **Roundedness check:** this is the trickiest part to encode numerically. Two practical approaches:
   - Fit a quadratic (parabola) to the cup's price path and require a good R² fit (rounded) vs. a poor fit (V-shaped/sharp) — this operationalizes "rounded not V-shaped."
   - Simpler heuristic: require the cup to consist of **multiple pivots on both the down-leg and up-leg** (not a single sharp drop and single sharp recovery), and that no single-bar move accounts for a large fraction of the total cup depth.
4. **Left/right rim symmetry:** right rim should recover to within ~0–5% of left rim price (allow right rim slightly below left rim; a right rim *above* the left rim is fine too and often bullish).
5. **Cup duration:** roughly 7–65 weeks on weekly data (most reliable in the 1–6 month range on daily data) — reject cups shorter than a few weeks as noise.
6. **Handle:** must form in the **upper half** of the cup's total range, retrace **no more than ~33% (up to 50% in choppier tape) of the cup's total advance**, drift sideways-to-down (not a fresh sharp selloff), on **contracting volume**, over roughly 1–4 weeks.
7. Breakout: close above handle high (+ small buffer), with the ~40–50% volume-expansion confirmation.

**Invalidation:**
- Handle depth exceeding ~50% of cup depth, or handle dropping into the lower half of the cup → structurally broken, reclassify as failed base rather than valid handle.
- New low below the cup bottom at any point after the cup is "complete" → invalidated.

**Inverse cup & handle:** mirror image (bearish continuation, rounded top + small upward "handle" bounce, breakdown below handle low). Same thresholds mirrored; note in literature this variant has a somewhat lower documented win rate than the standard bullish version.

**Target:** breakout price + cup depth (measured move), projected upward (or downward for inverse) from the breakout.

---

### 4.5 Volatility Contraction Pattern (VCP) — bullish continuation/base

**Note on rigor:** VCP is the least formally standardized pattern here — it comes from Mark Minervini's trading books/methodology rather than classical TA literature, and sources vary on exact thresholds. Implement it as a **quantitative, parametrized rule** (this is actually its strength — it's the most naturally algorithmic of all these patterns) rather than chasing a single "official" definition.

**Geometry:** a sequence of **2–6 successive pullback legs within a base**, each pullback shallower than the previous, accompanied by declining volume, culminating in a low-volatility "pivot" point, then a volume-confirmed breakout.

**Detection algorithm:**
1. Require prior uptrend and a **Trend Template gate** before even looking for VCP (this is closely tied to Minervini's methodology): price above rising 150/200-day MAs, 50-day MA above 150/200-day MA, price within a reasonable % of its 52-week high, etc. Implement as a configurable `is_in_stage2_uptrend(df)` filter — VCP is a continuation setup within an established uptrend, not a standalone shape.
2. Within the base window, run the pivot extractor at fine granularity to get the sequence of local highs/lows (each high→low leg = one "contraction").
3. Compute each contraction's depth as `% decline from that leg's high to that leg's low`.
4. Validate **monotonically decreasing contraction depth**: `depth[i+1] < depth[i]` for each successive contraction (allow one minor tolerance violation, don't require perfect monotonicity — real data is noisy). Typical real-world sequences look like 20–25% → 10–15% → 5–8% → 2–3%.
5. Each contraction's **low should hold above the previous contraction's low** (higher lows within the base) — this is what separates VCP from a stock just chopping sideways.
6. Compute **volume trend** across the base — average volume per contraction leg should also trend down; flag (don't reject) if it doesn't, since price contraction is the primary signal and volume is confirmatory.
7. Compute an **ATR-contraction ratio**: `ATR(10) at the final contraction / ATR(50) baseline` — should fall meaningfully below 1 (commonly cited: roughly ⅓ of the longer-term average) as a quantitative proxy for "volatility has dried up."
8. Define the **pivot price** = high of the final (tightest) contraction.
9. Confirm on close above pivot price with the standard ~40–50%+ volume expansion, ideally also closing back above the 20-day MA on the breakout bar.

**Invalidation:**
- A later contraction violates the "shallower than previous" rule by a wide margin, or a contraction's low breaks below the base's overall low → base is broken, not a valid VCP; reclassify as failed base.
- Price closes below a rising 50-day MA during base formation → invalidate (violates the Stage-2-uptrend precondition).

**Volume signature:** this is core to the pattern, not just confirmatory — declining volume through each successive contraction, sharp expansion on breakout.

**Target:** no single agreed convention; implement `pivot + (pivot − base_low)` as the default measured-move target, and separately surface "prior base high" / recent swing high as an alternate resistance-based target for the consumer to choose from.

---

### 4.6 Rising / Falling Wedges (bonus — cheap add given triangle infrastructure)

**Geometry:** both trendlines slope in the *same* direction (both up = rising wedge, bearish; both down = falling wedge, bullish) and converge. This is the key discriminator vs. triangles (which have one flat or opposite-sloped line) and vs. channels (which don't converge).

**Detection:** reuse the triangle trendline-fitting code; classify as wedge when `sign(upper_slope) == sign(lower_slope)` and both are meaningfully non-zero, with convergence. Rising wedges typically resolve bearishly (even appearing within uptrends), falling wedges bullishly — flag this counter-to-slope-direction resolution explicitly, it's a common source of confusion vs. triangles.

**Target/invalidation:** same measured-move and apex-based expiration logic as triangles.

---

### 4.7 Flags & Pennants (bonus — short/mid-term continuation, cheap given zigzag infra)

**Geometry:** a sharp, near-vertical prior move (the "flagpole") followed by a brief, low-volatility consolidation that's a small parallel channel (flag) or small symmetric triangle (pennant), then continuation in the flagpole's direction.

**Detection:** identify a flagpole leg (large % move in few bars, elevated volume) via the pivot sequence, then check the immediately following consolidation is (a) short (typically days to a few weeks — much shorter than the patterns above), (b) low-volatility relative to the flagpole, (c) retraces a limited fraction of the flagpole (commonly under ~50%). **Target:** flagpole length projected from breakout.

---

### 4.8 Rounding Bottom / Rounding Top (bonus)

**Geometry:** cup and handle without the handle — a long, smooth U (or inverted-U) with no distinct second pullback, breakout above the level where the rounding began.

**Detection:** reuse the cup's quadratic-fit roundedness check; skip the handle-specific rules; require a longer duration than a typical cup (rounding patterns tend to be slower/larger).

---

## 5. Core Data Model (for Claude Code to implement against)

```python
@dataclass
class PatternMatch:
    pattern_type: str                 # "HEAD_AND_SHOULDERS", "VCP", "ASCENDING_TRIANGLE", ...
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    pivots: list[Pivot]               # the defining pivot sequence
    key_levels: dict[str, float]      # e.g. {"neckline_start":.., "neckline_end":.., "head":..}
    trendlines: dict[str, tuple[float, float]]   # slope, intercept, keyed by name
    status: Literal["PENDING", "CONFIRMED", "INVALIDATED", "EXPIRED"]
    breakout_bar: Optional[int]
    entry_price: Optional[float]
    stop_price: Optional[float]
    target_price: Optional[float]
    confidence: float                 # 0-1, see §6
    volume_confirmed: bool
    formation_start: datetime
    formation_end: datetime
    notes: list[str]                  # human-readable reasons for score/status, for debuggability
```

Each pattern gets its own `Detector` implementing a common interface:

```python
class PatternDetector(ABC):
    @abstractmethod
    def scan(self, df: pd.DataFrame, pivots: list[Pivot]) -> list[PatternMatch]: ...
```

A top-level `PatternScanner` runs all registered detectors over a symbol's history and merges/dedupes overlapping matches.

---

## 6. Confidence Scoring Framework

Every geometric threshold above ("2 vs 3 touches," "12–33% cup depth," "±10% shoulder symmetry") should be a **soft scoring input, not a hard binary gate**, except for a small set of true structural invariants (head must exceed both shoulders; trendlines must actually converge for a triangle; handle must be in the upper half of the cup). Hard-gate only on structural invariants; everything else contributes to a weighted confidence score, e.g.:

| Factor | Weight (example) |
|---|---|
| **Geometric cleanliness** (see §6.1 — how well the pattern fits its own idealized rules) | 30% |
| Volume signature match (contraction-in, expansion-on-breakout) | 25% |
| Duration within the "typical" range for the pattern | 15% |
| Prior trend strength/qualification | 15% |
| Breakout close strength (% beyond level, not just a marginal close) | 15% |

Expose the weights as config — this is exactly the kind of thing you'll want to tune against backtested outcomes rather than guess once and freeze.

### 6.1 Geometric Cleanliness Sub-Score

This is the piece worth calling out on its own: a numeric measure of *how well the actual pivots/price path adhere to the pattern's idealized geometry*, independent of volume, duration, or trend context. Two patterns can pass every hard gate and still be wildly different quality — one where pivots sit almost exactly on the trendlines and shoulders are near-identical, another that technically qualifies but is visually messy. Cleanliness is what separates those. Compute it as its own `0–1` sub-score, itself a weighted blend of pattern-agnostic metrics plus a couple of pattern-specific ones:

**Pattern-agnostic metrics (apply to any pattern with trendlines/key levels):**

| Metric | How to compute | What it penalizes |
|---|---|---|
| **Trendline fit (R²)** | Fit each boundary line via linear regression through its touch points; compute R² of the fit. For a 2-point line this is trivially 1.0 — the metric only differentiates once you have 3+ touches. | Ragged, non-collinear touches (a "trendline" that only loosely connects its points) |
| **Touch tightness** | For every bar (not just pivots) that approaches a boundary, compute perpendicular distance normalized by ATR: `dist / ATR(14)`. Average (or take a penalized max) across all touches. | Touches that are technically "near" the line but by a sloppy margin |
| **Point count vs. minimum** | `min(touches_found / min_required, 1.0)` per boundary, e.g. 4 touches on a triangle that needs 2 scores higher than a bare-minimum 2-touch pattern. | Bare-minimum patterns that technically qualify on the fewest possible points |
| **Overshoot/undershoot penalty** | Count of pivots that pierce *through* a boundary by more than the tolerance band before the eventual breakout (i.e., "near-misses" that violate the pattern's premise without formally invalidating it). | Patterns with messy intermediate noise even if the overall shape holds |
| **Angle/slope sanity** | For patterns with a directional bias (ascending/descending triangle, wedges), check the sloped trendline's angle is neither ~flat (indistinguishable from the "flat" side) nor absurdly steep (unsustainable, more noise than trend). Score highest in a moderate mid-range. | Degenerate slopes that game the classification rather than reflecting real structure |

**Pattern-specific cleanliness additions:**

- **H&S / Double Top-Bottom — symmetry precision:** score continuously on both *price* symmetry (`1 − |LS − RS| / Head`) and *time* symmetry (`1 − |bars(LS→Head) − bars(Head→RS)| / bars(LS→RS)`). A pattern with near-mirror-image shoulders in both price and time is materially cleaner than one that merely satisfies the tolerance band.
- **Triangles / Wedges — convergence quality:** score how *monotonically* the range narrows leg-over-leg (penalize a triangle where range widens on an intermediate swing before resuming convergence), and how close the current bar sits to the apex without having reached it (too early = little conviction yet; right before the apex = classic high-conviction zone; past the apex = should already be EXPIRED).
- **Cup & Handle / Rounding patterns — roundedness fit:** use the quadratic-fit R² from §4.4 directly as this metric — a high R² against a parabola is a direct, principled cleanliness measure for "is this actually U-shaped or does it just technically retrace and recover."
- **VCP — contraction monotonicity strictness:** score how cleanly `depth[i+1] < depth[i]` holds across *all* legs with no violations (vs. the one-tolerance-violation-allowed floor used for the hard gate in §4.5) — a textbook 25%→12%→5%→2% sequence should score near 1.0, a noisy sequence that only barely avoids violating monotonicity should score much lower.

**Suggested aggregation:** average the pattern-agnostic metrics, then blend with the pattern-specific metric (e.g. 60% agnostic / 40% pattern-specific) to get the final cleanliness sub-score feeding into §6's top-level table. Surface the individual metric values (not just the blended score) in `PatternMatch.notes` — when you're eyeballing detector output during tuning, "symmetry: 0.91, touch_tightness: 0.62, R²: 0.88" is far more actionable than a single opaque 0.79.

This also gives you a natural UI/output feature for free: rank same-type pattern matches by cleanliness alone (separate from the volume/duration/trend-weighted overall confidence) when a user wants "show me the textbook-cleanest head and shoulders on the market right now" versus "show me all valid ones ranked by expected edge."

---

## 7. Validation Methodology (don't skip this)

Because every pattern here is fuzzy, the module is only trustworthy if you can measure it:

1. **Labeled test set:** hand-label a few hundred historical instances (both true positives and known "looks-like-but-isn't" negatives) across varied names/regimes. Bulkowski's *Encyclopedia of Chart Patterns* and Investor's Business Daily / MarketSmith base annotations are useful references for building this set.
2. **Precision/recall per pattern type**, not just aggregate — H&S and triangles will have very different false-positive rates.
3. **Outcome-based backtest, separate from detection accuracy:** for CONFIRMED patterns, measure forward returns (e.g., N days after breakout), target-hit rate, and failure/throwback rate (Bulkowski-style statistics — e.g. cup & handle's documented ~5% break-even failure rate and ~62% throwback rate are useful benchmarks to compare your detector's outcomes against). A detector can have great geometric precision and still be useless if the pattern itself has no edge — keep these two evaluations separate.
4. **Sensitivity analysis on pivot-extraction parameters** (ZigZag % / ATR multiple) — pattern counts and quality will swing a lot with this single parameter; sweep it and report stability, don't just pick one value and move on.
5. Track and surface `INVALIDATED_FAILED_BREAKOUT` cases explicitly rather than discarding them — false-breakout rate is itself a valuable output for building stop-placement rules.

---

## 8. Suggested Module Layout

```
patterns/
  pivots.py            # ZigZag + PIP pivot extraction, common Pivot dataclass
  trendlines.py         # regression fitting, touch counting, slope classification
  volume.py             # relative-volume helpers, contraction/expansion checks
  base.py                # PatternMatch, PatternDetector ABC, state machine
  detectors/
    head_shoulders.py    # + inverse
    double_top_bottom.py
    triangles.py          # ascending/descending/symmetric + wedges (shared trendline logic)
    cup_and_handle.py     # + inverse, + rounding bottom/top variant
    vcp.py
    flags_pennants.py
  scanner.py              # orchestrates all detectors over a symbol/date range
  scoring.py              # confidence weighting, configurable
  backtest/
    labeler.py            # tooling to hand-label historical instances
    evaluator.py           # precision/recall + forward-return outcome stats
config/
  pattern_thresholds.yaml # every numeric threshold in this doc, externalized and tunable
```

Keep **every numeric threshold in this doc in one external config file**, not hardcoded — you will be tuning these against your validation set, and different asset classes (large-cap vs. small-cap, equities vs. crypto) will likely need different values (e.g., a 20% ZigZag threshold is standard for volatile crypto but far too loose for a mega-cap on daily bars).

---

## 9. Key Open Design Decisions (flag these for yourself before implementation)

1. **Bar interval:** daily vs. weekly detection, or both, feeding different holding-period use cases (mid vs. long-term, per your framing).
2. **Real-time vs. end-of-day:** ZigZag's most recent pivot is unconfirmed/repainting — decide whether the scanner runs EOD-only (simpler, avoids repaint issues) or needs an intrabar mode (materially harder).
3. **Overlap handling:** the same swing points can simultaneously look like more than one pattern (e.g., a triangle that's also arguably a wedge) — decide whether to return all candidate matches with confidence scores (recommended) or force mutually-exclusive classification.
4. **Multi-timeframe confluence:** whether a pattern needs to be checked for higher-timeframe context (e.g., a weekly uptrend backdrop) before being surfaced — most sources treat "prior trend" and "market/sector regime" as important qualifiers, not the pattern shape in isolation.

---

## 9.1 Resolved Decisions

- **Bar interval:** both daily and weekly, configurable per scan — not two separate codepaths. `extract_pivots`, every detector, and the config file should all take a `timeframe` param that just changes which resampled `df` and which threshold profile (e.g. ZigZag %/ATR mult, min-bar durations) gets used. Weekly detection is the same code running on weekly-resampled OHLCV with a weekly-tuned threshold set in `pattern_thresholds.yaml` — don't fork logic, fork config.
- **Execution mode:** end-of-day batch only. This simplifies pivot extraction meaningfully — the scanner runs once per day after the close, every pivot in the output except possibly the very last one is fully confirmed, and there's no need to handle intrabar repainting or streaming updates. Still mark the most recent pivot `confirmed=False` in the data model (§5) since it can still be revised by tomorrow's bar, but the module never needs to re-evaluate mid-session.

## Sources referenced in this research
General pattern rules and thresholds cross-referenced from: Thomas Bulkowski's *Encyclopedia of Chart Patterns* (cited throughout the TA industry as the primary empirical source for pattern statistics), William O'Neil's *How to Make Money in Stocks* (cup and handle), Mark Minervini's *Trade Like a Stock Market Wizard* / *Think & Trade Like a Champion* (VCP), StockCharts ChartSchool conventions, and several algorithmic-detection writeups (Lo/Mamaysky/Wang-style kernel regression approaches, Chong & Poon's noise-filtered H&S recognition, ZigZag/PIP-based practitioner implementations on TradingView/MQL5/QuantConnect). Treat all specific numeric thresholds as **reasonable, literature-grounded starting points to tune against your own backtest**, not laws of physics — this is the core reason §6 and §7 (soft scoring + validation methodology) matter as much as the pattern geometry itself.