# stocks_analysis

Utilities and research notebooks for stock signal analysis: feature engineering on price/volume data, portfolio rebalancing experiments, and (soon) automated data retrieval.

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

## Project Structure

```
stocks_analysis/
├── src/
│   ├── data_processing/       # Data retrieval (Polygon/yfinance -> local storage)
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
