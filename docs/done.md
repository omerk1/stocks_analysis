# Done

Completed work, oldest first. Each entry is a one-line pointer, not the
full story — see `docs/sr_lines_design_notes.md` for the narrative behind
any sr_lines-related entry (root cause, real numbers, what was rejected
before landing on the fix). `docs/backlog.md` tracks what's still open.

Entries are plain bullets tagged with a stable `#N`, not a markdown
ordered list, so the number never silently reflows when an entry is
inserted or reworded (that's why `#14.5` exists: an item that landed
between `#14` and `#15` chronologically). Numbers are permanent
references — other entries and the design notes cite them (e.g. "Done
#22") — so don't renumber on edit, only append new ones at the end.

- **#1** — Project layout + dev environment setup (venv, requirements.txt).
- **#2** — Polygon.io + yfinance data retrieval, SQLite storage.
- **#3** — Reviewed `feature_engineering` indicators, fixed a bug, added missing ones.
- **#4** — Converted `feature_engineering` static-method classes to plain modules.
- **#5** — Storage made source-aware (Polygon/yfinance side by side, source in the primary key).
- **#6** — Resumable bulk ingestion for the whole market, both sources.
- **#7** — Per-ticker reference metadata table (market cap, sector, shares outstanding) from Polygon.
- **#8** — Point-in-time S&P 500/Nasdaq-100 membership tracking from free datasets (cost tradeoff vs. Polygon's paid add-on — see `limitations.md`).
- **#9** — Documented the Polygon/yfinance dividend-adjustment mismatch (different, both-correct conventions).
- **#10** — Fixed a yfinance bulk-ingest resumability bug + added ticker-list scoping.
- **#11** — Reject impossible OHLC values at the storage layer; purged 4,002 already-stored bad rows.
- **#12** — Full active-universe yfinance deep-history backfill (~5,300 tickers, 2010-2026).
- **#13** — **sr_lines milestone-4 checkpoint**: data layer, ATR-adaptive pivot detection, horizontal clustering, event classification, weighted scoring, lifecycle, Plotly chart + CLI.
- **#14** — **sr_lines review round** (AAPL/T/GME/KO): rendering fixes, backtesting/display split, proportional `role_reversal`, ATR%-of-price clustering, dedup rescoring bug. 133 tests passing.
- **#14.5** — `role_reversal` recalibrated to be quality-weighted, not a raw confirmation count.
- **#15** — **Milestone 5: diagonal (RANSAC-style) trendlines** implemented — candidates, event/scoring generalization, `diagonal_penalty`, lifecycle/plotting/CLI wiring. 151 tests passing.
- **#16, #17, #21, #28, #29** — Diagonal candidate generation & dedup: five real-chart-review fixes (pivot-overlap → price-proximity dedup, event/geometry consistency on merge, `first_touch`-on-merge, near-flat/horizontal duplication, candidate-cap fairness).
- **#18, #19** — `duration_density`'s diagonal-bias fix + volume weighting integrated into scoring.
- **#20, #22, #23, #24, #25** — The "hovering" bug and its full resolution arc: `in_play_gate` split out as its own gate, `regime_start` added, a box-rendering overreach corrected, evidence components regime-scoped, event-count saturation windowed.
- **#26, #27** — Chart marker rendering fixes: crossing-bar position, strength-based opacity/size fade.
- **#30** — Weekly-bar detection mechanism, plus two `duration_density` fixes (horizontal/diagonal symmetry, sparse-span density factor) found while reviewing its real output. 181 tests passing.
- **#31** — Historical shares-outstanding ingestion, new `shares_outstanding` table (real time series, unlike `ticker_metadata`'s single overwritten row) backfilled from yfinance's `get_shares_full` — Polygon's equivalent endpoint is `NOT_AUTHORIZED` on our current plan. Raw counts are NOT split-adjusted (confirmed: a ~4x jump lands exactly on AAPL's real 2020-08-31 split date) — a market-cap calc needs to reconcile that against `bars_1d`'s adjusted price convention first, not yet done. Resumable bulk backfill script mirrors `bulk_ticker_metadata_ingest.py`. Schema applied to the real project DB; full-universe backfill not yet run. 193 tests passing.
- **#32** — **`market_common` extraction** (Step 0 of a planned gaps/divergences/fibonacci/avwap effort): pulled `sr_lines`'s timeframe-agnostic data-loading/validation, ATR-ZigZag pivot detection, and shared dataclasses out into a new `src/market_common/` package sr_lines now delegates to (unchanged public signatures, zero call-site changes in `engine.py`/`cli.py`). Indicators (ATR/RSI/MACD/OBV) wrap `feature_engineering`'s existing talib-backed functions rather than reimplementing them. Pivot detection generalized to any single series (RSI, MACD histogram, OBV) or true OHLC high/low, via a pluggable threshold function. New `Pivot.value`/`threshold_at_pivot` fields with read-only `price`/`atr_at_pivot` aliases keep every existing sr_lines call site (candidates.py's clustering/diagonal-fit math) working unchanged. New `data/derived/analysis.sqlite` (separate from the raw price DB) with a shared `runs` table for the modules to follow. Verified: full pre-refactor suite (193 tests) passes unchanged, plus 30 new tests for market_common's own API; real-data cross-check re-confirmed the weekly-resample exact-match property through the new code path. 223 tests passing.

- **#33** — **Four new TA modules built on `market_common`** (gaps, divergences, fibonacci, avwap), each with its own config dataclass, detection logic, SQLite lifecycle tracking in `data/derived/analysis.sqlite`, Plotly chart, and CLI (`python -m src.<module>.cli TICKER|--all --timeframe daily|weekly|both [--as-of] [--plot]`). Built in parallel (four agents, disjoint directories) against a shared, pre-agreed spec. `gaps/`: classic 2-bar + 3-bar FVG detection, ATR-sized, forward-walked fill lifecycle (open/partial/soft_closed/closed). `divergences/`: RSI/MACD-hist/OBV price-divergence detection via paired price/indicator pivots, weighted strength score. `fibonacci/`: multi-scale (2/4/8x ATR) swing detection with cross-scale dedup, retracement/extension levels (linear or log), top-K weighted set ranking, origin-cross invalidation. `avwap/`: pure `anchored_vwap()` computation (zero-lookahead, NaN before anchor) plus anchor discovery (ath/atl/52w high-low/cycle high-low) with same-date dedup, cap-trimming, and staleness tracking. All four share the `runs` table and `ON CONFLICT DO UPDATE` upsert pattern (new to this repo — needed to preserve a row's uuid4 `id` across re-runs without an extra SELECT). 278 tests passing (223 baseline + 55 new). Not yet done: real-universe backfill (all four only run against ad-hoc tickers so far), and everything in the spec's explicit backlog (gap/fib/sr_lines confluence, hidden/triple-pivot divergences, AVWAP stdev bands, a backtest iterator API, etc. — see spec).

- **#34** — Persisted the raw, unclipped inputs behind two existing derived values instead of only their blended/final form. `divergences` now stores `duration_bars`/`price_move_atr`/`indicator_gap_raw` — the three components `strength` caps to [0,1] and weights together before storing (an 8.35x-ATR move and a 50x-ATR move both read `strength=1.0`); `strength` itself is unchanged, still the only field `plotting.py` consumes. `gaps` now stores `bars_to_first_touch`/`bars_to_soft_closed`/`bars_to_closed` alongside their existing date fields, so a bar-count duration doesn't require a re-join against `bars_1d`. Both verified against real data: divergences' new columns hand-matched for a real GME divergence (`price_move_atr=8.35`, `indicator_gap_raw=3.41`); gaps' new columns cross-checked against 542 date↔bar-offset pairs across 200 real NKE gaps, 0 mismatches. 278 tests passing.

175 tests passing by the end of the milestone-5 diagonal review arc (#16-#29); exact before/after numbers for every fix above live in `docs/sr_lines_design_notes.md`.
