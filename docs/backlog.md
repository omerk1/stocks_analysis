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
13. **Support/resistance line detection module** (`src/sr_lines/`), milestone-4 checkpoint reached: data layer + validation gate, ATR-adaptive pivot detection, horizontal candidate clustering, touch/wick-fake/body-fake/break event classification, weighted scoring, lifecycle (state/dedup/top-N), Plotly review chart + CLI.
14. **`sr_lines` review round** (real-chart visual review on AAPL/T/GME/KO, milestone-4 checkpoint still): filled-rectangle zone rendering; backtesting-vs-display split (`--as-of` freezes detection, chart still shows real price past it); zone extents always render to the reference date regardless of state; decay freezes on death but not for FLIPPED lines; proportional (not binary) `role_reversal`; time-decayed U&R (body-fake) `resilience` with a grace floor; `proximity` turned into a multiplicative `proximity x recency` relevance gate instead of an additive term (fixes old, far-from-price levels scoring competitively on stale evidence); gap-aware zone dedup (not overlap-only); clustering thresholded on ATR% of price instead of raw dollar ATR (scale-invariant across tickers/price levels); `--dedup-threshold`/`--zone-width-atr` CLI knobs for tuning by eye. Pre-merge review then found and fixed a real bug (`dedup_lines` merged events into a survivor without rescoring state/counts/strength from the union) and extended flip-confirmation to accept a resolved body-fake, not just touch/wick-fake, consistent with the U&R framing; both `lifecycle.py` and `scoring.py` now share one `flip_status.py` predicate instead of two independently-drifting checks. 133 tests passing. Full log: `docs/sr_lines_design_notes.md`. Stopping here for another review pass before diagonals/`as_of`/weight-tuning.

## In progress / open questions

- Whether/how to source quarterly financials — still gated behind an undecided Polygon paid tier.
- **`sr_lines` milestone 5 in progress** (`feature/sr-lines-diagonals-and-scoring`, branched after the milestone-4 PR merged): `role_reversal` recalibrated to be quality-weighted (reaction-strength/reclaim-speed x recency decay), not just a raw confirmation count — the count-based fix from the milestone-4 round turned out not to be enough; see `docs/sr_lines_design_notes.md` for the AAPL evidence and the fix. Diagonal (RANSAC-style, log-price) trendlines are next. Full `as_of()` lookahead test coverage and a systematic weight-tuning pass remain milestones 6-7. One open calibration question carried forward: `resilience`'s cap (1.0) can still be hit by a zone with enough events even after the time-decay fix — see `docs/sr_lines_design_notes.md`.
