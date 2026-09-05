# Order Blocks — Design Doc

**Status:** Closed, not shipping. §3's prototype/backtest gate was run against the full ticker universe and failed decisively — see §6. This doc is kept as a record of the investigation, not a pending implementation plan.

**Origin:** Came up while reviewing real chart examples for `feature/pivot-breakout-validation`'s BOS/CHoCH work (see `docs/features/pivot_breakout_validation_design.md`). An SMC/ICT reference article's example chart labeled a short entry as an "order block retest," which isn't a concept this codebase has — this doc scopes whether/how to add it.

---

## 1. What an order block is

Stripped of SMC/ICT jargon: **the last candle of the opposite color immediately before an impulsive move, whose price range becomes a supply/demand zone expected to hold on a later retest.**

- **Bearish order block** = the last up-candle right before a sharp breakdown. Theory: that candle is where large players built short positions (or offloaded longs) right before pushing price down, so its range becomes a supply zone — a later rally back into it is treated as a high-probability short (a "retest").
- **Bullish order block** = the mirror, last down-candle before a sharp rally.

SMC content typically pairs this with BOS/CHoCH: the break confirms a regime change, and the order block retest afterward is the actual entry trigger.

## 2. Is it just S/R with a different name?

Mostly yes, but the difference is real and specific: it's a different **evidence standard** for calling a zone valid, not a different kind of zone.

- `src/signals/sr_lines/` (this repo's existing S/R engine) requires a level to be **tested multiple times** before it's scored as meaningful — `min_touches_per_line`, duration/density scoring, resilience to failed breaks. A zone earns credibility from repeated respect over time.
- An order block claims a zone is valid **on its first retest, before it's ever been touched** — its evidence is "this candle preceded an impulsive move," not touch count. That's a weaker, more speculative signal, evaluated once rather than accumulated.

So: same output shape (a horizontal price zone with support/resistance semantics), different, unvalidated input signal for *which* zones deserve attention.

## 3. Does it hold up on daily/weekly bars?

Genuine open question, flagged rather than resolved here (same caution applies to BOS/CHoCH on 1D/1W — see the other design doc's discussion). Two considerations pulling opposite ways:

- **Against:** On an intraday chart, SMC treats one candle as one coherent institutional footprint (one actor's accumulation within a session). On a daily chart, "yesterday's candle" is a much coarser, more arbitrary slice of time — less likely to correspond to a single deliberate actor's order flow. The identification heuristic was calibrated to a data granularity this repo doesn't even store (no working intraday bars — see `market_common/data.py`).
- **For:** Reinterpreted loosely, "the origin candle of a strong breakout leg" is a real, commonly-watched daily-swing heuristic independent of SMC branding (e.g., watching the base candle before an earnings gap as support on a pullback). The mechanic itself — mark a candle-derived zone, track whether later price respects it — is timeframe-agnostic even if the SMC "why" isn't.

**Recommendation: prototype and backtest before committing engineering time.** Specifically: does "last opposing candle before an impulsive move" identify zones that hold up *better* than the horizontal zones `sr_lines` already finds via pivot clustering? If order-block-derived zones are mostly a subset of (or worse than) what the existing pivot-based candidate generation already surfaces, this isn't worth a separate feature — just a relabeling.

## 4. Proposed implementation shape (if it clears the prototype check)

The key insight: this is cheap to build, because the expensive part already exists. Order blocks would be a **new candidate-generation method feeding into `sr_lines`'s existing zone engine**, not a new detection engine or lifecycle:

- **New, small piece:** a candidate generator — scan bars for an "impulsive move" (a large-range breakout bar, or a gap, relative to ATR), find the last opposite-color candle immediately before it, emit its high/low range as a horizontal zone candidate. Natural home: a new function in `src/signals/sr_lines/candidates.py`, alongside the existing pivot-based `generate_horizontal_candidates`/`generate_diagonal_candidates`.
- **Reused, unchanged:** everything downstream. `sr_lines/events.py`'s TOUCH/BODY_TOUCH/WICK_FAKE/BODY_FAKE/BREAK classification, `sr_lines/scoring.py`'s scoring, `sr_lines/flip_status.py`'s break/flip tracking — none of it cares where a candidate zone came from. An order-block-sourced candidate would flow through the same `classify_events` → `score_line` → `build_line` pipeline real pivot-sourced candidates already use.
- **Open question:** does `Line`/`DetectionResult` need a field marking a line's *origin* (pivot-cluster vs. order-block), so a consumer can filter/distinguish them? Likely yes — a one-field addition to `sr_lines/models.py::Line`, not a schema overhaul.
- **What defines "impulsive"?** Not yet specified — candidate knobs: a bar (or short run of bars) whose range/gap exceeds some ATR multiple, mirroring how `patterns/config.py` already gates "prior trend" moves elsewhere in this codebase. Needs real-data calibration, same discipline `patterns/config.py`'s many hand-tuned, measured-against-real-data thresholds already follow (see that file's comments for the pattern to follow, e.g. `cup_rim_divergence_max_pct`'s calibration history).

## 5. Explicitly out of scope for this doc

- No code written yet.
- No decision on whether this ships at all — §3's prototype/backtest check is a gate, not a formality.
- Bullish order blocks, mitigation/"breaker block" variants, and fair-value-gap (a related but distinct SMC concept) are not addressed here — scope creep to avoid pulling in without a specific need.

## 6. §3 gate result: order blocks lose to pivot clustering, don't ship

Built and ran (then discarded, once the result was recorded here) the minimal version of §4's candidate generator: scan for a bar whose body exceeds a `body_atr_mult` multiple of ATR (an "impulsive" bar), take the nearest opposite-colored candle within a bounded lookback as the zone. Ran it through the *exact* same `sr_lines.events.classify_events` pipeline real pivot-clustered candidates use, so the comparison isolated candidate origin, not evaluation method. Deliberately never wired into `candidates.py`/`engine.py` -- this was a gate check, not a committed feature, and the gate failed.

Measured first-retest hold rate and forward returns (mean/median/winsorized mean at 10/20/60 bars, conditional on the retest holding) for order-block zones vs. `generate_horizontal_candidates`'s existing pivot-clustered zones, `medium_term` preset, **every ticker in `bars_1d`** (5,314 tickers, 0 failures):

| | n candidates | hold rate | median return 10b | median return 20b | median return 60b |
|---|---|---|---|---|---|
| order_block | 65,870 | 81.8% | 0.11% | 0.17% | 0.19% |
| pivot_cluster | 84,039 | 85.7% | 1.44% | 1.21% | 0.67% |

Pivot clustering wins on every axis measured: more candidates found, a higher hold rate, and 4-13x higher median forward returns at every horizon (mean and winsorized mean tell the same story). This is exactly the failure condition §3 named going in: order-block zones are not merely a subset of what pivot clustering already finds, they're a *worse* signal by the same evidence standard. Reinterpreting "last opposing candle before an impulsive move" as a timeframe-agnostic swing heuristic (§3's "for" argument) doesn't rescue it -- on this data, at daily granularity, it underperforms the thing it would have to justify a separate code path against.

**Decision: don't build §4.** The prototype/backtest code itself was not kept (a closed investigation isn't a reason to carry a dead module) -- this section is the record. Rebuilding it would be quick if a future variant (different `body_atr_mult`/lookback calibration, a different timeframe, order-block origin as a *tiebreaker* within existing pivot clusters rather than a standalone source) is ever worth a re-check, but the default assumption going forward is that this line of investigation is closed, not paused.
