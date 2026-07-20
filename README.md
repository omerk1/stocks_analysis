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

python -m src.data_processing.fetch_data --tickers AAPL,MSFT --start 2024-01-01 --end 2024-12-31
```

Daily OHLCV bars are saved to `data/raw/polygon/{ticker}.csv`. Re-running with an
overlapping date range is safe — rows are merged and de-duplicated by date.
The free Polygon tier is end-of-day data only, rate-limited to 5 requests/minute.

## Project Structure

```
stocks_analysis/
├── src/
│   ├── data_processing/       # Polygon.io client + fetch_data.py CLI -> data/raw/polygon/
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

`src/feature_engineering/` contains static-method classes wrapping TA-Lib and pandas-based indicators:

- `PriceBasedIndicators` — moving averages, RSI, MACD, Bollinger Bands
- `MomentumIndicators` — stochastic oscillator, CCI
- `TrendIndicators` — ADX, ATR, parabolic SAR
- `GeneralIndicators` — simple price ratios (high/open, low/open, close/open)

## Testing

```bash
pytest tests/
```
