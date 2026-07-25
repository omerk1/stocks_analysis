import itertools
import os
from datetime import date, datetime

import pandas as pd
from polygon import RESTClient

from src.data_processing.rate_limiter import RateLimiter

ENV_KEY = "POLYGON_API_KEY"

# Free ("Stocks Basic") tier: 5 requests/minute, shared across every endpoint
# on the key -- grouped-daily, per-ticker aggs, and reference/tickers
# pagination all draw from the same budget (confirmed by tripping a 429
# mixing calls across these during development).
_DEFAULT_MAX_CALLS_PER_MINUTE = 5


class PolygonClient:
    """Thin wrapper around polygon-api-client for pulling historical OHLCV bars.

    Targets the free tier: end-of-day data only, 2 years of history, 5
    requests/minute. The underlying RESTClient's own retry-on-429 uses a
    sub-second backoff (tuned for transient blips, not a hard per-minute
    budget) -- nowhere near enough to recover from sustained rate-limit
    pressure, so every method here paces itself proactively via a shared
    RateLimiter instead of relying on that.
    """

    def __init__(self, api_key: str | None = None, rate_limiter: RateLimiter | None = None):
        api_key = api_key or os.getenv(ENV_KEY)
        if not api_key:
            raise ValueError(
                f"No Polygon API key found. Set the {ENV_KEY} env var or pass api_key explicitly."
            )
        self._client = RESTClient(api_key=api_key)
        self._rate_limiter = rate_limiter or RateLimiter(
            max_calls=_DEFAULT_MAX_CALLS_PER_MINUTE, period_seconds=60
        )

    def get_daily_bars(
        self,
        ticker: str,
        start: str | date | datetime,
        end: str | date | datetime,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for `ticker` between `start` and `end` (inclusive).

        Returns a DataFrame indexed by `date` with columns:
        open, high, low, close, volume, vwap, transactions.
        """
        self._rate_limiter.wait()
        aggs = self._client.get_aggs(
            ticker=ticker,
            multiplier=1,
            timespan="day",
            from_=start,
            to=end,
            adjusted=adjusted,
            sort="asc",
            limit=50000,
        )

        rows = [
            {
                "date": pd.Timestamp(agg.timestamp, unit="ms", tz="UTC").normalize().tz_localize(None),
                "open": agg.open,
                "high": agg.high,
                "low": agg.low,
                "close": agg.close,
                "volume": agg.volume,
                "vwap": agg.vwap,
                "transactions": agg.transactions,
            }
            for agg in aggs
        ]

        df = pd.DataFrame(
            rows, columns=["date", "open", "high", "low", "close", "volume", "vwap", "transactions"]
        )
        return df.set_index("date")

    def get_grouped_daily_bars(self, day: str | date | datetime, adjusted: bool = True) -> pd.DataFrame:
        """Fetch OHLCV for every ticker that traded on `day`, in a single API
        call covering the entire market (~10-12k tickers). This is what makes
        a full-market backfill tractable under the 5 req/min limit -- one
        request per trading day rather than one per ticker.

        Returns a plain DataFrame (not indexed by date -- `day` is a single
        fixed value here) with columns: ticker, open, high, low, close, volume.
        Non-trading days (weekends, holidays) come back empty, not an error.
        """
        self._rate_limiter.wait()
        aggs = self._client.get_grouped_daily_aggs(day, adjusted=adjusted)
        rows = [
            {
                "ticker": agg.ticker,
                "open": agg.open,
                "high": agg.high,
                "low": agg.low,
                "close": agg.close,
                "volume": agg.volume,
            }
            for agg in aggs
        ]
        return pd.DataFrame(rows, columns=["ticker", "open", "high", "low", "close", "volume"])

    def list_common_stock_tickers(self, active: bool, page_size: int = 1000) -> pd.DataFrame:
        """Page through Polygon's reference tickers for common stock (type=CS).

        `active=False` returns delisted tickers too (with a `delisted_utc`
        date) -- deliberately supported so a ticker universe built from this
        isn't survivorship-biased.

        Rate-limited per page, not per ticker: each page is its own HTTP
        request under the hood, so `page_size` items are pulled from the
        underlying generator per `wait()` call (page_size == the page size
        requested from the API, so pulling exactly that many items exhausts
        one page without triggering the next page's request early).
        """
        rows = []
        generator = self._client.list_tickers(
            market="stocks", type="CS", active=active, limit=page_size
        )
        while True:
            self._rate_limiter.wait()
            page = list(itertools.islice(generator, page_size))
            if not page:
                break
            rows.extend(
                {
                    "ticker": t.ticker,
                    "name": getattr(t, "name", None),
                    "type": getattr(t, "type", None),
                    "active": active,
                    "delisted_utc": getattr(t, "delisted_utc", None),
                }
                for t in page
            )
            if len(page) < page_size:
                break
        return pd.DataFrame(rows, columns=["ticker", "name", "type", "active", "delisted_utc"])
