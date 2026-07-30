# Backlog

Concise log of completed and in-progress work, oldest first. Append new entries as work completes rather than rewriting history.

## Done

1. **#1** — Restructured project layout, set up dev environment (venv, requirements.txt).
2. **#2** — Polygon.io + yfinance data retrieval, SQLite storage.
3. **#3** — Reviewed `feature_engineering` indicators, fixed a bug, added missing ones.
4. **#4** — Converted `feature_engineering` static-method classes to plain modules.
5. **#5** — Made storage source-aware: Polygon and yfinance stored side by side (source is part of the primary key).
6. **#6** — Resumable bulk ingestion for the whole market, both sources (rate-limited/retry-bounded for Polygon, batched for yfinance).
7. **#7** — Per-ticker reference metadata table (market cap, sector, shares outstanding) from Polygon.
8. **#8** — Point-in-time S&P 500 / Nasdaq-100 index membership tracking, from free community datasets (not Polygon's paid add-on — cost tradeoff documented in `limitations.md`).
9. **#9** — Documented the Polygon/yfinance dividend-adjustment mismatch (different, both-correct conventions, cross-validated against a third vendor).
10. **#10** — Fixed a yfinance bulk-ingest resumability bug (job_type collision across different date ranges) + added ticker-list scoping.
11. **#11** — Reject rows with impossible OHLC values at the storage layer; purged 4,002 already-stored bad rows found in a real yfinance deep-history pull.
12. Full active-universe yfinance deep-history backfill (`--start 2010-01-01`, ~5,300 active tickers, 2010-2026) + OHLC validation caught and dropped bad rows live during the run.
13. **Support/resistance line detection module** (`src/sr_lines/`), milestone-4 checkpoint reached: data layer + validation gate, ATR-adaptive pivot detection, horizontal candidate clustering, touch/wick-fake/body-fake/break event classification, weighted scoring, lifecycle (state/dedup/top-N), Plotly review chart + CLI. 110 tests passing, real smoke test on AAPL. Stopping here for review per the module's own spec before diagonals/`as_of`/weight-tuning.

## In progress / open questions

- Whether/how to source quarterly financials — still gated behind an undecided Polygon paid tier.
- **`sr_lines` next steps (milestones 5-7, pending review of the milestone-4 checkpoint)**: diagonal (RANSAC-style, log-price) candidates; full `as_of()` lookahead test coverage; a weight-tuning pass. One concrete finding from the real AAPL run worth resolving in that pass: every line that has ever flipped role gets the full `role_reversal` weight (1.0), which currently lets flipped lines dominate the top-N regardless of their other component scores (e.g. a never-broken line with real touch-quality signal scored *lower* than several flipped lines with almost no signal elsewhere) — may need dampening, a cap, or a different formulation.
