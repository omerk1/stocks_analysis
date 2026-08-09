# stocks_analysis

Utilities and research notebooks for stock signal analysis: feature engineering on price/volume data, portfolio rebalancing experiments, and automated data retrieval from Polygon.io.

## Quick Start

### Prerequisites

```
Python >= 3.12
TA-Lib C library (macOS: brew install ta-lib)
```

### Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Fetch data

```bash
cp .env.example .env
# Add your Polygon.io API key (free tier: https://polygon.io/) to .env

python -m src.data_processing.fetch_data --tickers AAPL,MSFT --start 2024-01-01 --end 2024-12-31 --source polygon
python -m src.data_processing.fetch_data --tickers AAPL,MSFT --start 2024-01-01 --end 2024-12-31 --source yfinance
```

Bars are stored in `data/raw/market_data.sqlite`, one table per timeframe
(`bars_1d`, `bars_1w`, `bars_1mo`; `bars_1h` reserved for future intraday work),
keyed by `(ticker, timestamp, source)`. Polygon and yfinance data for the same
ticker/date live side by side rather than overwriting each other -- `--source`
defaults to `polygon`. Fetching daily bars also recomputes that source's
weekly/monthly bars from its full stored daily history for that ticker.
Re-running with an overlapping date range is safe — rows are upserted
(`INSERT OR REPLACE`), so the same (ticker, timestamp, source) never duplicates.

The free Polygon tier is end-of-day data only, rate-limited to 5 requests/minute
— there's no intraday (1H/4H) data on that tier; yfinance is the intraday source
(see below) via `get_hourly_bars`, though `bars_1h` storage isn't wired up yet.
Weekly/monthly bars are derived locally from daily bars rather than fetched,
since Polygon's own W/M aggregates cost the same request either way but this
keeps everything reproducible from one daily pull. A period still in progress
(the current week/month, or a day fetched before market close) is stored with
`is_partial=1` and gets overwritten in place once more data arrives — it does
**not** account for market holidays shortening a week/month, only the calendar.

### Cross-check sources

```bash
python -m src.data_processing.validate_sources --ticker AAPL --start 2024-01-01 --end 2024-01-31
```

Compares Polygon vs. yfinance daily closes **already stored** by `fetch_data.py`
for both sources — an on-demand query, not a live re-fetch — and reports any
dates that disagree beyond a tolerance (default 1%). `YFinanceClient` also
exposes `get_hourly_bars` for intraday data Polygon's free tier doesn't
provide — Yahoo retains roughly the trailing 730 days of hourly history.

### Bulk ingestion (the whole market, not just a few tickers)

`fetch_data.py` is for a handful of known tickers. For "give me every stock,"
there's a separate set of scripts, in order:

```bash
# 1. Build the ticker universe (once; refresh occasionally). Polygon is the
#    single source of truth for "which tickers exist" -- both active and
#    delisted common stock, so the universe itself isn't survivorship-biased.
python -m src.data_processing.ticker_universe

# 2. Bulk-ingest daily bars for the whole market from Polygon: one
#    grouped-daily API call per trading day (not per ticker), which is what
#    keeps a full-market 2-year backfill to ~100 minutes under the 5 req/min
#    limit instead of being infeasible.
python -m src.data_processing.bulk_polygon_ingest --start 2024-07-22 --end 2026-07-22

# 3. Same ticker universe, from yfinance -- batched (yf.download supports
#    many tickers per call), since yfinance has no bulk single-call endpoint
#    and no documented rate limit to pace against precisely.
python -m src.data_processing.bulk_yfinance_ingest --start 2024-07-22 --end 2026-07-22

# 4. Derive weekly/monthly bars for every ticker now stored (pure compute,
#    no API calls -- run per source).
python -m src.data_processing.resample_bulk --source polygon
python -m src.data_processing.resample_bulk --source yfinance

# 5. Refresh per-ticker reference metadata (market cap, SIC industry
#    code/description, shares outstanding, employee count) from Polygon.
#    One call per active ticker -- there's no bulk endpoint for this, unlike
#    bars, so this is much slower than step 2 (~5,300 active tickers / 5
#    req/min is on the order of hours, not minutes) and draws from the same
#    shared rate limit -- avoid running it at the same time as step 2.
python -m src.data_processing.bulk_ticker_metadata_ingest

# 6. Refresh point-in-time S&P 500 / Nasdaq-100 index membership. Free,
#    community-maintained sources (not Polygon -- see docs/limitations.md
#    for why), no API key or rate limit involved -- fast, full refresh.
python -m src.data_processing.index_membership
```

