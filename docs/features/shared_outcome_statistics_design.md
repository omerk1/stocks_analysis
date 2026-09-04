# Shared Outcome-Statistics Toolkit — Design Doc

**Status:** Not started. Scoping doc, not an implementation plan — captures a design discussion so it can be picked up later without needing the conversation that produced it.

**Related:** `docs/features/pivot_breakout_validation_backtest_design.md` (scoped to the three new `feature/pivot-breakout-validation` detectors specifically). That doc's §3 says the new `market_structure/backtest.py` should "reuse `evaluator._return_stats` and its exact three-statistic convention" via cross-import from `patterns`. This doc formalizes that instead of leaving it as an informal cross-module import — extract the statistic, not just borrow it.

**Origin:** "Do you think it's possible to create the framework for all signals?" — asked while scoping backtesting for the three new detectors. Investigated before writing this: is a single outcome-evaluation framework across all 8 signal modules (`avwap`, `breadth`, `divergences`, `fibonacci`, `gaps`, `market_structure`, `patterns`, `relative_strength`, `sr_lines`) realistic?

---

## 1. What's actually shared vs. what isn't

**Not shareable, and shouldn't be forced:** what counts as a "good outcome" is genuinely different per domain — a gap's success is "did it fill," a pattern's is "did it hit its measured-move target," an S/R line's is "did it hold as new support after flipping," a CHoCH's is "did the regime survive." Collapsing these into one generic evaluator would either lose real domain meaning or produce an interface so generic it does nothing. Each module's own `lifecycle.py` (all of `gaps`/`divergences`/`fibonacci`/`avwap`/`sr_lines` already have one, tracking fill status / `max_favorable_move_atr` / reaction / flip-and-reclaim respectively) is the right place for that domain logic and should stay put.

**Genuinely shareable, and currently isn't shared:** the *statistical treatment* of "many per-event outcome numbers → one honest summary." `patterns/backtest/evaluator.py::_return_stats` already solved this correctly (mean, median, winsorized mean — see its own docstring for the measured `falling_wedge` case where the plain mean read +21% while the median was negative). That treatment lives as a private function in one module and nowhere else.

**The actual finding, checked directly rather than assumed:** grepped every signal module's file layout. `gaps`, `divergences`, `fibonacci`, `avwap`, `sr_lines` each have a `lifecycle.py` computing real per-event outcome fields — but **none of them has a `backtest/` subpackage or any aggregation step at all.** `patterns` is the only module in the repo that ever summarizes its own outcome data across many events into a number a person could look at. This isn't "5 modules doing it riskily" — it's "5 modules with no way to do it yet." `market_structure` (new, from the other design doc) will be a 6th unless it's built against a shared helper from day one.

## 2. What to extract

New module: `src/foundation/market_common/stats.py` — same tier/convention as `pivots.py`/`indicators.py`/`trendline_fit.py`, a shared primitive every detection engine can call, not owned by any one of them.

```python
@dataclass
class DistributionStats:
    n: int
    mean: float | None
    median: float | None
    winsorized_mean: float | None
    p10: float | None
    p25: float | None
    p75: float | None
    p90: float | None

def distribution_stats(
    values: list[float],
    winsor_limit: float = 0.01,
    percentiles: tuple[float, ...] = (0.10, 0.25, 0.75, 0.90),
) -> DistributionStats:
    ...
```

- Mean/median/winsorized-mean: lifted directly from `_return_stats`, same `WINSOR_LIMIT=0.01` default, same "empty input -> all None, not zero" behavior (a right-censored/no-data case is not a zero return, `_return_stats`'s existing docstring already makes this point and it carries over unchanged).
- **p10/p25/p75/p90, added per this doc's request:** median alone (p50) says nothing about spread. p25/p75 gives an IQR-style "typical range," p10/p90 gives tail behavior without the instability of raw min/max on a small sample. Same reasoning that motivated winsorizing over trimming in the first place — report the shape, don't hide it. Percentile choice is configurable (the four defaults are a starting point, not sacred) but shouldn't grow unbounded; four is enough to see distribution shape without turning every summary table into an unreadable wall of columns.
- Deliberately generic over what the values mean (returns, ATR-normalized moves, days-to-fill, whatever) — takes `list[float]`, no return-specific assumptions baked in.

## 3. Migration plan

1. **Build `market_common/stats.py`** with `distribution_stats`.
2. **Refactor `patterns/backtest/evaluator.py`** to call it instead of its private `_return_stats`. Behavior-preserving for mean/median/winsorized (same numbers, same edge cases); additive for percentiles — `summarize()` gains `p10_return_{h}b`/`p25_return_{h}b`/`p75_return_{h}b`/`p90_return_{h}b` columns per horizon alongside the existing ones, nothing removed. `tests/test_patterns_evaluator.py` needs to keep passing unchanged for the existing columns; new tests cover the added percentile columns.
3. **Add `confidence: float | None` to `PatternOutcome`**, populated from `match.confidence` (already computed by every detector via `scoring.py`, just never carried through to the outcome record). This is the schema change from §0 above — lets `summarize()` eventually bucket by confidence quartile and actually check whether the score means anything, which nothing in this repo can currently do.
4. **Build `market_structure/backtest.py`** (scoped in the other design doc) against `market_common.stats.distribution_stats` directly — not via a cross-import into `patterns`. Its own outcome dataclass should also carry `confidence: float | None` from day one (`None` until BOS/CHoCH gets a scoring pass — tracked separately, see §4 below — so this doesn't need a second migration once that lands).
5. **Lower priority, explicitly not detailed here:** `gaps`/`divergences`/`fibonacci`/`avwap`/`sr_lines` each getting their own lightweight aggregation step using the same shared helper. Each has a different per-event outcome shape (fill %, ATR-normalized favorable move, reaction window, flip persistence), so scoping each one is its own small design question — flagged as the natural next targets once §1-4 land, not planned in detail here.

## 4. Relationship to BOS/CHoCH confidence scoring

A separate, previously-discussed idea: give `market_structure` events a `confidence` score the way `patterns` already has one (`scoring.breakout_close_strength` and `volume_signature_score` are directly reusable as-is; a new "prior pivot significance" component, reusing `trendlines.count_touches`, would be the one genuinely new piece). Not part of this doc's scope, and doesn't block it — but §3 step 4's `confidence: float | None` field only pays off once that scoring work lands, and once it does, this toolkit is what lets its calibration actually be checked against real outcomes rather than left as another "first-pass, not yet tuned" knob.

## 5. Explicitly out of scope

- No code written yet.
- Per-module aggregation for gaps/divergences/fibonacci/avwap/sr_lines (§3 step 5) — flagged, not scoped in detail.
- BOS/CHoCH confidence scoring itself (§4) — separate concern, only its schema compatibility is addressed here.
