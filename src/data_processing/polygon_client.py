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

    def get_ticker_details(self, ticker: str) -> dict:
        """Fetch reference metadata for a single ticker: market cap, SIC
        industry code/description, shares outstanding, employee count, etc.

        Unlike bars/tickers, there's no bulk equivalent for this -- one call
        per ticker, drawing from the same shared rate limit as every other
        method on this client.
        """
        self._rate_limiter.wait()
        details = self._client.get_ticker_details(ticker)
        return {
            "ticker": details.ticker,
            "market_cap": details.market_cap,
            "sic_code": details.sic_code,
            "sic_description": details.sic_description,
            "share_class_shares_outstanding": details.share_class_shares_outstanding,
            "weighted_shares_outstanding": details.weighted_shares_outstanding,
            "total_employees": details.total_employees,
            "primary_exchange": details.primary_exchange,
            "list_date": details.list_date,
        }

    def get_splits(self, ticker: str) -> pd.DataFrame:
        """Fetch `ticker`'s full historical stock-split record: execution
        date plus the from/to factors of the split ratio (e.g. split_from=1,
        split_to=4 for a 4-for-1 forward split; split_from=10, split_to=1
        for a 1-for-10 reverse split). Confirmed live on the free tier --
        unlike financials, this reference endpoint isn't paid-tier gated.
        Real ground truth, not inferred from other data: e.g. AAPL's real
        2020-08-31 4-for-1 split comes back with that exact execution date,
        unlike `shares_outstanding`'s own raw share-count jump for the same
        split, which only shows up ~7 weeks later due to filing lag.

        Returns a DataFrame sorted ascending by execution_date with columns:
        execution_date (Timestamp), split_from, split_to, ratio (split_to /
        split_from -- the real-share-count multiplier callers like
        `market_cap.py` need directly). One call regardless of how many
        splits a ticker has (like `get_ticker_details` -- no bulk
        equivalent), rather than page-by-page like
        `list_common_stock_tickers`: a ticker accumulating enough splits to
        span multiple response pages (default page size 10) in practice
        doesn't happen on real data.
        """
        self._rate_limiter.wait()
        splits = self._client.list_splits(ticker=ticker)
        rows = [
            {
                "execution_date": pd.Timestamp(s.execution_date),
                "split_from": s.split_from,
                "split_to": s.split_to,
                "ratio": s.split_to / s.split_from,
            }
            for s in splits
        ]
        df = pd.DataFrame(rows, columns=["execution_date", "split_from", "split_to", "ratio"])
        return df.sort_values("execution_date").reset_index(drop=True)

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
