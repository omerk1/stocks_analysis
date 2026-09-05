# Gaps Backtest — Design Doc

**Status:** Not started. Scoping doc only.

**Related:** `docs/features/shared_outcome_statistics_design.md` §3 step 5 lists "gaps/divergences/fibonacci/avwap/sr_lines each getting their own lightweight aggregation step" as flagged-but-not-scoped. This doc is that scoping for `gaps` specifically — the first of the five. Modeled on the two existing backtest modules: `src/signals/patterns/backtest/evaluator.py` (the original) and `src/signals/market_structure/backtest.py` (the newer one, already built on `market_common.stats.distribution_stats` rather than the older private `_return_stats`).

**Origin:** Picked as the first of the five §3-step-5 modules because, per §2 below, it turns out to need less new code than either existing precedent — `gaps/lifecycle.py` already computes real outcome fields per gap, so this is closer to "finally aggregate data that already exists" than "build new outcome-computation machinery."

---

## 1. What already exists (don't rebuild this)

`src/signals/gaps/lifecycle.py::apply_lifecycle` forward-walks every detected gap from its creation bar to the end of available data and populates, directly on the `Gap` dataclass (`src/signals/gaps/models.py`):

- `status` — `OPEN` / `PARTIAL` / `SOFT_CLOSED` (≥ `config.soft_close_pct`, default 80%) / `CLOSED` (100% filled)
- `max_fill_pct` — the running-max fill, 0-100
- `first_touch_date` / `soft_closed_date` / `closed_date`, each paired with a `bars_to_*` count
- `n_approaches` — distinct times price re-entered the zone and receded (not just the running-max curve — a gap touched once for 40 bars and one touched 10 separate times can share the same `max_fill_pct` and tell very different stories)
- `volume_ratio_at_creation` — rolling-20-bar volume ratio on the creation bar
- `reaction_atr_after_close` / `bars_to_reaction_peak` — once `status == CLOSED`, the ATR-normalized best move *back in the gap's original direction* within `config.reaction_window_bars` (default 10) — the "fill then reverse" check

This is the same shape `patterns`' `PatternMatch.status`/`target_price` or `market_structure`'s `TrendState` carry — a fully-resolved-or-still-open outcome record per event, built once and never touched again. The difference from both: **`apply_lifecycle` already *is* the outcome-computation step.** Neither `patterns/backtest/evaluator.py::compute_outcomes` nor `market_structure/backtest.py::compute_outcomes` has an equivalent here to write — there is no new forward-return or whipsaw-style metric to invent, only aggregation of fields that already exist on every `Gap` row. This is cheaper to build than either precedent, the same "the expensive part already exists" shape `docs/features/order_blocks_design.md` §4 argued for order blocks (which, per that doc's §6, didn't actually pay off there — this is a different, stronger case: the fields aren't a hoped-for reuse, they're already sitting there unaggregated).

`detect.detect(conn, ticker, timeframe, config, as_of=None)` (`src/signals/gaps/detect.py`) runs detection + lifecycle in one call and is the right entry point to scan fresh from — same "don't read the stored table, it may be stale/differently-configured" reasoning `evaluator.py` and `market_structure/backtest.py` both already apply to their own stored tables.

`GapConfig` (`src/signals/gaps/config.py`) has no preset system, unlike `SRConfig`/`MarketStructureConfig`/`PatternConfig` — `cli.py` just instantiates `GapConfig()` directly. The backtest module doesn't need a `--preset` flag; a bare default config (with CLI overrides for the couple of knobs that matter — see §5) is enough.

## 2. What's missing: aggregation across gaps

Same finding the shared-toolkit doc already made for every one of these five modules: no `backtest/` subpackage, no cross-gap summary. Every field in §1 lives on individual `Gap` rows, one detection run at a time. Nobody has ever asked, e.g., "across the whole ticker universe, what fraction of bullish FVGs actually reach `CLOSED`?" or "does high volume at creation predict a faster or slower fill?" — both are directly answerable from fields that already exist, just never rolled up.

## 3. Proposed metrics

All computed via `market_common.stats.distribution_stats` (already built, see `shared_outcome_statistics_design.md`) over the relevant numeric field within each bucket — no new statistical treatment to invent, same discipline `market_structure/backtest.py` already established for reusing it as-is.

