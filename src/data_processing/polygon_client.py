import os
from datetime import date, datetime

import pandas as pd
from polygon import RESTClient

ENV_KEY = "POLYGON_API_KEY"


class PolygonClient:
    """Thin wrapper around polygon-api-client for pulling historical OHLCV bars.

    Targets the free tier: end-of-day data only, 5 requests/minute. The
    underlying RESTClient already retries on 429s, so basic rate limiting
    is handled for you.
    """

    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv(ENV_KEY)
        if not api_key:
            raise ValueError(
                f"No Polygon API key found. Set the {ENV_KEY} env var or pass api_key explicitly."
            )
        self._client = RESTClient(api_key=api_key)

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
