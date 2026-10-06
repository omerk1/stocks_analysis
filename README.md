# stocks_analysis

Research codebase for US equities: a local market-data store, technical signal
modules (gaps, AVWAP, S/R lines, patterns, breadth, relative strength, ...), a
completed moving-average study, and the modeling phase now under way — a
setup-scoring model built on a triple-barrier target.

## Setup

Requires Python 3.12+ and the TA-Lib C library (macOS: `brew install ta-lib`).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the keys below
```

| Key | Used for | Free tier |
|---|---|---|
| `POLYGON_API_KEY` | ticker universe, reference metadata | 5 requests/min |
| `FRED_API_KEY` | macro series | yes |
| `TIINGO_API_KEY` | history of delisted index members | 50 requests/hour |
| `EODHD_API_KEY` | delisted members Tiingo lacks (not wired up yet) | 20 requests/day |

## Data

Everything lives in two SQLite files under `data/` (not in git):
`data/raw/market_data.sqlite` (bars, tickers, index membership, share counts,
splits, sectors, macro) and `data/derived/analysis.sqlite` (signal-module output).

**Two price bases.** Daily bars are stored twice, and every module declares
which one it uses (`src/foundation/market_common/price_basis.py`, reasoning in
`docs/decisions/price-basis.md`):

- `total_return` — adjusted for splits and dividends; for anything measuring returns.
- `traded` — adjusted for splits only; for price levels and market caps.

**Sources.** yfinance is the main price source. Tiingo supplies former index
members yfinance no longer serves; only the modeling dataset reads them.
Polygon provides the ticker universe and metadata, SEC EDGAR the share counts
and industry codes, FRED the macro series. Index membership (S&P 500,
Nasdaq-100) is point-in-time.

Common refreshes:

```bash
python -m src.foundation.data_processing.bulk_yfinance_ingest --start 1970-01-01 --end 2026-12-31 --job-type <new>   # total_return
python -m src.foundation.data_processing.bulk_yfinance_ingest --split-only --incremental                             # traded
python -m src.foundation.data_processing.index_membership
python -m src.foundation.data_processing.fetch_macro --series all
```

Bulk jobs are resumable: progress is kept in the `fetch_jobs` table, and a rerun
only retries what's missing or failed. Other ingests (ticker universe, share
counts, splits, sectors, renames, Tiingo) are in `src/foundation/data_processing/`,
each with its usage in the module docstring.

## Signal modules

One package per concept under `src/signals/`, each with its own config,
compute, store and CLI, writing to `analysis.sqlite`:

```bash
python -m src.signals.gaps.cli AAPL           # or --all; also avwap, fibonacci, divergences,
                                              # volume_profile, patterns, sr_lines
python -m src.signals.relative_strength.cli --index sp500
python -m src.signals.breadth.cli --index sp500 --weighting cap
```

`sr_lines` also renders an interactive Plotly review chart (`--out chart.html`).

## Research

- **Moving-average study** — complete. `docs/features/moving-averages/`
  (`STATUS.md` for the results).
- **Modeling** — in progress, `src/models/`: point-in-time dataset with a
  locked holdout (data after 2021-12-31), barrier labels, baselines, learners,
  validation gates. Start with `docs/modeling/IDEAS.md` and
  `VALIDATION_HARNESS.md`.

## Docs

| | |
|---|---|
| `docs/done.md` | numbered log of completed work |
| `docs/backlog.md` | open items and known data issues |
| `docs/limitations.md` | deliberate simplifications in the pipeline |
| `docs/decisions/` | decision records |
| `docs/features/` | design notes per signal module |
| `CLAUDE.md` | working rules (MA study invariants, parallel-agent workflow) |

## Layout

```
src/
  foundation/
    data_processing/     clients, SQLite storage, ingestion CLIs
    market_common/       bar loading, price bases, indicators, pivots, anchors
    feature_engineering/ TA-Lib indicator wrappers
  signals/               one detection module per concept
  models/                modeling harness
  analysis/              one-off research scripts
configs/config.yaml      data paths and runtime settings
tests/
```

## Tests

```bash
pytest tests/   # ~1,500 tests, about 15 minutes
```
