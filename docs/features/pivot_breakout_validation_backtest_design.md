# Pivot Breakout Validation — Backtest / Validation Design Doc

**Status:** §2's trigger-key fix and §3's `market_structure/backtest.py` are implemented and sanity-checked against real data (AAPL/MSFT/NVDA, both timeframes). §4's full-universe `--all` runs (both modules, both timeframes) have not been done — that's a multi-hour job across ~6,554 tickers, deliberately left as a separate, explicit step rather than run silently as part of landing the code (see §4 below for the runtime estimate).

**Depends on:** `feature/pivot-breakout-validation` (BOS/CHoCH, Triple Top/Bottom, 1-2-3 Reversal — see `docs/features/pivot_breakout_validation_design.md`) merged to `main` first. This doc references files that only exist on that branch.

**Origin:** While reviewing real chart examples for that branch's three new detectors, two things came up that a single example chart can't settle:
1. Whether BOS/CHoCH (and the other two patterns) are actually good signals, or just correctly-detected geometry — a chart can show the rule fired, not whether it was worth trading.
2. A single hand-picked example is themselves not evidence of anything general — worth noting, an early look at two real instances already showed the honest range: DIS's 1-2-3 Reversal took ~9 weeks to reach its target (not fast), and an AAPL BOS/CHoCH regime that ran cleanly for 9 months eventually reversed on its own CHoCH. Anecdotal, N=1 each, not a substitute for what follows — but the direction it points (these signals have a real distribution of outcomes, not a uniform "it works") is the reason this doc exists.

---

## 1. What already exists (don't rebuild this)

`src/signals/patterns/backtest/evaluator.py` is a working, generic outcome-based backtest harness, built for the design doc's own §7.3: for every match that broke out, compute forward returns at fixed horizons (mean **and** median **and** winsorized mean — see its own docstring for why a single mean is actively misleading on equity return data: one real run showed `falling_wedge`'s 60-bar mean at +21% while its median was negative, because a single sub-dollar stock's +3,080% return supplied 90% of the mean), target-hit rate, failed-breakout rate, and throwback rate. `run_backtest(conn, tickers, timeframe, config)` scans fresh (not from stored `pattern_matches`, since those may be stale/differently-configured), computes outcomes, and `summarize()` groups everything by `pattern_type` into one row per type. There's a CLI: `python -m src.signals.patterns.backtest.evaluator --all --timeframe daily`.

There's also `src/signals/patterns/backtest/labeler.py` — a human-in-the-loop tool for hand-labeling chart windows into a ground-truth table (`pattern_labels`), for eventual precision/recall work. That table is currently empty; nobody has run it yet, for any pattern type, old or new.

## 2. Triple Top/Bottom and 1-2-3 Reversal: already compatible, mostly free

Both go through the exact same pipeline as every other pattern (`scan_bars` → `lifecycle.apply_lifecycle` → `PatternMatch` with `target_price`/`stop_price`/`status`). `evaluator.run_backtest` doesn't allowlist pattern types — it groups by whatever `match.pattern_type.value` says. So:

- **Action item: just run it.** `python -m src.signals.patterns.backtest.evaluator --all --timeframe daily` (and `--timeframe weekly`) already produces real hit-rate/forward-return/throwback stats for `triple_top`, `triple_bottom`, and `reversal_123` alongside every existing pattern type, with zero new code. This hasn't been run yet for the two new types.
- **One real, small gap: throwback-rate accuracy.** `evaluator._reconstruct_trigger_at` looks up each pattern type's trigger level from `match.key_levels`/`match.trendlines` via three lookup tables (`_FLAT_TRIGGER_KEY`, `_SLOPED_FIXED_TRIGGER_KEY`, `_SLOPED_DIRECTIONAL_TRIGGER_TYPES`), so `had_throwback` can compare against the pattern's *real* per-bar level. `TRIPLE_TOP`/`TRIPLE_BOTTOM`/`REVERSAL_123` aren't in any of those tables, so today `had_throwback` silently falls back to `match.entry_price` — which is a materially *wrong* stand-in here (entry_price is the breakout bar's close, already past the trigger by construction; the neckline/Point-2 level it should be compared against is a different, earlier value). Fix: both new pattern detectors already persist a flat trigger under the key `"neckline"` (triple top/bottom, `detectors/double_top_bottom.py::_build_triple_match`) and `"point2"` (1-2-3 reversal, `detectors/reversal_123.py`) — same convention `DOUBLE_TOP`/`DOUBLE_BOTTOM` already use. Add three lines to `_FLAT_TRIGGER_KEY`:
  ```python
  PatternType.TRIPLE_TOP: "neckline",
  PatternType.TRIPLE_BOTTOM: "neckline",
  PatternType.REVERSAL_123: "point2",
  ```
  Do this *before* running the backtest, not after — otherwise the first run's throwback numbers for these two types are wrong and need re-running anyway.
