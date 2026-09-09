# MA Study — project instructions

Research project analysing moving-average behaviour in equities.
**Full design: `docs/features/moving-averages/DESIGN.md`.** Read the relevant section before starting a module.
This file holds only the invariants that must survive every session.

Code and tests follow this repo's existing module convention (`src/signals/<name>/`,
`tests/test_<name>_*.py` — see `src/signals/gaps/`, `src/signals/relative_strength/`
for the pattern) rather than DESIGN.md §10.1's standalone `ma_study/` tree; see
**Layout** below for the real paths. Reuse existing infrastructure before building new:
`market_common.data` (bar loading/validation), `market_common.indicators` (ATR/RSI/
MACD/OBV wrappers), `src/signals/relative_strength/` (the `rs_rank` momentum control),
`db.read_index_membership` (point-in-time universe).

## What this project is

A **discovery** study, not a strategy build and not a validation exercise.
Two tracks with different rules (DESIGN §1.5):
- **Track A (exploration)** — wide, cheap, no multiple-testing correction, nothing stated as a finding.
- **Track B (confirmation)** — pre-registered, full statistical protocol.

Always state which track you are working in. Never let a Track A number appear as a claim.

## Non-negotiable invariants

These are silent failure modes. Violating them produces plausible, confident, wrong results.

1. **Holdout is locked.** Never read, load, plot, or aggregate data after `2021-12-31` unless the task explicitly says "open holdout". If a task seems to need it, stop and ask. (Revised 2026-09-07 from the original `2016-12-31` — see DESIGN.md §3.3 / §12's development-window-coverage item: the development window shrank to 2010-2021 because that's what the loaded active-ticker data actually supports.)
2. **One-bar lag.** Signal computed on the close of day *t* executes at day *t+1*. Never same-bar. The lag is applied centrally in `src/signals/moving_averages/features/panel.py` — do not bypass it.
3. **No full-sample statistics.** Every z-score, percentile, rank, mean, and standard deviation is rolling/trailing. If you write `.mean()` over a whole column, you have introduced look-ahead.
4. **Never drop delisted tickers.** They carry terminal returns. Dropping them biases every weak-trend bucket upward.
5. **No bare conditional means.** Every conditional statistic is reported as a delta against a matched control (C0/C1/C2, DESIGN §6.1). A number without its control is not a result.
6. **Report effective N.** Distinct event *dates* alongside raw row count, in every table. Events cluster; 40,000 rows on 55 dates is 55 observations.
7. **Log scale for slopes.** `slope_log_k` only. Percentage and price-unit slopes are not comparable across tickers.
8. **Costs annotated.** Any claim implying trading carries `signals_per_year × cost` next to the gross number.
9. **Derived features preserve their inputs' missingness.** Comparison operators (`>`, `<`, `==`) return `False` on NaN where arithmetic propagates it — a boolean feature built from a comparison (not arithmetic) needs an explicit `.where(input.notna())`/`.mask(input.isna())` and a test asserting NA across the input's undefined region, not just correct values elsewhere. (Found 2026-09-09: `above_sma_200` read its own 200-day MA warmup as "below" instead of undefined, on ~6.6% of the panel — see `tests/test_moving_averages_features.py::test_above_is_na_during_ma_warmup_not_false` for the enforced case.)

## Before running any analysis

State, in this order, before writing analysis code:
- which module (M0–M17) and which track
- the hypothesis
- the **kill criterion** — the pre-committed condition under which you declare it dead
- the control tier you are using and why

If you cannot state a kill criterion, the task is not ready to run.

## After running any analysis

- Argue against your own result. What confound would produce this number if the effect were not real?
- Check the plateau rule (DESIGN §6.7): do neighbouring parameters agree? A lone bright pixel is noise — say so.
- Track A → append to `docs/features/moving-averages/EXPLORATION_LOG.md`, one line, whether or not it went anywhere.
- Negative results → `docs/features/moving-averages/DEAD_ENDS.md` with the number that killed it and the effective N.

**A null result is a successful outcome.** Do not search for a framing that makes a dead hypothesis look alive.

## Layout

Design and study logs live together under `docs/features/moving-averages/`:

```
docs/features/moving-averages/
  DESIGN.md               reference — the full research design
  PREREGISTRATION.md      frozen hypothesis grid (Track B). Do not edit after P3.
  EXPLORATION_LOG.md      every Track A look, one line each
  DEAD_ENDS.md            killed hypotheses + evidence
```

Code follows this repo's existing per-module convention, not DESIGN.md §10.1's
standalone `ma_study/` tree literally — §10.1's stages (data/features/events/
labels/stats/modules) map onto this real layout:

```
src/signals/moving_averages/
  config.py               universe tiers, lookback grid, lag-matching config
  data.py                 PIT universe assembly on top of market_common.data / db
  features/
    ma.py                   families, lag-matching helpers
    distance.py              pct/atr/z/pctile normalisations
    slope.py
    ribbon.py
    regime.py                 ER, ADX, vol, breadth
    panel.py                  -> cached parquet; one-bar lag applied here, centrally
  events/
    definitions.py           every event type, parameterised
    build_events.py          -> event table
  labels/
    forward_returns.py
    path_metrics.py           MFE/MAE
    barriers.py
  stats/
    controls.py               C0/C1/C2 matching
    inference.py               NW, block bootstrap, date clustering
    multiple_testing.py        BH, Reality Check, SPA, DSR
    plateau.py                 neighbourhood stability
  modules/
    m01_state.py … m15_synthesis.py
  cli.py

tests/test_moving_averages_*.py   golden fixtures, look-ahead shift test, hygiene tests
```

## Commands

No Makefile yet — run directly:

```bash
pytest tests/test_moving_averages_*.py                     # unit + hygiene + look-ahead tests. Must pass before any analysis is trusted.
python -m src.signals.moving_averages.cli build-panel      # rebuild feature panel (slow, cached)
python -m src.signals.moving_averages.cli validate-synth   # synthetic planted-effect check — see below
```

## The synthetic check

`validate-synth` runs the pipeline against (a) generated data with a planted effect of known
size, and (b) generated data with no effect. The pipeline must recover (a) at the right magnitude
and report nothing on (b).

**If this is failing or absent, no result from this repo means anything.** Fix it first.

## Style

- Vectorise across the panel; never loop per ticker.
- float32 for features.
- Every module reads from cache; no module recomputes the panel.
- Plots before tests. Look at the distribution before you summarise it.
