"""Thin client for Tiingo's end-of-day API -- used for index members that
delisted before yfinance or Polygon could serve them (survivorship-free
history, `bulk_tiingo_ingest.py`).

Free tier: 50 requests/hour, 1,000/day, 500 distinct symbols/month, personal
use. Both request limits are paced proactively (`RateLimiter`), so a run
sleeps rather than collecting 429s. The monthly symbol cap isn't paced: once
it's hit, every request for a new symbol raises `TiingoError` until the month
turns over.

Tiingo serves one listing per symbol: the latest holder. Its public ticker
list (`supported_tickers`) shows every holder with its date range (EMC: EMC
Corp 1988-2016, then an ETF from 2023), but `/tiingo/daily/EMC` only answers
for the ETF. Older holders of a reused symbol aren't reachable on this tier.

Each price row carries raw OHLCV, fully adjusted OHLCV (splits + dividends)
and the day's `splitFactor` (on the ex-date, e.g. 4.0 for AAPL 2020-08-31).
`to_bars` turns that into this repo's two price bases.
"""

from __future__ import annotations

import io
import os
import time
import zipfile

import pandas as pd
import requests

from src.foundation.data_processing.rate_limiter import RateLimiter

ENV_KEY = "TIINGO_API_KEY"
_BASE_URL = "https://api.tiingo.com/tiingo/daily"
SUPPORTED_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"

_HOURLY = RateLimiter(max_calls=50, period_seconds=3600)
_DAILY = RateLimiter(max_calls=1000, period_seconds=86400)
# On a 429, wait out (part of) the hourly window and retry, a few times.
_MAX_RATE_LIMITED_WAITS = 6
RATE_LIMITED_WAIT_SECONDS = 600


class TiingoError(requests.RequestException):
    """Tiingo answered with an error message instead of data (a quota)."""


class TiingoClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None,
                 rate_limited_wait_seconds: float = RATE_LIMITED_WAIT_SECONDS):
        self._rate_limited_wait_seconds = rate_limited_wait_seconds
        api_key = api_key or os.getenv(ENV_KEY)
        if not api_key:
            raise ValueError(f"No Tiingo API key found. Set the {ENV_KEY} env var or pass api_key explicitly.")
        self._api_key = api_key
        self._session = session or requests.Session()

    def metadata(self, ticker: str) -> dict | None:
        """{ticker, name, startDate, endDate, exchangeCode, ...} for the
        symbol's current holder, or None if Tiingo doesn't know the symbol."""
        return self._get(f"{_BASE_URL}/{ticker}")

    def daily_prices(self, ticker: str, start: str, end: str) -> pd.DataFrame | None:
        """Tiingo's raw daily rows for [start, end] (inclusive), indexed by
        date. None if the symbol is unknown; empty if it has no rows there."""
        rows = self._get(f"{_BASE_URL}/{ticker}/prices", {"startDate": start, "endDate": end})
        if rows is None:
            return None
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date")).dt.tz_localize(None), name="timestamp")
        return frame

    def _get(self, url: str, params: dict | None = None):
        for attempt in range(_MAX_RATE_LIMITED_WAITS + 1):
            _HOURLY.wait()
            _DAILY.wait()
            response = self._session.get(
                url, params={**(params or {}), "format": "json"},
                headers={"Authorization": f"Token {self._api_key}"}, timeout=60,
            )
            # The local limiters only see this process's calls; requests from
            # another run in the same hour still count against the key.
            if response.status_code != 429 or attempt == _MAX_RATE_LIMITED_WAITS:
                break
            time.sleep(self._rate_limited_wait_seconds)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        # Quota errors come back as 200 with {"detail": ...} instead of data
        # (e.g. the free tier's 500 distinct symbols per month).
        if isinstance(body, dict) and set(body) == {"detail"}:
            raise TiingoError(body["detail"])
        return body


def to_bars(prices: pd.DataFrame, split_only: bool) -> pd.DataFrame:
    """Tiingo rows -> `bars_1d` columns on one price basis.

    - `split_only=False`: Tiingo's adjusted OHLCV (splits + dividends) -- the
      `total_return` basis, matching yfinance's default bars (AAPL 2020-08-28:
      Tiingo 120.965 vs yfinance 120.956).
    - `split_only=True`: raw prices divided by every *later* split factor --
      the `traded` basis (AAPL 2020-08-28: 499.23 / 4 = 124.81, yfinance's
      split-only close). Volume is multiplied by the same factor.

    Days with zero volume are dropped: Tiingo fills a flat placeholder bar on
    a delisting day after trading stopped (FRX 2014-07-01: O=H=L=C, volume 0),
    and an S&P 500 member never genuinely trades zero shares.
    """
    traded = prices[prices["volume"] > 0]
    if split_only:
        # Factor for day t = product of splitFactor over days strictly after t.
        later = prices["splitFactor"][::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
        later = later.loc[traded.index]
        bars = traded[["open", "high", "low", "close"]].div(later, axis=0)
        bars["volume"] = traded["volume"] * later
    else:
        bars = traded[["adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume"]].copy()
        bars.columns = ["open", "high", "low", "close", "volume"]
    bars["is_partial"] = 0
    return bars


def to_splits(prices: pd.DataFrame) -> pd.DataFrame:
    """Tiingo's split factors as `splits` table rows (execution_date,
    split_from, split_to, ratio), same convention as the yfinance source:
    ratio 4.0 for a 4-for-1, 0.05 for a 1-for-20. Tiingo also books some
    spin-offs as a split (T 2022-04-11, 1.324), as yfinance does."""
    factors = prices.loc[prices["splitFactor"] != 1.0, "splitFactor"].astype(float)
    return pd.DataFrame({
        "execution_date": factors.index,
        "split_from": [1.0 if r >= 1 else 1.0 / r for r in factors],
        "split_to": [r if r >= 1 else 1.0 for r in factors],
        "ratio": factors.to_numpy(),
    })


def supported_tickers(url: str = SUPPORTED_TICKERS_URL) -> pd.DataFrame:
    """Tiingo's public ticker list (no key, no request budget): one row per
    listing -- ticker, exchange, assetType, priceCurrency, startDate, endDate.
    A reused symbol has one row per holder."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            return pd.read_csv(f, keep_default_na=False, na_values=[""])