- **Optional, lower priority:** grow `pattern_labels` for these two types via `labeler.py`, same "opportunistically from the first detector onward" discipline that module's docstring already documents — not blocking, precision/recall work for *any* pattern type is deferred until that table has real rows.

## 3. BOS/CHoCH (`market_structure`): genuinely new work

`track_market_structure()` only emits `TrendState` events — no `target_price`, no `stop_price`, no lifecycle, nothing `evaluator.py` can consume. This needs its own small backtest module, modeled directly on `evaluator.py`'s shape rather than reinvented:

- **New file, e.g. `src/signals/market_structure/backtest.py`:**
  - `forward_return_pct(bars, event, horizon_bars)` — mirrors `evaluator.forward_return_pct` exactly: signed % return `horizon_bars` after `event`'s break bar, positive in the event's own direction. `TrendState` has no `entry_price` field the way `PatternMatch` does; use `event.close` (the field already exists) as the entry basis.
  - **Reuse `evaluator._return_stats` and its exact three-statistic convention (mean, median, winsorized mean) — do not reinvent this.** The reason it exists (equity forward returns are right-skewed and unbounded above, a raw mean is provably misleading) applies identically here; there is no reason to expect BOS/CHoCH forward returns to be better-behaved than pattern forward returns.
  - Group by `(event.value, direction.value)` — i.e. four buckets (CHoCH-bullish, CHoCH-bearish, BOS-bullish, BOS-bearish) — not by `pattern_type`, since `market_structure` doesn't have one. This is the natural split: does a CHoCH's implied reversal actually hold, separately from whether a BOS's implied continuation holds.
  - **A question forward-return-at-fixed-horizon doesn't answer, worth computing separately: does the regime whipsaw?** A CHoCH can show a solidly positive 20-bar return while having *already flipped back* by bar 12 — the AAPL example found while building the earlier chart (CHoCH → BOS → BOS → CHoCH again inside one year, on the same ticker) is a real instance of exactly this. A useful second metric: for each CHoCH, does an opposite-direction CHoCH occur within N bars (a "regime survival" / whipsaw rate) — bounded-formation pattern backtesting doesn't need this because a `PatternMatch`'s lifecycle already terminates (HIT_TARGET/INVALIDATED/EXPIRED); an open-ended regime tracker does.
  - `run_backtest(conn, tickers, timeframe, config)` / CLI entry point, same shape as `evaluator.py`'s (`--all`, `--timeframe`, `--horizons`).
- **This directly settles the earlier open question** (does BOS/CHoCH carry real information at 1D/1W, or is it geometry with no edge) — split the results by `timeframe` and look, rather than reasoning about it from priors the way the original design discussion had to.

## 4. Suggested order

1. Land the 3-line `_FLAT_TRIGGER_KEY` fix in `evaluator.py` (§2). — Done.
2. Run `evaluator.py --all` for daily and weekly, both before this branch's changes (as a sanity check the fix didn't perturb existing pattern types) and after (to get real triple-top/bottom/reversal-123 numbers). — Sanity-checked on AAPL/MSFT/NVDA only (both `triple_top`/`triple_bottom`/`reversal_123` now report a real `throwback_rate` instead of silently falling back to `entry_price`). The full `--all` run has not been done: at the observed ~2s/ticker this is ~3.5 hours per timeframe across the ~6,554-ticker universe in `bars_1d`, explicitly not run as a side effect of landing this code.
3. Build the new `market_structure/backtest.py` module (§3) — the only real new code in this doc. — Done, with tests (`tests/test_market_structure_backtest.py`).
4. Run it, `--all`, both timeframes, and look at the CHoCH/BOS split and the whipsaw rate before drawing any conclusion about whether BOS/CHoCH is worth trusting on daily/weekly bars. — Sanity-checked on AAPL/MSFT/NVDA only (~0.5s/ticker, both timeframes ran cleanly; `bos_*`'s `whipsaw_rate` correctly reports `NaN`, not 0, since BOS never carries a whipsaw verdict). On that 3-ticker sample, `choch_bearish` whipsawed far more often than `choch_bullish` (daily: 69% vs. 48%; weekly: 95% vs. 33%) — suggestive, but N=3 tickers is not the universe-wide read this step calls for. The full `--all` run has not been done, same runtime-cost reasoning as step 2.

Steps 1 and 3 (the actual code) are done. Steps 2 and 4 (the full-universe runs that turn this into a real conclusion about whether these signals are worth trusting) are a deliberate, separate follow-up — run `python -m src.signals.patterns.backtest.evaluator --all --timeframe daily` (and `--timeframe weekly`) and `python -m src.signals.market_structure.backtest --all --timeframe daily` (and `--timeframe weekly`) when ready to spend the several hours of compute this takes.
