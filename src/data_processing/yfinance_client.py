import pandas as pd
import yfinance as yf

_COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


class YFinanceClient:
    """Secondary data source: cross-checking Polygon and covering lower
    timeframes Polygon's free tier doesn't offer (intraday bars)."""

    def get_daily_bars(self, ticker: str, start, end) -> pd.DataFrame:
        return self._fetch(ticker, start, end, interval="1d", keep_time=False)

    def get_hourly_bars(self, ticker: str, start, end) -> pd.DataFrame:
        """Fetch hourly bars. Yahoo only retains ~730 days of 1h history --
        requesting further back silently returns a truncated range, it does
        not raise."""
        return self._fetch(ticker, start, end, interval="1h", keep_time=True)

    @staticmethod
    def _fetch(ticker: str, start, end, interval: str, keep_time: bool) -> pd.DataFrame:
        raw = yf.Ticker(ticker).history(start=start, end=end, interval=interval)
        if raw.empty:
            columns = ["open", "high", "low", "close", "volume"]
            return pd.DataFrame(columns=columns).rename_axis("timestamp")

        df = raw.rename(columns=_COLUMN_MAP)[["open", "high", "low", "close", "volume"]]

        idx = df.index.tz_convert("UTC")
        if not keep_time:
            idx = idx.normalize()
        df.index = idx.tz_localize(None)
        df.index.name = "timestamp"
        return df
