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

175 tests passing by the end of the milestone-5 diagonal review arc (#16-#29); exact before/after numbers for every fix above live in `docs/sr_lines_design_notes.md`.
