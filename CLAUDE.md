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
10. **Report distribution shape alongside the mean.** Every module's standard result object also reports hit rate, win/loss magnitude ratio, and skew (definitions and rationale: DESIGN §6.11.1 — read there, not here, so this line and that section can't drift apart). **These three are descriptive only: no CI, no kill criterion, no `N_tests` contribution.** Treating them as three new hypothesis tests per cell is exactly the FDR inflation §6.11.1 exists to rule out. (Added 2026-09-10, forward-looking only — M1/M4/M11 are not backfilled.)

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
- Track B (every tested cell, Tier 1–4, whatever it found) → append a row to `docs/features/moving-averages/EXPERIMENTS.csv` — point estimate, CI, effective N, cost hurdle/verdict, tier, and a one-line outcome. Not a file for negative results only: log the result, not the verdict.
- Track B, Tier 1–3 only → also append an entry to `docs/features/moving-averages/FINDINGS.md`, in its existing per-cell format (hypothesis, why plausible, what was run, the number, effective N, cost at both CI ends, tier, what would change the verdict). Tier 4 needs no `FINDINGS.md` entry — the `EXPERIMENTS.csv` row is the complete record. `DEAD_ENDS.md` is retired (superseded by `EXPERIMENTS.csv`) — don't add to it.

**A null result is a successful outcome.** Do not search for a framing that makes a dead hypothesis look alive.

## MA study workflow

The session-level lifecycle around the two sections above. Fully scoped to this study's own
directory, `docs/features/moving-averages/` — `STATUS.md` included, moved there from the
repo's `docs/` root (see Layout below); its content turned out to be entirely about this
study's own modules, not genuine cross-feature infrastructure. Not a general template other
features in this repo are expected to follow.

**Session start**
- Read the relevant `DESIGN.md` section for the module in play (see top of file).
- Read `STATUS.md` for the current cross-module scoreboard and any open cross-module watch
  items (e.g. the SMA200 watch, the pending whole-grid FDR pass) before assuming a module's
  status. "Cross-module" means across M1/M4/M11/etc. — this study's own modules, not other
  features in the repo.
- Before re-running or extending a hypothesis, grep `EXPERIMENTS.csv` and `FINDINGS.md` for
  its `cell_id`/feature name — a cell already logged there, any outcome, isn't a fresh look.
  `DEAD_ENDS.md` is retired; don't check or add to it.

**Track B: pre-register before running**
- State the four things under "Before running any analysis" above, then write the entry in
  `PREREGISTRATION.md` — module/track, "Promoted from" (which `EXPLORATION_LOG.md` line
  motivated it), hypothesis, scope — and commit it before running the analysis it describes.
- Once a grid entry has been run, its definition there is frozen. A scope change or new
  result is a new, separately dated addendum appended below it (e.g. "### Result (... addendum)"),
  never a silent edit — every existing module entry (M4, M1, M11) follows this.

**After running — logging**
- Follow "After running any analysis" above: Track A appends a dated line to
  `EXPLORATION_LOG.md` (under that session's `##` date header, one line per look, whether or
  not it went anywhere); Track B appends a row to `EXPERIMENTS.csv` and, for Tier 1–3, an
  entry to `FINDINGS.md`. Both logging paths happen every session that runs analysis — neither
  is optional bookkeeping.
- If the result changes a module's tier, headline, or an open cross-module question, also
  update `STATUS.md` in the same session — it's a kept-current scoreboard, not a history.
  (Its own PR-boundary note: a merged module PR isn't necessarily a *tiered* module — check
  both landed before treating the module as done.)

**Heavy exploration**
- Track A is explicitly wide and cheap (DESIGN §1.5) — a good fit for a forked subagent for a
  broad sweep (sectors/eras/deciles/facets) whose intermediate output you won't need again.
  Keep the synthesis — which candidates got promoted, the `EXPLORATION_LOG.md` lines — in the
  main conversation.

**Stop and ask**
- Beyond invariant #1 (holdout): editing a run `PREREGISTRATION.md` entry instead of appending
  a dated addendum; promoting a Track A number into `FINDINGS.md` or a report without a Track B
  pre-registered test behind it; anything that would widen the pre-registered grid after P3
  without a new dated entry.

## Layout

Design and study logs live together under `docs/features/moving-averages/`:

```
docs/features/moving-averages/
  DESIGN.md               reference — the full research design
  PREREGISTRATION.md      frozen hypothesis grid (Track B). Do not edit after P3.
  EXPLORATION_LOG.md      every Track A look, one line each
  EXPERIMENTS.csv         every Track B cell run, one row each — point estimate, CI,
                           effective N, cost, tier, outcome. Whatever it found, not
                           just what killed it. STATUS.md is the cross-module
                           scoreboard built on top of this; PREREGISTRATION.md is the
                           frozen-before-running text per module.
  FINDINGS.md              one entry per Tier 1-3 cell that survived — sibling to
                           DEAD_ENDS.md, same per-entry discipline, for results
                           instead of dead ends.
  DEAD_ENDS.md             retired (superseded by EXPERIMENTS.csv) — a pointer only,
                           don't add to it.
  STATUS.md                cross-module scoreboard, kept current — what's run, what's
                           next, open cross-module (M1/M4/M11/...) watch items. Moved
                           here from docs/STATUS.md (2026-09-11) — it was always
                           MA-study-only content, never genuine cross-feature state.
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