All three ingestion scripts are **resumable**: every date (Polygon bars),
ticker (yfinance bars, ticker metadata) gets recorded in a `fetch_jobs` table
as `success` or `failed`. Re-running the same command only retries what's
missing or previously failed — it does not redo completed work, and a failing
item gets a couple of quick retries and then gets flagged and skipped rather
than blocking the rest of the run indefinitely. `PolygonClient` paces every
call (grouped-daily bars, reference-data pagination, ticker metadata) against
the 5 req/min budget itself via a shared rate limiter — this is proactive,
not just reacting to 429s, since the underlying library's own retry backoff
is far too fast to recover from a sustained rate-limit condition on its own.

Index membership (step 6) is different: not rate-limited, not resumable via
`fetch_jobs` — it's a full delete-then-insert replace of the whole table per
index on every run, since it comes from re-downloading/recomputing a
complete dataset rather than paginating an API. Query it point-in-time via
`db.read_index_membership(conn, "sp500", as_of="2020-06-01")` — omit `as_of`
to get every stored interval, including past (non-current) memberships.

## Support/resistance line detection

```bash
python -m src.sr_lines.cli AAPL --preset long_term --out review_AAPL.html \
    [--as-of 2025-07-01] [--top-n 10 | --strength-floor 0.2] \
    [--dedup-threshold 0.6] [--zone-width-atr 0.4] \
    [--diagonals] [--timeframe daily|weekly]
```

Detects horizontal zones and (with `--diagonals`) RANSAC-style diagonal
trendlines, from daily or (`--timeframe weekly`) resampled weekly bars
(`bars_1d`, yfinance only — Polygon/yfinance use different adjustment
conventions, never mixed here), scores each line's strength (touch
quality, duration/density, resilience to failed breaks, role-reversal —
gated by a multiplicative proximity x recency relevance factor so old,
far-from-price levels fade out regardless of how strong their historical
evidence was), and renders an interactive Plotly review chart. With
`--as-of`, detection only ever sees bars up to that date (no lookahead),
while the chart still shows real price action past it, for manual
backtest review. The engine (`engine.detect()`) returns a plain,
JSON-serializable `DetectionResult` with no plotting/DB coupling, so a
future model consumer can use line features directly.

**Status: milestone 5 (diagonals + weekly bars) done, review ongoing**
(see `docs/done.md`, `docs/backlog.md`, and `docs/sr_lines_design_notes.md`
for the full log) — full `as_of()` lookahead test coverage and a
systematic weight-tuning pass on real charts are staged next.

## Project Structure

```
stocks_analysis/
├── src/
│   ├── data_processing/       # Polygon/yfinance clients, SQLite storage, resampling,
│   │                          # rate limiting, and per-ticker (fetch_data.py) + bulk-market
│   │                          # ingestion CLIs
│   ├── feature_engineering/   # Technical indicators (price, momentum, trend, general)
│   ├── sr_lines/               # Support/resistance line detection engine + Plotly review chart
│   ├── models/                # Model training and evaluation
│   └── utils/                 # Config loading and shared utilities
├── configs/
│   └── config.yaml            # Runtime parameters (data paths, etc.)
├── data/
│   ├── raw/                   # Raw fetched data (not in git)
│   ├── processed/             # Cleaned data
│   ├── features/              # Engineered features
│   └── models/                # Trained model artifacts
├── notebooks/                 # Exploration notebooks
├── tests/                     # Unit tests
└── requirements.txt
```

## Feature Engineering

`src/feature_engineering/` contains one module per indicator category, wrapping TA-Lib and pandas-based indicators as plain functions:

- `price_based_indicators` — moving averages, RSI, MACD, Bollinger Bands
- `momentum_indicators` — stochastic oscillator, CCI, rate of change, Williams %R
- `trend_indicators` — ADX, ATR (+ %ATR), parabolic SAR
- `volume_indicators` — on-balance volume, money flow index
- `general_indicators` — simple price ratios (high/open, low/open, close/open, overnight gap)

## Testing

```bash
pytest tests/
```

## Known Limitations

Deliberate simplifications in the data pipeline (no trading-calendar
awareness, `is_partial` heuristics, yfinance intraday caps, etc.) are tracked
in [`docs/limitations.md`](docs/limitations.md).
