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

## Project Structure

```
stocks_analysis/
├── src/
│   ├── data_processing/       # Polygon/yfinance clients, SQLite storage, resampling, fetch_data.py CLI
│   ├── feature_engineering/   # Technical indicators (price, momentum, trend, general)
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