- **Fill rate** — fraction of (resolution-eligible, see §4) gaps reaching `CLOSED`. The headline number; the entire "do gaps get filled" question this backtest exists to answer.
- **Soft-close rate** — fraction reaching at least `SOFT_CLOSED` (≥80% filled) — a softer version of the same question, useful precisely because `soft_close_pct` itself is flagged in `config.py` as "a starting point, not validated"; this backtest is what would let someone actually check that.
- **Bars-to-fill distribution** — `distribution_stats` over `bars_to_closed` (and separately `bars_to_soft_closed`) for gaps that reached that milestone. Median answers "how long does a fill typically take"; the full distribution (via `percentiles`) shows whether that's a tight, reliable number or all over the place.
- **Approach-count distribution** — `distribution_stats` over `n_approaches`. Does a gap typically fill on the first return, or only after being tested repeatedly? Directly informs whether "first retest" is even a coherent entry concept for this instrument the way it's debated for order blocks (`order_blocks_design.md` §2's exact question, asked here about a different zone type).
- **Volume-at-creation as a predictor** — split gaps into two buckets by `volume_ratio_at_creation` (above/below its own median within the sample, since there's no natural fixed threshold) and compare fill rate and bars-to-fill between them. A real, checkable hypothesis — e.g. SMC framing treats a high-volume gap as more likely to represent genuine imbalance (holds/continues) vs. a low-volume one as noise (fills fast) — that nothing in this repo currently checks either way.
- **Post-close reaction** — `distribution_stats` over `reaction_atr_after_close` for `CLOSED` gaps only. This is the actual "fill then reverse" trade thesis some gap-trading approaches use; a mean/median near zero (or negative) would mean that thesis doesn't hold up here.

**Bucketing:** by `(kind, direction)` — `classic`/`fvg` × `bullish`/`bearish`, four buckets — the same shape `market_structure/backtest.py` uses for `(event, direction)`, run separately per `--timeframe` (daily/weekly), not merged. `related_id` (an FVG confirmed by a same-bar classic gap vs. a standalone FVG) is a plausible fifth cut but deferred — see §6.

## 4. Right-censoring: the one real design decision

A gap created 3 bars before the end of available data hasn't had a fair chance to fill; counting its current `OPEN` status as a real "never fills" would bias fill rate downward for no good reason — exactly the problem `patterns`' `EXPIRED_UNRESOLVED` vs. `CONFIRMED`/`ACTIVE` split (see `evaluator.py`'s `_BREAKOUT_STATUSES` docstring) and `market_structure/backtest.py`'s whipsaw right-censoring both already solve for their own domains.

`apply_lifecycle` doesn't retain "how many bars were available after creation" once it returns (it only walks and mutates `Gap` in place) — so `backtest.py` needs to compute that itself: `bars_available_after = (len(bars) - 1) - bar_index_of(gap.created_at)`. Small and new, but entirely local to `backtest.py`; no change to `lifecycle.py`/`models.py` needed.

Proposed handling, mirroring `evaluator.py`'s "report the raw thing and the honest thing" discipline (its `mean_return` kept alongside `median_return` rather than replaced):

- A `--resolution-horizon-bars` CLI knob (default: same order of magnitude as `reaction_window_bars`'s existing 10, but this needs its own real-data look before picking a number — treat the default as a starting point, not validated, same caveat `config.py` already attaches to `reaction_window_bars` itself).
- **Fill rate / soft-close rate** computed only over gaps with `bars_available_after >= resolution_horizon_bars` — the headline numbers, denominator excludes anything too young to have had a fair chance.
- **Status distribution "as of last bar"** (including young, still-open gaps) reported alongside as a separate, unfiltered number — informative on its own (what does the *current* open-gap backlog look like), and makes the horizon's effect visible rather than silently discarding data.

## 5. Proposed implementation shape

New file `src/signals/gaps/backtest.py`, modeled on `market_structure/backtest.py`'s shape (closer than `patterns/backtest/evaluator.py`'s, since gaps has no target/stop/`PENDING`→resolution funnel to filter — every detected gap is already a "happened" event the way every `TrendState` is, just possibly still open):

- No new `Outcome` dataclass — operate directly on the `Gap` objects `detect.detect` already returns fully populated. This is the concrete form of §1's "cheaper than both precedents" claim: `compute_outcomes` doesn't need to exist as a separate step here.
- `_bars_available_after(bars, gap) -> int` — the one new piece of arithmetic (§4).
- `summarize(gaps: list[Gap], bars_available_after: dict[str, int], resolution_horizon_bars: int) -> pd.DataFrame` — one row per `(kind, direction)` bucket, columns: `n`, `n_resolution_eligible`, `fill_rate`, `soft_close_rate`, `status_open_pct`/`status_partial_pct`/`status_soft_closed_pct`/`status_closed_pct` (the unfiltered "as of last bar" view from §4), then `distribution_stats`-derived columns (mean/median/wins/std/risk_adj/percentiles/n) for `bars_to_closed`, `bars_to_soft_closed`, `n_approaches`, and `reaction_atr_after_close` (`CLOSED`-only) — same flattening convention `market_structure/backtest.py::summarize` already uses for its per-horizon return columns.
- `run_backtest(raw_conn, tickers, timeframe, config, resolution_horizon_bars) -> pd.DataFrame` — fresh `detect.detect(...)` per ticker (not reading the stored `gaps` table), continue-on-error per ticker, identical shape to both existing `run_backtest`s.
- CLI: `python -m src.signals.gaps.backtest TICKER [TICKER ...] | --all [--timeframe daily|weekly] [--resolution-horizon-bars N]` — `--timeframe` takes `daily`/`weekly` only (not `cli.py`'s `both` convenience — matches how both existing backtest CLIs already scope one timeframe per run, so results aren't silently pooled across timeframes with very different bar-count semantics for `bars_to_closed` etc.).

## 6. Open questions / explicitly deferred

- **FVG-confirmed-by-classic-gap cross-tab:** does an FVG whose `related_id` points to a same-bar classic gap (i.e. the impulsive move was strong enough to also leave a 2-bar gap) fill differently than a standalone FVG? A plausible fifth bucket dimension, not included in §3's four-bucket v1 — flagged as a natural second cut once the base module exists and has been run once.
- **Calibrating `soft_close_pct`/`reaction_window_bars`/`min_gap_atr` against real results** is exactly what this backtest would make possible, but doing that calibration is not part of landing the module — same "build the tool, calibrate as a separate follow-up" split `order_blocks_design.md` and `pivot_breakout_validation_backtest_design.md` both already keep.
- **No comparison against other zone types** (sr_lines, order blocks) is in scope here — `order_blocks_design.md` already ran that comparison for one zone-origin question and it would be its own separate doc if ever extended to gaps.

## 7. Explicitly out of scope

- No code written yet.
- The three calibration/comparison items in §6.
- Full-universe `--all` runs and drawing any conclusion from them — same explicit, separate-step discipline `pivot_breakout_validation_backtest_design.md` §4 already applies ("a multi-hour job... deliberately left as a separate, explicit step rather than run silently as part of landing the code").
