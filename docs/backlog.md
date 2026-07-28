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

## In progress / open questions

- Full active-universe yfinance deep-history backfill (`--start 2010-01-01`) — not yet run; #10 and #11 were prep work for it.
- Whether/how to source quarterly financials — still gated behind an undecided Polygon paid tier.
- The full-market Polygon 2yr price backfill + weekly/monthly resample is complete and live in the DB (separate from the above yfinance deep-history work).
